import unittest

from subtitles.service import export_subtitles, parse_subtitles, validate_cues


class SubtitleServiceTests(unittest.TestCase):
    def test_srt_round_trip_preserves_multiline_text_and_timing(self):
        document = parse_subtitles('1\n00:00:01,250 --> 00:00:03,500\n第一行\n第二行\n', filename='demo.srt')
        self.assertEqual(document.cues[0].start, 1.25)
        self.assertEqual(document.cues[0].text, '第一行\n第二行')
        exported = export_subtitles([cue.to_dict() for cue in document.cues], 'srt')
        self.assertIn('00:00:01,250 --> 00:00:03,500', exported)

    def test_vtt_parser_accepts_minute_timestamp_and_exports_header(self):
        document = parse_subtitles('WEBVTT\n\n00:01.000 --> 00:04.000\nhello\n', filename='demo.vtt')
        self.assertEqual(document.cues[0].end, 4.0)
        self.assertTrue(export_subtitles([document.cues[0].to_dict()], 'vtt').startswith('WEBVTT'))

    def test_txt_import_builds_editable_timeline(self):
        document = parse_subtitles('第一句\n第二句\n', filename='demo.txt')
        self.assertEqual(len(document.cues), 2)
        self.assertEqual(document.cues[1].start, 3.0)

    def test_invalid_cue_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '结束时间'):
            validate_cues([{'start': 2, 'end': 1, 'text': 'bad'}])


if __name__ == '__main__':
    unittest.main()
