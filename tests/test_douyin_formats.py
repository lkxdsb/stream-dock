import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetchers.downloader import download_hls_media, download_media
from fetchers.exporters import OUTPUT_FORMATS as SHARED_OUTPUT_FORMATS
from fetchers.exporters import export_media as shared_export_media
from fetchers.exporters import run_ffmpeg
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

    def test_run_ffmpeg_reports_timeout_cleanly(self):
        with patch('fetchers.exporters.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='ffmpeg', timeout=1)):
            with self.assertRaisesRegex(RuntimeError, '超时'):
                run_ffmpeg(['ffmpeg', '-version'])


class DownloaderTests(unittest.TestCase):
    def test_download_media_uses_ffmpeg_for_m3u8_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / 'source.mp4'
            with patch('fetchers.downloader.requests.get', side_effect=AssertionError('requests path should not be used')):
                with patch('fetchers.downloader.download_hls_media', return_value=destination, create=True) as mocked_hls:
                    result = download_media(
                        'https://example.com/video-720.m3u8',
                        destination,
                        user_agent='demo-agent',
                        referer='https://m.gifshow.com/',
                    )

        self.assertEqual(result, destination)
        mocked_hls.assert_called_once()

    def test_download_hls_media_reports_timeout_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / 'source.mp4'
            with patch('fetchers.downloader.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='ffmpeg', timeout=1)):
                with self.assertRaisesRegex(RuntimeError, '超时'):
                    download_hls_media(
                        'https://example.com/video-720.m3u8',
                        destination,
                        user_agent='demo-agent',
                        referer='https://m.gifshow.com/',
                    )


if __name__ == '__main__':
    unittest.main()

class SubtitleOcrTests(unittest.TestCase):
    def test_merge_ocr_samples_groups_repeated_text_and_exports_srt(self):
        from fetchers.subtitle_ocr import cues_to_srt, merge_ocr_samples

        cues = merge_ocr_samples([
            (0.0, '第一句字幕\n'),
            (1.0, '第一句字幕'),
            (2.0, ''),
            (3.0, 'Second line'),
        ], interval_seconds=1.0)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, '第一句字幕')
        self.assertEqual((cues[0].start, cues[0].end), (0.0, 2.0))
        srt = cues_to_srt(cues)
        self.assertIn('00:00:00,000 --> 00:00:02,000', srt)
        self.assertIn('Second line', srt)

    def test_ocr_normalizer_filters_latin_noise_for_chinese_subtitles(self):
        from fetchers.subtitle_ocr import _normalize_ocr_text

        text = _normalize_ocr_text('HB 2 5B nae\n一， TEE ne\nCERES) 至\nSR: ERE / 评分人数: 80万\nI4¢OVO.9 1 FAL - Sa Ene\nQ 第十区电影\nSecond line of English subtitle\n')
        self.assertIn('评分人数', text)
        self.assertIn('第十区电影', text)
        self.assertNotIn('nae', text)
        self.assertNotIn('I4', text)
        self.assertIn('Second line of English subtitle', text)

class SubtitleAsrTests(unittest.TestCase):
    def test_parse_srt_cues_for_cli_fallback(self):
        from fetchers.subtitle_asr import _parse_srt_cues

        cues = _parse_srt_cues('''1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n2\n00:00:02,000 --> 00:00:03,000\n第二句\n''')
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, '第一句')
        self.assertEqual((cues[1].start, cues[1].end), (2.0, 3.0))

    def test_segments_to_cues_supports_dict_segments(self):
        from fetchers.subtitle_asr import _segments_to_cues

        cues = _segments_to_cues([
            {'start': 0, 'end': 1.2, 'text': ' 你好 '},
            {'start': 2, 'end': 1, 'text': 'bad'},
            {'start': 2, 'end': 3, 'text': ''},
        ])
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, '你好')

class NativeSubtitleConversionTests(unittest.TestCase):
    def test_bilibili_json_subtitle_payload_can_be_exported_as_srt(self):
        from fetchers.pipeline import _subtitle_json_to_srt

        srt = _subtitle_json_to_srt({
            'body': [
                {'from': 0.0, 'to': 1.5, 'content': '第一句'},
                {'from': 2.0, 'to': 3.25, 'content': '第二句'},
            ]
        })
        self.assertIsNotNone(srt)
        self.assertIn('00:00:00,000 --> 00:00:01,500', srt or '')
        self.assertIn('第二句', srt or '')

class MetadataSubtitleFallbackTests(unittest.TestCase):
    def test_tiktok_metadata_fallback_creates_explanatory_srt_from_url(self):
        from fetchers.models import MediaFetchResult
        from fetchers.pipeline import generate_metadata_subtitle_file

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fallback.srt'
            result = MediaFetchResult(
                platform='tiktok',
                content_type='video',
                title='tiktok_7653663917918440722',
                source_url='https://www.tiktok.com/@rxxiiny/video/7653663917918440722?is_from_webapp=1',
                final_url='https://www.tiktok.com/@rxxiiny/video/7653663917918440722?is_from_webapp=1',
                cover_url=None,
                author=None,
                metadata={},
            )
            generated = generate_metadata_subtitle_file(result, target, duration_seconds=10)
            self.assertEqual(generated, target)
            text = target.read_text(encoding='utf-8')
            self.assertIn('@rxxiiny', text)
            self.assertIn('平台未提供字幕轨', text)
