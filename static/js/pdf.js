(() => {
  const input = document.getElementById('pdfFileInput');
  if (!input) return;
  const pick = document.getElementById('pdfPickButton');
  const analyze = document.getElementById('pdfAnalyzeButton');
  const parse = document.getElementById('pdfParseButton');
  const cancel = document.getElementById('pdfCancelButton');
  const status = document.getElementById('pdfStatus');
  const analysisBox = document.getElementById('pdfAnalysis');
  const stepHint = document.getElementById('pdfStepHint');
  const result = document.getElementById('pdfResult');
  const preview = document.getElementById('pdfPreview');
  const health = document.getElementById('pdfHealth');
  const healthRefresh = document.getElementById('pdfHealthRefresh');
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
  const modeLabel = (value) => {
    const key = String(value || '').toLowerCase();
    return {
      auto: '自动判断 AUTO',
      fast: '快速解析 FAST',
      ocr: '扫描件 OCR',
      precise: '精准混合 PRECISE',
    }[key] || String(value || '未知模式').toUpperCase();
  };
  const normalizePdfMarkdownText = (raw) => {
    let text = String(raw || '');
    text = text.replace(/<br\s*\/?\s*>/gi, '\n');
    text = text.replace(/<\/p>\s*<p[^>]*>/gi, '\n\n').replace(/<\/?p[^>]*>/gi, '');
    text = text.replace(/<\/?(?:thead|tbody|tfoot|table)[^>]*>/gi, '\n');
    text = text.replace(/<tr[^>]*>/gi, '').replace(/<\/tr>/gi, '\n');
    text = text.replace(/<\/(?:td|th)>\s*<(?:td|th)[^>]*>/gi, ' | ');
    text = text.replace(/<(?:td|th)[^>]*>/gi, '').replace(/<\/(?:td|th)>/gi, '');
    text = text.replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#39;/gi, "'");
    text = text.replace(/<\/?(?:div|span|section|article|strong|em|b|i|u|center|font)[^>]*>/gi, '');
    return text.replace(/\n{4,}/g, '\n\n\n').replace(/[ \t]{2,}/g, ' ').trim();
  };
  const renderPdfMarkdownPreview = (raw, taskId = '') => {
    const images = [];
    let text = String(raw || '');
    const stashImage = (src, alt = '图片') => {
      const index = images.push({ src: String(src || '').trim(), alt: String(alt || '图片').trim() }) - 1;
      return `\n[[STREAMDOCK_PDF_IMAGE_${index}]]\n`;
    };
    text = text.replace(/<img\b[^>]*src=["']([^"']+)["'][^>]*>/gi, (match, src) => {
      const alt = (match.match(/alt=["']([^"']*)["']/i) || [])[1] || '图片';
      return stashImage(src, alt);
    });
    text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => stashImage(src, alt || '图片'));
    text = normalizePdfMarkdownText(text);
    let html = escapeHtml(text);
    html = html.replace(/\[\[STREAMDOCK_PDF_IMAGE_(\d+)\]\]/g, (_, rawIndex) => {
      const item = images[Number(rawIndex)];
      if (!item?.src || !taskId) return `<span class="pdf-image-missing">[图片：${escapeHtml(item?.src || 'image')}]</span>`;
      const url = `/api/pdf/tasks/${encodeURIComponent(taskId)}/asset?path=${encodeURIComponent(item.src)}`;
      return `<figure class="pdf-inline-image"><img src="${url}" alt="${escapeHtml(item.alt)}" loading="lazy" /><figcaption>${escapeHtml(item.alt || item.src.split('/').pop() || '图片')}</figcaption></figure>`;
    });
    return html;
  };
  const ensurePdfImageLightbox = () => {
    let box = document.getElementById('pdfImageLightbox');
    if (box) return box;
    box = document.createElement('div');
    box.id = 'pdfImageLightbox';
    box.className = 'pdf-image-lightbox';
    box.hidden = true;
    box.innerHTML = '<button type="button" aria-label="关闭图片预览">×</button><img alt="PDF 图片预览" />';
    box.addEventListener('click', (event) => { if (event.target === box || event.target.tagName === 'BUTTON') box.hidden = true; });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') box.hidden = true; });
    document.body.appendChild(box);
    return box;
  };
  const openPdfImageLightbox = (img) => {
    const box = ensurePdfImageLightbox();
    const target = box.querySelector('img');
    target.src = img.src;
    target.alt = img.alt || 'PDF 图片预览';
    box.hidden = false;
  };
  const bindPdfPreviewImages = (root) => {
    if (root.dataset.imagePreviewBound === '1') return;
    root.dataset.imagePreviewBound = '1';
    root.addEventListener('click', (event) => {
      const img = event.target.closest?.('.pdf-inline-image img');
      if (!img) return;
      event.preventDefault();
      openPdfImageLightbox(img);
    });
  };
  const setFile = (file) => {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) { status.textContent = '请选择 PDF 文件。'; return; }
    selectedFile = file; title.textContent = file.name; meta.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 等待文档特征分析`;
    analyze.disabled = false; parse.disabled = true; analysisBox.hidden = true; preview.hidden = true; status.textContent = '文件已就绪，请先分析文档。';
    if (stepHint) stepHint.innerHTML = '<i>2</i><span>文件已就绪，先分析文档特征，再开始解析。</span>';
    analyze.title = '分析 PDF 文档特征';
    parse.title = '请先完成文档分析';
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
    const finishedStatuses = ['completed', 'failed', 'cancelled', 'skipped'];
    taskList.innerHTML = rows.map((task) => `<article class="pdf-task-item is-${escapeHtml(task.status || 'pending')}" data-pdf-task-id="${escapeHtml(task.id)}"><div><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.stage || statusName(task.status))}${task.progress == null ? '' : ` · ${Math.round(task.progress)}%`} · ${escapeHtml(task.result?.quality?.level || '')}</span>${task.error ? `<span class="pdf-task-error">${escapeHtml(task.error)}</span>` : ''}</div><div class="pdf-task-actions"><em>${escapeHtml(statusName(task.status))}</em>${task.status === 'completed' ? '<button type="button" data-view-pdf-result>查看结果</button><button type="button" data-open-pdf-output>打开目录</button>' : ''}${['pending','running'].includes(task.status) ? '<button type="button" data-cancel-pdf-task>取消</button>' : ''}${finishedStatuses.includes(task.status) ? '<button type="button" data-delete-pdf-task>删除记录</button>' : ''}</div></article>`).join('');
    taskEmpty.textContent = (query || filter !== 'all') ? '没有符合条件的 PDF 任务。' : '暂无 PDF 任务。';
    taskEmpty.hidden = rows.length > 0;
    taskList.querySelectorAll('[data-view-pdf-result]').forEach((button) => button.addEventListener('click', () => { const id = button.closest('[data-pdf-task-id]').dataset.pdfTaskId; setTab('results'); resultTask.value = id; renderStructuredResult(id); }));
    taskList.querySelectorAll('[data-open-pdf-output]').forEach((button) => button.addEventListener('click', async () => { const task = pdfTasks.find((item) => item.id === button.closest('[data-pdf-task-id]').dataset.pdfTaskId); const form = new FormData(); form.append('path', task.result.outputPath); await fetch('/api/open-output-path', { method: 'POST', body: form }); }));
    taskList.querySelectorAll('[data-cancel-pdf-task]').forEach((button) => button.addEventListener('click', async () => { await fetch(`/api/tasks/${button.closest('[data-pdf-task-id]').dataset.pdfTaskId}`, { method: 'DELETE' }); await refreshPdfTasks(); }));
    taskList.querySelectorAll('[data-delete-pdf-task]').forEach((button) => button.addEventListener('click', async () => {
      const id = button.closest('[data-pdf-task-id]').dataset.pdfTaskId;
      button.disabled = true;
      try {
        const response = await fetch(`/api/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' });
        const body = await response.json();
        if (!response.ok || !body.success) throw new Error(body.error || '删除记录失败');
        window.StreamDockUI?.showToast?.('PDF 任务记录已删除');
        await refreshPdfTasks();
      } catch (error) {
        status.textContent = error.message || '删除记录失败';
        button.disabled = false;
      }
    }));
  };
  const refreshPdfTasks = async () => {
    const response = await fetch('/api/tasks?kind=pdf'); const body = await response.json(); pdfTasks = body.tasks || []; renderTaskList();
    const completed = pdfTasks.filter((task) => task.status === 'completed'); const selected = resultTask.value;
    resultTask.innerHTML = completed.map((task) => `<option value="${escapeHtml(task.id)}">${escapeHtml(task.title)}</option>`).join('') || '<option value="">暂无已完成任务</option>';
    if (completed.some((task) => task.id === selected)) resultTask.value = selected;
    if (resultTask.value) {
      const selectedTask = completed.find((task) => task.id === resultTask.value);
      renderStructuredResult(resultTask.value, { fromHistory: !activeTaskId || activeTaskId !== resultTask.value });
      if (result && selectedTask?.result) {
        const quality = selectedTask.result.quality || {};
        result.innerHTML = `<strong>最近一次解析结果 · 来自历史记录</strong><br>${escapeHtml(selectedTask.title || 'PDF 文档')} · 质量${escapeHtml(quality.level || '未知')} ${escapeHtml(quality.score ?? '-')} 分<br>${escapeHtml(selectedTask.result.outputPath || '')}`;
      }
    } else {
      document.getElementById('pdfResultTitle').textContent = '请选择已完成任务';
      document.getElementById('pdfResultPreview').textContent = '暂无结构化内容。';
      document.getElementById('pdfResultToc').innerHTML = '<span>暂无目录</span>';
      document.getElementById('pdfResultQuality').textContent = '暂无数据。';
      document.getElementById('pdfArchiveResult').disabled = true;
      document.getElementById('pdfOpenResult').disabled = true;
    }
  };
  let resultRenderToken = 0;
  const renderStructuredResult = async (id, options = {}) => {
    const task = pdfTasks.find((item) => item.id === id); if (!task?.result) return;
    const token = ++resultRenderToken;
    const previewElement = document.getElementById('pdfResultPreview');
    const tocElement = document.getElementById('pdfResultToc');
    const titlePrefix = options.fromHistory ? `${task.title} · 历史记录` : task.title;
    document.getElementById('pdfResultTitle').textContent = `${titlePrefix} · 正在读取完整结果`;
    previewElement.textContent = '正在加载完整 Markdown…';
    tocElement.innerHTML = '<span>正在生成完整目录…</span>';
    let text = task.result.preview || '';
    let headings = [];
    try {
      const response = await fetch(`/api/pdf/tasks/${encodeURIComponent(id)}/content`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || '完整结果读取失败');
      if (token !== resultRenderToken) return;
      text = body.content || '';
      headings = body.headings || [];
      document.getElementById('pdfResultTitle').textContent = `${titlePrefix} · ${Number(body.characters || text.length).toLocaleString()} 字符`;
    } catch (error) {
      if (token !== resultRenderToken) return;
      headings = Array.from(text.matchAll(/^(#{1,6})\s+(.+?)\s*$/gm)).map((match) => ({ level: match[1].length, title: match[2], offset: match.index }));
      document.getElementById('pdfResultTitle').textContent = `${titlePrefix} · 仅显示缓存预览`;
    }
    previewElement.innerHTML = renderPdfMarkdownPreview(text, id) || '未生成 Markdown 内容。';
    bindPdfPreviewImages(previewElement);
    tocElement.innerHTML = headings.map((heading) => `<button type="button" data-heading-offset="${Number(heading.offset || 0)}" style="--toc-level:${Number(heading.level || 1)}">${escapeHtml(heading.title)}</button>`).join('') || '<span>未识别到标题目录</span>';
    tocElement.querySelectorAll('[data-heading-offset]').forEach((button) => button.addEventListener('click', () => {
      const offset = Number(button.dataset.headingOffset || 0);
      const range = Math.max(0, previewElement.scrollHeight - previewElement.clientHeight);
      previewElement.scrollTo({ top: text.length ? range * (offset / text.length) : 0, behavior: 'smooth' });
      tocElement.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
    }));
    const quality = task.result.quality || {}; const strategy = task.result.strategy || {};
    document.getElementById('pdfResultQuality').innerHTML = `<div class="pdf-quality-score">${escapeHtml(quality.score ?? '-')}</div><strong>${escapeHtml(quality.level || '未知')}</strong><div class="pdf-quality-list"><span>Markdown <b>${quality.markdownFiles || 0}</b></span><span>JSON <b>${quality.jsonFiles || 0}</b></span><span>图片 <b>${quality.imageFiles || 0}</b></span><span>文本字符 <b>${quality.textCharacters || 0}</b></span></div><div class="pdf-strategy">请求模式：${escapeHtml(modeLabel(strategy.requestedMode || task.result.mode))}<br>最终模式：${escapeHtml(modeLabel(strategy.finalMode || task.result.mode))}<br>${(strategy.attempts || []).map((item) => `${modeLabel(item.mode)} ${item.score}分`).join(' → ')}</div>`;
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
      analysisBox.innerHTML = `<strong>建议：${escapeHtml(modeLabel(item.recommended_mode))}</strong><br>${escapeHtml(item.reason)}<br>页数：${escapeHtml(item.page_count ?? '未知')} · 原生文本：${item.has_native_text === null ? '未知' : item.has_native_text ? '是' : '否'}`;
      analysisBox.hidden = false; parse.disabled = !body.engine.available; status.textContent = body.engine.available ? '分析完成，可开始本地解析。' : 'PDF 策略已识别，正在等待本地引擎安装。';
      if (stepHint) stepHint.innerHTML = body.engine.available ? '<i>3</i><span>分析完成，可以开始本地解析。</span>' : '<i>!</i><span>策略已识别，但本地 PDF 引擎暂不可用。</span>';
      parse.title = body.engine.available ? '开始本地 PDF 解析' : '本地 PDF 引擎暂不可用';
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
      preview.innerHTML = renderPdfMarkdownPreview(item.preview || '', activeTaskId); bindPdfPreviewImages(preview); preview.hidden = !item.preview; status.textContent = '本地 PDF 解析完成。';
      await refreshPdfTasks();
    } catch (error) { result.textContent = error.message; status.textContent = '解析未完成。'; }
    finally { activeTaskId = ''; cancel.hidden = true; parse.disabled = false; }
  });
  cancel.addEventListener('click', async () => { if (!activeTaskId) return; await fetch(`/api/tasks/${activeTaskId}`, { method: 'DELETE' }); activeTaskId = ''; cancel.hidden = true; status.textContent = '已请求取消 PDF 任务。'; });
  document.getElementById('pdfSelectDir').addEventListener('click', async () => { const form = new FormData(); form.append('currentPath', outputPath.value); const response = await fetch('/api/select-output-dir', { method: 'POST', body: form }); const body = await response.json(); if (body.success && body.path) outputPath.value = body.path; });
  async function refreshPdfHealth() {
    if (!health) return;
    if (healthRefresh) { healthRefresh.disabled = true; healthRefresh.textContent = '检查中...'; }
    try {
      const response = await fetch('/api/pdf/health');
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'PDF 环境检查失败');
      const status = body.available ? 'ok' : 'missing';
      const detail = `${body.detail || 'PDF 解析引擎状态未知'}${body.version ? ` · ${body.version}` : ''}`;
      health.innerHTML = `<div class="system-health-item is-${status}"><strong>${body.available ? 'PDF 引擎可用' : 'PDF 引擎待安装'}</strong><span>${escapeHtml(detail)}</span></div>`;
    } catch (error) {
      health.innerHTML = `<div class="system-health-item is-error"><strong>PDF 环境检查失败</strong><span>${escapeHtml(error.message || '本地服务暂时不可用')}</span></div>`;
    } finally {
      if (healthRefresh) { healthRefresh.disabled = false; healthRefresh.textContent = '重新检查'; }
    }
  }
  refreshPdfHealth();
  healthRefresh?.addEventListener('click', refreshPdfHealth);
  tabButtons.forEach((button) => button.addEventListener('click', () => setTab(button.dataset.pdfTab)));
  const initialHash = window.location.hash.replace('#', '');
  if (['workbench', 'tasks', 'results'].includes(initialHash)) setTab(initialHash);
  taskSearch?.addEventListener('input', renderTaskList); taskFilter?.addEventListener('change', renderTaskList); resultTask?.addEventListener('change', () => renderStructuredResult(resultTask.value));
  document.getElementById('pdfClearFinished')?.addEventListener('click', async () => { await fetch('/api/task-actions/clear-finished?kind=pdf', { method: 'DELETE' }); await refreshPdfTasks(); });
  document.getElementById('pdfArchiveResult')?.addEventListener('click', async () => { if (!resultTask.value) return; const response = await fetch(`/api/pdf/tasks/${resultTask.value}/archive`, { method: 'POST' }); const body = await response.json(); if (body.path) { const form = new FormData(); form.append('path', body.path); await fetch('/api/open-output-path', { method: 'POST', body: form }); } });
  document.getElementById('pdfOpenResult')?.addEventListener('click', async () => { const task = pdfTasks.find((item) => item.id === resultTask.value); if (!task) return; const form = new FormData(); form.append('path', task.result.outputPath); await fetch('/api/open-output-path', { method: 'POST', body: form }); });
  refreshPdfTasks();
})();
