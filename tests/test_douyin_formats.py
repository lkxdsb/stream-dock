import subprocess
import tempfile
import unittest
from pathlib import Path

from douyin_fetch import (
    OUTPUT_FORMATS,
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


if __name__ == '__main__':
    unittest.main()
