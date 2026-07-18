(function () {
  const toast = document.getElementById('toast');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobileMenuToggle = document.getElementById('mobileMenuToggle');
  const mobileNavPanel = document.getElementById('mobileNavPanel');


  function setMobileMenu(open) {
    if (!mobileMenuToggle || !mobileNavPanel) return;
    mobileNavPanel.hidden = !open;
    mobileMenuToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.classList.toggle('is-mobile-menu-open', open);
  }
  const deferredActionKey = 'streamdock.deferredAction.v1';

  function performPageAction(action) {
    if (!action) return false;
    if (action.openAdvanced) {
      const advanced = document.querySelector('.advanced-options');
      if (!advanced) return false;
      advanced.open = true;
      advanced.scrollIntoView({ behavior: prefersReducedMotion.matches ? 'auto' : 'smooth', block: 'center' });
      return true;
    }
    if (action.click) {
      const target = document.querySelector(action.click);
      if (!target) return false;
      target.click();
    }
    if (action.focus) {
      const target = document.querySelector(action.focus);
      if (!target) return false;
      target.focus({ preventScroll: true });
      target.scrollIntoView({ behavior: prefersReducedMotion.matches ? 'auto' : 'smooth', block: 'center' });
      return true;
    }
    if (action.scroll) {
      const target = document.querySelector(action.scroll);
      if (!target) return false;
      target.scrollIntoView({ behavior: prefersReducedMotion.matches ? 'auto' : 'smooth', block: action.block || 'center' });
      return true;
    }
    return true;
  }

  function runDeferredPageAction() {
    let payload = null;
    try { payload = JSON.parse(window.sessionStorage.getItem(deferredActionKey) || 'null'); }
    catch (_error) { payload = null; }
    if (!payload?.route || payload.route !== `${window.location.pathname}${window.location.hash}`) return;
    let attempts = 0;
    const attempt = () => {
      attempts += 1;
      activateWorkspaceTarget(payload.route);
      if (performPageAction(payload.action) || attempts >= 12) {
        window.sessionStorage.removeItem(deferredActionKey);
        return;
      }
      window.setTimeout(attempt, 120);
    };
    attempt();
  }

  function schedulePageAction(route, action) {
    window.sessionStorage.setItem(deferredActionKey, JSON.stringify({ route, action }));
    const targetUrl = new URL(route, window.location.href);
    if (targetUrl.pathname === window.location.pathname) {
      window.history.pushState(null, '', `${targetUrl.pathname}${targetUrl.hash}`);
      runDeferredPageAction();
      return;
    }
    navigateWithTransition(`${targetUrl.pathname}${targetUrl.hash}`);
  }


  function showToast(message) {
    if (!toast) {
      return;
    }
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(window.__streamdockToastTimer);
    window.__streamdockToastTimer = window.setTimeout(() => {
      toast.classList.remove('show');
    }, 1800);
  }

  function scrollToTarget(targetId) {
    const target = document.getElementById(targetId);
    if (!target) {
      return false;
    }
    target.scrollIntoView({
      behavior: prefersReducedMotion.matches ? 'auto' : 'smooth',
      block: 'start',
    });
    return true;
  }

  function isSamePageUrl(url) {
    return url.pathname === window.location.pathname && url.search === window.location.search;
  }

  function navigateWithTransition(href) {
    const targetUrl = new URL(href, window.location.href);
    if (targetUrl.origin !== window.location.origin || isSamePageUrl(targetUrl) || prefersReducedMotion.matches) {
      window.location.href = targetUrl.href;
      return;
    }

    document.body.classList.add('is-page-transitioning');
    document.body.classList.add('is-page-leaving');
    window.clearTimeout(window.__streamdockNavigationTimer);
    window.__streamdockNavigationTimer = window.setTimeout(() => {
      window.location.href = targetUrl.href;
    }, 380);
  }

  function activateWorkspaceTarget(path) {
    const targetUrl = new URL(path, window.location.href);
    const route = `${targetUrl.pathname}${targetUrl.hash}`;
    const rules = {
      '/convert#workbench': '[data-convert-nav="workbench"]',
      '/convert#tasks': '[data-convert-nav="tasks"]',
      '/convert#matrix': '[data-convert-nav="matrix"]',
      '/convert#tools': '[data-convert-nav="tools"]',
      '/convert#settings': '[data-convert-nav="settings"]',
      '/pdf#workbench': '[data-pdf-tab="workbench"]',
      '/pdf#tasks': '[data-pdf-tab="tasks"]',
      '/pdf#results': '[data-pdf-tab="results"]',
      '/use#parse': '[data-use-tab="parse"]',
      '/use#downloading': '[data-use-tab="downloading"]',
      '/use#completed': '[data-use-tab="completed"]',
      '/use#settings': '[data-use-tab="settings"]',
    };
    const trigger = document.querySelector(rules[route]);
    if (!trigger) return false;
    trigger.click();
    return true;
  }

  function applyCurrentHashTarget() {
    if (!window.location.hash) return false;
    return activateWorkspaceTarget(`${window.location.pathname}${window.location.hash}`);
  }

  function goPrimaryAction(path = '/use') {
    const targetUrl = new URL(path, window.location.href);
    if (targetUrl.pathname === window.location.pathname && activateWorkspaceTarget(`${targetUrl.pathname}${targetUrl.hash}`)) {
      return;
    }
    navigateWithTransition(`${targetUrl.pathname}${targetUrl.hash}`);
  }

  function goUsePage() {
    goPrimaryAction('/use');
  }

  function clearTransitionState() {
    document.body.classList.remove('is-page-transitioning', 'is-page-leaving');
  }

  clearTransitionState();
  window.addEventListener('pageshow', () => {
    clearTransitionState();
    window.setTimeout(() => { applyCurrentHashTarget(); runDeferredPageAction(); }, 0);
  });
  window.addEventListener('pagehide', () => {
    window.clearTimeout(window.__streamdockNavigationTimer);
  });

  document.querySelectorAll('[data-scroll-target]').forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      const targetId = trigger.getAttribute('data-scroll-target');
      if (!targetId) {
        return;
      }
      if (scrollToTarget(targetId)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll('[data-transition-link]').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.defaultPrevented) {
        return;
      }
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#')) {
        return;
      }
      const targetUrl = new URL(href, window.location.href);
      if (targetUrl.pathname === window.location.pathname && targetUrl.hash) {
        event.preventDefault();
        window.history.pushState(null, '', `${targetUrl.pathname}${targetUrl.hash}`);
        activateWorkspaceTarget(`${targetUrl.pathname}${targetUrl.hash}`);
        setMobileMenu(false);
        return;
      }
      event.preventDefault();
      navigateWithTransition(href);
    });
  });

  mobileMenuToggle?.addEventListener('click', () => {
    setMobileMenu(mobileNavPanel?.hidden !== false);
  });

  document.querySelectorAll('[data-mobile-menu-close]').forEach((button) => {
    button.addEventListener('click', () => setMobileMenu(false));
  });

  mobileNavPanel?.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => setMobileMenu(false));
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMobileMenu(false);
  });

  window.addEventListener('hashchange', () => { applyCurrentHashTarget(); runDeferredPageAction(); });
  window.setTimeout(() => { applyCurrentHashTarget(); runDeferredPageAction(); }, 0);

  document.getElementById('githubBtn')?.addEventListener('click', (event) => {
    const repositoryUrl = event.currentTarget?.dataset?.repositoryUrl;
    if (!repositoryUrl) {
      showToast('项目仓库尚未配置');
      return;
    }
    window.open(repositoryUrl, '_blank', 'noopener,noreferrer');
  });

  document.getElementById('topDownloadBtn')?.addEventListener('click', (event) => {
    goPrimaryAction(event.currentTarget?.dataset?.primaryAction || '/use');
  });
  document.getElementById('mainDownloadBtn')?.addEventListener('click', goUsePage);
  document.getElementById('learnMoreBtn')?.addEventListener('click', () => {
    navigateWithTransition('/about');
  });

  window.StreamDockUI = {
    showToast,
    scrollToTarget,
    prefersReducedMotion,
    goUsePage,
    goPrimaryAction,
    navigateWithTransition,
    activateWorkspaceTarget,
    applyCurrentHashTarget,
    schedulePageAction,
    setMobileMenu,
  };
})();
