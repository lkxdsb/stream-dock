"""Conservative share-text extraction and bounded Weibo short-link handling."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from fetchers.adapters.common import get_url_host, host_matches

URL_RE = re.compile(r'https?://[^\s]+', re.I)
TRAILING = '.,，。!！?？)]）]】'
WEIBO_HOSTS = ('weibo.com', 'weibo.cn', 'video.h5.weibo.cn')
SHARE_HOSTS = ('bilibili.com', 'b23.tv', 'douyin.com', 'iesdouyin.com', 'kuaishou.com',
               'gifshow.com', 'chenzhongtech.com', 'weibo.com', 'weibo.cn',
               'xiaohongshu.com', 'xhslink.com', 'weixin.qq.com', 'qq.com')


def normalize_share_url(raw: str) -> str:
    match = URL_RE.search(str(raw or ''))
    if not match:
        raise ValueError('No URL found in input link text')
    url = match.group(0).rstrip(TRAILING)
    host = get_url_host(url)
    if host == 't.cn':
        for _ in range(3):
            response = requests.get(url, timeout=6, allow_redirects=False,
                                    headers={'User-Agent': 'Mozilla/5.0'})
            location = str(response.headers.get('location') or '')
            response.close()
            if not location:
                raise ValueError('微博短链未返回目标地址')
            target = urljoin(url, location)
            target_host = get_url_host(target)
            if not target_host or not (target_host == 't.cn' or host_matches(target_host, SHARE_HOSTS)):
                raise ValueError('微博短链跳转到不受支持的目标')
            url = target
            if target_host != 't.cn':
                break
        if get_url_host(url) == 't.cn':
            raise ValueError('微博短链跳转过多')
        host = get_url_host(url)
    if host in {'video.weibo.com', 'video.h5.weibo.cn'}:
        parsed = urlsplit(url)
        if host == 'video.weibo.com':
            fid = (parse_qs(parsed.query).get('fid') or [''])[0]
        else:
            fid = (parsed.path.strip('/').split('/') or [''])[0]
        if not re.fullmatch(r'1034:\d+', fid):
            raise ValueError('Unsupported Weibo video link variant: missing fid')
        return f'https://weibo.com/tv/show/{fid}'
    return url
