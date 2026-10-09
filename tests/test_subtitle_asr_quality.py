import math
import unittest
from fetchers.subtitle_asr import SubtitleQualityError, validate_asr_cues
from fetchers.subtitle_ocr import OcrSubtitleCue


class AsrQualityTests(unittest.TestCase):
    def test_rejects_actual_damaged_transcript(self):
        with self.assertRaisesRegex(SubtitleQualityError, '损坏字符'):
            validate_asr_cues([OcrSubtitleCue(14.56, 16.7, '展芯之日和之前的栗蓝�eee前霄材充热')])

    def test_valid_mixed_language_is_not_rewritten(self):
        validate_asr_cues([OcrSubtitleCue(0, 1, '中文 English GPT-6 😀\n第二行')])

    def test_invalid_time_and_controls_are_rejected(self):
        for start, end, text in [(-1, 1, '字幕'), (0, math.nan, '字幕'), (0, math.inf, '字幕'), (1, 1, '字幕'), (0, 1, '字幕\x00')]:
            with self.subTest(start=start, end=end, text=text), self.assertRaises(SubtitleQualityError):
                validate_asr_cues([OcrSubtitleCue(start, end, text)])
