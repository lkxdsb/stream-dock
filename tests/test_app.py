import unittest
import subprocess
import tempfile
import os
import io
from pathlib import Path
from unittest.mock import patch

import httpx

# App tests must never read, create, or clear the user's real task history.
os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''

from app import FetchRequest, app, task_store
from tasks.models import TaskKind
from douyin_fetch import choose_media_capture, merge_streams_to_mp4, validate_output_request


class TestIsolationTests(unittest.TestCase):
    def test_app_uses_in_memory_task_store_during_tests(self):
        self.assertIsNone(task_store.storage_path)


class HomePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_renders_demo_shell_without_real_fetch_form(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('在线使用', text)
        self.assertIn('demo-panel', text)
        self.assertNotIn('id="fetchForm"', text)
        self.assertNotIn('name="outputPath"', text)
        self.assertNotIn('name="outputType"', text)
        self.assertNotIn('name="videoQuality"', text)
        self.assertNotIn('name="bilibiliCookie"', text)

    async def test_home_page_renders_streamdock_landing_content(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('StreamDock', text)
        self.assertIn('从各处而来，归于本地。', text)
        self.assertIn('支持平台', text)
        self.assertIn('抖音', text)
        self.assertIn('快手', text)
        self.assertIn('B站', text)
        self.assertIn('id="taskDetailLayer"', text)

    async def test_home_page_uses_reference_poster_layout(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('class="page-shell"', text)
        self.assertIn('class="hero"', text)
        self.assertIn('class="demo-window"', text)
        self.assertIn('class="bottom"', text)
        self.assertIn('id="topDownloadBtn"', text)
        self.assertIn('id="mainDownloadBtn"', text)
        self.assertNotIn('streamdock-reference.png', text)

    def test_home_hero_top_spacing_is_compact_under_header(self):
        css = Path('static/css/home.css').read_text(encoding='utf-8')
        hero_inner_block = css.split('.hero-inner {', 1)[1].split('}\n\n.hero-title', 1)[0]

        self.assertIn('.hero-inner {', css)
        self.assertIn('align-items: start;', hero_inner_block)
        self.assertIn('padding-top: 60px;', hero_inner_block)
        self.assertIn('padding-bottom: 28px;', hero_inner_block)
        self.assertNotIn('align-items: center;', hero_inner_block)



    async def test_convert_page_renders_file_conversion_workbench(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/convert')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('文件转换中心', text)
        self.assertIn('id="convertFileInput"', text)
        self.assertIn('id="convertCapabilityMatrix"', text)
        self.assertIn('id="convertJumpTasks"', text)
        self.assertIn('/static/css/convert.css', text)
        self.assertIn('/static/js/convert-form.js', text)



    async def test_convert_settings_panel_exposes_common_preferences(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/convert')

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="convertDefaultOutputPath"', html)
        self.assertIn('id="convertSelectDefaultDirButton"', html)
        self.assertIn('id="convertNamingStrategy"', html)
        self.assertIn('id="convertAfterDoneAction"', html)
        self.assertIn('id="convertDefaultLevel"', html)
        self.assertIn('id="convertSaveSettingsButton"', html)
        self.assertIn('/static/js/convert-settings.js', html)

    async def test_convert_page_uses_functional_sidebar_and_separate_matrix_panel(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/convert')

        self.assertEqual(response.status_code, 200)
        html = response.text
        for tab in ['workbench', 'tasks', 'matrix', 'tools', 'settings']:
            self.assertIn(f'data-convert-nav="{tab}"', html)
            self.assertIn(f'data-convert-panel="{tab}"', html)
        sidebar = html.split('<section class="convert-main-shell">', 1)[0]
        self.assertIn('文件转换中心', sidebar)
        self.assertIn('转换任务', sidebar)
        self.assertIn('转换能力矩阵', sidebar)
        self.assertIn('专业工具推荐', sidebar)
        self.assertIn('转换设置', sidebar)
        self.assertNotIn('文件类型', sidebar)
        self.assertNotIn('data-convert-type="document"', sidebar)

    async def test_convert_page_uses_world_model_type_filters_without_top_filter_card(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/convert')

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertNotIn('convert-filter-card', html)
        self.assertNotIn('data-convert-filter="stable"', html)
        self.assertIn('convert-world-types', html)
        self.assertIn('data-convert-type="document"', html)
        self.assertIn('data-convert-type="image"', html)
        self.assertIn('data-convert-type="media"', html)
        self.assertIn('data-count-for="document"', html)

    async def test_convert_capabilities_api_exposes_stable_basic_and_vendor_paths(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/api/convert/capabilities')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        levels = {item['level'] for item in data['capabilities']}
        self.assertTrue({'stable', 'basic', 'vendor'}.issubset(levels))
        keys = {item['key'] for item in data['capabilities']}
        self.assertIn('csv:xlsx', keys)
        self.assertIn('pdf:docx', keys)

    async def test_convert_probe_and_run_csv_to_json(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            probe = await client.post('/api/convert/probe', files={'file': ('sample.csv', b'name,age\nAda,12\n', 'text/csv')})
            with tempfile.TemporaryDirectory() as tmp:
                run = await client.post(
                    '/api/convert/run',
                    files={'file': ('sample.csv', b'name,age\nAda,12\n', 'text/csv')},
                    data={'inputType': 'csv', 'outputType': 'json', 'outputPath': tmp},
                )
                self.assertEqual(run.status_code, 200)
                body = run.json()
                self.assertTrue(body['success'])
                self.assertTrue(Path(body['outputPath']).exists())

        self.assertEqual(probe.status_code, 200)
        self.assertEqual(probe.json()['source'], 'csv')
        self.assertTrue(any(item['target'] == 'json' for item in probe.json()['options']))

    async def test_use_page_renders_real_tooling_fields_and_logs(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/use')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('id="fetchForm"', text)
        self.assertIn('name="link"', text)
        self.assertIn('name="outputPath"', text)
        self.assertIn('name="outputType"', text)
        self.assertIn('name="videoQuality"', text)
        self.assertIn('name="bilibiliCookie"', text)
        self.assertIn('开始解析', text)
        self.assertIn('id="logOutput"', text)
        self.assertIn('id="resultPlatform"', text)
        self.assertIn('id="resultError"', text)
        self.assertIn('id="qualityHint"', text)
        self.assertIn('id="mediaProbePreview"', text)
        self.assertIn('id="mediaProbeSummary"', text)
        self.assertIn('id="mediaProbeDetailGrid"', text)
        self.assertIn('id="mediaProbeToggle"', text)
        self.assertIn('id="selectOutputDirButton"', text)
        self.assertIn('readonly', text)
        for tab in ['parse', 'downloading', 'completed', 'settings']:
            self.assertIn(f'data-use-tab="{tab}"', text)
            self.assertIn(f'data-use-panel="{tab}"', text)
        self.assertIn('id="downloadingTasks"', text)
        self.assertIn('id="completedTasks"', text)
        self.assertIn('value="skipped"', text)
        self.assertIn('id="settingsForm"', text)
        self.assertIn('id="recentOpenDirectoryButton"', text)
        self.assertIn('视频下载完成后立即可用', text)

    def test_task_center_filters_and_detail_drawer_are_interactive(self):
        script = Path('static/js/task-center.js').read_text(encoding='utf-8')
        styles = Path('static/css/components.css').read_text(encoding='utf-8')

        self.assertIn("addEventListener('change', rerenderFilteredTasks)", script)
        self.assertIn("addEventListener('search', rerenderFilteredTasks)", script)
        self.assertIn('function renderMediaFinished()', script)
        self.assertIn('没有符合条件的记录。', script)
        self.assertIn('没有符合条件的转换任务。', script)
        self.assertIn('function additionalDetailRows(task)', script)
        self.assertIn('data-delete-task-record', script)
        self.assertIn('data-delete-detail', script)
        self.assertIn('function deleteTaskRecord(taskId)', script)
        self.assertIn('function openConvertTasks(taskId)', script)
        self.assertIn('function subtitleJobActive(task)', script)
        self.assertIn('视频已可用，字幕正在后台识别', script)
        self.assertIn('data-open-directory-card', script)
        self.assertIn('字幕处理（独立后台任务）', script)
        self.assertIn('data-task-id', script)
        self.assertIn('result.author', script)
        self.assertIn('result.stdout', script)
        self.assertIn('max-height: 100dvh;', styles)
        self.assertIn('-webkit-overflow-scrolling: touch;', styles)
        self.assertIn('white-space: pre-wrap;', styles)

    def test_probe_preview_renders_resource_detail_card(self):
        script = Path('static/js/use-form.js').read_text(encoding='utf-8')
        styles = Path('static/css/use.css').read_text(encoding='utf-8')

        self.assertIn('mediaProbeSummary', script)
        self.assertIn('mediaProbeDetailGrid', script)
        self.assertIn('将语音识别字幕', script)
        self.assertIn("document.getElementById('mediaProbeDetails')", script)
        self.assertIn("setAttribute('aria-expanded'", script)
        self.assertIn('下载提示', script)
        self.assertIn('资源大小', script)
        self.assertIn('stream.filesizeLabel', script)
        self.assertIn('.media-probe-summary', styles)
        self.assertIn('.media-probe-detail-grid', styles)
        self.assertIn('.media-probe-toggle', styles)
        self.assertIn('object-fit: contain', styles)
        self.assertIn("frame.style.setProperty('--media-cover-aspect'", script)
        self.assertIn("frame.style.setProperty('--media-cover-width'", script)
        self.assertIn("frame.style.setProperty('--media-cover-height'", script)
        self.assertIn("metrics.orientation === 'square'", script)
        self.assertIn('aspect-ratio: var(--media-cover-aspect, 16 / 9);', styles)
        self.assertIn('"cover main facts"', styles)
        self.assertIn('grid-area: summary;', styles)
        self.assertNotIn('.media-probe-cover-wrap.is-portrait .media-probe-cover { object-fit: cover; }', styles)

    async def test_base_template_loads_split_css_and_use_js_assets(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            home_response = await client.get('/')
            use_response = await client.get('/use')
            platforms_response = await client.get('/platforms')

        self.assertIn('/static/css/base.css', home_response.text)
        self.assertIn('/static/css/header.css', home_response.text)
        self.assertIn('/static/css/components.css', home_response.text)
        self.assertIn('/static/js/main.js', use_response.text)
        self.assertIn('/static/js/use-form.js', use_response.text)
        self.assertIn('/static/js/use-quality.js', use_response.text)
        self.assertIn('/static/js/use-logs.js', use_response.text)
        self.assertIn('/static/js/use-result.js', use_response.text)
        self.assertIn('/static/js/use-tabs.js', use_response.text)
        self.assertIn('/static/css/platforms.css', platforms_response.text)
        self.assertIn('/static/js/platforms.js', platforms_response.text)

    async def test_updates_log_is_a_dedicated_page_not_home_section(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            home_response = await client.get('/')
            updates_response = await client.get('/updates')

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(updates_response.status_code, 200)
        self.assertNotIn('home-updates', home_response.text)
        self.assertIn('href="/updates"', home_response.text)
        self.assertIn('StreamDock · 更新日志', updates_response.text)
        self.assertIn('updates-timeline', updates_response.text)
        self.assertIn('产品时间线', updates_response.text)

    async def test_header_uses_github_octocat_icon_and_page_transition_hooks(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('class="github-mark"', text)
        self.assertIn('aria-hidden="true"', text)
        self.assertIn('viewBox="0 0 16 16"', text)
        self.assertNotIn('◑ GitHub', text)

        base_css = Path('static/css/base.css').read_text(encoding='utf-8')
        header_css = Path('static/css/header.css').read_text(encoding='utf-8')
        main_js = Path('static/js/main.js').read_text(encoding='utf-8')
        self.assertIn('@keyframes page-enter', base_css)
        self.assertIn('body.is-page-leaving .page-shell', base_css)
        self.assertIn('navigateWithTransition', main_js)
        self.assertIn('data-transition-link', text)
        self.assertIn('.github-mark', header_css)

    def test_page_transitions_use_smoother_view_transition_fallback(self):
        base_css = Path('static/css/base.css').read_text(encoding='utf-8')
        main_js = Path('static/js/main.js').read_text(encoding='utf-8')

        self.assertIn('@view-transition {', base_css)
        self.assertIn('navigation: auto;', base_css)
        self.assertIn('::view-transition-old(root)', base_css)
        self.assertIn('::view-transition-new(root)', base_css)
        self.assertIn('@keyframes streamdock-view-old', base_css)
        self.assertIn('@keyframes streamdock-view-new', base_css)
        self.assertIn('filter: blur(8px);', base_css)
        self.assertIn('cubic-bezier(.16, 1, .3, 1)', base_css)
        self.assertIn('page-enter .72s', base_css)
        self.assertIn('streamdock-view-old .48s', base_css)
        self.assertIn('streamdock-view-new .68s', base_css)
        self.assertIn('opacity .38s', base_css)
        self.assertIn('body.is-page-transitioning', base_css)
        self.assertIn("document.body.classList.add('is-page-transitioning')", main_js)
        self.assertIn('380', main_js)

    def test_frontend_scripts_are_split_by_page_and_feature(self):
        home_script = Path('static/js/home-demo.js')
        main_script = Path('static/js/main.js')
        use_form_script = Path('static/js/use-form.js')
        use_quality_script = Path('static/js/use-quality.js')
        use_logs_script = Path('static/js/use-logs.js')
        use_result_script = Path('static/js/use-result.js')
        platforms_script = Path('static/js/platforms.js')
        for path in [home_script, main_script, use_form_script, use_quality_script, use_logs_script, use_result_script, platforms_script]:
            self.assertTrue(path.exists(), f'{path} should exist')

    def test_use_sidebar_and_header_match_platforms_layout_scale(self):
        css = Path('static/css/use.css').read_text(encoding='utf-8')
        platforms_css = Path('static/css/platforms.css').read_text(encoding='utf-8')
        use_html = Path('templates/use.html').read_text(encoding='utf-8')
        platforms_html = Path('templates/platforms.html').read_text(encoding='utf-8')
        header_css = Path('static/css/header.css').read_text(encoding='utf-8')
        self.assertIn('class="use-body"', use_html)
        self.assertIn('use-sidebar-brand', use_html)
        self.assertIn('sidebar-item-icon', use_html)
        self.assertIn('sidebar-item-copy', use_html)
        self.assertIn('sidebar-item-title', use_html)
        self.assertIn('sidebar-item-subtitle', use_html)
        self.assertIn('sidebar-item-icon', platforms_html)
        self.assertIn('sidebar-item-copy', platforms_html)
        self.assertIn('sidebar-item-title', platforms_html)
        self.assertIn('sidebar-item-subtitle', platforms_html)
        self.assertIn('padding-left: 240px;', css)
        self.assertIn('grid-template-columns: 1fr;', css)
        self.assertIn('.use-sidebar {\n  position: fixed;', css)
        self.assertIn('width: 240px;', css)
        self.assertIn('height: 100vh;', css)
        self.assertIn('padding: 28px 22px 24px 24px;', css)
        self.assertIn('margin-top: 56px;', css)
        for shared_rule in [
            'grid-template-columns: 18px minmax(0, 1fr);',
            'font-size: 16px;',
            'font-weight: 660;',
            'font-size: 12px;',
            'margin-top: 8px;',
        ]:
            self.assertIn(shared_rule, css)
            self.assertIn(shared_rule, platforms_css)
        self.assertIn('.use-body .header-inner,\n.platforms-body .header-inner,\n.convert-body .header-inner,\n.pdf-body .header-inner {', header_css)
        self.assertIn('padding-left: 40px;', header_css)
        self.assertIn('white-space: nowrap;', header_css)
        self.assertIn('grid-template-columns: 240px minmax(0, 1fr) 270px;', header_css)
        self.assertIn('visibility: visible;', header_css)
        self.assertNotIn('visibility: hidden;', header_css)
        self.assertNotIn('height: 72px;', header_css)
        self.assertIn('width: 240px;', platforms_css)

    def test_platforms_sidebar_extends_to_top_without_changing_header_content(self):
        css = Path('static/css/platforms.css').read_text(encoding='utf-8')
        platforms_html = Path('templates/platforms.html').read_text(encoding='utf-8')
        header_css = Path('static/css/header.css').read_text(encoding='utf-8')
        self.assertIn('class="platforms-body"', platforms_html)
        self.assertIn('platform-sidebar-brand', platforms_html)
        self.assertIn('.platform-category-nav {\n  position: fixed;', css)
        self.assertIn('top: 0;', css)
        self.assertIn('height: 100vh;', css)
        self.assertIn('.platforms-body .header-inner,', header_css)
        self.assertIn('padding-left: 40px;', header_css)
        self.assertIn('platform-category-icon', platforms_html)

    def test_platforms_page_removes_top_hero_summary_block(self):
        css = Path('static/css/platforms.css').read_text(encoding='utf-8')
        platforms_html = Path('templates/platforms.html').read_text(encoding='utf-8')
        self.assertIn('margin-top: 56px;', css)
        self.assertIn('.platforms-workspace {\n  padding: 24px 0 64px;', css)
        self.assertNotIn('class="platforms-hero"', platforms_html)
        self.assertNotIn('class="platforms-stats"', platforms_html)
        self.assertNotIn('覆盖主流视频与社交平台。', platforms_html)
        self.assertNotIn('.platforms-hero', css)
        self.assertNotIn('.platforms-stats', css)

    def test_use_and_platforms_pages_share_lightweight_workspace_heading(self):
        use_html = Path('templates/use.html').read_text(encoding='utf-8')
        platforms_html = Path('templates/platforms.html').read_text(encoding='utf-8')
        use_css = Path('static/css/use.css').read_text(encoding='utf-8')
        platforms_css = Path('static/css/platforms.css').read_text(encoding='utf-8')

        for html in [use_html, platforms_html]:
            self.assertIn('class="workspace-heading"', html)
            self.assertIn('class="workspace-eyebrow"', html)
            self.assertIn('class="workspace-title"', html)
            self.assertIn('class="workspace-description"', html)

        self.assertIn('Online workspace', use_html)
        self.assertIn('在线解析工作台', use_html)
        self.assertIn('Capability matrix', platforms_html)
        self.assertIn('平台能力矩阵', platforms_html)

        for css in [use_css, platforms_css]:
            self.assertIn('.workspace-heading {', css)
            self.assertIn('padding-bottom: 18px;', css)
            self.assertIn('border-bottom: 1px solid rgba(50,43,36,.14);', css)
            self.assertIn('.workspace-title {', css)
            self.assertIn('font-size: 30px;', css)

    def test_use_page_keeps_only_workspace_heading_without_panel_subtitles(self):
        use_html = Path('templates/use.html').read_text(encoding='utf-8')
        use_css = Path('static/css/use.css').read_text(encoding='utf-8')

        self.assertIn('在线解析工作台', use_html)
        self.assertNotIn('use-panel-title', use_html)
        self.assertNotIn('use-panel-subtitle', use_html)
        self.assertNotIn('class="panel-title', use_html)
        self.assertNotIn('class="panel-subtitle', use_html)
        self.assertNotIn('.use-panel-title', use_css)
        self.assertNotIn('.use-panel-subtitle', use_css)

    def test_platform_matrix_uses_official_icon_files_instead_of_generated_marks(self):
        script = Path('static/js/platforms.js').read_text(encoding='utf-8')
        css = Path('static/css/platforms.css').read_text(encoding='utf-8')
        icon_dir = Path('static/icons/platforms/svg')
        self.assertIn("iconSrc: '/static/icons/platforms/svg/douyin.svg'", script)
        self.assertIn('platform-logo-img', script)
        self.assertIn('renderPlatformIcon', script)
        self.assertNotIn('icon-shape', script)
        self.assertNotIn('.platform-logo-douyin .icon-shape', css)
        for icon_name in ['douyin.svg', 'bilibili.svg', 'kuaishou.svg', 'xiaohongshu.svg', 'weibo.svg', 'channels.svg']:
            self.assertTrue((icon_dir / icon_name).exists(), f'{icon_name} should be stored locally')

    async def test_platforms_page_renders_interactive_capability_matrix(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/platforms')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('支持平台', text)
        self.assertIn('平台能力矩阵', text)
        self.assertIn('href="/platforms"', text)
        self.assertIn('data-platform-category="domestic"', text)
        self.assertIn('data-platform-category="overseas"', text)
        self.assertIn('data-platform-category="experimental"', text)
        self.assertIn('id="platformMatrix"', text)
        self.assertIn('id="platformDetail"', text)
        for platform in ['抖音', 'B站', '快手', '小红书', '微博', '视频号', 'YouTube', 'TikTok', 'X / Twitter']:
            self.assertIn(platform, text)


class OutputDirectoryDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_output_dir_api_returns_chosen_directory(self):
        from unittest.mock import patch

        completed = subprocess.CompletedProcess(
            ['osascript'],
            0,
            stdout='/Users/demo/Downloads/StreamDock\n',
            stderr='',
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.sys.platform', 'darwin'), patch('app.subprocess.run', return_value=completed) as run_mock:
                response = await client.post('/api/select-output-dir')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['path'], '/Users/demo/Downloads/StreamDock')
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], 'osascript')
        self.assertIn('choose folder', command[-1])

    async def test_select_output_dir_api_reports_cancelled_dialog(self):
        from unittest.mock import patch

        completed = subprocess.CompletedProcess(
            ['osascript'],
            1,
            stdout='',
            stderr='User canceled.',
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.sys.platform', 'darwin'), patch('app.subprocess.run', return_value=completed):
                response = await client.post('/api/select-output-dir')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['path'], None)
        self.assertIn('取消', data['error'])


class BatchConversionApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_convert_probe_applies_upload_size_limit(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.MAX_CONVERT_FILE_BYTES', 4, create=True):
                response = await client.post(
                    '/api/convert/probe',
                    files={'file': ('large.csv', b'name\nAda\n', 'text/csv')},
                )
        self.assertEqual(response.status_code, 413)

    async def test_convert_probe_rejects_obvious_extension_spoofing(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post(
                '/api/convert/probe',
                files={'file': ('fake.csv', b'%PDF-1.7\n', 'text/csv')},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('扩展名不一致', response.json()['error'])

    async def test_convert_batch_probe_accepts_same_source_files(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post(
                '/api/convert/batch-probe',
                files=[
                    ('files', ('a.csv', b'name\nAda\n', 'text/csv')),
                    ('files', ('b.csv', b'name\nBob\n', 'text/csv')),
                ],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['source'], 'csv')
        self.assertEqual(data['fileCount'], 2)
        self.assertTrue(any(item['target'] == 'json' for item in data['options']))

    async def test_convert_batch_probe_rejects_mixed_sources(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post(
                '/api/convert/batch-probe',
                files=[
                    ('files', ('a.csv', b'name\nAda\n', 'text/csv')),
                    ('files', ('b.tsv', b'name\nBob\n', 'text/tab-separated-values')),
                ],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('同一种输入格式', data['error'])

    async def test_convert_batch_run_creates_convert_tasks(self):
        task_store.clear(TaskKind.CONVERT)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with tempfile.TemporaryDirectory() as tmp:
                response = await client.post(
                    '/api/convert/batch-run',
                    files=[
                        ('files', ('a.csv', b'name\nAda\n', 'text/csv')),
                        ('files', ('b.csv', b'name\nBob\n', 'text/csv')),
                    ],
                    data={'inputType': 'csv', 'outputType': 'json', 'outputPath': tmp},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'], data.get('logs'))
        self.assertEqual(data['successCount'], 2)
        self.assertEqual(len(data['tasks']), 2)
        self.assertTrue(all(task['kind'] == 'convert' for task in data['tasks']))
        self.assertTrue(all(task['status'] == 'completed' for task in data['tasks']))

    async def test_convert_run_rejects_single_file_over_size_limit(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with tempfile.TemporaryDirectory() as tmp, patch('app.MAX_CONVERT_FILE_BYTES', 4, create=True):
                response = await client.post(
                    '/api/convert/run',
                    files={'file': ('large.csv', b'name\nAda\n', 'text/csv')},
                    data={'inputType': 'csv', 'outputType': 'json', 'outputPath': tmp},
                )

        self.assertEqual(response.status_code, 413)
        self.assertIn('超过', response.json()['detail'])

    async def test_convert_batch_run_rejects_total_upload_over_size_limit(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with tempfile.TemporaryDirectory() as tmp, patch('app.MAX_CONVERT_BATCH_TOTAL_BYTES', 8, create=True):
                response = await client.post(
                    '/api/convert/batch-run',
                    files=[
                        ('files', ('a.csv', b'name\nAda\n', 'text/csv')),
                        ('files', ('b.csv', b'name\nBob\n', 'text/csv')),
                    ],
                    data={'inputType': 'csv', 'outputType': 'json', 'outputPath': tmp},
                )

        self.assertEqual(response.status_code, 413)
        self.assertIn('批量', response.json()['detail'])

    async def test_task_api_lists_and_fetches_tasks(self):
        task_store.clear(TaskKind.CONVERT)
        task = task_store.create(TaskKind.CONVERT, '示例转换', {'source': 'csv', 'target': 'json'})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            list_response = await client.get('/api/tasks?kind=convert')
            get_response = await client.get(f'/api/tasks/{task.id}')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(any(item['id'] == task.id for item in list_response.json()['tasks']))
        self.assertEqual(get_response.json()['task']['id'], task.id)


class BatchMediaApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_task_cancel_api_returns_updated_task(self):
        task = task_store.create(TaskKind.MEDIA, '待取消', {'link': 'https://example.com/video'})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.media_queue.cancel', return_value=True):
                response = await client.delete(f'/api/tasks/{task.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    async def test_finished_task_delete_api_removes_single_record(self):
        from tasks.models import TaskStatus

        finished = task_store.create(TaskKind.MEDIA, '已完成记录', {'link': 'https://example.com/done'})
        other = task_store.create(TaskKind.MEDIA, '保留记录', {'link': 'https://example.com/keep'})
        task_store.update(finished.id, status=TaskStatus.COMPLETED, result={'outputPath': '/tmp/done.mp4'})
        task_store.update(other.id, status=TaskStatus.COMPLETED, result={'outputPath': '/tmp/keep.mp4'})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.delete(f'/api/tasks/{finished.id}')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['deleted'])
        self.assertIsNone(task_store.get(finished.id))
        self.assertIsNotNone(task_store.get(other.id))

    async def test_video_record_cannot_be_deleted_while_background_subtitle_is_running(self):
        from tasks.models import TaskStatus

        task = task_store.create(TaskKind.MEDIA, '视频已完成', {'link': 'https://example.com/video'})
        task_store.update(task.id, status=TaskStatus.COMPLETED, result={
            'outputPath': '/tmp/video.mp4',
            'subtitleJob': {'status': 'running'},
        })
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.delete(f'/api/tasks/{task.id}')

        self.assertEqual(response.status_code, 409)
        self.assertIn('字幕仍在后台识别', response.json()['error'])
        self.assertIsNotNone(task_store.get(task.id))

    async def test_fetch_batch_submits_links_to_conservative_queue(self):
        from unittest.mock import patch

        fake_tasks = [
            {'id': 'task-1', 'kind': 'media', 'status': 'pending', 'payload': {'link': 'https://v.douyin.com/a/'}},
            {'id': 'task-2', 'kind': 'media', 'status': 'pending', 'payload': {'link': 'https://www.bilibili.com/video/BV1demo'}},
        ]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.media_queue.submit', return_value=fake_tasks) as mocked_submit:
                response = await client.post(
                    '/api/fetch/batch',
                    json={
                        'links': ['https://v.douyin.com/a/', 'https://www.bilibili.com/video/BV1demo'],
                        'outputPath': '/tmp/out',
                        'outputType': 'mp4',
                    },
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['tasks']), 2)
        submitted = mocked_submit.call_args.args[0]
        self.assertEqual([item['link'] for item in submitted], ['https://v.douyin.com/a/', 'https://www.bilibili.com/video/BV1demo'])
        self.assertTrue(all(item['outputType'] == 'mp4' for item in submitted))


class MediaSelectionTests(unittest.TestCase):
    def test_prefers_video_when_both_audio_and_video_urls_exist(self):
        capture = choose_media_capture(
            candidate_video_url='https://example.com/media-video-avc1/?id=1',
            candidate_audio_url='https://example.com/media-audio-und-mp4a/?id=1',
            dom_video_sources=['blob:https://www.douyin.com/abc'],
            final_url='https://www.douyin.com/video/123',
            title='demo - 抖音',
        )
        self.assertEqual(capture['media_kind'], 'video')
        self.assertEqual(capture['media_url'], 'https://example.com/media-video-avc1/?id=1')
        self.assertEqual(capture['audio_url'], 'https://example.com/media-audio-und-mp4a/?id=1')

    def test_rejects_mp4_output_when_only_audio_stream_exists(self):
        with self.assertRaisesRegex(ValueError, 'Only audio stream found'):
            validate_output_request(media_kind='audio', output_type='mp4')

    def test_merge_streams_to_mp4_produces_audio_and_video_tracks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file = temp_path / 'video.mp4'
            audio_file = temp_path / 'audio.m4a'
            merged_file = temp_path / 'merged.mp4'

            subprocess.run(
                [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'color=c=black:s=320x240:d=1',
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    str(video_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'sine=frequency=1000:duration=1',
                    '-c:a', 'aac',
                    str(audio_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            merge_streams_to_mp4(video_file, audio_file, merged_file)

            probe = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'stream=codec_type',
                    '-of', 'csv=p=0',
                    str(merged_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            codecs = {line.strip() for line in probe.stdout.splitlines() if line.strip()}
            self.assertEqual(codecs, {'video', 'audio'})


class OutputTypeValidationTests(unittest.TestCase):
    def test_fetch_request_accepts_new_formats(self):
        for output_type in ['wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm']:
            payload = FetchRequest(link='https://v.douyin.com/demo/', outputPath='/tmp/demo', outputType=output_type)
            self.assertEqual(payload.outputType, output_type)


class HomePageOptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_lists_new_output_options(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/use')
        text = response.text
        for marker in ['value="wav"', 'value="flac"', 'value="aac"', 'value="ogg"', 'value="opus"', 'value="mkv"', 'value="mov"', 'value="webm"']:
            self.assertIn(marker, text)


class ApiResponseShapeTests(unittest.IsolatedAsyncioTestCase):
    def test_quality_selector_submits_stable_label_not_temporary_url(self):
        script = Path('static/js/use-quality.js').read_text(encoding='utf-8')
        self.assertIn("option.dataset.qualityLabel = stream.qualityLabel || ''", script)
        self.assertIn('selectedQualityLabel', script)
        self.assertNotIn('option.value = stream.url;', script)

    async def test_probe_api_returns_video_quality_options(self):
        from unittest.mock import patch

        from fetchers.models import MediaFetchResult, MediaStream

        fake_result = MediaFetchResult(
            platform='douyin',
            content_type='video',
            title='抖音测试视频',
            source_url='https://v.douyin.com/demo/',
            final_url='https://www.douyin.com/video/1',
            cover_url=None,
            author=None,
            video_streams=[
                MediaStream(
                    url='https://cdn.example.com/dy-540.mp4',
                    stream_type='video',
                    container='mp4',
                    width=576,
                    height=1024,
                    bitrate=927132,
                    filesize=32 * 1024 * 1024,
                    quality_label='normal_540_0',
                ),
                MediaStream(
                    url='https://cdn.example.com/dy-1080.mp4',
                    stream_type='video',
                    container='mp4',
                    width=1080,
                    height=1920,
                    bitrate=1509869,
                    filesize=64 * 1024 * 1024,
                    quality_label='normal_1080_0',
                ),
            ],
            audio_streams=[],
            preferred_video=MediaStream(
                url='https://cdn.example.com/dy-1080.mp4',
                stream_type='video',
                container='mp4',
                width=1080,
                height=1920,
                bitrate=1509869,
                filesize=64 * 1024 * 1024,
                quality_label='normal_1080_0',
            ),
            preferred_audio=None,
            metadata={'capture_strategy': 'no-login'},
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.probe_media', return_value=fake_result):
                response = await client.post('/api/probe', json={'link': 'https://v.douyin.com/demo/'})

        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['platform'], 'douyin')
        self.assertEqual(len(data['videoStreams']), 2)
        self.assertEqual(data['preferredVideoQuality'], 'normal_1080_0')
        self.assertEqual(data['videoStreams'][1]['qualityLabel'], 'normal_1080_0')
        self.assertEqual(data['probeSummary']['qualityCount'], 2)
        self.assertEqual(data['probeSummary']['bestQualityLabel'], 'normal_1080_0')
        self.assertEqual(data['probeSummary']['bestResolution'], '1080×1920')
        self.assertEqual(data['probeSummary']['bestContainer'], 'mp4')
        self.assertEqual(data['probeSummary']['bestBitrateLabel'], '1510 kbps')
        self.assertEqual(data['probeSummary']['bestFilesizeLabel'], '64MB')
        self.assertIn('downloadHint', data['probeSummary'])
        self.assertEqual(data['videoStreams'][1]['host'], 'cdn.example.com')
        self.assertFalse(data['videoStreams'][1]['isHls'])
        self.assertEqual(data['videoStreams'][1]['filesizeLabel'], '64MB')
        self.assertEqual(data['probeSummary']['delivery'], 'direct')
        self.assertIn('未登录', data['probeSummary']['accessHint'])

    async def test_probe_api_includes_login_hint_for_bilibili_when_cookie_missing(self):
        from unittest.mock import patch

        from fetchers.models import MediaFetchResult, MediaStream

        fake_result = MediaFetchResult(
            platform='bilibili',
            content_type='video',
            title='B站测试视频',
            source_url='https://www.bilibili.com/video/BV1demo',
            final_url='https://www.bilibili.com/video/BV1demo',
            cover_url=None,
            author=None,
            video_streams=[
                MediaStream(
                    url='https://cdn.example.com/bili-480.mp4',
                    stream_type='video',
                    container='mp4',
                    width=854,
                    height=480,
                    bitrate=600000,
                    quality_label='480P',
                ),
            ],
            audio_streams=[],
            preferred_video=MediaStream(
                url='https://cdn.example.com/bili-480.mp4',
                stream_type='video',
                container='mp4',
                width=854,
                height=480,
                bitrate=600000,
                quality_label='480P',
            ),
            preferred_audio=None,
            metadata={'capture_strategy': 'web-playurl', 'cookie_source': None},
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.probe_media', return_value=fake_result):
                response = await client.post('/api/probe', json={'link': 'https://www.bilibili.com/video/BV1demo'})

        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['probeSummary']['qualityCount'], 1)
        self.assertEqual(data['probeSummary']['delivery'], 'direct')
        self.assertIn('未检测到登录态', data['probeSummary']['accessHint'])

    async def test_probe_api_reports_hls_hint_for_kuaishou(self):
        from unittest.mock import patch

        from fetchers.models import MediaFetchResult, MediaStream

        fake_result = MediaFetchResult(
            platform='kuaishou',
            content_type='video',
            title='快手测试视频',
            source_url='https://www.kuaishou.com/short-video/demo',
            final_url='https://m.gifshow.com/fw/photo/demo',
            cover_url=None,
            author=None,
            video_streams=[
                MediaStream(
                    url='https://cdn.example.com/demo-master.m3u8',
                    stream_type='video',
                    container='m3u8',
                    width=1280,
                    height=720,
                    bitrate=888000,
                    quality_label='高清',
                ),
            ],
            audio_streams=[],
            preferred_video=MediaStream(
                url='https://cdn.example.com/demo-master.m3u8',
                stream_type='video',
                container='m3u8',
                width=1280,
                height=720,
                bitrate=888000,
                quality_label='高清',
            ),
            preferred_audio=None,
            metadata={'capture_strategy': 'mobile-init-state'},
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.probe_media', return_value=fake_result):
                response = await client.post('/api/probe', json={'link': 'https://www.kuaishou.com/short-video/demo'})

        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['probeSummary']['delivery'], 'hls')
        self.assertIn('HLS', data['probeSummary']['deliveryHint'])

    async def test_probe_api_reports_fallback_hint_for_xiaohongshu(self):
        from unittest.mock import patch

        from fetchers.models import MediaFetchResult, MediaStream

        fake_result = MediaFetchResult(
            platform='xiaohongshu',
            content_type='video',
            title='小红书测试视频',
            source_url='https://www.xiaohongshu.com/explore/demo',
            final_url='https://www.xiaohongshu.com/explore/demo',
            cover_url=None,
            author=None,
            video_streams=[
                MediaStream(
                    url='https://cdn.example.com/xhs-demo.mp4',
                    stream_type='video',
                    container='mp4',
                    width=720,
                    height=1280,
                    bitrate=666000,
                    quality_label='720p',
                ),
            ],
            audio_streams=[],
            preferred_video=MediaStream(
                url='https://cdn.example.com/xhs-demo.mp4',
                stream_type='video',
                container='mp4',
                width=720,
                height=1280,
                bitrate=666000,
                quality_label='720p',
            ),
            preferred_audio=None,
            metadata={'resolve_method': 'playwright-fallback'},
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.probe_media', return_value=fake_result):
                response = await client.post('/api/probe', json={'link': 'https://www.xiaohongshu.com/explore/demo'})

        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('回退', data['probeSummary']['sourceHint'])


class ProbeCookieIsolationTests(unittest.IsolatedAsyncioTestCase):
    def test_bilibili_cookie_env_uses_request_scoped_override_without_mutating_process_env(self):
        from app import bilibili_cookie_env
        from fetchers.adapters.bilibili import load_manual_cookies_for_bilibili
        from unittest.mock import patch

        with patch.dict(os.environ, {'BILIBILI_COOKIE': 'SESSDATA=env-demo; bili_jct=env-csrf'}, clear=False):
            original_cookie = os.environ['BILIBILI_COOKIE']
            with bilibili_cookie_env('SESSDATA=request-demo; bili_jct=request-csrf', None):
                self.assertEqual(os.environ['BILIBILI_COOKIE'], original_cookie)
                cookies = load_manual_cookies_for_bilibili()
                self.assertEqual(cookies['SESSDATA'], 'request-demo')
                self.assertEqual(cookies['bili_jct'], 'request-csrf')
            self.assertEqual(os.environ['BILIBILI_COOKIE'], original_cookie)

    async def test_fetch_api_returns_platform_field_on_success(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run') as mocked_run, patch('app.validate_media_output', return_value={'valid': True}):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = '[douyin-fetch] platform: douyin\n[douyin-fetch] output file: /tmp/demo.mp3\n'
                mocked_run.return_value.stderr = ''
                response = await client.post('/api/fetch', json={
                    'link': 'https://v.douyin.com/demo/',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp3',
                    'videoQuality': 'normal_1080_0',
                })
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['platform'], 'douyin')
        self.assertEqual(data['outputPath'], '/tmp/demo.mp3')
        called_command = mocked_run.call_args.args[0]
        self.assertIn('--videoQuality', called_command)
        self.assertIn('normal_1080_0', called_command)

    async def test_fetch_api_passes_manual_bilibili_cookie_into_subprocess_env(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run') as mocked_run, patch('app.validate_media_output', return_value={'valid': True}):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = '[douyin-fetch] platform: bilibili\n[douyin-fetch] output file: /tmp/demo.mp4\n'
                mocked_run.return_value.stderr = ''
                response = await client.post('/api/fetch', json={
                    'link': 'https://www.bilibili.com/video/demo',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp4',
                    'bilibiliCookie': 'SESSDATA=manual-demo; bili_jct=csrf-demo',
                })
        data = response.json()
        self.assertTrue(data['success'])
        called_env = mocked_run.call_args.kwargs['env']
        self.assertEqual(called_env['BILIBILI_COOKIE'], 'SESSDATA=manual-demo; bili_jct=csrf-demo')
        self.assertIn('/opt/homebrew/bin', called_env['PATH'].split(':'))

    async def test_fetch_api_returns_platform_field_for_expanded_platforms(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        for platform_name in ['xiaohongshu', 'weibo', 'channels', 'youtube', 'tiktok', 'twitter_x']:
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                with patch('app.subprocess.run') as mocked_run, patch('app.validate_media_output', return_value={'valid': True}):
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stdout = (
                        f'[douyin-fetch] platform: {platform_name}\n'
                        '[douyin-fetch] output file: /tmp/demo.mp4\n'
                    )
                    mocked_run.return_value.stderr = ''
                    response = await client.post('/api/fetch', json={
                        'link': 'https://example.com/demo',
                        'outputPath': '/tmp/out',
                        'outputType': 'mp4',
                    })
            data = response.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['platform'], platform_name)
            self.assertEqual(data['outputPath'], '/tmp/demo.mp4')

    async def test_fetch_api_returns_timeout_error_when_cli_hangs(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='demo', timeout=180)):
                response = await client.post('/api/fetch', json={
                    'link': 'https://example.com/demo',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp4',
                })
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('timeout', data['error'].lower())

    def test_queued_media_fetch_defers_generated_subtitles_after_video_is_ready(self):
        from app import run_media_fetch

        class FakeProcess:
            def __init__(self):
                self.stdout = io.StringIO(
                    '[douyin-fetch] platform: douyin\n'
                    '[douyin-fetch] title: demo\n'
                    '[douyin-fetch] subtitle count: 0\n'
                    '[douyin-fetch] subtitle pending: true\n'
                    '[douyin-fetch] output file: /tmp/demo.mp4\n'
                )
                self.stderr = io.StringIO('')
                self.returncode = 0
                self.pid = 12345

            def poll(self):
                return 0

        fake_process = FakeProcess()
        with patch('app.subprocess.Popen', return_value=fake_process) as mocked_popen, \
             patch('app.validate_media_output', return_value={'valid': True}):
            result = run_media_fetch({
                '_taskId': 'queued-task',
                'link': 'https://v.douyin.com/demo/',
                'outputPath': '/tmp',
                'outputType': 'mp4',
                'saveAssets': True,
                'subtitleStrategy': 'native-asr-ocr',
            })

        command = mocked_popen.call_args.args[0]
        self.assertIn('--deferGeneratedSubtitles', command)
        self.assertTrue(result['success'])
        self.assertTrue(result['downloadCompleted'])
        self.assertEqual(result['outputPath'], '/tmp/demo.mp4')
        self.assertEqual(result['subtitleJob']['status'], 'pending')



class MediaTaskAssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_task_asset_serves_recorded_cover_file(self):
        from tasks.models import TaskStatus

        with tempfile.TemporaryDirectory() as tmp:
            cover = Path(tmp) / 'demo_cover.webp'
            cover.write_bytes(b'RIFFdemoWEBP')
            task = task_store.create(TaskKind.MEDIA, 'cover demo', {'link': 'https://example.com/video'})
            task_store.update(task.id, status=TaskStatus.COMPLETED, result={'assets': {'cover': str(cover), 'subtitles': []}})
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.get(f'/api/media/tasks/{task.id}/asset', params={'path': str(cover)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'RIFFdemoWEBP')


class MediaCoverProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cover_proxy_adds_bilibili_referer_and_returns_image(self):
        class FakeResponse:
            headers = {'content-type': 'image/jpeg'}
            content = b'fake-jpeg'

            def raise_for_status(self):
                return None

        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            captured['headers'] = kwargs.get('headers') or {}
            return FakeResponse()

        transport = httpx.ASGITransport(app=app)
        with patch('app.requests.get', side_effect=fake_get):
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.get('/api/media/cover-proxy', params={'url': 'https://i0.hdslb.com/bfs/archive/demo.jpg'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(response.content, b'fake-jpeg')
        self.assertEqual(captured['headers']['Referer'], 'https://www.bilibili.com/')


    async def test_cover_proxy_adds_douyin_referer_and_sniffs_webp_octet_stream(self):
        class FakeResponse:
            headers = {'content-type': 'application/octet-stream'}
            content = b'RIFFxxxxWEBPpayload'

            def raise_for_status(self):
                return None

        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            captured['headers'] = kwargs.get('headers') or {}
            return FakeResponse()

        transport = httpx.ASGITransport(app=app)
        with patch('app.requests.get', side_effect=fake_get):
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.get(
                    '/api/media/cover-proxy',
                    params={'url': 'https://p3-sign.douyinpic.com/tos-cn-i-demo/cover.webp?x-signature=demo%3D'},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/webp')
        self.assertIn('x-signature=demo%3D', captured['url'])
        self.assertNotIn('x-signature=demo=', captured['url'])
        self.assertEqual(captured['headers']['Referer'], 'https://www.douyin.com/')

    def test_cover_proxy_headers_support_xiaohongshu_and_x_cdn_hosts(self):
        from app import media_cover_headers

        self.assertEqual(
            media_cover_headers('https://sns-webpic-qc.xhscdn.com/demo/cover.jpg')['Referer'],
            'https://www.xiaohongshu.com/',
        )
        self.assertEqual(
            media_cover_headers('https://pbs.twimg.com/media/demo.jpg')['Referer'],
            'https://x.com/',
        )


class OutputFileActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_output_file_rejects_missing_file(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/open-output-file', data={'path': '/tmp/streamdock-missing-output.mp4'})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()['success'])

    async def test_open_output_file_uses_system_opener_for_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.txt'
            output.write_text('done', encoding='utf-8')
            transport = httpx.ASGITransport(app=app)
            with patch('app.subprocess.Popen') as mocked_popen:
                async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                    response = await client.post('/api/open-output-file', data={'path': str(output)})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        mocked_popen.assert_called_once()


class PlatformReliabilityApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_api_reports_required_local_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.get('/api/health', params={'outputPath': tmp})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        keys = {item['key'] for item in data['checks']}
        self.assertTrue({'ffmpeg', 'ffprobe', 'output'}.issubset(keys))

    async def test_failed_media_task_can_be_resubmitted_for_fresh_probe(self):
        from tasks.models import TaskStatus

        task = task_store.create(TaskKind.MEDIA, 'retry demo', {
            'link': 'https://v.douyin.com/demo/', 'outputPath': '/tmp/out', 'outputType': 'mp4',
        })
        task_store.update(task.id, status=TaskStatus.FAILED, error='temporary')
        submitted = {'id': 'replacement', 'kind': 'media', 'status': 'pending'}
        transport = httpx.ASGITransport(app=app)
        with patch('app.media_queue.submit', return_value=[submitted]) as mocked_submit:
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.post(f'/api/tasks/{task.id}/retry')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'reprobe')
        payload = mocked_submit.call_args.args[0][0]
        self.assertEqual(payload['retryOf'], task.id)

    async def test_clear_finished_tasks_keeps_pending_tasks(self):
        from tasks.models import TaskStatus

        pending = task_store.create(TaskKind.CONVERT, 'pending', {})
        completed = task_store.create(TaskKind.CONVERT, 'completed', {})
        task_store.update(completed.id, status=TaskStatus.COMPLETED)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.delete('/api/task-actions/clear-finished', params={'kind': 'convert'})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(task_store.get(pending.id))
        self.assertIsNone(task_store.get(completed.id))


if __name__ == '__main__':
    unittest.main()
