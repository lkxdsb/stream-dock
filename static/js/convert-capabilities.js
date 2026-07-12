(function () {
  const matrix = document.getElementById('convertCapabilityMatrix');
  const filterButtons = Array.from(document.querySelectorAll('[data-convert-filter]'));
  const typeButtons = Array.from(document.querySelectorAll('[data-convert-type]'));
  const description = document.getElementById('convertWorkspaceDescription');
  const orbitTotal = document.getElementById('convertOrbitTotal');
  const orbitTitle = document.getElementById('convertOrbitTitle');
  const orbitText = document.getElementById('convertOrbitText');
  const orbitRoutes = document.getElementById('convertOrbitRoutes');
  const worldCloud = document.getElementById('convertWorldCloud');
  const worldCanvas = document.getElementById('convertWorldCanvas');
  const worldPopover = document.getElementById('convertWorldPopover');
  const worldSearchInput = document.getElementById('convertWorldSearchInput');
  const ctx = worldCanvas?.getContext('2d');
  let capabilities = [];
  let particles = [];
  let activeFilter = 'all';
  let activeType = 'all';
  let activeQuery = '';
  let selectedCapability = null;
  let hoveredCapability = null;
  let canvasWidth = 0;
  let canvasHeight = 0;
  let animationStarted = false;
  let visibleKeySet = new Set();
  let isWorldVisible = true;
  let isDocumentVisible = true;
  let isScrolling = false;
  let scrollTimer = null;
  let lastFrameAt = 0;
  const frameInterval = 1000 / 20;

  const typeMeta = {
    all: {
      title: '全部转换路径',
      text: '这是 StreamDock 当前登记的完整转换世界。点击任何动态节点，可以查看具体源格式、目标格式和执行策略。',
      description: '展示所有已登记转换能力；本地能力会直接执行，复杂高保真路径会推荐专业工具。',
      color: '#2f6fed',
    },
    document: {
      title: 'Document routes',
      text: '文档、Office、电子书和结构化表格转换，适合格式明确、结构可解析的文件。',
      description: '聚焦文档、Office、电子书和结构化表格转换；PDF 高保真转换暂不作为本地重点。',
      color: '#2f6fed',
    },
    image: {
      title: 'Image routes',
      text: '图片、图标和矢量图基础转换，适合 PNG、JPG、WEBP、BMP、TIFF、ICO 等常见格式。',
      description: '聚焦图片与矢量图转换；透明背景转 JPG 会自动使用白底。',
      color: '#26b48b',
    },
    media: {
      title: 'Media routes',
      text: '音频、视频容器、音轨提取和 GIF 导出，依赖本机 ffmpeg。',
      description: '聚焦音频、视频容器和常见转码；依赖本机 ffmpeg。',
      color: '#ff7a2f',
    },
    subtitle: {
      title: 'Subtitle routes',
      text: '字幕与歌词时间轴转换，复杂字幕样式会降级为文本。',
      description: '聚焦字幕和歌词时间轴转换，复杂样式会降级为文本。',
      color: '#9567f6',
    },
    archive: {
      title: 'Archive routes',
      text: '压缩包转换、解压与文件夹打包，第一版不处理加密压缩包。',
      description: '聚焦压缩包解压和重新打包；第一版不处理加密压缩包。',
      color: '#20b8c7',
    },
  };

  function capabilityType(item) {
    const category = item.category || '';
    if (['数据表格', '轻文档', 'Office 基础', '电子书'].includes(category)) return 'document';
    if (['图片', '矢量图文档'].includes(category)) return 'image';
    if (['音频', '视频'].includes(category)) return 'media';
    if (category === '字幕') return 'subtitle';
    if (category === '压缩包') return 'archive';
    return 'document';
  }

  function levelLabel(level) {
    if (level === 'stable') return '稳定';
    if (level === 'basic') return '基础';
    return '推荐';
  }

  function matchesActiveFilters(item) {
    const levelMatches = activeFilter === 'all' || item.level === activeFilter;
    const typeMatches = activeType === 'all' || capabilityType(item) === activeType;
    const query = activeQuery.trim().toLowerCase();
    const queryMatches = !query || [item.source, item.target, item.category, item.engine, item.description].join(' ').toLowerCase().includes(query);
    return levelMatches && typeMatches && queryMatches;
  }

  function groupByCategory(items) {
    return items.reduce((acc, item) => {
      acc[item.category] = acc[item.category] || [];
      acc[item.category].push(item);
      return acc;
    }, {});
  }

  function hexToRgba(hex, alpha) {
    const value = hex.replace('#', '');
    const bigint = parseInt(value, 16);
    const r = (bigint >> 16) & 255;
    const g = (bigint >> 8) & 255;
    const b = bigint & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function syncActiveButtons() {
    filterButtons.forEach((item) => item.classList.toggle('active', (item.dataset.convertFilter || 'all') === activeFilter));
    typeButtons.forEach((item) => item.classList.toggle('active', (item.dataset.convertType || 'all') === activeType));
  }

  function sampleRoutes(items) {
    const list = items.length ? items : capabilities.filter((item) => activeType === 'all' || capabilityType(item) === activeType);
    return list.slice(0, 6).map((item) => `
      <span class="convert-orbit-route" data-level="${item.level}">
        ${item.source.toUpperCase()} → ${item.target.toUpperCase()} · ${levelLabel(item.level)}
      </span>
    `).join('') || '<span class="convert-orbit-route">暂无匹配路径</span>';
  }

  function renderWorldDetail(filtered) {
    const meta = typeMeta[activeType] || typeMeta.all;
    if (description) description.textContent = meta.description;

    if (selectedCapability && matchesActiveFilters(selectedCapability)) {
      if (orbitTitle) orbitTitle.textContent = `${selectedCapability.source.toUpperCase()} → ${selectedCapability.target.toUpperCase()}`;
      if (orbitText) orbitText.textContent = `${selectedCapability.category} · ${levelLabel(selectedCapability.level)} · ${selectedCapability.description || '已登记转换路径。'}`;
      if (orbitRoutes) {
        orbitRoutes.innerHTML = `
          <span class="convert-orbit-route" data-level="${selectedCapability.level}">${selectedCapability.engine || 'local'}</span>
          <span class="convert-orbit-route" data-level="${selectedCapability.level}">${selectedCapability.notes || '可在当前策略下处理'}</span>
        `;
      }
      return;
    }

    selectedCapability = null;
    if (orbitTitle) orbitTitle.textContent = meta.title;
    if (orbitText) orbitText.textContent = meta.text;
    if (orbitRoutes) orbitRoutes.innerHTML = sampleRoutes(filtered);
  }

  function dotPosition(index, total) {
    const golden = Math.PI * (3 - Math.sqrt(5));
    const radius = Math.sqrt((index + 0.5) / Math.max(total, 1));
    const angle = index * golden;
    return { radius, angle };
  }

  function buildParticles() {
    // 控制节点数与刷新率，保留动态效果但不抢占页面滚动帧。
    const max = Math.min(capabilities.length, 140);
    particles = capabilities.slice(0, max).map((item, index) => {
      const type = capabilityType(item);
      const pos = dotPosition(index, max);
      return {
        item,
        type,
        color: typeMeta[type].color,
        radius: pos.radius,
        angle: pos.angle,
        phase: index * 0.71,
        speed: 0.00005 + (index % 9) * 0.000006,
        orbit: 0.62 + (index % 7) * 0.04,
        size: item.level === 'vendor' ? 4.8 : item.level === 'basic' ? 4.1 : 3.6,
        x: 0,
        y: 0,
      };
    });
  }

  function resizeCanvas() {
    if (!worldCanvas || !worldCloud || !ctx) return;
    const rect = worldCloud.getBoundingClientRect();
    const dpr = 1;
    const nextWidth = Math.max(1, Math.floor(rect.width));
    const nextHeight = Math.max(1, Math.floor(rect.height));
    if (nextWidth === canvasWidth && nextHeight === canvasHeight) return;
    canvasWidth = nextWidth;
    canvasHeight = nextHeight;
    worldCanvas.width = Math.floor(nextWidth * dpr);
    worldCanvas.height = Math.floor(nextHeight * dpr);
    worldCanvas.style.width = `${nextWidth}px`;
    worldCanvas.style.height = `${nextHeight}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function particlePoint(particle, time) {
    const minSide = Math.min(canvasWidth, canvasHeight);
    const cloudRadius = minSide * 0.46;
    const swirl = time * particle.speed;
    const angle = particle.angle + swirl + Math.sin(time * 0.00028 + particle.phase) * 0.08;
    const radius = cloudRadius * particle.radius * particle.orbit + Math.sin(time * 0.0011 + particle.phase) * 9;
    const x = canvasWidth / 2 + Math.cos(angle) * radius + Math.sin(time * 0.0007 + particle.phase) * 7;
    const y = canvasHeight / 2 + Math.sin(angle) * radius * 0.86 + Math.cos(time * 0.0006 + particle.phase) * 7;
    particle.x = x;
    particle.y = y;
    return { x, y };
  }

  function drawRoundRect(x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  function drawParticleLabel(particle) {
    const text = `${particle.item.source.toUpperCase()} → ${particle.item.target.toUpperCase()}`;
    ctx.save();
    ctx.font = '700 12px system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
    const metrics = ctx.measureText(text);
    const width = metrics.width + 24;
    const height = 28;
    const x = Math.min(canvasWidth - width - 10, particle.x + 14);
    const y = Math.max(10, particle.y - height / 2);
    ctx.shadowColor = 'rgba(0,0,0,.18)';
    ctx.shadowBlur = 16;
    ctx.fillStyle = 'rgba(20,20,20,.90)';
    drawRoundRect(x, y, width, height, 10);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#fff';
    ctx.fillText(text, x + 12, y + 18);
    ctx.restore();
  }

  function drawCanvas(time) {
    if (!ctx || !worldCanvas) return;
    resizeCanvas();
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    const hoveredKey = hoveredCapability?.key;
    const selectedKey = selectedCapability?.key;

    particles.forEach((particle) => {
      const point = particlePoint(particle, time);
      const visible = visibleKeySet.has(particle.item.key);
      const selected = selectedKey === particle.item.key;
      const hovered = hoveredKey === particle.item.key;
      const pulse = Math.sin(time * 0.003 + particle.phase) * 0.55;
      const size = particle.size + pulse + (hovered || selected ? 5 : visible ? 1 : 0);
      const alpha = selected ? .95 : hovered ? .88 : visible ? .58 : .055;

      ctx.beginPath();
      ctx.fillStyle = hexToRgba(particle.color, Math.max(.035, alpha));
      ctx.arc(point.x, point.y, Math.max(1.4, size), 0, Math.PI * 2);
      ctx.fill();

      if (selected || hovered) {
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        ctx.beginPath();
        ctx.fillStyle = hexToRgba(particle.color, .14);
        ctx.arc(point.x, point.y, size + 15, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.lineWidth = 2;
        ctx.strokeStyle = hexToRgba(particle.color, .82);
        ctx.arc(point.x, point.y, size + 8, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    });

    const labelParticle = particles.find((particle) => particle.item.key === (hoveredKey || selectedKey));
    if (labelParticle) drawParticleLabel(labelParticle);
  }

  function animate(time) {
    if (!animationStarted) return;
    const now = time || 0;
    if (isDocumentVisible && isWorldVisible && !isScrolling && now - lastFrameAt >= frameInterval) {
      drawCanvas(now);
      lastFrameAt = now;
    }
    requestAnimationFrame(animate);
  }

  function startAnimation() {
    if (animationStarted || !ctx) return;
    animationStarted = true;
    resizeCanvas();
    requestAnimationFrame(animate);
  }

  function nearestParticle(event) {
    if (!worldCanvas || !particles.length) return null;
    const rect = worldCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest = null;
    let nearestDistance = Infinity;
    particles.forEach((particle) => {
      const visible = matchesActiveFilters(particle.item);
      if (!visible) return;
      const dx = particle.x - x;
      const dy = particle.y - y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = particle;
      }
    });
    return nearestDistance <= 22 ? nearest : null;
  }

  function bindCanvasEvents() {
    if (!worldCanvas) return;
    worldCanvas.addEventListener('mousemove', (event) => {
      const nearest = nearestParticle(event);
      hoveredCapability = nearest?.item || null;
      worldCanvas.style.cursor = hoveredCapability ? 'pointer' : 'default';
    });
    worldCanvas.addEventListener('mouseleave', () => {
      hoveredCapability = null;
      worldCanvas.style.cursor = 'default';
    });
    worldCanvas.addEventListener('click', (event) => {
      const nearest = nearestParticle(event);
      if (!nearest) return;
      selectedCapability = nearest.item;
      activeType = nearest.type;
      render();
    });
    window.addEventListener('resize', () => {
      resizeCanvas();
      drawCanvas(performance.now());
    });

    window.addEventListener('scroll', () => {
      isScrolling = true;
      window.clearTimeout(scrollTimer);
      scrollTimer = window.setTimeout(() => {
        isScrolling = false;
        drawCanvas(performance.now());
      }, 160);
    }, { passive: true });

    document.addEventListener('visibilitychange', () => {
      isDocumentVisible = !document.hidden;
      if (isDocumentVisible) drawCanvas(performance.now());
    });

    if ('IntersectionObserver' in window && worldCloud) {
      const observer = new IntersectionObserver((entries) => {
        isWorldVisible = entries[0]?.isIntersecting ?? true;
        if (isWorldVisible) drawCanvas(performance.now());
      }, { threshold: 0.05 });
      observer.observe(worldCloud);
    }
  }

  function renderMatrix(filtered) {
    if (!matrix) return;
    const grouped = groupByCategory(filtered);
    matrix.innerHTML = Object.entries(grouped).map(([category, items]) => `
      <section class="convert-group">
        <h3>${category}<span>${items.length} 条路径</span></h3>
        <div class="convert-flow-list">
          ${items.map((item) => `
            <button class="convert-flow-card" type="button" data-capability-key="${item.key}" data-level="${item.level}" data-type="${capabilityType(item)}" title="${item.description || ''}">
              <span class="flow-source">${item.source.toUpperCase()}</span>
              <i aria-hidden="true"></i>
              <span class="flow-target">${item.target.toUpperCase()}</span>
              <em>${levelLabel(item.level)}</em>
            </button>
          `).join('')}
        </div>
      </section>
    `).join('') || '<div class="convert-card convert-empty-state">暂无匹配能力</div>';

    matrix.querySelectorAll('[data-capability-key]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedCapability = capabilities.find((item) => item.key === button.dataset.capabilityKey) || null;
        render();
        worldPopover?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

  function render() {
    const filtered = capabilities.filter(matchesActiveFilters);
    visibleKeySet = new Set(filtered.map((item) => item.key));
    renderWorldDetail(filtered);
    syncActiveButtons();
    renderMatrix(filtered);
    window.StreamDockConvertActiveFilters = { level: activeFilter, type: activeType, query: activeQuery };
    window.dispatchEvent(new CustomEvent('streamdock:convert-filter-change', { detail: window.StreamDockConvertActiveFilters }));
    drawCanvas(performance.now());
  }

  function setCount(name, value) {
    document.querySelectorAll(`[data-count-for="${name}"]`).forEach((node) => {
      node.textContent = String(value);
    });
  }

  function updateCounts() {
    const byType = (type) => capabilities.filter((item) => capabilityType(item) === type).length;
    const total = capabilities.length;
    if (orbitTotal) orbitTotal.textContent = String(total.toLocaleString());
    setCount('all', total);
    setCount('stable', capabilities.filter((item) => item.level === 'stable').length);
    setCount('basic', capabilities.filter((item) => item.level === 'basic').length);
    setCount('vendor', capabilities.filter((item) => item.level === 'vendor').length);
    setCount('type-all', total);
    ['document', 'image', 'media', 'subtitle', 'archive'].forEach((type) => {
      setCount(type, byType(type));
      setCount(`orbit-${type}`, byType(type));
    });
  }

  filterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.convertFilter || 'all';
      selectedCapability = null;
      render();
    });
  });

  typeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeType = button.dataset.convertType || 'all';
      selectedCapability = null;
      render();
    });
  });

  worldSearchInput?.addEventListener('input', () => {
    activeQuery = worldSearchInput.value || '';
    selectedCapability = null;
    render();
  });

  fetch('/api/convert/capabilities')
    .then((res) => res.json())
    .then((data) => {
      capabilities = data.capabilities || [];
      window.StreamDockConvertCapabilities = capabilities;
      window.StreamDockConvertCapabilityType = capabilityType;
      window.StreamDockConvertFilterOptions = (items) => (items || []).filter(matchesActiveFilters);
      buildParticles();
      bindCanvasEvents();
      updateCounts();
      render();
      startAnimation();
    })
    .catch(() => {
      if (matrix) matrix.innerHTML = '<div class="convert-card convert-empty-state">能力矩阵加载失败</div>';
    });
})();
