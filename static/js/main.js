(function () {
  const toast = document.getElementById('toast');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

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
    window.setTimeout(() => {
      window.location.href = targetUrl.href;
    }, 380);
  }

  function goUsePage() {
    navigateWithTransition('/use');
  }

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
        return;
      }
      event.preventDefault();
      navigateWithTransition(href);
    });
  });

  document.getElementById('githubBtn')?.addEventListener('click', (event) => {
    const repositoryUrl = event.currentTarget?.dataset?.repositoryUrl;
    if (!repositoryUrl) {
      showToast('项目仓库尚未配置');
      return;
    }
    window.open(repositoryUrl, '_blank', 'noopener,noreferrer');
  });

  document.getElementById('topDownloadBtn')?.addEventListener('click', goUsePage);
  document.getElementById('mainDownloadBtn')?.addEventListener('click', goUsePage);
  document.getElementById('learnMoreBtn')?.addEventListener('click', () => {
    if (!scrollToTarget('platforms')) {
      window.location.href = '/#platforms';
    }
  });

  window.StreamDockUI = {
    showToast,
    scrollToTarget,
    prefersReducedMotion,
    goUsePage,
    navigateWithTransition,
  };
})();
