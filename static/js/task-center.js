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
  const convertTaskSearch = document.getElementById('convertTaskSearch');
  const convertTaskStatusFilter = document.getElementById('convertTaskStatusFilter');
  const POLL_MS = 3500;
  let timer = null;
  let lastPresentedMediaTaskId = '';
  let currentDetailTaskId = '';
  let latestMediaTasks = [];
  let latestConvertTasks = [];

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
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

  function stageLabel(task) {
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

  function validationSummary(task) {
    const validation = task.result?.validation || {};
    if (!validation.valid) return '';
    const resolution = validation.width && validation.height ? `${validation.width}×${validation.height}` : '';
    const codecs = [validation.videoCodec, validation.audioCodec].filter(Boolean).join('/');
    return [resolution, codecs, validation.sizeLabel, '校验通过'].filter(Boolean).join(' · ');
  }

  function compactActivity(task) {
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
      const haystack = [task.title, task.status, task.payload?.link, task.payload?.filename,
        task.payload?.source, task.payload?.target, task.result?.platform, task.result?.outputPath]
        .filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    });
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
    if (!error) return { title: '任务未完成', hint: '请打开运行记录查看详细信息。' };
    if (lowered.includes('timeout') || error.includes('超时')) {
      return { title: '处理超时', hint: '平台响应较慢或文件较大，可以稍后重新执行。' };
    }
    if (error.includes('登录') || lowered.includes('cookie') || error.includes('权限')) {
      return { title: '当前内容需要登录或权限', hint: '确认浏览器登录状态后重新识别资源。' };
    }
    if (error.includes('不支持') || lowered.includes('unsupported')) {
      return { title: '暂不支持当前内容', hint: '请确认复制的是受支持平台的视频分享链接或转换格式。' };
    }
    if (error.includes('磁盘') || lowered.includes('no space')) {
      return { title: '磁盘空间不足', hint: '清理空间或更换输出目录后再次执行。' };
    }
    if (error.includes('格式') || error.includes('内容与')) {
      return { title: '文件格式校验失败', hint: '文件扩展名与真实内容可能不一致。' };
    }
    if (error.includes('取消')) {
      return { title: '任务已取消', hint: '任务记录已保留，可以重新提交。' };
    }
    if (error.includes('网络') || lowered.includes('connection') || lowered.includes('http')) {
      return { title: '网络连接失败', hint: '检查网络后重新执行；临时资源链接也可能已经失效。' };
    }
    return { title: '处理失败', hint: '可以复制错误信息用于排查，或稍后重新执行。' };
  }

  function detailRow(label, value, useCode) {
    if (!value) return '';
    const tag = useCode ? 'code' : 'strong';
    return `<div class="task-detail-row"><span>${escapeHtml(label)}</span><${tag}>${escapeHtml(value)}</${tag}></div>`;
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
    const payload = task.payload || {};
    const result = task.result || {};
    const outputPath = result.outputPath || '';
    const stage = stageLabel(task);
    const latestLog = compactActivity(task) || stage;
    const errorInfo = errorPresentation(task.error);

    detailTitle.textContent = task.title || '本地任务';
    detailContent.innerHTML = `
      <div class="task-detail-stage is-${escapeHtml(task.status || 'pending')}">
        <i class="task-detail-stage-mark" aria-hidden="true"></i>
        <div><strong>${escapeHtml(stage)}</strong><span>${escapeHtml(latestLog)}${elapsedLabel(task) ? ` · 已耗时 ${escapeHtml(elapsedLabel(task))}` : ''}</span></div>
      </div>
      ${task.error ? `<section class="task-detail-section"><div class="task-detail-error"><strong>${escapeHtml(errorInfo.title)}</strong>${escapeHtml(errorInfo.hint)}<br>${escapeHtml(task.error)}</div></section>` : ''}
      <section class="task-detail-section">
        <h3>基本信息</h3>
        <div class="task-detail-grid">
          ${detailRow('任务类型', task.kind === 'media' ? '视频解析' : task.kind === 'pdf' ? 'PDF 智能解析' : '文件转换')}
          ${detailRow('输入内容', sourceLabel(task), true)}
          ${detailRow('输出格式', payload.outputType ? String(payload.outputType).toUpperCase() : (payload.target ? String(payload.target).toUpperCase() : ''))}
          ${detailRow('平台', result.platform || payload.platform || '')}
          ${detailRow('清晰度', payload.videoQuality || '')}
          ${detailRow('创建时间', dateLabel(task.createdAt))}
          ${detailRow('更新时间', dateLabel(task.updatedAt))}
          ${detailRow('任务编号', task.id, true)}
        </div>
      </section>
      ${outputPath || payload.outputPath ? `<section class="task-detail-section"><h3>输出</h3><div class="task-detail-grid">${detailRow(outputPath ? '输出文件' : '保存目录', outputPath || payload.outputPath, true)}</div></section>` : ''}
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
    `;

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
    bindAction(detailFooter.querySelector('[data-deep-quality]'), async () => {
      const form = new FormData(); form.append('path', outputPath);
      const response = await fetch('/api/media/quality/deep', { method: 'POST', body: form }); const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '深度检测失败');
      const report = data.report; const target = detailContent.querySelector('#deepQualityResult');
      if (target) target.innerHTML = `<div class="task-detail-grid">${detailRow('深度评分', report.deepQualityScore)}${detailRow('黑屏区间', String((report.blackIntervals || []).length))}${detailRow('长静音区间', String((report.silenceIntervals || []).length))}${detailRow('冻结画面', String((report.freezeIntervals || []).length))}</div>${(report.warnings || []).length ? `<div class="task-detail-error">${escapeHtml(report.warnings.join('\n'))}</div>` : '<p>未发现明显黑屏、长静音或画面冻结。</p>'}`;
    });

    currentDetailTaskId = task.id;
    detailLayer.hidden = false;
    document.body.style.overflow = 'hidden';
    if (shouldMoveFocus) detailLayer.querySelector('.task-detail-close')?.focus();
  }

  async function cancelTask(taskId) {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '取消失败');
    window.StreamDockUI?.showToast?.('已取消任务');
  }

  function render(container, emptyEl, tasks) {
    if (!container || !emptyEl) return;
    container.innerHTML = '';
    emptyEl.hidden = tasks.length > 0;
    tasks.forEach((task) => {
      const result = task.result || {};
      const stage = stageLabel(task);
      const errorInfo = errorPresentation(task.error);
      const card = document.createElement('article');
      card.className = `task-card task-card-${task.status || 'pending'}`;
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `查看任务详情：${task.title || '本地任务'}`);
      card.innerHTML = `
        <div class="thumb task-thumb"></div>
        <div class="task-body">
          <div class="task-title">${escapeHtml(task.title || '本地任务')}</div>
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
          ${task.kind === 'media' && ['failed', 'cancelled', 'skipped'].includes(task.status) ? '<button type="button" data-retry-card>重新执行</button>' : ''}
          ${task.kind === 'media' && ['pending', 'running'].includes(task.status) ? '<button type="button" data-cancel-task>取消</button>' : ''}
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
        render(convertList, convertEmpty, filterTasks(latestConvertTasks, convertTaskSearch, convertTaskStatusFilter));
        detailTask = latestConvertTasks.find((task) => task.id === currentDetailTaskId) || detailTask;
      }
      if (downloadingTasks || completedTasks) {
        latestMediaTasks = await fetchTasks('media');
        render(downloadingTasks, downloadingEmpty, latestMediaTasks.filter((task) => ['pending', 'running'].includes(task.status)));
        const finished = latestMediaTasks.filter((task) => ['completed', 'failed', 'skipped', 'cancelled'].includes(task.status));
        render(completedTasks, completedEmpty, filterTasks(finished, mediaTaskSearch, mediaTaskStatusFilter));
        detailTask = latestMediaTasks.find((task) => task.id === currentDetailTaskId) || detailTask;
        const latest = finished[0];
        if (latest && latest.id !== lastPresentedMediaTaskId && ['completed', 'failed'].includes(latest.status)) {
          lastPresentedMediaTaskId = latest.id;
          const latestResult = latest.result || {};
          if (latest.status === 'completed') {
            window.StreamDockResult?.setStatus?.('success', `${latestResult.platform || '未知平台'} · 已保存到本地`);
            window.StreamDockResult?.showResult?.({ path: latestResult.outputPath || '', platform: latestResult.platform || '', validation: latestResult.validation || null });
          } else {
            window.StreamDockResult?.setStatus?.('error', latest.error || '解析失败');
            window.StreamDockResult?.showResult?.({ path: latestResult.outputPath || '', platform: latestResult.platform || '', error: latest.error || '解析失败' });
          }
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
    control?.addEventListener('input', () => {
      if (control === mediaTaskSearch || control === mediaTaskStatusFilter) {
        const finished = latestMediaTasks.filter((task) => ['completed', 'failed', 'skipped', 'cancelled'].includes(task.status));
        render(completedTasks, completedEmpty, filterTasks(finished, mediaTaskSearch, mediaTaskStatusFilter));
      } else {
        render(convertList, convertEmpty, filterTasks(latestConvertTasks, convertTaskSearch, convertTaskStatusFilter));
      }
    });
  });

  window.StreamDockTaskCenter = { refreshNow: refresh, start };
  if (convertList || downloadingTasks || completedTasks) start();
})();
