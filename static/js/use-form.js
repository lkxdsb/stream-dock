(function () {
  const form = document.getElementById('fetchForm');
  const linkInput = document.getElementById('link');
  const outputType = document.getElementById('outputType');
  const outputPath = document.getElementById('outputPath');
  const bilibiliCookie = document.getElementById('bilibiliCookie');
  const submitButton = document.getElementById('submitButton');
  const selectOutputDirButton = document.getElementById('selectOutputDirButton');
  const clearLogButton = document.getElementById('clearLogButton');
  const quality = window.StreamDockQuality;
  const logs = window.StreamDockLogs;
  const result = window.StreamDockResult;
  const ui = window.StreamDockUI;
  const tabs = window.StreamDockTasks;
  const probePreview = document.getElementById('mediaProbePreview');
  const probePlatform = document.getElementById('mediaProbePlatform');
  const probeTitle = document.getElementById('mediaProbeTitle');
  const probeFacts = document.getElementById('mediaProbeFacts');
  const streamTable = document.getElementById('mediaStreamTable');
  let confirmedProbeKey = '';
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function renderProbePreview(data) {
    if (!probePreview || !data) return;
    probePlatform.textContent = data.platform || '未知平台';
    probeTitle.textContent = data.title || '未命名视频';
    const recommendation = data.recommendations?.best_quality?.stream;
    probeFacts.innerHTML = [
      `${(data.videoStreams || []).length} 档画质`,
      recommendation?.qualityLabel || data.preferredVideoQuality || '自动优选',
      data.probeSummary?.delivery === 'hls' ? 'HLS 合流' : '直链资源',
    ].map((item) => `<em>${item}</em>`).join('');
    const recommended = new Map();
    Object.entries(data.recommendations || {}).forEach(([strategy, item]) => { if (item?.stream?.qualityLabel) recommended.set(item.stream.qualityLabel, strategy); });
    streamTable.innerHTML = (data.videoStreams || []).map((stream) => {
      const strategy = recommended.get(stream.qualityLabel); const reason = strategy === 'best_quality' ? '最佳画质' : strategy === 'best_compatibility' ? '最佳兼容' : strategy === 'smallest_size' ? '最小体积' : '';
      return `<div class="media-stream-row${quality?.qualityPreset?.value === stream.qualityLabel ? ' is-selected' : ''}"><strong>${escapeHtml(stream.qualityLabel || '未命名')}</strong><span>${escapeHtml(stream.width && stream.height ? `${stream.width}×${stream.height}` : '分辨率未知')}</span><span>${escapeHtml(stream.codec || '编码未知')}</span><span>${escapeHtml(stream.bitrate ? `${Math.round(stream.bitrate / 1000)} kbps` : '码率未知')}</span><button type="button" data-select-stream="${escapeHtml(stream.qualityLabel || '')}">${escapeHtml(reason || '选择')}</button></div>`;
    }).join('');
    streamTable.querySelectorAll('[data-select-stream]').forEach((button) => button.addEventListener('click', () => { quality.qualityPreset.value = button.dataset.selectStream; streamTable.querySelectorAll('.media-stream-row').forEach((row) => row.classList.remove('is-selected')); button.closest('.media-stream-row').classList.add('is-selected'); submitButton.textContent = '确认并开始下载'; }));
    probePreview.hidden = false;
  }

  function extractLinks(raw) {
    const text = String(raw || '').trim();
    if (!text) return [];
    const urls = text.match(/https?:\/\/[^\s，。]+/g) || [];
    const unique = [];
    urls.forEach((url) => {
      const cleaned = url.replace(/[）)\].,，。!！?？]+$/g, '');
      if (cleaned && !unique.includes(cleaned)) unique.push(cleaned);
    });
    return unique.length ? unique : [text];
  }

  function friendlyRequestError(error) {
    const message = error instanceof Error ? error.message : String(error || '');
    if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
      return '无法连接本地服务，请确认 StreamDock 服务正在运行。';
    }
    return message || '请求失败，请稍后重试。';
  }

  async function readJson(response) {
    const text = await response.text();
    try { return text ? JSON.parse(text) : {}; }
    catch (_error) { return { success: false, error: text || `HTTP ${response.status}` }; }
  }

  async function submitQueue(payload, links) {
    const response = await fetch('/api/fetch/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        links,
        outputPath: payload.outputPath,
        outputType: payload.outputType,
        videoQuality: payload.videoQuality || null,
        bilibiliCookie: payload.bilibiliCookie || null,
      }),
    });
    const data = await readJson(response);
    if (!response.ok || !data.success) throw new Error(data.error || data.detail || '任务提交失败');
    return data;
  }

  selectOutputDirButton?.addEventListener('click', async () => {
    selectOutputDirButton.disabled = true;
    const originalText = selectOutputDirButton.textContent;
    selectOutputDirButton.textContent = '选择中...';
    try {
      const response = await fetch('/api/select-output-dir', { method: 'POST' });
      const data = await readJson(response);
      if (!response.ok || !data.success || !data.path) {
        ui?.showToast(data.error || '未选择保存目录');
        return;
      }
      if (outputPath) outputPath.value = data.path;
      ui?.showToast('保存目录已更新');
    } catch (error) {
      ui?.showToast(friendlyRequestError(error));
    } finally {
      selectOutputDirButton.disabled = false;
      selectOutputDirButton.textContent = originalText || '选择目录';
    }
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const links = extractLinks(linkInput?.value || '');
    const payload = {
      outputPath: String(outputPath?.value || '').trim(),
      outputType: String(outputType?.value || '').trim(),
      videoQuality: '',
      bilibiliCookie: String(bilibiliCookie?.value || '').trim(),
    };

    if (!links.length || !payload.outputPath || !payload.outputType) {
      result?.setStatus('error', '请先完整填写链接、输出目录和输出类型。');
      logs?.renderLogs(['表单校验未通过。']);
      result?.showResult();
      ui?.showToast('请先粘贴视频链接并确认导出设置');
      linkInput?.focus();
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = links.length > 1 ? '批量提交中...' : '识别中...';
    submitButton.classList.add('loading');
    result?.setStatus('running', links.length > 1 ? `${links.length} 条链接正在加入队列` : '正在识别链接与可用画质');
    logs?.renderLogs([
      '阶段 1/3：校验链接',
      `链接数量：${links.length}`,
      links.length > 1 ? '批量任务将顺序执行，以降低平台限流风险。' : '正在识别可用清晰度...',
    ]);
    result?.showResult();

    try {
      if (links.length === 1 && quality?.isVideoOutputType(payload.outputType)) {
        const probeKey = `${links[0]}|${payload.outputType}|${payload.bilibiliCookie}`;
        const probeData = await quality.probeQualityOptions(links[0], { silent: true });
        payload.videoQuality = String(quality?.qualityPreset?.value || '').trim();
        renderProbePreview(probeData);
        if (confirmedProbeKey !== probeKey) {
          confirmedProbeKey = probeKey;
          result?.setStatus('running', '已识别视频资源，请确认画质后开始下载');
          logs?.renderLogs(['视频资源识别完成', `平台：${probeData?.platform || 'unknown'}`, `可用画质：${(probeData?.videoStreams || []).length} 档`, '请确认选项后再次点击。']);
          submitButton.disabled = false; submitButton.textContent = '确认并开始下载'; submitButton.classList.remove('loading');
          return;
        }
      }
      submitButton.textContent = '提交队列中...';
      logs?.renderLogs([
        '阶段 2/3：清晰度识别完成',
        payload.videoQuality ? `已选择：${payload.videoQuality}` : '使用自动最优画质',
        '阶段 3/3：提交本地任务队列',
      ]);
      const data = await submitQueue(payload, links);
      const count = (data.tasks || []).length;
      result?.setStatus('running', `${count} 个任务已进入队列，可在“下载中”查看进度`);
      logs?.renderLogs([
        '任务已提交',
        `任务数量：${count}`,
        '状态：等待执行',
        '可切换到“下载中”查看阶段、耗时并取消等待中的任务。',
      ]);
      window.StreamDockTaskCenter?.refreshNow?.();
      tabs?.setActiveTab?.('downloading');
      ui?.showToast('解析任务已加入队列');
    } catch (error) {
      const message = friendlyRequestError(error);
      result?.setStatus('error', message);
      result?.showResult({ error: message });
      logs?.renderLogs(['任务提交失败', message]);
      ui?.showToast(message);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = confirmedProbeKey ? '确认并开始下载' : '开始解析';
      submitButton.classList.remove('loading');
    }
  });

  linkInput?.addEventListener('input', () => { confirmedProbeKey = ''; if (probePreview) probePreview.hidden = true; if (submitButton) submitButton.textContent = '开始解析'; });

  clearLogButton?.addEventListener('click', () => {
    logs?.renderLogs([]);
    ui?.showToast('日志已清空');
  });
})();
