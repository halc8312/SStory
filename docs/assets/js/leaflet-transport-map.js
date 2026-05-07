(() => {
   const BASE_PATH = '../data/map/';
   const CACHE_BUSTER = '20260507b';

    // === 座標変換設定 ===
    // Map Data座標系 (0-10000) を Leaflet表示座標に変換する設定
    const MAP_COORDINATE_CONFIG = {
      // データ座標の範囲 (world-map.svg の原始座標系)
      width: 10000,
      height: 10000,
      // 反転
      flipX: false,
      flipY: false,
      // スケール (1=等倍, >1で拡大, <1で縮小)
      // 現在: 世界地図画像の形状と大陸位置を合わせるため、微調整中
      scaleX: 0.95,  //  empirically adjusted to align continents horizontally
      scaleY: 0.85,  //  empirically adjusted to align continents vertically
      // オフセット
      offsetX: -300, // empirically adjusted
      offsetY: -200, // empirically adjusted
      // スケールの中心点
      centerX: 5000,
      centerY: 5000,
      // デバッグ表示
      showGrid: false,
      showDebugNodes: true
    };

    // データ座標の範囲 (変換前)
    const WORLD_COORDINATE_BOUNDS = [[0, 0], [MAP_COORDINATE_CONFIG.width, MAP_COORDINATE_CONFIG.height]];

    // 背景画像の表示範囲 (変換後座標系)
    // 現在はデータ座標系と同一。必要に応じて画像の実効範囲に合わせて調整可。
    const WORLD_IMAGE_BOUNDS = WORLD_COORDINATE_BOUNDS;

   const DEFAULT_MESSAGE = 'Leaflet版交通マップを読み込めませんでした。';
  const DEFAULT_NODE_STYLE = { radius: 6, fillColor: '#c18857', color: '#7d5130', weight: 1.8, fillOpacity: 0.9 };
  const NODE_STYLE_BY_TYPE = {
    capital: { radius: 9, fillColor: '#d5b34b', color: '#8c6a10', weight: 2.2, fillOpacity: 0.95 },
    port: { radius: 7, fillColor: '#4f89cb', color: '#234f7f', weight: 2, fillOpacity: 0.92 },
    seaport: { radius: 7, fillColor: '#4f89cb', color: '#234f7f', weight: 2, fillOpacity: 0.92 },
    airport: { radius: 7.5, fillColor: '#9664cf', color: '#5e3794', weight: 2, fillOpacity: 0.92 },
    air_terminal: { radius: 7.5, fillColor: '#9664cf', color: '#5e3794', weight: 2, fillOpacity: 0.92 },
    oasis: { radius: 7, fillColor: '#57a36b', color: '#2f6d3f', weight: 2, fillOpacity: 0.92 },
    forbidden_gate: { radius: 7.5, fillColor: '#a65190', color: '#692558', weight: 2, fillOpacity: 0.92 },
    warp_gate: { radius: 7.5, fillColor: '#a65190', color: '#692558', weight: 2, fillOpacity: 0.92 },
    warp_terminal: { radius: 7.5, fillColor: '#a65190', color: '#692558', weight: 2, fillOpacity: 0.92 }
  };
  const ROUTE_DEFINITION_BY_TYPE = {
    road: { overlayName: '陸路', style: { color: '#9d5a31', weight: 4.5, opacity: 0.9 } },
    caravan: { overlayName: '陸路', style: { color: '#bb8a43', weight: 4, opacity: 0.9, dashArray: '10 8 2 8' } },
    ice_road: { overlayName: '陸路', style: { color: '#8aa7bf', weight: 4, opacity: 0.9, dashArray: '10 6' } },
    rail: { overlayName: '鉄道', style: { color: '#4b4f5a', weight: 5.5, opacity: 0.9 } },
    sea: { overlayName: '海路', style: { color: '#317fcb', weight: 4, opacity: 0.85, dashArray: '12 10' } },
    air: { overlayName: '空路', style: { color: '#8558c7', weight: 4, opacity: 0.85, dashArray: '8 10' } },
    submarine: { overlayName: '特殊交通', style: { color: '#1f9aa1', weight: 4, opacity: 0.85, dashArray: '8 6' } },
    tunnel: { overlayName: '特殊交通', style: { color: '#67636a', weight: 4, opacity: 0.9, dashArray: '8 8' } },
    underwater_tunnel: { overlayName: '特殊交通', style: { color: '#2389a8', weight: 4, opacity: 0.9, dashArray: '8 8' } },
    forbidden_path: { overlayName: '特殊交通', style: { color: '#9b3441', weight: 4, opacity: 0.9, dashArray: '6 8 2 8' } },
    default: { overlayName: '特殊交通', style: { color: '#9150b8', weight: 4, opacity: 0.88, dashArray: '6 10' } }
  };
  const POI_CATEGORY_STYLES = {
    government: { color: '#8e5a2a', fillColor: '#d8a15d' },
    military: { color: '#7d2e2e', fillColor: '#d86b5f' },
    transport: { color: '#2f5f8f', fillColor: '#6aa4d8' },
    market: { color: '#8a6f2a', fillColor: '#d8bd5f' },
    shop: { color: '#7a6a3a', fillColor: '#c9b06a' },
    inn: { color: '#6a4b2d', fillColor: '#c58d5a' },
    food: { color: '#8b4f2f', fillColor: '#d98a5a' },
    guild: { color: '#4b5f7a', fillColor: '#8da6c8' },
    academy: { color: '#5c4a8a', fillColor: '#a58bd8' },
    temple: { color: '#8a7a3a', fillColor: '#e0cf76' },
    culture: { color: '#7b4a7d', fillColor: '#c586c8' },
    entertainment: { color: '#8a4f6a', fillColor: '#d486ac' },
    industry: { color: '#5f5a4a', fillColor: '#aaa07d' },
    research: { color: '#3f6f74', fillColor: '#79b8bd' },
    hazard_support: { color: '#8a3a2a', fillColor: '#d8765f' },
    dungeon: { color: '#4a3a3a', fillColor: '#8d7777' },
    landmark: { color: '#4f7a4f', fillColor: '#8fc98f' },
    residential: { color: '#6f6f6f', fillColor: '#b6b6b6' },
    utility: { color: '#4f6f6f', fillColor: '#8fbaba' },
    restricted: { color: '#5d2a5d', fillColor: '#a85ca8' }
  };
  const POI_CATEGORY_LABELS = {
    government: 'POI: 行政',
    military: 'POI: 軍事',
    transport: 'POI: 交通施設',
    market: 'POI: 市場',
    shop: 'POI: 商店',
    inn: 'POI: 宿泊',
    food: 'POI: 飲食',
    guild: 'POI: ギルド',
    academy: 'POI: 学院',
    temple: 'POI: 神殿',
    culture: 'POI: 文化',
    entertainment: 'POI: 娯楽',
    industry: 'POI: 工業',
    research: 'POI: 研究',
    hazard_support: 'POI: 危険対応',
    dungeon: 'POI: ダンジョン',
    landmark: 'POI: 名所',
    residential: 'POI: 居住',
    utility: 'POI: 公共設備',
    restricted: 'POI: 制限区域'
  };
  const UNKNOWN_VALUE = 'unknown';
  const UNKNOWN_POI_CATEGORY = 'unknown';

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  }

    function transformPosition(position) {
      const config = MAP_COORDINATE_CONFIG;
      let x = Number(position?.x ?? 0);
      let y = Number(position?.y ?? 0);

      // 反転
      if (config.flipX) {
        x = config.width - x;
      }
      if (config.flipY) {
        y = config.height - y;
      }

      // スケール・オフセット (中心からの相対)
      x = config.centerX + (x - config.centerX) * config.scaleX + config.offsetX;
      y = config.centerY + (y - config.centerY) * config.scaleY + config.offsetY;

      return { x, y };
    }

    function toLatLng(position) {
      const transformed = transformPosition(position);
      return [transformed.y, transformed.x];
    }

    function getAdjustedHazardRadius(hazard) {
      const radius = Number(hazard?.radius ?? 0);
      const scale = (MAP_COORDINATE_CONFIG.scaleX + MAP_COORDINATE_CONFIG.scaleY) / 2;
      return radius * scale;
    }

    function createCoordinateGridLayer() {
      const gridLayer = L.layerGroup();
      const gridColor = '#8a6f42';
      const gridWeight = 1;
      const gridOpacity = 0.25;

      // 縦線 (X = 一定)
      for (let x = 0; x <= MAP_COORDINATE_CONFIG.width; x += 1000) {
        L.polyline(
          [toLatLng({ x, y: 0 }), toLatLng({ x, y: MAP_COORDINATE_CONFIG.height })],
          { color: gridColor, weight: gridWeight, opacity: gridOpacity }
        ).addTo(gridLayer);
      }

      // 横線 (Y = 一定)
      for (let y = 0; y <= MAP_COORDINATE_CONFIG.height; y += 1000) {
        L.polyline(
          [toLatLng({ x: 0, y }), toLatLng({ x: MAP_COORDINATE_CONFIG.width, y })],
          { color: gridColor, weight: gridWeight, opacity: gridOpacity }
        ).addTo(gridLayer);
      }

      return gridLayer;
    }

  function formatMonths(months) {
    return Array.isArray(months) && months.length > 0 ? months.join(', ') : 'なし';
  }

  function formatList(items) {
    return Array.isArray(items) && items.length > 0 ? items.join(' / ') : 'なし';
  }

  function formatCoordinate(position) {
    if (!position || position.x === undefined || position.y === undefined) {
      return 'X: ?, Y: ?';
    }
    return `X: ${position.x}, Y: ${position.y}`;
  }

  function formatPoiCoordinate(position) {
    if (!position || position.x === undefined || position.y === undefined) {
      return 'X: ?, Y: ?, Z: ?';
    }
    const zValue = position.z ?? 0;
    return `X: ${position.x}, Y: ${position.y}, Z: ${zValue}`;
  }

  function isFiniteNumber(value) {
    return Number.isFinite(Number(value));
  }

  function buildLookupById(items) {
    return Object.fromEntries((items || []).filter(item => item?.id).map(item => [item.id, item]));
  }

  function createPopupHtml(title, rows, description) {
    const rowHtml = rows.map(([term, value]) => `
      <dt>${escapeHtml(term)}</dt>
      <dd>${escapeHtml(value ?? 'なし')}</dd>
    `).join('');

    return `
      <article class="leaflet-popup-card">
        <h3>${escapeHtml(title)}</h3>
        <dl>${rowHtml}</dl>
        <p>${escapeHtml(description || '説明なし')}</p>
      </article>
    `;
  }

  function getPoiCategoryLabel(category) {
    return POI_CATEGORY_LABELS[category] ?? `POI: ${category ?? UNKNOWN_POI_CATEGORY}`;
  }

  function normalizePoiLookupKey(value) {
    return String(value ?? '').trim();
  }

  function getPoiRadius(poi) {
    const importance = Math.min(Math.max(Number(poi?.importance ?? 1) || 1, 1), 5);
    return [3.5, 4.5, 5.5, 7, 8.5][importance - 1];
  }

  function getPoiStyle(poi) {
    const categoryStyle = POI_CATEGORY_STYLES[poi?.category] || { color: '#6f5a46', fillColor: '#c7ab88' };
    return {
      pane: 'poiPane',
      radius: getPoiRadius(poi),
      color: categoryStyle.color,
      fillColor: categoryStyle.fillColor,
      weight: 1.4,
      opacity: 0.9,
      fillOpacity: 0.8,
      className: 'leaflet-poi-marker'
    };
  }

  function createPoiPopupHtml(poi) {
    const metaSummary = [
      `カテゴリ: ${poi.category ?? UNKNOWN_POI_CATEGORY}`,
      `種別: ${poi.type ?? UNKNOWN_VALUE}`,
      `重要度: ${poi.importance ?? '不明'}`,
      `状態: ${poi.status ?? UNKNOWN_VALUE}`
    ].join(' / ');

    const factRows = [
      ['最寄りノード', poi.nearest_node_id ?? '不明'],
      ['座標', formatPoiCoordinate(poi.position)]
    ].map(([term, value]) => `
      <dt>${escapeHtml(term)}</dt>
      <dd>${escapeHtml(value)}</dd>
    `).join('');

    const narrativeSections = [
      ['交通上の役割', poi.transport_role],
      ['経済上の役割', poi.economic_role],
      ['文化上の役割', poi.cultural_role],
      ['危険文脈', poi.risk_context],
      ['歴史的背景', poi.historical_reason]
    ].filter(([, value]) => value).map(([label, value]) => `
      <section class="poi-popup-section">
        <h4>${escapeHtml(label)}</h4>
        <p>${escapeHtml(value)}</p>
      </section>
    `).join('');

    const loreBasis = Array.isArray(poi.lore_basis) && poi.lore_basis.length > 0
      ? `
        <section class="poi-popup-section poi-popup-section-secondary">
          <h4>設定根拠</h4>
          <ul class="poi-popup-list poi-popup-lore">
            ${poi.lore_basis.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
          </ul>
        </section>
      `
      : '';

    const tags = Array.isArray(poi.tags) && poi.tags.length > 0
      ? `<div class="poi-tags">${poi.tags.map(tag => `<span class="poi-tag">${escapeHtml(tag)}</span>`).join('')}</div>`
      : '<p class="poi-tags-empty">タグなし</p>';

    return `
      <article class="leaflet-popup-card poi-popup">
        <h3>${escapeHtml(poi.name || poi.id || 'POI')}</h3>
        <p class="poi-popup-meta">${escapeHtml(metaSummary)}</p>
        <p class="poi-popup-description">${escapeHtml(poi.description || '説明なし')}</p>
        ${factRows ? `<dl class="poi-popup-facts">${factRows}</dl>` : ''}
        ${narrativeSections}
        ${loreBasis}
        <section class="poi-popup-section">
          <h4>タグ</h4>
          ${tags}
        </section>
      </article>
    `;
  }

  function createLeafletUnavailableApi(reason = 'Leaflet unavailable') {
    return {
      isAvailable: false,
      reason,
      map: null,
      routeLayerById: new Map(),
      nodeMarkerById: new Map(),
      poiById: new Map(),
      poiMarkerById: new Map(),
      poiLayersByCategory: new Map(),
      fitWorld() {},
      clearHighlights() {},
      highlightRouteIds() {},
      focusNodeIds() {},
      focusPoi() {
        return false;
      }
    };
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const mapElement = document.getElementById('leaflet-transport-map');
    const messageElement = document.getElementById('leaflet-transport-map-message');

    if (!mapElement) {
      return;
    }

    window.EternalArcadiaLeafletMap = createLeafletUnavailableApi('Leaflet map not initialized yet.');

    function showLeafletMessage(message) {
      if (!messageElement) {
        return;
      }
      messageElement.textContent = message;
      messageElement.hidden = false;
    }

    function clearLeafletMessage() {
      if (!messageElement) {
        return;
      }
      messageElement.textContent = '';
      messageElement.hidden = true;
    }

    try {
      if (!window.L) {
        showLeafletMessage('Leafletを読み込めませんでした。ページを再読み込みするか、時間をおいて再度お試しください。');
        window.EternalArcadiaLeafletMap = createLeafletUnavailableApi('Leaflet global `window.L` is missing.');
        console.error(
          '[LeafletTransportMap] Leaflet is not available. Check local Leaflet CSS/JS loading, script order, cache state, or vendor file paths.'
        );
        return;
      }

      const leafletCssElement = document.querySelector('link[href*="leaflet.css"]');
      if (!leafletCssElement) {
        console.warn('[LeafletTransportMap] Leaflet CSS link was not found. Controls may render incorrectly.');
      }
      if (mapElement.clientHeight < 300) {
        console.warn('[LeafletTransportMap] Map container height is smaller than expected:', mapElement.clientHeight);
      }

      const fetchJson = async (name) => {
        const response = await fetch(`${BASE_PATH}${name}?v=${CACHE_BUSTER}`);
        if (!response.ok) {
          throw new Error(`${name}: HTTP ${response.status}`);
        }
        return response.json();
      };

      let datasets = {};
      const fetchResults = await Promise.allSettled([
        fetchJson('nodes.json'),
        fetchJson('routes.json'),
        fetchJson('hazards.json'),
        fetchJson('continents.json'),
        fetchJson('regions.json')
      ]);

      const keys = ['nodes', 'routes', 'hazards', 'continents', 'regions'];
      const failedKeys = [];
      fetchResults.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          datasets[keys[index]] = Array.isArray(result.value) ? result.value : [];
        } else {
          failedKeys.push(keys[index]);
          datasets[keys[index]] = [];
          console.error('[LeafletTransportMap] Failed to load dataset:', keys[index], result.reason);
        }
      });

      if (failedKeys.length > 0) {
        showLeafletMessage(`一部のMap Dataを読み込めませんでした: ${failedKeys.join(', ')}`);
      } else {
        clearLeafletMessage();
      }

      const continentsById = buildLookupById(datasets.continents);
      const regionsById = buildLookupById(datasets.regions);
      const nodeById = buildLookupById(datasets.nodes);

      try {
        const pois = await fetchJson('pois.json');
        datasets.pois = Array.isArray(pois) ? pois : [];
      } catch (error) {
        datasets.pois = [];
        console.warn('POI data could not be loaded. Leaflet POI layers are skipped.', error);
      }

    const nodeMarkerById = new Map();
    const routeLayerById = new Map();
    const poiById = new Map();
    const poiMarkerById = new Map();
    const poiLayersByCategory = new Map();
    const poiAliasToId = new Map();
    const nodeBaseStyleById = new Map();
    const routeBaseStyleById = new Map();
    let highlightedNodeIds = [];
   let highlightedRouteIds = [];

        const map = L.map(mapElement, {
         crs: L.CRS.Simple,
         minZoom: -4,
         maxZoom: 4,
         zoomSnap: 0.25,
         wheelPxPerZoomLevel: 80,
         attributionControl: false,
         preferCanvas: true
       });

        // 初期表示: 画像boundsに合わせる
        map.fitBounds(WORLD_IMAGE_BOUNDS, { padding: [24, 24] });
        // 表示可能範囲をデータ座標範囲に制限（余白を少し確保）
        map.setMaxBounds([[-1200, -1200], [11200, 11200]]);

        const WORLD_MAP_IMAGE_URL = '../assets/images/maps/world/world-map.svg';
        const worldMapLayer = L.imageOverlay(WORLD_MAP_IMAGE_URL, WORLD_IMAGE_BOUNDS, {
         opacity: 0.82,
         interactive: false,
         zIndex: 0
       }).addTo(map);

      worldMapLayer.on('error', () => {
        console.warn('[LeafletTransportMap] World map background image failed to load.');
        showLeafletMessage('世界地図背景画像を読み込めませんでした。交通データのみ表示します。');
      });

       const poiPane = map.createPane('poiPane');
       poiPane.style.zIndex = '380';

        const hazardLayer = L.layerGroup().addTo(map);
       const roadLayer = L.layerGroup().addTo(map);
       const railLayer = L.layerGroup().addTo(map);
       const seaLayer = L.layerGroup().addTo(map);
       const airLayer = L.layerGroup().addTo(map);
       const specialLayer = L.layerGroup().addTo(map);
       const nodeLayer = L.layerGroup().addTo(map);

       // 座標グリッドレイヤー (デフォルト非表示)
       const gridLayer = createCoordinateGridLayer();

       // Highlight layers for search results (separate from base layers)
       const routeHighlightLayer = L.layerGroup().addTo(map);
       const nodeHighlightLayer = L.layerGroup().addTo(map);
      const routeHighlightPolylinesById = new Map();
      const nodeHighlightMarkersById = new Map();

    function getNodeStyle(node) {
      return NODE_STYLE_BY_TYPE[node?.type] || DEFAULT_NODE_STYLE;
    }

    function getRouteDefinition(route) {
      const type = route?.type || 'default';
      const definition = ROUTE_DEFINITION_BY_TYPE[type] || ROUTE_DEFINITION_BY_TYPE.default;
      const groupByOverlayName = {
        陸路: roadLayer,
        鉄道: railLayer,
        海路: seaLayer,
        空路: airLayer,
        特殊交通: specialLayer
      };

      return {
        group: groupByOverlayName[definition.overlayName] || specialLayer,
        label: definition.overlayName,
        style: { ...definition.style }
      };
    }

    function getHazardStyle(hazard) {
      const severity = Math.min(Math.max(Number(hazard?.severity) || 1, 1), 5);
      const opacity = 0.1 + severity * 0.05;
      if (hazard?.type === 'ice_sea' || hazard?.type === 'ice') return { color: '#3a6f9a', fillColor: '#5f95c8', fillOpacity: opacity, weight: 2 };
      if (hazard?.type === 'time_distortion') return { color: '#69328e', fillColor: '#8c56bf', fillOpacity: opacity, weight: 2 };
      if (hazard?.type === 'forbidden_zone') return { color: '#6f202a', fillColor: '#9d3947', fillOpacity: opacity + 0.03, weight: 2 };
      if (hazard?.type === 'pirate_sea' || hazard?.type === 'monster_sea') return { color: '#7d2c22', fillColor: '#a54c3d', fillOpacity: opacity, weight: 2 };
      if (hazard?.type === 'storm') return { color: '#5c4575', fillColor: '#8567a8', fillOpacity: opacity, weight: 2 };
      return { color: '#8c3b2c', fillColor: '#b86b44', fillOpacity: opacity, weight: 2 };
    }

    function getPoiLayer(category) {
      if (!poiLayersByCategory.has(category)) {
        const layer = L.layerGroup().addTo(map);
        poiLayersByCategory.set(category, layer);
      }
      return poiLayersByCategory.get(category);
    }

    function bindPopupAndInteractions(layer, html, detailCallback, popupOptions = { maxWidth: 360 }) {
      layer.bindPopup(html, popupOptions);
      if (typeof detailCallback === 'function') {
        layer.on('click', detailCallback);
      }
    }

    function clearHighlights() {
      highlightedRouteIds.forEach(routeId => {
        const layer = routeLayerById.get(routeId);
        const baseStyle = routeBaseStyleById.get(routeId);
        if (layer && baseStyle) {
          layer.setStyle(baseStyle);
        }
      });
      highlightedNodeIds.forEach(nodeId => {
        const marker = nodeMarkerById.get(nodeId);
        const baseStyle = nodeBaseStyleById.get(nodeId);
        if (marker && baseStyle) {
          marker.setStyle(baseStyle);
        }
      });
      highlightedRouteIds = [];
      highlightedNodeIds = [];
    }

    function highlightRoutes(routeIds = []) {
      clearHighlights();
      highlightedRouteIds = routeIds.filter(routeId => routeLayerById.has(routeId));
      highlightedRouteIds.forEach(routeId => {
        const layer = routeLayerById.get(routeId);
        const baseStyle = routeBaseStyleById.get(routeId);
        if (!layer || !baseStyle) {
          return;
        }
        layer.setStyle({
          ...baseStyle,
          color: '#f1c232',
          weight: (baseStyle.weight || 4) + 2,
          opacity: 1
        });
        layer.bringToFront();
      });
    }

    function highlightNodes(nodeIds = []) {
      highlightedNodeIds = nodeIds.filter(nodeId => nodeMarkerById.has(nodeId));
      highlightedNodeIds.forEach(nodeId => {
        const marker = nodeMarkerById.get(nodeId);
        const baseStyle = nodeBaseStyleById.get(nodeId);
        if (!marker || !baseStyle) {
          return;
        }
        marker.setStyle({
          ...baseStyle,
          radius: (baseStyle.radius || 6) + 2,
          color: '#f1c232',
          weight: (baseStyle.weight || 2) + 1,
          fillOpacity: 1
        });
        marker.bringToFront();
      });
    }

    function focusNodes(nodeIds = []) {
      const latLngs = nodeIds
        .map(nodeId => nodeById[nodeId])
        .filter(node => node?.position && isFiniteNumber(node.position.x) && isFiniteNumber(node.position.y))
        .map(node => toLatLng(node.position));

      if (latLngs.length === 0) {
        return;
      }

      if (latLngs.length === 1) {
        map.setView(latLngs[0], Math.max(map.getZoom(), 1));
        return;
      }

      map.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
    }

    // ----- Search Result Highlighting (separate layers) -----

    function highlightRouteNodes(nodeIds = [], nodeTypes = {}) {
      nodeIds.forEach(nodeId => {
        const node = nodeById[nodeId];
        const marker = nodeMarkerById.get(nodeId);
        if (!node || !marker || !node.position) return;

        const baseStyle = nodeBaseStyleById.get(nodeId) || DEFAULT_NODE_STYLE;
        const type = nodeTypes[nodeId] || 'via';
        let fillColor, strokeColor, radius, className;

        if (type === 'start') {
          fillColor = '#4db67e';
          strokeColor = '#1d6e46';
          radius = (baseStyle.radius || 6) + 4;
          className = 'leaflet-route-start';
        } else if (type === 'goal') {
          fillColor = '#cf6d58';
          strokeColor = '#8d3024';
          radius = (baseStyle.radius || 6) + 4;
          className = 'leaflet-route-goal';
        } else {
          fillColor = '#f0c05a';
          strokeColor = '#9b6c14';
          radius = (baseStyle.radius || 6) + 3;
          className = 'leaflet-route-via';
        }

        const highlightMarker = L.circleMarker(toLatLng(node.position), {
          radius,
          fillColor,
          color: strokeColor,
          weight: 4,
          fillOpacity: 0.95,
          className,
          interactive: false
        }).addTo(nodeHighlightLayer);

        nodeHighlightMarkersById.set(nodeId, highlightMarker);
      });
    }

    function highlightRoutePolylines(routeIds = []) {
      routeIds.forEach(routeId => {
        const layer = routeLayerById.get(routeId);
        const baseStyle = routeBaseStyleById.get(routeId);
        if (!layer || !baseStyle) return;

        const latlngs = layer.getLatLngs();
        if (!latlngs || latlngs.length < 2) return;

        const highlightPolyline = L.polyline(latlngs, {
          color: '#f1c232',
          weight: (baseStyle.weight || 4) + 4,
          opacity: 1,
          dashArray: baseStyle.dashArray || undefined,
          className: 'leaflet-route-highlight',
          interactive: false
        }).addTo(routeHighlightLayer);

        routeHighlightPolylinesById.set(routeId, highlightPolyline);
      });
    }

    function fitRouteBounds(result) {
      const allCoords = [];
      result.segments.forEach(segment => {
        if (segment.fromNode?.position) {
          const pos = segment.fromNode.position;
          if (isFiniteNumber(pos.x) && isFiniteNumber(pos.y)) {
            allCoords.push(toLatLng(pos));
          }
        }
        if (segment.toNode?.position) {
          const pos = segment.toNode.position;
          if (isFiniteNumber(pos.x) && isFiniteNumber(pos.y)) {
            allCoords.push(toLatLng(pos));
          }
        }
      });

      if (allCoords.length === 0) return;

      const bounds = L.latLngBounds(allCoords);
      const isMobile = window.matchMedia("(max-width: 720px)").matches;
      const padding = isMobile ? [60, 60] : [40, 40];
      map.fitBounds(bounds, { padding });
    }

    function clearRouteHighlight() {
      // Clear route highlight layer
      routeHighlightLayer.clearLayers();
      routeHighlightPolylinesById.clear();

      // Clear node highlight layer
      nodeHighlightLayer.clearLayers();
      nodeHighlightMarkersById.clear();
    }

    function highlightRoute(result) {
      if (!result?.found || !result.segments) return;

      clearRouteHighlight();

      const routeIds = result.segments.map(seg => seg.route?.id).filter(Boolean);
      highlightRoutePolylines(routeIds);

      const startId = result.segments[0]?.fromNode?.id;
      const goalId = result.segments[result.segments.length - 1]?.toNode?.id;
      const viaIds = result.segments.slice(0, -1)
        .map(seg => seg.toNode?.id)
        .filter(id => id && id !== startId && id !== goalId);

      const nodeTypes = {};
      if (startId) nodeTypes[startId] = 'start';
      if (goalId) nodeTypes[goalId] = 'goal';
      viaIds.forEach(id => { nodeTypes[id] = 'via'; });

      highlightRouteNodes([startId, goalId, ...viaIds], nodeTypes);
      fitRouteBounds(result);
    }

     (datasets.hazards || []).forEach(hazard => {
       if (!hazard?.center || !isFiniteNumber(hazard.center.x) || !isFiniteNumber(hazard.center.y) || !isFiniteNumber(hazard.radius)) {
         console.warn('[LeafletTransportMap] Hazard skipped due to missing center/radius:', hazard?.id || hazard);
         return;
       }

       const circle = L.circle(toLatLng(hazard.center), {
         radius: getAdjustedHazardRadius(hazard),
         ...getHazardStyle(hazard)
       }).addTo(hazardLayer);

      bindPopupAndInteractions(circle, createPopupHtml(
        hazard.name || hazard.id || '危険区域',
        [
          ['ID', hazard.id || '不明'],
          ['種別', hazard.type || 'unknown'],
          ['中心座標', formatCoordinate(hazard.center)],
          ['半径', hazard.radius],
          ['危険度', hazard.severity ?? '不明'],
          ['季節変動', hazard.seasonal ? 'あり' : 'なし'],
          ['活動月', formatMonths(hazard.active_months)]
        ],
        hazard.description
      ));
    });

    (datasets.routes || []).forEach(route => {
      const fromNode = nodeById[route?.from];
      const toNode = nodeById[route?.to];

      if (!fromNode?.position || !toNode?.position || !isFiniteNumber(fromNode.position.x) || !isFiniteNumber(fromNode.position.y) || !isFiniteNumber(toNode.position.x) || !isFiniteNumber(toNode.position.y)) {
        console.warn('[LeafletTransportMap] Route skipped due to missing from/to node:', route?.id || route);
        return;
      }

      const definition = getRouteDefinition(route);
      const polyline = L.polyline([toLatLng(fromNode.position), toLatLng(toNode.position)], definition.style).addTo(definition.group);
      routeLayerById.set(route.id, polyline);
      routeBaseStyleById.set(route.id, { ...definition.style });

      bindPopupAndInteractions(polyline, createPopupHtml(
        route.name || route.id || 'ルート',
        [
          ['ID', route.id || '不明'],
          ['種別', route.type || 'unknown'],
          ['交通モード', route.mode || 'unknown'],
          ['分類', definition.label],
          ['出発地', fromNode.name || route.from || '不明'],
          ['到着地', toNode.name || route.to || '不明'],
          ['距離(km)', route.distance_km ?? '不明'],
          ['推定所要時間(時間)', route.estimated_time_hours ?? '不明'],
          ['危険度', route.danger_level ?? '不明'],
          ['状態', route.status || 'unknown'],
          ['季節運行', route.seasonal ? 'あり' : 'なし'],
          ['活動月', formatMonths(route.active_months)]
        ],
        route.description
      ));
    });

    (datasets.nodes || []).forEach(node => {
      if (!node?.position || !isFiniteNumber(node.position.x) || !isFiniteNumber(node.position.y)) {
        console.warn('[LeafletTransportMap] Node skipped due to missing position:', node?.id || node);
        return;
      }

      const style = getNodeStyle(node);
      const marker = L.circleMarker(toLatLng(node.position), style).addTo(nodeLayer);
      nodeMarkerById.set(node.id, marker);
      nodeBaseStyleById.set(node.id, { ...style });

      bindPopupAndInteractions(marker, createPopupHtml(
        node.name || node.id || 'ノード',
        [
          ['ID', node.id || '不明'],
          ['種別', node.type || 'unknown'],
          ['大陸', continentsById[node.continent_id]?.name || node.continent_id || '不明'],
          ['地域', regionsById[node.region_id]?.name || node.region_id || '不明'],
          ['座標', formatCoordinate(node.position)]
        ],
        node.description
      ));
    });

    (datasets.pois || []).forEach(poi => {
      if (!poi?.id || !poi?.position || !isFiniteNumber(poi.position.x) || !isFiniteNumber(poi.position.y)) {
        console.warn('[LeafletTransportMap] POI skipped due to missing id/position:', poi?.id || poi);
        return;
      }

      const category = poi.category ?? UNKNOWN_POI_CATEGORY;
      const marker = L.circleMarker(toLatLng(poi.position), getPoiStyle(poi)).addTo(getPoiLayer(category));
      poiById.set(poi.id, poi);
      poiMarkerById.set(poi.id, marker);
      (poi.aliases || []).forEach(alias => {
        const aliasKey = normalizePoiLookupKey(alias);
        if (!aliasKey || aliasKey === poi.id) {
          return;
        }
        if (poiAliasToId.has(aliasKey) && poiAliasToId.get(aliasKey) !== poi.id) {
          console.warn('[LeafletTransportMap] Duplicate POI alias skipped:', aliasKey);
          return;
        }
        poiAliasToId.set(aliasKey, poi.id);
      });

      bindPopupAndInteractions(marker, createPoiPopupHtml(poi), undefined, { maxWidth: 320 });
    });

      const overlayLayers = {
        '世界地図背景': worldMapLayer,
        'ノード': nodeLayer,
        '陸路': roadLayer,
        '鉄道': railLayer,
        '海路': seaLayer,
        '空路': airLayer,
        '特殊交通': specialLayer,
        '危険区域': hazardLayer,
        '座標グリッド': gridLayer
      };

      Array.from(poiLayersByCategory.keys())
        .sort((left, right) => getPoiCategoryLabel(left).localeCompare(getPoiCategoryLabel(right), 'ja'))
        .forEach(category => {
          overlayLayers[getPoiCategoryLabel(category)] = poiLayersByCategory.get(category);
        });

      const layersControl = L.control.layers(null, overlayLayers, { collapsed: window.matchMedia("(max-width: 720px)").matches }).addTo(map);

      // Responsive layer control collapse on resize
      const updateLayerControlCollapse = () => {
        const isSmallScreen = window.matchMedia("(max-width: 720px)").matches;
        const controlContainer = document.querySelector('.leaflet-control-layers');
        if (controlContainer) {
          if (isSmallScreen) {
            controlContainer.classList.remove('leaflet-control-layers-expanded');
          } else {
            controlContainer.classList.add('leaflet-control-layers-expanded');
          }
        }
      };
      // Run after a short delay to ensure Leaflet has added its classes
      setTimeout(updateLayerControlCollapse, 0);
      window.addEventListener('resize', () => {
        updateLayerControlCollapse();
      });

     const opacityInput = document.getElementById('world-map-opacity');
     if (opacityInput) {
       opacityInput.addEventListener('input', () => {
         worldMapLayer.setOpacity(Number(opacityInput.value));
       });
     } else {
       console.warn('[LeafletTransportMap] world-map-opacity input not found.');
     }

     /**
      * Public Leaflet map API for future integrations such as route-search highlighting.
      * Consumers can access the raw Leaflet map instance, node/route layer maps,
      * reset the viewport, apply simple node/route highlighting, and control world map opacity.
      */
      window.EternalArcadiaLeafletMap = {
        isAvailable: true,
        map,
        routeLayerById,
        nodeMarkerById,
        poiById,
        poiMarkerById,
        poiLayersByCategory,
        worldMapLayer,
        MAP_COORDINATE_CONFIG,
        transformPosition,
        toLatLng,
        WORLD_COORDINATE_BOUNDS,
        WORLD_IMAGE_BOUNDS,
        fitWorld() {
          map.fitBounds(WORLD_IMAGE_BOUNDS, { padding: [24, 24] });
        },
        setWorldMapOpacity(value) {
          worldMapLayer.setOpacity(value);
        },
        clearHighlights,
        highlightRouteIds(routeIds = []) {
          highlightRoutes(routeIds);
        },
        highlightRoute,
        clearRouteHighlight,
        focusNodeIds(nodeIds = []) {
          highlightNodes(nodeIds);
          focusNodes(nodeIds);
        },
        focusPoi(id) {
          const lookupKey = normalizePoiLookupKey(id);
          const resolvedId = poiById.has(lookupKey) ? lookupKey : poiAliasToId.get(lookupKey);
          const poi = resolvedId ? poiById.get(resolvedId) : null;
          const marker = resolvedId ? poiMarkerById.get(resolvedId) : null;
          if (!poi || !marker) {
            return false;
          }
          const categoryLayer = poiLayersByCategory.get(poi.category ?? UNKNOWN_POI_CATEGORY);
          if (categoryLayer && !map.hasLayer(categoryLayer)) {
            categoryLayer.addTo(map);
          }
          map.setView(marker.getLatLng(), Math.max(map.getZoom(), 1));
          marker.bringToFront();
          marker.openPopup();
          return true;
        }
      };

      if (!datasets.nodes.length && !datasets.routes.length && !datasets.hazards.length) {
        showLeafletMessage(DEFAULT_MESSAGE);
      }
    } catch (error) {
      showLeafletMessage('Leaflet版交通マップを読み込めませんでした。しばらくしてから再度お試しください。');
      window.EternalArcadiaLeafletMap = createLeafletUnavailableApi(error?.message || 'Leaflet initialization failed.');
      console.error('[LeafletTransportMap] Initialization failed.', error);
    }
  });
})();
