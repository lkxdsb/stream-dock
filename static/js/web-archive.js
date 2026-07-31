(function () {
  'use strict';

  var urlInput = document.getElementById('webArchiveUrl');
  var outputPathInput = document.getElementById('webArchiveOutputPath');
  var selectDirBtn = document.getElementById('webArchiveSelectDir');
  var extractBtn = document.getElementById('webArchiveExtractBtn');
  var cancelBtn = document.getElementById('webArchiveCancelBtn');
  var statusEl = document.getElementById('webArchiveStatus');
  var resultArea = document.getElementById('webArchiveResult');
  var resultInfo = document.getElementById('webArchiveResultInfo');
  var openDirBtn = document.getElementById('webArchiveOpenDir');
  var openMdBtn = document.getElementById('webArchiveOpenMd');
  var taskList = document.getElementById('webArchiveTaskList');
  var taskEmpty = document.getElementById('webArchiveTaskEmpty');

  var pollTimer = null;
  var currentTaskId = null;

  function showToast(msg) {
    var toast = document.getElementById('toast');
    if (toast) {
      toast.textContent = msg;
      toast.className = 'toast show';
      setTimeout(function () { toast.className = 'toast'; }, 3000);
    }
  }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  function isValidUrl(str) {
    try {
      var u = new URL(str.trim());
      return u.protocol === 'http:' || u.protocol === 'https:';
    } catch (_) {
      return false;
    }
  }

  selectDirBtn && selectDirBtn.addEventListener('click', function () {
    fetch('/api/select-output-dir', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success && data.path) {
          outputPathInput.value = data.path;
        }
      })
      .catch(function () { showToast('选择目录失败'); });
  });

  extractBtn && extractBtn.addEventListener('click', function () {
    var url = (urlInput.value || '').trim();
    var outputPath = (outputPathInput.value || '').trim();

    if (!url) {
      showToast('请输入网页链接');
      urlInput.focus();
      return;
    }
    if (!isValidUrl(url)) {
      showToast('请输入有效的网页链接（需以 http:// 或 https:// 开头）');
      urlInput.focus();
      return;
    }
    if (!outputPath) {
      showToast('请选择输出目录');
      return;
    }

    extractBtn.disabled = true;
    cancelBtn.hidden = false;
    setStatus('正在提交提取任务...');

    fetch('/api/web-archive/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url, outputPath: outputPath }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success && data.task) {
          currentTaskId = data.task.id;
          setStatus('任务已提交，正在提取...');
          startPolling(data.task.id);
        } else {
          extractBtn.disabled = false;
          cancelBtn.hidden = true;
          setStatus(data.error || '提交失败');
          showToast(data.error || '提交失败');
        }
      })
      .catch(function () {
        extractBtn.disabled = false;
        cancelBtn.hidden = true;
        setStatus('网络错误，提交失败');
        showToast('网络错误，提交失败');
      });
  });

  cancelBtn && cancelBtn.addEventListener('click', function () {
    if (!currentTaskId) return;
    fetch('/api/tasks/' + currentTaskId, { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function () {
        stopPolling();
        extractBtn.disabled = false;
        cancelBtn.hidden = true;
        setStatus('任务已取消');
        showToast('任务已取消');
      })
      .catch(function () { showToast('取消失败'); });
  });

  function startPolling(taskId) {
    stopPolling();
    pollTimer = setInterval(function () { pollTask(taskId); }, 2000);
    pollTask(taskId);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function pollTask(taskId) {
    fetch('/api/tasks/' + taskId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success || !data.task) return;
        var task = data.task;
        updateTaskUI(task);
        if (task.status === 'completed') {
          stopPolling();
          extractBtn.disabled = false;
          cancelBtn.hidden = true;
          setStatus('提取完成');
          showResult(task);
        } else if (task.status === 'failed' || task.status === 'cancelled') {
          stopPolling();
          extractBtn.disabled = false;
          cancelBtn.hidden = true;
          setStatus(task.error || '任务失败');
          showToast(task.error || '任务失败');
        } else if (task.status === 'running') {
          setStatus(task.stage || '正在处理...');
        }
      })
      .catch(function () {});
  }

  function updateTaskUI(task) {
    var item = document.querySelector('[data-task-id="' + task.id + '"]');
    if (!item) {
      item = document.createElement('div');
      item.className = 'web-archive-task-item';
      item.setAttribute('data-task-id', task.id);
      taskList.appendChild(item);
      taskEmpty && (taskEmpty.hidden = true);
    }
    item.innerHTML =
      '<span class="task-title">' + escapeHtml(task.title) + '</span>' +
      '<span class="task-stage">' + escapeHtml(task.stage || '') + '</span>' +
      '<span class="task-status ' + task.status + '">' + statusLabel(task.status) + '</span>';
  }

  function statusLabel(s) {
    var map = {
      pending: '等待中',
      running: '处理中',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
      skipped: '已跳过',
    };
    return map[s] || s;
  }

  function showResult(task) {
    var result = task.result || {};
    resultArea.hidden = false;
    resultInfo.innerHTML =
      '<div><strong>页面标题:</strong> ' + escapeHtml(result.title || '-') + '</div>' +
      '<div><strong>原始链接:</strong> ' + escapeHtml(result.url || '-') + '</div>' +
      '<div><strong>提取模式:</strong> ' + escapeHtml(result.extractMode === 'playwright' ? '浏览器渲染' : '直接获取') + '</div>' +
      '<div><strong>图片数量:</strong> ' + (result.imageCount || 0) + ' 张</div>' +
      '<div><strong>输出目录:</strong> ' + escapeHtml(result.outputDir || '-') + '</div>' +
      '<div><strong>Markdown 文件:</strong> ' + escapeHtml(result.markdownPath || '-') + '</div>';

    openDirBtn.disabled = false;
    openMdBtn.disabled = false;

    openDirBtn.onclick = function () {
      fetch('/api/open-output-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'path=' + encodeURIComponent(result.outputDir || ''),
      }).catch(function () { showToast('打开目录失败'); });
    };

    openMdBtn.onclick = function () {
      fetch('/api/open-output-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'path=' + encodeURIComponent(result.markdownPath || ''),
      }).catch(function () { showToast('打开文件失败'); });
    };
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  function loadTaskList() {
    fetch('/api/tasks?kind=web_archive')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success || !data.tasks || data.tasks.length === 0) {
          taskEmpty.hidden = false;
          return;
        }
        taskEmpty.hidden = true;
        taskList.innerHTML = '';
        data.tasks.forEach(function (task) {
          var item = document.createElement('div');
          item.className = 'web-archive-task-item';
          item.setAttribute('data-task-id', task.id);
          item.innerHTML =
            '<span class="task-title">' + escapeHtml(task.title) + '</span>' +
            '<span class="task-stage">' + escapeHtml(task.stage || '') + '</span>' +
            '<span class="task-status ' + task.status + '">' + statusLabel(task.status) + '</span>';
          taskList.appendChild(item);
        });
      })
      .catch(function () {});
  }

  loadTaskList();
})();