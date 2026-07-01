import unittest

from douyin_fetch import (
    OUTPUT_FORMATS,
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


if __name__ == '__main__':
    unittest.main()
