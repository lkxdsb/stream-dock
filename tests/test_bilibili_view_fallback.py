import json
import unittest
from unittest.mock import Mock, patch
import requests
from fetchers.adapters.bilibili import BilibiliAdapter, VIEW_ENDPOINT

URL = 'https://www.bilibili.com/video/BV1xx411c7mD/'
DATA = {'bvid': 'BV1xx411c7mD', 'cid': 101, 'title': '中文测试', 'pic': 'https://example.test/cover.jpg',
        'owner': {'name': '作者'}, 'pages': [{'cid': 101}, {'cid': 202}], 'is_upower_exclusive': False}
PLAY = {'dash': {'video': [{'base_url': 'https://example.test/video.m4s', 'id': 32}],
                 'audio': [{'base_url': 'https://example.test/audio.m4s'}]}}

class ViewFallbackTests(unittest.TestCase):
    def fetch(self, url=URL, data=None, page_error=None, play=None):
        adapter = BilibiliAdapter()
        with patch('fetchers.adapters.bilibili.load_bilibili_cookies', return_value=({'SESSDATA': 'dummy'}, 'manual')), \
             patch('fetchers.adapters.bilibili._get_page_with_scoped_cookies', side_effect=page_error or requests.HTTPError('412 page')), \
             patch.object(adapter, '_fetch_via_view_api', return_value=data or DATA) as view, \
             patch.object(adapter, '_fetch_playurl', return_value=play or PLAY) as player, \
             patch.object(adapter, '_fetch_subtitle_tracks', return_value=[]):
            result = adapter.fetch_media(url)
        return result, view, player

    def test_412_falls_back_and_preserves_metadata_and_auth(self):
        result, view, player = self.fetch()
        self.assertEqual(result.metadata['capture_strategy'], 'api-view-fallback')
        self.assertEqual(result.metadata['metadata_fallback_reason'], '412 page')
        self.assertEqual((result.title, result.author, result.cover_url), ('中文测试', '作者', DATA['pic']))
        self.assertEqual(view.call_args.kwargs['cookies'], {'SESSDATA': 'dummy'})
        self.assertEqual(player.call_args.kwargs['cookies'], {'SESSDATA': 'dummy'})

    def test_requested_part_uses_correct_cid(self):
        result, _, player = self.fetch(URL+'?p=2')
        self.assertEqual(result.metadata['cid'], 202)
        self.assertEqual(player.call_args.kwargs['cid'], 202)

    def test_invalid_part_does_not_silently_download_first(self):
        for p in ('0','3','oops'):
            with self.subTest(p=p), self.assertRaisesRegex(ValueError, '分 P'):
                self.fetch(URL+'?p='+p)

    def test_unsafe_redirect_never_triggers_fallback(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            self.fetch(page_error=ValueError('Unsupported Bilibili redirect host'))

    def test_both_failure_causes_are_preserved(self):
        adapter = BilibiliAdapter()
        with patch('fetchers.adapters.bilibili.load_bilibili_cookies', return_value=(None,None)), \
             patch('fetchers.adapters.bilibili._get_page_with_scoped_cookies', side_effect=requests.HTTPError('412 page')), \
             patch.object(adapter, '_fetch_via_view_api', side_effect=RuntimeError('API -403')):
            with self.assertRaisesRegex(RuntimeError, 'web-page: 412 page; api-view-fallback: API -403'):
                adapter.fetch_media(URL)

    def test_api_request_bv_and_av(self):
        for url,params in ((URL,{'bvid': DATA['bvid']}), ('https://www.bilibili.com/video/av170001/',{'aid':'170001'})):
            with self.subTest(url=url):
                response=Mock(status_code=200); response.json.return_value={'code':0,'data':DATA}
                with patch('fetchers.adapters.bilibili.requests.get',return_value=response) as get:
                    self.assertEqual(BilibiliAdapter()._fetch_via_view_api(url,cookies={'x':'y'}),DATA)
                self.assertEqual(get.call_args.args[0],VIEW_ENDPOINT)
                self.assertEqual(get.call_args.kwargs['params'],params)
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                self.assertEqual(get.call_args.kwargs['cookies'],{'x':'y'})

    def test_api_business_errors_and_bad_payloads(self):
        for payload in ({'code':-403,'message':'blocked'}, [], {'code':0,'data':{}},
                        {'code':0,'data':{**DATA,'pages':[None]}},
                        {'code':0,'data':{**DATA,'cid':None,'pages':[]}},
                        {'code':0,'data':{**DATA,'bvid':'BV1different'}}):
            with self.subTest(payload=payload):
                response=Mock(status_code=200);response.json.return_value=payload
                with patch('fetchers.adapters.bilibili.requests.get',return_value=response), self.assertRaises(RuntimeError):
                    BilibiliAdapter()._fetch_via_view_api(URL)

    def test_preview_rejection_remains_in_force_after_fallback(self):
        play={'timelength':147000,'durl':[{'url':'https://example.test/preview.mp4','length':20000}]}
        with self.assertRaisesRegex(RuntimeError,'UP 主专属'):
            self.fetch(data={**DATA,'is_upower_exclusive':True},play=play)

    def test_playurl_errors_do_not_trigger_metadata_fallback(self):
        adapter=BilibiliAdapter()
        response=Mock(url=URL,text='window.__INITIAL_STATE__='+json.dumps({'videoData':DATA})+';')
        with patch('fetchers.adapters.bilibili.load_bilibili_cookies',return_value=(None,None)), \
             patch('fetchers.adapters.bilibili._get_page_with_scoped_cookies',return_value=response), \
             patch.object(adapter,'_fetch_playurl',side_effect=RuntimeError('playurl permission denied')), \
             patch.object(adapter,'_fetch_via_view_api') as view:
            with self.assertRaisesRegex(RuntimeError,'playurl permission denied'):adapter.fetch_media(URL)
            view.assert_not_called()

    def test_missing_page_state_and_malformed_json_fall_back(self):
        for html in ('<html>risk control</html>', 'window.__INITIAL_STATE__={broken};', 'window.__INITIAL_STATE__={};'):
            adapter=BilibiliAdapter();response=Mock(url=URL,text=html)
            with patch('fetchers.adapters.bilibili.load_bilibili_cookies',return_value=(None,None)), \
                 patch('fetchers.adapters.bilibili._get_page_with_scoped_cookies',return_value=response), \
                 patch.object(adapter,'_fetch_via_view_api',return_value=DATA), \
                 patch.object(adapter,'_fetch_playurl',return_value=PLAY), \
                 patch.object(adapter,'_fetch_subtitle_tracks',return_value=[]):
                self.assertEqual(adapter.fetch_media(URL).metadata['capture_strategy'],'api-view-fallback')
