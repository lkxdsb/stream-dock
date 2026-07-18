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

  function readJson(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_error) { return fallback; }
  }

  function writeJson(key, value) {
    window.localStorage.setItem(key, JSON.stringify(value));
  }

  function setActiveTab(name) {
    tabButtons.forEach((button) => button.classList.toggle('active', button.dataset.useTab === name));
    panels.forEach((panel) => {
      const isActive = panel.dataset.usePanel === name;
      panel.classList.toggle('active', isActive);
      panel.hidden = !isActive;
    });
    window.localStorage.setItem('streamdock.activeTab.v1', name);
  }

  function applySettings(settings) {
    if (outputPath && settings.outputPath) outputPath.value = settings.outputPath;
    if (outputType && settings.outputType) {
      outputType.value = settings.outputType;
      outputType.dispatchEvent(new Event('change'));
    }
    if (bilibiliCookie && settings.bilibiliCookie) bilibiliCookie.value = settings.bilibiliCookie;
    if (settingsOutputPath) settingsOutputPath.value = settings.outputPath || outputPath?.value || '~/Downloads/StreamDock';
    if (settingsOutputType) settingsOutputType.value = settings.outputType || outputType?.value || 'mp4';
    if (settingsQualityMode) settingsQualityMode.value = settings.qualityMode === 'best' ? 'best_quality' : (settings.qualityMode || 'best_quality');
    if (settingsBilibiliCookie) settingsBilibiliCookie.value = settings.bilibiliCookie || '';
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
      bilibiliCookie: settingsBilibiliCookie?.value || '',
    };
    writeJson(settingsKey, settings);
    writeJson(platformSettingsKey, { ...readJson(platformSettingsKey, {}), outputPath: settings.outputPath });
    applySettings(settings);
    ui?.showToast('设置已保存');
  });

  settingsSelectOutputDirButton?.addEventListener('click', async () => {
    settingsSelectOutputDirButton.disabled = true;
    try { await selectDirectoryInto(settingsOutputPath); }
    finally { settingsSelectOutputDirButton.disabled = false; }
  });

  const platformSettings = readJson(platformSettingsKey, {});
  applySettings({ ...readJson(settingsKey, {}), ...(platformSettings.outputPath ? { outputPath: platformSettings.outputPath } : {}) });
  const initialHash = window.location.hash.replace('#', '');
  setActiveTab(['parse', 'downloading', 'completed', 'settings'].includes(initialHash) ? initialHash : (window.localStorage.getItem('streamdock.activeTab.v1') || 'parse'));

  window.StreamDockTasks = { setActiveTab };
  window.StreamDockUseTabs = { setActiveTab };
})();
