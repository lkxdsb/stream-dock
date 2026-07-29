(function () {
  const lists = Array.from(document.querySelectorAll('[data-health-list]'));
  const buttons = Array.from(document.querySelectorAll('[data-health-refresh]'));
  if (!lists.length) return;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function currentOutputPath() {
    return document.getElementById('settingsOutputPath')?.value
      || document.getElementById('convertDefaultOutputPath')?.value
      || document.getElementById('outputPath')?.value
      || document.getElementById('convertOutputPath')?.value
      || '~/Downloads/StreamDock';
  }

  function render(checks) {
    const html = (checks || []).map((item) => `
      <div class="system-health-item is-${escapeHtml(item.status || 'missing')}">
        <strong>${escapeHtml(item.name)} · ${item.required ? '必需' : '可选'}</strong>
        <span>${escapeHtml(item.detail)}</span>
      </div>
    `).join('');
    lists.forEach((list) => { list.innerHTML = html || '<div class="system-health-item"><span>暂无检查结果</span></div>'; });
  }

  async function refresh() {
    buttons.forEach((button) => { button.disabled = true; button.textContent = '检查中...'; });
    try {
      const response = await fetch(`/api/health?outputPath=${encodeURIComponent(currentOutputPath())}`);
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '环境检查失败');
      render(data.checks);
    } catch (error) {
      render([{ name: '环境检查', status: 'error', detail: error.message || '本地服务暂时不可用' }]);
    } finally {
      buttons.forEach((button) => { button.disabled = false; button.textContent = '重新检查'; });
    }
  }

  buttons.forEach((button) => button.addEventListener('click', refresh));
  refresh();
})();
