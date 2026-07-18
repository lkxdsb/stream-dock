(function () {
  const form = document.getElementById('fetchForm');
  const linkInput = document.getElementById('link');
  const outputType = document.getElementById('outputType');
  const outputPath = document.getElementById('outputPath');
  const bilibiliCookie = document.getElementById('bilibiliCookie');
  const saveAssets = document.getElementById('saveAssets');
  const subtitleStrategy = document.getElementById('subtitleStrategy');
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
  const probeAuthor = document.getElementById('mediaProbeAuthor');
  const probeFacts = document.getElementById('mediaProbeFacts');
  const probeCover = document.getElementById('mediaProbeCover');
  const probeCoverEmpty = document.getElementById('mediaProbeCoverEmpty');
  const probeSummary = document.getElementById('mediaProbeSummary');
  const probeDetailGrid = document.getElementById('mediaProbeDetailGrid');
  const probeToggle = document.getElementById('mediaProbeToggle');
  const probeCancel = document.getElementById('mediaProbeCancel');
  const probeResetButton = document.getElementById('probeResetButton');
  const streamTable = document.getElementById('mediaStreamTable');
  const streamDetails = document.getElementById('mediaProbeDetails');
  let confirmedProbeKey = '';
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const mediaCoverSrc = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (raw.startsWith('data:') || raw.startsWith('blob:') || raw.startsWith('/')) return raw;
    const normalized = raw.startsWith('//') ? `https:${raw}` : raw;
    return /^https?:\/\//i.test(normalized) ? `/api/media/cover-proxy?url=${encodeURIComponent(normalized)}` : normalized;
  };

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return `${size.toFixed(index === 0 ? 0 : 1)}${units[index]}`;
  }

  function bitrateLabel(value) {
    const bitrate = Number(value || 0);
    return bitrate ? `${Math.round(bitrate / 1000)} kbps` : '';
  }

  function detailCell(label, value) {
    if (value === undefined || value === null || value === '') return '';
    return `<div class="media-probe-detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
  }

  function coverFrameMetrics(naturalWidth, naturalHeight) {
    const width = Number(naturalWidth || 0);
    const height = Number(naturalHeight || 0);
    if (width <= 0 || height <= 0) return null;
    const ratio = width / height;
    const orientation = ratio > 1.08 ? 'landscape' : (ratio < 0.92 ? 'portrait' : 'square');
    const bounds = orientation === 'landscape'
      ? { width: 200, height: 120 }
      : (orientation === 'portrait' ? { width: 132, height: 148 } : { width: 132, height: 132 });
    const scale = Math.min(bounds.width / width, bounds.height / height, 1);
    return {
      orientation,
      width: Math.max(1, Math.round(width * scale)),
      height: Math.max(1, Math.round(height * scale)),
      aspect: `${width} / ${height}`,
    };
  }

  function resetCoverFrame() {
    const frame = probeCover?.closest('.media-probe-cover-wrap');
    if (!frame) return;
    frame.classList.remove('is-portrait', 'is-landscape', 'is-square', 'is-missing');
    frame.style.removeProperty('--media-cover-aspect');
    frame.style.removeProperty('--media-cover-width');
    frame.style.removeProperty('--media-cover-height');
  }

  function setProbeCover(url) {
    if (!probeCover || !probeCoverEmpty) return;
    resetCoverFrame();
    probeCover.onload = null;
    probeCover.onerror = null;
    const src = mediaCoverSrc(url);
    if (!src) {
      probeCover.removeAttribute('src');
      probeCover.hidden = true;
      probeCoverEmpty.textContent = '暂无封面';
      probeCoverEmpty.hidden = false;
      return;
    }
    probeCover.onload = () => {
      const frame = probeCover.closest('.media-probe-cover-wrap');
      if (frame) {
        const metrics = coverFrameMetrics(probeCover.naturalWidth, probeCover.naturalHeight);
        if (metrics) {
          frame.style.setProperty('--media-cover-aspect', metrics.aspect);
          frame.style.setProperty('--media-cover-width', `${metrics.width}px`);
          frame.style.setProperty('--media-cover-height', `${metrics.height}px`);
          frame.classList.toggle('is-portrait', metrics.orientation === 'portrait');
          frame.classList.toggle('is-landscape', metrics.orientation === 'landscape');
          frame.classList.toggle('is-square', metrics.orientation === 'square');
        }
        frame.classList.remove('is-missing');
      }
      probeCover.hidden = false;
      probeCoverEmpty.hidden = true;
    };
    probeCover.onerror = () => {
      const frame = probeCover.closest('.media-probe-cover-wrap');
      frame?.classList.add('is-missing');
      probeCover.removeAttribute('src');
      probeCover.hidden = true;
      probeCoverEmpty.textContent = '封面加载失败';
      probeCoverEmpty.hidden = false;
    };
    probeCoverEmpty.textContent = '封面加载中';
    probeCoverEmpty.hidden = false;
    probeCover.hidden = true;
    probeCover.src = src;
  }

  function summaryCell(label, value) {
    return `<div class="media-probe-summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || '-')}</strong></div>`;
  }

  function renderProbePreview(data) {
    if (!probePreview || !data) return;
    probePlatform.textContent = data.platform || '未知平台';
    probeTitle.textContent = data.title || '未命名视频';
    if (probeAuthor) probeAuthor.textContent = data.author ? `作者：${data.author}` : '';
    setProbeCover(data.coverUrl);
    const recommendation = data.recommendations?.best_quality?.stream;
    const subtitleCount = Number(data.assetSummary?.subtitleCount ?? data.probeSummary?.subtitleCount ?? 0);
    const summary = data.probeSummary || {};
    const best = recommendation || data.videoStreams?.[0] || {};
    const bestSize = summary.bestFilesizeLabel || best.filesizeLabel || formatBytes(best.filesize) || '平台未返回';
    const bestBitrate = summary.bestBitrateLabel || bitrateLabel(best.bitrate) || '未知';
    const bestContainer = String(summary.bestContainer || best.container || (best.isHls ? 'm3u8' : '') || '未知').toUpperCase();
    const streamCount = Number(summary.qualityCount ?? data.videoStreams?.length ?? 0);
    const subtitleHint = subtitleCount > 0
      ? `${subtitleCount} 条字幕轨`
      : (saveAssets?.checked ? '将语音识别字幕' : '暂无字幕轨');
    probeFacts.innerHTML = [
      `${streamCount || 0} 路视频流`,
      recommendation ? `最高可达 ${quality?.friendlyResolution?.(recommendation) || `${recommendation.height || ''}P`}` : '自动优选',
      best.filesize || summary.bestFilesize ? `约 ${bestSize}` : '大小未知',
      data.coverUrl ? '封面可保存' : '无封面',
      subtitleHint,
      data.probeSummary?.delivery === 'hls' ? 'HLS 合流' : '直链资源',
    ].map((item) => `<em>${item}</em>`).join('');
    if (probeSummary) {
      probeSummary.innerHTML = [
        summaryCell('推荐画质', summary.bestQualityLabel || best.qualityLabel || quality?.friendlyResolution?.(best) || '自动'),
        summaryCell('分辨率', summary.bestResolution || (best.width && best.height ? `${best.width}×${best.height}` : quality?.friendlyResolution?.(best))),
        summaryCell('资源大小', bestSize),
        summaryCell('下载方式', summary.delivery === 'hls' ? 'HLS 合流' : '直链下载'),
      ].join('');
    }
    if (probeDetailGrid) {
      const metadata = data.metadata || {};
      probeDetailGrid.innerHTML = [
        detailCell('平台', data.platform || '未知'),
        detailCell('内容类型', data.contentType || 'video'),
        detailCell('作者', data.author || '平台未返回'),
        detailCell('推荐容器', bestContainer),
        detailCell('推荐编码', summary.bestCodec || best.codec || '未知'),
        detailCell('推荐码率', bestBitrate),
        detailCell('候选视频流', `${streamCount} 路`),
        detailCell('候选音频流', `${Number(data.audioStreams?.length || 0)} 路`),
        detailCell('字幕轨', subtitleCount > 0 ? `${subtitleCount} 条` : '未发现'),
        detailCell('封面', data.coverUrl ? '可预览 / 可保存' : '平台未返回'),
        detailCell('来源策略', metadata.capture_strategy || metadata.resolve_method || '默认解析'),
        detailCell('下载提示', summary.downloadHint || summary.deliveryHint || '请确认后开始下载'),
        detailCell('资源域名', best.host || '未知'),
      ].join('');
    }
    const recommended = new Map();
    Object.entries(data.recommendations || {}).forEach(([strategy, item]) => { if (item?.stream?.qualityLabel) recommended.set(item.stream.qualityLabel, strategy); });
    const deduplicated = Array.from((data.videoStreams || []).reduce((groups, stream) => {
      const codec = String(stream.codec || '').toLowerCase().replace(/[^a-z0-9].*$/, '');
      const key = `${stream.width || 0}x${stream.height || 0}:${codec}`;
      const previous = groups.get(key);
      if (!previous || Number(stream.bitrate || 0) > Number(previous.bitrate || 0)) groups.set(key, stream);
      return groups;
    }, new Map()).values()).sort((a, b) => Number(b.height || 0) - Number(a.height || 0) || Number(b.bitrate || 0) - Number(a.bitrate || 0)).slice(0, 10);
    if (streamDetails) streamDetails.querySelector('summary').textContent = `高级技术详情（已从 ${(data.videoStreams || []).length} 路去重为 ${deduplicated.length} 路）`;
    streamTable.innerHTML = deduplicated.map((stream) => {
      const strategy = recommended.get(stream.qualityLabel); const reason = strategy === 'best_quality' ? '最佳画质' : strategy === 'best_compatibility' ? '最佳兼容' : strategy === 'smallest_size' ? '最小体积' : '';
      return `<div class="media-stream-row" data-stream-label="${escapeHtml(stream.qualityLabel || '')}"><strong>${escapeHtml(quality?.friendlyResolution?.(stream) || '清晰度未知')}</strong><span>${escapeHtml(stream.width && stream.height ? `${stream.width}×${stream.height}` : '分辨率未知')}</span><span>${escapeHtml((stream.codec || '编码未知').toUpperCase())}</span><span>${escapeHtml(stream.bitrate ? `${Math.round(stream.bitrate / 1000)} kbps` : '码率未知')}</span><span>${escapeHtml(stream.filesizeLabel || formatBytes(stream.filesize) || (stream.isHls ? 'HLS 分片' : '大小未知'))}</span><button type="button" data-select-stream="${escapeHtml(stream.qualityLabel || '')}">${escapeHtml(reason || '使用此流')}</button></div>`;
    }).join('');
    streamTable.querySelectorAll('[data-select-stream]').forEach((button) => button.addEventListener('click', () => {
      const stream = deduplicated.find((item) => item.qualityLabel === button.dataset.selectStream);
      quality?.selectManualStream?.(stream);
      streamTable.querySelectorAll('.media-stream-row').forEach((row) => row.classList.remove('is-selected'));
      button.closest('.media-stream-row').classList.add('is-selected');
      submitButton.textContent = '确认并开始下载';
    }));
    probePreview.hidden = false;
    if (probeCancel) probeCancel.hidden = false;
    if (probeResetButton) probeResetButton.hidden = false;
    if (probeToggle) {
      probeToggle.setAttribute('aria-expanded', streamDetails?.open ? 'true' : 'false');
    }
  }



  async function probeSingleLink(link) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch('/api/media/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          link,
          bilibiliCookie: String(bilibiliCookie?.value || '').trim() || null,
        }),
      });
      const data = await readJson(response);
      if (!response.ok || !data.success) throw new Error(data.error || data.detail || '识别失败');
      return data;
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error('清晰度识别超时，请稍后重试');
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  async function probeBatchLinks(links) {
    const results = [];
    for (let index = 0; index < links.length; index += 1) {
      const link = links[index];
      logs?.renderLogs([
        '阶段 1/3：批量识别视频资源',
        `正在识别第 ${index + 1}/${links.length} 条`,
        link,
      ]);
      try {
        const data = await probeSingleLink(link);
        results.push({ link, success: true, data });
      } catch (error) {
        results.push({ link, success: false, error: friendlyRequestError(error) });
      }
    }
    return results;
  }

  function renderBatchProbePreview(items, payload) {
    if (!probePreview || !items.length) return;
    const successItems = items.filter((item) => item.success && item.data);
    const failedItems = items.filter((item) => !item.success);
    const first = successItems[0]?.data || {};
    const coverCount = successItems.filter((item) => item.data?.coverUrl).length;
    const nativeSubtitleCount = successItems.reduce((sum, item) => sum + Number(item.data?.assetSummary?.subtitleCount ?? item.data?.probeSummary?.subtitleCount ?? 0), 0);
    const maxHeight = Math.max(...successItems.map((item) => Number(item.data?.recommendations?.best_quality?.stream?.height || item.data?.videoStreams?.[0]?.height || 0)), 0);
    const maxQuality = maxHeight ? `${maxHeight}P` : '自动最优';

    probePlatform.textContent = 'BATCH';
    probeTitle.textContent = `${successItems.length}/${items.length} 条视频已识别，确认后开始下载`;
    if (probeAuthor) probeAuthor.textContent = payload.saveAssets ? '封面和字幕保存已开启' : '仅下载媒体文件，封面和字幕不会保存';
    setProbeCover(first.coverUrl);
    probeFacts.innerHTML = [
      `${items.length} 条链接`,
      `${successItems.length} 条可下载`,
      failedItems.length ? `${failedItems.length} 条识别失败` : `最高可达 ${maxQuality}`,
      payload.saveAssets ? `封面保存 ${coverCount}/${successItems.length}` : '封面未开启保存',
      nativeSubtitleCount > 0 ? `原生字幕 ${nativeSubtitleCount} 条` : '无原生字幕，将按策略兜底',
    ].map((item) => `<em>${escapeHtml(item)}</em>`).join('');
    if (probeSummary) {
      probeSummary.innerHTML = [
        summaryCell('批量状态', failedItems.length ? '部分失败，请调整链接后重试' : '全部识别完成'),
        summaryCell('下载画质', `每条自动选择当前最优 · 最高 ${maxQuality}`),
        summaryCell('封面/字幕', payload.saveAssets ? '将随视频保存到输出目录' : '当前未开启保存'),
        summaryCell('字幕策略', payload.subtitleStrategy === 'native' ? '仅平台原生字幕' : payload.subtitleStrategy === 'ocr' ? '仅 OCR 画面字幕' : payload.subtitleStrategy === 'native-asr-ocr' ? '原生 → ASR → OCR' : '原生 → ASR'),
      ].join('');
    }
    if (probeDetailGrid) {
      probeDetailGrid.innerHTML = [
        detailCell('总链接', `${items.length} 条`),
        detailCell('可下载', `${successItems.length} 条`),
        detailCell('识别失败', failedItems.length ? `${failedItems.length} 条` : '无'),
        detailCell('封面保存', payload.saveAssets ? `${coverCount} 条可保存` : '未开启'),
        detailCell('原生字幕', nativeSubtitleCount > 0 ? `${nativeSubtitleCount} 条` : '未发现'),
        detailCell('兜底策略', payload.saveAssets ? '无原生字幕时按字幕策略尝试补齐' : '未开启资产保存'),
      ].join('');
    }
    if (streamDetails) streamDetails.querySelector('summary').textContent = '批量识别详情';
    if (streamTable) {
      streamTable.innerHTML = items.map((item, index) => {
        if (!item.success) {
          return `<div class="media-stream-row media-batch-row is-error"><strong>${index + 1}. 识别失败</strong><span>${escapeHtml(item.error || '无法识别')}</span><span>${escapeHtml(item.link)}</span></div>`;
        }
        const data = item.data || {};
        const best = data.recommendations?.best_quality?.stream || data.videoStreams?.[0] || {};
        const subtitles = Number(data.assetSummary?.subtitleCount ?? data.probeSummary?.subtitleCount ?? 0);
        return `<div class="media-stream-row media-batch-row"><strong>${index + 1}. ${escapeHtml(data.platform || 'unknown')}</strong><span>${escapeHtml(data.title || '未命名视频')}</span><span>${escapeHtml(quality?.friendlyResolution?.(best) || '自动最优')}</span><span>${data.coverUrl ? '封面可保存' : '无封面'}</span><span>${subtitles > 0 ? `${subtitles} 条字幕` : '无原生字幕'}</span></div>`;
      }).join('');
    }
    probePreview.hidden = false;
    if (probeCancel) probeCancel.hidden = false;
    if (probeResetButton) probeResetButton.hidden = false;
    if (probeToggle) probeToggle.setAttribute('aria-expanded', streamDetails?.open ? 'true' : 'false');
  }

  function buildProbeKey(links, payload) {
    return JSON.stringify({
      links,
      outputType: payload.outputType,
      bilibiliCookie: payload.bilibiliCookie,
      saveAssets: Boolean(payload.saveAssets),
      subtitleStrategy: payload.subtitleStrategy || 'native-asr-ocr',
    });
  }

  probeToggle?.addEventListener('click', (event) => {
    event.preventDefault();
    if (!streamDetails) return;
    streamDetails.open = !streamDetails.open;
    probeToggle.textContent = streamDetails.open ? '收起详情' : '查看详情';
    probeToggle.setAttribute('aria-expanded', streamDetails.open ? 'true' : 'false');
    if (streamDetails.open) {
      streamDetails.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });
  streamDetails?.addEventListener('toggle', () => {
    if (probeToggle) probeToggle.textContent = streamDetails.open ? '收起详情' : '查看详情';
    if (probeToggle) probeToggle.setAttribute('aria-expanded', streamDetails.open ? 'true' : 'false');
  });

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

  function resetProbeState({ clearInput = false, resetWorkspace = false, toast = '' } = {}) {
    confirmedProbeKey = '';
    if (clearInput && linkInput) linkInput.value = '';
    if (probePreview) probePreview.hidden = true;
    if (probeCancel) probeCancel.hidden = true;
    if (probeResetButton) probeResetButton.hidden = true;
    if (probeCover) {
      probeCover.onload = null;
      probeCover.onerror = null;
      probeCover.removeAttribute('src');
      probeCover.hidden = true;
    }
    resetCoverFrame();
    if (probeCoverEmpty) {
      probeCoverEmpty.textContent = '暂无封面';
      probeCoverEmpty.hidden = false;
    }
    if (probePlatform) probePlatform.textContent = '待识别';
    if (probeTitle) probeTitle.textContent = '视频信息';
    if (probeAuthor) probeAuthor.textContent = '';
    if (probeFacts) probeFacts.innerHTML = '';
    if (probeSummary) probeSummary.innerHTML = '';
    if (probeDetailGrid) probeDetailGrid.innerHTML = '';
    if (streamTable) streamTable.innerHTML = '';
    if (streamDetails) streamDetails.open = false;
    if (probeToggle) {
      probeToggle.textContent = '查看详情';
      probeToggle.setAttribute('aria-expanded', 'false');
    }
    quality?.invalidateProbeCache?.();
    quality?.resetQualityOptions?.(quality?.isVideoOutputType?.(outputType?.value) ? '最佳画质（自动）' : '音频输出无需选择');
    quality?.setQualityHint?.(quality?.isVideoOutputType?.(outputType?.value) ? '自动选择当前可达最高画质。' : '当前为音频导出，无需选择清晰度。');
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = '开始解析';
      submitButton.classList.remove('loading');
    }
    if (resetWorkspace) {
      result?.resetRecentCard?.('等待新的解析任务');
      logs?.renderLogs(['等待执行...']);
    }
    if (toast) ui?.showToast?.(toast);
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
        saveAssets: Boolean(payload.saveAssets),
        subtitleStrategy: payload.subtitleStrategy || 'native-asr-ocr',
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
      saveAssets: Boolean(saveAssets?.checked),
      subtitleStrategy: String(subtitleStrategy?.value || 'native-asr-ocr'),
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
    submitButton.textContent = '识别中...';
    submitButton.classList.add('loading');
    result?.setStatus('running', links.length > 1 ? `正在识别 ${links.length} 条链接` : '正在识别链接与可用画质');
    logs?.renderLogs([
      '阶段 1/3：校验链接',
      `链接数量：${links.length}`,
      links.length > 1 ? '批量任务会先识别，确认后再加入下载队列。' : '正在识别可用清晰度...',
    ]);
    result?.showResult();

    try {
      if (quality?.isVideoOutputType(payload.outputType)) {
        const probeKey = buildProbeKey(links, payload);
        if (confirmedProbeKey !== probeKey) {
          if (links.length === 1) {
            const probeData = await quality.probeQualityOptions(links[0], { silent: true });
            payload.videoQuality = String(quality?.selectedQualityLabel?.() || '').trim();
            renderProbePreview(probeData);
            confirmedProbeKey = probeKey;
            result?.setStatus('running', '已识别视频资源，请确认画质后开始下载');
            logs?.renderLogs(['视频资源识别完成', `平台：${probeData?.platform || 'unknown'}`, '已整理为：最高画质 / 兼容优先 / 小体积', payload.saveAssets ? '确认后会同时保存封面和字幕。' : '当前未开启封面和字幕保存。']);
          } else {
            const batchProbe = await probeBatchLinks(links);
            renderBatchProbePreview(batchProbe, payload);
            const failed = batchProbe.filter((item) => !item.success);
            if (failed.length) {
              result?.setStatus('error', `${failed.length} 条链接识别失败，请调整后重试`);
              logs?.renderLogs(['批量识别未全部通过', ...failed.map((item, index) => `${index + 1}. ${item.error || '识别失败'}：${item.link}`)]);
              submitButton.disabled = false;
              submitButton.textContent = '重新识别';
              submitButton.classList.remove('loading');
              return;
            }
            confirmedProbeKey = probeKey;
            result?.setStatus('running', `${links.length} 条视频已识别，请确认后开始下载`);
            logs?.renderLogs(['批量视频资源识别完成', `链接数量：${links.length}`, payload.saveAssets ? '确认后会同时保存封面和字幕；无原生字幕时按当前字幕策略兜底。' : '当前未开启封面和字幕保存。', '请确认后再次点击。']);
          }
          submitButton.disabled = false;
          submitButton.textContent = links.length > 1 ? '确认并开始批量下载' : '确认并开始下载';
          submitButton.classList.remove('loading');
          return;
        }
        if (links.length === 1) payload.videoQuality = String(quality?.selectedQualityLabel?.() || '').trim();
      }
      submitButton.textContent = '提交队列中...';
      logs?.renderLogs([
        '阶段 2/3：清晰度识别完成',
        payload.videoQuality ? `已选择：${payload.videoQuality}` : '使用自动最优画质',
        '阶段 3/3：提交本地任务队列',
      ]);
      const data = await submitQueue(payload, links);
      const count = (data.tasks || []).length;
      result?.trackTasks?.((data.tasks || []).map((task) => task.id));
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
      submitButton.textContent = confirmedProbeKey ? (extractLinks(linkInput?.value || '').length > 1 ? '确认并开始批量下载' : '确认并开始下载') : '开始解析';
      submitButton.classList.remove('loading');
    }
  });

  linkInput?.addEventListener('input', () => {
    resetProbeState({ clearInput: false });
  });

  function cancelProbeAndReset() {
    resetProbeState({ clearInput: true, resetWorkspace: true, toast: '已取消本次识别，回到待解析状态' });
    linkInput?.focus();
  }

  probeCancel?.addEventListener('click', cancelProbeAndReset);
  probeResetButton?.addEventListener('click', cancelProbeAndReset);

  clearLogButton?.addEventListener('click', () => {
    logs?.renderLogs([]);
    ui?.showToast('日志已清空');
  });
})();
