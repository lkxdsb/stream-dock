(function () {
  const logOutput = document.getElementById('logOutput');

  function renderLogs(parts) {
    if (!logOutput) {
      return;
    }
    const lines = Array.isArray(parts) ? parts.filter(Boolean) : [];
    logOutput.textContent = lines.length ? lines.join('\n\n').trim() : '等待执行...';
  }

  window.StreamDockLogs = {
    renderLogs,
  };
})();
