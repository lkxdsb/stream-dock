from __future__ import annotations

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.bilibili import BilibiliAdapter
from fetchers.adapters.channels import ChannelsAdapter
from fetchers.adapters.douyin import DouyinAdapter
from fetchers.adapters.kuaishou import KuaishouAdapter
from fetchers.adapters.weibo import WeiboAdapter
from fetchers.adapters.xiaohongshu import XiaohongshuAdapter

try:
    from fetchers.adapters.youtube import YoutubeAdapter
except ModuleNotFoundError:
    YoutubeAdapter = None  # type: ignore[assignment]

try:
    from fetchers.adapters.tiktok import TiktokAdapter
except ModuleNotFoundError:
    TiktokAdapter = None  # type: ignore[assignment]

try:
    from fetchers.adapters.twitter_x import TwitterXAdapter
except ModuleNotFoundError:
    TwitterXAdapter = None  # type: ignore[assignment]


def get_registered_adapters() -> list[BasePlatformAdapter]:
    adapters: list[BasePlatformAdapter] = [
        DouyinAdapter(),
        KuaishouAdapter(),
        BilibiliAdapter(),
        XiaohongshuAdapter(),
        WeiboAdapter(),
        ChannelsAdapter(),
    ]

    if YoutubeAdapter is not None:
        adapters.append(YoutubeAdapter())
    if TiktokAdapter is not None:
        adapters.append(TiktokAdapter())
    if TwitterXAdapter is not None:
        adapters.append(TwitterXAdapter())

    return adapters
