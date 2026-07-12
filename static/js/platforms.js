(function () {
  const matrix = document.getElementById('platformMatrix');
  const detail = document.getElementById('platformDetail');
  const categoryButtons = Array.from(document.querySelectorAll('[data-platform-category]'));

  if (!matrix || !detail || categoryButtons.length === 0) {
    return;
  }

  const iconVersion = '20260708-icons1';

  const platforms = {
    domestic: [
      {
        name: '抖音', iconSrc: '/static/icons/platforms/svg/douyin.svg', level: '稳定', type: '短视频', quality: '自动优选可达最高画质',
        badges: ['视频', '音频', '浏览器登录态'],
        summary: '优先结构化解析分享链接，必要时读取本机浏览器登录态，以当前账号可访问的视频源为准。',
        strategy: '分享链接规范化 → 视频页探测 → 可用流筛选 → ffmpeg 输出',
        limit: '画质上限取决于平台返回源和账号权限。',
      },
      {
        name: 'B站', iconSrc: '/static/icons/platforms/svg/bilibili.svg', level: '稳定', type: '长视频 / 番剧外内容', quality: '支持识别多档清晰度',
        badges: ['视频', '音频', '画质选择', 'Cookie 可选'],
        summary: '调用播放信息提取视频与音频流，自动合并输出；本机登录或手动 Cookie 可提升可用清晰度。',
        strategy: 'BV/AV 链接识别 → playurl 信息 → 音视频分离流合并',
        limit: '未登录、非会员或版权限制内容会降低可选画质。',
      },
      {
        name: '快手', iconSrc: '/static/icons/platforms/svg/kuaishou.svg', level: '稳定', type: '短视频', quality: '自动选择候选视频源',
        badges: ['视频', '音频', 'HLS 合流'],
        summary: '从移动端初始化数据和候选播放地址提取媒体源，HLS 内容走本地 ffmpeg 合流。',
        strategy: '移动端页面 → 初始化状态 → 播放地址候选 → 本地下载',
        limit: '部分直播、私密或过期分享不可解析。',
      },
      {
        name: '小红书', iconSrc: '/static/icons/platforms/svg/xiaohongshu.svg', level: '部分', type: '视频 / 图文', quality: '按页面返回源识别',
        badges: ['视频识别', '图文识别', '浏览器回退'],
        summary: '先读取页面结构化数据，识别图文与视频类型；结构化失败时回退浏览器抓取。',
        strategy: '分享页 → 页面状态 → 类型判断 → 视频源或图片集合',
        limit: '平台经常调整页面结构，部分内容需要浏览器回退。',
      },
      {
        name: '微博', iconSrc: '/static/icons/platforms/svg/weibo.svg', level: '部分', type: '视频动态', quality: '按变体源识别',
        badges: ['视频', '浏览器回退'],
        summary: '从微博页面数据中提取视频变体，失败时回退浏览器抓取当前播放源。',
        strategy: '微博链接 → 页面数据 → 视频变体 → 下载',
        limit: '登录可见、作者限制或已删除内容不可稳定获取。',
      },
      {
        name: '视频号', iconSrc: '/static/icons/platforms/svg/channels.svg', level: '受限', type: '微信分享', quality: '以预览接口返回为准',
        badges: ['分享链接', '预览接口', '浏览器回退'],
        summary: '面向微信视频号分享链接做预览接口解析；网页端能力有限时给出明确失败原因。',
        strategy: '短链/分享链 → 预览接口 → 视频地址候选 → 回退探测',
        limit: '没有完整网页端，复制入口不同会影响可解析信息。',
      },
    ],
    overseas: [
      {
        name: 'YouTube', iconSrc: '/static/icons/platforms/svg/youtube.svg', level: '实验', type: '公开视频', quality: '自动优选可用格式',
        badges: ['视频', '音频', '格式列表'],
        summary: '预留海外公开视频解析链路，重点处理格式列表、音视频合流和本地导出。',
        strategy: '公开视频链接 → 格式枚举 → 最高可达格式 → 输出',
        limit: '地区、年龄、登录与版权限制会影响结果。',
      },
      {
        name: 'TikTok', iconSrc: '/static/icons/platforms/svg/tiktok-color.svg', level: '实验', type: '短视频', quality: '按页面候选源识别',
        badges: ['视频', '浏览器回退'],
        summary: '以公开分享页为入口，优先读取页面候选视频源，必要时使用浏览器播放态回退。',
        strategy: '分享链接 → 页面状态 → 视频候选源 → 下载',
        limit: '区域限制和反自动化变动会导致稳定性波动。',
      },
      {
        name: 'X / Twitter', iconSrc: '/static/icons/platforms/svg/x.svg', level: '实验', type: '社交视频', quality: '视频变体选择',
        badges: ['视频变体', '浏览器回退'],
        summary: '面向公开推文视频做变体识别，按码率选择可用下载源。',
        strategy: '推文链接 → 视频变体 → 码率排序 → 下载',
        limit: '登录可见、敏感内容或作者限制内容不保证可用。',
      },
    ],
    experimental: [
      {
        name: '浏览器回退', iconSrc: '', level: '能力', type: '通用兜底', quality: '跟随实际播放源',
        badges: ['Playwright', '网络监听', '播放态'],
        summary: '结构化接口不可用时，打开本机浏览器上下文观察实际播放请求，提升复杂页面覆盖率。',
        strategy: '打开页面 → 监听媒体请求 → 过滤视频/音频流 → 下载',
        limit: '速度更慢，且仍受账号权限和页面播放状态影响。',
      },
      {
        name: '登录态增强', iconSrc: '', level: '能力', type: '账号权限', quality: '账号可达上限',
        badges: ['本机 Cookie', '手动 Cookie', '权限继承'],
        summary: '优先读取本机浏览器登录态；在别人的机器无法读取时，可在特定平台手动补充 Cookie。',
        strategy: '本机浏览器状态 → 平台请求 → 可用清晰度提升',
        limit: '不会突破账号本身权限，会员或地区限制仍由平台决定。',
      },
      {
        name: '清晰度策略', iconSrc: '', level: '能力', type: '画质选择', quality: '默认最高，必要时手动',
        badges: ['自动优选', '多档识别', '受限说明'],
        summary: '默认选择当前可达最高画质；当平台返回多档信息时，支持展示和手动选择。',
        strategy: '候选流收集 → 清晰度排序 → 最高优先 → 输出提示',
        limit: '平台只返回低清源时，工具不会凭空生成高清源。',
      },
    ],
  };

  let currentCategory = 'domestic';
  let currentIndex = 0;
  let runtimeStatuses = {};

  const platformKeys = {
    '抖音': 'douyin', 'B站': 'bilibili', '快手': 'kuaishou', '小红书': 'xiaohongshu',
    '微博': 'weibo', '视频号': 'channels', 'YouTube': 'youtube', 'TikTok': 'tiktok', 'X / Twitter': 'twitter_x',
  };

  function runtimeLabel(item) {
    const status = runtimeStatuses[platformKeys[item.name]];
    if (!status) return item.level;
    if (status.runtimeStatus === 'verified') return '最近验证';
    if (status.runtimeStatus === 'failed') return '最近失败';
    return item.level;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[char]));
  }

  function renderPlatformIcon(item) {
    const src = String(item.iconSrc || '').trim();
    if (!src) {
      return '<span class="platform-logo platform-logo-empty" aria-hidden="true"></span>';
    }
    const separator = src.includes('?') ? '&' : '?';
    const versionedSrc = `${src}${separator}v=${iconVersion}`;
    return `<span class="platform-logo" aria-hidden="true"><img class="platform-logo-img" src="${escapeHtml(versionedSrc)}" alt="" loading="lazy" decoding="async" /></span>`;
  }

  function renderMatrix() {
    const rows = platforms[currentCategory] || [];
    matrix.innerHTML = rows.map((item, index) => `
      <button class="matrix-row ${index === currentIndex ? 'active' : ''}" type="button" data-platform-index="${index}">
        <span class="platform-name">
          ${renderPlatformIcon(item)}
          <span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.type)}</small></span>
        </span>
        <span class="platform-badges">${item.badges.map((badge) => `<span class="platform-badge">${escapeHtml(badge)}</span>`).join('')}</span>
        <span class="platform-quality">${escapeHtml(item.quality)}</span>
        <span class="platform-status">${escapeHtml(runtimeLabel(item))}</span>
      </button>
    `).join('');

    matrix.querySelectorAll('[data-platform-index]').forEach((row) => {
      row.addEventListener('click', () => {
        currentIndex = Number(row.getAttribute('data-platform-index') || 0);
        renderMatrix();
        renderDetail();
        window.requestAnimationFrame(() => {
          detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      });
    });
  }

  function renderDetail() {
    const item = (platforms[currentCategory] || [])[currentIndex];
    if (!item) {
      detail.innerHTML = '<div class="detail-empty">当前分类暂无平台。</div>';
      return;
    }

    detail.innerHTML = `
      <div class="detail-grid">
        <div>
          <h3 class="detail-title">${escapeHtml(item.name)}</h3>
          <p class="detail-summary">${escapeHtml(item.summary)}</p>
        </div>
        <ul class="detail-list">
          <li><span>解析策略</span><strong>${escapeHtml(item.strategy)}</strong></li>
          <li><span>画质策略</span><strong>${escapeHtml(item.quality)}</strong></li>
          <li><span>当前状态</span><strong>${escapeHtml(runtimeLabel(item))}</strong></li>
          ${runtimeStatuses[platformKeys[item.name]]?.lastCheckedAt ? `<li><span>最近运行</span><strong>${escapeHtml(new Date(runtimeStatuses[platformKeys[item.name]].lastCheckedAt).toLocaleString('zh-CN'))}</strong></li>` : ''}
          <li><span>限制说明</span><strong>${escapeHtml(item.limit)}</strong></li>
        </ul>
      </div>
    `;
  }

  categoryButtons.forEach((button) => {
    button.addEventListener('click', () => {
      currentCategory = button.getAttribute('data-platform-category') || 'domestic';
      currentIndex = 0;
      categoryButtons.forEach((candidate) => candidate.classList.toggle('active', candidate === button));
      renderMatrix();
      renderDetail();
    });
  });

  renderMatrix();
  renderDetail();

  fetch('/api/platform-status').then((response) => response.json()).then((data) => {
    if (!data.success) return;
    runtimeStatuses = Object.fromEntries((data.platforms || []).map((item) => [item.platform, item]));
    renderMatrix();
    renderDetail();
  }).catch(() => {});
})();
