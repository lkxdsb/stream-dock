import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import requests

from fetchers.browser_runtime import BrowserUnavailableError, browser_capability, browser_context
from fetchers.adapters.common import should_fallback_to_browser
from fetchers.errors import MediaProbeError
from error_catalog import classify_error


class BrowserRuntimeTests(unittest.TestCase):
    def test_auto_prefers_chromium_and_releases_context(self):
        browser = MagicMock(version='1.63')
        playwright = SimpleNamespace(chromium=MagicMock())
        playwright.chromium.launch.return_value = browser
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('playwright.sync_api.sync_playwright', return_value=manager):
            with browser_context(user_agent='probe') as (context, runtime, version):
                self.assertEqual((runtime, version), ('chromium', '1.63'))
                context.add_cookies([])
        playwright.chromium.launch.assert_called_once()
        self.assertNotIn('channel', playwright.chromium.launch.call_args.kwargs)
        browser.new_context.assert_called_once()
        browser.new_context.return_value.close.assert_called_once()
        browser.close.assert_called_once()

    def test_auto_falls_back_to_chrome_only_after_launch_failure(self):
        playwright = SimpleNamespace(chromium=MagicMock())
        playwright.chromium.launch.side_effect = [RuntimeError('Chromium missing'), MagicMock(version='chrome')]
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('playwright.sync_api.sync_playwright', return_value=manager):
            with browser_context() as (_, runtime, _version):
                self.assertEqual(runtime, 'chrome')
        self.assertEqual(playwright.chromium.launch.call_count, 2)
        self.assertEqual(playwright.chromium.launch.call_args.kwargs['channel'], 'chrome')

    def test_both_missing_is_non_retryable_environment_error(self):
        playwright = SimpleNamespace(chromium=MagicMock())
        playwright.chromium.launch.side_effect = RuntimeError('missing')
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('playwright.sync_api.sync_playwright', return_value=manager):
            with self.assertRaises(BrowserUnavailableError) as captured:
                with browser_context():
                    pass
        self.assertEqual(len(captured.exception.reasons), 2)
        self.assertEqual(classify_error(str(captured.exception))['retryable'], False)
        self.assertEqual(classify_error(str(captured.exception))['code'], 'browser_unavailable')

    def test_resource_exhaustion_does_not_launch_fallback_browser(self):
        playwright = SimpleNamespace(chromium=MagicMock())
        playwright.chromium.launch.side_effect = RuntimeError('ENOMEM: cannot allocate memory')
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        from fetchers.browser_runtime import BrowserBusyError
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('playwright.sync_api.sync_playwright', return_value=manager):
            with self.assertRaises(BrowserBusyError):
                with browser_context():
                    pass
        playwright.chromium.launch.assert_called_once()

    def test_disabled_does_not_import_browser(self):
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'disabled'}):
            result = browser_capability(refresh=True)
        self.assertEqual(result['status'], 'disabled')

    def test_capability_requires_actual_dom_execution(self):
        context = MagicMock()
        context.new_page.return_value.evaluate.return_value = 'ready'
        from contextlib import nullcontext
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('fetchers.browser_runtime.browser_context', return_value=nullcontext((context, 'chromium', '1.63'))):
            result = browser_capability(refresh=True)
        self.assertEqual(result['status'], 'ok')
        context.new_page.return_value.evaluate.assert_called_once()

    def test_upstream_rejection_never_falls_back_to_browser(self):
        for status in (401, 403, 412, 429):
            response = requests.Response()
            response.status_code = status
            self.assertFalse(should_fallback_to_browser(requests.HTTPError('upstream', response=response)))
        self.assertTrue(should_fallback_to_browser(RuntimeError('missing embedded data')))
        self.assertFalse(should_fallback_to_browser(requests.Timeout('timed out')))
        self.assertFalse(should_fallback_to_browser(RuntimeError('captcha required')))
        self.assertEqual(classify_error('412 Client Error: Precondition Failed')['code'], 'upstream_access_rejected')

    def test_failed_javascript_does_not_report_browser_ready(self):
        context = MagicMock()
        context.new_page.return_value.evaluate.return_value = None
        from contextlib import nullcontext
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('fetchers.browser_runtime.browser_context', return_value=nullcontext((context, 'chromium', '1.63'))):
            result = browser_capability(refresh=True)
        self.assertEqual(result['status'], 'error')

    def test_browser_verification_page_stops_before_media_selection(self):
        from fetchers.adapters.common import _capture_media_from_context
        context = MagicMock()
        page = context.new_page.return_value
        page.url = 'https://weibo.com/captcha'
        page.evaluate.return_value = {'title': '安全验证', 'videoSources': [], 'author': None, 'cover': None}
        with self.assertRaises(MediaProbeError) as captured:
            _capture_media_from_context(context, 'https://weibo.com/example/post', wait_ms=0)
        self.assertEqual(captured.exception.code, 'verification_required')

    def test_health_cache_reuses_result_without_launching_again(self):
        context = MagicMock()
        context.new_page.return_value.evaluate.return_value = 'ready'
        from contextlib import nullcontext
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'auto'}), patch('fetchers.browser_runtime.browser_context', return_value=nullcontext((context, 'chromium', '1.63'))) as launch:
            first = browser_capability(refresh=True)
            second = browser_capability()
        self.assertEqual(first, second)
        launch.assert_called_once()

    def test_invalid_mode_reports_error_in_health_instead_of_crashing(self):
        with patch.dict('os.environ', {'STREAMDOCK_BROWSER_MODE': 'invalid'}):
            self.assertEqual(browser_capability(refresh=True)['status'], 'error')


if __name__ == '__main__':
    unittest.main()
