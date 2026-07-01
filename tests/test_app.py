import unittest
import subprocess
import tempfile
from pathlib import Path

import httpx

from app import app
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


if __name__ == '__main__':
    unittest.main()
