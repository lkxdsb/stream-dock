import unittest

from error_catalog import classify_error
from tasks.models import TaskItem, TaskKind


class ErrorCatalogTests(unittest.TestCase):
    def test_upower_preview_has_specific_entitlement_error(self):
        info = classify_error(
            'RuntimeError: Bilibili UP 主专属内容未解锁：当前登录态仅返回 20 秒试看流，无权访问完整资源'
        )

        self.assertEqual(info['code'], 'content_entitlement_required')
        self.assertEqual(info['action'], 'openAdvanced')
        self.assertIn('Cookie', info['message'])

    def test_unsupported_platform_has_stable_non_retryable_code(self):
        info = classify_error('RuntimeError: unsupported platform link')

        self.assertEqual(info['code'], 'unsupported_platform')
        self.assertEqual(info['category'], 'input')
        self.assertFalse(info['retryable'])
        self.assertEqual(info['action'], 'capability')

    def test_provider_capture_failure_is_retryable_without_leaking_traceback(self):
        info = classify_error('Traceback (most recent call last):\nRuntimeError: capture failed in all strategies')

        self.assertEqual(info['code'], 'media_unavailable')
        self.assertTrue(info['retryable'])
        self.assertNotIn('Traceback', info['message'])

    def test_task_contract_exposes_structured_error_info(self):
        task = TaskItem(id='demo', kind=TaskKind.MEDIA, title='demo', payload={}, error='FFmpeg command not found')

        payload = task.to_dict()

        self.assertEqual(payload['errorInfo']['code'], 'dependency_unavailable')
        self.assertEqual(payload['errorInfo']['action'], 'health')

    def test_unknown_error_preserves_only_last_bounded_line(self):
        info = classify_error(f'Traceback line\nRuntimeError: {"x" * 500}')

        self.assertEqual(info['code'], 'unknown_error')
        self.assertLessEqual(len(info['message']), 320)
        self.assertNotIn('Traceback', info['message'])


if __name__ == '__main__':
    unittest.main()
