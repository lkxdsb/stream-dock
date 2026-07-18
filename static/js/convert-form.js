(function () {
  const fileInput = document.getElementById('convertFileInput');
  const pickButton = document.getElementById('convertPickButton');
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
  let selectedFiles = [];
  let currentSource = '';
  let currentOptions = [];
  let batchMode = false;

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
    const options = visibleOptions();
    outputType.innerHTML = options.map((item) => `<option value="${item.target}" data-level="${item.level}" data-vendors="${(item.vendors || []).join('|')}">${optionLabel(item)}</option>`).join('') || '<option value="">当前筛选下暂无可用转换</option>';
    updateHint();
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
    const maxVisible = 6;
    const visibleFiles = files.slice(0, maxVisible);
    fileList.innerHTML = [
      '<div class="convert-file-list-title">已选择文件</div>',
      '<div class="convert-file-chips">',
      ...visibleFiles.map((file) => `<span class="convert-file-chip" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>`),
      files.length > maxVisible ? `<span class="convert-file-chip muted">+${files.length - maxVisible} 个更多</span>` : '',
      '</div>',
    ].join('');
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

  async function fallbackProbeFiles(files) {
    const probed = [];
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch('/api/convert/probe', { method: 'POST', body: form });
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

  async function probeFiles(filesLike) {
    selectedFiles = Array.from(filesLike || []).filter(Boolean);
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
      const response = await fetch('/api/convert/batch-probe', { method: 'POST', body: form });
      data = await readJsonResponse(response);
      if (!response.ok || !data.success) {
        if (response.status === 404 || response.status === 405 || response.status === 422) {
          setLog([
            `批量识别接口返回 HTTP ${response.status}，改用逐文件识别兜底...`,
            data?.detail ? `detail: ${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}` : '',
          ].filter(Boolean));
          data = await fallbackProbeFiles(selectedFiles);
        } else {
          throw new Error(errorMessageFrom(data, response, '格式识别失败'));
        }
      }
    } else {
      const form = new FormData();
      form.append('file', selectedFiles[0]);
      const response = await fetch('/api/convert/probe', { method: 'POST', body: form });
      data = await readJsonResponse(response);
      if (!response.ok || !data.success) {
        throw new Error(errorMessageFrom(data, response, '格式识别失败'));
      }
    }

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
  fileInput?.addEventListener('change', () => {
    if (fileInput.files?.length) probeFiles(fileInput.files).catch(handleProbeError);
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
    if (files?.length) probeFiles(files).catch(handleProbeError);
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
    if (batchMode) selectedFiles.forEach((file) => form.append('files', file));
    else form.append('file', selectedFiles[0]);
    form.append('inputType', currentSource);
    form.append('outputType', outputType.value);
    form.append('outputPath', outputPath.value || '~/Downloads/StreamDock');
    const convertSettings = window.StreamDockConvertSettings?.get?.() || {};
    form.append('namingStrategy', convertSettings.namingStrategy || 'append');

    const label = `${currentSource.toUpperCase()} → ${outputType.value.toUpperCase()}`;
    setLog([batchMode ? '开始批量转换...' : '开始转换...', label, `文件数量：${selectedFiles.length}`]);
    window.StreamDockConvertResult?.processing?.(batchMode ? `正在转换 ${selectedFiles.length} 个文件` : `正在转换 ${selectedFiles[0]?.name || '文件'}`);
    startButton.disabled = true;
    startButton.textContent = batchMode ? '批量转换中...' : '转换中...';
    try {
      const response = await fetch(batchMode ? '/api/convert/batch-run' : '/api/convert/run', { method: 'POST', body: form });
      const data = await response.json();
      setLog(data.logs || []);
      if (data.success) {
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
          fetch('/api/open-output-path', { method: 'POST', body: openForm }).catch(() => {});
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
