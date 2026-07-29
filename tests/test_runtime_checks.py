import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_checks import augmented_path, deep_media_quality, environment_health, network_subprocess_environment, partial_output_path, prepare_output_directory, resolve_tool_path, validate_media_output


class RuntimeChecksTests(unittest.TestCase):
    def test_environment_health_reports_full_local_capability_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = environment_health(tmp)

        keys = {item['key'] for item in result['checks']}
        self.assertTrue({'python', 'ffmpeg', 'ffprobe', 'playwright', 'subtitle_asr', 'subtitle_ocr', 'pdf_engine', 'output'}.issubset(keys))
        self.assertEqual(result['summary']['total'], len(result['checks']))
        self.assertGreaterEqual(result['summary']['requiredTotal'], 4)

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

    def test_augmented_path_adds_common_macos_tool_dirs(self):
        path = augmented_path('/usr/bin:/bin')
        self.assertIn('/opt/homebrew/bin', path.split(':'))
        self.assertIn('/usr/local/bin', path.split(':'))

    def test_resolve_tool_path_finds_homebrew_tools_when_path_is_minimal(self):
        ffmpeg = resolve_tool_path('ffmpeg')
        if Path('/opt/homebrew/bin/ffmpeg').exists():
            self.assertEqual(ffmpeg, '/opt/homebrew/bin/ffmpeg')
        else:
            self.assertTrue(ffmpeg == 'ffmpeg' or Path(ffmpeg).exists())

    def test_network_subprocess_environment_inherits_macos_system_proxy_when_launchd_only_has_no_proxy(self):
        base_env = {
            'PATH': '/usr/bin:/bin',
            'NO_PROXY': '127.0.0.1,localhost',
            'no_proxy': '127.0.0.1,localhost',
        }
        with patch(
            'runtime_checks.discover_system_proxies',
            return_value={'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'},
        ):
            result = network_subprocess_environment(base_env)

        self.assertEqual(result['HTTP_PROXY'], 'http://127.0.0.1:7890')
        self.assertEqual(result['HTTPS_PROXY'], 'http://127.0.0.1:7890')
        self.assertEqual(result['http_proxy'], 'http://127.0.0.1:7890')
        self.assertEqual(result['https_proxy'], 'http://127.0.0.1:7890')
        self.assertEqual(result['NO_PROXY'], '127.0.0.1,localhost')

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
