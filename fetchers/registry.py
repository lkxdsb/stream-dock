from __future__ import annotations

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.bilibili import BilibiliAdapter
from fetchers.adapters.channels import ChannelsAdapter
from fetchers.adapters.douyin import DouyinAdapter
from fetchers.adapters.kuaishou import KuaishouAdapter
from fetchers.adapters.tiktok import TiktokAdapter
from fetchers.adapters.twitter_x import TwitterXAdapter
from fetchers.adapters.youtube import YoutubeAdapter
from fetchers.adapters.weibo import WeiboAdapter
from fetchers.adapters.xiaohongshu import XiaohongshuAdapter


def get_registered_adapters() -> list[BasePlatformAdapter]:
    return [
        DouyinAdapter(),
        KuaishouAdapter(),
        BilibiliAdapter(),
        XiaohongshuAdapter(),
        WeiboAdapter(),
        ChannelsAdapter(),
        YoutubeAdapter(),
        TiktokAdapter(),
        TwitterXAdapter(),
    ]
