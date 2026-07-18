(function () {
  const navItems = Array.from(document.querySelectorAll('[data-convert-nav]'));
  const panels = Array.from(document.querySelectorAll('[data-convert-panel]'));

  const allowed = new Set(navItems.map((item) => item.dataset.convertNav));

  function activate(name) {
    const target = allowed.has(name) ? name : 'workbench';
    navItems.forEach((item) => item.classList.toggle('active', item.dataset.convertNav === target));
    panels.forEach((panel) => {
      const active = panel.dataset.convertPanel === target;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    window.localStorage.setItem('streamdock.convert.activePanel.v1', target);
  }

  navItems.forEach((item) => {
    item.addEventListener('click', () => activate(item.dataset.convertNav || 'workbench'));
  });

  const initialHash = window.location.hash.replace('#', '');
  activate(allowed.has(initialHash) ? initialHash : (window.localStorage.getItem('streamdock.convert.activePanel.v1') || 'workbench'));
  window.StreamDockConvertTabs = { activate };
})();
