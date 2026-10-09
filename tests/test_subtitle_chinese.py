import unittest
from subtitles.chinese import normalize_chinese_asr, to_simplified


class ChineseSubtitleTests(unittest.TestCase):
    def test_phrase_conversion_keeps_other_content(self):
        self.assertEqual(to_simplified('考慮過這樣的條件嗎？\nEnglish 😀 123'), '考虑过这样的条件吗？\nEnglish 😀 123')

    def test_only_chinese_recognition_is_normalized(self):
        text = '那是不是他得將就你了'
        for language in ('zh', 'zh-CN', 'zh_TW', 'Chinese'):
            self.assertEqual(normalize_chinese_asr(text, language), '那是不是他得将就你了')
        for language in ('en', 'ja', None):
            self.assertEqual(normalize_chinese_asr(text, language), text)
