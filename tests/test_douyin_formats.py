import subprocess
import tempfile
import unittest
from pathlib import Path

from fetchers.exporters import OUTPUT_FORMATS as SHARED_OUTPUT_FORMATS
from fetchers.exporters import export_media as shared_export_media
from douyin_fetch import (
    OUTPUT_FORMATS,
    enrich_capture_if_missing_audio,
    export_media,
    get_output_format_spec,
    is_audio_output,
    is_video_output,
)


class OutputFormatRegistryTests(unittest.TestCase):
    def test_registry_contains_all_expected_formats(self):
        self.assertEqual(
            set(OUTPUT_FORMATS),
            {'m4a', 'mp3', 'mp4', 'wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm'},
        )

    def test_audio_and_video_helpers_classify_formats(self):
        self.assertTrue(is_audio_output('wav'))
        self.assertTrue(is_audio_output('opus'))
        self.assertTrue(is_video_output('mkv'))
        self.assertTrue(is_video_output('webm'))
        self.assertFalse(is_video_output('flac'))

    def test_webm_spec_requires_transcode(self):
        spec = get_output_format_spec('webm')
        self.assertEqual(spec.kind, 'video')
        self.assertEqual(spec.mode, 'transcode')
        self.assertTrue(spec.needs_video_stream)
        self.assertTrue(spec.needs_audio_stream)


class AudioExportTests(unittest.TestCase):
    def _make_audio_fixture(self, temp_path: Path) -> Path:
        audio_file = temp_path / 'audio.m4a'
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
        return audio_file

    def test_wav_export_creates_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_file = self._make_audio_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=None,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='wav',
            )
            self.assertEqual(final_path.suffix, '.wav')
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(final_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(probe.stdout.strip(), 'audio')

    def test_opus_export_creates_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_file = self._make_audio_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=None,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='opus',
            )
            self.assertEqual(final_path.suffix, '.opus')

    def test_ogg_export_creates_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_file = self._make_audio_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=None,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='ogg',
            )
            self.assertEqual(final_path.suffix, '.ogg')


class VideoExportTests(unittest.TestCase):
    def _make_av_fixture(self, temp_path: Path) -> tuple[Path, Path]:
        video_file = temp_path / 'video.mp4'
        audio_file = temp_path / 'audio.m4a'
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=1', '-c:a', 'aac', str(audio_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return video_file, audio_file

    def test_mkv_export_contains_audio_and_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file, audio_file = self._make_av_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=video_file,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='mkv',
            )
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(final_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual({line.strip() for line in probe.stdout.splitlines() if line.strip()}, {'video', 'audio'})

    def test_webm_export_contains_audio_and_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file, audio_file = self._make_av_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=video_file,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='webm',
            )
            self.assertEqual(final_path.suffix, '.webm')


class CaptureEnrichmentTests(unittest.TestCase):
    def test_retries_capture_when_video_missing_audio_url(self):
        initial_capture = {
            'media_kind': 'video',
            'media_url': 'https://example.com/video-only.mp4',
            'video_url': 'https://example.com/video-only.mp4',
            'audio_url': None,
            'title': 'demo - 抖音',
            'final_url': 'https://www.douyin.com/video/1',
        }
        retried_capture = {
            **initial_capture,
            'audio_url': 'https://example.com/audio.m4a',
        }
        calls: list[tuple[str, int]] = []

        def fake_no_login(link: str, wait_ms: int):
            calls.append((link, wait_ms))
            return retried_capture

        updated_capture, updated_strategy = enrich_capture_if_missing_audio(
            initial_capture,
            link='https://v.douyin.com/demo/',
            strategy='no-login',
            no_login_capturer=fake_no_login,
            cookie_capturer=None,
        )

        self.assertEqual(updated_capture['audio_url'], 'https://example.com/audio.m4a')
        self.assertEqual(updated_strategy, 'no-login')
        self.assertEqual(calls, [('https://v.douyin.com/demo/', 15000)])


class SharedExporterTests(unittest.TestCase):
    def test_shared_exporter_exposes_all_formats(self):
        self.assertEqual(
            set(SHARED_OUTPUT_FORMATS),
            {'m4a', 'mp3', 'mp4', 'wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm'},
        )

    def test_old_export_media_symbol_uses_shared_exporter(self):
        self.assertIs(shared_export_media, export_media)


if __name__ == '__main__':
    unittest.main()
