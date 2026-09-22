from __future__ import annotations

from typing import Any
import re
import requests


def _last_error_line(raw: str, fallback: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    last = lines[-1] if lines else fallback
    prefixes = ('ValueError:', 'RuntimeError:', 'TimeoutError:', 'OSError:')
    if ':' in last and any(last.startswith(prefix) for prefix in prefixes):
        last = last.split(':', 1)[1].strip()
    last = re.sub(r'https?://[^\s]+', '[url]', last, flags=re.I)
    last = re.sub(r'(?i)\b(?:cookie|authorization)\s*:\s*[^\r\n]+', '[credential]', last)
    last = re.sub(r'(?i)(?:SESSDATA|bili_jct|sessionid|cookie)=([^\s;]+)', '[credential]', last)
    return f'{last[:317]}...' if len(last) > 320 else last


def classify_error(raw_error: str | None, *, fallback: str = '操作失败') -> dict[str, Any]:
    """Map unstable provider/runtime errors to a stable public contract."""
    raw = str(raw_error or '').strip()
    lowered = raw.lower()

    def result(
        code: str,
        category: str,
        title: str,
        message: str,
        *,
        retryable: bool,
        action: str,
        action_label: str,
    ) -> dict[str, Any]:
        return {
            'code': code,
            'category': category,
            'title': title,
            'message': message,
            'retryable': retryable,
            'action': action,
            'actionLabel': action_label,
        }

    if not raw:
        return result('unknown_error', 'unknown', '任务未完成', fallback, retryable=True, action='logs', action_label='查看运行记录')
    if 'browser unavailable:' in lowered or 'run "playwright install chrome"' in lowered:
        return result('browser_unavailable', 'environment', '浏览器解析不可用', '请管理员检查浏览器运行环境；纯 HTTP 解析仍可使用。', retryable=False, action='health', action_label='检查环境')
    if 'browser concurrency limit reached' in lowered:
        return result('browser_busy', 'environment', '浏览器解析繁忙', '请稍后再试。', retryable=True, action='retry', action_label='稍后重试')
    if any(marker in lowered for marker in ('captcha', 'verification required', 'challenge required')) or any(marker in raw for marker in ('验证码', '安全验证', '人机验证')):
        return result('verification_required', 'provider', '平台要求交互验证', '请先在平台完成验证；自动解析不会绕过验证。', retryable=False, action='auth', action_label='检查平台授权')
    if 'unsupported weibo video link variant' in lowered:
        return result('unsupported_link_variant', 'input', '暂不支持的微博视频地址', '该分享地址缺少可识别的视频标识，请提供完整作品链接。', retryable=False, action='reselect', action_label='重新输入链接')
    if '412 client error' in lowered or '403 client error' in lowered:
        return result('upstream_access_rejected', 'provider', '平台拒绝访问', '当前访问条件被平台拒绝，请检查访问环境。', retryable=False, action='logs', action_label='查看诊断')
    if '429 client error' in lowered:
        return result('rate_limited', 'provider', '平台请求受限', '请等待平台限流解除后再试。', retryable=True, action='retry', action_label='稍后重试')
    if '授权版本已撤销' in raw or '授权配置已失效' in raw or '授权配置已不存在' in raw:
        return result('authorization_revoked', 'authorization', '任务授权已撤销', '请重新授权后提交任务；不会自动改用新账号。', retryable=False, action='auth', action_label='重新授权')
    if any(marker in lowered for marker in ('cookie expired', 'session expired', 'authorization expired')) or any(marker in raw for marker in ('登录态已失效', '授权已过期')):
        return result('authorization_expired', 'authorization', '平台授权已失效', '请更新该平台授权后重新提交。', retryable=False, action='auth', action_label='更新授权')
    if 'resource invalid' in lowered or '资源返回非媒体内容' in raw:
        return result('resource_invalid', 'resource', '候选资源无效', '平台返回的候选地址不是可下载媒体，请重新解析或切换候选流。', retryable=True, action='retry', action_label='重新解析')
    if 'resource unverified' in lowered or '资源尚未核实' in raw:
        return result('resource_unverified', 'resource', '候选资源待核实', '仅取得媒体元数据，尚未证明候选资源可下载。', retryable=True, action='retry', action_label='重新核实')
    if '取消' in raw or 'cancelled' in lowered or 'canceled' in lowered:
        return result('task_cancelled', 'task', '任务已取消', '任务记录已保留，可以重新提交。', retryable=True, action='retry', action_label='重新提交')
    if 'no space' in lowered or '磁盘空间' in raw or 'disk full' in lowered:
        return result('disk_space_insufficient', 'storage', '磁盘空间不足', '请清理空间或更换输出目录后再次执行。', retryable=True, action='settings', action_label='打开保存设置')
    if 'up 主专属' in lowered or 'upower' in lowered:
        return result(
            'content_entitlement_required',
            'authorization',
            '当前账号未解锁 UP 主专属内容',
            '平台只返回了试看片段。请使用已解锁该内容的账号 Cookie 重试；大会员不代表已解锁 UP 主专属内容。',
            retryable=True,
            action='openAdvanced',
            action_label='更换授权信息',
        )
    if any(marker in lowered for marker in ('cookie', 'login required', 'sign in', 'unauthorized', 'forbidden')) or any(marker in raw for marker in ('需要登录', '登录态', '无权访问', '没有权限')):
        return result('authentication_required', 'authorization', '当前内容需要登录或权限', '请确认浏览器登录态，或在高级选项中补充授权信息后重试。', retryable=True, action='openAdvanced', action_label='打开高级选项')
    if 'unsupported platform link' in lowered or '暂不支持该平台' in raw or '不支持当前链接' in raw:
        return result('unsupported_platform', 'input', '暂不支持当前链接', '暂不支持该平台或链接格式，请确认复制的是视频分享链接。', retryable=False, action='capability', action_label='查看支持平台')
    if any(marker in lowered for marker in ('invalid url', 'invalid link', 'malformed url')) or any(marker in raw for marker in ('链接格式错误', '无效链接', '请输入链接')):
        return result('invalid_link', 'input', '链接格式不正确', '请粘贴完整的视频分享链接后重新识别。', retryable=False, action='reselect', action_label='重新输入链接')
    if any(marker in lowered for marker in ('capture failed in all strategies', 'window._router_data', 'no media url captured')) or any(marker in raw for marker in ('未能从页面提取', '分享链接已过期', '媒体资源不存在')):
        return result('media_unavailable', 'provider', '未找到可用媒体资源', '分享链接可能已过期，或平台返回了风控页面。请重新复制链接后重试。', retryable=True, action='retry', action_label='重新识别')
    if 'requested video quality not found' in lowered or '所选清晰度已失效' in raw:
        return result('quality_unavailable', 'provider', '所选清晰度已失效', '请重新识别可用清晰度后再试。', retryable=True, action='retry', action_label='重新识别')
    if 'timeout' in lowered or 'timed out' in lowered or '超时' in raw:
        return result('operation_timeout', 'runtime', '处理超时', '平台响应较慢或文件较大，可以稍后重新执行。', retryable=True, action='retry', action_label='重新执行')
    if any(marker in lowered for marker in ('ffmpeg', 'ffprobe', 'mineru', 'command not found', 'no such file or directory')) or any(marker in raw for marker in ('引擎不可用', '缺少依赖', '依赖不可用')):
        return result('dependency_unavailable', 'environment', '本地依赖不可用', '请检查 FFmpeg、PDF 引擎或相关转换依赖。', retryable=False, action='health', action_label='检查本地环境')
    if any(marker in lowered for marker in ('connection refused', 'connection reset', 'network is unreachable', 'name resolution', 'http error')) or any(marker in raw for marker in ('网络连接失败', '网络不可用')):
        return result('network_unavailable', 'network', '网络连接失败', '请检查网络后重新执行；平台临时资源链接也可能已经失效。', retryable=True, action='retry', action_label='重新执行')

    return result('unknown_error', 'unknown', '这次没有成功完成', _last_error_line(raw, fallback) or fallback, retryable=True, action='logs', action_label='查看运行记录')


def classify_probe_exception(exc: Exception) -> dict[str, Any]:
    """Classify typed parser failures before legacy message heuristics."""
    from fetchers.errors import MediaProbeError
    info = classify_error(str(exc), fallback='链接探测失败')
    if isinstance(exc, MediaProbeError):
        info.update(code=exc.code, stage=exc.stage, retryable=exc.retryable)
        if exc.action:
            info['action'] = exc.action
        if exc.retry_after is not None:
            info['retryAfter'] = exc.retry_after
        if exc.platform:
            info['platform'] = exc.platform
        if exc.causes:
            info['causes'] = [_last_error_line(cause, '阶段失败') for cause in exc.causes[:3]]
        return info
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        mapping = {
            401: ('authentication_required', 'auth', False, 'auth'),
            403: ('upstream_access_rejected', 'http', False, 'logs'),
            404: ('content_unavailable', 'http', False, 'reselect'),
            412: ('upstream_access_rejected', 'http', False, 'logs'),
            429: ('rate_limited', 'http', True, 'retry'),
        }
        if status in mapping:
            code, stage, retryable, action = mapping[status]
            info.update(code=code, stage=stage, retryable=retryable, action=action)
            info['message'] = {
                401: '平台明确要求登录；请配置该平台授权后重试。',
                403: '平台拒绝当前访问；不能仅据此断定授权过期。',
                404: '平台未找到该内容；请检查分享链接是否仍有效。',
                412: '平台拒绝当前访问条件；请检查服务器网络及平台限制。',
                429: '平台请求受限；请按 Retry-After 等待后重试。',
            }[status]
            if status == 429:
                delay = str(exc.response.headers.get('Retry-After') or '')
                if delay.isdigit():
                    info['retryAfter'] = min(int(delay), 86400)
        else:
            info['stage'] = 'http'
    elif isinstance(exc, requests.Timeout):
        info.update(code='network_timeout', stage='network', retryable=True)
    elif isinstance(exc, requests.ConnectionError):
        info.update(code='network_unavailable', stage='network', retryable=True)
    elif isinstance(exc, ValueError):
        info['stage'] = 'auth' if '授权' in str(exc) else 'normalization'
    else:
        info.setdefault('stage', 'parser')
    return info
