import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime_checks import deep_media_quality, partial_output_path, prepare_output_directory, validate_media_output


class RuntimeChecksTests(unittest.TestCase):
    def test_prepare_output_directory_creates_and_checks_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'new-output'
            result = prepare_output_directory(output, minimum_free_bytes=1)
            self.assertTrue(output.is_dir())
            self.assertTrue(result['writable'])
            self.assertGreater(result['freeBytes'], 0)

    def test_partial_output_path_keeps_real_extension(self):
        path = partial_output_path(Path('/tmp/demo.mp4'))
        self.assertEqual(path.name, '.demo.streamdock-part.mp4')

    def test_validate_media_output_reports_streams_and_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fixture.mp4'
            subprocess.run(
                [
                    'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=0.3',
                    '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=0.3', '-shortest',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(output),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result = validate_media_output(output, expected_kind='video')
            self.assertTrue(result['valid'])
            self.assertTrue(result['hasVideo'])
            self.assertTrue(result['hasAudio'])
            self.assertEqual((result['width'], result['height']), (320, 240))

            deep = deep_media_quality(output, timeout_seconds=30)
            self.assertIn('deepQualityScore', deep)
            self.assertIn('blackIntervals', deep)
            self.assertIn('silenceIntervals', deep)
            self.assertIsInstance(deep['warnings'], list)


if __name__ == '__main__':
    unittest.main()
