from __future__ import annotations

import unittest

from fetchers.models import MediaStream
from media.ranker import rank_streams, recommendations


class MediaRankerTests(unittest.TestCase):
    def setUp(self):
        self.streams = [
            MediaStream('https://example/low.mp4', 'video', 'mp4', 'h264', 854, 480, 900_000, 20_000_000, '480P'),
            MediaStream('https://example/hevc.mp4', 'video', 'mp4', 'hevc', 1920, 1080, 3_000_000, 80_000_000, '1080P'),
            MediaStream('https://example/webm', 'video', 'webm', 'av1', 1920, 1080, 2_000_000, 55_000_000, '1080P'),
        ]

    def test_quality_prefers_high_resolution_stream(self):
        self.assertEqual(rank_streams(self.streams, 'best_quality')[0].stream.height, 1080)

    def test_compatibility_prefers_mp4_over_webm(self):
        self.assertEqual(rank_streams(self.streams, 'best_compatibility')[0].stream.container, 'mp4')

    def test_recommendations_expose_three_strategies(self):
        self.assertEqual(set(recommendations(self.streams)), {'best_quality', 'best_compatibility', 'smallest_size'})

