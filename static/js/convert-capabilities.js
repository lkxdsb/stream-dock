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
  const detailSource = document.getElementById('convertDetailSource');
  const detailTarget = document.getElementById('convertDetailTarget');
  const detailSourceLabel = document.getElementById('convertDetailSourceLabel');
  const detailTargetLabel = document.getElementById('convertDetailTargetLabel');
  const detailRouteCount = document.getElementById('convertDetailRouteCount');
  const detailLocalCount = document.getElementById('convertDetailLocalCount');
  const detailFormatCount = document.getElementById('convertDetailFormatCount');
  const exploreWorldRoutes = document.querySelector('[data-explore-world-routes]');
  const ctx = worldCanvas?.getContext('2d');
  let capabilities = [];
  let particles = [];
  let routeEdges = [];
  let worldTextureDots = [];
  let worldMapShapes = [];
  let worldLandDots = [];
  let selectedFormat = null;
  let routePinned = false;
  let activeFilter = 'all';
  let activeType = 'all';
  let activeQuery = '';
  const focusTypes = ['document', 'image', 'media', 'subtitle', 'archive'];
  let focusWeightsFrom = null;
  let focusTransitionStartedAt = 0;
  const focusTransitionDuration = 620;
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
  let worldRotationX = -0.32;
  let worldRotationY = 0;
  let worldVelocityX = 0;
  let worldVelocityY = 0;
  let worldTargetRotationX = worldRotationX;
  let worldTargetRotationY = worldRotationY;
  let worldFocusRotating = false;
  let isDraggingWorld = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let dragMoved = false;
  let lastDragEndedAt = 0;
  let lastPointerX = 0;
  let lastPointerY = 0;
  const frameInterval = 0;

  const typeMeta = {
    all: {
      title: '全部转换路径',
      text: '默认展示全部格式节点和转换路径。点击节点或右侧路径后，再聚焦查看某条转换链路。',
      description: '展示所有已登记转换能力；本地能力会直接执行，复杂高保真路径会推荐专业工具。',
      color: '#5f7fae',
    },
    document: {
      title: 'Document routes',
      text: '文档、Office、电子书和结构化表格转换，适合格式明确、结构可解析的文件。',
      description: '聚焦文档、Office、电子书和结构化表格转换；PDF 高保真转换暂不作为本地重点。',
      color: '#5f7fae',
    },
    image: {
      title: 'Image routes',
      text: '图片、图标和矢量图基础转换，适合 PNG、JPG、WEBP、BMP、TIFF、ICO 等常见格式。',
      description: '聚焦图片与矢量图转换；透明背景转 JPG 会自动使用白底。',
      color: '#6faeb8',
    },
    media: {
      title: 'Media routes',
      text: '音频、视频容器、音轨提取和 GIF 导出，依赖本机 ffmpeg。',
      description: '聚焦音频、视频容器和常见转码；依赖本机 ffmpeg。',
      color: '#c58a62',
    },
    subtitle: {
      title: 'Subtitle routes',
      text: '字幕与歌词时间轴转换，复杂字幕样式会降级为文本。',
      description: '聚焦字幕和歌词时间轴转换，复杂样式会降级为文本。',
      color: '#9b84b8',
    },
    archive: {
      title: 'Archive routes',
      text: '压缩包转换、解压与文件夹打包，第一版不处理加密压缩包。',
      description: '聚焦压缩包解压和重新打包；第一版不处理加密压缩包。',
      color: '#8faf9a',
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
    if (level === 'stable') return '成熟引擎';
    if (level === 'basic') return '基础转换';
    return '专业工具';
  }

  function verificationLabel(item) {
    if (item.verification === 'verified') return '样例已验证';
    if (item.verification === 'engine') return '引擎可用';
    if (item.verification === 'best-effort') return '可能有损';
    return '外部能力';
  }

  function matchesActiveFilters(item) {
    const levelMatches = activeFilter === 'all' || item.level === activeFilter;
    const typeMatches = activeType === 'all' || capabilityType(item) === activeType;
    const query = activeQuery.trim().toLowerCase();
    const queryMatches = !query || [item.source, item.target, item.category, item.engine, item.description].join(' ').toLowerCase().includes(query);
    return levelMatches && typeMatches && queryMatches;
  }

  function matchesCanvasFilters(item) {
    const levelMatches = activeFilter === 'all' || item.level === activeFilter;
    const query = activeQuery.trim().toLowerCase();
    const queryMatches = !query || [item.source, item.target, item.category, item.engine, item.description].join(' ').toLowerCase().includes(query);
    return levelMatches && queryMatches;
  }

  function focusWeightForState(type, state) {
    if (state === 'all') return 1;
    return type === state ? 1 : 0.12;
  }

  function easeFocusProgress(value) {
    const t = clamp(value, 0, 1);
    return t * t * (3 - 2 * t);
  }

  function typeFocusWeight(type, time = performance.now()) {
    if (!focusWeightsFrom) return focusWeightForState(type, activeType);
    const progress = easeFocusProgress((time - focusTransitionStartedAt) / focusTransitionDuration);
    if (progress >= 1) {
      focusWeightsFrom = null;
      return focusWeightForState(type, activeType);
    }
    const from = focusWeightsFrom[type] ?? focusWeightForState(type, activeType);
    const to = focusWeightForState(type, activeType);
    return from + (to - from) * progress;
  }

  function normalizeAngle(value) {
    let angle = value;
    while (angle > Math.PI) angle -= Math.PI * 2;
    while (angle < -Math.PI) angle += Math.PI * 2;
    return angle;
  }

  function setRotationTargetFromVector(vector) {
    if (!vector) return;
    const y = Math.atan2(-vector.sx, vector.sz || 0.0001);
    const zAfterY = -vector.sx * Math.sin(y) + vector.sz * Math.cos(y);
    const x = Math.atan2(vector.sy, zAfterY || 0.0001);
    worldTargetRotationY = worldRotationY + normalizeAngle(y - worldRotationY);
    worldTargetRotationX = worldRotationX + normalizeAngle(x - worldRotationX);
    worldVelocityX = 0;
    worldVelocityY = 0;
    worldFocusRotating = true;
  }

  function focusVectorForType(type) {
    if (type === 'all' || !particles.length) return { sx: 0, sy: 0.34, sz: 1 };
    const selected = particles.filter((particle) => particle.type === type);
    if (!selected.length) return null;
    const vector = selected.reduce((acc, particle) => {
      const weight = 1 + Math.min(8, particle.item.weight || 1);
      acc.sx += particle.sx * weight;
      acc.sy += particle.sy * weight;
      acc.sz += particle.sz * weight;
      acc.weight += weight;
      return acc;
    }, { sx: 0, sy: 0, sz: 0, weight: 0 });
    const length = Math.hypot(vector.sx, vector.sy, vector.sz);
    if (length < 0.12) {
      const strongest = selected.slice().sort((a, b) => (b.item.weight || 0) - (a.item.weight || 0))[0];
      return strongest ? { sx: strongest.sx, sy: strongest.sy, sz: strongest.sz } : null;
    }
    return { sx: vector.sx / length, sy: vector.sy / length, sz: vector.sz / length };
  }

  function focusVectorForRoute(route) {
    if (!route || !particles.length) return null;
    const source = particles.find((particle) => particle.item.key === route.source);
    const target = particles.find((particle) => particle.item.key === route.target);
    if (!source && !target) return null;
    if (!source) return { sx: target.sx, sy: target.sy, sz: target.sz };
    if (!target) return { sx: source.sx, sy: source.sy, sz: source.sz };
    const sx = source.sx + target.sx;
    const sy = source.sy + target.sy;
    const sz = source.sz + target.sz;
    const length = Math.hypot(sx, sy, sz);
    if (length < 0.08) return { sx: source.sx, sy: source.sy, sz: source.sz };
    return { sx: sx / length, sy: sy / length, sz: sz / length };
  }

  function focusWorldOnType(type) {
    setRotationTargetFromVector(focusVectorForType(type));
  }

  function setActiveType(nextType, options = {}) {
    const normalizedType = nextType || 'all';
    if (normalizedType === activeType && !options.forceRotate) return false;
    const now = performance.now();
    focusWeightsFrom = focusTypes.reduce((acc, type) => {
      acc[type] = typeFocusWeight(type, now);
      return acc;
    }, {});
    focusTransitionStartedAt = now;
    activeType = normalizedType;
    if (options.route) setRotationTargetFromVector(focusVectorForRoute(options.route));
    else focusWorldOnType(normalizedType);
    return true;
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

  function animateWorldDetailChange() {
    if (!worldPopover) return;
    worldPopover.classList.remove('is-updating');
    void worldPopover.offsetWidth;
    worldPopover.classList.add('is-updating');
    window.setTimeout(() => worldPopover.classList.remove('is-updating'), 220);
  }

  function updateWorldSelection() {
    const filtered = capabilities.filter(matchesActiveFilters);
    visibleKeySet = new Set(filtered.map((item) => item.key));
    renderWorldDetail(filtered);
    renderMatrix(filtered);
    syncActiveButtons();
    animateWorldDetailChange();
    window.StreamDockConvertActiveFilters = { level: activeFilter, type: activeType, query: activeQuery };
    window.dispatchEvent(new CustomEvent('streamdock:convert-filter-change', { detail: window.StreamDockConvertActiveFilters }));
    drawCanvas(performance.now());
  }

  function sampleRoutes(items) {
    const list = items.length ? items : capabilities.filter((item) => activeType === 'all' || capabilityType(item) === activeType);
    return list.slice(0, 6).map((item) => `
      <button class="convert-orbit-route" type="button" data-route-key="${item.key}" data-level="${item.level}">
        ${item.source.toUpperCase()} → ${item.target.toUpperCase()} · ${verificationLabel(item)}
      </button>
    `).join('') || '<span class="convert-orbit-route">暂无匹配路径</span>';
  }


  function bindRouteButtons() {
    orbitRoutes?.querySelectorAll('[data-route-key]').forEach((button) => {
      button.addEventListener('click', () => {
        const route = capabilities.find((item) => item.key === button.dataset.routeKey);
        selectRoute(route);
      });
    });
  }

  function formatsForRoutes(items) {
    const formats = new Set();
    items.forEach((item) => {
      formats.add(item.source);
      formats.add(item.target);
    });
    return formats;
  }

  function renderWorldSummary(filtered) {
    const route = selectedCapability && matchesActiveFilters(selectedCapability) ? selectedCapability : null;
    const formats = formatsForRoutes(filtered);
    if (detailRouteCount) detailRouteCount.textContent = String(filtered.length);
    if (detailLocalCount) detailLocalCount.textContent = String(filtered.filter((item) => item.level !== 'vendor').length);
    if (detailFormatCount) detailFormatCount.textContent = String(formats.size);

    if (route) {
      if (detailSource) detailSource.textContent = route.source.toUpperCase();
      if (detailTarget) detailTarget.textContent = route.target.toUpperCase();
      if (detailSourceLabel) detailSourceLabel.textContent = '输入';
      if (detailTargetLabel) detailTargetLabel.textContent = '输出';
      return;
    }

    const typeName = activeType === 'all' ? 'ALL' : activeType.slice(0, 4).toUpperCase();
    if (detailSource) detailSource.textContent = typeName;
    if (detailTarget) detailTarget.textContent = String(filtered.length);
    if (detailSourceLabel) detailSourceLabel.textContent = activeType === 'all' ? '全部格式' : '当前类型';
    if (detailTargetLabel) detailTargetLabel.textContent = '条路径';
  }

  function renderWorldDetail(filtered) {
    const meta = typeMeta[activeType] || typeMeta.all;
    if (description) description.textContent = meta.description;
    renderWorldSummary(filtered);

    if (selectedCapability && matchesActiveFilters(selectedCapability)) {
      if (orbitTitle) orbitTitle.textContent = `${selectedCapability.source.toUpperCase()} → ${selectedCapability.target.toUpperCase()}`;
      if (orbitText) orbitText.textContent = `${selectedCapability.category} · ${levelLabel(selectedCapability.level)} · ${selectedCapability.description || '已登记转换路径。'}`;
      if (orbitRoutes) {
        const related = filtered.filter((item) => item.key !== selectedCapability.key && (item.source === selectedCapability.source || item.target === selectedCapability.source || item.source === selectedCapability.target || item.target === selectedCapability.target)).slice(0, 4);
        orbitRoutes.innerHTML = `
          <span class="convert-orbit-route" data-level="${selectedCapability.level}">${selectedCapability.engine || 'local'}</span>
          <span class="convert-orbit-route" data-level="${selectedCapability.level}">${selectedCapability.notes || '可在当前策略下处理'}</span>
          ${related.map((item) => `<button class="convert-orbit-route" type="button" data-route-key="${item.key}" data-level="${item.level}">${item.source.toUpperCase()} → ${item.target.toUpperCase()}</button>`).join('')}
        `;
        bindRouteButtons();
      }
      return;
    }

    selectedCapability = null;
    if (orbitTitle) orbitTitle.textContent = meta.title;
    if (orbitText) orbitText.textContent = meta.text;
    if (selectedFormat) {
      const routes = filtered.filter((item) => item.source === selectedFormat || item.target === selectedFormat);
      if (routes.length) {
        if (orbitTitle) orbitTitle.textContent = `${selectedFormat.toUpperCase()} 相关路径`;
        if (orbitText) orbitText.textContent = '点击下方路径，球体会高亮对应源格式、目标格式和转换连线。';
        if (orbitRoutes) orbitRoutes.innerHTML = sampleRoutes(routes);
        bindRouteButtons();
        return;
      }
    }
    if (orbitRoutes) {
      orbitRoutes.innerHTML = sampleRoutes(filtered);
      bindRouteButtons();
    }
  }

  function dotPosition(index, total) {
    const golden = Math.PI * (3 - Math.sqrt(5));
    const radius = Math.sqrt((index + 0.5) / Math.max(total, 1));
    const angle = index * golden;
    return { radius, angle };
  }

  function buildParticles() {
    const formats = new Map();
    capabilities.forEach((item) => {
      const type = capabilityType(item);
      [item.source, item.target].forEach((format) => {
        if (!format) return;
        const key = format.toLowerCase();
        if (!formats.has(key)) {
          formats.set(key, { key, format: key, type, routes: [], weight: 0 });
        }
        const node = formats.get(key);
        node.routes.push(item);
        node.weight += 1;
        if (item.level !== 'vendor') node.type = type;
      });
    });

    const nodes = Array.from(formats.values()).slice(0, 96);
    const total = nodes.length;
    particles = nodes.map((node, index) => {
      const golden = Math.PI * (3 - Math.sqrt(5));
      const y = 1 - (index / Math.max(total - 1, 1)) * 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = index * golden;
      return {
        item: node,
        type: node.type,
        color: typeMeta[node.type].color,
        sx: Math.cos(theta) * radius,
        sy: y,
        sz: Math.sin(theta) * radius,
        phase: index * 0.71,
        size: Math.min(7.2, 3.8 + Math.sqrt(node.weight) * 0.52),
        x: 0,
        y: 0,
        z: 0,
        scale: 1,
        visibleRoutes: [],
      };
    });

    const nodeByFormat = new Map(particles.map((particle) => [particle.item.key, particle]));
    routeEdges = capabilities.map((item, index) => ({
      index,
      item,
      source: nodeByFormat.get(item.source),
      target: nodeByFormat.get(item.target),
      type: capabilityType(item),
    })).filter((edge) => edge.source && edge.target);
    buildWorldTexture();
    buildWorldMapShapes();
  }



  function lonLatPoint(lon, lat) {
    const lambda = lon * Math.PI / 180;
    const phi = lat * Math.PI / 180;
    const cosPhi = Math.cos(phi);
    return {
      sx: Math.sin(lambda) * cosPhi,
      sy: -Math.sin(phi),
      sz: Math.cos(lambda) * cosPhi,
    };
  }

  function buildWorldMapShapes() {
    const landRings = Array.isArray(window.STREAMDOCK_WORLD_LAND)
      ? window.STREAMDOCK_WORLD_LAND
      : [];
    worldMapShapes = landRings
      .filter((coordinates) => Array.isArray(coordinates) && coordinates.length >= 4)
      .map((coordinates, index) => {
        const lons = coordinates.map((point) => point[0]);
        const lats = coordinates.map((point) => point[1]);
        const longitudeSpan = Math.max(...lons) - Math.min(...lons);
        const latitudeSpan = Math.max(...lats) - Math.min(...lats);
        const areaHint = Math.max(1, longitudeSpan * latitudeSpan);
        return {
          name: `natural-earth-land-${index}`,
          weight: clamp(0.72 + Math.log10(areaHint) * 0.13, 0.72, 1.18),
          areaHint,
          coordinates,
          points: coordinates.map(([lon, lat]) => lonLatPoint(lon, lat)),
        };
      })
      // Antarctica is intentionally omitted from this decorative product globe:
      // keeping the lower hemisphere open makes the six familiar inhabited
      // continents immediately readable at this scale.
      .filter((shape) => shape.coordinates.reduce((sum, point) => sum + point[1], 0) / shape.coordinates.length > -62);
    buildWorldLandDots();
  }

  function deterministicNoise(seed) {
    const value = Math.sin(seed * 12.9898) * 43758.5453123;
    return value - Math.floor(value);
  }

  function isPointInPolygon(lon, lat, coordinates) {
    let inside = false;
    for (let i = 0, j = coordinates.length - 1; i < coordinates.length; j = i, i += 1) {
      const xi = coordinates[i][0];
      const yi = coordinates[i][1];
      const xj = coordinates[j][0];
      const yj = coordinates[j][1];
      const intersects = ((yi > lat) !== (yj > lat))
        && (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || 0.0001) + xi);
      if (intersects) inside = !inside;
    }
    return inside;
  }

  function buildWorldLandDots() {
    worldLandDots = [];
    worldMapShapes.forEach((shape, shapeIndex) => {
      const coordinates = shape.coordinates || [];
      if (coordinates.length < 3) return;
      const lons = coordinates.map((point) => point[0]);
      const lats = coordinates.map((point) => point[1]);
      const minLon = Math.floor(Math.min(...lons) - 1);
      const maxLon = Math.ceil(Math.max(...lons) + 1);
      const minLat = Math.floor(Math.min(...lats) - 1);
      const maxLat = Math.ceil(Math.max(...lats) + 1);
      const step = shape.areaHint > 500 ? 1.7 : shape.areaHint > 80 ? 2.0 : 2.35;
      for (let lat = minLat; lat <= maxLat; lat += step) {
        for (let lon = minLon; lon <= maxLon; lon += step) {
          if (!isPointInPolygon(lon, lat, coordinates)) continue;
          const seed = (shapeIndex + 1) * 100000 + Math.round((lon + 180) * 10) * 97 + Math.round((lat + 90) * 10) * 37;
          const noiseA = deterministicNoise(seed);
          const noiseB = deterministicNoise(seed + 17);
          const jitterLon = lon + (noiseA - 0.5) * 0.72;
          const jitterLat = lat + (noiseB - 0.5) * 0.72;
          const point = lonLatPoint(jitterLon, jitterLat);
          worldLandDots.push({
            sx: point.sx,
            sy: point.sy,
            sz: point.sz,
            size: 0.42 + noiseA * 0.43 + Math.max(0, (shape.weight || 1) - 1) * 0.1,
            alpha: 0.09 + noiseB * 0.065 + Math.max(0, (shape.weight || 1) - 1) * 0.025,
          });
        }
      }
    });
  }

  function buildWorldTexture() {
    worldTextureDots = [];
    const count = 260;
    for (let index = 0; index < count; index += 1) {
      const band = index % 5;
      const longitude = ((index * 137.508) % 360) * Math.PI / 180;
      const latitudeBase = Math.sin(index * 12.9898) * 0.62;
      const latitude = latitudeBase + (band - 2) * 0.055;
      const cluster = 0.72 + ((index * 17) % 11) * 0.018;
      const r = Math.sqrt(Math.max(0, 1 - latitude * latitude)) * cluster;
      worldTextureDots.push({
        sx: Math.cos(longitude) * r,
        sy: latitude * cluster,
        sz: Math.sin(longitude) * r,
        size: 0.9 + (index % 4) * 0.42,
        alpha: 0.035 + (index % 7) * 0.012,
      });
    }
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function projectSpherePoint(x, y, z, radiusScale = 1) {
    const minSide = Math.min(canvasWidth, canvasHeight);
    const sphereRadius = minSide * 0.43 * radiusScale;
    const cosY = Math.cos(worldRotationY);
    const sinY = Math.sin(worldRotationY);
    const cosX = Math.cos(worldRotationX);
    const sinX = Math.sin(worldRotationX);
    const x1 = x * cosY + z * sinY;
    const z1 = -x * sinY + z * cosY;
    const y1 = y * cosX - z1 * sinX;
    const z2 = y * sinX + z1 * cosX;
    const depth = 2.85;
    const scale = depth / (depth - z2 * 0.72);
    return {
      x: canvasWidth / 2 + x1 * sphereRadius * scale,
      y: canvasHeight / 2 + y1 * sphereRadius * 0.9 * scale,
      z: z2,
      scale,
      radius: sphereRadius,
    };
  }

  function resizeCanvas() {
    if (!worldCanvas || !worldCloud || !ctx) return;
    const rect = worldCloud.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
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

  function particlePoint(particle) {
    const point = projectSpherePoint(particle.sx, particle.sy, particle.sz);
    particle.x = point.x;
    particle.y = point.y;
    particle.z = point.z;
    particle.scale = point.scale;
    return point;
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
    const activeRoute = selectedCapability && (selectedCapability.source === particle.item.key || selectedCapability.target === particle.item.key) ? selectedCapability : particle.item.routes[0];
    const text = activeRoute ? `${activeRoute.source.toUpperCase()} → ${activeRoute.target.toUpperCase()}` : particle.item.format.toUpperCase();
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

  function boxesOverlap(a, b, padding = 3) {
    return !(a.right + padding < b.left || a.left - padding > b.right || a.bottom + padding < b.top || a.top - padding > b.bottom);
  }

  function drawFormatLabel(particle, active, typeFocused, placedBoxes) {
    const text = particle.item.format.toUpperCase();
    const size = particle.renderSize || particle.size;
    ctx.save();
    ctx.font = `${active ? 800 : 720} ${active ? 12 : 9.5}px system-ui, -apple-system, BlinkMacSystemFont, sans-serif`;
    const textWidth = ctx.measureText(text).width;
    const halfWidth = textWidth / 2;
    const gap = active ? 11 : 9;
    const candidates = [
      { x: particle.x, y: particle.y + size + gap },
      { x: particle.x, y: particle.y - size - gap },
      { x: particle.x + size + halfWidth + 6, y: particle.y },
      { x: particle.x - size - halfWidth - 6, y: particle.y },
      { x: particle.x + halfWidth * 0.55, y: particle.y + size + gap },
      { x: particle.x - halfWidth * 0.55, y: particle.y - size - gap },
    ];
    const makeBox = (candidate) => ({
      left: candidate.x - halfWidth,
      right: candidate.x + halfWidth,
      top: candidate.y - 6,
      bottom: candidate.y + 6,
    });
    let chosen = candidates.find((candidate) => {
      const box = makeBox(candidate);
      const insideCanvas = box.left >= 5 && box.right <= canvasWidth - 5 && box.top >= 5 && box.bottom <= canvasHeight - 5;
      return insideCanvas && !placedBoxes.some((placed) => boxesOverlap(box, placed));
    }) || candidates[0];
    const chosenBox = makeBox(chosen);
    placedBoxes.push(chosenBox);
    ctx.fillStyle = active || typeFocused ? 'rgba(53,60,69,.88)' : 'rgba(72,81,94,.70)';
    ctx.strokeStyle = 'rgba(255,255,255,.82)';
    ctx.lineWidth = active ? 3.6 : 3;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.strokeText(text, chosen.x, chosen.y);
    ctx.fillText(text, chosen.x, chosen.y);
    ctx.restore();
  }

  function routeMatchesActive(route) {
    return matchesActiveFilters(route);
  }

  function isRouteHighlighted(route) {
    if (selectedCapability?.key === route.key || hoveredCapability?.key === route.key) return true;
    if (selectedFormat && (route.source === selectedFormat || route.target === selectedFormat)) return true;
    return false;
  }


  function drawWorldMapLayer(radius) {
    if (!worldMapShapes.length) return;
    const cx = canvasWidth / 2;
    const cy = canvasHeight / 2;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.985, 0, Math.PI * 2);
    ctx.clip();

    // 1) A restrained land wash gives the accurate coastline a readable body.
    // Only polygons mostly facing the camera are filled, preventing far-side
    // geometry from folding across the globe.
    worldMapShapes.forEach((shape) => {
      const points = shape.points.map((point) => projectSpherePoint(point.sx, point.sy, point.sz, 0.952));
      const avgZ = points.reduce((sum, point) => sum + point.z, 0) / Math.max(points.length, 1);
      const visibleRatio = points.filter((point) => point.z > 0.02).length / Math.max(points.length, 1);
      if (avgZ < 0.08 || visibleRatio < 0.74) return;
      const front = clamp((avgZ - 0.02) / 0.98, 0, 1);
      ctx.beginPath();
      points.forEach((point, pointIndex) => {
        if (pointIndex === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.closePath();
      ctx.fillStyle = `rgba(78,98,121,${(0.018 + front * 0.032) * (shape.weight || 1)})`;
      ctx.fill();
    });

    // 2) Dotted continent texture, matching the reference image: the land mass
    // is perceived through dense halftone points instead of solid dark blocks.
    worldLandDots.forEach((dot) => {
      const point = projectSpherePoint(dot.sx, dot.sy, dot.sz, 0.956);
      if (point.z < -0.05) return;
      const front = clamp((point.z + 0.05) / 1.05, 0, 1);
      const alpha = dot.alpha * (0.5 + front * 1.15);
      ctx.beginPath();
      ctx.fillStyle = `rgba(63,82,105,${alpha})`;
      ctx.arc(point.x, point.y, dot.size * point.scale * (0.72 + front * 0.72), 0, Math.PI * 2);
      ctx.fill();
    });

    // 3) Draw only visible coastline segments. This keeps the real Natural
    // Earth silhouettes crisp while the hidden hemisphere remains clean.
    worldMapShapes.forEach((shape) => {
      const points = shape.points.map((point) => projectSpherePoint(point.sx, point.sy, point.sz, 0.958));
      let hasVisibleSegment = false;
      ctx.beginPath();
      points.forEach((point, pointIndex) => {
        const previous = points[pointIndex - 1];
        const visible = point.z > -0.025;
        const previousVisible = previous && previous.z > -0.025;
        if (!visible) return;
        if (!previousVisible) ctx.moveTo(point.x, point.y);
        else {
          ctx.lineTo(point.x, point.y);
          hasVisibleSegment = true;
        }
      });
      if (!hasVisibleSegment) return;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.strokeStyle = `rgba(55,75,98,${0.18 * (shape.weight || 1)})`;
      ctx.lineWidth = 0.9;
      ctx.stroke();
      ctx.strokeStyle = 'rgba(255,255,255,.12)';
      ctx.lineWidth = 0.42;
      ctx.stroke();
    });

    // A few faint latitude seams keep the map attached to the globe.
    ctx.globalCompositeOperation = 'multiply';
    ctx.strokeStyle = 'rgba(95,127,174,.038)';
    ctx.lineWidth = 0.68;
    [-45, -20, 0, 20, 45].forEach((lat) => {
      const samples = [];
      for (let lon = -175; lon <= 180; lon += 10) samples.push(lonLatPoint(lon, lat));
      const points = samples.map((point) => projectSpherePoint(point.sx, point.sy, point.sz, 0.948)).filter((point) => point.z > -0.025);
      if (points.length < 2) return;
      ctx.beginPath();
      points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
    });
    ctx.restore();
  }

  function drawWorldBackdrop(time) {
    const minSide = Math.min(canvasWidth, canvasHeight);
    const radius = minSide * 0.43;
    const cx = canvasWidth / 2;
    const cy = canvasHeight / 2;

    ctx.save();
    const glow = ctx.createRadialGradient(cx, cy, radius * 0.1, cx, cy, radius * 1.2);
    glow.addColorStop(0, 'rgba(255,255,255,.80)');
    glow.addColorStop(0.5, 'rgba(237,229,218,.24)');
    glow.addColorStop(1, 'rgba(95,127,174,.00)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 1.18, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = 'rgba(95,127,174,.16)';
    ctx.lineWidth = 1.05;
    for (let i = 0; i < 5; i += 1) {
      ctx.beginPath();
      ctx.ellipse(cx, cy, radius * (1.02 + i * 0.055), radius * (0.18 + i * 0.025), worldRotationY * 0.45 + i * 0.56, 0, Math.PI * 2);
      ctx.stroke();
    }

    const sphere = ctx.createRadialGradient(cx - radius * 0.22, cy - radius * 0.28, radius * 0.12, cx, cy, radius * 1.02);
    sphere.addColorStop(0, 'rgba(255,255,255,.68)');
    sphere.addColorStop(0.58, 'rgba(245,241,235,.40)');
    sphere.addColorStop(1, 'rgba(95,127,174,.10)');
    ctx.fillStyle = sphere;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(95,127,174,.12)';
    ctx.stroke();
    ctx.restore();

    drawWorldMapLayer(radius);

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.985, 0, Math.PI * 2);
    ctx.clip();
    worldTextureDots.forEach((dot) => {
      const point = projectSpherePoint(dot.sx, dot.sy, dot.sz, 0.99);
      if (point.z < -0.72) return;
      ctx.beginPath();
      ctx.fillStyle = `rgba(92,103,116,${dot.alpha * (point.z > 0 ? 1.45 : 0.7)})`;
      ctx.arc(point.x, point.y, dot.size * point.scale, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  function drawSphereGuides(time) {
    const minSide = Math.min(canvasWidth, canvasHeight);
    const radius = minSide * 0.43;
    const cx = canvasWidth / 2;
    const cy = canvasHeight / 2;
    ctx.save();
    ctx.strokeStyle = 'rgba(95,127,174,.14)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 6; i += 1) {
      const y = cy + (i - 2.5) * radius * 0.18;
      ctx.beginPath();
      ctx.ellipse(cx, y, radius * (0.94 - Math.abs(i - 2.5) * 0.08), radius * 0.14, Math.sin(worldRotationY) * 0.3, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let i = 0; i < 5; i += 1) {
      ctx.beginPath();
      ctx.ellipse(cx, cy, radius * (0.22 + i * 0.16), radius * 0.9, worldRotationY + i * 0.64, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawRoute(edge, highlighted, time) {
    const source = edge.source;
    const target = edge.target;
    const bothBack = source.z < -0.55 && target.z < -0.55;
    const focus = typeFocusWeight(edge.type, time);
    const alpha = highlighted ? 0.68 : (bothBack ? 0.045 : 0.13) * focus;
    const color = typeMeta[edge.type]?.color || typeMeta.all.color;
    const midX = (source.x + target.x) / 2 + Math.sin(time * 0.001 + source.phase) * 12;
    const midY = (source.y + target.y) / 2 - 18 * Math.max(source.scale, target.scale);
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.quadraticCurveTo(midX, midY, target.x, target.y);
    ctx.strokeStyle = hexToRgba(color, alpha);
    ctx.lineWidth = highlighted ? 1.75 : 0.9;
    ctx.stroke();

    if (highlighted) {
      const t = (time * 0.0007 + source.phase) % 1;
      const x = (1 - t) * (1 - t) * source.x + 2 * (1 - t) * t * midX + t * t * target.x;
      const y = (1 - t) * (1 - t) * source.y + 2 * (1 - t) * t * midY + t * t * target.y;
      ctx.globalCompositeOperation = 'lighter';
      ctx.beginPath();
      ctx.fillStyle = hexToRgba(color, 0.38);
      ctx.arc(x, y, 3.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawCanvas(time) {
    if (!ctx || !worldCanvas) return;
    resizeCanvas();
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    particles.forEach((particle) => particlePoint(particle));
    drawWorldBackdrop(time);
    drawSphereGuides(time);

    const filteredRoutes = capabilities.filter(matchesCanvasFilters).slice(0, 160);

    const routeSet = new Set(filteredRoutes.map((item) => item.key));
    routeEdges.forEach((edge) => {
      if (!routeSet.has(edge.item.key)) return;
      drawRoute(edge, isRouteHighlighted(edge.item), time);
    });

    const activeFormatSet = new Set();
    if (selectedCapability) {
      activeFormatSet.add(selectedCapability.source);
      activeFormatSet.add(selectedCapability.target);
    }
    if (hoveredCapability) {
      activeFormatSet.add(hoveredCapability.source);
      activeFormatSet.add(hoveredCapability.target);
    }
    if (selectedFormat) activeFormatSet.add(selectedFormat);

    const visibleFormatSet = new Set();
    filteredRoutes.forEach((item) => {
      visibleFormatSet.add(item.source);
      visibleFormatSet.add(item.target);
    });

    const sortedParticles = particles.slice().sort((a, b) => a.z - b.z);
    sortedParticles.forEach((particle) => {
      const visible = visibleFormatSet.has(particle.item.key);
      const active = activeFormatSet.has(particle.item.key);
      const front = particle.z > -0.35;
      const pulse = Math.sin(time * 0.0025 + particle.phase) * 0.35;
      const focus = typeFocusWeight(particle.type, time);
      const typeFocused = activeType !== 'all' && particle.type === activeType;
      const size = (particle.size + pulse + (active ? 4.4 : 0) + (typeFocused ? 1.2 : 0)) * particle.scale * 1.2;
      particle.renderSize = size;
      const alpha = active ? .92 : typeFocused && visible && front ? .8 : visible && front ? .66 * focus : visible ? .16 * focus : .035;
      ctx.beginPath();
      ctx.fillStyle = hexToRgba(particle.color, alpha);
      ctx.arc(particle.x, particle.y, Math.max(1.4, size), 0, Math.PI * 2);
      ctx.fill();

      if (active || (typeFocused && front)) {
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        ctx.beginPath();
        ctx.fillStyle = hexToRgba(particle.color, active ? .12 : .055);
        ctx.arc(particle.x, particle.y, size + (active ? 13 : 8), 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.lineWidth = active ? 1.4 : 1;
        ctx.strokeStyle = hexToRgba(particle.color, active ? .45 : .25);
        ctx.arc(particle.x, particle.y, size + (active ? 6 : 4), 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

    });

    // Naming rule: all front-facing nodes in the current view are labelled.
    // During type focus, labels from other groups disappear with their nodes.
    const placedLabelBoxes = [];
    sortedParticles
      .filter((particle) => {
        const visible = visibleFormatSet.has(particle.item.key);
        const active = activeFormatSet.has(particle.item.key);
        const typeFocused = activeType !== 'all' && particle.type === activeType;
        return active || (visible && particle.z > 0.015 && (activeType === 'all' || typeFocused));
      })
      .sort((a, b) => {
        const activeDifference = Number(activeFormatSet.has(b.item.key)) - Number(activeFormatSet.has(a.item.key));
        if (activeDifference) return activeDifference;
        return b.z - a.z || b.item.weight - a.item.weight;
      })
      .forEach((particle) => {
        drawFormatLabel(
          particle,
          activeFormatSet.has(particle.item.key),
          activeType !== 'all' && particle.type === activeType,
          placedLabelBoxes,
        );
      });

    const labelParticle = particles.find((particle) => activeFormatSet.has(particle.item.key) && particle.z > -0.6);
    if (labelParticle) drawParticleLabel(labelParticle);
  }

  function animate(time) {
    if (!animationStarted) return;
    const now = time || 0;
    const delta = Math.min(34, lastFrameAt ? now - lastFrameAt : 16.7);
    if (isDocumentVisible && isWorldVisible && !isScrolling) {
      if (!isDraggingWorld) {
        if (worldFocusRotating) {
          const ease = 1 - Math.pow(0.0018, delta / 900);
          const diffY = normalizeAngle(worldTargetRotationY - worldRotationY);
          const diffX = normalizeAngle(worldTargetRotationX - worldRotationX);
          worldRotationY += diffY * ease;
          worldRotationX += diffX * ease;
          if (Math.abs(diffY) < 0.0025 && Math.abs(diffX) < 0.0025) {
            worldRotationY = worldTargetRotationY;
            worldRotationX = worldTargetRotationX;
            worldFocusRotating = false;
          }
        } else {
          worldRotationY += delta * 0.00011 + worldVelocityY;
          worldRotationX += worldVelocityX;
          worldVelocityX *= 0.93;
          worldVelocityY *= 0.93;
        }
      }
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
    const visibleFormats = new Set();
    capabilities.filter(matchesCanvasFilters).forEach((item) => {
      visibleFormats.add(item.source);
      visibleFormats.add(item.target);
    });
    let nearest = null;
    let nearestDistance = Infinity;
    particles.forEach((particle) => {
      if (!visibleFormats.has(particle.item.key)) return;
      const dx = particle.x - x;
      const dy = particle.y - y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = particle;
      }
    });
    return nearestDistance <= 29 ? nearest : null;
  }

  function selectRoute(route) {
    if (!route) return;
    routePinned = true;
    selectedCapability = route;
    selectedFormat = route.source;
    setActiveType(capabilityType(route), { route, forceRotate: true });
    updateWorldSelection();
  }

  function selectFormat(format) {
    routePinned = true;
    selectedFormat = format;
    const route = capabilities.find((item) => matchesActiveFilters(item) && (item.source === format || item.target === format));
    if (route) selectedCapability = route;
    updateWorldSelection();
  }

  function bindCanvasEvents() {
    if (!worldCanvas) return;
    worldCanvas.addEventListener('pointerdown', (event) => {
      isDraggingWorld = true;
      dragMoved = false;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      lastPointerX = event.clientX;
      lastPointerY = event.clientY;
      worldVelocityX = 0;
      worldVelocityY = 0;
      worldFocusRotating = false;
      worldCanvas.setPointerCapture?.(event.pointerId);
      worldCanvas.style.cursor = 'grabbing';
    });
    worldCanvas.addEventListener('pointermove', (event) => {
      if (isDraggingWorld) {
        const dx = event.clientX - lastPointerX;
        const dy = event.clientY - lastPointerY;
        // One drag across the visible globe maps to a complete revolution.
        // Both axes are continuous, so users can inspect every hemisphere.
        const globeDiameter = Math.max(320, Math.min(canvasWidth, canvasHeight) * 0.86);
        const radiansPerPixel = (Math.PI * 2) / globeDiameter;
        if (Math.abs(event.clientX - dragStartX) + Math.abs(event.clientY - dragStartY) > 4) dragMoved = true;
        worldRotationY += dx * radiansPerPixel;
        worldRotationX += dy * radiansPerPixel;
        worldTargetRotationY = worldRotationY;
        worldTargetRotationX = worldRotationX;
        worldVelocityY = dx * radiansPerPixel * 0.055;
        worldVelocityX = dy * radiansPerPixel * 0.055;
        lastPointerX = event.clientX;
        lastPointerY = event.clientY;
        drawCanvas(performance.now());
        return;
      }
      const nearest = nearestParticle(event);
      if (nearest) {
        hoveredCapability = capabilities.find((item) => matchesCanvasFilters(item) && (item.source === nearest.item.key || item.target === nearest.item.key)) || null;
      } else {
        hoveredCapability = null;
      }
      worldCanvas.style.cursor = nearest ? 'grab' : 'grab';
    });
    const endDrag = (event) => {
      if (!isDraggingWorld) return;
      if (Math.abs(event.clientX - dragStartX) + Math.abs(event.clientY - dragStartY) > 4) dragMoved = true;
      isDraggingWorld = false;
      if (dragMoved) lastDragEndedAt = performance.now();
      worldCanvas.releasePointerCapture?.(event.pointerId);
      worldCanvas.style.cursor = 'grab';
    };
    worldCanvas.addEventListener('pointerup', endDrag);
    worldCanvas.addEventListener('pointercancel', endDrag);
    worldCanvas.addEventListener('mouseleave', () => {
      if (!isDraggingWorld) hoveredCapability = null;
    });
    worldCanvas.addEventListener('click', (event) => {
      if (dragMoved || performance.now() - lastDragEndedAt < 180) return;
      const nearest = nearestParticle(event);
      if (!nearest) return;
      setActiveType(nearest.type, { forceRotate: true });
      selectFormat(nearest.item.key);
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
              <em>${verificationLabel(item)}</em>
            </button>
          `).join('')}
        </div>
      </section>
    `).join('') || '<div class="convert-card convert-empty-state">暂无匹配能力</div>';

    matrix.querySelectorAll('[data-capability-key]').forEach((button) => {
      button.addEventListener('click', () => {
        const route = capabilities.find((item) => item.key === button.dataset.capabilityKey) || null;
        selectRoute(route);
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

  function setFormatCount(name, value) {
    document.querySelectorAll(`[data-format-count-for="${name}"]`).forEach((node) => {
      node.textContent = String(value);
    });
  }

  function updateCounts() {
    const byType = (type) => capabilities.filter((item) => capabilityType(item) === type).length;
    const formatsByType = (type) => formatsForRoutes(capabilities.filter((item) => type === 'all' || capabilityType(item) === type)).size;
    const total = capabilities.length;
    if (orbitTotal) orbitTotal.textContent = String(total.toLocaleString());
    setCount('all', total);
    setCount('stable', capabilities.filter((item) => item.level === 'stable').length);
    setCount('basic', capabilities.filter((item) => item.level === 'basic').length);
    setCount('vendor', capabilities.filter((item) => item.level === 'vendor').length);
    setCount('type-all', total);
    setFormatCount('all', formatsByType('all'));
    ['document', 'image', 'media', 'subtitle', 'archive'].forEach((type) => {
      setCount(type, byType(type));
      setCount(`orbit-${type}`, byType(type));
      setFormatCount(type, formatsByType(type));
    });
  }

  filterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.convertFilter || 'all';
      selectedCapability = null;
      selectedFormat = null;
      routePinned = false;
      render();
    });
  });

  typeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      setActiveType(button.dataset.convertType || 'all');
      selectedCapability = null;
      selectedFormat = null;
      routePinned = false;
      updateWorldSelection();
    });
  });

  worldSearchInput?.addEventListener('input', () => {
    activeQuery = worldSearchInput.value || '';
    selectedCapability = null;
    selectedFormat = null;
    routePinned = false;
    render();
  });

  exploreWorldRoutes?.addEventListener('click', () => {
    matrix?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
