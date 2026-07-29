(function () {
  const fileInput = document.getElementById('subtitleFile');
  const videoInput = document.getElementById('subtitleVideo');
  const player = document.getElementById('subtitlePlayer');
  const stage = document.getElementById('subtitleStage');
  const cuesRoot = document.getElementById('subtitleCues');
  const empty = document.getElementById('subtitleEmpty');
  const nameNode = document.getElementById('subtitleName');
  const countNode = document.getElementById('subtitleCount');
  const durationNode = document.getElementById('subtitleDuration');
  const nowNode = document.getElementById('subtitleNow');
  const documentStatus = document.getElementById('subtitleDocumentStatus');
  const stateNode = document.getElementById('subtitleState');
  const readyDot = document.getElementById('subtitleReadyDot');
  const formatLabel = document.getElementById('subtitleFormatLabel');
  const selectionSummary = document.getElementById('subtitleSelectionSummary');
  const mediaName = document.getElementById('subtitleMediaName');
  const currentTimeNode = document.getElementById('subtitleCurrentTime');
  const mediaDurationNode = document.getElementById('subtitleMediaDuration');
  let filename = 'subtitle.srt';
  let cues = [];
  let importSequence = 0;
  let exportRunning = false;
  let mediaObjectUrl = '';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[character]));
  }

  function uid() { return Math.random().toString(36).slice(2, 12); }
  function toast(message) { window.StreamDockUI?.showToast?.(message); }

  function shortClock(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = Math.floor(value % 60);
    return hours ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}` : `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function preciseClock(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(value / 60);
    const secs = Math.floor(value % 60);
    const millis = Math.floor((value % 1) * 1000);
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
  }

  function setDocumentState(label, dirty = false) {
    documentStatus.textContent = label;
    stateNode.textContent = dirty ? '有未导出修改' : label;
    readyDot.classList.toggle('ready', cues.length > 0);
  }

  function syncFromDom() {
    cues = Array.from(cuesRoot.querySelectorAll('.subtitle-cue')).map((row) => ({
      id: row.dataset.id,
      start: Number(row.querySelector('[data-start]').value),
      end: Number(row.querySelector('[data-end]').value),
      text: row.querySelector('[data-text]').value,
    }));
  }

  function validateClientCues() {
    if (!cues.length || cues.length > 5000) throw new Error('字幕片段数量应为 1～5000 条');
    for (const cue of cues) {
      if (!Number.isFinite(cue.start) || !Number.isFinite(cue.end) || cue.start < 0 || cue.end <= cue.start || cue.end > 604800) {
        throw new Error('字幕时间必须位于 0～7 天范围内，且结束时间晚于开始时间');
      }
      if (!String(cue.text || '').trim() || String(cue.text).length > 4000) throw new Error('每条字幕需包含 1～4000 个字符');
    }
  }

  function updateDocumentMeta() {
    const timelineEnd = Math.max(0, ...cues.map((cue) => Number(cue.end) || 0));
    countNode.textContent = String(cues.length);
    durationNode.textContent = shortClock(timelineEnd);
    selectionSummary.textContent = cues.length ? `${cues.length} 个片段 · ${shortClock(timelineEnd)} 时间轴` : '尚未导入字幕';
    readyDot.classList.toggle('ready', cues.length > 0);
  }

  function bindCueRow(row, cue) {
    row.querySelector('[data-delete]').addEventListener('click', (event) => {
      event.stopPropagation();
      syncFromDom();
      cues = cues.filter((item) => item.id !== row.dataset.id);
      render();
      setDocumentState('已修改', true);
    });
    row.querySelectorAll('input,textarea').forEach((control) => control.addEventListener('input', () => {
      syncFromDom();
      updateDocumentMeta();
      setDocumentState('编辑中', true);
    }));
    row.addEventListener('click', (event) => {
      if (event.target.matches('input,textarea,button')) return;
      player.currentTime = Number(cue.start) || 0;
      if (stage.classList.contains('has-media')) player.play().catch(() => {});
    });
  }

  function render() {
    empty.hidden = cues.length > 0;
    cuesRoot.innerHTML = cues.map((cue, index) => `<article class="subtitle-cue" data-id="${escapeHtml(cue.id || uid())}" style="animation-delay:${Math.min(index, 8) * 18}ms">
      <b>${String(index + 1).padStart(2, '0')}</b>
      <input data-start type="number" min="0" step="0.001" value="${Number(cue.start).toFixed(3)}" aria-label="开始时间" />
      <input data-end type="number" min="0" step="0.001" value="${Number(cue.end).toFixed(3)}" aria-label="结束时间" />
      <textarea data-text aria-label="字幕文本">${escapeHtml(cue.text)}</textarea>
      <button data-delete type="button" aria-label="删除字幕">×</button>
    </article>`).join('');
    updateDocumentMeta();
    cuesRoot.querySelectorAll('.subtitle-cue').forEach((row, index) => bindCueRow(row, cues[index]));
  }

  function applyDocument(document, message) {
    filename = document.filename;
    cues = document.cues;
    nameNode.textContent = filename;
    formatLabel.textContent = `${String(document.format || filename.split('.').pop() || 'subtitle').toUpperCase()} 字幕文件`;
    render();
    setDocumentState('已载入');
    toast(message);
  }

  async function importFile(file, sequence) {
    const body = new FormData();
    body.append('file', file);
    setDocumentState('正在导入');
    const response = await fetch('/api/subtitles/import', { method: 'POST', body });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '字幕导入失败');
    if (sequence !== importSequence) return;
    applyDocument(data.document, `已导入 ${data.document.cueCount} 条字幕`);
  }

  function handleSubtitleFile(file) {
    if (!file) return;
    if (!/\.(srt|vtt|txt)$/i.test(file.name)) { toast('请选择 SRT、VTT 或 TXT 字幕文件'); return; }
    if (file.size > 5 * 1024 * 1024) { toast('字幕文件不能超过 5MB'); return; }
    const sequence = ++importSequence;
    importFile(file, sequence).catch((error) => {
      if (sequence === importSequence) {
        setDocumentState('导入失败');
        toast(error.message);
      }
    });
  }

  async function importTaskAsset() {
    const query = new URLSearchParams(window.location.search);
    const taskId = query.get('taskId');
    const path = query.get('path');
    if (!taskId || !path) return;
    const sequence = ++importSequence;
    setDocumentState('正在读取任务字幕');
    const asset = await fetch(`/api/media/tasks/${encodeURIComponent(taskId)}/asset?path=${encodeURIComponent(path)}`);
    if (!asset.ok) throw new Error('无法读取任务中的字幕文件');
    const text = await asset.text();
    const assetName = path.split(/[\\/]/).pop() || 'subtitle.srt';
    const parsed = await fetch('/api/subtitles/parse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: assetName, text }),
    });
    const data = await parsed.json();
    if (!parsed.ok || !data.success) throw new Error(data.error || '字幕解析失败');
    if (sequence !== importSequence) return;
    applyDocument(data.document, `已载入 ${data.document.cueCount} 条任务字幕`);
  }

  function clearWorkspace() {
    cues = [];
    filename = 'subtitle.srt';
    nameNode.textContent = '未导入字幕';
    formatLabel.textContent = 'SRT / VTT / TXT';
    fileInput.value = '';
    render();
    setDocumentState('新建工作区');
    toast('工作区已清空');
  }

  fileInput?.addEventListener('change', () => handleSubtitleFile(fileInput.files?.[0]));
  videoInput?.addEventListener('change', () => {
    const file = videoInput.files?.[0];
    if (!file) return;
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    mediaObjectUrl = URL.createObjectURL(file);
    player.src = mediaObjectUrl;
    stage.classList.add('has-media');
    mediaName.textContent = file.name;
    player.load();
  });

  document.getElementById('subtitleAdd')?.addEventListener('click', () => {
    syncFromDom();
    const start = Number(player.currentTime || cues.at(-1)?.end || 0);
    cues.push({ id: uid(), start, end: start + 2.8, text: '新字幕' });
    render();
    setDocumentState('编辑中', true);
    cuesRoot.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    cuesRoot.lastElementChild?.querySelector('textarea')?.focus();
  });

  document.getElementById('subtitleSort')?.addEventListener('click', () => {
    syncFromDom();
    cues.sort((left, right) => left.start - right.start || left.end - right.end);
    render();
    setDocumentState('已按时间排序', true);
  });

  document.getElementById('subtitleClear')?.addEventListener('click', clearWorkspace);

  document.getElementById('subtitleExport')?.addEventListener('click', async () => {
    if (exportRunning) return;
    exportRunning = true;
    const button = document.getElementById('subtitleExport');
    button.disabled = true;
    try {
      syncFromDom();
      validateClientCues();
      const format = document.getElementById('subtitleExportFormat').value;
      const response = await fetch('/api/subtitles/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename, format, cues }),
      });
      if (!response.ok) { const data = await response.json(); throw new Error(data.error || '导出失败'); }
      const blob = await response.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `${filename.replace(/\.[^.]+$/, '')}.${format}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      setDocumentState('已导出');
      toast('字幕已导出');
    } catch (error) {
      toast(error.message || '导出失败');
    } finally {
      exportRunning = false;
      button.disabled = false;
    }
  });

  player?.addEventListener('loadedmetadata', () => { mediaDurationNode.textContent = preciseClock(player.duration); });
  player?.addEventListener('timeupdate', () => {
    const time = player.currentTime;
    currentTimeNode.textContent = preciseClock(time);
    let activeText = '';
    cuesRoot.querySelectorAll('.subtitle-cue').forEach((row, index) => {
      const cue = cues[index];
      const active = cue && time >= cue.start && time <= cue.end;
      row.classList.toggle('is-active', active);
      if (active) activeText = cue.text;
    });
    nowNode.textContent = activeText;
    nowNode.hidden = !activeText;
  });

  empty?.addEventListener('dragover', (event) => { event.preventDefault(); empty.classList.add('is-dragging'); });
  empty?.addEventListener('dragleave', () => empty.classList.remove('is-dragging'));
  empty?.addEventListener('drop', (event) => {
    event.preventDefault();
    empty.classList.remove('is-dragging');
    handleSubtitleFile(event.dataTransfer?.files?.[0]);
  });

  document.addEventListener('keydown', (event) => {
    const editing = event.target.matches('input,textarea,select');
    if (!editing && event.code === 'Space' && stage.classList.contains('has-media')) {
      event.preventDefault();
      if (player.paused) player.play().catch(() => {}); else player.pause();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      document.getElementById('subtitleExport').click();
    }
  });

  window.addEventListener('beforeunload', () => { if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl); });
  render();
  importTaskAsset().catch((error) => { setDocumentState('任务字幕载入失败'); toast(error.message); });
})();
