(() => {
   const BASE_PATH = '../data/map/';
   const CACHE_BUSTER = '20260507d';

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
  const ROUTE_DEFINITION_BY_TYPE = {
    road: { overlayName: '陸路', style: { color: '#8f5f33', weight: 4.5, opacity: 0.88, lineCap: 'round', lineJoin: 'round' } },
    caravan: { overlayName: '陸路', style: { color: '#b18449', weight: 4.25, opacity: 0.88, dashArray: '9 7 2 7', lineCap: 'round', lineJoin: 'round' } },
    ice_road: { overlayName: '陸路', style: { color: '#87a1b4', weight: 4.1, opacity: 0.82, dashArray: '10 6', lineCap: 'round', lineJoin: 'round' } },
    rail: { overlayName: '鉄道', style: { color: '#575046', weight: 5.25, opacity: 0.9, dashArray: '14 5 2 5', lineCap: 'round', lineJoin: 'round' } },
    sea: { overlayName: '海路', style: { color: '#5f88a9', weight: 4.1, opacity: 0.82, dashArray: '11 9', lineCap: 'round', lineJoin: 'round' } },
    air: { overlayName: '空路', style: { color: '#7b63ab', weight: 3.9, opacity: 0.8, dashArray: '4 10', lineCap: 'round', lineJoin: 'round' } },
    submarine: { overlayName: '特殊交通', style: { color: '#3e8e94', weight: 4, opacity: 0.82, dashArray: '7 6', lineCap: 'round', lineJoin: 'round' } },
    tunnel: { overlayName: '特殊交通', style: { color: '#5f5954', weight: 4, opacity: 0.84, dashArray: '8 8', lineCap: 'round', lineJoin: 'round' } },
    underwater_tunnel: { overlayName: '特殊交通', style: { color: '#377f8f', weight: 4, opacity: 0.84, dashArray: '7 7', lineCap: 'round', lineJoin: 'round' } },
    forbidden_path: { overlayName: '特殊交通', style: { color: '#822f38', weight: 4.1, opacity: 0.85, dashArray: '6 7 2 7', lineCap: 'round', lineJoin: 'round' } },
    default: { overlayName: '特殊交通', style: { color: '#7f5b93', weight: 4, opacity: 0.82, dashArray: '6 9', lineCap: 'round', lineJoin: 'round' } }
  };
  const MOBILE_BREAKPOINT_WIDTH = 720;
  const POI_ICON_SIZE_BY_IMPORTANCE = [20, 22, 24, 28, 32];
  const DEFAULT_NODE_ICON_SIZE = 28;
  const START_GOAL_HIGHLIGHT_RADIUS_RATIO = 0.38;
  const VIA_HIGHLIGHT_RADIUS_RATIO = 0.34;
  const POI_GROUP_SYMBOLS = {
    poi_civic: '♜',
    poi_transport_utility: '◆',
    poi_commerce: '⚖',
    poi_culture_magic: '✦',
    poi_adventure_risk: '⚔',
    poi_other: '•'
  };
  const POI_SYMBOLS_BY_CATEGORY = {
    government: '♜',
    military: '盾',
    transport: '道',
    market: '市',
    shop: '店',
    inn: '宿',
    food: '杯',
    guild: '剣',
    academy: '書',
    temple: '祈',
    culture: '劇',
    entertainment: '楽',
    industry: '工',
    research: '星',
    hazard_support: '警',
    dungeon: '門',
    landmark: '碑',
    residential: '家',
    utility: '水',
    restricted: '封'
  };
  const NODE_SYMBOLS_BY_TYPE = {
    capital: '城',
    city: '塔',
    town: '町',
    port: '錨',
    seaport: '錨',
    airport: '羽',
    air_terminal: '羽',
    carriage_terminal: '道',
    checkpoint: '関',
    oasis: '泉',
    floating_island: '浮',
    underwater_city: '貝',
    marine_port: '港',
    submarine_terminal: '潜',
    warp_gate: '渦',
    forbidden_gate: '封',
    fortress: '砦',
    inn: '宿',
    landmark: '碑'
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
  const POI_GROUP_DEFINITIONS = {
    poi_civic: {
      label: 'POI: 行政・軍事',
      categories: ['government', 'military']
    },
    poi_transport_utility: {
      label: 'POI: 交通・公共',
      categories: ['transport', 'utility', 'residential']
    },
    poi_commerce: {
      label: 'POI: 商業・飲食・宿泊',
      categories: ['market', 'shop', 'inn', 'food', 'industry']
    },
    poi_culture_magic: {
      label: 'POI: 学術・宗教・文化',
      categories: ['academy', 'temple', 'culture', 'entertainment', 'research', 'landmark']
    },
    poi_adventure_risk: {
      label: 'POI: 冒険・危険・制限',
      categories: ['guild', 'hazard_support', 'dungeon', 'restricted']
    },
    poi_other: {
      label: 'POI: その他',
      categories: []
    }
  };
  const POI_STATUS_LABELS = {
    draft: '試験',
    active: '稼働',
    historical: '歴史',
    ruined: '廃墟',
    restricted: '制限',
    sealed: '封印',
    abandoned: '放棄',
    seasonal: '季節',
    hidden: '秘匿'
  };
  const UNKNOWN_VALUE = 'unknown';
  const UNKNOWN_POI_CATEGORY = 'unknown';
  const POI_DISPLAY_SEPARATOR = ' / ';

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

  /**
   * Returns the short Japanese category label used inside POI popups.
   * @param {string | undefined} category
   * @returns {string}
   */
  function getPoiCategoryDisplayName(category) {
    return getPoiCategoryLabel(category).replace(/^POI:\s*/, '');
  }

  /**
   * Resolves a POI category to the configured overlay group ID.
   * @param {string | undefined} category
   * @returns {string}
   */
  function getPoiGroupForCategory(category) {
    const normalizedCategory = category ?? UNKNOWN_POI_CATEGORY;
    const matchedEntry = Object.entries(POI_GROUP_DEFINITIONS).find(([groupId, definition]) => (
      groupId !== 'poi_other' && definition.categories.includes(normalizedCategory)
    ));
    return matchedEntry?.[0] ?? 'poi_other';
  }

  /**
   * Returns a user-facing Japanese status label for a POI.
   * @param {string | undefined} status
   * @returns {string}
   */
  function getPoiStatusLabel(status) {
    return POI_STATUS_LABELS[status] ?? status ?? UNKNOWN_VALUE;
  }

  /**
   * Formats a POI importance value in the supported 1-5 range.
   * @param {number | string | undefined} importance
   * @returns {string}
   */
  function formatPoiImportance(importance) {
    const level = Math.min(Math.max(Number(importance ?? 1) || 1, 1), 5);
    return `★${level}`;
  }

  /**
   * Converts snake_case POI types into a readable popup label.
   * @param {string | undefined} type
   * @returns {string}
   */
  function formatPoiType(type) {
    return String(type ?? UNKNOWN_VALUE).replace(/_/g, ' ');
  }

  function normalizePoiSearchValue(value) {
    return String(value ?? '').trim().toLowerCase();
  }

  function comparePoiText(left, right) {
    return String(left ?? '').localeCompare(String(right ?? ''), 'ja');
  }

  function comparePois(left, right) {
    const continentComparison = comparePoiText(left?.continent_id, right?.continent_id);
    if (continentComparison !== 0) {
      return continentComparison;
    }

    const regionComparison = comparePoiText(left?.region_id, right?.region_id);
    if (regionComparison !== 0) {
      return regionComparison;
    }

    const categoryComparison = comparePoiText(left?.category, right?.category);
    if (categoryComparison !== 0) {
      return categoryComparison;
    }

    const importanceDifference = Number(right?.importance ?? 1) - Number(left?.importance ?? 1);
    if (importanceDifference !== 0) {
      return importanceDifference;
    }

    return comparePoiText(left?.name, right?.name);
  }

  function buildPoiSearchText(poi) {
    return [
      poi?.name,
      poi?.id,
      poi?.category,
      getPoiCategoryDisplayName(poi?.category),
      poi?.type,
      poi?.description,
      ...(Array.isArray(poi?.tags) ? poi.tags : [])
    ].filter(Boolean).map(value => String(value).trim()).join(' ').toLowerCase();
  }

  function isSmallScreenViewport() {
    return window.innerWidth <= MOBILE_BREAKPOINT_WIDTH;
  }

  function normalizeImportance(importance) {
    return Math.min(Math.max(Number(importance ?? 1) || 1, 1), 5);
  }

  function getPoiIconPixelSize(poi) {
    const baseSize = POI_ICON_SIZE_BY_IMPORTANCE[normalizeImportance(poi?.importance) - 1];
    return baseSize + (isSmallScreenViewport() ? 2 : 0);
  }

  function getPoiIconSize(poi) {
    const size = getPoiIconPixelSize(poi);
    return [size, size];
  }

  function getPoiIconAnchor(poi) {
    const size = getPoiIconPixelSize(poi);
    return [size / 2, size / 2];
  }

  function getPoiSymbol(poi) {
    const category = poi?.category ?? UNKNOWN_POI_CATEGORY;
    if (POI_SYMBOLS_BY_CATEGORY[category]) {
      return POI_SYMBOLS_BY_CATEGORY[category];
    }
    return POI_GROUP_SYMBOLS[getPoiGroupForCategory(category)] ?? '•';
  }

  function createPoiIcon(poi) {
    const group = getPoiGroupForCategory(poi?.category);
    const importance = normalizeImportance(poi?.importance);
    const symbol = escapeHtml(getPoiSymbol(poi));
    const size = getPoiIconSize(poi);

    return L.divIcon({
      className: [
        'fantasy-map-icon',
        'fantasy-map-icon--poi',
        `fantasy-map-icon--importance-${importance}`,
        `fantasy-map-icon--${group}`
      ].join(' '),
      html: `<span class="fantasy-map-icon__symbol">${symbol}</span>`,
      iconSize: size,
      iconAnchor: getPoiIconAnchor(poi),
      popupAnchor: [0, Math.round(-size[1] * 0.52)]
    });
  }

  function normalizeNodeType(type) {
    return (String(type ?? 'default').trim().toLowerCase().replace(/\s+/g, '_')) || 'default';
  }

  function getNodeSymbol(node) {
    return NODE_SYMBOLS_BY_TYPE[normalizeNodeType(node?.type)] ?? '塔';
  }

  function getNodeIconPixelSize(node) {
    const normalizedType = normalizeNodeType(node?.type);
    const mobileAdjustment = isSmallScreenViewport() ? 2 : 0;
    if (normalizedType === 'capital') return 36 + mobileAdjustment;
    if (['city', 'floating_island', 'underwater_city'].includes(normalizedType)) return 32 + mobileAdjustment;
    if (['port', 'seaport', 'airport', 'air_terminal', 'warp_gate', 'forbidden_gate'].includes(normalizedType)) return 30 + mobileAdjustment;
    return DEFAULT_NODE_ICON_SIZE + mobileAdjustment;
  }

  function createNodeIcon(node) {
    const type = normalizeNodeType(node?.type);
    const symbol = escapeHtml(getNodeSymbol(node));
    const size = getNodeIconPixelSize(node);

    return L.divIcon({
      className: [
        'fantasy-map-icon',
        'fantasy-map-icon--node',
        `fantasy-map-icon--node-${type}`
      ].join(' '),
      html: `<span class="fantasy-map-icon__symbol">${symbol}</span>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, Math.round(-size * 0.5)]
    });
  }

  function toggleMarkerClass(marker, className, shouldAdd) {
    const element = marker?.getElement?.();
    if (!element || !className) {
      return;
    }
    element.classList.toggle(className, Boolean(shouldAdd));
  }

  function emphasizeMarker(marker, className, duration = 1600) {
    toggleMarkerClass(marker, className, true);
    window.setTimeout(() => {
      toggleMarkerClass(marker, className, false);
    }, duration);
  }

  function createPoiPopupHtml(poi) {
    const metaRows = [
      ['カテゴリ', getPoiCategoryDisplayName(poi.category)],
      ['種別', formatPoiType(poi.type)],
      ['重要度', formatPoiImportance(poi.importance)],
      ['状態', getPoiStatusLabel(poi.status)],
      ['最寄りノード', poi.nearest_node_id ?? '不明']
    ].map(([term, value]) => `
      <dt>${escapeHtml(term)}</dt>
      <dd>${escapeHtml(value)}</dd>
    `).join('');

    const contextRows = [
      ['交通上の役割', poi.transport_role],
      ['経済上の役割', poi.economic_role],
      ['文化上の役割', poi.cultural_role],
      ['危険文脈', poi.risk_context]
    ].filter(([, value]) => value).map(([label, value]) => `
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(value)}</dd>
    `).join('');

    const loreBasisItems = Array.isArray(poi.lore_basis) && poi.lore_basis.length > 0
      ? `<ul class="poi-popup-lore-list">${poi.lore_basis.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : '<p class="poi-popup-note">記載なし</p>';

    const tags = Array.isArray(poi.tags) && poi.tags.length > 0
      ? `<div class="poi-tags">${poi.tags.map(tag => `<span class="poi-tag">${escapeHtml(tag)}</span>`).join('')}</div>`
      : '<p class="poi-tags-empty">タグなし</p>';

    return `
      <article class="leaflet-popup-card poi-popup">
        <h3>${escapeHtml(poi.name || poi.id || 'POI')}</h3>
        <dl class="poi-popup-meta">${metaRows}</dl>
        <section class="poi-popup-section">
          <h4>説明</h4>
          <p>${escapeHtml(poi.description || '説明なし')}</p>
        </section>
        ${contextRows ? `
        <section class="poi-popup-section">
          <h4>主要文脈</h4>
          <dl class="poi-popup-context-list">${contextRows}</dl>
        </section>` : ''}
        ${poi.historical_reason ? `
        <section class="poi-popup-section">
          <h4>歴史的背景</h4>
          <p>${escapeHtml(poi.historical_reason)}</p>
        </section>` : ''}
        <section class="poi-popup-section poi-popup-lore">
          <h4>設定根拠</h4>
          ${loreBasisItems}
        </section>
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
      poiLayersByGroup: new Map(),
      POI_GROUP_DEFINITIONS,
      getPoiGroupForCategory,
      fitWorld() {},
      clearHighlights() {},
      highlightRouteIds() {},
      highlightRoute() {},
      clearRouteHighlight() {},
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
    const poiLayersByGroup = new Map();
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

      map.createPane('hazardPane');
      map.getPane('hazardPane').style.zIndex = '410';
      map.createPane('routePane');
      map.getPane('routePane').style.zIndex = '420';
      map.createPane('poiPane');
      map.getPane('poiPane').style.zIndex = '430';
      map.createPane('nodePane');
      map.getPane('nodePane').style.zIndex = '450';
      map.createPane('highlightPane');
      map.getPane('highlightPane').style.zIndex = '470';
      map.on('popupopen', event => {
        keepPopupInViewport(event.popup);
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
        style: { ...definition.style, pane: 'routePane' }
      };
    }

    function getHazardStyle(hazard) {
      const severity = Math.min(Math.max(Number(hazard?.severity) || 1, 1), 5);
      const fillOpacity = 0.08 + severity * 0.04;
      const baseStyle = {
        pane: 'hazardPane',
        weight: 2.2,
        opacity: 0.82,
        dashArray: '10 6',
        lineCap: 'round'
      };
      if (hazard?.type === 'ice_sea' || hazard?.type === 'ice') return { ...baseStyle, color: '#4d7390', fillColor: '#88accb', fillOpacity };
      if (hazard?.type === 'time_distortion') return { ...baseStyle, color: '#6f4a8e', fillColor: '#9b76b6', fillOpacity: fillOpacity + 0.01 };
      if (hazard?.type === 'forbidden_zone') return { ...baseStyle, color: '#6a2530', fillColor: '#9e4c5a', fillOpacity: fillOpacity + 0.02, dashArray: '7 5 2 5' };
      if (hazard?.type === 'pirate_sea' || hazard?.type === 'monster_sea') return { ...baseStyle, color: '#7b4236', fillColor: '#ab6954', fillOpacity };
      if (hazard?.type === 'storm') return { ...baseStyle, color: '#685579', fillColor: '#8d77a2', fillOpacity };
      return { ...baseStyle, color: '#87523d', fillColor: '#b98868', fillOpacity };
    }

    function getPoiLayer(category) {
      if (!poiLayersByCategory.has(category)) {
        const layer = L.layerGroup();
        const groupId = getPoiGroupForCategory(category);
        const groupLayer = getPoiGroupLayer(groupId);
        groupLayer.addLayer(layer);
        poiLayersByCategory.set(category, layer);
      }
      return poiLayersByCategory.get(category);
    }

    function getPoiGroupLayer(groupId) {
      if (!poiLayersByGroup.has(groupId)) {
        const layer = L.layerGroup().addTo(map);
        poiLayersByGroup.set(groupId, layer);
      }
      return poiLayersByGroup.get(groupId);
    }

    function bindPopupAndInteractions(layer, html, detailCallback, popupOptions = {}) {
      layer.bindPopup(html, { maxWidth: 360, ...popupOptions });
      if (typeof detailCallback === 'function') {
        layer.on('click', detailCallback);
      }
    }

    function keepPopupInViewport(popup) {
      window.requestAnimationFrame(() => {
        const popupElement = popup?.getElement?.() || popup?._container;
        if (!popupElement) {
          return;
        }
        const rect = popupElement.getBoundingClientRect();
        const margin = 16;
        let deltaX = 0;
        let deltaY = 0;

        if (rect.left < margin) {
          deltaX = margin - rect.left;
        } else if (rect.right > window.innerWidth - margin) {
          deltaX = (window.innerWidth - margin) - rect.right;
        }

        if (rect.top < margin) {
          deltaY = margin - rect.top;
        } else if (rect.bottom > window.innerHeight - margin) {
          deltaY = (window.innerHeight - margin) - rect.bottom;
        }

        if (deltaX || deltaY) {
          map.panBy([-deltaX, -deltaY], { animate: false });
        }
      });
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
        if (marker) {
          toggleMarkerClass(marker, 'fantasy-map-icon--highlighted', false);
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
      highlightedNodeIds.forEach(nodeId => {
        const marker = nodeMarkerById.get(nodeId);
        if (marker) {
          toggleMarkerClass(marker, 'fantasy-map-icon--highlighted', false);
        }
      });
      highlightedNodeIds = nodeIds.filter(nodeId => nodeMarkerById.has(nodeId));
      highlightedNodeIds.forEach(nodeId => {
        const marker = nodeMarkerById.get(nodeId);
        if (!marker) {
          return;
        }
        toggleMarkerClass(marker, 'fantasy-map-icon--highlighted', true);
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

        const baseStyle = nodeBaseStyleById.get(nodeId) || { size: DEFAULT_NODE_ICON_SIZE };
        const type = nodeTypes[nodeId] || 'via';
        let fillColor, strokeColor, radius, className;

        if (type === 'start') {
          fillColor = '#4db67e';
          strokeColor = '#1d6e46';
          radius = Math.round((baseStyle.size || DEFAULT_NODE_ICON_SIZE) * START_GOAL_HIGHLIGHT_RADIUS_RATIO);
          className = 'leaflet-route-start';
        } else if (type === 'goal') {
          fillColor = '#cf6d58';
          strokeColor = '#8d3024';
          radius = Math.round((baseStyle.size || DEFAULT_NODE_ICON_SIZE) * START_GOAL_HIGHLIGHT_RADIUS_RATIO);
          className = 'leaflet-route-goal';
        } else {
          fillColor = '#f0c05a';
          strokeColor = '#9b6c14';
          radius = Math.round((baseStyle.size || DEFAULT_NODE_ICON_SIZE) * VIA_HIGHLIGHT_RADIUS_RATIO);
          className = 'leaflet-route-via';
        }

        const highlightMarker = L.circleMarker(toLatLng(node.position), {
          radius,
          fillColor,
          color: strokeColor,
          weight: 4,
          fillOpacity: 0.95,
          className,
          pane: 'highlightPane',
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
          pane: 'highlightPane',
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
      const isMobile = isSmallScreenViewport();
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

      const size = getNodeIconPixelSize(node);
      const marker = L.marker(toLatLng(node.position), {
        icon: createNodeIcon(node),
        pane: 'nodePane',
        keyboard: true,
        riseOnHover: true
      }).addTo(nodeLayer);
      nodeMarkerById.set(node.id, marker);
      nodeBaseStyleById.set(node.id, { size, type: normalizeNodeType(node.type) });

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

    /**
     * Returns popup sizing and auto-pan settings tuned for the current viewport.
     * @returns {{maxWidth: number, minWidth: number, maxHeight: number, keepInView: boolean, autoPanPaddingTopLeft: number[], autoPanPaddingBottomRight: number[]}}
     */
    function getPoiPopupOptions() {
      const isSmallScreen = isSmallScreenViewport();
      return {
        maxWidth: isSmallScreen ? 300 : 360,
        minWidth: isSmallScreen ? 220 : 260,
        maxHeight: isSmallScreen ? 260 : 360,
        keepInView: true,
        autoPanPaddingTopLeft: [24, isSmallScreen ? 180 : 220],
        autoPanPaddingBottomRight: [24, 32]
      };
    }

    (datasets.pois || []).forEach(poi => {
      if (!poi?.id || !poi?.position || !isFiniteNumber(poi.position.x) || !isFiniteNumber(poi.position.y)) {
        console.warn('[LeafletTransportMap] POI skipped due to missing id/position:', poi?.id || poi);
        return;
      }

      const category = poi.category ?? UNKNOWN_POI_CATEGORY;
      const marker = L.marker(toLatLng(poi.position), {
        icon: createPoiIcon(poi),
        pane: 'poiPane',
        keyboard: true,
        riseOnHover: true
      }).addTo(getPoiLayer(category));
      poiById.set(poi.id, poi);
      poiMarkerById.set(poi.id, marker);
      (poi.aliases || []).forEach(alias => {
        if (alias && !poiAliasToId.has(alias)) {
          poiAliasToId.set(alias, poi.id);
        }
      });

      bindPopupAndInteractions(marker, createPoiPopupHtml(poi), undefined, getPoiPopupOptions());
    });

    /**
     * Resolves a POI identifier or registered alias to the canonical POI ID.
     * @param {string | undefined} idOrAlias
     * @returns {string | null}
     */
    function resolvePoiId(idOrAlias) {
      if (poiById.has(idOrAlias)) {
        return idOrAlias;
      }
      return poiAliasToId.get(idOrAlias) ?? null;
    }

    function initializePoiSearchUi(pois) {
      const searchInput = document.getElementById('poi-search-input');
      const categoryFilter = document.getElementById('poi-category-filter');
      const poiSelect = document.getElementById('poi-select');
      const focusButton = document.getElementById('poi-focus-button');
      const message = document.getElementById('poi-search-message');

      if (!searchInput || !categoryFilter || !poiSelect || !focusButton) {
        return;
      }

      const sortedPois = Array.isArray(pois)
        ? pois.filter(poi => poi?.id).slice().sort(comparePois)
        : [];

      const setMessage = text => {
        if (!message) {
          return;
        }
        message.textContent = text;
        message.hidden = !text;
      };

      const updateFocusButtonState = () => {
        focusButton.disabled = !poiSelect.value;
      };

      const categoryValues = Array.from(new Set(sortedPois
        .map(poi => poi?.category ?? UNKNOWN_POI_CATEGORY)))
        .sort((left, right) => {
          const leftLabel = getPoiCategoryDisplayName(left);
          const rightLabel = getPoiCategoryDisplayName(right);
          return comparePoiText(leftLabel, rightLabel);
        });

      categoryFilter.innerHTML = '';
      categoryFilter.append(new Option('すべて', ''));
      categoryValues.forEach(category => {
        categoryFilter.append(new Option(getPoiCategoryDisplayName(category), category));
      });

      const renderPoiOptions = filteredPois => {
        const previousValue = poiSelect.value;
        poiSelect.innerHTML = '';

        if (!filteredPois.length) {
          poiSelect.append(new Option('条件に一致するPOIがありません', ''));
          poiSelect.disabled = true;
          updateFocusButtonState();
          return;
        }

        poiSelect.append(new Option('POIを選択してください', ''));
        filteredPois.forEach(poi => {
          const optionLabel = [
            poi.name || poi.id,
            getPoiCategoryDisplayName(poi.category),
            formatPoiImportance(poi.importance)
          ].filter(Boolean).join(POI_DISPLAY_SEPARATOR);
          poiSelect.append(new Option(optionLabel, poi.id));
        });

        poiSelect.disabled = false;
        if (filteredPois.length === 1) {
          poiSelect.value = filteredPois[0].id;
        } else if (filteredPois.some(poi => poi.id === previousValue)) {
          poiSelect.value = previousValue;
        } else {
          poiSelect.value = '';
        }
        updateFocusButtonState();
      };

      const applyFilters = () => {
        const selectedCategory = categoryFilter.value;
        const searchQuery = normalizePoiSearchValue(searchInput.value);
        const filteredPois = sortedPois.filter(poi => {
          if (selectedCategory && (poi?.category ?? UNKNOWN_POI_CATEGORY) !== selectedCategory) {
            return false;
          }
          if (!searchQuery) {
            return true;
          }
          return buildPoiSearchText(poi).includes(searchQuery);
        });

        renderPoiOptions(filteredPois);

        if (!filteredPois.length) {
          setMessage('条件に一致するPOIがありません。');
        } else if (filteredPois.length === 1) {
          setMessage('候補が1件のため、自動で選択しました。');
        } else {
          setMessage('');
        }
      };

      searchInput.addEventListener('input', applyFilters);
      categoryFilter.addEventListener('change', applyFilters);
      poiSelect.addEventListener('change', () => {
        updateFocusButtonState();
        if (poiSelect.value) {
          setMessage('');
        }
      });
      focusButton.addEventListener('click', () => {
        const poiId = poiSelect.value;
        if (!poiId) {
          setMessage('地図で見るPOIを選択してください。');
          updateFocusButtonState();
          return;
        }

        const focusSucceeded = window.EternalArcadiaLeafletMap?.focusPoi?.(poiId);
        if (focusSucceeded) {
          setMessage('');
          return;
        }

        setMessage('選択したPOIへ移動できませんでした。');
      });

      if (!sortedPois.length) {
        poiSelect.innerHTML = '';
        poiSelect.append(new Option('表示できるPOIがありません', ''));
        poiSelect.disabled = true;
        updateFocusButtonState();
        setMessage('表示できるPOIがありません。');
        return;
      }

      applyFilters();
    }

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

      Object.keys(POI_GROUP_DEFINITIONS).forEach(groupId => {
        const groupLayer = poiLayersByGroup.get(groupId);
        if (groupLayer && groupLayer.getLayers().length > 0) {
          overlayLayers[POI_GROUP_DEFINITIONS[groupId].label] = groupLayer;
        }
      });

      initializePoiSearchUi(datasets.pois || []);

      const layersControl = L.control.layers(null, overlayLayers, { collapsed: isSmallScreenViewport() }).addTo(map);

      // Responsive layer control collapse on resize
      const updateLayerControlCollapse = () => {
        const isSmallScreen = isSmallScreenViewport();
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
        poiLayersByGroup,
        poiAliasToId,
        POI_GROUP_DEFINITIONS,
        getPoiGroupForCategory,
        worldMapLayer,
        MAP_COORDINATE_CONFIG,
        transformPosition,
        toLatLng,
        WORLD_COORDINATE_BOUNDS,
        WORLD_IMAGE_BOUNDS,
        resolvePoiId,
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
          const resolvedId = resolvePoiId(id);
          const poi = resolvedId ? poiById.get(resolvedId) : null;
          const marker = resolvedId ? poiMarkerById.get(resolvedId) : null;
          if (!poi || !marker) {
            return false;
          }
          const groupId = getPoiGroupForCategory(poi.category);
          const groupLayer = poiLayersByGroup.get(groupId);
          if (groupLayer && !map.hasLayer(groupLayer)) {
            groupLayer.addTo(map);
          }
          map.setView(marker.getLatLng(), Math.max(map.getZoom(), 1));
          map.panInside(marker.getLatLng(), {
            paddingTopLeft: [24, isSmallScreenViewport() ? 180 : 220],
            paddingBottomRight: [24, 40],
            animate: false
          });
          marker.bringToFront();
          emphasizeMarker(marker, 'fantasy-map-icon--focused');
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
