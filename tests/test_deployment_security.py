import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''

from app import app
from deployment_security import bearer_token, deployment_security, enforce_server_output_root
from runtime_checks import prepare_output_directory


TOKEN = 'm9-test-token-with-at-least-24-characters'


def server_environment(root: Path) -> dict[str, str]:
    return {
        'STREAMDOCK_MODE': 'server',
        'STREAMDOCK_ALLOW_LAN_API': '0',
        'STREAMDOCK_API_TOKEN': TOKEN,
        'STREAMDOCK_TRUSTED_HOSTS': 'streamdock.test',
        'STREAMDOCK_ALLOWED_ORIGINS': 'http://streamdock.test',
        'STREAMDOCK_SERVER_OUTPUT_ROOT': str(root),
    }


class DeploymentSecurityUnitTests(unittest.TestCase):
    def test_server_mode_fails_closed_when_required_settings_are_missing(self):
        with patch.dict(os.environ, {
            'STREAMDOCK_MODE': 'server',
            'STREAMDOCK_ALLOW_LAN_API': '0',
            'STREAMDOCK_API_TOKEN': '',
            'STREAMDOCK_TRUSTED_HOSTS': '',
            'STREAMDOCK_ALLOWED_ORIGINS': '',
            'STREAMDOCK_SERVER_OUTPUT_ROOT': '',
        }, clear=False):
            config = deployment_security()
        self.assertTrue(config.server)
        self.assertEqual(len(config.errors), 4)

    def test_token_host_origin_and_bearer_checks_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, server_environment(Path(tmp)), clear=False):
            config = deployment_security()
            self.assertTrue(config.token_matches(TOKEN))
            self.assertFalse(config.token_matches(TOKEN + 'x'))
            self.assertTrue(config.host_allowed('streamdock.test:80'))
            self.assertFalse(config.host_allowed('evil.test'))
            self.assertTrue(config.origin_allowed('http://streamdock.test'))
            self.assertFalse(config.origin_allowed('https://streamdock.test'))
            self.assertEqual(bearer_token(f'Bearer {TOKEN}'), TOKEN)

    def test_server_output_is_confined_to_configured_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'outputs'
            outside = Path(tmp) / 'outside'
            with patch.dict(os.environ, server_environment(root), clear=False):
                allowed_path = enforce_server_output_root(root / 'job')
                allowed = prepare_output_directory(allowed_path, minimum_free_bytes=0)
                self.assertEqual(Path(allowed['path']), (root / 'job').resolve())
                with self.assertRaisesRegex(RuntimeError, '必须位于'):
                    enforce_server_output_root(outside)


class DeploymentSecurityHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_requires_auth_and_keeps_liveness_public(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, server_environment(Path(tmp)), clear=False):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://streamdock.test') as client:
                live = await client.get('/api/health')
                denied = await client.get('/api/convert/capabilities')
                accepted = await client.get('/api/convert/capabilities', headers={'Authorization': f'Bearer {TOKEN}'})
            self.assertEqual(live.status_code, 200)
            self.assertEqual(live.json()['mode'], 'server')
            self.assertEqual(denied.status_code, 401)
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.headers['x-frame-options'], 'DENY')

    async def test_browser_login_sets_httponly_session_and_origin_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, server_environment(Path(tmp)), clear=False):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://streamdock.test', follow_redirects=False) as client:
                redirect = await client.get('/convert')
                bad_origin = await client.post('/auth', data={'apiToken': TOKEN}, headers={'Origin': 'https://evil.test'})
                login = await client.post('/auth', data={'apiToken': TOKEN}, headers={'Origin': 'http://streamdock.test'})
                page = await client.get('/convert')
                desktop_only = await client.get('/api/open-output-path')
            self.assertEqual(redirect.status_code, 303)
            self.assertEqual(redirect.headers['location'], '/auth')
            self.assertEqual(bad_origin.status_code, 403)
            self.assertEqual(login.status_code, 303)
            self.assertIn('HttpOnly', login.headers['set-cookie'])
            self.assertIn('SameSite=strict', login.headers['set-cookie'])
            self.assertEqual(page.status_code, 200)
            self.assertEqual(desktop_only.status_code, 403)

    async def test_invalid_server_configuration_fails_closed_but_liveness_reports_it(self):
        invalid = {
            'STREAMDOCK_MODE': 'server',
            'STREAMDOCK_ALLOW_LAN_API': '0',
            'STREAMDOCK_API_TOKEN': '',
            'STREAMDOCK_TRUSTED_HOSTS': '',
            'STREAMDOCK_ALLOWED_ORIGINS': '',
            'STREAMDOCK_SERVER_OUTPUT_ROOT': '',
        }
        with patch.dict(os.environ, invalid, clear=False):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://untrusted.test') as client:
                live = await client.get('/api/health')
                blocked = await client.get('/api/convert/capabilities')
        self.assertEqual(live.status_code, 200)
        self.assertFalse(live.json()['configured'])
        self.assertEqual(blocked.status_code, 503)


if __name__ == '__main__':
    unittest.main()
