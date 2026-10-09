import os
import unittest

import httpx

os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''
from app import app


class SubtitleApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_simplify_preserves_timing_multiline_and_emoji(self):
        transport = httpx.ASGITransport(app=app)
        rows = [{'start': 5.9, 'end': 8.2, 'text': '他得將就一輩子了\n你沒有考慮過男生吧 😀 English 123'}]
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/subtitles/simplify', json={'cues': rows})
            converted = response.json()['cues']
            exported = await client.post('/api/subtitles/export', json={'format': 'srt', 'cues': converted})
        self.assertEqual(converted, [{'start': 5.9, 'end': 8.2, 'text': '他得将就一辈子了\n你没有考虑过男生吧 😀 English 123'}])
        self.assertIn('00:00:05,900 --> 00:00:08,200', exported.text)
        self.assertIn('你没有考虑过男生吧', exported.text)

    async def test_workbench_page_and_assets_are_registered(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/subtitles')
        self.assertEqual(response.status_code, 200)
        self.assertIn('字幕时间轴', response.text)
        self.assertIn('把字幕文件拖到这里', response.text)
        self.assertIn('/static/js/subtitles.js', response.text)

    async def test_import_and_export_srt(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            imported = await client.post('/api/subtitles/import', files={'file': ('demo.srt', b'1\n00:00:01,000 --> 00:00:02,000\nhello\n', 'text/plain')})
            document = imported.json()['document']
            exported = await client.post('/api/subtitles/export', json={'filename': 'demo.srt', 'format': 'vtt', 'cues': document['cues']})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(document['cueCount'], 1)
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.text.startswith('WEBVTT'))

    async def test_import_rejects_unsupported_extension(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/subtitles/import', files={'file': ('demo.exe', b'bad', 'application/octet-stream')})
        self.assertEqual(response.status_code, 400)

    async def test_vtt_and_txt_interfaces_return_editable_cues(self):
        cases = {
            'demo.vtt': b'WEBVTT\n\n00:00.000 --> 00:02.000\nhello\n',
            'demo.txt': '第一句\n第二句\n'.encode(),
        }
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            for filename, content in cases.items():
                imported = await client.post('/api/subtitles/import', files={'file': (filename, content, 'text/plain')})
                self.assertEqual(imported.status_code, 200, filename)
                document = imported.json()['document']
                self.assertGreater(document['cueCount'], 0)
                exported = await client.post('/api/subtitles/export', json={'filename': filename, 'format': filename.rsplit('.', 1)[1], 'cues': document['cues']})
                self.assertEqual(exported.status_code, 200, filename)


if __name__ == '__main__':
    unittest.main()
