(function () {
  const tabButtons = Array.from(document.querySelectorAll('[data-use-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-use-panel]'));
  const outputPath = document.getElementById('outputPath');
  const outputType = document.getElementById('outputType');
  const bilibiliCookie = document.getElementById('bilibiliCookie');
  const settingsForm = document.getElementById('settingsForm');
  const settingsOutputPath = document.getElementById('settingsOutputPath');
  const settingsOutputType = document.getElementById('settingsOutputType');
  const settingsQualityMode = document.getElementById('settingsQualityMode');
  const settingsBilibiliCookie = document.getElementById('settingsBilibiliCookie');
  const settingsSelectOutputDirButton = document.getElementById('settingsSelectOutputDirButton');
  const ui = window.StreamDockUI;
  const settingsKey = 'streamdock.settings.v1';
  const platformSettingsKey = 'streamdock.platform.settings.v1';
  const mediaAuthPlatform = document.getElementById('mediaAuthPlatform');
  const mediaAuthCookie = document.getElementById('mediaAuthCookie');
  const mediaAuthFile = document.getElementById('mediaAuthFile');
  const mediaAuthStatus = document.getElementById('mediaAuthStatus');

  function clearLegacyCookieCache(key) {
    const settings = readJson(key, {});
    if (!settings || typeof settings !== 'object' || !Object.hasOwn(settings, 'bilibiliCookie')) return;
    delete settings.bilibiliCookie;
    writeJson(key, settings);
    ui?.showToast?.('已清除浏览器中旧版 B站 Cookie 缓存；请在平台授权配置中重新导入');
  }

  function readJson(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_error) { return fallback; }
  }

  function writeJson(key, value) {
    window.localStorage.setItem(key, JSON.stringify(value));
  }

  function setActiveTab(name, updateHistory = true) {
    tabButtons.forEach((button) => button.classList.toggle('active', button.dataset.useTab === name));
    panels.forEach((panel) => {
      const isActive = panel.dataset.usePanel === name;
      panel.classList.toggle('active', isActive);
      panel.hidden = !isActive;
    });
    window.localStorage.setItem('streamdock.activeTab.v1', name);
    if (updateHistory && window.location.hash !== `#${name}`) window.history.pushState({ panel: name }, '', `#${name}`);
  }

  function applySettings(settings) {
    if (outputPath && settings.outputPath) outputPath.value = settings.outputPath;
    if (outputType && settings.outputType) {
      outputType.value = settings.outputType;
      outputType.dispatchEvent(new Event('change'));
    }
    if (settingsOutputPath) settingsOutputPath.value = settings.outputPath || outputPath?.value || '~/Downloads/StreamDock';
    if (settingsOutputType) settingsOutputType.value = settings.outputType || outputType?.value || 'mp4';
    if (settingsQualityMode) settingsQualityMode.value = settings.qualityMode === 'best' ? 'best_quality' : (settings.qualityMode || 'best_quality');
  }

  async function selectDirectoryInto(inputEl) {
    const response = await fetch('/api/select-output-dir', { method: 'POST' });
    const data = await response.json();
    if (!response.ok || !data.success || !data.path) {
      ui?.showToast(data.error || '未选择保存目录');
      return;
    }
    inputEl.value = data.path;
    ui?.showToast('目录已选择');
  }

  tabButtons.forEach((button) => button.addEventListener('click', () => setActiveTab(button.dataset.useTab || 'parse')));

  settingsForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    const settings = {
      outputPath: settingsOutputPath?.value || outputPath?.value || '~/Downloads/StreamDock',
      outputType: settingsOutputType?.value || outputType?.value || 'mp4',
      qualityMode: settingsQualityMode?.value || 'best_quality',
    };
    writeJson(settingsKey, settings);
    writeJson(platformSettingsKey, { ...readJson(platformSettingsKey, {}), outputPath: settings.outputPath });
    applySettings(settings);
    if (bilibiliCookie && settingsBilibiliCookie?.value) bilibiliCookie.value = settingsBilibiliCookie.value;
    if (settingsBilibiliCookie) settingsBilibiliCookie.value = '';
    ui?.showToast('设置已保存');
  });

  settingsSelectOutputDirButton?.addEventListener('click', async () => {
    settingsSelectOutputDirButton.disabled = true;
    try { await selectDirectoryInto(settingsOutputPath); }
    finally { settingsSelectOutputDirButton.disabled = false; }
  });

  clearLegacyCookieCache(settingsKey);
  clearLegacyCookieCache(platformSettingsKey);
  const platformSettings = readJson(platformSettingsKey, {});
  applySettings({ ...readJson(settingsKey, {}), ...(platformSettings.outputPath ? { outputPath: platformSettings.outputPath } : {}) });
  const initialHash = window.location.hash.replace('#', '');
  setActiveTab(['parse', 'downloading', 'completed', 'settings'].includes(initialHash) ? initialHash : (window.localStorage.getItem('streamdock.activeTab.v1') || 'parse'), false);
  window.addEventListener('popstate', () => {
    const target = window.location.hash.replace('#', '');
    setActiveTab(['parse', 'downloading', 'completed', 'settings'].includes(target) ? target : 'parse', false);
  });

  window.StreamDockTasks = { setActiveTab };
  window.StreamDockUseTabs = { setActiveTab };

  async function refreshMediaAuth() {
    if (!mediaAuthPlatform || !mediaAuthStatus) return;
    const response = await fetch('/api/media/auth');
    const data = await response.json();
    const selected = (data.profiles || []).find((item) => item.platform === mediaAuthPlatform.value);
    const verification = ({ valid: '最近确认有效', unknown: '有效性未确认', unchecked: '尚未验证' })[selected?.verificationStatus] || selected?.verificationStatus || '尚未验证';
    mediaAuthStatus.textContent = selected?.configured
      ? `已配置 · 版本 ${selected.version} · ${selected.persisted ? '服务器加密保存' : '仅当前进程内存'} · ${verification}`
      : '未配置授权';
  }
  mediaAuthPlatform?.addEventListener('change', () => { refreshMediaAuth().catch(() => { mediaAuthStatus.textContent = '状态查询失败'; }); });
  document.getElementById('mediaAuthImport')?.addEventListener('click', async () => {
    const cookie = mediaAuthCookie?.value || '';
    const file = mediaAuthFile?.files?.[0];
    if (!cookie && !file) return;
    try {
      let response;
      if (file) {
        const form = new FormData();
        form.append('file', file);
        form.append('save', String(Boolean(document.getElementById('mediaAuthSave')?.checked)));
        response = await fetch(`/api/media/auth/${encodeURIComponent(mediaAuthPlatform.value)}/import`, { method: 'POST', body: form });
      } else {
        response = await fetch(`/api/media/auth/${encodeURIComponent(mediaAuthPlatform.value)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cookie, save: Boolean(document.getElementById('mediaAuthSave')?.checked) }),
        });
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '导入失败');
      mediaAuthCookie.value = '';
      if (mediaAuthFile) mediaAuthFile.value = '';
      await refreshMediaAuth();
    } catch (error) { mediaAuthStatus.textContent = error.message || '导入失败'; }
  });
  document.getElementById('mediaAuthVerify')?.addEventListener('click', async () => {
    const response = await fetch(`/api/media/auth/${encodeURIComponent(mediaAuthPlatform.value)}/verify`, { method: 'POST' });
    const data = await response.json();
    mediaAuthStatus.textContent = data.message || `验证结果：${data.status || data.error || 'unknown'}`;
  });
  document.getElementById('mediaAuthDelete')?.addEventListener('click', async () => {
    const response = await fetch(`/api/media/auth/${encodeURIComponent(mediaAuthPlatform.value)}`, { method: 'DELETE' });
    if (response.ok) await refreshMediaAuth();
  });
  refreshMediaAuth().catch(() => {});

  let activeDiagnosticId = null;
  const diagnosticCancel = document.getElementById('mediaDiagnosticCancel');
  const diagnosticRun = document.getElementById('mediaDiagnosticRun');
  diagnosticCancel?.addEventListener('click', async () => {
    if (!activeDiagnosticId) return;
    const response = await fetch(`/api/tasks/${encodeURIComponent(activeDiagnosticId)}`, { method: 'DELETE' });
    if (!response.ok) { document.getElementById('mediaDiagnosticStatus').textContent = '诊断取消失败'; return; }
    diagnosticCancel.disabled = true;
  });
  diagnosticRun?.addEventListener('click', async () => {
    const output = document.getElementById('mediaDiagnosticStatus');
    const links = (document.getElementById('mediaDiagnosticLinks')?.value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    const fullDownload = Boolean(document.getElementById('mediaDiagnosticFull')?.checked);
    if (!links.length || links.length > (fullDownload ? 2 : 10)) { output.textContent = `请输入 1–${fullDownload ? 2 : 10} 条链接`; return; }
    diagnosticRun.disabled = true;
    try {
      const response = await fetch('/api/media/diagnostics', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ links, fullDownload }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '诊断未启动');
      const id = data.diagnostic.id;
      activeDiagnosticId = id;
      if (diagnosticCancel) diagnosticCancel.disabled = false;
      output.textContent = `诊断任务 ${id} 已排队`;
      for (let index = 0; index < (fullDownload ? 360 : 180); index += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const check = await fetch(`/api/media/diagnostics/${encodeURIComponent(id)}`);
        const state = (await check.json()).diagnostic;
        if (!state) throw new Error('诊断状态丢失');
        output.textContent = JSON.stringify({ status: state.status, results: state.results }, null, 2);
        if (['completed', 'cancelled', 'failed'].includes(state.status)) break;
      }
    } catch (error) { output.textContent = error.message || '诊断失败'; }
    finally { activeDiagnosticId = null; diagnosticRun.disabled = false; if (diagnosticCancel) diagnosticCancel.disabled = true; }
  });
})();
