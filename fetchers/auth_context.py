"""Deployment-scoped, opt-in media credentials; never part of task history."""

from __future__ import annotations

import contextvars
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import requests


PLATFORM_DOMAINS = {
    'bilibili': ('bilibili.com',), 'douyin': ('douyin.com', 'iesdouyin.com'),
    'kuaishou': ('kuaishou.com', 'gifshow.com', 'chenzhongtech.com'),
    'weibo': ('weibo.com', 'weibo.cn'), 'xiaohongshu': ('xiaohongshu.com',),
    'channels': ('weixin.qq.com', 'channels.weixin.qq.com', 'finder.video.qq.com'),
}


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def parse_cookie(raw: str) -> dict[str, str]:
    if len(raw.encode('utf-8')) > 16 * 1024 or any(char in raw for char in '\r\n\0'):
        raise ValueError('Cookie 格式或大小不合法')
    parsed = {}
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            raise ValueError('Cookie 必须使用 name=value 格式')
        name, value = part.split('=', 1)
        name = name.strip()
        if not name or any(char.isspace() for char in name):
            raise ValueError('Cookie 名称不合法')
        parsed[name] = value.strip()
    if not parsed or len(parsed) > 128:
        raise ValueError('Cookie 为空或数量过多')
    return parsed


def parse_cookie_file(platform: str, contents: bytes, *, with_scopes: bool = False):
    """Accept a Cookie header, Netscape jar, or cookie-only Playwright JSON.

    Never import browser localStorage or credentials for another domain.
    """
    if platform not in PLATFORM_DOMAINS or len(contents) > 32 * 1024:
        raise ValueError('授权文件平台或大小不合法')
    try:
        source = contents.decode('utf-8-sig').strip()
    except UnicodeDecodeError as exc:
        raise ValueError('授权文件必须是 UTF-8 文本') from exc
    cookies: dict[str, str] = {}
    scopes: list[dict[str, str]] = []
    if source.startswith('{'):
        try:
            data = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError('授权 JSON 格式不合法') from exc
        if not isinstance(data, dict) or not isinstance(data.get('cookies'), list) or data.get('origins'):
            raise ValueError('仅支持无 localStorage 的 Cookie-only Playwright 状态')
        for item in data['cookies']:
            if not isinstance(item, dict):
                raise ValueError('授权 Cookie 项格式不合法')
            original_domain = str(item.get('domain') or '').lower()
            domain = original_domain.lstrip('.')
            if not _matches(domain, PLATFORM_DOMAINS[platform]) or item.get('path', '/') != '/' or item.get('secure') is False:
                raise ValueError('授权文件含非本平台域名或非根路径 Cookie')
            name, value = item.get('name'), item.get('value')
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError('授权 Cookie 名称或内容不合法')
            cookies[name] = value
            scopes.append({'name': name, 'value': value, 'domain': original_domain, 'path': '/', 'secure': 'true'})
    elif '\t' in source and any(line.startswith('# Netscape HTTP Cookie File') for line in source.splitlines()):
        for line in source.splitlines():
            line = line.removeprefix('#HttpOnly_')
            if not line or line.startswith('#'):
                continue
            fields = line.split('\t')
            if len(fields) != 7:
                raise ValueError('Netscape Cookie 行格式不合法')
            domain, _, path, secure, _, name, value = fields
            if not _matches(domain.lower().lstrip('.'), PLATFORM_DOMAINS[platform]) or path != '/' or secure.upper() != 'TRUE':
                raise ValueError('授权文件含非本平台域名、非根路径或非安全 Cookie')
            cookies[name] = value
            scopes.append({'name': name, 'value': value, 'domain': domain.lower(), 'path': '/', 'secure': 'true'})
    else:
        raw = source.removeprefix('Cookie:').removeprefix('cookie:').strip()
        if '\n' in raw or '\r' in raw:
            raise ValueError('Cookie Header 文件只能包含一行')
        cookies = parse_cookie(raw)
    header = '; '.join(f'{name}={value}' for name, value in cookies.items())
    parse_cookie(header)
    return (header, scopes) if with_scopes else header


@dataclass(frozen=True)
class AuthProfile:
    platform: str
    id: str
    version: int
    cookie: str
    updated_at: str
    persisted: bool = False
    cookie_scopes: tuple[dict[str, str], ...] = ()

    def public(self) -> dict[str, object]:
        return {'platform': self.platform, 'configured': True, 'profileId': self.id,
                'version': self.version, 'updatedAt': self.updated_at,
                'verificationStatus': 'unchecked', 'persisted': self.persisted}


class AuthStore:
    def __init__(self, path: Path | None = None, key: str | None = None):
        self.path = path
        self.key = key
        self._profiles: dict[str, AuthProfile] = {}
        self._verification: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()
        if path and path.exists():
            if not key:
                raise RuntimeError('Encrypted media auth store requires STREAMDOCK_MEDIA_AUTH_KEY')
            from cryptography.fernet import Fernet
            data = json.loads(Fernet(key.encode()).decrypt(path.read_bytes()))
            for row in data.values():
                profile = AuthProfile(**row)
                self._profiles[profile.platform] = profile

    def _persist(self) -> None:
        if not self.path:
            return
        from cryptography.fernet import Fernet
        if not self.key:
            raise RuntimeError('保存授权需要单独配置 STREAMDOCK_MEDIA_AUTH_KEY')
        payload = {key: profile.__dict__ for key, profile in self._profiles.items() if profile.persisted}
        encrypted = Fernet(self.key.encode()).encrypt(json.dumps(payload).encode())
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='.media-auth-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def put(self, platform: str, cookie: str, *, save: bool = False,
            cookie_scopes: list[dict[str, str]] | None = None) -> AuthProfile:
        if platform not in PLATFORM_DOMAINS:
            raise ValueError('不支持的平台授权')
        parse_cookie(cookie)
        if cookie_scopes:
            for item in cookie_scopes:
                if (not _matches(item['domain'].lstrip('.'), PLATFORM_DOMAINS[platform])
                        or item['path'] != '/' or item['secure'] != 'true'):
                    raise ValueError('授权 Cookie 的域、路径或安全属性不合法')
        if save and (not self.path or not self.key):
            raise ValueError('持久化授权需要配置独立加密密钥和存储路径')
        with self._lock:
            old = self._profiles.get(platform)
            profile = AuthProfile(platform, old.id if old else uuid.uuid4().hex,
                                  old.version + 1 if old else 1, cookie,
                                  datetime.now(timezone.utc).isoformat(), save,
                                  tuple(cookie_scopes or ()))
            self._profiles[platform] = profile
            try:
                self._persist()
            except Exception:
                if old:
                    self._profiles[platform] = old
                else:
                    self._profiles.pop(platform, None)
                raise
            self._verification.pop(platform, None)
            return profile

    def get(self, platform: str, profile_id: str | None = None, version: int | None = None) -> AuthProfile | None:
        with self._lock:
            profile = self._profiles.get(platform)
            if profile_id and (profile is None or profile.id != profile_id):
                raise ValueError('平台授权配置已不存在或不属于该平台')
            if version is not None and (profile is None or profile.version != version):
                raise ValueError('排队任务的授权版本已撤销，请重新授权后提交')
            return profile

    def delete(self, platform: str) -> None:
        if platform not in PLATFORM_DOMAINS:
            raise ValueError('不支持的平台授权')
        with self._lock:
            old = self._profiles.pop(platform, None)
            try:
                self._persist()
            except Exception:
                if old:
                    self._profiles[platform] = old
                raise
            self._verification.pop(platform, None)

    def set_verification(self, platform: str, version: int, status: str) -> None:
        with self._lock:
            profile = self._profiles.get(platform)
            if profile and profile.version == version:
                self._verification[platform] = {'verificationStatus': status,
                                                 'verificationCheckedAt': datetime.now(timezone.utc).isoformat()}

    def verification_recent(self, platform: str, seconds: int = 60) -> bool:
        with self._lock:
            checked = self._verification.get(platform, {}).get('verificationCheckedAt')
        if not checked:
            return False
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(str(checked))).total_seconds() < seconds
        except ValueError:
            return False

    def list_public(self) -> list[dict[str, object]]:
        with self._lock:
            rows = []
            ttl_minutes = max(1, min(1440, int(os.getenv('STREAMDOCK_AUTH_VERIFICATION_TTL_MINUTES', '60'))))
            for name in PLATFORM_DOMAINS:
                if name not in self._profiles:
                    rows.append({'platform': name, 'configured': False, 'verificationStatus': 'not_configured'})
                    continue
                row = {**self._profiles[name].public(), **self._verification.get(name, {})}
                checked = row.get('verificationCheckedAt')
                if checked:
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(checked))).total_seconds()
                        if age > ttl_minutes * 60:
                            row['verificationStatus'] = 'unknown'
                            row['verificationStale'] = True
                    except (TypeError, ValueError):
                        row['verificationStatus'] = 'unknown'
                rows.append(row)
            return rows


auth_store = AuthStore(
    Path(os.environ['STREAMDOCK_MEDIA_AUTH_STORE']).expanduser() if os.environ.get('STREAMDOCK_MEDIA_AUTH_STORE') else None,
    os.environ.get('STREAMDOCK_MEDIA_AUTH_KEY'),
)
_current = contextvars.ContextVar('streamdock_media_auth', default=None)


@contextmanager
def use_auth(profile: AuthProfile | None) -> Iterator[None]:
    token = _current.set(profile)
    try:
        yield
    finally:
        _current.reset(token)


def current_auth() -> AuthProfile | None:
    return _current.get()


def cookie_jar(profile: AuthProfile) -> CookieJar:
    jar = requests.cookies.RequestsCookieJar()
    records = profile.cookie_scopes or tuple(
        {'name': name, 'value': value, 'domain': '.' + PLATFORM_DOMAINS[profile.platform][0],
         'path': '/', 'secure': 'true'} for name, value in parse_cookie(profile.cookie).items())
    for item in records:
        jar.set_cookie(requests.cookies.create_cookie(name=item['name'], value=item['value'],
                                                       domain=item['domain'], path=item['path'], secure=True))
    return jar


def scoped_request(method: str, url: str, **kwargs):
    profile = current_auth()
    host = (urlsplit(url).hostname or '').lower()
    if profile and _matches(host, PLATFORM_DOMAINS[profile.platform]):
        if kwargs.get('cookies') is None:
            kwargs['cookies'] = cookie_jar(profile)
    return getattr(requests, method.lower())(url, **kwargs)


def browser_cookies(profile: AuthProfile) -> list[dict[str, object]]:
    records = profile.cookie_scopes or tuple(
        {'name': name, 'value': value, 'domain': '.' + PLATFORM_DOMAINS[profile.platform][0],
         'path': '/', 'secure': 'true'} for name, value in parse_cookie(profile.cookie).items())
    return [{'name': item['name'], 'value': item['value'], 'domain': item['domain'], 'path': item['path'],
             'secure': True, 'httpOnly': False, 'sameSite': 'Lax'}
            for item in records]
