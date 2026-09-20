(function () {
  const STORAGE_KEY = 'streamdock.convert.settings.v1';
  const PLATFORM_STORAGE_KEY = 'streamdock.platform.settings.v1';
  const defaults = {
    outputPath: '~/Downloads/StreamDock',
    namingStrategy: 'append',
    afterDoneAction: 'none',
    defaultLevel: 'all',
    imageQuality: 90,
    audioBitrateKbps: 192, audioSampleRate: 0, videoMaxWidth: 0, videoFrameRate: 0,
    videoBitrateKbps: 0, videoCrf: 22, hardwareAcceleration: 'software'
  };

  const defaultOutputPath = document.getElementById('convertDefaultOutputPath');
  const selectDefaultDirButton = document.getElementById('convertSelectDefaultDirButton');
  const namingStrategy = document.getElementById('convertNamingStrategy');
  const afterDoneAction = document.getElementById('convertAfterDoneAction');
  const defaultLevel = document.getElementById('convertDefaultLevel');
  const imageQuality = document.getElementById('convertImageQuality');
  const audioBitrate = document.getElementById('convertAudioBitrate');
  const audioSampleRate = document.getElementById('convertAudioSampleRate');
  const videoMaxWidth = document.getElementById('convertVideoMaxWidth');
  const videoFrameRate = document.getElementById('convertVideoFrameRate');
  const videoBitrate = document.getElementById('convertVideoBitrate');
  const videoCrf = document.getElementById('convertVideoCrf');
  const hardwareAcceleration = document.getElementById('convertHardwareAcceleration');
  const saveButton = document.getElementById('convertSaveSettingsButton');
  const resetButton = document.getElementById('convertResetSettingsButton');
  const status = document.getElementById('convertSettingsStatus');
  const workbenchOutputPath = document.getElementById('convertOutputPath');

  function readStored() {
    try {
      const raw = window.localStorage?.getItem(STORAGE_KEY);
      const platformRaw = window.localStorage?.getItem(PLATFORM_STORAGE_KEY);
      const platform = platformRaw ? JSON.parse(platformRaw) : {};
      if (!raw) return { ...defaults, ...(platform.outputPath ? { outputPath: platform.outputPath } : {}) };
      return { ...defaults, ...JSON.parse(raw), ...(platform.outputPath ? { outputPath: platform.outputPath } : {}) };
    } catch (_) {
      return { ...defaults };
    }
  }

  function currentFromControls() {
    return {
      outputPath: defaultOutputPath?.value || defaults.outputPath,
      namingStrategy: namingStrategy?.value || defaults.namingStrategy,
      afterDoneAction: afterDoneAction?.value || defaults.afterDoneAction,
      defaultLevel: defaultLevel?.value || defaults.defaultLevel,
      imageQuality: Number(imageQuality?.value || defaults.imageQuality),
      audioBitrateKbps: Number(audioBitrate?.value || defaults.audioBitrateKbps), audioSampleRate: Number(audioSampleRate?.value || 0),
      videoMaxWidth: Number(videoMaxWidth?.value || 0), videoFrameRate: Number(videoFrameRate?.value || 0),
      videoBitrateKbps: Number(videoBitrate?.value || 0), videoCrf: Number(videoCrf?.value || defaults.videoCrf),
      hardwareAcceleration: hardwareAcceleration?.value || defaults.hardwareAcceleration
    };
  }

  function writeControls(settings, syncWorkbench = false) {
    if (defaultOutputPath) defaultOutputPath.value = settings.outputPath || defaults.outputPath;
    if (namingStrategy) namingStrategy.value = settings.namingStrategy || defaults.namingStrategy;
    if (afterDoneAction) afterDoneAction.value = settings.afterDoneAction || defaults.afterDoneAction;
    if (defaultLevel) defaultLevel.value = settings.defaultLevel || defaults.defaultLevel;
    if (imageQuality) imageQuality.value = settings.imageQuality || defaults.imageQuality;
    if (audioBitrate) audioBitrate.value = settings.audioBitrateKbps || defaults.audioBitrateKbps;
    if (audioSampleRate) audioSampleRate.value = settings.audioSampleRate || 0;
    if (videoMaxWidth) videoMaxWidth.value = settings.videoMaxWidth || 0;
    if (videoFrameRate) videoFrameRate.value = settings.videoFrameRate || 0;
    if (videoBitrate) videoBitrate.value = settings.videoBitrateKbps || 0;
    if (videoCrf) videoCrf.value = settings.videoCrf ?? defaults.videoCrf;
    if (hardwareAcceleration) hardwareAcceleration.value = settings.hardwareAcceleration || defaults.hardwareAcceleration;
    if (syncWorkbench && workbenchOutputPath) workbenchOutputPath.value = settings.outputPath || defaults.outputPath;
  }

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function save(settings) {
    const next = { ...defaults, ...settings };
    window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(next));
    window.localStorage?.setItem(PLATFORM_STORAGE_KEY, JSON.stringify({ outputPath: next.outputPath }));
    writeControls(next);
    window.dispatchEvent(new CustomEvent('streamdock:convert-settings-change', { detail: next }));
    return next;
  }

  function get() {
    return readStored();
  }

  function reset() {
    window.localStorage?.removeItem(STORAGE_KEY);
    window.localStorage?.removeItem(PLATFORM_STORAGE_KEY);
    writeControls(defaults);
    window.dispatchEvent(new CustomEvent('streamdock:convert-settings-change', { detail: { ...defaults } }));
    setStatus('已恢复默认设置。');
  }

  writeControls(readStored(), true);

  selectDefaultDirButton?.addEventListener('click', async () => {
    setStatus('正在打开系统目录选择窗口...');
    const response = await fetch('/api/convert/select-output-dir', { method: 'POST' });
    const data = await response.json();
    if (data.success && data.path) {
      const next = save({ ...currentFromControls(), outputPath: data.path });
      setStatus(`已选择默认保存目录：${next.outputPath}`);
    } else {
      setStatus(data.error || '目录选择已取消。');
    }
  });

  saveButton?.addEventListener('click', () => {
    save(currentFromControls());
    setStatus('常用设置已保存，下次转换会自动带入。');
  });

  resetButton?.addEventListener('click', reset);

  [namingStrategy, afterDoneAction, defaultLevel, imageQuality, audioBitrate, audioSampleRate, videoMaxWidth, videoFrameRate, videoBitrate, videoCrf, hardwareAcceleration].forEach((control) => {
    control?.addEventListener('change', () => {
      setStatus('设置已修改，点击“保存设置”后生效。');
    });
  });

  window.StreamDockConvertSettings = { get, save, reset, defaults: { ...defaults } };
})();
