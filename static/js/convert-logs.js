(function () {
  const logOutput = document.getElementById('convertLogOutput');
  window.StreamDockConvertLogs = {
    set(lines) {
      if (!logOutput) return;
      const value = Array.isArray(lines) ? lines.join('\n') : String(lines || '');
      logOutput.textContent = value || '等待执行...';
    },
    append(line) {
      if (!logOutput) return;
      logOutput.textContent = `${logOutput.textContent || ''}\n${line}`.trim();
    },
  };
})();
