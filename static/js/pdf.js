(() => {
  const input = document.getElementById('pdfFileInput');
  if (!input) return;
  const pick = document.getElementById('pdfPickButton');
  const analyze = document.getElementById('pdfAnalyzeButton');
  const parse = document.getElementById('pdfParseButton');
  const cancel = document.getElementById('pdfCancelButton');
  const status = document.getElementById('pdfStatus');
  const analysisBox = document.getElementById('pdfAnalysis');
  const result = document.getElementById('pdfResult');
  const preview = document.getElementById('pdfPreview');
  const health = document.getElementById('pdfHealth');
  const title = document.getElementById('pdfFileTitle');
  const meta = document.getElementById('pdfFileMeta');
  const mode = document.getElementById('pdfMode');
  const outputPath = document.getElementById('pdfOutputPath');
  const tabButtons = Array.from(document.querySelectorAll('[data-pdf-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-pdf-panel]'));
  const taskList = document.getElementById('pdfTaskList');
  const taskEmpty = document.getElementById('pdfTaskEmpty');
  const taskSearch = document.getElementById('pdfTaskSearch');
  const taskFilter = document.getElementById('pdfTaskFilter');
  const resultTask = document.getElementById('pdfResultTask');
  let pdfTasks = [];
  let selectedFile = null;
  let activeTaskId = '';

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const setFile = (file) => {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) { status.textContent = '请选择 PDF 文件。'; return; }
    selectedFile = file; title.textContent = file.name; meta.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 等待文档特征分析`;
    analyze.disabled = false; parse.disabled = true; analysisBox.hidden = true; preview.hidden = true; status.textContent = '文件已就绪，请先分析文档。';
  };
  const waitForTask = async (taskId) => {
    while (activeTaskId === taskId) {
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
      const response = await fetch(`/api/tasks/${taskId}`); const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || '无法读取 PDF 任务');
      const task = body.task; status.textContent = `${task.stage || '处理中'}${task.progress == null ? '' : ` · ${Math.round(task.progress)}%`}`;
      if (['completed', 'failed', 'cancelled', 'skipped'].includes(task.status)) return task;
    }
    throw new Error('任务已取消');
  };
  const setTab = (name) => {
    tabButtons.forEach((button) => button.classList.toggle('active', button.dataset.pdfTab === name));
    panels.forEach((panel) => { const active = panel.dataset.pdfPanel === name; panel.hidden = !active; panel.classList.toggle('active', active); });
    if (name !== 'workbench') refreshPdfTasks();
  };
  const statusName = (value) => ({ pending: '等待中', running: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消' }[value] || value);
  const renderTaskList = () => {
    const query = String(taskSearch?.value || '').trim().toLowerCase(); const filter = taskFilter?.value || 'all';
    const rows = pdfTasks.filter((task) => (filter === 'all' || task.status === filter) && (!query || task.title.toLowerCase().includes(query)));
    taskList.innerHTML = rows.map((task) => `<article class="pdf-task-item" data-pdf-task-id="${escapeHtml(task.id)}"><div><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.stage || statusName(task.status))}${task.progress == null ? '' : ` · ${Math.round(task.progress)}%`} · ${escapeHtml(task.result?.quality?.level || '')}</span>${task.error ? `<span>${escapeHtml(task.error)}</span>` : ''}</div><div class="pdf-task-actions"><em>${escapeHtml(statusName(task.status))}</em>${task.status === 'completed' ? '<button type="button" data-view-pdf-result>查看结果</button><button type="button" data-open-pdf-output>打开目录</button>' : ''}${['pending','running'].includes(task.status) ? '<button type="button" data-cancel-pdf-task>取消</button>' : ''}</div></article>`).join('');
    taskEmpty.hidden = rows.length > 0;
    taskList.querySelectorAll('[data-view-pdf-result]').forEach((button) => button.addEventListener('click', () => { const id = button.closest('[data-pdf-task-id]').dataset.pdfTaskId; setTab('results'); resultTask.value = id; renderStructuredResult(id); }));
    taskList.querySelectorAll('[data-open-pdf-output]').forEach((button) => button.addEventListener('click', async () => { const task = pdfTasks.find((item) => item.id === button.closest('[data-pdf-task-id]').dataset.pdfTaskId); const form = new FormData(); form.append('path', task.result.outputPath); await fetch('/api/open-output-path', { method: 'POST', body: form }); }));
    taskList.querySelectorAll('[data-cancel-pdf-task]').forEach((button) => button.addEventListener('click', async () => { await fetch(`/api/tasks/${button.closest('[data-pdf-task-id]').dataset.pdfTaskId}`, { method: 'DELETE' }); await refreshPdfTasks(); }));
  };
  const refreshPdfTasks = async () => {
    const response = await fetch('/api/tasks?kind=pdf'); const body = await response.json(); pdfTasks = body.tasks || []; renderTaskList();
    const completed = pdfTasks.filter((task) => task.status === 'completed'); const selected = resultTask.value;
    resultTask.innerHTML = completed.map((task) => `<option value="${escapeHtml(task.id)}">${escapeHtml(task.title)}</option>`).join('') || '<option value="">暂无已完成任务</option>';
    if (completed.some((task) => task.id === selected)) resultTask.value = selected;
    if (resultTask.value) renderStructuredResult(resultTask.value);
  };
  const renderStructuredResult = (id) => {
    const task = pdfTasks.find((item) => item.id === id); if (!task?.result) return;
    const text = task.result.preview || ''; const headings = text.split('\n').filter((line) => /^#{1,6}\s/.test(line));
    document.getElementById('pdfResultTitle').textContent = task.title; document.getElementById('pdfResultPreview').textContent = text || '未生成 Markdown 预览。';
    document.getElementById('pdfResultToc').innerHTML = headings.map((line) => `<button type="button">${escapeHtml(line.replace(/^#+\s*/, ''))}</button>`).join('') || '<span>未识别到标题目录</span>';
    const quality = task.result.quality || {}; const strategy = task.result.strategy || {};
    document.getElementById('pdfResultQuality').innerHTML = `<div class="pdf-quality-score">${escapeHtml(quality.score ?? '-')}</div><strong>${escapeHtml(quality.level || '未知')}</strong><div class="pdf-quality-list"><span>Markdown <b>${quality.markdownFiles || 0}</b></span><span>JSON <b>${quality.jsonFiles || 0}</b></span><span>图片 <b>${quality.imageFiles || 0}</b></span><span>文本字符 <b>${quality.textCharacters || 0}</b></span></div><div class="pdf-strategy">请求模式：${escapeHtml(strategy.requestedMode || task.result.mode)}<br>最终模式：${escapeHtml(strategy.finalMode || task.result.mode)}<br>${(strategy.attempts || []).map((item) => `${item.mode} ${item.score}分`).join(' → ')}</div>`;
    document.getElementById('pdfArchiveResult').disabled = false; document.getElementById('pdfOpenResult').disabled = false;
  };

  pick.addEventListener('click', () => input.click());
  input.addEventListener('change', () => setFile(input.files[0]));
  const drop = document.getElementById('pdfDropZone');
  drop.addEventListener('dragover', (event) => event.preventDefault());
  drop.addEventListener('drop', (event) => { event.preventDefault(); setFile(event.dataTransfer.files[0]); });

  analyze.addEventListener('click', async () => {
    if (!selectedFile) return; analyze.disabled = true; status.textContent = '正在分析 PDF 特征...';
    const form = new FormData(); form.append('file', selectedFile);
    try {
      const response = await fetch('/api/pdf/analyze', { method: 'POST', body: form }); const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.detail || body.error || '分析失败');
      const item = body.analysis; mode.value = item.recommended_mode;
      analysisBox.innerHTML = `<strong>建议：${escapeHtml(item.recommended_mode.toUpperCase())}</strong><br>${escapeHtml(item.reason)}<br>页数：${escapeHtml(item.page_count ?? '未知')} · 原生文本：${item.has_native_text === null ? '未知' : item.has_native_text ? '是' : '否'}`;
      analysisBox.hidden = false; parse.disabled = !body.engine.available; status.textContent = body.engine.available ? '分析完成，可开始本地解析。' : 'PDF 策略已识别，正在等待本地引擎安装。';
    } catch (error) { status.textContent = error.message; } finally { analyze.disabled = false; }
  });

  parse.addEventListener('click', async () => {
    if (!selectedFile) return; parse.disabled = true; status.textContent = '正在提交本地 PDF 任务...';
    const form = new FormData(); form.append('file', selectedFile); form.append('outputPath', outputPath.value); form.append('mode', mode.value);
    try {
      const response = await fetch('/api/pdf/parse', { method: 'POST', body: form }); const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.detail || body.error || '解析失败');
      activeTaskId = body.task.id; cancel.hidden = false; result.innerHTML = `<strong>PDF 任务已进入队列</strong><br>任务 ${escapeHtml(activeTaskId.slice(0, 10))}`;
      const task = await waitForTask(activeTaskId);
      if (task.status !== 'completed') throw new Error(task.error || `任务${task.stage || '未完成'}`);
      const item = task.result; const quality = item.quality || {};
      result.innerHTML = `<strong>解析完成 · 质量${escapeHtml(quality.level || '未知')} ${escapeHtml(quality.score ?? '-')} 分</strong><br>${escapeHtml(item.outputPath)}<br>Markdown ${escapeHtml(quality.markdownFiles || 0)} · JSON ${escapeHtml(quality.jsonFiles || 0)} · 文本 ${escapeHtml(quality.textCharacters || 0)} 字符`;
      preview.textContent = item.preview || ''; preview.hidden = !item.preview; status.textContent = '本地 PDF 解析完成。';
      await refreshPdfTasks();
    } catch (error) { result.textContent = error.message; status.textContent = '解析未完成。'; }
    finally { activeTaskId = ''; cancel.hidden = true; parse.disabled = false; }
  });
  cancel.addEventListener('click', async () => { if (!activeTaskId) return; await fetch(`/api/tasks/${activeTaskId}`, { method: 'DELETE' }); activeTaskId = ''; cancel.hidden = true; status.textContent = '已请求取消 PDF 任务。'; });
  document.getElementById('pdfSelectDir').addEventListener('click', async () => { const form = new FormData(); form.append('currentPath', outputPath.value); const response = await fetch('/api/select-output-dir', { method: 'POST', body: form }); const body = await response.json(); if (body.success && body.path) outputPath.value = body.path; });
  fetch('/api/pdf/health').then((response) => response.json()).then((body) => { health.innerHTML = body.available ? `<strong>引擎可用</strong><br>${escapeHtml(body.detail)}${body.version ? `<br>${escapeHtml(body.version)}` : ''}` : `<strong>引擎待安装</strong><br>${escapeHtml(body.detail)}`; });
  tabButtons.forEach((button) => button.addEventListener('click', () => setTab(button.dataset.pdfTab)));
  taskSearch?.addEventListener('input', renderTaskList); taskFilter?.addEventListener('change', renderTaskList); resultTask?.addEventListener('change', () => renderStructuredResult(resultTask.value));
  document.getElementById('pdfClearFinished')?.addEventListener('click', async () => { await fetch('/api/task-actions/clear-finished?kind=pdf', { method: 'DELETE' }); await refreshPdfTasks(); });
  document.getElementById('pdfArchiveResult')?.addEventListener('click', async () => { if (!resultTask.value) return; const response = await fetch(`/api/pdf/tasks/${resultTask.value}/archive`, { method: 'POST' }); const body = await response.json(); if (body.path) { const form = new FormData(); form.append('path', body.path); await fetch('/api/open-output-path', { method: 'POST', body: form }); } });
  document.getElementById('pdfOpenResult')?.addEventListener('click', async () => { const task = pdfTasks.find((item) => item.id === resultTask.value); if (!task) return; const form = new FormData(); form.append('path', task.result.outputPath); await fetch('/api/open-output-path', { method: 'POST', body: form }); });
  refreshPdfTasks();
})();
