(function () {
  const navItems = Array.from(document.querySelectorAll('[data-convert-nav]'));
  const panels = Array.from(document.querySelectorAll('[data-convert-panel]'));

  function activate(name) {
    navItems.forEach((item) => item.classList.toggle('active', item.dataset.convertNav === name));
    panels.forEach((panel) => panel.classList.toggle('active', panel.dataset.convertPanel === name));
  }

  navItems.forEach((item) => {
    item.addEventListener('click', () => activate(item.dataset.convertNav || 'workbench'));
  });
})();
