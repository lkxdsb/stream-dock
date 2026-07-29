import os
import tempfile
import unittest
from pathlib import Path

import httpx

os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''
from app import MAX_SUBTITLE_FILE_BYTES, app, task_store
from subtitles.service import parse_subtitles
from tasks.models import TaskKind, TaskStatus


class SubtitleAdversarialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_export_rejects_negative_and_extreme_timestamps(self):
        for start, end in [(-1, 1), (0, 604801), (999999999999, 1000000000000)]:
            response = await self.client.post('/api/subtitles/export', json={
                'filename': 'demo.srt', 'format': 'srt', 'cues': [{'start': start, 'end': end, 'text': 'x'}],
            })
            self.assertIn(response.status_code, {400, 422})

    async def test_unicode_and_header_injection_filename_is_safe(self):
        response = await self.client.post('/api/subtitles/export', json={
            'filename': '中文字幕\r\nX-Evil: yes.srt', 'format': 'srt',
            'cues': [{'start': 0, 'end': 1, 'text': '<img src=x onerror=alert(1)>'}],
        })
        self.assertEqual(response.status_code, 200)
        disposition = response.headers['content-disposition']
        self.assertNotIn('\r', disposition)
        self.assertNotIn('\n', disposition)
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertNotIn('X-Evil:', disposition)

    async def test_oversized_upload_and_excessive_cue_array_are_rejected(self):
        oversized = await self.client.post('/api/subtitles/import', files={
            'file': ('large.txt', b'a' * (MAX_SUBTITLE_FILE_BYTES + 1), 'text/plain'),
        })
        self.assertEqual(oversized.status_code, 400)
        cues = [{'start': i, 'end': i + .5, 'text': 'x'} for i in range(5001)]
        excessive = await self.client.post('/api/subtitles/export', json={'filename': 'x', 'format': 'srt', 'cues': cues})
        self.assertEqual(excessive.status_code, 422)

    async def test_export_schema_rejects_non_text_and_non_finite_values(self):
        payloads = [
            {'start': 0, 'end': 1, 'text': {'html': '<script>alert(1)</script>'}},
            {'start': 'NaN', 'end': 1, 'text': 'x'},
            {'start': 0, 'end': 'Infinity', 'text': 'x'},
        ]
        for cue in payloads:
            response = await self.client.post('/api/subtitles/export', json={'filename': 'x', 'format': 'srt', 'cues': [cue]})
            self.assertEqual(response.status_code, 422)

    async def test_task_asset_endpoint_denies_unrelated_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / 'allowed.srt'
            denied = Path(tmp) / 'denied.srt'
            allowed.write_text('allowed', encoding='utf-8')
            denied.write_text('denied', encoding='utf-8')
            task = task_store.create(TaskKind.MEDIA, 'asset boundary', {})
            task_store.update(task.id, status=TaskStatus.COMPLETED, result={'assets': {'subtitles': [str(allowed)]}})
            try:
                response = await self.client.get(f'/api/media/tasks/{task.id}/asset', params={'path': str(denied)})
            finally:
                task_store.delete(task.id)
        self.assertEqual(response.status_code, 403)

    async def test_utf16_bom_is_supported_and_invalid_encoding_is_rejected(self):
        content = '1\n00:00:00,000 --> 00:00:01,000\n中文\n'.encode('utf-16')
        valid = await self.client.post('/api/subtitles/import', files={'file': ('utf16.srt', content, 'text/plain')})
        invalid = await self.client.post('/api/subtitles/import', files={'file': ('bad.srt', b'\xff', 'text/plain')})
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()['document']['cues'][0]['text'], '中文')
        self.assertEqual(invalid.status_code, 400)

    def test_invalid_timestamp_components_and_embedded_nul_are_handled(self):
        with self.assertRaisesRegex(ValueError, '分和秒'):
            parse_subtitles('1\n00:99:00,000 --> 00:99:01,000\nbad\n', filename='bad.srt')
        document = parse_subtitles('1\n00:00:00,000 --> 00:00:01,000\na\x00b\n', filename='nul.srt')
        self.assertEqual(document.cues[0].text, 'ab')

    def test_txt_cue_limit_is_enforced_before_building_unbounded_timeline(self):
        text = '\n'.join('x' for _ in range(5001))
        with self.assertRaisesRegex(ValueError, '5000'):
            parse_subtitles(text, filename='many.txt')


if __name__ == '__main__':
    unittest.main()
