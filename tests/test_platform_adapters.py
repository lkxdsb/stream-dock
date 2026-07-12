import unittest
import tempfile
from unittest.mock import patch

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.bilibili import BilibiliAdapter
from fetchers.adapters.channels import ChannelsAdapter
from fetchers.adapters.common import classify_browser_response_candidate
from fetchers.adapters.douyin import DouyinAdapter
from fetchers.adapters.kuaishou import KuaishouAdapter
from fetchers.adapters.weibo import WeiboAdapter
from fetchers.adapters.xiaohongshu import XiaohongshuAdapter
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream, ResolvedMediaSelection


class ModelContractTests(unittest.TestCase):
    def test_media_stream_records_quality_fields(self):
        stream = MediaStream(
            url="https://example.com/video.mp4",
            stream_type="video",
            container="mp4",
            codec="h264",
            width=1080,
            height=1920,
            bitrate=1467000,
            filesize=None,
            quality_label="1080p",
        )
        self.assertEqual(stream.stream_type, "video")
        self.assertEqual(stream.quality_label, "1080p")

    def test_fetch_result_keeps_preferred_streams(self):
        video = MediaStream(url="https://example.com/video.mp4", stream_type="video")
        audio = MediaStream(url="https://example.com/audio.m4a", stream_type="audio")
        result = MediaFetchResult(
            platform="douyin",
            content_type="video",
            title="demo",
            source_url="https://v.douyin.com/demo/",
            final_url="https://www.douyin.com/video/1",
            cover_url=None,
            author=None,
            video_streams=[video],
            audio_streams=[audio],
            preferred_video=video,
            preferred_audio=audio,
            metadata={},
        )
        self.assertEqual(result.platform, "douyin")
        self.assertEqual(result.preferred_audio.url, "https://example.com/audio.m4a")

    def test_export_request_and_selection_are_simple_value_models(self):
        request = ExportRequest(output_path="/tmp/out", output_type="mp4")
        video = MediaStream(url="https://example.com/video.mp4", stream_type="video")
        selection = ResolvedMediaSelection(
            video_stream=video,
            audio_stream=None,
            title="demo",
            output_type="mp4",
        )
        self.assertEqual(request.output_type, "mp4")
        self.assertEqual(selection.title, "demo")

    def test_base_adapter_exposes_required_methods(self):
        methods = {name for name in dir(BasePlatformAdapter) if not name.startswith("_")}
        self.assertTrue({"platform_name", "can_handle", "normalize_link", "fetch_media"}.issubset(methods))


class BrowserCaptureHelperTests(unittest.TestCase):
    def test_browser_response_candidate_ignores_image_response_even_if_url_contains_video_host(self):
        self.assertIsNone(
            classify_browser_response_candidate(
                "https://finder.video.qq.com/251/20304/stodownload?picformat=200",
                resource_type="image",
                content_type="image/jpg",
            )
        )

    def test_browser_response_candidate_accepts_video_content_type_without_extension(self):
        self.assertEqual(
            classify_browser_response_candidate(
                "https://example.com/download?id=123",
                resource_type="media",
                content_type="video/mp4",
            ),
            "video",
        )


class RegistryTests(unittest.TestCase):
    def test_registry_exposes_all_platform_adapters(self):
        from fetchers.registry import get_registered_adapters

        adapter_names = [adapter.platform_name for adapter in get_registered_adapters()]
        self.assertEqual(
            adapter_names,
            [
                "douyin",
                "kuaishou",
                "bilibili",
                "xiaohongshu",
                "weibo",
                "channels",
                "youtube",
                "tiktok",
                "twitter_x",
            ],
        )

    def test_pipeline_detects_platform_by_url(self):
        from fetchers.pipeline import detect_platform_adapter

        self.assertEqual(detect_platform_adapter("https://v.douyin.com/abcd/").platform_name, "douyin")
        self.assertEqual(
            detect_platform_adapter("https://www.kuaishou.com/short-video/123").platform_name,
            "kuaishou",
        )
        self.assertEqual(
            detect_platform_adapter("https://www.bilibili.com/video/BV1xx411c7mD").platform_name,
            "bilibili",
        )
        self.assertEqual(
            detect_platform_adapter("https://www.xiaohongshu.com/explore/66abc123").platform_name,
            "xiaohongshu",
        )
        self.assertEqual(detect_platform_adapter("https://weibo.com/tv/show/1034:abc").platform_name, "weibo")
        self.assertEqual(
            detect_platform_adapter("https://channels.weixin.qq.com/web/pages/feed?feedid=xyz").platform_name,
            "channels",
        )
        self.assertEqual(
            detect_platform_adapter("https://www.youtube.com/watch?v=dQw4w9WgXcQ").platform_name,
            "youtube",
        )
        self.assertEqual(
            detect_platform_adapter("https://www.tiktok.com/@demo/video/7350000000000000001").platform_name,
            "tiktok",
        )
        self.assertEqual(
            detect_platform_adapter("https://x.com/demo/status/1800000000000000000").platform_name,
            "twitter_x",
        )


class DouyinAdapterTests(unittest.TestCase):
    def test_douyin_adapter_recognizes_douyin_links(self):
        adapter = DouyinAdapter()
        self.assertTrue(adapter.can_handle("https://v.douyin.com/abcd/"))
        self.assertTrue(adapter.can_handle("https://www.douyin.com/video/123"))
        self.assertFalse(adapter.can_handle("https://www.bilibili.com/video/BV1xx411c7mD"))
        self.assertFalse(adapter.can_handle("https://evil.example.com/?redirect=https://www.douyin.com/video/123"))

    def test_douyin_adapter_builds_quality_streams_from_aweme_detail(self):
        adapter = DouyinAdapter()
        capture = {
            "final_url": "https://www.douyin.com/video/7444687640944790844",
            "title": "抖音测试视频 - 抖音",
            "media_url": "https://cdn.example.com/dy-540.mp4",
            "media_kind": "video",
            "video_url": "https://cdn.example.com/dy-540.mp4",
            "audio_url": "https://cdn.example.com/dy-audio.m4a",
            "aweme_detail": {
                "video": {
                    "bit_rate": [
                        {
                            "gear_name": "normal_540_0",
                            "bit_rate": 927132,
                            "is_h265": 0,
                            "is_bytevc1": 0,
                            "play_addr": {
                                "width": 576,
                                "height": 1024,
                                "data_size": 15432940,
                                "url_list": ["https://cdn.example.com/dy-540.mp4"],
                            },
                        },
                        {
                            "gear_name": "normal_1080_0",
                            "bit_rate": 1509869,
                            "is_h265": 0,
                            "is_bytevc1": 0,
                            "play_addr": {
                                "width": 1080,
                                "height": 1920,
                                "data_size": 25133105,
                                "url_list": ["https://cdn.example.com/dy-1080.mp4"],
                            },
                        },
                    ]
                }
            },
        }

        with patch("fetchers.adapters.douyin.capture_media_no_login", return_value=capture):
            with patch("fetchers.adapters.douyin.enrich_capture_if_missing_audio", return_value=(capture, "no-login")):
                result = adapter.fetch_media("https://v.douyin.com/demo/")

        self.assertEqual(len(result.video_streams), 2)
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/dy-1080.mp4")
        self.assertEqual(result.preferred_video.quality_label, "normal_1080_0")
        self.assertEqual(result.video_streams[0].stream_type, "video")
        self.assertEqual(result.audio_streams[0].url, "https://cdn.example.com/dy-audio.m4a")

    def test_pipeline_can_select_requested_video_quality(self):
        from pathlib import Path

        from fetchers.pipeline import run_pipeline

        class FakeAdapter:
            platform_name = "douyin"

            def can_handle(self, raw_link: str) -> bool:
                return True

            def normalize_link(self, raw_link: str) -> str:
                return "normalized-link"

            def fetch_media(self, normalized_link: str) -> MediaFetchResult:
                video_540 = MediaStream(
                    url="https://cdn.example.com/dy-540.mp4",
                    stream_type="video",
                    container="mp4",
                    width=576,
                    height=1024,
                    bitrate=927132,
                    quality_label="normal_540_0",
                )
                video_1080 = MediaStream(
                    url="https://cdn.example.com/dy-1080.mp4",
                    stream_type="video",
                    container="mp4",
                    width=1080,
                    height=1920,
                    bitrate=1509869,
                    quality_label="normal_1080_0",
                )
                audio = MediaStream(url="https://cdn.example.com/dy-audio.m4a", stream_type="audio")
                return MediaFetchResult(
                    platform="douyin",
                    content_type="video",
                    title="demo",
                    source_url="https://v.douyin.com/demo/",
                    final_url="https://www.douyin.com/video/1",
                    cover_url=None,
                    author=None,
                    video_streams=[video_540, video_1080],
                    audio_streams=[audio],
                    preferred_video=video_1080,
                    preferred_audio=audio,
                    metadata={},
                )

        with tempfile.TemporaryDirectory() as output_dir:
            with patch("fetchers.pipeline.download_media") as mocked_download:
                with patch("fetchers.pipeline.export_media", return_value=Path(output_dir) / "demo.mp4"), \
                     patch("fetchers.pipeline.validate_media_output", return_value={'valid': True}), \
                     patch("fetchers.pipeline.commit_partial"):
                    mocked_download.side_effect = [
                        Path("/tmp/source.mp4"),
                        Path("/tmp/audio.m4a"),
                    ]
                    result = run_pipeline(
                        raw_link="https://v.douyin.com/demo/",
                        export_request=ExportRequest(output_path=output_dir, output_type="mp4"),
                        adapter=FakeAdapter(),
                        video_quality="normal_540_0",
                    )

        self.assertEqual(result["platform"], "douyin")
        self.assertEqual(mocked_download.call_args_list[0].args[0], "https://cdn.example.com/dy-540.mp4")

    def test_pipeline_runs_with_injected_fake_adapter(self):
        from fetchers.pipeline import run_pipeline

        class FakeAdapter:
            platform_name = "douyin"

            def can_handle(self, raw_link: str) -> bool:
                return True

            def normalize_link(self, raw_link: str) -> str:
                return "normalized-link"

            def fetch_media(self, normalized_link: str) -> MediaFetchResult:
                audio = MediaStream(url="https://example.com/audio.m4a", stream_type="audio")
                return MediaFetchResult(
                    platform="douyin",
                    content_type="audio",
                    title="demo",
                    source_url="https://v.douyin.com/demo/",
                    final_url="https://www.douyin.com/video/1",
                    cover_url=None,
                    author=None,
                    video_streams=[],
                    audio_streams=[audio],
                    preferred_video=None,
                    preferred_audio=audio,
                    metadata={},
                )

        result = run_pipeline(
            raw_link="https://v.douyin.com/demo/",
            export_request=ExportRequest(output_path="/tmp/out", output_type="mp3"),
            adapter=FakeAdapter(),
            dry_run=True,
        )
        self.assertEqual(result["platform"], "douyin")
        self.assertEqual(result["normalized_link"], "normalized-link")


class YoutubeAdapterTests(unittest.TestCase):
    def test_youtube_adapter_recognizes_watch_urls_and_rejects_spoofed_domain(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        self.assertTrue(adapter.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(adapter.can_handle("https://youtu.be/dQw4w9WgXcQ"))
        self.assertFalse(adapter.can_handle("https://evil.example.com/?next=https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_youtube_adapter_normalizes_short_url(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        self.assertEqual(
            adapter.normalize_link("分享链接 https://youtu.be/dQw4w9WgXcQ"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    def test_youtube_adapter_fetches_streams_from_player_response(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        html = """
        <html><body>
        <script>var ytInitialPlayerResponse = {"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"YouTube 测试视频","author":"demo-channel","thumbnail":{"thumbnails":[{"url":"https://example.com/cover.jpg"}]}},"streamingData":{"formats":[{"url":"https://cdn.example.com/yt-720.mp4","mimeType":"video/mp4; codecs=\\"avc1\\"","width":1280,"height":720,"bitrate":800000,"contentLength":"1234567","qualityLabel":"720p"}],"adaptiveFormats":[{"url":"https://cdn.example.com/yt-audio.m4a","mimeType":"audio/mp4; codecs=\\"mp4a\\"","bitrate":128000}]}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.youtube.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        self.assertEqual(result.platform, "youtube")
        self.assertEqual(result.title, "YouTube 测试视频")
        self.assertEqual(result.author, "demo-channel")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/yt-720.mp4")
        self.assertEqual(result.preferred_video.filesize, 1234567)
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/yt-audio.m4a")
        self.assertEqual(result.metadata["raw_platform_id"], "dQw4w9WgXcQ")
        self.assertEqual(result.metadata["resolve_method"], "embedded-json")

    def test_youtube_adapter_extracts_stream_url_from_signature_cipher(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        html = """
        <html><body>
        <script>var ytInitialPlayerResponse = {"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"Cipher YouTube","author":"demo-channel"},"streamingData":{"formats":[{"signatureCipher":"url=https%3A%2F%2Fcdn.example.com%2Fyt-720.mp4&sp=signature&sig=plain-video-signature","mimeType":"video/mp4; codecs=\\"avc1\\"","width":1280,"height":720,"bitrate":800000,"qualityLabel":"720p"}],"adaptiveFormats":[{"cipher":"url=https%3A%2F%2Fcdn.example.com%2Fyt-audio.m4a&sp=sig&sig=plain-audio-signature","mimeType":"audio/mp4; codecs=\\"mp4a\\"","bitrate":128000}]}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.youtube.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        self.assertEqual(
            result.preferred_video.url,
            "https://cdn.example.com/yt-720.mp4?signature=plain-video-signature",
        )
        self.assertEqual(
            result.preferred_audio.url,
            "https://cdn.example.com/yt-audio.m4a?sig=plain-audio-signature",
        )
        self.assertEqual(result.metadata["resolve_method"], "embedded-json")

    def test_youtube_adapter_accepts_player_response_anchor_variant(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        html = """
        <html><body>
        <script>ytInitialPlayerResponse={"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"Anchor Variant","author":"demo-channel"},"streamingData":{"formats":[{"url":"https://cdn.example.com/yt-720.mp4","mimeType":"video/mp4; codecs=\\"avc1\\"","width":1280,"height":720,"bitrate":800000,"qualityLabel":"720p"}],"adaptiveFormats":[]}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.youtube.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        self.assertEqual(result.title, "Anchor Variant")
        self.assertEqual(result.metadata["resolve_method"], "embedded-json")

    def test_youtube_adapter_falls_back_when_cipher_needs_signature_decoding(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()
        html = """
        <html><body>
        <script>var ytInitialPlayerResponse = {"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"Cipher Needs Decode","author":"demo-channel"},"streamingData":{"formats":[{"signatureCipher":"url=https%3A%2F%2Fcdn.example.com%2Fyt-720.mp4&sp=sig&s=encrypted","mimeType":"video/mp4; codecs=\\"avc1\\"","width":1280,"height":720,"bitrate":800000,"qualityLabel":"720p"}],"adaptiveFormats":[]}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "fallback cipher youtube",
            "author": "fallback channel",
            "cover_url": "https://example.com/fallback-cipher.jpg",
            "video_url": "https://cdn.example.com/fallback-cipher-video.mp4",
            "audio_url": None,
        }
        with patch("fetchers.adapters.youtube.requests.get", return_value=FakeResponse(html)):
            with patch("fetchers.adapters.youtube.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        self.assertEqual(result.title, "fallback cipher youtube")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")

    def test_youtube_adapter_falls_back_to_browser_capture(self):
        from fetchers.adapters.youtube import YoutubeAdapter

        adapter = YoutubeAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "fallback youtube",
            "author": "fallback channel",
            "cover_url": "https://example.com/fallback.jpg",
            "video_url": "https://cdn.example.com/fallback-video.mp4",
            "audio_url": "https://cdn.example.com/fallback-audio.m4a",
        }
        with patch("fetchers.adapters.youtube.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.youtube.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        self.assertEqual(result.title, "fallback youtube")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")


class TiktokAdapterTests(unittest.TestCase):
    def test_tiktok_adapter_recognizes_video_links_and_rejects_spoofed_domain(self):
        from fetchers.adapters.tiktok import TiktokAdapter

        adapter = TiktokAdapter()
        self.assertTrue(adapter.can_handle("https://www.tiktok.com/@demo/video/7350000000000000001"))
        self.assertFalse(adapter.can_handle("https://evil.example.com/?next=https://www.tiktok.com/@demo/video/7350000000000000001"))

    def test_tiktok_adapter_normalize_rejects_non_video_page(self):
        from fetchers.adapters.tiktok import TiktokAdapter

        adapter = TiktokAdapter()
        with self.assertRaisesRegex(ValueError, "Unsupported TikTok video URL"):
            adapter.normalize_link("https://www.tiktok.com/@demo")

    def test_tiktok_adapter_fetches_media_from_next_data(self):
        from fetchers.adapters.tiktok import TiktokAdapter

        adapter = TiktokAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"itemInfo":{"itemStruct":{"id":"7350000000000000001","desc":"TikTok 测试视频","author":{"nickname":"demo-creator"},"video":{"cover":"https://example.com/tiktok-cover.jpg","downloadAddr":"https://cdn.example.com/tiktok-video.mp4","playAddr":"https://cdn.example.com/tiktok-play.mp4"},"music":{"playUrl":"https://cdn.example.com/tiktok-audio.m4a"}}}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.tiktok.com/@demo/video/7350000000000000001"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.tiktok.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.tiktok.com/@demo/video/7350000000000000001")

        self.assertEqual(result.platform, "tiktok")
        self.assertEqual(result.title, "TikTok 测试视频")
        self.assertEqual(result.author, "demo-creator")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/tiktok-video.mp4")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/tiktok-audio.m4a")
        self.assertEqual(result.metadata["raw_platform_id"], "7350000000000000001")

    def test_tiktok_adapter_uses_play_addr_when_download_addr_missing(self):
        from fetchers.adapters.tiktok import TiktokAdapter

        adapter = TiktokAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"itemInfo":{"itemStruct":{"id":"7350000000000000001","desc":"TikTok playAddr","author":{"nickname":"demo-creator"},"video":{"cover":"https://example.com/tiktok-cover.jpg","playAddr":"https://cdn.example.com/tiktok-play.mp4"},"music":{"playUrl":"https://cdn.example.com/tiktok-audio.m4a"}}}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.tiktok.com/@demo/video/7350000000000000001"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.tiktok.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.tiktok.com/@demo/video/7350000000000000001")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/tiktok-play.mp4")

    def test_tiktok_adapter_falls_back_to_browser_capture(self):
        from fetchers.adapters.tiktok import TiktokAdapter

        adapter = TiktokAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://www.tiktok.com/@demo/video/7350000000000000001"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://www.tiktok.com/@demo/video/7350000000000000001",
            "title": "fallback tiktok",
            "author": "fallback creator",
            "cover_url": "https://example.com/tiktok-fallback.jpg",
            "video_url": "https://cdn.example.com/tiktok-fallback.mp4",
            "audio_url": None,
        }
        with patch("fetchers.adapters.tiktok.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.tiktok.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://www.tiktok.com/@demo/video/7350000000000000001")

        self.assertEqual(result.title, "fallback tiktok")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")


class TwitterXAdapterTests(unittest.TestCase):
    def test_twitter_x_adapter_recognizes_status_video_links_and_rejects_spoofed_domain(self):
        from fetchers.adapters.twitter_x import TwitterXAdapter

        adapter = TwitterXAdapter()
        self.assertTrue(adapter.can_handle("https://x.com/demo/status/1800000000000000000"))
        self.assertTrue(adapter.can_handle("https://twitter.com/demo/status/1800000000000000000"))
        self.assertFalse(adapter.can_handle("https://evil.example.com/?next=https://x.com/demo/status/1800000000000000000"))

    def test_twitter_x_adapter_normalizes_twitter_host_and_rejects_non_status_page(self):
        from fetchers.adapters.twitter_x import TwitterXAdapter

        adapter = TwitterXAdapter()
        self.assertEqual(
            adapter.normalize_link("https://twitter.com/demo/status/1800000000000000000"),
            "https://x.com/demo/status/1800000000000000000",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported X status URL"):
            adapter.normalize_link("https://x.com/demo")

    def test_twitter_x_adapter_fetches_variants_from_next_data(self):
        from fetchers.adapters.twitter_x import TwitterXAdapter

        adapter = TwitterXAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"status":{"rest_id":"1800000000000000000","text":"X 测试视频","core":{"user_results":{"result":{"legacy":{"name":"demo-author"}}}},"mediaEntities":[{"media_url_https":"https://example.com/x-cover.jpg","video_info":{"variants":[{"content_type":"video/mp4","bitrate":832000,"url":"https://cdn.example.com/x-720.mp4"},{"content_type":"video/mp4","bitrate":256000,"url":"https://cdn.example.com/x-480.mp4"}]}}]}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://x.com/demo/status/1800000000000000000"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.twitter_x.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://x.com/demo/status/1800000000000000000")

        self.assertEqual(result.platform, "twitter_x")
        self.assertEqual(result.title, "X 测试视频")
        self.assertEqual(result.author, "demo-author")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/x-720.mp4")
        self.assertEqual(result.cover_url, "https://example.com/x-cover.jpg")
        self.assertEqual(result.metadata["raw_platform_id"], "1800000000000000000")

    def test_twitter_x_adapter_ignores_hls_and_prefers_highest_mp4_variant(self):
        from fetchers.adapters.twitter_x import TwitterXAdapter

        adapter = TwitterXAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"status":{"rest_id":"1800000000000000000","text":"X variants","core":{"user_results":{"result":{"legacy":{"name":"demo-author"}}}},"mediaEntities":[{"media_url_https":"https://example.com/x-cover.jpg","video_info":{"variants":[{"content_type":"application/x-mpegURL","url":"https://cdn.example.com/x-master.m3u8"},{"content_type":"video/mp4","bitrate":256000,"url":"https://cdn.example.com/x-480.mp4"},{"content_type":"video/mp4","bitrate":832000,"url":"https://cdn.example.com/x-720.mp4"}]}}]}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://x.com/demo/status/1800000000000000000"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.twitter_x.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://x.com/demo/status/1800000000000000000")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/x-720.mp4")

    def test_twitter_x_adapter_falls_back_to_browser_capture(self):
        from fetchers.adapters.twitter_x import TwitterXAdapter

        adapter = TwitterXAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://x.com/demo/status/1800000000000000000"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://x.com/demo/status/1800000000000000000",
            "title": "fallback x",
            "author": "fallback user",
            "cover_url": "https://example.com/x-fallback.jpg",
            "video_url": "https://cdn.example.com/x-fallback.mp4",
            "audio_url": None,
        }
        with patch("fetchers.adapters.twitter_x.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.twitter_x.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://x.com/demo/status/1800000000000000000")

        self.assertEqual(result.title, "fallback x")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")


class BilibiliAdapterTests(unittest.TestCase):
    def test_bilibili_adapter_extracts_core_url_from_share_text(self):
        adapter = BilibiliAdapter()
        raw_link = "0.74 复制打开B站 https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.999"
        self.assertEqual(
            adapter.normalize_link(raw_link),
            "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.999",
        )

    def test_bilibili_adapter_rejects_non_video_pages(self):
        adapter = BilibiliAdapter()
        self.assertFalse(adapter.can_handle("https://www.bilibili.com/bangumi/play/ep123456"))
        self.assertFalse(adapter.can_handle("https://www.bilibili.com/cheese/play/ss123"))
        self.assertFalse(adapter.can_handle("https://evil.example.com/?target=https://www.bilibili.com/video/BV1xx411c7mD"))

    def test_bilibili_adapter_fetches_media_streams_from_page_and_playurl(self):
        adapter = BilibiliAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"videoData":{"title":"B站测试视频","bvid":"BV1xx411c7mD","cid":123456,"pic":"https://example.com/cover.jpg","owner":{"name":"demo-up"}}};</script>
        </body></html>
        """
        playurl_payload = {
            "code": 0,
            "data": {
                "quality": 64,
                "accept_quality": [112, 80, 64, 32],
                "accept_description": ["高清 1080P+", "高清 1080P", "高清 720P", "清晰 480P"],
                "dash": {
                    "video": [
                        {
                            "id": 32,
                            "base_url": "https://cdn.example.com/video-480-avc.m4s",
                            "codecs": "avc1.64001F",
                            "width": 852,
                            "height": 480,
                            "bandwidth": 500000,
                        },
                        {
                            "id": 64,
                            "base_url": "https://cdn.example.com/video-720-av01.m4s",
                            "codecs": "av01.0.08M.08",
                            "width": 1280,
                            "height": 720,
                            "bandwidth": 1100000,
                        },
                        {
                            "id": 64,
                            "base_url": "https://cdn.example.com/video-720-avc.m4s",
                            "codecs": "avc1.640020",
                            "width": 1280,
                            "height": 720,
                            "bandwidth": 900000,
                        },
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "base_url": "https://cdn.example.com/audio-30280.m4s",
                            "codecs": "mp4a.40.2",
                            "bandwidth": 192000,
                        }
                    ],
                },
            },
        }

        class FakeResponse:
            def __init__(self, *, text=None, json_data=None, url="https://www.bilibili.com/video/BV1xx411c7mD/"):
                self.text = text or ""
                self._json_data = json_data
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._json_data

        with patch("fetchers.adapters.bilibili.requests.get") as mocked_get:
            mocked_get.side_effect = [
                FakeResponse(text=html),
                FakeResponse(json_data=playurl_payload),
            ]
            result = adapter.fetch_media("https://www.bilibili.com/video/BV1xx411c7mD/")

        self.assertEqual(result.platform, "bilibili")
        self.assertEqual(result.title, "B站测试视频")
        self.assertEqual(result.author, "demo-up")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/video-720-avc.m4s")
        self.assertEqual(result.preferred_video.quality_label, "高清 720P")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/audio-30280.m4s")

    def test_bilibili_adapter_uses_chrome_cookies_to_unlock_higher_quality(self):
        adapter = BilibiliAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"videoData":{"title":"B站高画质测试","bvid":"BV1cookieTest","cid":987654,"pic":"https://example.com/cover.jpg","owner":{"name":"demo-up"}}};</script>
        </body></html>
        """
        no_cookie_payload = {
            "code": 0,
            "data": {
                "accept_quality": [32, 16],
                "accept_description": ["清晰 480P", "流畅 360P"],
                "dash": {
                    "video": [
                        {
                            "id": 32,
                            "base_url": "https://cdn.example.com/video-480-avc.m4s",
                            "codecs": "avc1.64001F",
                            "width": 852,
                            "height": 480,
                            "bandwidth": 560000,
                        }
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "base_url": "https://cdn.example.com/audio-30280.m4s",
                            "codecs": "mp4a.40.2",
                            "bandwidth": 192000,
                        }
                    ],
                },
            },
        }
        cookie_payload = {
            "code": 0,
            "data": {
                "accept_quality": [116, 80, 64, 32, 16],
                "accept_description": ["高清 1080P60", "高清 1080P", "高清 720P", "清晰 480P", "流畅 360P"],
                "dash": {
                    "video": [
                        {
                            "id": 80,
                            "base_url": "https://cdn.example.com/video-1080-avc.m4s",
                            "codecs": "avc1.640032",
                            "width": 1920,
                            "height": 1080,
                            "bandwidth": 2915169,
                        },
                        {
                            "id": 32,
                            "base_url": "https://cdn.example.com/video-480-avc.m4s",
                            "codecs": "avc1.64001F",
                            "width": 852,
                            "height": 480,
                            "bandwidth": 560000,
                        },
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "base_url": "https://cdn.example.com/audio-30280.m4s",
                            "codecs": "mp4a.40.2",
                            "bandwidth": 192000,
                        }
                    ],
                },
            },
        }

        class FakeResponse:
            def __init__(self, *, text=None, json_data=None, url="https://www.bilibili.com/video/BV1cookieTest/"):
                self.text = text or ""
                self._json_data = json_data
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._json_data

        def fake_get(request_url, **kwargs):
            cookies = kwargs.get("cookies")
            if request_url.startswith("https://www.bilibili.com/video/"):
                return FakeResponse(text=html)
            if request_url.startswith("https://api.bilibili.com/x/player/playurl"):
                if cookies:
                    return FakeResponse(json_data=cookie_payload)
                return FakeResponse(json_data=no_cookie_payload)
            raise AssertionError(f"unexpected url {request_url}")

        with patch("fetchers.adapters.bilibili.load_bilibili_cookies", return_value=({"SESSDATA": "demo"}, "chrome"), create=True):
            with patch("fetchers.adapters.bilibili.requests.get", side_effect=fake_get):
                result = adapter.fetch_media("https://www.bilibili.com/video/BV1cookieTest/")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/video-1080-avc.m4s")
        self.assertEqual(result.preferred_video.quality_label, "高清 1080P")

    def test_bilibili_adapter_falls_back_to_edge_when_chrome_cookie_missing(self):
        adapter = BilibiliAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"videoData":{"title":"B站浏览器回退测试","bvid":"BV1fallbackTest","cid":987655,"pic":"https://example.com/cover.jpg","owner":{"name":"demo-up"}}};</script>
        </body></html>
        """
        cookie_payload = {
            "code": 0,
            "data": {
                "accept_quality": [80, 64, 32, 16],
                "accept_description": ["高清 1080P", "高清 720P", "清晰 480P", "流畅 360P"],
                "dash": {
                    "video": [
                        {
                            "id": 80,
                            "base_url": "https://cdn.example.com/video-1080-avc.m4s",
                            "codecs": "avc1.640032",
                            "width": 1920,
                            "height": 1080,
                            "bandwidth": 2915169,
                        }
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "base_url": "https://cdn.example.com/audio-30280.m4s",
                            "codecs": "mp4a.40.2",
                            "bandwidth": 192000,
                        }
                    ],
                },
            },
        }

        class FakeResponse:
            def __init__(self, *, text=None, json_data=None, url="https://www.bilibili.com/video/BV1fallbackTest/"):
                self.text = text or ""
                self._json_data = json_data
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._json_data

        def fake_get(request_url, **kwargs):
            if request_url.startswith("https://www.bilibili.com/video/"):
                return FakeResponse(text=html)
            if request_url.startswith("https://api.bilibili.com/x/player/playurl"):
                return FakeResponse(json_data=cookie_payload)
            raise AssertionError(f"unexpected url {request_url}")

        with patch("fetchers.adapters.bilibili.load_bilibili_cookies", return_value=({"SESSDATA": "edge-demo"}, "edge"), create=True):
            with patch("fetchers.adapters.bilibili.requests.get", side_effect=fake_get):
                result = adapter.fetch_media("https://www.bilibili.com/video/BV1fallbackTest/")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/video-1080-avc.m4s")
        self.assertEqual(result.metadata["cookie_source"], "edge")

    def test_bilibili_adapter_prefers_manual_cookie_over_browser_cookie(self):
        adapter = BilibiliAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"videoData":{"title":"B站手动Cookie测试","bvid":"BV1manualCookie","cid":987656,"pic":"https://example.com/cover.jpg","owner":{"name":"demo-up"}}};</script>
        </body></html>
        """
        cookie_payload = {
            "code": 0,
            "data": {
                "accept_quality": [80, 64],
                "accept_description": ["高清 1080P", "高清 720P"],
                "dash": {
                    "video": [
                        {
                            "id": 80,
                            "base_url": "https://cdn.example.com/video-1080-avc.m4s",
                            "codecs": "avc1.640032",
                            "width": 1920,
                            "height": 1080,
                            "bandwidth": 2915169,
                        }
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "base_url": "https://cdn.example.com/audio-30280.m4s",
                            "codecs": "mp4a.40.2",
                            "bandwidth": 192000,
                        }
                    ],
                },
            },
        }

        class FakeResponse:
            def __init__(self, *, text=None, json_data=None, url="https://www.bilibili.com/video/BV1manualCookie/"):
                self.text = text or ""
                self._json_data = json_data
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._json_data

        observed_cookie = {}

        def fake_get(request_url, **kwargs):
            cookies = kwargs.get("cookies")
            if request_url.startswith("https://www.bilibili.com/video/"):
                observed_cookie["value"] = cookies
                return FakeResponse(text=html)
            if request_url.startswith("https://api.bilibili.com/x/player/playurl"):
                return FakeResponse(json_data=cookie_payload)
            raise AssertionError(f"unexpected url {request_url}")

        with patch.dict("os.environ", {"BILIBILI_COOKIE": "SESSDATA=manual-demo; bili_jct=csrf-demo"}, clear=False):
            with patch("fetchers.adapters.bilibili.requests.get", side_effect=fake_get):
                result = adapter.fetch_media("https://www.bilibili.com/video/BV1manualCookie/")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/video-1080-avc.m4s")
        self.assertEqual(result.metadata["cookie_source"], "manual")
        self.assertEqual(observed_cookie["value"]["SESSDATA"], "manual-demo")
        self.assertEqual(observed_cookie["value"]["bili_jct"], "csrf-demo")


class KuaishouAdapterTests(unittest.TestCase):
    def test_kuaishou_adapter_normalizes_share_text_to_mobile_url(self):
        adapter = KuaishouAdapter()
        raw_link = "复制打开快手 https://www.kuaishou.com/short-video/3x58pjvr7ripi7c?foo=bar"
        normalized = adapter.normalize_link(raw_link)
        self.assertTrue(normalized.startswith("https://m.gifshow.com/fw/photo/3x58pjvr7ripi7c"))

    def test_kuaishou_adapter_fetches_media_from_mobile_init_state(self):
        adapter = KuaishouAdapter()
        html = """
        <html><body>
        <script>
        window.INIT_STATE = {
          "photo-query": {
            "result": 1,
            "photo": {
              "type": 1,
              "singlePicture": false,
              "userName": "快手测试号",
              "photoId": "5229523707741271525",
              "caption": "快手测试视频",
              "coverUrls": [{"url": "https://example.com/cover.jpg"}],
              "mainMvUrls": [{"url": "https://example.com/video.mp4"}],
              "manifest": {
                "adaptationSet": [{
                  "representation": [{
                    "qualityLabel": "高清",
                    "width": 1280,
                    "height": 720,
                    "avgBitrate": 501,
                    "videoCodec": "avc",
                    "url": "https://example.com/video-hls.m3u8"
                  }]
                }]
              }
            }
          }
        };
        </script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, *, text: str, url: str):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.kuaishou.requests.get") as mocked_get:
            mocked_get.return_value = FakeResponse(
                text=html,
                url="https://m.gifshow.com/fw/photo/3x58pjvr7ripi7c?foo=bar",
            )
            result = adapter.fetch_media("https://m.gifshow.com/fw/photo/3x58pjvr7ripi7c?foo=bar")

        self.assertEqual(result.platform, "kuaishou")
        self.assertEqual(result.title, "快手测试视频")
        self.assertEqual(result.author, "快手测试号")
        self.assertEqual(result.preferred_video.url, "https://example.com/video.mp4")
        self.assertEqual(result.preferred_video.quality_label, "高清")
        self.assertIsNone(result.preferred_audio)

    def test_kuaishou_adapter_builds_quality_streams_from_manifest_representations(self):
        adapter = KuaishouAdapter()
        html = """
        <html><body>
        <script>
        window.INIT_STATE = {
          "photo-query": {
            "result": 1,
            "photo": {
              "type": 1,
              "singlePicture": false,
              "userName": "快手测试号",
              "photoId": "5229523707741271525",
              "caption": "快手多清晰度测试",
              "coverUrls": [{"url": "https://example.com/cover.jpg"}],
              "mainMvUrls": [{"url": "https://example.com/video.mp4"}],
              "manifest": {
                "adaptationSet": [{
                  "representation": [
                    {
                      "qualityLabel": "流畅",
                      "width": 640,
                      "height": 360,
                      "avgBitrate": 300000,
                      "videoCodec": "avc",
                      "url": "https://example.com/video-360.m3u8"
                    },
                    {
                      "qualityLabel": "高清",
                      "width": 1280,
                      "height": 720,
                      "avgBitrate": 800000,
                      "videoCodec": "avc",
                      "url": "https://example.com/video-720.m3u8"
                    }
                  ]
                }]
              }
            }
          }
        };
        </script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, *, text: str, url: str):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.kuaishou.requests.get") as mocked_get:
            mocked_get.return_value = FakeResponse(
                text=html,
                url="https://m.gifshow.com/fw/photo/3x58pjvr7ripi7c?foo=bar",
            )
            result = adapter.fetch_media("https://m.gifshow.com/fw/photo/3x58pjvr7ripi7c?foo=bar")

        self.assertEqual(len(result.video_streams), 2)
        self.assertEqual(result.preferred_video.url, "https://example.com/video-720.m3u8")
        self.assertEqual(result.preferred_video.quality_label, "高清")


class XiaohongshuAdapterTests(unittest.TestCase):
    def test_xiaohongshu_adapter_recognizes_links_and_extracts_url_from_share_text(self):
        adapter = XiaohongshuAdapter()
        raw = "复制打开小红书 https://www.xiaohongshu.com/explore/66abc123?xsec_token=demo"
        self.assertTrue(adapter.can_handle(raw))
        self.assertEqual(
            adapter.normalize_link(raw),
            "https://www.xiaohongshu.com/explore/66abc123?xsec_token=demo",
        )

    def test_xiaohongshu_adapter_fetches_media_from_embedded_state(self):
        adapter = XiaohongshuAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"note":{"noteId":"66abc123","title":"小红书测试视频","user":{"nickname":"测试作者"},"cover":{"url":"https://example.com/cover.jpg"},"video":{"media":{"stream":{"h264":[{"masterUrl":"https://cdn.example.com/xhs-video.mp4","width":1080,"height":1920,"avgBitrate":1467000}]},"audioStream":{"url":"https://cdn.example.com/xhs-audio.m4a","avgBitrate":128000}}}}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.xiaohongshu.com/explore/66abc123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.xiaohongshu.com/explore/66abc123")

        self.assertEqual(result.platform, "xiaohongshu")
        self.assertEqual(result.title, "小红书测试视频")
        self.assertEqual(result.author, "测试作者")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/xhs-video.mp4")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/xhs-audio.m4a")
        self.assertEqual(result.metadata["resolve_method"], "embedded-json")
        self.assertEqual(result.metadata["raw_platform_id"], "66abc123")

    def test_xiaohongshu_adapter_merges_multiple_codec_stream_groups_for_quality_selection(self):
        adapter = XiaohongshuAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"note":{"noteId":"66multi123","title":"小红书多档测试","user":{"nickname":"测试作者"},"cover":{"url":"https://example.com/cover.jpg"},"video":{"media":{"stream":{"h264":[{"masterUrl":"https://cdn.example.com/xhs-720-h264.mp4","width":1280,"height":720,"avgBitrate":1467000,"qualityLabel":"720p"}],"h265":[{"masterUrl":"https://cdn.example.com/xhs-1080-h265.mp4","width":1920,"height":1080,"avgBitrate":2467000,"qualityLabel":"1080p","codec":"h265"}]}}}}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.xiaohongshu.com/explore/66multi123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.xiaohongshu.com/explore/66multi123")

        self.assertEqual(len(result.video_streams), 2)
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/xhs-1080-h265.mp4")
        self.assertEqual(result.preferred_video.quality_label, "1080p")

    def test_xiaohongshu_adapter_parses_embedded_state_with_braces_inside_string(self):
        adapter = XiaohongshuAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"note":{"noteId":"66abc123","title":"小红书测试视频 }; 仍应解析","user":{"nickname":"测试作者"},"cover":{"url":"https://example.com/cover.jpg"},"video":{"media":{"stream":{"h264":[{"masterUrl":"https://cdn.example.com/xhs-video.mp4","width":1080,"height":1920,"avgBitrate":1467000}]}}}}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.xiaohongshu.com/explore/66abc123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.xiaohongshu.com/explore/66abc123")

        self.assertEqual(result.title, "小红书测试视频 }; 仍应解析")

    def test_xiaohongshu_adapter_parses_embedded_state_with_undefined_values(self):
        adapter = XiaohongshuAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"global":{"pwaAddDesktopPrompt":undefined,"firstVisitUrl":undefined},"note":{"noteId":"66real123","title":"小红书真实页兼容测试","user":{"nickname":"测试作者"},"cover":{"url":"https://example.com/cover.jpg"},"video":{"media":{"stream":{"h264":[{"masterUrl":"https://cdn.example.com/xhs-real.mp4","width":720,"height":1280,"avgBitrate":1745583,"qualityType":"HD"}],"h265":[],"av1":[]}}}}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.xiaohongshu.com/discovery/item/66real123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.xiaohongshu.com/discovery/item/66real123")

        self.assertEqual(result.metadata["resolve_method"], "embedded-json")
        self.assertEqual(result.title, "小红书真实页兼容测试")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/xhs-real.mp4")
        self.assertEqual(result.preferred_video.width, 720)
        self.assertEqual(result.preferred_video.height, 1280)

    def test_xiaohongshu_adapter_extracts_note_from_note_detail_map_shape(self):
        adapter = XiaohongshuAdapter()
        html = """
        <html><head><title>demo</title></head><body>
        <script>window.__INITIAL_STATE__={"global":{"pwaAddDesktopPrompt":undefined},"note":{"currentNoteId":"66map123","noteDetailMap":{"66map123":{"note":{"noteId":"66map123","title":"小红书新版结构测试","user":{"nickname":"测试作者"},"cover":{"url":"https://example.com/cover.jpg"},"video":{"media":{"stream":{"h264":[{"masterUrl":"https://cdn.example.com/xhs-map.mp4","width":720,"height":1280,"avgBitrate":1745583,"qualityType":"HD"}],"h265":[],"av1":[]}}}}}}}};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://www.xiaohongshu.com/discovery/item/66map123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://www.xiaohongshu.com/discovery/item/66map123")

        self.assertEqual(result.metadata["resolve_method"], "embedded-json")
        self.assertEqual(result.title, "小红书新版结构测试")
        self.assertEqual(result.metadata["raw_platform_id"], "66map123")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/xhs-map.mp4")

    def test_xiaohongshu_adapter_rejects_spoofed_domain(self):
        adapter = XiaohongshuAdapter()
        self.assertFalse(adapter.can_handle("https://evil.example.com/?next=https://www.xiaohongshu.com/explore/66abc123"))

    def test_xiaohongshu_short_link_must_resolve_to_supported_host(self):
        adapter = XiaohongshuAdapter()

        class FakeResponse:
            def __init__(self, url: str):
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse("https://evil.example.com/post/1")):
            with self.assertRaisesRegex(ValueError, "Unsupported XiaoHongShu host"):
                adapter.normalize_link("https://xhslink.com/abc")

    def test_xiaohongshu_adapter_falls_back_to_browser_capture(self):
        adapter = XiaohongshuAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://www.xiaohongshu.com/explore/66abc123"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://www.xiaohongshu.com/explore/66abc123",
            "title": "fallback xhs",
            "author": "fallback 作者",
            "cover_url": "https://example.com/fallback-cover.jpg",
            "video_url": "https://cdn.example.com/fallback-xhs.mp4",
            "audio_url": "https://cdn.example.com/fallback-xhs.m4a",
        }
        with patch("fetchers.adapters.xiaohongshu.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.xiaohongshu.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://www.xiaohongshu.com/explore/66abc123")

        self.assertEqual(result.title, "fallback xhs")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/fallback-xhs.mp4")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/fallback-xhs.m4a")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")


class WeiboAdapterTests(unittest.TestCase):
    def test_weibo_adapter_recognizes_share_links(self):
        adapter = WeiboAdapter()
        self.assertTrue(adapter.can_handle("https://weibo.com/tv/show/1034:abc"))
        self.assertEqual(
            adapter.normalize_link("分享微博 https://weibo.com/tv/show/1034:abc"),
            "https://weibo.com/tv/show/1034:abc",
        )

    def test_weibo_adapter_fetches_media_from_page_info(self):
        adapter = WeiboAdapter()
        html = """
        <html><body>
        <script>var $render_data = [{"status":{"id":"509999","text_raw":"微博测试视频","user":{"screen_name":"微博作者"},"page_info":{"page_pic":{"url":"https://example.com/weibo-cover.jpg"},"media_info":{"stream_url":"https://cdn.example.com/weibo-video.mp4","stream_url_hd":"https://cdn.example.com/weibo-video-hd.mp4"}}}}][0] || {};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://weibo.com/tv/show/1034:abc"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.weibo.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://weibo.com/tv/show/1034:abc")

        self.assertEqual(result.platform, "weibo")
        self.assertEqual(result.title, "微博测试视频")
        self.assertEqual(result.author, "微博作者")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/weibo-video-hd.mp4")
        self.assertEqual(result.metadata["resolve_method"], "embedded-json")
        self.assertEqual(result.metadata["raw_platform_id"], "509999")

    def test_weibo_adapter_deduplicates_quality_candidates_and_prefers_hd(self):
        adapter = WeiboAdapter()
        html = """
        <html><body>
        <script>var $render_data = [{"status":{"id":"509999","text_raw":"微博多档测试视频","user":{"screen_name":"微博作者"},"page_info":{"page_pic":{"url":"https://example.com/weibo-cover.jpg"},"media_info":{"stream_url":"https://cdn.example.com/weibo-video-sd.mp4","mp4_sd_url":"https://cdn.example.com/weibo-video-sd.mp4","stream_url_hd":"https://cdn.example.com/weibo-video-hd.mp4","mp4_hd_url":"https://cdn.example.com/weibo-video-hd.mp4"}}}}][0] || {};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://weibo.com/tv/show/1034:abc"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.weibo.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://weibo.com/tv/show/1034:abc")

        self.assertEqual(len(result.video_streams), 2)
        self.assertEqual(result.video_streams[0].quality_label, "高清")
        self.assertEqual(result.video_streams[1].quality_label, "标清")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/weibo-video-hd.mp4")

    def test_weibo_adapter_parses_render_data_with_braces_inside_string(self):
        adapter = WeiboAdapter()
        html = """
        <html><body>
        <script>var $render_data = [{"status":{"id":"509999","text_raw":"微博测试视频 }; 仍应解析","user":{"screen_name":"微博作者"},"page_info":{"page_pic":{"url":"https://example.com/weibo-cover.jpg"},"media_info":{"stream_url":"https://cdn.example.com/weibo-video.mp4"}}}}][0] || {};</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://weibo.com/tv/show/1034:abc"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.weibo.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://weibo.com/tv/show/1034:abc")

        self.assertEqual(result.title, "微博测试视频 }; 仍应解析")

    def test_weibo_adapter_rejects_spoofed_domain(self):
        adapter = WeiboAdapter()
        self.assertFalse(adapter.can_handle("https://evil.example.com/?target=https://weibo.com/tv/show/1034:abc"))

    def test_weibo_adapter_falls_back_to_browser_capture(self):
        adapter = WeiboAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://weibo.com/tv/show/1034:abc"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://weibo.com/tv/show/1034:abc",
            "title": "fallback weibo",
            "author": "fallback 博主",
            "cover_url": "https://example.com/weibo-fallback-cover.jpg",
            "video_url": "https://cdn.example.com/weibo-fallback.mp4",
            "audio_url": None,
        }
        with patch("fetchers.adapters.weibo.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.weibo.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://weibo.com/tv/show/1034:abc")

        self.assertEqual(result.title, "fallback weibo")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/weibo-fallback.mp4")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")


class ChannelsAdapterTests(unittest.TestCase):
    def test_channels_adapter_recognizes_feed_links(self):
        adapter = ChannelsAdapter()
        raw = "打开视频号 https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123&profile=demo"
        self.assertTrue(adapter.can_handle(raw))
        self.assertEqual(
            adapter.normalize_link(raw),
            "https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123&profile=demo",
        )

    def test_channels_adapter_recognizes_weixin_short_link_and_preview_link(self):
        adapter = ChannelsAdapter()
        self.assertTrue(adapter.can_handle("https://weixin.qq.com/sph/A6aw3m5o99"))
        self.assertTrue(adapter.can_handle("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99"))

    def test_channels_adapter_normalizes_weixin_short_link_to_preview_page(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, url: str):
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch(
            "fetchers.adapters.channels.requests.get",
            return_value=FakeResponse("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99"),
        ):
            normalized = adapter.normalize_link("https://weixin.qq.com/sph/A6aw3m5o99")

        self.assertEqual(
            normalized,
            "https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99",
        )

    def test_channels_adapter_fetches_media_from_short_uri_preview_api(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, payload: dict):
                self._payload = payload
                self.status_code = 201

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        payload = {
            "data": {
                "authorInfo": {
                    "nickname": "视频号作者",
                    "headImgUrl": "https://example.com/avatar.jpg",
                },
                "feedInfo": {
                    "description": "视频号分享视频",
                    "coverUrl": "https://example.com/cover.jpg",
                    "videoUrl": "https://cdn.example.com/channels-default.mp4",
                    "h264VideoInfo": {"videoUrl": "https://cdn.example.com/channels-h264.mp4"},
                    "h265VideoInfo": {"videoUrl": "https://cdn.example.com/channels-h265.mp4"},
                    "originVideoUrl": "https://cdn.example.com/channels-origin.mp4",
                    "mediaType": 4,
                },
                "sceneInfo": {
                    "dynamicExportId": "export/UzFfBgAAxLKjVDNccgHsjczT4DCsIq2KMQIsDdntpvX5DGrt4EMWab6VSw",
                },
            },
            "errCode": 0,
            "errMsg": "",
        }

        with patch("fetchers.adapters.channels.requests.post", return_value=FakeResponse(payload)):
            result = adapter.fetch_media("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99")

        self.assertEqual(result.platform, "channels")
        self.assertEqual(result.title, "视频号分享视频")
        self.assertEqual(result.author, "视频号作者")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/channels-origin.mp4")
        self.assertEqual(result.metadata["resolve_method"], "preview-api-shorturi")
        self.assertEqual(result.metadata["raw_platform_id"], "A6aw3m5o99")
        self.assertEqual(len(result.video_streams), 4)

    def test_channels_adapter_surfaces_preview_only_error_when_short_uri_api_returns_cover_only(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, payload: dict):
                self._payload = payload
                self.status_code = 201

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        payload = {
            "data": {
                "authorInfo": {"nickname": "地产杂谈"},
                "feedInfo": {
                    "description": "只有封面，没有视频流",
                    "coverUrl": "https://example.com/cover.jpg",
                },
                "sceneInfo": {
                    "dynamicExportId": "export/demo",
                },
            },
            "errCode": 0,
            "errMsg": "",
        }

        with patch("fetchers.adapters.channels.requests.post", return_value=FakeResponse(payload)):
            with patch(
                "fetchers.adapters.channels.capture_media_with_browser",
                side_effect=RuntimeError("No media URL captured"),
            ):
                with self.assertRaisesRegex(RuntimeError, "仅返回封面或文案"):
                    adapter.fetch_media("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99")

    def test_channels_adapter_uses_optional_parse_service_when_cookie_is_configured(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, payload: dict, status_code: int = 200):
                self._payload = payload
                self.status_code = status_code

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        preview_only_payload = {
            "data": {
                "authorInfo": {"nickname": "地产杂谈"},
                "feedInfo": {
                    "description": "只有封面，没有视频流",
                    "coverUrl": "https://example.com/cover.jpg",
                },
            },
            "errCode": 0,
            "errMsg": "",
        }
        parse_service_payload = {
            "data": {
                "playable_url": "https://channels.weixin.qq.com/finder-preview/pages/feed?token=token_demo&eid=export/demo",
                "wx_export_id": "export/demo",
            }
        }
        export_payload = {
            "data": {
                "authorInfo": {"nickname": "视频号作者"},
                "feedInfo": {
                    "description": "深解析视频号视频",
                    "coverUrl": "https://example.com/cover.jpg",
                    "originVideoUrl": "https://cdn.example.com/channels-origin.mp4",
                },
            },
            "errCode": 0,
            "errMsg": "",
        }

        with patch.dict("os.environ", {"CHANNELS_PARSE_COOKIE": "cookie-demo"}, clear=False):
            with patch(
                "fetchers.adapters.channels.requests.post",
                side_effect=[
                    FakeResponse(preview_only_payload, status_code=201),
                    FakeResponse(parse_service_payload, status_code=200),
                    FakeResponse(export_payload, status_code=201),
                ],
            ):
                result = adapter.fetch_media("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99")

        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/channels-origin.mp4")
        self.assertEqual(result.metadata["resolve_method"], "preview-api-exportid")
        self.assertEqual(result.metadata["raw_platform_id"], "export/demo")

    def test_channels_adapter_fetches_media_from_init_data(self):
        adapter = ChannelsAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"feed":{"feedId":"feed_123","title":"视频号测试视频","nickname":"视频号作者","coverUrl":"https://example.com/channels-cover.jpg","video":{"playUrl":"https://cdn.example.com/channels-video.mp4","width":1080,"height":1920,"bitrate":1888000},"audio":{"playUrl":"https://cdn.example.com/channels-audio.m4a","bitrate":128000}}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.channels.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123")

        self.assertEqual(result.platform, "channels")
        self.assertEqual(result.title, "视频号测试视频")
        self.assertEqual(result.author, "视频号作者")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/channels-video.mp4")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/channels-audio.m4a")
        self.assertEqual(result.metadata["raw_platform_id"], "feed_123")

    def test_channels_adapter_builds_quality_streams_from_variants(self):
        adapter = ChannelsAdapter()
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"feed":{"feedId":"feed_123","title":"视频号多档测试视频","nickname":"视频号作者","coverUrl":"https://example.com/channels-cover.jpg","video":{"playUrl":"https://cdn.example.com/channels-video-720.mp4","width":1280,"height":720,"bitrate":1280000,"variants":[{"playUrl":"https://cdn.example.com/channels-video-480.mp4","width":854,"height":480,"bitrate":800000,"qualityLabel":"480p"},{"playUrl":"https://cdn.example.com/channels-video-720.mp4","width":1280,"height":720,"bitrate":1280000,"qualityLabel":"720p"},{"playUrl":"https://cdn.example.com/channels-video-1080.mp4","width":1920,"height":1080,"bitrate":2280000,"qualityLabel":"1080p"}]},"audio":{"playUrl":"https://cdn.example.com/channels-audio.m4a","bitrate":128000}}}}}</script>
        </body></html>
        """

        class FakeResponse:
            def __init__(self, text: str, url: str = "https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123"):
                self.text = text
                self.url = url
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.channels.requests.get", return_value=FakeResponse(html)):
            result = adapter.fetch_media("https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123")

        self.assertEqual(len(result.video_streams), 3)
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/channels-video-1080.mp4")
        self.assertEqual(result.preferred_video.quality_label, "1080p")

    def test_channels_adapter_rejects_spoofed_domain(self):
        adapter = ChannelsAdapter()
        self.assertFalse(adapter.can_handle("https://evil.example.com/?jump=https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123"))

    def test_channels_adapter_falls_back_to_browser_capture(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123"
                self.status_code = 200

            def raise_for_status(self):
                return None

        fallback_capture = {
            "final_url": "https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123",
            "title": "fallback channels",
            "author": "fallback 视频号",
            "cover_url": "https://example.com/channels-fallback-cover.jpg",
            "video_url": "https://cdn.example.com/channels-fallback.mp4",
            "audio_url": "https://cdn.example.com/channels-fallback.m4a",
        }
        with patch("fetchers.adapters.channels.requests.get", return_value=FakeResponse("<html></html>")):
            with patch("fetchers.adapters.channels.capture_media_with_browser", return_value=fallback_capture):
                result = adapter.fetch_media("https://channels.weixin.qq.com/web/pages/feed?feedid=feed_123")

        self.assertEqual(result.title, "fallback channels")
        self.assertEqual(result.preferred_video.url, "https://cdn.example.com/channels-fallback.mp4")
        self.assertEqual(result.preferred_audio.url, "https://cdn.example.com/channels-fallback.m4a")
        self.assertEqual(result.metadata["resolve_method"], "playwright-fallback")

    def test_channels_adapter_surfaces_clear_error_when_browser_fallback_captures_no_media(self):
        adapter = ChannelsAdapter()

        class FakeResponse:
            def __init__(self, text: str):
                self.text = text
                self.url = "https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99"
                self.status_code = 200

            def raise_for_status(self):
                return None

        with patch("fetchers.adapters.channels.requests.get", return_value=FakeResponse("<html></html>")):
            with patch(
                "fetchers.adapters.channels.capture_media_with_browser",
                side_effect=RuntimeError("No media URL captured"),
            ):
                with self.assertRaisesRegex(RuntimeError, "仅返回封面或文案"):
                    adapter.fetch_media("https://channels.weixin.qq.com/finder-preview/pages/sph?id=A6aw3m5o99")
