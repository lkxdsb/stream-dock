from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


SESSION_COOKIE = 'streamdock_session'
DESKTOP_ONLY_API_PATHS = {
    '/api/select-output-dir',
    '/api/convert/select-output-dir',
    '/api/open-output-path',
    '/api/open-output-file',
    '/api/reveal-output-file',
}


def _items(name: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in os.getenv(name, '').split(',') if item.strip())


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return None
    default_port = 80 if parsed.scheme == 'http' else 443
    port = parsed.port or default_port
    suffix = '' if port == default_port else f':{port}'
    return f'{parsed.scheme}://{parsed.hostname.lower()}{suffix}'


@dataclass(frozen=True)
class DeploymentSecurity:
    mode: str
    token: str | None
    trusted_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    output_root: Path | None
    errors: tuple[str, ...]

    @property
    def server(self) -> bool:
        return self.mode == 'server'

    def token_matches(self, candidate: str | None) -> bool:
        return bool(self.token and candidate and secrets.compare_digest(self.token, candidate))

    def host_allowed(self, host_header: str) -> bool:
        try:
            hostname = urlsplit(f'//{host_header}').hostname
        except ValueError:
            return False
        return bool(hostname and hostname.lower() in self.trusted_hosts)

    def origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            return True
        normalized = _normalized_origin(origin)
        return bool(normalized and normalized in self.allowed_origins)


def deployment_security() -> DeploymentSecurity:
    raw_mode = os.getenv('STREAMDOCK_MODE', 'desktop').strip().lower()
    # The old LAN switch is treated as server mode now; LAN exposure without
    # authentication is no longer a supported configuration.
    mode = 'server' if raw_mode == 'server' or os.getenv('STREAMDOCK_ALLOW_LAN_API', '0') == '1' else 'desktop'
    errors: list[str] = []
    if raw_mode not in {'desktop', 'server'}:
        errors.append('STREAMDOCK_MODE 只能是 desktop 或 server')
    token = os.getenv('STREAMDOCK_API_TOKEN', '').strip() or None
    trusted_hosts = _items('STREAMDOCK_TRUSTED_HOSTS')
    allowed_origins = tuple(filter(None, (_normalized_origin(value) for value in _items('STREAMDOCK_ALLOWED_ORIGINS'))))
    configured_root = os.getenv('STREAMDOCK_SERVER_OUTPUT_ROOT', '').strip()
    output_root = Path(configured_root).expanduser().resolve() if configured_root else None
    if mode == 'server':
        if not token or len(token) < 24:
            errors.append('server 模式需要至少 24 字符的 STREAMDOCK_API_TOKEN')
        if not trusted_hosts:
            errors.append('server 模式需要 STREAMDOCK_TRUSTED_HOSTS')
        if not allowed_origins:
            errors.append('server 模式需要 STREAMDOCK_ALLOWED_ORIGINS')
        if output_root is None:
            errors.append('server 模式需要 STREAMDOCK_SERVER_OUTPUT_ROOT')
    return DeploymentSecurity(mode, token, trusted_hosts, allowed_origins, output_root, tuple(errors))


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = str(authorization or '').partition(' ')
    return token.strip() if scheme.lower() == 'bearer' and token.strip() else None


def enforce_server_output_root(path: Path) -> Path:
    config = deployment_security()
    resolved = path.expanduser().resolve()
    if not config.server:
        return resolved
    if config.errors or config.output_root is None:
        raise RuntimeError('服务器模式尚未正确配置')
    try:
        resolved.relative_to(config.output_root)
    except ValueError as exc:
        raise RuntimeError(f'服务器模式输出目录必须位于 {config.output_root} 之内') from exc
    return resolved
