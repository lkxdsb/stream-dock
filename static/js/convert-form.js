(function () {
  const fileInput = document.getElementById('convertFileInput');
  const folderInput = document.getElementById('convertFolderInput');
  const pickButton = document.getElementById('convertPickButton');
  const pickFolderButton = document.getElementById('convertPickFolderButton');
  const dropZone = document.getElementById('convertDropZone');
  const fileTitle = document.getElementById('convertFileTitle');
  const fileMeta = document.getElementById('convertFileMeta');
  const fileList = document.getElementById('convertFileList');
  const inputType = document.getElementById('convertInputType');
  const outputType = document.getElementById('convertOutputType');
  const outputPath = document.getElementById('convertOutputPath');
  const selectDirButton = document.getElementById('convertSelectDirButton');
  const startButton = document.getElementById('convertStartButton');
  const hint = document.getElementById('convertHint');
  const archivePasswordField = document.getElementById('convertArchivePasswordField');
  let selectedFiles = [];
  let currentSource = '';
  let currentOptions = [];
  let batchMode = false;
  let folderMode = false;
  let folderName = '';
  let folderEntries = [];
  let folderDirectories = [];
  let probeSequence = 0;
  let probeController = null;

  function setLog(lines) { window.StreamDockConvertLogs?.set(lines); }
  function setResultWaiting() { window.StreamDockConvertResult?.waiting(); }
  function setError(message, vendors) { window.StreamDockConvertResult?.error(message, vendors); }
  function setSuccess(data) { window.StreamDockConvertResult?.success(data); }
  function setBatch(data) { window.StreamDockConvertResult?.batch(data); }

  function optionLabel(item) {
    const level = item.verification === 'verified' ? '样例已验证'
      : item.level === 'stable' ? '成熟引擎'
        : item.level === 'basic' ? '基础转换' : '推荐厂商';
    return `${item.target.toUpperCase()} · ${level}`;
  }

  function visibleOptions() {
    const preferredLevel = window.StreamDockConvertSettings?.get?.().defaultLevel;
    if (preferredLevel && preferredLevel !== 'all') {
      // “本地基础”代表允许所有本地路径，不应把更可靠的 stable 路径排除。
      const filtered = currentOptions.filter((item) => (
        preferredLevel === 'basic'
          ? ['stable', 'basic'].includes(item.level)
          : item.level === preferredLevel
      ));
      return filtered.length ? filtered : currentOptions;
    }
    return currentOptions;
  }

  function renderOutputOptions() {
    const previousTarget = outputType.value;
    const options = visibleOptions();
    outputType.innerHTML = options.map((item) => `<option value="${item.target}" data-level="${item.level}" data-vendors="${(item.vendors || []).join('|')}">${optionLabel(item)}</option>`).join('') || '<option value="">当前筛选下暂无可用转换</option>';
    if (previousTarget && options.some((item) => item.target === previousTarget)) outputType.value = previousTarget;
    updateHint();
    if (archivePasswordField) archivePasswordField.hidden = !['zip', 'rar', '7z'].includes(currentSource);
  }

  function fileSizeLabel(files) {
    const total = files.reduce((sum, file) => sum + (file.size || 0), 0);
    if (total > 1024 * 1024) return `${(total / 1024 / 1024).toFixed(1)} MB`;
    return `${(total / 1024).toFixed(1)} KB`;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function renderSelectedFiles(files) {
    if (!fileList) return;
    if (!files.length) {
      fileList.innerHTML = '';
      return;
    }
    fileList.innerHTML = [
      `<div class="convert-file-list-title"><span>已选择 ${files.length} 个文件</span><button type="button" data-clear-files>清空</button></div>`,
      '<div class="convert-file-chips">',
      ...files.map((file, index) => {
        const name = file.streamdockRelativePath || file.webkitRelativePath || file.name;
        return `<span class="convert-file-chip" title="${escapeHtml(name)}"><span>${index + 1}. ${escapeHtml(name)}</span><button type="button" data-remove-file="${index}" aria-label="移除 ${escapeHtml(name)}">×</button></span>`;
      }),
      '</div>',
    ].join('');
  }

  function fileIdentity(file) {
    return [file.streamdockRelativePath || file.webkitRelativePath || file.name, file.size, file.lastModified].join(':');
  }

  function resetSelection() {
    selectedFiles = [];
    currentSource = '';
    currentOptions = [];
    batchMode = false;
    folderMode = false;
    folderName = '';
    folderEntries = [];
    folderDirectories = [];
    probeController?.abort();
    probeSequence += 1;
    renderSelectedFiles([]);
    fileTitle.textContent = '选择或拖入文件';
    fileMeta.textContent = '可分多次追加同类型文件，并在提交前逐项移除';
    inputType.value = '';
    outputType.innerHTML = '<option value="">请先选择文件</option>';
    if (archivePasswordField) archivePasswordField.hidden = true;
    setResultWaiting();
  }

  function configureFolder(entries, directories, name) {
    folderMode = true;
    folderName = name || '文件夹';
    folderEntries = entries;
    folderDirectories = directories;
    selectedFiles = entries.map((entry) => {
      try { Object.defineProperty(entry.file, 'streamdockRelativePath', { value: entry.path, configurable: true }); } catch (_error) {}
      return entry.file;
    });
    batchMode = false;
    currentSource = 'folder';
    currentOptions = [
      { target: 'zip', level: 'stable', verification: 'verified', vendors: [] },
      { target: 'tar.gz', level: 'stable', verification: 'verified', vendors: [] },
    ];
    inputType.value = 'FOLDER';
    fileTitle.textContent = `已选择文件夹：${folderName}`;
    fileMeta.textContent = `${selectedFiles.length} 个文件 · ${folderDirectories.length} 个目录（包含空目录）`;
    renderSelectedFiles(selectedFiles);
    renderOutputOptions();
    setLog(['文件夹目录树已读取', `文件：${selectedFiles.length} 个`, `目录：${folderDirectories.length} 个`]);
    setResultWaiting();
  }

  async function chooseFolder() {
    if (!window.showDirectoryPicker) {
      folderInput?.click();
      return;
    }
    const root = await window.showDirectoryPicker({ mode: 'read' });
    const entries = [];
    const directories = [];
    async function walk(handle, prefix) {
      for await (const child of handle.values()) {
        const path = prefix ? `${prefix}/${child.name}` : child.name;
        if (child.kind === 'directory') {
          directories.push(path);
          await walk(child, path);
        } else {
          entries.push({ file: await child.getFile(), path });
        }
      }
    }
    await walk(root, '');
    configureFolder(entries, directories, root.name);
  }

  function mergeFiles(current, incoming) {
    const merged = new Map(current.map((file) => [fileIdentity(file), file]));
    incoming.forEach((file) => merged.set(fileIdentity(file), file));
    return Array.from(merged.values());
  }

  function inferClientFormat(filename) {
    const lower = String(filename || '').toLowerCase();
    if (lower.endsWith('.tar.gz')) return 'tar.gz';
    if (lower.endsWith('.ndjson')) return 'ndjson';
    const dotIndex = lower.lastIndexOf('.');
    if (dotIndex < 0 || dotIndex === lower.length - 1) return '';
    const ext = lower.slice(dotIndex + 1);
    const aliases = { jpeg: 'jpg', htm: 'html', markdown: 'md', yml: 'yaml', tgz: 'tar.gz' };
    return aliases[ext] || ext;
  }

  function validateSameFormat(files) {
    const formats = Array.from(new Set(files.map((file) => inferClientFormat(file.name) || '未知')));
    if (formats.length <= 1) return { ok: true, format: formats[0] || '' };
    return { ok: false, formats };
  }

  async function readJsonResponse(response) {
    const text = await response.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch (_error) {
      return { success: false, error: text || `HTTP ${response.status}` };
    }
  }

  function errorMessageFrom(data, response, fallback) {
    if (data?.error) return data.error;
    if (data?.detail) return typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    return `${fallback}（HTTP ${response.status}）`;
  }

  async function fallbackProbeFiles(files, signal) {
    const probed = [];
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch('/api/convert/probe', { method: 'POST', body: form, signal });
      const data = await readJsonResponse(response);
      if (!response.ok || !data.success) {
        throw new Error(errorMessageFrom(data, response, `${file.name} 识别失败`));
      }
      probed.push({ file, data });
    }
    const sources = Array.from(new Set(probed.map((item) => item.data.source || '')));
    if (sources.length !== 1) {
      throw new Error(`批量转换第一版要求同一种输入格式；当前识别到：${sources.join(' / ') || '未知'}`);
    }
    return {
      success: true,
      source: sources[0],
      fileCount: files.length,
      supported: Boolean(probed[0]?.data?.supported),
      options: probed[0]?.data?.options || [],
      files: probed.map((item) => ({ filename: item.file.name, source: item.data.source })),
      fallback: true,
    };
  }

  async function probeFiles(filesLike, { append = false } = {}) {
    folderMode = false;
    folderName = '';
    folderEntries = [];
    folderDirectories = [];
    const sequence = ++probeSequence;
    probeController?.abort();
    probeController = new AbortController();
    const signal = probeController.signal;
    const incoming = Array.from(filesLike || []).filter(Boolean);
    selectedFiles = append ? mergeFiles(selectedFiles, incoming) : incoming;
    batchMode = selectedFiles.length > 1;
    if (!selectedFiles.length) return;

    const names = selectedFiles.map((file) => file.name);
    fileTitle.textContent = batchMode ? `已选择 ${selectedFiles.length} 个文件` : selectedFiles[0].name;
    fileMeta.textContent = batchMode
      ? `${fileSizeLabel(selectedFiles)} · 正在检查是否为同一种输入格式...`
      : `${fileSizeLabel(selectedFiles)} · 正在识别格式...`;
    renderSelectedFiles(selectedFiles);
    outputType.innerHTML = '<option value="">识别中...</option>';
    setResultWaiting();
    setLog(['识别文件格式...', ...names.slice(0, 8)]);

    if (batchMode) {
      const formatCheck = validateSameFormat(selectedFiles);
      if (!formatCheck.ok) {
        const message = `不能同时选择不同文件格式：${formatCheck.formats.map((item) => item.toUpperCase()).join(' / ')}。请一次只选择同一种格式的文件。`;
        currentSource = '';
        currentOptions = [];
        inputType.value = '';
        outputType.innerHTML = '<option value="">请重新选择同格式文件</option>';
        fileMeta.textContent = message;
        setError(message);
        setLog(['批量选择已拦截', message, ...names]);
        return;
      }
    }

    let data;
    if (batchMode) {
      const form = new FormData();
      selectedFiles.forEach((file) => form.append('files', file));
      const response = await fetch('/api/convert/batch-probe', { method: 'POST', body: form, signal });
      data = await readJsonResponse(response);
      if (!response.ok || !data.success) {
        if (response.status === 404 || response.status === 405 || response.status === 422) {
          setLog([
            `批量识别接口返回 HTTP ${response.status}，改用逐文件识别兜底...`,
            data?.detail ? `detail: ${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}` : '',
          ].filter(Boolean));
          data = await fallbackProbeFiles(selectedFiles, signal);
        } else {
          throw new Error(errorMessageFrom(data, response, '格式识别失败'));
        }
      }
    } else {
      const form = new FormData();
      form.append('file', selectedFiles[0]);
      const response = await fetch('/api/convert/probe', { method: 'POST', body: form, signal });
      data = await readJsonResponse(response);
      if (!response.ok || !data.success) {
        throw new Error(errorMessageFrom(data, response, '格式识别失败'));
      }
    }

    if (sequence !== probeSequence || signal.aborted) return;
    currentSource = data.source || '';
    currentOptions = data.options || [];
    inputType.value = currentSource.toUpperCase();
    if (batchMode) fileTitle.textContent = `已选择 ${selectedFiles.length} 个 ${currentSource.toUpperCase()} 文件`;
    fileMeta.textContent = data.supported
      ? `识别为 ${currentSource.toUpperCase()}，${batchMode ? `${selectedFiles.length} 个文件，` : ''}找到 ${currentOptions.length} 条可用路径`
      : `识别为 ${currentSource.toUpperCase()}，暂无可用路径`;
    renderOutputOptions();
    setLog([
      '格式识别完成',
      data.fallback ? '识别方式：逐文件兜底' : '识别方式：批量接口',
      `输入格式：${currentSource.toUpperCase()}`,
      `文件数量：${selectedFiles.length}`,
      `可用路径：${currentOptions.length}`,
    ]);
  }

  function updateHint() {
    const option = outputType.selectedOptions[0];
    const level = option?.dataset?.level;
    if (level === 'vendor') hint.textContent = '该路径属于推荐厂商能力，不执行本地转换。';
    else if (level === 'basic') hint.textContent = batchMode ? '批量基础转换会逐个文件顺序执行，复杂排版可能有损。' : '基础转换适合普通文件，复杂排版可能有损。';
    else hint.textContent = batchMode ? '批量转换会按同一路径顺序处理，结果逐条进入任务中心。' : '本地稳定路径会直接转换，转换结果保存在指定目录。';
  }

  function handleProbeError(error) {
    const message = error instanceof Error ? error.message : String(error || '格式识别失败');
    currentSource = '';
    currentOptions = [];
    if (inputType) inputType.value = '';
    if (outputType) outputType.innerHTML = '<option value="">暂无可用转换</option>';
    if (fileTitle && selectedFiles.length > 1) fileTitle.textContent = `已选择 ${selectedFiles.length} 个文件`;
    if (fileMeta) fileMeta.textContent = message;
    setError(message);
    setLog(['格式识别失败', message]);
  }

  pickButton?.addEventListener('click', () => fileInput?.click());
  pickFolderButton?.addEventListener('click', () => chooseFolder().catch((error) => {
    if (error?.name !== 'AbortError') handleProbeError(error);
  }));
  fileInput?.addEventListener('change', () => {
    if (fileInput.files?.length) probeFiles(fileInput.files, { append: selectedFiles.length > 0 && !folderMode }).catch((error) => { if (error?.name !== 'AbortError') handleProbeError(error); });
    fileInput.value = '';
  });
  folderInput?.addEventListener('change', () => {
    const files = Array.from(folderInput.files || []);
    if (!files.length) return;
    const firstPath = files[0].webkitRelativePath || files[0].name;
    const root = firstPath.split('/')[0] || '文件夹';
    const entries = files.map((file) => {
      const raw = file.webkitRelativePath || file.name;
      const path = raw.startsWith(`${root}/`) ? raw.slice(root.length + 1) : raw;
      return { file, path };
    });
    configureFolder(entries, [], root);
    folderInput.value = '';
  });
  outputType?.addEventListener('change', updateHint);
  window.addEventListener('streamdock:convert-settings-change', () => {
    if (currentOptions.length) renderOutputOptions();
  });

  dropZone?.addEventListener('dragover', (event) => { event.preventDefault(); dropZone.classList.add('dragging'); });
  dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('dragging'));
  dropZone?.addEventListener('drop', (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragging');
    const files = event.dataTransfer?.files;
    if (files?.length) probeFiles(files, { append: selectedFiles.length > 0 }).catch((error) => { if (error?.name !== 'AbortError') handleProbeError(error); });
  });

  fileList?.addEventListener('click', (event) => {
    const removeButton = event.target.closest('[data-remove-file]');
    if (removeButton) {
      const index = Number(removeButton.dataset.removeFile);
      if (folderMode) {
        const remainingEntries = folderEntries.filter((_entry, currentIndex) => currentIndex !== index);
        if (remainingEntries.length) configureFolder(remainingEntries, folderDirectories, folderName);
        else resetSelection();
        return;
      }
      const remaining = selectedFiles.filter((_file, currentIndex) => currentIndex !== index);
      if (remaining.length) probeFiles(remaining).catch(handleProbeError);
      else {
        probeController?.abort();
        probeSequence += 1;
        selectedFiles = [];
        currentSource = '';
        currentOptions = [];
        batchMode = false;
        fileTitle.textContent = '选择或拖入文件';
        fileMeta.textContent = '可分多次追加同类型文件，并在提交前逐项移除';
        inputType.value = '';
        outputType.innerHTML = '<option value="">请先选择文件</option>';
        if (archivePasswordField) archivePasswordField.hidden = true;
        renderSelectedFiles([]);
        setResultWaiting();
      }
      return;
    }
    if (event.target.closest('[data-clear-files]')) {
      resetSelection();
    }
  });

  selectDirButton?.addEventListener('click', async () => {
    setLog(['打开系统目录选择窗口...']);
    const response = await fetch('/api/convert/select-output-dir', { method: 'POST' });
    const data = await response.json();
    if (data.success && data.path) {
      outputPath.value = data.path;
      setLog(['已选择保存目录', data.path]);
    } else {
      setLog(['目录选择未完成', data.error || '已取消']);
    }
  });

  startButton?.addEventListener('click', async () => {
    if (!selectedFiles.length) {
      setError('请先选择需要转换的文件');
      return;
    }
    if (!outputType.value) {
      setError('请选择输出格式');
      return;
    }
    const option = outputType.selectedOptions[0];
    if (option?.dataset?.level === 'vendor') {
      setError('该转换对高保真或 OCR 要求较高，建议使用专业工具完成。', (option.dataset.vendors || '').split('|').filter(Boolean));
      setLog(['推荐厂商路径，不执行本地转换']);
      return;
    }
    const form = new FormData();
    if (folderMode) {
      folderEntries.forEach((entry) => form.append('files', entry.file));
      form.append('relativePaths', JSON.stringify(folderEntries.map((entry) => entry.path)));
      form.append('directoryPaths', JSON.stringify(folderDirectories));
      form.append('folderName', folderName);
    } else if (batchMode) selectedFiles.forEach((file) => form.append('files', file));
    else form.append('file', selectedFiles[0]);
    form.append('inputType', currentSource);
    form.append('outputType', outputType.value);
    form.append('outputPath', outputPath.value || '~/Downloads/StreamDock');
    const convertSettings = window.StreamDockConvertSettings?.get?.() || {};
    form.append('namingStrategy', convertSettings.namingStrategy || 'append');
    form.append('imageQuality', String(convertSettings.imageQuality || 90));
    form.append('audioBitrateKbps', String(convertSettings.audioBitrateKbps || 192));
    form.append('audioSampleRate', String(convertSettings.audioSampleRate || 0));
    form.append('videoMaxWidth', String(convertSettings.videoMaxWidth || 0));
    form.append('videoFrameRate', String(convertSettings.videoFrameRate || 0));
    form.append('videoBitrateKbps', String(convertSettings.videoBitrateKbps || 0));
    form.append('videoCrf', String(convertSettings.videoCrf ?? 22));
    form.append('hardwareAcceleration', convertSettings.hardwareAcceleration || 'software');
    form.append('archivePassword', document.getElementById('convertArchivePassword')?.value || '');

    const label = `${currentSource.toUpperCase()} → ${outputType.value.toUpperCase()}`;
    setLog([batchMode ? '开始批量转换...' : '开始转换...', label, `文件数量：${selectedFiles.length}`]);
    window.StreamDockConvertResult?.processing?.(batchMode ? `正在转换 ${selectedFiles.length} 个文件` : `正在转换 ${selectedFiles[0]?.name || '文件'}`);
    startButton.disabled = true;
    startButton.textContent = batchMode ? '批量转换中...' : '转换中...';
    try {
      const endpoint = folderMode ? '/api/convert/folder-run' : batchMode ? '/api/convert/batch-run' : '/api/convert/run';
      const response = await fetch(endpoint, { method: 'POST', body: form });
      const data = await response.json();
      setLog(data.logs || []);
      if (batchMode && Array.isArray(data.results)) {
        setBatch(data);
        window.StreamDockConvertResult?.showTaskJump?.(data.tasks?.[0]?.id || '');
        if (!data.success) window.StreamDockUI?.showToast?.(`批量转换部分完成：成功 ${data.successCount || 0}，失败 ${data.failedCount || 0}`);
      } else if (data.success) {
        if (batchMode) {
          setBatch(data);
          window.StreamDockConvertResult?.showTaskJump?.(data.tasks?.[0]?.id || '');
        } else {
          setSuccess(data);
          window.StreamDockConvertResult?.showTaskJump?.(data.task?.id || '');
        }
        if (['open', 'highlight', 'open-folder'].includes(convertSettings.afterDoneAction)) {
          const openForm = new FormData();
          openForm.append('path', data.outputPath || outputPath.value || '~/Downloads/StreamDock');
          const endpoint = convertSettings.afterDoneAction === 'highlight'
            ? '/api/reveal-output-file'
            : '/api/open-output-path';
          fetch(endpoint, { method: 'POST', body: openForm }).catch(() => {});
        }
      } else {
        setError(data.error || '转换失败', data.vendorRecommendations);
        if (data.task?.id) window.StreamDockConvertResult?.showTaskJump?.(data.task.id);
      }
      window.StreamDockTaskCenter?.refreshNow?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      startButton.disabled = false;
      startButton.textContent = '开始转换';
    }
  });
})();
