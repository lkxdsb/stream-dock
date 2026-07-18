(function () {
  const statusBadge = document.getElementById('statusBadge');
  const statusText = document.getElementById('statusText');
  const resultBox = document.getElementById('resultBox');
  const resultPlatform = document.getElementById('resultPlatform');
  const resultPath = document.getElementById('resultPath');
  const resultError = document.getElementById('resultError');
  const resultErrorRow = document.getElementById('resultErrorRow');
  const resultQuality = document.getElementById('resultQuality');
  const resultQualityRow = document.getElementById('resultQualityRow');
  const resultWarning = document.getElementById('resultWarning');
  const resultWarningRow = document.getElementById('resultWarningRow');
  const recentCard = document.getElementById('recentCard');
  const recentTitle = document.getElementById('recentTitle');
  const recentThumb = recentCard?.querySelector('.thumb');
  const recentProgress = document.getElementById('recentProgress');
  const recentProgressBar = document.getElementById('recentProgressBar');
  const recentCancelButton = document.getElementById('recentCancelButton');
  const recentOpenDirectoryButton = document.getElementById('recentOpenDirectoryButton');
  let currentRecentTaskId = '';
  let currentRecentStatus = '';
  let currentOutputPath = '';
  let currentSubtitleActive = false;
  let restoredTaskIds = [];
  try { restoredTaskIds = JSON.parse(sessionStorage.getItem('streamdock:media-tasks') || '[]'); } catch (_error) { restoredTaskIds = []; }
  const trackedTaskIds = new Set(Array.isArray(restoredTaskIds) ? restoredTaskIds : []);

  function mediaCoverSrc(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (raw.startsWith('data:') || raw.startsWith('blob:') || raw.startsWith('/')) return raw;
    const normalized = raw.startsWith('//') ? `https:${raw}` : raw;
    return /^https?:\/\//i.test(normalized) ? `/api/media/cover-proxy?url=${encodeURIComponent(normalized)}` : normalized;
  }

  function saveTrackedTasks() {
    sessionStorage.setItem('streamdock:media-tasks', JSON.stringify(Array.from(trackedTaskIds).slice(-30)));
  }

  function updateRecentCancelButton() {
    if (!recentCancelButton) return;
    const hasTask = Boolean(currentRecentTaskId);
    recentCancelButton.disabled = !hasTask;
    recentCancelButton.hidden = !hasTask;
    if (hasTask && currentSubtitleActive) {
      recentCancelButton.disabled = true;
      recentCancelButton.textContent = '字幕处理中';
      recentCancelButton.setAttribute('aria-label', '字幕正在后台处理，视频已经可以打开');
      return;
    }
    const running = ['pending', 'running'].includes(currentRecentStatus);
    recentCancelButton.textContent = running ? '取消解析' : '删除记录';
    recentCancelButton.setAttribute('aria-label', running ? '取消上次解析任务' : '删除上次解析记录');
  }

  function rememberTask(taskOrId, status = '') {
    const task = typeof taskOrId === 'object' && taskOrId ? taskOrId : null;
    const id = task?.id || taskOrId;
    if (!id) return;
    if (currentRecentTaskId && currentRecentTaskId !== String(id)) currentSubtitleActive = false;
    currentRecentTaskId = String(id);
    currentRecentStatus = String(task?.status || status || currentRecentStatus || 'pending');
    updateRecentCancelButton();
  }

  function trackTasks(ids) {
    const values = (ids || []).filter(Boolean).map(String);
    values.forEach((id) => trackedTaskIds.add(id));
    if (values.length) rememberTask(values[values.length - 1], 'pending');
    saveTrackedTasks();
  }

  function isTracked(id) { return trackedTaskIds.has(String(id || '')); }

  function completeTask(id) {
    trackedTaskIds.delete(String(id || ''));
    saveTrackedTasks();
  }

  function setProgress(value, active = true) {
    if (!recentProgress || !recentProgressBar) return;
    recentProgress.hidden = !active;
    const numeric = Number(value);
    recentProgress.classList.toggle('indeterminate', active && !Number.isFinite(numeric));
    recentProgressBar.style.width = Number.isFinite(numeric) ? `${Math.max(2, Math.min(100, numeric))}%` : '';
  }

  function setStatus(kind, text) {
    if (statusBadge) {
      statusBadge.textContent = kind === 'running'
        ? '⌛ 处理中'
        : kind === 'success'
          ? '✓ 完成'
          : kind === 'error'
            ? '⚠ 失败'
            : '• 待执行';
      statusBadge.style.color = kind === 'running'
        ? '#9a6b28'
        : kind === 'success'
          ? '#4b9c5e'
          : kind === 'error'
            ? '#c45858'
            : '';
    }

    if (statusText) {
      statusText.textContent = text;
    }

    if (!recentTitle) {
      return;
    }

    currentRecentStatus = kind === 'running' ? 'running' : kind === 'success' ? 'completed' : kind === 'error' ? 'failed' : currentRecentStatus;
    updateRecentCancelButton();

    if (kind === 'running') {
      recentTitle.textContent = '正在解析链接';
      recentCard?.classList.add('processing');
      setProgress(undefined, true);
    } else if (kind === 'success') {
      recentTitle.textContent = '解析完成的视频';
      recentCard?.classList.remove('processing');
      setProgress(100, true);
      window.setTimeout(() => setProgress(100, false), 900);
    } else if (kind === 'error') {
      recentTitle.textContent = '解析失败';
      recentCard?.classList.remove('processing');
      setProgress(undefined, false);
    } else {
      recentTitle.textContent = '等待新的解析任务';
      recentCard?.classList.remove('processing');
      setProgress(undefined, false);
    }
  }

  function setRecentThumb(coverUrl) {
    if (!recentThumb) return;
    if (coverUrl) {
      recentThumb.innerHTML = `<img class="task-thumb-img" src="${mediaCoverSrc(coverUrl).replace(/"/g, '&quot;')}" alt="视频封面" loading="lazy">`;
      recentThumb.classList.add('has-image');
    } else {
      recentThumb.innerHTML = '';
      recentThumb.classList.remove('has-image');
    }
  }

  function showResult({ path = '', platform = '', error = '', validation = null, coverUrl = '', title = '', subtitleCount = null, subtitleJob = null } = {}) {
    if (!resultBox || !resultPath || !resultPlatform || !resultError || !resultErrorRow) {
      return;
    }

    resultPlatform.textContent = platform || '-';
    resultPath.textContent = path || '-';
    currentOutputPath = String(path || '');
    currentSubtitleActive = ['pending', 'running'].includes(String(subtitleJob?.status || ''));
    updateRecentCancelButton();
    if (recentOpenDirectoryButton) {
      recentOpenDirectoryButton.hidden = !currentOutputPath;
      recentOpenDirectoryButton.disabled = !currentOutputPath;
    }
    if (title && recentTitle) recentTitle.textContent = title;
    setRecentThumb(coverUrl);

    const qualityParts = [];
    if (validation) {
      if (validation.width && validation.height) qualityParts.push(`${validation.width}×${validation.height}`);
      if (validation.videoCodec) qualityParts.push(String(validation.videoCodec).toUpperCase());
      if (validation.audioCodec) qualityParts.push(String(validation.audioCodec).toUpperCase());
      if (validation.bitrate) qualityParts.push(`${Math.round(Number(validation.bitrate) / 1000)} kbps`);
      if (validation.qualityScore !== undefined) qualityParts.push(`评分 ${validation.qualityScore}`);
    }
    if (subtitleCount !== null && Number(subtitleCount) > 0) qualityParts.push(`字幕 ${Number(subtitleCount)} 条`);
    if (['pending', 'running'].includes(String(subtitleJob?.status || ''))) qualityParts.push('字幕后台识别中');
    if (resultQuality && resultQualityRow) {
      resultQuality.textContent = qualityParts.join(' · ') || '-';
      resultQualityRow.hidden = qualityParts.length === 0;
    }
    const warnings = Array.isArray(validation?.warnings) ? validation.warnings : [];
    if (resultWarning && resultWarningRow) {
      resultWarning.textContent = warnings.join('；') || '-';
      resultWarningRow.hidden = warnings.length === 0;
    }

    if (error) {
      resultError.textContent = error;
      resultErrorRow.hidden = false;
    } else {
      resultError.textContent = '-';
      resultErrorRow.hidden = true;
    }

    resultBox.hidden = !(path || platform || error);
  }

  function resetRecentCard(message = '已取消上次解析。') {
    currentRecentTaskId = '';
    currentRecentStatus = '';
    currentSubtitleActive = false;
    trackedTaskIds.clear();
    saveTrackedTasks();
    setRecentThumb('');
    setProgress(undefined, false);
    showResult();
    setStatus('idle', message);
    if (resultErrorRow) resultErrorRow.hidden = true;
    updateRecentCancelButton();
  }

  async function cancelRecentTask() {
    if (!currentRecentTaskId || !recentCancelButton) return;
    const taskId = currentRecentTaskId;
    const running = ['pending', 'running'].includes(currentRecentStatus);
    recentCancelButton.disabled = true;
    recentCancelButton.textContent = running ? '取消中...' : '删除中...';
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) throw new Error(data.error || '操作失败');
      completeTask(taskId);
      resetRecentCard(running ? '已取消上次解析。' : '已删除上次解析记录。');
      window.StreamDockTaskCenter?.refreshNow?.();
      window.StreamDockUI?.showToast?.(running ? '已取消上次解析' : '已删除上次解析记录');
    } catch (error) {
      recentCancelButton.disabled = false;
      updateRecentCancelButton();
      window.StreamDockUI?.showToast?.(error.message || '操作失败');
    }
  }

  recentCancelButton?.addEventListener('click', cancelRecentTask);
  recentOpenDirectoryButton?.addEventListener('click', async () => {
    if (!currentOutputPath) return;
    recentOpenDirectoryButton.disabled = true;
    try {
      const form = new FormData();
      form.append('path', currentOutputPath);
      const response = await fetch('/api/open-output-path', { method: 'POST', body: form });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) throw new Error(data.error || '打开目录失败');
    } catch (error) {
      window.StreamDockUI?.showToast?.(error.message || '打开目录失败');
    } finally {
      recentOpenDirectoryButton.disabled = !currentOutputPath;
    }
  });
  updateRecentCancelButton();

  window.StreamDockResult = {
    setStatus,
    showResult,
    setProgress,
    trackTasks,
    isTracked,
    completeTask,
    rememberTask,
    resetRecentCard,
  };
})();
