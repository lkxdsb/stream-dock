(function () {
  const linkInput = document.getElementById('link');
  const outputType = document.getElementById('outputType');
  const qualityPreset = document.getElementById('qualityPreset');
  const qualityHint = document.getElementById('qualityHint');
  const bilibiliCookie = document.getElementById('bilibiliCookie');
  const logs = window.StreamDockLogs;
  const audioOutputTypes = new Set(['m4a', 'mp3', 'wav', 'flac', 'aac', 'ogg', 'opus']);

  let lastProbeLink = '';
  let lastProbePlatform = '';
  let lastProbeResult = null;
  let lastProbeCookieKey = '';

  function isVideoOutputType(value) {
    return !audioOutputTypes.has(String(value || '').trim().toLowerCase());
  }

  function setQualityHint(message) {
    if (!qualityHint) {
      return;
    }
    qualityHint.textContent = message || '自动选择当前可达最高画质。';
  }

  function resetQualityOptions(message = '最佳画质（自动）') {
    if (!qualityPreset) {
      return;
    }
    qualityPreset.innerHTML = '';
    const option = document.createElement('option');
    option.value = '';
    option.textContent = message;
    qualityPreset.appendChild(option);
    qualityPreset.disabled = true;
  }

  function formatQualityOption(stream) {
    const quality = stream.qualityLabel || '未命名清晰度';
    const size = stream.height ? `${stream.height}P` : '';
    const bitrate = stream.bitrate ? `${Math.round(stream.bitrate / 1000)} kbps` : '';
    return [quality, size, bitrate].filter(Boolean).join(' · ');
  }

  function renderQualityOptions(streams, preferredQuality) {
    if (!qualityPreset) {
      return;
    }
    qualityPreset.innerHTML = '';
    (streams || []).forEach((stream) => {
      const option = document.createElement('option');
      // 提交稳定的画质标识，不提交探测时带签名的临时 CDN URL。
      // 后端会在真正下载前重新解析，URL 可能已经变化，而 qualityLabel 保持稳定。
      option.value = stream.qualityLabel || '';
      option.dataset.qualityLabel = stream.qualityLabel || '';
      option.dataset.streamUrl = stream.url || '';
      option.textContent = formatQualityOption(stream);
      if (stream.qualityLabel === preferredQuality) {
        option.selected = true;
      }
      qualityPreset.appendChild(option);
    });
    qualityPreset.disabled = !(streams || []).length;
  }

  function formatProbeHint(summary) {
    if (!summary) {
      return '自动选择当前可达最高画质。';
    }
    return [summary.sourceHint, summary.accessHint, summary.deliveryHint].filter(Boolean).join(' · ');
  }

  async function probeQualityOptions(link, { silent = false } = {}) {
    if (!qualityPreset || !outputType) {
      return null;
    }
    const normalizedLink = String(link || '').trim();
    const currentCookieKey = String(bilibiliCookie?.value || '').trim();
    if (!normalizedLink || !isVideoOutputType(outputType.value)) {
      lastProbeLink = '';
      lastProbePlatform = '';
      lastProbeResult = null;
      lastProbeCookieKey = '';
      resetQualityOptions(isVideoOutputType(outputType.value) ? '最佳画质（自动）' : '音频输出无需选择');
      setQualityHint(isVideoOutputType(outputType.value) ? '自动选择当前可达最高画质。' : '当前为音频导出，无需选择清晰度。');
      return null;
    }

    if (
      lastProbeLink === normalizedLink
      && lastProbeCookieKey === currentCookieKey
      && qualityPreset.options.length > 0
      && !qualityPreset.disabled
    ) {
      return lastProbeResult || { platform: lastProbePlatform, preferredVideoQuality: qualityPreset.value };
    }

    if (!silent) {
      logs?.renderLogs(['正在识别可用清晰度...']);
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 120000);
    let response;
    try {
      response = await fetch('/api/media/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          link: normalizedLink,
          bilibiliCookie: currentCookieKey || null,
        }),
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error('清晰度识别超时，请稍后重试');
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
    const data = await response.json();

    if (!response.ok || !data.success) {
      resetQualityOptions('清晰度识别失败');
      setQualityHint('当前未识别到可用清晰度信息。');
      if (!silent) {
        logs?.renderLogs([(data.error || data.detail) ? `probe error:\n${data.error || data.detail}` : 'probe error:\nUnknown error']);
      }
      throw new Error(data.error || data.detail || '清晰度识别失败');
    }

    let preferredQuality = data.preferredVideoQuality || '';
    try {
      const settings = JSON.parse(window.localStorage.getItem('streamdock.settings.v1') || '{}');
      const strategy = settings.qualityMode === 'best' ? 'best_quality' : (settings.qualityMode || 'best_quality');
      if (strategy !== 'manual') preferredQuality = data.recommendations?.[strategy]?.stream?.qualityLabel || preferredQuality;
    } catch (_error) {}
    renderQualityOptions(data.videoStreams || [], preferredQuality);
    setQualityHint(formatProbeHint(data.probeSummary));
    lastProbeLink = normalizedLink;
    lastProbePlatform = data.platform || '';
    lastProbeResult = data;
    lastProbeCookieKey = currentCookieKey;
    if (!silent) {
      logs?.renderLogs([
        `已识别 ${data.platform || 'unknown'} 可选清晰度：${(data.videoStreams || []).length} 档`,
        formatProbeHint(data.probeSummary),
      ]);
    }
    return data;
  }

  function invalidateProbeCache() {
    lastProbeLink = '';
    lastProbePlatform = '';
    lastProbeResult = null;
    lastProbeCookieKey = '';
  }

  outputType?.addEventListener('change', async () => {
    if (!isVideoOutputType(outputType.value)) {
      resetQualityOptions('音频输出无需选择');
      setQualityHint('当前为音频导出，无需选择清晰度。');
      return;
    }
    resetQualityOptions('最佳画质（自动）');
    setQualityHint('自动选择当前可达最高画质。');
    if (linkInput?.value.trim()) {
      try {
        await probeQualityOptions(linkInput.value, { silent: true });
      } catch (_error) {
      }
    }
  });

  linkInput?.addEventListener('change', async () => {
    invalidateProbeCache();
    if (!isVideoOutputType(outputType?.value)) {
      resetQualityOptions('音频输出无需选择');
      setQualityHint('当前为音频导出，无需选择清晰度。');
      return;
    }
    try {
      await probeQualityOptions(linkInput.value, { silent: true });
    } catch (_error) {
    }
  });

  bilibiliCookie?.addEventListener('change', async () => {
    invalidateProbeCache();
    if (!isVideoOutputType(outputType?.value) || !linkInput?.value.trim()) {
      return;
    }
    try {
      await probeQualityOptions(linkInput.value, { silent: true });
    } catch (_error) {
    }
  });

  if (qualityPreset) {
    if (isVideoOutputType(outputType?.value)) {
      resetQualityOptions('最佳画质（自动）');
      setQualityHint('自动选择当前可达最高画质。');
    } else {
      resetQualityOptions('音频输出无需选择');
      setQualityHint('当前为音频导出，无需选择清晰度。');
    }
  }

  window.StreamDockQuality = {
    isVideoOutputType,
    probeQualityOptions,
    resetQualityOptions,
    setQualityHint,
    invalidateProbeCache,
    qualityPreset,
  };
})();
