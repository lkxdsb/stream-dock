(function () {
  const resultBox = document.getElementById('convertResultBox');
  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }
  function resultRows(rows) {
    return (rows || []).map((row) => `
      <div class="convert-result-row ${row.success ? 'success' : 'error'}">
        <strong>${escapeHtml(row.filename)}</strong>
        <span>${escapeHtml((row.source || '').toUpperCase())} → ${escapeHtml((row.target || '').toUpperCase())}</span>
        ${row.outputPath ? `<code>${escapeHtml(row.outputPath)}</code>${row.validation?.valid ? `<span>校验通过${row.validation.sizeLabel ? ` · ${escapeHtml(row.validation.sizeLabel)}` : ''}</span>` : ''}` : `<span>${escapeHtml(row.error || '转换失败')}</span>`}
      </div>
    `).join('');
  }
  window.StreamDockConvertResult = {
    waiting() {
      if (!resultBox) return;
      resultBox.innerHTML = '<strong>等待转换任务</strong><span>选择文件后，这里会显示输出文件或专业工具建议。</span>';
    },
    success(data) {
      if (!resultBox) return;
      const path = typeof data === 'string' ? data : data?.outputPath;
      const validation = typeof data === 'object' ? data?.validation : null;
      resultBox.innerHTML = `<strong>转换完成${validation?.valid ? ' · 校验通过' : ''}</strong><span>输出文件：${escapeHtml(path)}</span>${validation?.sizeLabel ? `<span>文件大小：${escapeHtml(validation.sizeLabel)}</span>` : ''}`;
    },
    batch(data) {
      if (!resultBox) return;
      resultBox.innerHTML = `
        <strong>批量转换完成</strong>
        <span>${escapeHtml(data.successCount)} 个成功，${escapeHtml(data.failedCount)} 个失败，共 ${escapeHtml(data.total)} 个文件。</span>
        <div class="convert-result-list">${resultRows(data.results || [])}</div>
      `;
    },
    error(message, vendors) {
      if (!resultBox) return;
      const vendorText = Array.isArray(vendors) && vendors.length ? `<span>推荐工具：${vendors.map(escapeHtml).join(' / ')}</span>` : '';
      resultBox.innerHTML = `<strong>转换未完成</strong><span>${escapeHtml(message)}</span>${vendorText}`;
    },
  };
})();
