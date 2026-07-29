from __future__ import annotations

from typing import Any


def _last_error_line(raw: str, fallback: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    last = lines[-1] if lines else fallback
    prefixes = ('ValueError:', 'RuntimeError:', 'TimeoutError:', 'OSError:')
    if ':' in last and any(last.startswith(prefix) for prefix in prefixes):
        last = last.split(':', 1)[1].strip()
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
