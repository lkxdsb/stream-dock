const form = document.getElementById('fetchForm');
const submitButton = document.getElementById('submitButton');
const clearLogButton = document.getElementById('clearLogButton');
const logOutput = document.getElementById('logOutput');
const statusBadge = document.getElementById('statusBadge');
const statusText = document.getElementById('statusText');
const resultBox = document.getElementById('resultBox');
const resultPath = document.getElementById('resultPath');

function setStatus(kind, text) {
  statusBadge.classList.remove('is-running', 'is-success', 'is-error');
  if (kind === 'running') {
    statusBadge.textContent = '执行中';
    statusBadge.classList.add('is-running');
  } else if (kind === 'success') {
    statusBadge.textContent = '成功';
    statusBadge.classList.add('is-success');
  } else if (kind === 'error') {
    statusBadge.textContent = '失败';
    statusBadge.classList.add('is-error');
  } else {
    statusBadge.textContent = '待执行';
  }
  statusText.textContent = text;
}

function renderLogs(parts) {
  const content = parts.filter(Boolean).join('\n\n').trim();
  logOutput.textContent = content || '无输出。';
}

function showResult(path) {
  if (path) {
    resultPath.textContent = path;
    resultBox.hidden = false;
  } else {
    resultPath.textContent = '-';
    resultBox.hidden = true;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const payload = {
    link: String(formData.get('link') || '').trim(),
    outputPath: String(formData.get('outputPath') || '').trim(),
    outputType: String(formData.get('outputType') || '').trim(),
  };

  if (!payload.link || !payload.outputPath || !payload.outputType) {
    setStatus('error', '请先完整填写链接、输出目录和输出类型。');
    renderLogs(['表单校验未通过。']);
    showResult('');
    return;
  }

  submitButton.disabled = true;
  setStatus('running', '正在调用本地解析脚本，请稍候...');
  renderLogs(['请求已提交，等待脚本输出...']);
  showResult('');

  try {
    const response = await fetch('/api/fetch', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    const stdout = data.stdout ? `stdout:\n${data.stdout}` : '';
    const stderr = data.stderr ? `stderr:\n${data.stderr}` : '';
    renderLogs([stdout, stderr]);

    if (!response.ok || !data.success) {
      setStatus('error', data.error || '解析失败，请查看日志。');
      showResult(data.outputPath || '');
      return;
    }

    setStatus('success', '解析完成，可直接到输出目录查看文件。');
    showResult(data.outputPath || '');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus('error', '请求发送失败，请确认本地服务是否正常。');
    renderLogs([`request error:\n${message}`]);
    showResult('');
  } finally {
    submitButton.disabled = false;
  }
});

clearLogButton.addEventListener('click', () => {
  renderLogs([]);
});
