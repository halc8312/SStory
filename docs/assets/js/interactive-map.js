/**
 * Interactive Map v1 (stable)
 * SVG描画・表示制御・詳細パネル担当
 */

document.addEventListener('DOMContentLoaded', () => {
  const MapCommon = window.EternalArcadiaMapCommon;
  if (!MapCommon) {
    console.error('[InteractiveMap] map-common.js must be loaded before interactive-map.js.');
    return;
  }
  const { escapeHtml, clamp, formatMonths, createJsonFetcher } = MapCommon;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const BASE_PATH = '../data/map/';
  const CACHE_BUSTER = '20260718a';
  const DEFAULT_VIEW_BOX = { x: 0, y: 0, width: 10000, height: 10000 };
  const MIN_VIEW_BOX_SIZE = 2200;
  const DATA_FILES = [
    { key: 'continents', url: 'continents.json' },
    { key: 'regions', url: 'regions.json' },
    { key: 'nodes', url: 'nodes.json' },
    { key: 'routes', url: 'routes.json' },
    { key: 'hazards', url: 'hazards.json' }
  ];

  const mapData = {};
  const currentViewBox = { ...DEFAULT_VIEW_BOX };
  const countElements = {
    continents: document.getElementById('count-continents'),
    regions: document.getElementById('count-regions'),
    nodes: document.getElementById('count-nodes'),
    routes: document.getElementById('count-routes'),
    hazards: document.getElementById('count-hazards')
  };
  const messageElement = document.getElementById('map-data-message');
  const previewContainers = {
    nodes: document.getElementById('nodes-preview'),
    routes: document.getElementById('routes-preview'),
    hazards: document.getElementById('hazards-preview')
  };
  const svgElement = document.getElementById('transport-map-svg');
  const detailPanel = document.getElementById('map-detail-panel');
  const detailContent = document.getElementById('map-detail-content');
  const layerToggles = document.querySelectorAll('input[data-layer-toggle]');
  const zoomInButton = document.getElementById('map-zoom-in');
  const zoomOutButton = document.getElementById('map-zoom-out');
  const zoomResetButton = document.getElementById('map-zoom-reset');

  function createSvgElement(tagName) {
    return document.createElementNS(SVG_NS, tagName);
  }

  function showError(message) {
    if (messageElement) {
      messageElement.textContent = message;
      messageElement.hidden = false;
    }
    console.error('[InteractiveMap]', message);
  }

  function showWarning(message) {
    console.warn('[InteractiveMap]', message);
    if (messageElement) {
      const warningEl = document.createElement('p');
      warningEl.className = 'map-warning';
      warningEl.textContent = message;
      messageElement.appendChild(warningEl);
      messageElement.hidden = false;
    }
  }

  const fetchJson = createJsonFetcher(BASE_PATH, CACHE_BUSTER);

  function fetchData(key, url) {
    return fetchJson(url)
      .then(data => {
        if (Array.isArray(data)) {
          mapData[key] = data;
          return data.length;
        }
        if (typeof data === 'object' && data !== null) {
          mapData[key] = data;
          if (data.nodes) return data.nodes.length;
          if (data.routes) return data.routes.length;
          if (data.hazards) return data.hazards.length;
          return Object.keys(data).length;
        }
        return 0;
      });
  }

  function formatArray(values, fallback = 'なし') {
    if (!Array.isArray(values) || values.length === 0) {
      return fallback;
    }
    return values.map(item => escapeHtml(item)).join(', ');
  }

  function formatCoordinate(position) {
    return `X: ${position?.x ?? '?'}, Y: ${position?.y ?? '?'}, Z: ${position?.z ?? 0}`;
  }

  function appendTitle(svgParent, text) {
    const title = createSvgElement('title');
    title.textContent = text;
    svgParent.appendChild(title);
  }

  function enableMapInteraction(target, onActivate) {
    target.setAttribute('tabindex', '0');
    target.setAttribute('role', 'button');
    target.addEventListener('click', event => {
      event.stopPropagation();
      onActivate();
    });
    target.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onActivate();
      }
    });
  }

  function getNodeVisual(type, isMajor) {
    if (type === 'capital') return { className: 'node-capital', radius: 48 };
    if (type === 'port' || type === 'seaport') return { className: 'node-port', radius: isMajor ? 30 : 24 };
    if (type === 'airport' || type === 'air_terminal') return { className: 'node-airport', radius: isMajor ? 32 : 25 };
    if (type === 'oasis') return { className: 'node-oasis', radius: 24 };
    if (type === 'floating_island') return { className: 'node-floating-island', radius: isMajor ? 30 : 24 };
    if (type === 'underwater_city') return { className: 'node-underwater-city', radius: isMajor ? 30 : 24 };
    if (type === 'forbidden_gate' || type === 'warp_gate') return { className: 'node-warp-gate', radius: 28 };
    return { className: 'node-city', radius: isMajor ? 28 : 22 };
  }

  function getRouteVisual(type, status) {
    if (type === 'road') return { layer: 'road', className: 'route-road', stroke: '#9d5a31', width: 24, hoverWidth: 34, dasharray: '' };
    if (type === 'caravan') return { layer: 'road', className: 'route-caravan', stroke: '#bb8a43', width: 20, hoverWidth: 30, dasharray: '20 14 4 14' };
    if (type === 'ice_road') return { layer: 'road', className: 'route-ice-road', stroke: '#9fb7cb', width: 20, hoverWidth: 30, dasharray: '16 10' };
    if (type === 'rail') return { layer: 'road', className: 'route-rail', stroke: '#4b4f5a', width: 30, hoverWidth: 40, dasharray: '' };
    if (type === 'sea') return { layer: 'sea', className: 'route-sea', stroke: '#317fcb', width: 18, hoverWidth: 28, dasharray: '18 18' };
    if (type === 'air') return { layer: 'air', className: 'route-air', stroke: '#8558c7', width: 18, hoverWidth: 28, dasharray: '14 14' };
    if (type === 'submarine') return { layer: 'special', className: 'route-submarine', stroke: '#1f9aa1', width: 20, hoverWidth: 30, dasharray: '10 8' };
    if (type === 'tunnel' || type === 'underwater_tunnel') {
      return {
        layer: 'special',
        className: type === 'tunnel' ? 'route-tunnel' : 'route-underwater-tunnel',
        stroke: type === 'tunnel' ? '#67636a' : '#2389a8',
        width: 20,
        hoverWidth: 30,
        dasharray: '12 10'
      };
    }

    const isForbidden = status === 'forbidden' || type === 'forbidden_path';
    return {
      layer: 'special',
      className: isForbidden ? 'route-forbidden' : 'route-warp',
      stroke: isForbidden ? '#9b3441' : '#9150b8',
      width: 22,
      hoverWidth: 32,
      dasharray: isForbidden ? '8 10 2 10' : '8 12'
    };
  }

  function getHazardVisual(type, severity) {
    const severityValue = clamp(Number(severity) || 1, 1, 5);
    const baseOpacity = (0.12 + severityValue * 0.035).toFixed(3);

    if (type === 'ice_sea' || type === 'ice') {
      return { className: 'hazard-ice', fill: '#5f95c8', stroke: '#3a6f9a', opacity: baseOpacity };
    }
    if (type === 'time_distortion') {
      return { className: 'hazard-time', fill: '#8c56bf', stroke: '#69328e', opacity: (0.14 + severityValue * 0.04).toFixed(3) };
    }
    if (type === 'forbidden_zone') {
      return { className: 'hazard-forbidden', fill: '#9d3947', stroke: '#6f202a', opacity: (0.15 + severityValue * 0.04).toFixed(3) };
    }
    if (type === 'pirate_sea' || type === 'monster_sea') {
      return { className: 'hazard-sea-danger', fill: '#a54c3d', stroke: '#7d2c22', opacity: baseOpacity };
    }
    if (type === 'storm') {
      return { className: 'hazard-storm', fill: '#8567a8', stroke: '#5c4575', opacity: baseOpacity };
    }
    return { className: 'hazard-default', fill: '#b86b44', stroke: '#8c3b2c', opacity: baseOpacity };
  }

  function renderNodes(svg, nodes) {
    const layerGroup = createSvgElement('g');
    layerGroup.setAttribute('id', 'layer-nodes');
    layerGroup.setAttribute('data-layer', 'nodes');

    const labelGroup = createSvgElement('g');
    labelGroup.setAttribute('id', 'layer-node-labels');
    labelGroup.setAttribute('data-layer', 'labels');

    nodes.forEach(node => {
      if (!node.position || node.position.x === undefined || node.position.y === undefined) {
        showWarning(`ノード ${node.id || 'unknown'}: positionデータ不足、スキップします`);
        return;
      }

      const x = node.position.x;
      const y = node.position.y;
      const type = node.type || 'unknown';
      const name = node.name || node.id || 'unnamed';
      const transportRoles = node.transport_roles || [];
      const tags = node.tags || [];
      const isMajor = type === 'capital' || transportRoles.includes('major_hub') || transportRoles.includes('road_hub') || tags.includes('major_hub');
      const visual = getNodeVisual(type, isMajor);

      const nodeGroup = createSvgElement('g');
      nodeGroup.setAttribute('class', `map-node ${visual.className}`);
      nodeGroup.setAttribute('data-layer', 'nodes');
      nodeGroup.setAttribute('data-node-id', node.id || name);
      nodeGroup.style.setProperty('--node-radius', String(visual.radius));
      nodeGroup.setAttribute('aria-label', `${name} の詳細を表示`);

      const ring = createSvgElement('circle');
      ring.setAttribute('class', 'map-node-ring');
      ring.setAttribute('cx', x);
      ring.setAttribute('cy', y);
      ring.setAttribute('r', visual.radius + 5);

      const core = createSvgElement('circle');
      core.setAttribute('class', 'map-node-core');
      core.setAttribute('cx', x);
      core.setAttribute('cy', y);
      core.setAttribute('r', visual.radius);

      const hitArea = createSvgElement('circle');
      hitArea.setAttribute('class', 'map-node-hitarea');
      hitArea.setAttribute('cx', x);
      hitArea.setAttribute('cy', y);
      hitArea.setAttribute('r', visual.radius + 22);

      appendTitle(nodeGroup, name);
      nodeGroup.appendChild(ring);
      nodeGroup.appendChild(core);
      nodeGroup.appendChild(hitArea);
      enableMapInteraction(nodeGroup, () => showNodeDetail(node));
      layerGroup.appendChild(nodeGroup);

      if (isMajor) {
        const label = createSvgElement('text');
        label.setAttribute('class', `map-label map-node-label ${visual.className}`);
        label.setAttribute('data-layer', 'labels');
        label.setAttribute('x', x);
        label.setAttribute('y', y - visual.radius - 26);
        label.setAttribute('text-anchor', 'middle');
        label.textContent = name;
        labelGroup.appendChild(label);
      }
    });

    svg.appendChild(layerGroup);
    svg.appendChild(labelGroup);
  }

  function renderRoutes(svg, routes, nodes) {
    const nodeById = {};
    nodes.forEach(node => {
      if (node.id && node.position) {
        nodeById[node.id] = node;
      }
    });

    const layers = {
      road: createSvgElement('g'),
      sea: createSvgElement('g'),
      air: createSvgElement('g'),
      special: createSvgElement('g')
    };

    Object.entries(layers).forEach(([layerName, group]) => {
      group.setAttribute('data-layer', layerName);
    });

    routes.forEach(route => {
      const fromNode = nodeById[route.from];
      const toNode = nodeById[route.to];

      if (!fromNode || !toNode || !fromNode.position || !toNode.position) {
        showWarning(`ルート ${route.id || 'unknown'}: from/toノード情報不足、スキップします`);
        return;
      }

      const visual = getRouteVisual(route.type || 'unknown', route.status || 'unknown');
      const name = route.name || route.id || 'unnamed';
      const routeGroup = createSvgElement('g');
      routeGroup.setAttribute('class', `map-route ${visual.className}`);
      routeGroup.setAttribute('data-layer', visual.layer);
      routeGroup.setAttribute('data-route-id', route.id || name);
      routeGroup.style.setProperty('--route-color', visual.stroke);
      routeGroup.style.setProperty('--route-width', String(visual.width));
      routeGroup.style.setProperty('--route-hover-width', String(visual.hoverWidth));
      routeGroup.style.setProperty('--route-hit-width', String(Math.max(visual.width + 22, 34)));
      if (visual.dasharray) {
        routeGroup.style.setProperty('--route-dasharray', visual.dasharray);
      }
      routeGroup.setAttribute('aria-label', `${name} の詳細を表示`);

      const line = createSvgElement('line');
      line.setAttribute('class', 'map-route-visual');
      line.setAttribute('x1', fromNode.position.x);
      line.setAttribute('y1', fromNode.position.y);
      line.setAttribute('x2', toNode.position.x);
      line.setAttribute('y2', toNode.position.y);

      const hitArea = createSvgElement('line');
      hitArea.setAttribute('class', 'map-route-hitarea');
      hitArea.setAttribute('x1', fromNode.position.x);
      hitArea.setAttribute('y1', fromNode.position.y);
      hitArea.setAttribute('x2', toNode.position.x);
      hitArea.setAttribute('y2', toNode.position.y);

      appendTitle(routeGroup, name);
      routeGroup.appendChild(line);
      routeGroup.appendChild(hitArea);
      enableMapInteraction(routeGroup, () => showRouteDetail(route, fromNode, toNode));
      layers[visual.layer].appendChild(routeGroup);
    });

    Object.values(layers).forEach(group => {
      if (group.childNodes.length > 0) {
        svg.appendChild(group);
      }
    });
  }

  function renderHazards(svg, hazards) {
    const group = createSvgElement('g');
    group.setAttribute('id', 'layer-hazards');
    group.setAttribute('data-layer', 'hazards');

    hazards.forEach(hazard => {
      if (!hazard.center || hazard.center.x === undefined || hazard.center.y === undefined || !hazard.radius) {
        showWarning(`危険区域 ${hazard.id || 'unknown'}: center/radiusデータ不足、スキップします`);
        return;
      }

      const name = hazard.name || hazard.id || 'unnamed';
      const visual = getHazardVisual(hazard.type || 'unknown', hazard.severity || 1);
      const severity = clamp(Number(hazard.severity) || 1, 1, 5);
      const hazardGroup = createSvgElement('g');
      hazardGroup.setAttribute('class', `map-hazard ${visual.className}`);
      hazardGroup.setAttribute('data-layer', 'hazards');
      hazardGroup.setAttribute('data-severity', String(severity));
      hazardGroup.setAttribute('data-hazard-id', hazard.id || name);
      hazardGroup.style.setProperty('--hazard-fill', visual.fill);
      hazardGroup.style.setProperty('--hazard-stroke', visual.stroke);
      hazardGroup.style.setProperty('--hazard-opacity', visual.opacity);
      hazardGroup.setAttribute('aria-label', `${name} の詳細を表示`);

      const area = createSvgElement('circle');
      area.setAttribute('class', 'map-hazard-area');
      area.setAttribute('cx', hazard.center.x);
      area.setAttribute('cy', hazard.center.y);
      area.setAttribute('r', hazard.radius);

      const hitArea = createSvgElement('circle');
      hitArea.setAttribute('class', 'map-hazard-hitarea');
      hitArea.setAttribute('cx', hazard.center.x);
      hitArea.setAttribute('cy', hazard.center.y);
      hitArea.setAttribute('r', hazard.radius + 32);

      appendTitle(hazardGroup, name);
      hazardGroup.appendChild(area);
      hazardGroup.appendChild(hitArea);
      enableMapInteraction(hazardGroup, () => showHazardDetail(hazard));
      group.appendChild(hazardGroup);
    });

    svg.appendChild(group);
  }

  function renderContinents(svg, continents) {
    const group = createSvgElement('g');
    group.setAttribute('id', 'layer-continents');
    group.setAttribute('data-layer', 'labels');

    continents.forEach(continent => {
      const center = continent.center || {};
      const label = createSvgElement('text');
      label.setAttribute('class', 'map-label map-continent-label');
      label.setAttribute('data-layer', 'labels');
      label.setAttribute('x', center.x ?? 5000);
      label.setAttribute('y', center.y ?? 5000);
      label.setAttribute('text-anchor', 'middle');
      label.textContent = continent.name || continent.id || 'unknown';
      group.appendChild(label);
    });

    svg.appendChild(group);
  }

  function renderTransportMap() {
    if (!svgElement) return;

    svgElement.innerHTML = '';
    resetZoom();

    const nodes = mapData.nodes || [];
    const routes = mapData.routes || [];
    const hazards = mapData.hazards || [];
    const continents = Array.isArray(mapData.continents) ? mapData.continents : [];

    console.log('[InteractiveMap] Rendering map:', {
      nodes: nodes.length,
      routes: routes.length,
      hazards: hazards.length,
      continents: continents.length
    });

    renderContinents(svgElement, continents);
    renderHazards(svgElement, hazards);
    renderRoutes(svgElement, routes, nodes);
    renderNodes(svgElement, nodes);
  }

   function initializeRouteSearchModule() {
     if (typeof window.initializeRouteSearch !== 'function') {
       console.warn('[InteractiveMap] route-search.js is not available');
       return;
     }

     const nodes = Array.isArray(mapData.nodes) ? mapData.nodes : [];
     const routes = Array.isArray(mapData.routes) ? mapData.routes : [];

     const nodeById = {};
     nodes.forEach(node => {
       if (node.id) {
         nodeById[node.id] = node;
       }
     });

     window.initializeRouteSearch({
       nodes,
       routes,
       svgElement,
       nodeById
     });
   }

  function createBadge(text, className = 'detail-badge') {
    return `<span class="${className}">${escapeHtml(text)}</span>`;
  }

  function createStatusBadge(status) {
    return createBadge(status || 'unknown', `detail-badge status-badge status-${escapeHtml(status || 'unknown')}`);
  }

  function createSeverityBadge(value) {
    return createBadge(`危険度 ${value ?? '?'}`, `detail-badge severity-badge severity-level-${clamp(Number(value) || 1, 1, 5)}`);
  }

  function formatEffects(effects) {
    if (!effects || Object.keys(effects).length === 0) {
      return '<span class="detail-muted">なし</span>';
    }

    const items = Object.entries(effects)
      .map(([key, value]) => `<li><span class="detail-effect-key">${escapeHtml(key)}</span><span>${escapeHtml(value)}</span></li>`)
      .join('');
    return `<ul class="detail-inline-list">${items}</ul>`;
  }

  function renderDetailCard(kindLabel, title, badges, rows, description) {
    const badgeHtml = badges.filter(Boolean).join('');
    const rowHtml = rows
      .map(({ term, value, html }) => `<dt>${escapeHtml(term)}</dt><dd>${html ? value : escapeHtml(value ?? 'なし')}</dd>`)
      .join('');

    detailContent.innerHTML = `
      <article class="detail-card">
        <header class="detail-header">
          <p class="detail-kicker">${escapeHtml(kindLabel)}</p>
          <h3>${escapeHtml(title)}</h3>
          ${badgeHtml ? `<div class="detail-badge-list">${badgeHtml}</div>` : ''}
        </header>
        <dl class="detail-list">${rowHtml}</dl>
        <div class="detail-description"><p>${escapeHtml(description || '説明なし')}</p></div>
      </article>
    `;
    detailPanel.hidden = false;
  }

  function showNodeDetail(node) {
    if (!detailContent || !detailPanel) return;

    const continent = mapData.continents?.find(item => item.id === node.continent_id) || null;
    const region = mapData.regions?.find(item => item.id === node.region_id) || null;
    const badges = [createBadge(node.type || 'unknown')];

    if ((node.transport_roles || []).includes('major_hub') || (node.tags || []).includes('major_hub')) {
      badges.push(createBadge('主要拠点'));
    }

    renderDetailCard(
      'ノード',
      node.name || node.id,
      badges,
      [
        { term: 'ID', value: node.id || '不明' },
        { term: '種別', value: node.type || 'unknown' },
        { term: '大陸', value: continent?.name || node.continent_id || '不明' },
        { term: '地域', value: region?.name || node.region_id || '不明' },
        { term: '座標', value: formatCoordinate(node.position) },
        { term: '交通ロール', value: formatArray(node.transport_roles) },
        { term: '施設', value: formatArray(node.facilities) },
        { term: 'タグ', value: formatArray(node.tags) }
      ],
      node.description
    );
  }

  function showRouteDetail(route, fromNode, toNode) {
    if (!detailContent || !detailPanel) return;

    const isRestricted = route.status === 'restricted' || route.status === 'forbidden' || (route.tags || []).includes('restricted');
    const badges = [createBadge(route.type || 'unknown'), createStatusBadge(route.status || 'unknown')];

    if (route.seasonal) {
      badges.push(createBadge('季節運行', 'detail-badge detail-badge-accent'));
    }
    if (isRestricted) {
      badges.push(createBadge('制限あり', 'detail-badge detail-badge-warning'));
    }
    if (route.danger_level !== undefined && route.danger_level !== null) {
      badges.push(createSeverityBadge(route.danger_level));
    }

    renderDetailCard(
      'ルート',
      route.name || route.id,
      badges,
      [
        { term: 'ID', value: route.id || '不明' },
        { term: '種別', value: route.type || 'unknown' },
        { term: '交通モード', value: route.mode || '未設定' },
        { term: '出発地', value: fromNode?.name || fromNode?.id || route.from || '不明' },
        { term: '到着地', value: toNode?.name || toNode?.id || route.to || '不明' },
        { term: '距離', value: `${route.distance_km ?? '?'} km` },
        { term: '所要時間', value: `${route.estimated_time_hours ?? '?'} 時間` },
        { term: '費用', value: `${route.cost_gold ?? '?'} GP` },
        { term: '運行月', value: formatMonths(route.active_months) },
        { term: '運営者', value: formatArray(route.operators, '不明') },
        { term: 'タグ', value: formatArray(route.tags) }
      ],
      route.description
    );
  }

  function showHazardDetail(hazard) {
    if (!detailContent || !detailPanel) return;

    const continent = mapData.continents?.find(item => item.id === hazard.continent_id) || null;
    const badges = [createBadge(hazard.type || 'unknown'), createSeverityBadge(hazard.severity)];

    if (hazard.seasonal) {
      badges.push(createBadge('季節変動', 'detail-badge detail-badge-accent'));
    }

    renderDetailCard(
      '危険区域',
      hazard.name || hazard.id,
      badges,
      [
        { term: 'ID', value: hazard.id || '不明' },
        { term: '種別', value: hazard.type || 'unknown' },
        { term: '大陸', value: continent?.name || hazard.continent_id || '不明' },
        { term: '中心座標', value: formatCoordinate(hazard.center) },
        { term: '半径', value: `${hazard.radius ?? '?'} km相当` },
        { term: '活動月', value: formatMonths(hazard.active_months) },
        { term: '効果', value: formatEffects(hazard.effects), html: true }
      ],
      hazard.description
    );
  }

  function setupLayerToggles() {
    if (!svgElement) return;

    layerToggles.forEach(toggle => {
      toggle.addEventListener('change', event => {
        const layer = event.target.getAttribute('data-layer-toggle');
        const isVisible = event.target.checked;
        const elements = svgElement.querySelectorAll(`[data-layer="${layer}"]`);
        elements.forEach(element => {
          element.classList.toggle('map-hidden', !isVisible);
        });
      });
    });
  }

  function applyViewBox() {
    if (!svgElement) return;
    svgElement.setAttribute('viewBox', `${currentViewBox.x} ${currentViewBox.y} ${currentViewBox.width} ${currentViewBox.height}`);
  }

  function resetZoom() {
    currentViewBox.x = DEFAULT_VIEW_BOX.x;
    currentViewBox.y = DEFAULT_VIEW_BOX.y;
    currentViewBox.width = DEFAULT_VIEW_BOX.width;
    currentViewBox.height = DEFAULT_VIEW_BOX.height;
    applyViewBox();
  }

  function zoomBy(factor) {
    const nextWidth = clamp(Math.round(currentViewBox.width * factor), MIN_VIEW_BOX_SIZE, DEFAULT_VIEW_BOX.width);
    const nextHeight = clamp(Math.round(currentViewBox.height * factor), MIN_VIEW_BOX_SIZE, DEFAULT_VIEW_BOX.height);
    const centerX = currentViewBox.x + currentViewBox.width / 2;
    const centerY = currentViewBox.y + currentViewBox.height / 2;

    currentViewBox.width = nextWidth;
    currentViewBox.height = nextHeight;
    currentViewBox.x = clamp(Math.round(centerX - nextWidth / 2), DEFAULT_VIEW_BOX.x, DEFAULT_VIEW_BOX.width - nextWidth);
    currentViewBox.y = clamp(Math.round(centerY - nextHeight / 2), DEFAULT_VIEW_BOX.y, DEFAULT_VIEW_BOX.height - nextHeight);
    applyViewBox();
  }

  function setupZoomControls() {
    zoomInButton?.addEventListener('click', () => zoomBy(0.8));
    zoomOutButton?.addEventListener('click', () => zoomBy(1.25));
    zoomResetButton?.addEventListener('click', resetZoom);
  }

  function renderNodesPreview(nodes) {
    const container = previewContainers.nodes;
    if (!container) return;
    const items = nodes.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    container.innerHTML = items.map(node => {
      const name = node.name || node.id || 'unnamed';
      const type = node.type || 'unknown';
      const location = node.continent_id || node.region_id || '';
      return `<div class="data-preview-card"><strong>${escapeHtml(name)}</strong><span class="type-badge">${escapeHtml(type)}</span>${location ? `<span class="location">${escapeHtml(location)}</span>` : ''}</div>`;
    }).join('');
  }

  function renderRoutesPreview(routes) {
    const container = previewContainers.routes;
    if (!container) return;
    const items = routes.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    container.innerHTML = items.map(route => {
      const name = route.name || route.id || 'unnamed';
      const type = route.type || 'unknown';
      const status = route.status || 'unknown';
      return `<div class="data-preview-card"><strong>${escapeHtml(name)}</strong><span class="type-badge">${escapeHtml(type)}</span><span class="status-badge status-${escapeHtml(status)}">${escapeHtml(status)}</span></div>`;
    }).join('');
  }

  function renderHazardsPreview(hazards) {
    const container = previewContainers.hazards;
    if (!container) return;
    const items = hazards.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    container.innerHTML = items.map(hazard => {
      const name = hazard.name || hazard.id || 'unnamed';
      const type = hazard.type || 'unknown';
      const severity = hazard.severity || '?';
      return `<div class="data-preview-card"><strong>${escapeHtml(name)}</strong><span class="type-badge">${escapeHtml(type)}</span><span class="severity-badge severity-level-${clamp(Number(severity) || 1, 1, 5)}">危険度 ${escapeHtml(severity)}</span></div>`;
    }).join('');
  }

  function updateCount(key, count) {
    const element = countElements[key];
    if (element) {
      element.textContent = `${count}件`;
      element.classList.add('status-ok');
    }
  }

  function setErrorCount(key) {
    const element = countElements[key];
    if (element) {
      element.textContent = 'エラー';
      element.classList.add('status-error');
    }
  }

  async function loadAllData() {
    const promises = DATA_FILES.map(file => fetchData(file.key, file.url)
      .then(count => ({ key: file.key, count }))
      .catch(error => {
        console.error(`Failed to load ${file.key}:`, error);
        return { key: file.key, error };
      }));

    const results = await Promise.all(promises);
    const failures = results.filter(result => result.error);
    results.forEach(({ key, count, error }) => {
      if (error) {
        setErrorCount(key);
      } else {
        updateCount(key, count);
      }
    });
    if (failures.length > 0) {
      showError(`地図データの読み込みに失敗しました: ${failures.map(result => result.key).join(', ')}`);
    }

    if (Array.isArray(mapData.nodes)) renderNodesPreview(mapData.nodes);
    if (Array.isArray(mapData.routes)) renderRoutesPreview(mapData.routes);
    if (Array.isArray(mapData.hazards)) renderHazardsPreview(mapData.hazards);

    if (!svgElement) {
      showError('SVG描画領域が見つかりません。interactive-map.html を確認してください。');
      return;
    }

    try {
      renderTransportMap();
      initializeRouteSearchModule();
      setupLayerToggles();
      setupZoomControls();
      console.log('[InteractiveMap] SVG rendering completed');
    } catch (error) {
      showError(`SVG描画に失敗しました: ${error.message}`);
      console.error('[InteractiveMap] Render error:', error);
    }
  }

  loadAllData();
});
