import unittest
import subprocess
import tempfile
from pathlib import Path

import httpx

from app import FetchRequest, app
from douyin_fetch import choose_media_capture, merge_streams_to_mp4, validate_output_request


class HomePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_renders_fetch_form(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('<form', text)
        self.assertIn('name="link"', text)
        self.assertIn('name="outputPath"', text)
        self.assertIn('name="outputType"', text)
        self.assertIn('开始解析', text)

    async def test_home_page_renders_streamdock_landing_content(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('StreamDock', text)
        self.assertIn('从各处而来，归于本地。', text)
        self.assertIn('支持平台', text)
        self.assertIn('抖音', text)
        self.assertIn('快手', text)
        self.assertIn('B站', text)

    async def test_home_page_uses_reference_poster_layout(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('class="page"', text)
        self.assertIn('class="hero"', text)
        self.assertIn('class="bottom"', text)
        self.assertIn('class="panel"', text)
        self.assertIn('id="topDownloadBtn"', text)
        self.assertIn('id="mainDownloadBtn"', text)
        self.assertNotIn('streamdock-reference.png', text)

    def test_frontend_script_supports_poster_hotspot_interactions(self):
        script = Path('static/app.js').read_text(encoding='utf-8')
        self.assertIn('scrollTriggers', script)
        self.assertIn('scrollIntoView', script)
        self.assertIn('prefers-reduced-motion', script)


class MediaSelectionTests(unittest.TestCase):
    def test_prefers_video_when_both_audio_and_video_urls_exist(self):
        capture = choose_media_capture(
            candidate_video_url='https://example.com/media-video-avc1/?id=1',
            candidate_audio_url='https://example.com/media-audio-und-mp4a/?id=1',
            dom_video_sources=['blob:https://www.douyin.com/abc'],
            final_url='https://www.douyin.com/video/123',
            title='demo - 抖音',
        )
        self.assertEqual(capture['media_kind'], 'video')
        self.assertEqual(capture['media_url'], 'https://example.com/media-video-avc1/?id=1')
        self.assertEqual(capture['audio_url'], 'https://example.com/media-audio-und-mp4a/?id=1')

    def test_rejects_mp4_output_when_only_audio_stream_exists(self):
        with self.assertRaisesRegex(ValueError, 'Only audio stream found'):
            validate_output_request(media_kind='audio', output_type='mp4')

    def test_merge_streams_to_mp4_produces_audio_and_video_tracks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file = temp_path / 'video.mp4'
            audio_file = temp_path / 'audio.m4a'
            merged_file = temp_path / 'merged.mp4'

            subprocess.run(
                [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'color=c=black:s=320x240:d=1',
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    str(video_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'sine=frequency=1000:duration=1',
                    '-c:a', 'aac',
                    str(audio_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            merge_streams_to_mp4(video_file, audio_file, merged_file)

            probe = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'stream=codec_type',
                    '-of', 'csv=p=0',
                    str(merged_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            codecs = {line.strip() for line in probe.stdout.splitlines() if line.strip()}
            self.assertEqual(codecs, {'video', 'audio'})


class OutputTypeValidationTests(unittest.TestCase):
    def test_fetch_request_accepts_new_formats(self):
        for output_type in ['wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm']:
            payload = FetchRequest(link='https://v.douyin.com/demo/', outputPath='/tmp/demo', outputType=output_type)
            self.assertEqual(payload.outputType, output_type)


class HomePageOptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_lists_new_output_options(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')
        text = response.text
        for marker in ['value="wav"', 'value="flac"', 'value="aac"', 'value="ogg"', 'value="opus"', 'value="mkv"', 'value="mov"', 'value="webm"']:
            self.assertIn(marker, text)


class ApiResponseShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_api_returns_platform_field_on_success(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run') as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = '[douyin-fetch] platform: douyin\n[douyin-fetch] output file: /tmp/demo.mp3\n'
                mocked_run.return_value.stderr = ''
                response = await client.post('/api/fetch', json={
                    'link': 'https://v.douyin.com/demo/',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp3',
                })
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['platform'], 'douyin')
        self.assertEqual(data['outputPath'], '/tmp/demo.mp3')

    async def test_fetch_api_returns_platform_field_for_new_platforms(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        for platform_name in ['xiaohongshu', 'weibo', 'channels']:
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                with patch('app.subprocess.run') as mocked_run:
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stdout = (
                        f'[douyin-fetch] platform: {platform_name}\n'
                        '[douyin-fetch] output file: /tmp/demo.mp4\n'
                    )
                    mocked_run.return_value.stderr = ''
                    response = await client.post('/api/fetch', json={
                        'link': 'https://example.com/demo',
                        'outputPath': '/tmp/out',
                        'outputType': 'mp4',
                    })
            data = response.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['platform'], platform_name)
            self.assertEqual(data['outputPath'], '/tmp/demo.mp4')

    async def test_fetch_api_returns_timeout_error_when_cli_hangs(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='demo', timeout=180)):
                response = await client.post('/api/fetch', json={
                    'link': 'https://example.com/demo',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp4',
                })
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('timeout', data['error'].lower())


if __name__ == '__main__':
    unittest.main()
