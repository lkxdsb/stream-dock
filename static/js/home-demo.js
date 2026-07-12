(function () {
  const linkEl = document.getElementById('demoLinkText');
  const platformEl = document.getElementById('demoPlatformText');
  const qualityEl = document.getElementById('demoQualityText');
  const resultEl = document.getElementById('demoResultText');
  const statusEl = document.getElementById('demoStatusText');
  const badgeEl = document.getElementById('demoBadge');
  const dots = Array.from(document.querySelectorAll('.demo-progress-dot'));
  const startBtn = document.getElementById('demoStartBtn');

  if (!linkEl || !platformEl || !qualityEl || !resultEl || !statusEl || !badgeEl) {
    return;
  }

  const scenes = [
    {
      link: 'https://v.douyin.com/TWm6SYebkao/',
      platform: '抖音',
      quality: '1080P · 自动最优',
      result: '检测到无水印视频流',
      status: '复制分享文案，自动抽取核心链接并识别清晰度。',
      badge: '✓ 已识别',
      step: 0,
    },
    {
      link: 'https://www.bilibili.com/video/BV1xxxxxxx',
      platform: 'B站',
      quality: '1080P · 登录态可达',
      result: '识别视频流与音频流，准备合流输出',
      status: '如果本机有登录态，会自动按权限选择当前最高画质。',
      badge: '⌛ 下载中',
      step: 1,
    },
    {
      link: 'https://www.kuaishou.com/short-video/3x4xxxx',
      platform: '快手',
      quality: '720P · 直链',
      result: '输出到 ~/Downloads/StreamDock',
      status: '真实解析、日志与结果展示都在“在线使用”页面完成。',
      badge: '✓ 已保存',
      step: 2,
    },
  ];

  let index = 0;

  function render(scene) {
    linkEl.textContent = scene.link;
    platformEl.textContent = scene.platform;
    qualityEl.textContent = scene.quality;
    resultEl.textContent = scene.result;
    statusEl.textContent = scene.status;
    badgeEl.textContent = scene.badge;
    dots.forEach((dot, dotIndex) => {
      dot.classList.toggle('active', dotIndex === scene.step);
    });
  }

  render(scenes[index]);
  window.setInterval(() => {
    index = (index + 1) % scenes.length;
    render(scenes[index]);
  }, 2400);


  const flowArea = document.querySelector('.flow-area');
  const flowNodes = Array.from(document.querySelectorAll('.app-node[data-flow]'));
  const flowClassNames = flowNodes.map((node) => `flow-hover-${node.dataset.flow}`);

  function clearFlowHover() {
    if (!flowArea) return;
    flowArea.classList.remove('has-flow-hover', ...flowClassNames);
    flowNodes.forEach((node) => node.classList.remove('is-hovered'));
  }

  function setFlowHover(node) {
    if (!flowArea || !node?.dataset?.flow) return;
    clearFlowHover();
    flowArea.classList.add('has-flow-hover', `flow-hover-${node.dataset.flow}`);
    node.classList.add('is-hovered');
  }

  flowNodes.forEach((node) => {
    node.addEventListener('mouseenter', () => setFlowHover(node));
    node.addEventListener('mouseleave', clearFlowHover);
    node.addEventListener('focus', () => setFlowHover(node));
    node.addEventListener('blur', clearFlowHover);
  });

  startBtn?.addEventListener('click', () => {
    window.location.href = '/use';
  });
})();
