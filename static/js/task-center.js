(function () {
  const convertList = document.getElementById('convertTaskList');
  const convertEmpty = document.getElementById('convertTaskEmpty');
  const downloadingTasks = document.getElementById('downloadingTasks');
  const completedTasks = document.getElementById('completedTasks');
  const downloadingEmpty = document.getElementById('downloadingEmpty');
  const completedEmpty = document.getElementById('completedEmpty');
  const detailLayer = document.getElementById('taskDetailLayer');
  const detailTitle = document.getElementById('taskDetailTitle');
  const detailContent = document.getElementById('taskDetailContent');
  const detailFooter = document.getElementById('taskDetailFooter');
  const mediaTaskSearch = document.getElementById('mediaTaskSearch');
  const mediaTaskStatusFilter = document.getElementById('mediaTaskStatusFilter');
  const mediaFinishedSummary = document.getElementById('mediaFinishedSummary');
  const convertTaskSearch = document.getElementById('convertTaskSearch');
  const convertTaskStatusFilter = document.getElementById('convertTaskStatusFilter');
  const POLL_MS = 3500;
  const MEDIA_FINISHED_PREVIEW_LIMIT = 3;
  let timer = null;
  let lastPresentedMediaTaskKey = '';
  let currentDetailTaskId = '';
  let latestMediaTasks = [];
  let latestConvertTasks = [];

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function mediaCoverSrc(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (raw.startsWith('data:') || raw.startsWith('blob:') || raw.startsWith('/')) return raw;
    const normalized = raw.startsWith('//') ? `https:${raw}` : raw;
    if (/^https?:\/\//i.test(normalized)) {
      return `/api/media/cover-proxy?url=${encodeURIComponent(normalized)}`;
    }
    return normalized;
  }

  function mediaLocalAssetSrc(taskId, path) {
    const raw = String(path || '').trim();
    if (!taskId || !raw) return '';
    return `/api/media/tasks/${encodeURIComponent(taskId)}/asset?path=${encodeURIComponent(raw)}`;
  }

  function cssEscape(value) {
    if (window.CSS?.escape) return CSS.escape(String(value || ''));
    return String(value || '').replace(/["\\]/g, '\\$&');
  }

  function statusLabel(status) {
    return status === 'pending' ? '等待中'
      : status === 'running' ? '处理中'
        : status === 'completed' ? '已完成'
          : status === 'failed' ? '失败'
            : status === 'skipped' ? '已跳过'
              : status === 'cancelled' ? '已取消'
                : status || '未知';
  }

  function subtitleJob(task) {
    const job = task?.result?.subtitleJob;
    return job && typeof job === 'object' ? job : {};
  }

  function subtitleJobActive(task) {
    return ['pending', 'running'].includes(String(subtitleJob(task).status || ''));
  }

  function subtitleJobLabel(task) {
    const job = subtitleJob(task);
    const status = String(job.status || '');
    if (status === 'pending') return '字幕等待后台识别';
    if (status === 'running') return '字幕正在后台识别';
    if (status === 'completed') return job.message || '字幕已生成';
    if (status === 'unavailable') return job.message || '未生成字幕（视频可用）';
    if (status === 'failed' || status === 'interrupted') return job.message || '字幕识别未完成（视频可用）';
    if (status === 'skipped') return job.message || '已跳过字幕';
    return '';
  }

  function stageLabel(task) {
    if (task.status === 'completed' && subtitleJobActive(task)) return '视频已下载';
    if (task.status !== 'running') return statusLabel(task.status);
    if (task.stage && !['处理中', '等待中'].includes(task.stage)) return task.stage;
    const log = String((task.logs || []).filter(Boolean).slice(-1)[0] || '').toLowerCase();
    if (log.includes('等待')) return '等待中';
    if (log.includes('校验') || log.includes('verify')) return '校验中';
    if (log.includes('合并') || log.includes('merge') || log.includes('mux')) return '合并中';
    if (log.includes('下载') || log.includes('download')) return '下载中';
    if (log.includes('转换') || log.includes('convert') || log.includes('ffmpeg')) return '转换中';
    if (log.includes('识别') || log.includes('解析') || log.includes('probe')) return '识别中';
    return '处理中';
  }

  function elapsedLabel(task) {
    const started = Date.parse(task.createdAt || '');
    const ended = ['completed', 'failed', 'cancelled', 'skipped'].includes(task.status)
      ? Date.parse(task.updatedAt || '')
      : Date.now();
    if (!Number.isFinite(started) || !Number.isFinite(ended)) return '';
    const seconds = Math.max(0, Math.round((ended - started) / 1000));
    if (seconds < 60) return `${seconds} 秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
  }

  function dateLabel(value) {
    const date = new Date(value || '');
    if (!Number.isFinite(date.getTime())) return '-';
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(date);
  }

  function taskMeta(task) {
    const payload = task.payload || {};
    const result = task.result || {};
    return [
      payload.source && payload.target ? `${String(payload.source).toUpperCase()} → ${String(payload.target).toUpperCase()}` : '',
      result.platform || payload.platform || '',
      payload.outputType ? String(payload.outputType).toUpperCase() : '',
      payload.videoQuality || '',
      result.outputPath || payload.outputPath || '',
    ].filter(Boolean).join(' · ');
  }

  function taskDisplayTitle(task) {
    return task.result?.title || task.title || '本地任务';
  }

  function validationSummary(task) {
    const validation = task.result?.validation || {};
    if (!validation.valid) return '';
    const resolution = validation.width && validation.height ? `${validation.width}×${validation.height}` : '';
    const codecs = [validation.videoCodec, validation.audioCodec].filter(Boolean).join('/');
    return [resolution, codecs, validation.sizeLabel, '校验通过'].filter(Boolean).join(' · ');
  }

  function compactActivity(task) {
    if (task.status === 'completed' && subtitleJobActive(task)) {
      return subtitleJob(task).message || '视频已可用，字幕正在后台识别';
    }
    if (task.status !== 'running') return statusLabel(task.status);
    const lines = (task.logs || []).flatMap((item) => String(item || '').split('\n'))
      .map((item) => item.replace(/^\[douyin-fetch\]\s*/, '').trim())
      .filter((item) => item && !item.startsWith('http'));
    const value = lines.slice(-1)[0] || task.stage || stageLabel(task);
    return value.length > 110 ? `${value.slice(0, 107)}...` : value;
  }

  function filterTasks(tasks, searchControl, statusControl) {
    const query = String(searchControl?.value || '').trim().toLowerCase();
    const status = statusControl?.value || 'all';
    return tasks.filter((task) => {
      if (status !== 'all' && task.status !== status) return false;
      if (!query) return true;
      const result = task.result || {};
      const payload = task.payload || {};
      const haystack = [
        task.title, task.status, task.stage, task.error,
        result.title, result.platform, result.author, result.outputPath, result.finalUrl, result.coverUrl,
        payload.link, payload.filename, payload.source, payload.target, payload.outputType, payload.videoQuality, payload.outputPath,
        ...(Array.isArray(task.logs) ? task.logs : []),
      ]
        .filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }

  function renderMediaFinished() {
    const finished = latestMediaTasks.filter((task) => ['completed', 'failed', 'skipped', 'cancelled'].includes(task.status));
    const filtered = filterTasks(finished, mediaTaskSearch, mediaTaskStatusFilter);
    const hasSearch = Boolean(String(mediaTaskSearch?.value || '').trim());
    const hasStatusFilter = (mediaTaskStatusFilter?.value || 'all') !== 'all';
    const shouldPreview = !hasSearch && !hasStatusFilter && filtered.length > MEDIA_FINISHED_PREVIEW_LIMIT;
    const visible = shouldPreview ? filtered.slice(0, MEDIA_FINISHED_PREVIEW_LIMIT) : filtered;
    if (completedEmpty) {
      completedEmpty.textContent = (hasSearch || hasStatusFilter)
        ? '没有符合条件的记录。'
        : '还没有完成记录。';
    }
    render(completedTasks, completedEmpty, visible);
    if (mediaFinishedSummary) {
      if (!finished.length) {
        mediaFinishedSummary.textContent = '';
      } else if (shouldPreview) {
        mediaFinishedSummary.textContent = `默认展示最近 ${MEDIA_FINISHED_PREVIEW_LIMIT} 条，共 ${filtered.length} 条历史；搜索或筛选可查看全部记录。`;
      } else {
        mediaFinishedSummary.textContent = `当前显示 ${filtered.length} 条，共 ${finished.length} 条历史。`;
      }
    }
  }

  function renderConvertTasks() {
    const filtered = filterTasks(latestConvertTasks, convertTaskSearch, convertTaskStatusFilter);
    const hasSearch = Boolean(String(convertTaskSearch?.value || '').trim());
    const hasStatusFilter = (convertTaskStatusFilter?.value || 'all') !== 'all';
    if (convertEmpty) {
      convertEmpty.textContent = (hasSearch || hasStatusFilter)
        ? '没有符合条件的转换任务。'
        : '当前没有转换任务。批量转换或单文件转换完成后会显示在这里。';
    }
    render(convertList, convertEmpty, filtered);
  }

  function sourceLabel(task) {
    const payload = task.payload || {};
    return payload.link || payload.filename || (payload.source && payload.target
      ? `${String(payload.source).toUpperCase()} → ${String(payload.target).toUpperCase()}`
      : '-');
  }

  function errorPresentation(rawError) {
    const error = String(rawError || '').trim();
    const lowered = error.toLowerCase();
    if (!error) return { title: '任务未完成', hint: '这次没有拿到完整结果，可以重新提交链接，或打开运行记录查看原因。', action: 'logs', actionLabel: '查看运行记录' };
    if (lowered.includes('timeout') || error.includes('超时')) {
      return { title: '处理超时', hint: '平台响应较慢或文件较大，可以稍后重新执行。', action: 'retry', actionLabel: '重新执行' };
    }
    if (error.includes('登录') || lowered.includes('cookie') || error.includes('权限')) {
      return { title: '当前内容需要登录或权限', hint: '打开高级选项，确认浏览器登录态或补充 Cookie 后重试。', action: 'openAdvanced', actionLabel: '打开高级选项' };
    }
    if (lowered.includes('ffmpeg') || lowered.includes('mineru') || error.includes('引擎') || error.includes('依赖')) {
      return { title: '本地依赖不可用', hint: '打开本地环境状态，检查 FFmpeg、PDF 引擎或转换依赖。', action: 'health', actionLabel: '检查本地环境' };
    }
    if (error.includes('不支持') || error.includes('无法识别') || error.includes('未识别') || lowered.includes('unsupported')) {
      return { title: '暂不支持当前链接', hint: '请粘贴抖音、B站、快手、小红书、微博、视频号、YouTube、TikTok 或 X 的视频分享链接。', action: 'capability', actionLabel: '查看支持平台' };
    }
    if (error.includes('磁盘') || lowered.includes('no space')) {
      return { title: '磁盘空间不足', hint: '清理空间或更换输出目录后再次执行。', action: 'settings', actionLabel: '打开保存设置' };
    }
    if (error.includes('格式') || error.includes('内容与')) {
      return { title: '文件格式校验失败', hint: '文件扩展名与真实内容可能不一致，请重新选择源文件。', action: 'reselect', actionLabel: '重新选择文件' };
    }
    if (error.includes('取消')) {
      return { title: '任务已取消', hint: '任务记录已保留，可以重新提交。', action: 'retry', actionLabel: '重新提交' };
    }
    if (error.includes('网络') || lowered.includes('connection') || lowered.includes('http')) {
      return { title: '网络连接失败', hint: '请检查网络后重新执行；平台临时资源链接也可能已经失效。', action: 'retry', actionLabel: '重新执行' };
    }
    return { title: '这次没有成功完成', hint: '可以换一个链接、稍后重试，或打开运行记录查看最后停在哪一步。', action: 'logs', actionLabel: '查看运行记录' };
  }

  async function retryTask(task) {
    const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '重新执行失败');
    closeDetail();
    window.StreamDockUI?.showToast?.('已重新加入任务队列');
    if (task.kind === 'media') document.querySelector('[data-use-tab="downloading"]')?.click();
    await refresh();
  }

  function runFailureAction(task, action) {
    if (!action || action === 'logs') {
      detailContent?.querySelector('.task-detail-logs')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (action === 'retry') {
      if (task.kind === 'media') {
        retryTask(task).catch((error) => window.StreamDockUI?.showToast?.(error.message || '重新执行失败'));
        return;
      }
      closeDetail();
      const route = task.kind === 'pdf' ? '/pdf#workbench' : '/convert#workbench';
      const focus = task.kind === 'pdf' ? '#pdfPickButton' : '#convertPickButton';
      window.StreamDockUI?.schedulePageAction?.(route, { focus });
      return;
    }
    if (action === 'openAdvanced') {
      closeDetail();
      window.StreamDockUI?.schedulePageAction?.('/use#parse', { openAdvanced: true });
      return;
    }
    if (action === 'health') {
      closeDetail();
      const target = task.kind === 'pdf' ? '/pdf#workbench' : task.kind === 'convert' ? '/convert#settings' : '/use#settings';
      const scroll = task.kind === 'pdf' ? '.pdf-engine-card,#pdfHealth' : '.system-health-card';
      window.StreamDockUI?.schedulePageAction?.(target, { scroll });
      return;
    }
    if (action === 'settings') {
      closeDetail();
      const target = task.kind === 'convert' ? '/convert#settings' : task.kind === 'pdf' ? '/pdf#workbench' : '/use#settings';
      const scroll = task.kind === 'convert' ? '.convert-settings-card,.settings-form' : task.kind === 'pdf' ? '.pdf-fields' : '.settings-form';
      window.StreamDockUI?.schedulePageAction?.(target, { scroll });
      return;
    }
    if (action === 'reselect') {
      closeDetail();
      const route = task.kind === 'pdf' ? '/pdf#workbench' : '/convert#workbench';
      const focus = task.kind === 'pdf' ? '#pdfPickButton' : '#convertPickButton';
      window.StreamDockUI?.schedulePageAction?.(route, { focus });
      return;
    }
    if (action === 'capability') {
      closeDetail();
      if (task.kind === 'convert') window.StreamDockUI?.schedulePageAction?.('/convert#matrix', { scroll: '.convert-world-card' });
      else window.StreamDockUI?.navigateWithTransition?.('/platforms');
      return;
    }
  }

  function detailRow(label, value, useCode) {
    if (!value) return '';
    const tag = useCode ? 'code' : 'strong';
    return `<div class="task-detail-row"><span>${escapeHtml(label)}</span><${tag}>${escapeHtml(value)}</${tag}></div>`;
  }

  function additionalDetailRows(task) {
    const payload = task.payload || {};
    const result = task.result || {};
    const rows = [];
    const add = (label, value, useCode = false) => {
      if (value === undefined || value === null || value === '') return;
      rows.push(detailRow(label, typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value), useCode));
    };
    add('源链接', payload.link || result.sourceUrl, true);
    add('最终链接', result.finalUrl, true);
    add('封面链接', result.coverUrl, true);
    add('媒体类型', result.mediaKind || result.contentType || payload.contentType);
    add('处理策略', result.captureStrategy || result.capture_strategy || result.resolveMethod || result.resolve_method);
    add('返回码', result.returncode);
    add('标准输出', result.stdout, true);
    add('错误输出', result.stderr, true);
    return rows.join('');
  }

  function mediaAssetsSection(task) {
    if (task.kind !== 'media') return '';
    const result = task.result || {};
    const assets = result.assets || {};
    const subtitles = Array.isArray(assets.subtitles) ? assets.subtitles : [];
    const subtitleDetails = Array.isArray(assets.subtitleDetails) ? assets.subtitleDetails : [];
    const subtitleTracks = Array.isArray(result.subtitleTracks) ? result.subtitleTracks : [];
    const coverFile = assets.cover || '';
    const coverUrl = result.coverUrl || '';
    const subtitleCount = Number(result.subtitleCount || subtitleTracks.length || subtitles.length || 0);
    if (!result.title && !result.author && !coverUrl && !coverFile && subtitleCount <= 0) return '';
    const subtitleTrackLabel = subtitleTracks
      .slice(0, 4)
      .map((track) => [track.language, track.label || track.name || track.source].filter(Boolean).join(' · '))
      .filter(Boolean)
      .join('\n');
    const subtitleDetailLabel = subtitleDetails
      .map((item) => [item.source, item.quality, item.path].filter(Boolean).join(' · '))
      .filter(Boolean)
      .join('\n');
    return `<section class="task-detail-section media-assets-preview">
      <h3>视频信息与资产</h3>
      <div class="media-asset-layout">
        <div class="media-asset-cover">${coverFile || coverUrl ? `<img src="${escapeHtml(coverFile ? mediaLocalAssetSrc(task.id, coverFile) : mediaCoverSrc(coverUrl))}" alt="视频封面" loading="lazy">` : '<span>暂无封面</span>'}</div>
        <div class="task-detail-grid">
          ${detailRow('标题', result.title || task.title || '')}
          ${detailRow('作者', result.author || '')}
          ${detailRow('源封面', coverUrl ? '可预览' : '')}
          ${detailRow('封面', coverFile ? '已保存' : (coverUrl ? '可预览，未保存' : '未发现'))}
          ${detailRow('视频状态', result.outputPath ? '已下载，可立即打开' : '')}
          ${detailRow('字幕处理', subtitleJobLabel(task))}
          ${detailRow('字幕轨', subtitleCount > 0 ? `${subtitleCount} 条` : '未发现')}
          ${detailRow('字幕信息', subtitleTrackLabel, true)}
          ${detailRow('字幕来源', subtitleDetailLabel, true)}
          ${detailRow('封面文件', coverFile, true)}
          ${subtitles.length ? detailRow('字幕文件', subtitles.join('\\n'), true) : ''}
        </div>
      </div>
    </section>`;
  }

  function subtitleProgressSection(task) {
    if (task.kind !== 'media') return '';
    const job = subtitleJob(task);
    const label = subtitleJobLabel(task);
    if (!label || ['not_requested', 'skipped'].includes(String(job.status || ''))) return '';
    const active = subtitleJobActive(task);
    return `<section class="task-detail-section subtitle-job-section is-${escapeHtml(job.status || 'unknown')}">
      <h3>字幕处理（独立后台任务）</h3>
      <div class="subtitle-job-summary">
        <div><strong>${escapeHtml(label)}</strong><span>视频文件已经完成，不需要等待字幕识别即可打开。</span></div>
        <em>${active ? '后台处理中' : escapeHtml(job.status === 'completed' ? '已完成' : '视频不受影响')}</em>
      </div>
      ${active ? '<div class="task-progress-track indeterminate"><i></i></div>' : ''}
      ${job.error ? `<div class="subtitle-job-note">${escapeHtml(job.error)}</div>` : ''}
    </section>`;
  }

  function taskProgressSection(task) {
    if (!['pending', 'running'].includes(task.status)) return '';
    const numeric = Number(task.progress);
    const hasProgress = Number.isFinite(numeric);
    const width = hasProgress ? Math.max(2, Math.min(100, numeric)) : 0;
    const label = hasProgress ? `${Math.round(width)}%` : '正在处理';
    return `<section class="task-detail-section">
      <h3>处理进度</h3>
      <div class="task-detail-progress">
        <div class="task-progress-track ${hasProgress ? '' : 'indeterminate'}"><i style="${hasProgress ? `width:${width}%` : ''}"></i></div>
        <span>${escapeHtml(label)} · ${escapeHtml(compactActivity(task) || stageLabel(task))}</span>
      </div>
    </section>`;
  }

  async function postPath(endpoint, path) {
    const form = new FormData();
    form.append('path', path);
    const response = await fetch(endpoint, { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '操作失败');
    return data;
  }

  function bindAction(button, handler) {
    if (!button) return;
    button.addEventListener('click', async (event) => {
      event.stopPropagation();
      const original = button.textContent;
      button.disabled = true;
      try {
        await handler();
      } catch (error) {
        window.StreamDockUI?.showToast?.(error.message || '操作失败');
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
  }

  function closeDetail() {
    if (!detailLayer) return;
    detailLayer.hidden = true;
    document.body.style.overflow = '';
    currentDetailTaskId = '';
  }

  function showDetail(task) {
    if (!detailLayer || !detailTitle || !detailContent || !detailFooter) return;
    const shouldMoveFocus = detailLayer.hidden;
    const shouldPreserveScroll = !detailLayer.hidden && currentDetailTaskId === task.id;
    const previousContentScrollTop = detailContent.scrollTop;
    const previousLogs = detailContent.querySelector('.task-detail-logs');
    const previousLogsScrollTop = previousLogs?.scrollTop || 0;
    const payload = task.payload || {};
    const result = task.result || {};
    const outputPath = result.outputPath || '';
    const stage = stageLabel(task);
    const latestLog = compactActivity(task) || stage;
    const errorInfo = errorPresentation(task.error);

    detailTitle.textContent = taskDisplayTitle(task);
    detailContent.innerHTML = `
      <div class="task-detail-stage is-${escapeHtml(task.status || 'pending')}">
        <i class="task-detail-stage-mark" aria-hidden="true"></i>
        <div><strong>${escapeHtml(stage)}</strong><span>${escapeHtml(latestLog)}${elapsedLabel(task) ? ` · 已耗时 ${escapeHtml(elapsedLabel(task))}` : ''}</span></div>
      </div>
      ${taskProgressSection(task)}
      ${task.error ? `<section class="task-detail-section"><div class="task-detail-error"><strong>${escapeHtml(errorInfo.title)}</strong>${escapeHtml(errorInfo.hint)}<br>${escapeHtml(task.error)}<button class="task-error-action" type="button" data-failure-action="${escapeHtml(errorInfo.action || 'logs')}">${escapeHtml(errorInfo.actionLabel || '查看运行记录')}</button></div></section>` : ''}
      <section class="task-detail-section">
        <h3>基本信息</h3>
        <div class="task-detail-grid">
          ${detailRow('任务类型', task.kind === 'media' ? '视频解析' : task.kind === 'pdf' ? 'PDF 智能解析' : '文件转换')}
          ${detailRow('输入内容', sourceLabel(task), true)}
          ${detailRow('标题', result.title || task.title || '')}
          ${detailRow('输出格式', payload.outputType ? String(payload.outputType).toUpperCase() : (payload.target ? String(payload.target).toUpperCase() : ''))}
          ${detailRow('平台', result.platform || payload.platform || '')}
          ${detailRow('作者', result.author || '')}
          ${detailRow('清晰度', payload.videoQuality || '')}
          ${detailRow('创建时间', dateLabel(task.createdAt))}
          ${detailRow('更新时间', dateLabel(task.updatedAt))}
          ${detailRow('任务编号', task.id, true)}
        </div>
      </section>
      ${outputPath || payload.outputPath ? `<section class="task-detail-section"><h3>输出</h3><div class="task-detail-grid">${detailRow(outputPath ? '输出文件' : '保存目录', outputPath || payload.outputPath, true)}</div></section>` : ''}
      ${mediaAssetsSection(task)}
      ${subtitleProgressSection(task)}
      ${additionalDetailRows(task) ? `<section class="task-detail-section"><h3>完整上下文</h3><div class="task-detail-grid">${additionalDetailRows(task)}</div></section>` : ''}
      ${result.validation?.valid ? `<section class="task-detail-section"><h3>校验结果</h3><div class="task-detail-grid">
        ${detailRow('状态', '校验通过')}
        ${detailRow('文件大小', result.validation.sizeLabel || '')}
        ${detailRow('分辨率', result.validation.width && result.validation.height ? `${result.validation.width}×${result.validation.height}` : '')}
        ${detailRow('视频编码', result.validation.videoCodec || '')}
        ${detailRow('音频编码', result.validation.audioCodec || '')}
        ${detailRow('总码率', result.validation.bitrate ? `${Math.round(result.validation.bitrate / 1000)} kbps` : '')}
        ${detailRow('音画时长差', result.validation.audioVideoDeltaSeconds != null ? `${result.validation.audioVideoDeltaSeconds} 秒` : '')}
        ${detailRow('质量评分', result.validation.qualityScore != null ? `${result.validation.qualityScore} · ${result.validation.qualityLevel || ''}` : '')}
        ${detailRow('实际格式', result.validation.format || result.validation.detectedFormat || '')}
      </div>${(result.validation.warnings || []).length ? `<div class="task-detail-error">${escapeHtml(result.validation.warnings.join('\n'))}</div>` : ''}<div id="deepQualityResult"></div></section>` : ''}
      <section class="task-detail-section">
        <h3>运行记录</h3>
        <pre class="task-detail-logs">${escapeHtml((task.logs || []).filter(Boolean).join('\n') || '暂无运行记录')}</pre>
      </section>
    `;

    detailFooter.innerHTML = `
      ${outputPath ? '<button class="task-detail-action primary" type="button" data-open-file>打开文件</button><button class="task-detail-action" type="button" data-open-directory>打开目录</button><button class="task-detail-action" type="button" data-copy-output>复制路径</button>' : ''}
      ${task.error ? '<button class="task-detail-action" type="button" data-copy-error>复制错误</button>' : ''}
      ${task.kind === 'media' && ['failed', 'cancelled', 'skipped'].includes(task.status) ? '<button class="task-detail-action primary" type="button" data-retry-task>重新识别并执行</button>' : ''}
      ${task.kind === 'convert' && task.status === 'failed' ? '<button class="task-detail-action primary" type="button" data-reselect-file>重新选择文件</button>' : ''}
      ${task.kind === 'media' && ['pending', 'running'].includes(task.status) ? '<button class="task-detail-action" type="button" data-cancel-detail>取消任务</button>' : ''}
      ${task.kind === 'media' && task.status === 'completed' && outputPath ? '<button class="task-detail-action" type="button" data-deep-quality>深度质量检测</button>' : ''}
      ${['completed', 'failed', 'skipped', 'cancelled'].includes(task.status) && !subtitleJobActive(task) ? '<button class="task-detail-action danger" type="button" data-delete-detail>删除记录</button>' : ''}
    `;

    detailContent.querySelectorAll('[data-failure-action]').forEach((button) => {
      button.addEventListener('click', () => runFailureAction(task, button.dataset.failureAction));
    });

    bindAction(detailFooter.querySelector('[data-open-file]'), async () => {
      await postPath('/api/open-output-file', outputPath);
    });
    bindAction(detailFooter.querySelector('[data-open-directory]'), async () => {
      await postPath('/api/open-output-path', outputPath);
    });
    bindAction(detailFooter.querySelector('[data-copy-output]'), async () => {
      await navigator.clipboard?.writeText(outputPath);
      window.StreamDockUI?.showToast?.('路径已复制');
    });
    bindAction(detailFooter.querySelector('[data-copy-error]'), async () => {
      await navigator.clipboard?.writeText(task.error || '');
      window.StreamDockUI?.showToast?.('错误信息已复制');
    });
    bindAction(detailFooter.querySelector('[data-retry-task]'), async () => {
      const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '重新执行失败');
      closeDetail();
      window.StreamDockUI?.showToast?.('已重新识别并加入任务队列');
      document.querySelector('[data-use-tab="downloading"]')?.click();
      await refresh();
    });
    bindAction(detailFooter.querySelector('[data-reselect-file]'), async () => {
      closeDetail();
      document.querySelector('[data-convert-nav="workbench"]')?.click();
      window.setTimeout(() => document.getElementById('convertPickButton')?.focus(), 120);
    });
    bindAction(detailFooter.querySelector('[data-cancel-detail]'), async () => {
      await cancelTask(task.id);
      closeDetail();
      await refresh();
    });
    bindAction(detailFooter.querySelector('[data-delete-detail]'), async () => {
      await deleteTaskRecord(task.id);
      closeDetail();
      await refresh();
    });
    bindAction(detailFooter.querySelector('[data-deep-quality]'), async () => {
      const form = new FormData(); form.append('path', outputPath);
      const response = await fetch('/api/media/quality/deep', { method: 'POST', body: form }); const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '深度检测失败');
      const report = data.report; const target = detailContent.querySelector('#deepQualityResult');
      if (target) target.innerHTML = `<div class="task-detail-grid">${detailRow('深度评分', report.deepQualityScore)}${detailRow('黑屏区间', String((report.blackIntervals || []).length))}${detailRow('长静音区间', String((report.silenceIntervals || []).length))}${detailRow('冻结画面', String((report.freezeIntervals || []).length))}</div>${(report.warnings || []).length ? `<div class="task-detail-error">${escapeHtml(report.warnings.join('\n'))}</div>` : '<p>未发现明显黑屏、长静音或画面冻结。</p>'}`;
    });

    currentDetailTaskId = task.id;
    detailLayer.hidden = false;
    if (shouldPreserveScroll) {
      detailContent.scrollTop = previousContentScrollTop;
      const logs = detailContent.querySelector('.task-detail-logs');
      if (logs) logs.scrollTop = previousLogsScrollTop;
    } else {
      detailContent.scrollTop = 0;
    }
    document.body.style.overflow = 'hidden';
    if (shouldMoveFocus) detailLayer.querySelector('.task-detail-close')?.focus();
  }

  async function cancelTask(taskId) {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '取消失败');
    window.StreamDockUI?.showToast?.('已取消任务');
  }

  async function deleteTaskRecord(taskId) {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '删除失败');
    window.StreamDockUI?.showToast?.('任务记录已删除');
  }

  function render(container, emptyEl, tasks) {
    if (!container || !emptyEl) return;
    container.innerHTML = '';
    emptyEl.hidden = tasks.length > 0;
    tasks.forEach((task) => {
      const result = task.result || {};
      const coverUrl = result.coverUrl || '';
      const stage = stageLabel(task);
      const errorInfo = errorPresentation(task.error);
      const card = document.createElement('article');
      card.className = `task-card task-card-${task.status || 'pending'}`;
      card.tabIndex = 0;
      card.dataset.taskId = task.id || '';
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `查看任务详情：${taskDisplayTitle(task)}`);
      card.innerHTML = `
        <div class="thumb task-thumb">${coverUrl ? `<img class="task-thumb-img" src="${escapeHtml(mediaCoverSrc(coverUrl))}" alt="视频封面" loading="lazy">` : ''}</div>
        <div class="task-body">
          <div class="task-title">${escapeHtml(taskDisplayTitle(task))}</div>
          <div class="task-meta">${escapeHtml(taskMeta(task) || '等待任务信息')}</div>
          <div class="task-progress-meta">${escapeHtml(compactActivity(task) || stage)}${elapsedLabel(task) ? ` · 耗时 ${escapeHtml(elapsedLabel(task))}` : ''}</div>
          ${task.status === 'running' ? `<div class="task-progress-track ${Number.isFinite(task.progress) ? '' : 'indeterminate'}"><i style="${Number.isFinite(task.progress) ? `width:${Math.max(2, Math.min(100, task.progress))}%` : ''}"></i></div>` : ''}
          ${result.outputPath ? `<code class="task-path">${escapeHtml(result.outputPath)}</code>` : ''}
          ${validationSummary(task) ? `<div class="task-validation-summary">${escapeHtml(validationSummary(task))}</div>` : ''}
          ${task.error ? `<div class="task-error">${escapeHtml(errorInfo.title)} · ${escapeHtml(errorInfo.hint)}</div>` : ''}
        </div>
        <div class="task-actions">
          <span class="task-status status-${escapeHtml(task.status || 'pending')}">${escapeHtml(stage)}</span>
          <button type="button" data-task-detail>查看详情</button>
          ${task.kind === 'media' && result.outputPath ? '<button type="button" data-open-directory-card>打开目录</button>' : ''}
          ${task.kind === 'media' && ['failed', 'cancelled', 'skipped'].includes(task.status) ? '<button type="button" data-retry-card>重新执行</button>' : ''}
          ${task.kind === 'media' && ['pending', 'running'].includes(task.status) ? '<button type="button" data-cancel-task>取消</button>' : ''}
          ${['completed', 'failed', 'skipped', 'cancelled'].includes(task.status) && !subtitleJobActive(task) ? '<button type="button" data-delete-task-record>删除记录</button>' : ''}
        </div>
      `;
      const open = () => showDetail(task);
      card.addEventListener('click', open);
      card.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          open();
        }
      });
      card.querySelector('[data-task-detail]')?.addEventListener('click', (event) => {
        event.stopPropagation();
        open();
      });
      bindAction(card.querySelector('[data-cancel-task]'), async () => {
        await cancelTask(task.id);
        await refresh();
      });
      bindAction(card.querySelector('[data-open-directory-card]'), async () => {
        await postPath('/api/open-output-path', result.outputPath);
      });
      bindAction(card.querySelector('[data-delete-task-record]'), async () => {
        await deleteTaskRecord(task.id);
        await refresh();
      });
      bindAction(card.querySelector('[data-retry-card]'), async () => {
        const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || '重新执行失败');
        window.StreamDockUI?.showToast?.('已重新加入任务队列');
        await refresh();
      });
      container.appendChild(card);
    });
  }

  async function fetchTasks(kind) {
    const response = await fetch(`/api/tasks${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`);
    const data = await response.json();
    if (!response.ok || !data.success) return [];
    return data.tasks || [];
  }

  async function refresh() {
    try {
      let detailTask = null;
      if (convertList) {
        latestConvertTasks = await fetchTasks('convert');
        renderConvertTasks();
        detailTask = latestConvertTasks.find((task) => task.id === currentDetailTaskId) || detailTask;
      }
      if (downloadingTasks || completedTasks) {
        latestMediaTasks = await fetchTasks('media');
        render(downloadingTasks, downloadingEmpty, latestMediaTasks.filter((task) => ['pending', 'running'].includes(task.status)));
        const finished = latestMediaTasks.filter((task) => ['completed', 'failed', 'skipped', 'cancelled'].includes(task.status));
        renderMediaFinished();
        detailTask = latestMediaTasks.find((task) => task.id === currentDetailTaskId) || detailTask;
        const activeTracked = latestMediaTasks.find((task) => ['pending', 'running'].includes(task.status) && window.StreamDockResult?.isTracked?.(task.id));
        if (activeTracked) {
          window.StreamDockResult?.rememberTask?.(activeTracked);
          window.StreamDockResult?.setStatus?.('running', compactActivity(activeTracked));
          window.StreamDockResult?.setProgress?.(Number.isFinite(activeTracked.progress) ? activeTracked.progress : undefined, true);
        }
        const latest = finished[0];
        const latestPresentationKey = latest
          ? `${latest.id}:${latest.status}:${String(latest.result?.subtitleJob?.status || '')}`
          : '';
        if (latest && window.StreamDockResult?.isTracked?.(latest.id) && latestPresentationKey !== lastPresentedMediaTaskKey && ['completed', 'failed'].includes(latest.status)) {
          lastPresentedMediaTaskKey = latestPresentationKey;
          window.StreamDockResult?.rememberTask?.(latest);
          const latestResult = latest.result || {};
          if (latest.status === 'completed') {
            const subtitleActive = subtitleJobActive(latest);
            window.StreamDockResult?.setStatus?.('success', subtitleActive
              ? `${latestResult.platform || '未知平台'} · 视频已保存，字幕正在后台识别`
              : `${latestResult.platform || '未知平台'} · 已保存到本地`);
            window.StreamDockResult?.showResult?.({
              path: latestResult.outputPath || '',
              platform: latestResult.platform || '',
              validation: latestResult.validation || null,
              coverUrl: latestResult.coverUrl || '',
              title: latestResult.title || '',
              subtitleCount: latestResult.subtitleCount || 0,
              subtitleJob: latestResult.subtitleJob || null,
            });
          } else {
            window.StreamDockResult?.setStatus?.('error', latest.error || '解析失败');
            window.StreamDockResult?.showResult?.({ path: latestResult.outputPath || '', platform: latestResult.platform || '', error: latest.error || '解析失败' });
          }
          if (!subtitleJobActive(latest)) window.StreamDockResult?.completeTask?.(latest.id);
        }
      }
      if (currentDetailTaskId && detailTask) showDetail(detailTask);
    } catch (_error) {
      // 本地服务临时不可用时保持现有 UI，不打断用户输入。
    }
  }

  function start() {
    refresh();
    window.clearInterval(timer);
    timer = window.setInterval(refresh, POLL_MS);
  }

  async function openConvertTasks(taskId) {
    window.StreamDockConvertTabs?.activate?.('tasks');
    if (window.location.pathname === '/convert') {
      window.history.replaceState(null, '', '#tasks');
    }
    if (convertTaskStatusFilter) convertTaskStatusFilter.value = 'all';
    if (convertTaskSearch && taskId) convertTaskSearch.value = '';
    await refresh();
    const target = taskId ? document.querySelector(`[data-task-id="${cssEscape(taskId)}"]`) : convertList;
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (target && taskId) {
      target.classList.add('task-card-highlight');
      window.setTimeout(() => target.classList.remove('task-card-highlight'), 1800);
    }
  }

  detailLayer?.querySelectorAll('[data-task-detail-close]').forEach((button) => button.addEventListener('click', closeDetail));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && detailLayer && !detailLayer.hidden) closeDetail();
  });

  async function taskAction(endpoint, method, successMessage) {
    const response = await fetch(endpoint, { method });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '操作失败');
    window.StreamDockUI?.showToast?.(successMessage);
    await refresh();
  }

  bindAction(document.getElementById('pauseMediaTasks'), () => taskAction('/api/tasks/media/pause', 'POST', '等待队列已暂停'));
  bindAction(document.getElementById('resumeMediaTasks'), () => taskAction('/api/tasks/media/resume', 'POST', '等待队列已继续'));
  bindAction(document.getElementById('clearMediaFinished'), () => taskAction('/api/task-actions/clear-finished?kind=media', 'DELETE', '解析历史记录已清除'));
  bindAction(document.getElementById('clearConvertFinished'), () => taskAction('/api/task-actions/clear-finished?kind=convert', 'DELETE', '转换历史记录已清除'));
  [mediaTaskSearch, mediaTaskStatusFilter, convertTaskSearch, convertTaskStatusFilter].forEach((control) => {
    const rerenderFilteredTasks = () => {
      if (control === mediaTaskSearch || control === mediaTaskStatusFilter) {
        renderMediaFinished();
      } else {
        renderConvertTasks();
      }
    };
    control?.addEventListener('input', rerenderFilteredTasks);
    control?.addEventListener('change', rerenderFilteredTasks);
    control?.addEventListener('search', rerenderFilteredTasks);
  });

  window.StreamDockTaskCenter = { refreshNow: refresh, start, openConvertTasks };
  if (convertList || downloadingTasks || completedTasks) start();
})();
