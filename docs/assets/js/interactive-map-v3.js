/**
 * Eternal Arcadia interactive map v3.
 *
 * Preferred 512 px tile metadata contract (generate_tiles.py output):
 * {
 *   "tile_size": 512,
 *   "minzoom": 0,
 *   "maxzoom": 3,
 *   "native_zoom": 3,
 *   "tiles": ["{z}/{x}/{y}.webp"],
 *   "master": { "width": 4096, "height": 2730 }
 * }
 *
 * The custom CRS keeps [lat, lng] = [-pixelY, pixelX], and shifts the CRS scale
 * so one source pixel equals one display pixel at metadata.native_zoom.
 * Optional detail sheets publish only accepted manifest URLs; their 512 px
 * tiles are fetched for the current intersection and never decoded as one
 * full-size WebP overlay.
 */
(() => {
  'use strict';

  const Core = window.EternalArcadiaMapV3Core;

  const DATA_BASE = '../data/map/';
  const LEGACY_MAP_URL = '../assets/images/maps/world/world-map-hires.jpg';
  const metaContent = name => document.querySelector(`meta[name="${name}"]`)?.content.trim() || '';
  const runtimeConfig = window.EternalArcadiaMapV3Config || {};
  const BOOTSTRAP_CACHE_KEY =
    metaContent('ea-map-cache-key') || runtimeConfig.cacheKey || 'world-v3-contract-20260720';
  const REQUEST_TIMEOUT_MS = Number(runtimeConfig.requestTimeoutMs) > 0
    ? Number(runtimeConfig.requestTimeoutMs)
    : 8000;
  const ACTIVE_WORLD_RELEASE =
    metaContent('ea-map-world-release') || runtimeConfig.activeWorldRelease || 'world-v1';
  const HTML_TARGET_WORLD_RELEASE = metaContent('ea-map-world-target-release');
  const TARGET_WORLD_RELEASE =
    HTML_TARGET_WORLD_RELEASE || runtimeConfig.targetWorldRelease || 'world-v3';
  const PREVIEW_WORLD_RELEASE = HTML_TARGET_WORLD_RELEASE
    ? Core.worldReleasePreviewFromUrl(window.location.href, HTML_TARGET_WORLD_RELEASE)
    : null;
  const WORLD_RELEASE_URLS = {
    'world-v3': metaContent('ea-map-world-v3-manifest') ||
      runtimeConfig.worldManifestUrls?.['world-v3'] ||
      '../assets/images/maps/tiles/world-v3/metadata.json',
    'world-v2': metaContent('ea-map-world-v2-manifest') ||
      runtimeConfig.worldManifestUrls?.['world-v2'] ||
      '../assets/images/maps/tiles/world-v2/metadata.json',
    'world-v1': metaContent('ea-map-world-v1-manifest') ||
      metaContent('ea-map-tile-manifest') ||
      runtimeConfig.worldManifestUrls?.['world-v1'] ||
      runtimeConfig.tileManifestUrl ||
      '../assets/images/maps/tiles/world-v1/metadata.json'
  };
  const WORLD_FALLBACK_RELEASE_IDS = (
    metaContent('ea-map-world-fallback-releases') ||
    runtimeConfig.worldFallbackReleaseIds?.join(',') ||
    'world-v2,world-v1'
  ).split(',').map(value => value.trim()).filter(Boolean);
  const CONFIGURED_SHEET_TILE_INDEX_URL =
    metaContent('ea-map-sheet-tile-index') ||
    metaContent('ea-map-region-raster-index') ||
    runtimeConfig.sheetTileIndexUrl ||
    runtimeConfig.regionRasterIndexUrl ||
    '';
  const POI_OFFSET_SCALE = 0.4;
  const LEGACY_WORLD_NATIVE_ZOOM = 0;
  const MAX_BOUNDS_PADDING_RATIO = 0.12;
  const REGION_RASTER_PREFETCH_OFFSET = 2;
  const REGION_RASTER_VISIBLE_OFFSET = 2.25;
  const REGION_RASTER_UNLOAD_OFFSET = 1.75;
  const REGION_RASTER_DESKTOP_LIMIT = 2;
  const REGION_RASTER_COARSE_LIMIT = 1;

  const LOD_DEFINITIONS = [
    { id: 'world', label: '世界', minOffset: -Infinity },
    { id: 'continent', label: '大陸', minOffset: 0.75 },
    { id: 'region', label: '地域', minOffset: 2.25 },
    { id: 'detail', label: '詳細', minOffset: 3.75 }
  ];

  const ROUTE_STYLE = {
    road: { color: '#a87543', weight: 2.6, opacity: 0.82 },
    caravan: { color: '#bd8d55', weight: 2.4, opacity: 0.78, dashArray: '8 7' },
    ice_road: { color: '#89aabd', weight: 2.4, opacity: 0.78, dashArray: '9 6' },
    rail: { color: '#ddd4c1', weight: 3.1, opacity: 0.82, dashArray: '12 5' },
    sea: { color: '#5ca2c7', weight: 2.7, opacity: 0.82, dashArray: '12 8' },
    air: { color: '#aa8bd4', weight: 2.5, opacity: 0.78, dashArray: '4 10' },
    submarine: { color: '#4fb1b5', weight: 2.6, opacity: 0.8, dashArray: '7 6' },
    tunnel: { color: '#a8a49b', weight: 2.5, opacity: 0.78, dashArray: '6 6' },
    underwater_tunnel: { color: '#4d99aa', weight: 2.5, opacity: 0.78, dashArray: '6 6' },
    warp: { color: '#db777b', weight: 2.8, opacity: 0.82, dashArray: '3 8' },
    forbidden_path: { color: '#d35d67', weight: 2.8, opacity: 0.82, dashArray: '7 6 2 6' },
    default: { color: '#c7ab7a', weight: 2.5, opacity: 0.78, dashArray: '7 7' }
  };

  const NODE_SYMBOLS = {
    capital: '城',
    city: '都',
    town: '町',
    port: '港',
    seaport: '港',
    airport: '空',
    air_terminal: '空',
    carriage_terminal: '駅',
    checkpoint: '関',
    oasis: '泉',
    floating_island: '浮',
    underwater_city: '海',
    marine_port: '港',
    submarine_terminal: '潜',
    warp_gate: '環',
    forbidden_gate: '封',
    fortress: '砦',
    inn: '宿',
    landmark: '標'
  };

  const TYPE_LABELS = {
    capital: '王都', city: '都市', town: '町', port: '港', seaport: '港',
    airport: '空港', air_terminal: '空中ターミナル', carriage_terminal: '駅馬車ターミナル',
    checkpoint: '検問所', oasis: 'オアシス', floating_island: '浮島',
    underwater_city: '海底都市', marine_port: '海港', submarine_terminal: '潜水ターミナル',
    warp_gate: '転移門', forbidden_gate: '封印門', fortress: '砦', inn: '宿場', landmark: '名所'
  };

  const elements = {
    map: document.getElementById('mapV3'),
    loading: document.getElementById('loadingPanel'),
    loadingMessage: document.getElementById('loadingMessage'),
    error: document.getElementById('mapError'),
    errorDetail: document.getElementById('mapErrorDetail'),
    reload: document.getElementById('reloadButton'),
    baseBadge: document.getElementById('baseModeBadge'),
    baseDescription: document.getElementById('baseLayerDescription'),
    lodBadge: document.getElementById('lodBadge'),
    zoomValue: document.getElementById('zoomValue'),
    coordinateReadout: document.getElementById('coordinateReadout'),
    featureCount: document.getElementById('featureCount'),
    fitButton: document.getElementById('fitMapButton'),
    layerButton: document.getElementById('layerPanelButton'),
    layerPanel: document.getElementById('layerPanel'),
    layerClose: document.getElementById('layerPanelClose'),
    scrim: document.getElementById('panelScrim'),
    helpButton: document.getElementById('helpButton'),
    helpDialog: document.getElementById('helpDialog'),
    announcer: document.getElementById('announcer'),
    search: document.getElementById('mapSearch'),
    searchToggle: document.getElementById('mapSearchToggle'),
    searchSurface: document.getElementById('mapSearchSurface'),
    searchInput: document.getElementById('mapSearchInput'),
    searchClear: document.getElementById('mapSearchClear'),
    searchClose: document.getElementById('mapSearchClose'),
    searchResults: document.getElementById('mapSearchResults'),
    searchStatus: document.getElementById('mapSearchStatus')
  };

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const layerEnabled = Object.fromEntries(
    [...document.querySelectorAll('[data-map-layer]')].map(input => [input.dataset.mapLayer, input.checked])
  );

  let map;
  let worldBounds;
  let currentLod = null;
  let layerRoots;
  let labelLodLayers;
  let nodeLodLayers;
  let poiLodLayers;
  let regionRasterManager;
  let searchController;
  let searchFocusGeneration = 0;
  let runtimeCacheKey = BOOTSTRAP_CACHE_KEY;

  function escapeHtml(value) {
    const element = document.createElement('span');
    element.textContent = String(value ?? '');
    return element.innerHTML;
  }

  function announce(message) {
    if (!elements.announcer) return;
    elements.announcer.textContent = '';
    window.setTimeout(() => {
      elements.announcer.textContent = message;
    }, 30);
  }

  function setLoading(message) {
    if (elements.loadingMessage) elements.loadingMessage.textContent = message;
  }

  function showFatalError(error) {
    console.error('[InteractiveMapV3]', error);
    elements.loading?.classList.add('is-complete');
    if (elements.errorDetail) {
      elements.errorDetail.textContent = String(error?.message || '不明なエラーです。');
    }
    if (elements.error) elements.error.hidden = false;
  }

  async function fetchJson(url, { optional = false, signal = null, cacheKey = runtimeCacheKey } = {}) {
    try {
      return await Core.fetchJsonWithTimeout(url, {
        cacheKey,
        documentUrl: window.location.href,
        timeoutMs: REQUEST_TIMEOUT_MS,
        signal,
        optional
      });
    } catch (error) {
      if (optional) {
        console.info(`[InteractiveMapV3] Optional resource unavailable: ${url}`, error);
        return null;
      }
      throw error;
    }
  }

  async function fetchJsonWithSha256(
    url,
    { optional = false, signal = null, cacheKey = runtimeCacheKey } = {}
  ) {
    try {
      const buffer = await Core.fetchArrayBufferWithTimeout(url, {
        cacheKey,
        documentUrl: window.location.href,
        timeoutMs: REQUEST_TIMEOUT_MS,
        signal,
        optional
      });
      if (!buffer) return null;
      const json = JSON.parse(new window.TextDecoder('utf-8', { fatal: true }).decode(buffer));
      let sha256 = null;
      if (window.crypto?.subtle) {
        const digest = await window.crypto.subtle.digest('SHA-256', buffer);
        sha256 = [...new Uint8Array(digest)]
          .map(byte => byte.toString(16).padStart(2, '0'))
          .join('');
      }
      return Object.freeze({ json, sha256 });
    } catch (error) {
      if (optional) {
        console.info(`[InteractiveMapV3] Optional identity resource unavailable: ${url}`, error);
        return null;
      }
      throw error;
    }
  }

  function worldReleaseConfiguration() {
    return Core.normalizeWorldReleaseConfiguration({
      activeRelease: ACTIVE_WORLD_RELEASE,
      targetRelease: TARGET_WORLD_RELEASE,
      previewRelease: PREVIEW_WORLD_RELEASE,
      cacheKey: BOOTSTRAP_CACHE_KEY,
      releases: Object.entries(WORLD_RELEASE_URLS).map(([id, manifestUrl]) => ({ id, manifestUrl })),
      fallbackReleaseIds: WORLD_FALLBACK_RELEASE_IDS,
      sheetTileIndexUrl: CONFIGURED_SHEET_TILE_INDEX_URL || null
    }, window.location.href);
  }

  async function findWorldTileManifest(configuration, pixelMapping) {
    return Core.selectWorldTileManifestRelease(
      configuration,
      pixelMapping,
      window.location.href,
      candidate => fetchJsonWithSha256(candidate.manifestUrl, { optional: true }),
      (candidate, error) => {
        console.warn(`[InteractiveMapV3] Invalid ${candidate.id} tile manifest; trying rollback.`, error);
      }
    );
  }

  async function findSheetTileIndex(configuration, signal) {
    if (!configuration.sheetTileIndexUrl) return null;
    const index = await fetchJson(configuration.sheetTileIndexUrl, { optional: true, signal });
    return index ? { index, url: configuration.sheetTileIndexUrl } : null;
  }

  function ensureArray(value, name) {
    if (!Array.isArray(value)) throw new Error(`${name} は配列である必要があります。`);
    return value;
  }

  function pixelToLatLng(pixel) {
    return window.L.latLng(-Number(pixel.y), Number(pixel.x));
  }

  function pixelToCoordinates(pixel) {
    return [Number(pixel.x), -Number(pixel.y)];
  }

  function createPositionProjector(nodes, pixelMapping) {
    const nodeById = new Map(nodes.filter(node => node?.id).map(node => [node.id, node]));
    const anchors = nodes.flatMap(node => {
      const pixel = pixelMapping.nodes?.[node.id];
      const position = node.position;
      if (!pixel || !Number.isFinite(Number(position?.x)) || !Number.isFinite(Number(position?.y))) return [];
      return [{ id: node.id, position, pixel }];
    });

    return (position, preferredNodeId = null) => {
      if (!Number.isFinite(Number(position?.x)) || !Number.isFinite(Number(position?.y))) return null;
      const preferredNode = preferredNodeId ? nodeById.get(preferredNodeId) : null;
      const preferredPixel = preferredNodeId ? pixelMapping.nodes?.[preferredNodeId] : null;
      if (preferredNode?.position && preferredPixel) {
        return {
          x: Number(preferredPixel.x) + (Number(position.x) - Number(preferredNode.position.x)) * POI_OFFSET_SCALE,
          y: Number(preferredPixel.y) + (Number(position.y) - Number(preferredNode.position.y)) * POI_OFFSET_SCALE
        };
      }

      const nearest = anchors
        .map(anchor => ({
          anchor,
          distance: Math.hypot(
            Number(position.x) - Number(anchor.position.x),
            Number(position.y) - Number(anchor.position.y)
          )
        }))
        .sort((a, b) => a.distance - b.distance)
        .slice(0, 4);
      if (!nearest.length) return null;

      let xTotal = 0;
      let yTotal = 0;
      let weightTotal = 0;
      nearest.forEach(({ anchor, distance }) => {
        const weight = 1 / Math.max(distance, 1);
        xTotal += (
          Number(anchor.pixel.x) + (Number(position.x) - Number(anchor.position.x)) * POI_OFFSET_SCALE
        ) * weight;
        yTotal += (
          Number(anchor.pixel.y) + (Number(position.y) - Number(anchor.position.y)) * POI_OFFSET_SCALE
        ) * weight;
        weightTotal += weight;
      });
      return { x: xTotal / weightTotal, y: yTotal / weightTotal };
    };
  }

  function routeGeometry(route, pixelNodes) {
    const start = pixelNodes[route.from];
    const end = pixelNodes[route.to];
    if (!start || !end) return null;
    if (route.from !== route.to) {
      return [pixelToCoordinates(start), pixelToCoordinates(end)];
    }
    const radius = 34;
    return Array.from({ length: 17 }, (_, index) => {
      const angle = (Math.PI * 2 * index) / 16;
      return pixelToCoordinates({
        x: Number(start.x) + Math.cos(angle) * radius,
        y: Number(start.y) + Math.sin(angle) * radius
      });
    });
  }

  function makePopup(kind, title, description, rows) {
    const detailRows = rows
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
      .join('');
    return `
      <article class="v3-popup">
        <p class="v3-popup__eyebrow">${escapeHtml(kind)}</p>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(description || '説明は準備中です。')}</p>
        ${detailRows ? `<dl>${detailRows}</dl>` : ''}
      </article>
    `;
  }

  function makeLayerKeyboardAccessible(layer, label) {
    const attach = () => {
      const element = layer.getElement?.() || layer._path;
      if (!element || element.dataset.v3Keyboard === 'true') return;
      element.dataset.v3Keyboard = 'true';
      element.setAttribute('role', 'button');
      element.setAttribute('tabindex', '0');
      element.setAttribute('aria-label', label);
      element.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          layer.openPopup?.();
        }
      });
    };
    layer.on('add', () => window.requestAnimationFrame(attach));
    window.requestAnimationFrame(attach);
  }

  function nodeIcon(node, poi = false) {
    const type = String(node.type || node.category || 'default').toLowerCase();
    let modifier = '';
    if (poi) modifier = 'poi';
    else if (type === 'capital') modifier = 'capital';
    else if (type.includes('port') || type === 'underwater_city') modifier = 'port';
    else if (type.includes('air') || type === 'floating_island') modifier = 'air';
    else if (type.includes('forbidden') || type.includes('warp')) modifier = 'special';
    const symbol = poi ? '•' : (NODE_SYMBOLS[type] || '地');
    const size = poi ? 19 : 26;
    return window.L.divIcon({
      className: 'v3-map-marker-wrap',
      html: `<span class="v3-map-marker v3-map-marker--${modifier || 'default'}"><span>${escapeHtml(symbol)}</span></span>`,
      iconSize: [size, size],
      iconAnchor: poi ? [10, 10] : [13, 25],
      popupAnchor: poi ? [0, -8] : [0, -23]
    });
  }

  function labelIcon(name, kind) {
    const width = kind === 'continent' ? 240 : kind === 'region' ? 190 : 160;
    const height = kind === 'continent' ? 32 : 22;
    return window.L.divIcon({
      className: 'v3-map-label-wrap',
      html: `<span class="v3-map-label v3-map-label--${kind}">${escapeHtml(name)}</span>`,
      iconSize: [width, height],
      iconAnchor: [width / 2, kind === 'node' ? -13 : height / 2]
    });
  }

  function isPrimaryNode(node) {
    const tags = Array.isArray(node.tags) ? node.tags : [];
    return node.type === 'capital' || tags.includes('major_hub') || tags.includes('international') ||
      tags.includes('political_hub') || ['time_port', 'moonlight_grace', 'jade_capital'].includes(node.id);
  }

  function createVectorLayers(datasets, pixelMapping, regionRasterIndex) {
    const { nodes, routes, hazards, continents, regions, pois } = datasets;
    const pixelNodes = pixelMapping.nodes || {};
    const projectPosition = createPositionProjector(nodes, pixelMapping);
    const nodeById = new Map(nodes.filter(node => node?.id).map(node => [node.id, node]));
    const continentById = new Map(continents.filter(item => item?.id).map(item => [item.id, item]));
    const searchTargets = new Map();
    const regionSearchBounds = new Map(regions.map(region => [
      region.id,
      Core.mapSearchRegionLeafletBounds(regionRasterIndex?.rasters, region.id, pixelMapping)
    ]));

    const routeFeatures = routes.flatMap(route => {
      const coordinates = routeGeometry(route, pixelNodes);
      if (!coordinates) return [];
      return [{
        type: 'Feature',
        id: route.id,
        properties: { ...route, mapKind: 'route' },
        geometry: { type: 'LineString', coordinates }
      }];
    });

    const routesLayer = window.L.geoJSON({ type: 'FeatureCollection', features: routeFeatures }, {
      pane: 'routePaneV3',
      style: feature => ({
        ...(ROUTE_STYLE[feature.properties.type] || ROUTE_STYLE.default),
        pane: 'routePaneV3',
        lineCap: 'round',
        lineJoin: 'round'
      }),
      onEachFeature: (feature, layer) => {
        const route = feature.properties;
        const fromName = nodeById.get(route.from)?.name || route.from;
        const toName = nodeById.get(route.to)?.name || route.to;
        layer.bindTooltip(route.name || route.id, { className: 'v3-route-tooltip', sticky: true });
        layer.bindPopup(makePopup('ROUTE', route.name || route.id, route.description, [
          ['区間', `${fromName} → ${toName}`],
          ['方式', route.mode || route.type],
          ['距離', Number.isFinite(Number(route.distance_km)) ? `${Number(route.distance_km).toLocaleString()} km` : null],
          ['状態', route.status]
        ]));
        makeLayerKeyboardAccessible(layer, `${route.name || route.id}の詳細を表示`);
      }
    });

    const nodeFeatures = nodes.flatMap(node => {
      const pixel = pixelNodes[node.id];
      if (!pixel) return [];
      return [{
        type: 'Feature', id: node.id,
        properties: { ...node, mapKind: 'node', primary: isPrimaryNode(node) },
        geometry: { type: 'Point', coordinates: pixelToCoordinates(pixel) }
      }];
    });

    const makeNodeGeoJson = features => window.L.geoJSON({ type: 'FeatureCollection', features }, {
      pane: 'nodePaneV3',
      pointToLayer: (feature, latlng) => window.L.marker(latlng, {
        pane: 'nodePaneV3',
        icon: nodeIcon(feature.properties),
        keyboard: true,
        title: feature.properties.name || feature.properties.id,
        alt: `${feature.properties.name || feature.properties.id}（拠点）`,
        riseOnHover: true
      }),
      onEachFeature: (feature, layer) => {
        const node = feature.properties;
        const popupHtml = makePopup('LOCATION', node.name || node.id, node.description, [
          ['種別', TYPE_LABELS[node.type] || node.type],
          ['大陸', node.continent_id],
          ['地域', node.region_id],
          ['標高', Number.isFinite(Number(node.position?.z)) ? `${Number(node.position.z).toLocaleString()} m` : null]
        ]);
        layer.bindPopup(popupHtml);
        searchTargets.set(`node:${node.id}`, {
          kind: 'node',
          latlng: layer.getLatLng(),
          layer,
          popupHtml
        });
        makeLayerKeyboardAccessible(layer, `${node.name || node.id}の詳細を表示`);
      }
    });

    const primaryFeatures = nodeFeatures.filter(feature => feature.properties.primary);
    const secondaryFeatures = nodeFeatures.filter(feature => !feature.properties.primary);

    const poiFeatures = pois.flatMap(poi => {
      const pixel = projectPosition(poi.position, poi.nearest_node_id);
      if (!pixel) return [];
      return [{
        type: 'Feature', id: poi.id,
        properties: { ...poi, mapKind: 'poi' },
        geometry: { type: 'Point', coordinates: pixelToCoordinates(pixel) }
      }];
    });

    const makePoiGeoJson = features => window.L.geoJSON({ type: 'FeatureCollection', features }, {
      pane: 'poiPaneV3',
      pointToLayer: (feature, latlng) => window.L.marker(latlng, {
        pane: 'poiPaneV3',
        icon: nodeIcon(feature.properties, true),
        keyboard: true,
        title: feature.properties.name || feature.properties.id,
        alt: `${feature.properties.name || feature.properties.id}（施設）`,
        riseOnHover: true
      }),
      onEachFeature: (feature, layer) => {
        const poi = feature.properties;
        const popupHtml = makePopup('POINT OF INTEREST', poi.name || poi.id, poi.description, [
          ['カテゴリ', poi.category],
          ['重要度', Number.isFinite(Number(poi.importance)) ? `★${poi.importance}` : null],
          ['状態', poi.status],
          ['最寄り', nodeById.get(poi.nearest_node_id)?.name || poi.nearest_node_id]
        ]);
        layer.bindPopup(popupHtml);
        searchTargets.set(`poi:${poi.id}`, {
          kind: 'poi',
          latlng: layer.getLatLng(),
          layer,
          popupHtml
        });
        makeLayerKeyboardAccessible(layer, `${poi.name || poi.id}の詳細を表示`);
      }
    });

    const primaryPoiFeatures = poiFeatures.filter(feature => Number(feature.properties.importance || 0) >= 4);
    const secondaryPoiFeatures = poiFeatures.filter(feature => Number(feature.properties.importance || 0) < 4);

    const hazardFeatures = hazards.flatMap(hazard => {
      const pixel = pixelMapping.hazards?.[hazard.id];
      if (!pixel) return [];
      return [{
        type: 'Feature', id: hazard.id,
        properties: { ...hazard, mapKind: 'hazard' },
        geometry: { type: 'Point', coordinates: pixelToCoordinates(pixel) }
      }];
    });

    const hazardsLayer = window.L.geoJSON({ type: 'FeatureCollection', features: hazardFeatures }, {
      pane: 'hazardPaneV3',
      pointToLayer: (feature, latlng) => window.L.circle(latlng, {
        pane: 'hazardPaneV3',
        radius: Math.max(22, Number(feature.properties.radius || 0) * Number(pixelMapping.hazard_radius_scale || 0.4096)),
        color: '#db7771',
        weight: 2,
        dashArray: '6 5',
        opacity: 0.86,
        fillColor: '#b8494c',
        fillOpacity: 0.13
      }),
      onEachFeature: (feature, layer) => {
        const hazard = feature.properties;
        layer.bindTooltip(hazard.name || hazard.id, { className: 'v3-hazard-tooltip' });
        layer.bindPopup(makePopup('HAZARD', hazard.name || hazard.id, hazard.description, [
          ['種別', hazard.type], ['危険度', hazard.danger_level], ['状態', hazard.status]
        ]));
        makeLayerKeyboardAccessible(layer, `${hazard.name || hazard.id}の詳細を表示`);
      }
    });

    const continentLabelFeatures = continents.flatMap(continent => {
      const pixel = pixelMapping.continents?.[continent.id];
      return pixel ? [{
        type: 'Feature', id: continent.id, properties: { name: continent.name, kind: 'continent' },
        geometry: { type: 'Point', coordinates: pixelToCoordinates(pixel) }
      }] : [];
    });

    const regionLabelFeatures = regions.flatMap(region => {
      const regionPixels = nodes
        .filter(node => node.region_id === region.id && pixelNodes[node.id])
        .map(node => pixelNodes[node.id]);
      const pixel = regionPixels.length
        ? {
            x: regionPixels.reduce((sum, value) => sum + Number(value.x), 0) / regionPixels.length,
            y: regionPixels.reduce((sum, value) => sum + Number(value.y), 0) / regionPixels.length
          }
        : projectPosition(region.center);
      return pixel ? [{
        type: 'Feature', id: region.id, properties: { ...region, kind: 'region', mapKind: 'region' },
        geometry: { type: 'Point', coordinates: pixelToCoordinates(pixel) }
      }] : [];
    });

    const nodeLabelFeatures = nodeFeatures.map(feature => ({
      type: 'Feature', id: `${feature.id}-label`,
      properties: { name: feature.properties.name, kind: 'node' },
      geometry: feature.geometry
    }));

    const makeLabelLayer = (features, onEachFeature = null) => window.L.geoJSON({ type: 'FeatureCollection', features }, {
      pane: 'labelPaneV3',
      interactive: false,
      pointToLayer: (feature, latlng) => window.L.marker(latlng, {
        pane: 'labelPaneV3', interactive: false, keyboard: false,
        icon: labelIcon(feature.properties.name, feature.properties.kind)
      }),
      onEachFeature: (feature, layer) => onEachFeature?.(feature, layer)
    });

    const regionLabelsLayer = makeLabelLayer(regionLabelFeatures, (feature, layer) => {
      const region = feature.properties;
      const popupHtml = makePopup('REGION', region.name || region.id, region.description, [
        ['種別', region.type],
        ['大陸', continentById.get(region.continent_id)?.name || region.continent_id]
      ]);
      layer.bindPopup(popupHtml);
      searchTargets.set(`region:${region.id}`, {
        kind: 'region',
        latlng: layer.getLatLng(),
        bounds: regionSearchBounds.get(region.id),
        layer,
        popupHtml
      });
    });

    return {
      routes: routesLayer,
      nodesPrimary: makeNodeGeoJson(primaryFeatures),
      nodesSecondary: makeNodeGeoJson(secondaryFeatures),
      poisPrimary: makePoiGeoJson(primaryPoiFeatures),
      poisSecondary: makePoiGeoJson(secondaryPoiFeatures),
      hazards: hazardsLayer,
      labelsContinent: makeLabelLayer(continentLabelFeatures),
      labelsRegion: regionLabelsLayer,
      labelsNode: makeLabelLayer(nodeLabelFeatures),
      searchTargets,
      renderedCounts: {
        routes: routeFeatures.length,
        nodes: nodeFeatures.length,
        pois: poiFeatures.length,
        hazards: hazardFeatures.length
      }
    };
  }

  function getLod(zoom) {
    const fitZoom = map.getBoundsZoom(worldBounds, false, [18, 18]);
    return Core.selectLod(LOD_DEFINITIONS, zoom, fitZoom);
  }

  function replaceChildren(group, children) {
    group.clearLayers();
    children.forEach(child => group.addLayer(child));
  }

  function applyLayerVisibility() {
    if (!map || !layerRoots || !currentLod) return;
    const lodIndex = LOD_DEFINITIONS.findIndex(item => item.id === currentLod.id);

    const rootVisibility = {
      routes: layerEnabled.routes,
      nodes: layerEnabled.nodes,
      pois: layerEnabled.pois && lodIndex >= 2,
      labels: layerEnabled.labels,
      hazards: layerEnabled.hazards && lodIndex >= 2
    };

    Object.entries(rootVisibility).forEach(([name, visible]) => {
      const layer = layerRoots[name];
      if (visible && !map.hasLayer(layer)) layer.addTo(map);
      if (!visible && map.hasLayer(layer)) map.removeLayer(layer);
    });

    replaceChildren(
      layerRoots.nodes,
      lodIndex <= 1 ? [nodeLodLayers.primary] : [nodeLodLayers.primary, nodeLodLayers.secondary]
    );

    replaceChildren(
      layerRoots.pois,
      lodIndex >= 3 ? [poiLodLayers.primary, poiLodLayers.secondary] : [poiLodLayers.primary]
    );

    const labelChildren = lodIndex === 0
      ? [labelLodLayers.continent]
      : lodIndex === 1
        ? [labelLodLayers.continent, labelLodLayers.region]
        : lodIndex === 2
          ? [labelLodLayers.region]
          : [labelLodLayers.node];
    replaceChildren(layerRoots.labels, labelChildren);
  }

  function updateLod() {
    const zoom = map.getZoom();
    const nextLod = getLod(zoom);
    const changed = currentLod?.id !== nextLod.id;
    currentLod = nextLod;
    elements.lodBadge.textContent = nextLod.label;
    elements.zoomValue.textContent = `Z ${zoom.toFixed(1)}`;
    elements.zoomValue.setAttribute('aria-label', `ズームレベル ${zoom.toFixed(1)}`);
    elements.map.dataset.lod = nextLod.id;
    applyLayerVisibility();
    if (changed) announce(`${nextLod.label}表示に切り替わりました。`);
  }

  function focusSearchTarget(entry, target) {
    const generation = ++searchFocusGeneration;
    if (!target?.latlng) {
      announce(`${entry.label}の地図位置は準備中です。`);
      return false;
    }
    const fitZoom = map.getBoundsZoom(worldBounds, false, [18, 18]);
    const targetZoom = Core.mapSearchTargetZoom(
      entry.kind,
      fitZoom,
      map.getZoom(),
      map.getMaxZoom()
    );
    const regionPadding = [48, 48];
    const regionBounds = entry.kind === 'region' && target.bounds
      ? window.L.latLngBounds(target.bounds)
      : null;
    const navigationCenter = regionBounds ? regionBounds.getCenter() : target.latlng;
    const navigationZoom = regionBounds
      ? Math.min(targetZoom, map.getBoundsZoom(regionBounds, false, regionPadding))
      : targetZoom;
    let opened = false;
    let fallbackTimer = null;

    const openPopup = () => {
      map.off('moveend', openPopup);
      if (generation !== searchFocusGeneration || opened) return;
      opened = true;
      if (fallbackTimer !== null) window.clearTimeout(fallbackTimer);
      if (target.layer && map.hasLayer(target.layer)) {
        target.layer.openPopup();
      } else {
        window.L.popup({ maxWidth: 320, autoPan: true, closeButton: true })
          .setLatLng(target.latlng)
          .setContent(target.popupHtml)
          .openOn(map);
      }
      announce(`${entry.kindLabel}「${entry.label}」を表示しました。`);
    };

    const centerMatches = map.getCenter().equals(navigationCenter);
    const zoomMatches = Math.abs(map.getZoom() - navigationZoom) < 0.001;
    if (centerMatches && zoomMatches) {
      openPopup();
    } else {
      map.once('moveend', openPopup);
      fallbackTimer = window.setTimeout(openPopup, reducedMotion ? 0 : 500);
      if (regionBounds) {
        map.fitBounds(regionBounds, {
          padding: regionPadding,
          maxZoom: targetZoom,
          animate: !reducedMotion
        });
      } else {
        map.setView(target.latlng, targetZoom, { animate: !reducedMotion });
      }
    }
    return true;
  }

  function createMapSearchController(searchEntries, searchTargets) {
    const mobileMedia = window.matchMedia('(max-width: 760px)');
    let results = [];
    let activeIndex = -1;
    let composing = false;
    let mobileOpen = false;

    function syncMobileViewportHeight() {
      const height = Number(window.visualViewport?.height);
      if (height > 0) {
        elements.search.style.setProperty('--map-search-viewport-height', `${Math.floor(height)}px`);
      } else {
        elements.search.style.removeProperty('--map-search-viewport-height');
      }
    }

    function setStatus(message) {
      if (!elements.searchStatus) return;
      elements.searchStatus.textContent = message;
    }

    function setResultsExpanded(expanded) {
      elements.searchResults.hidden = !expanded;
      elements.searchInput.setAttribute('aria-expanded', String(expanded));
      if (!expanded) {
        activeIndex = -1;
        elements.searchInput.removeAttribute('aria-activedescendant');
      }
    }

    function updateActiveOption(nextIndex) {
      if (!results.length) {
        activeIndex = -1;
        elements.searchInput.removeAttribute('aria-activedescendant');
        return;
      }
      activeIndex = ((nextIndex % results.length) + results.length) % results.length;
      [...elements.searchResults.querySelectorAll('[role="option"]')].forEach((option, index) => {
        option.setAttribute('aria-selected', String(index === activeIndex));
      });
      const activeOption = document.getElementById(`map-search-option-${activeIndex}`);
      if (activeOption) {
        elements.searchInput.setAttribute('aria-activedescendant', activeOption.id);
        activeOption.scrollIntoView({ block: 'nearest' });
      }
    }

    function closeResults() {
      setResultsExpanded(false);
      elements.searchResults.replaceChildren();
    }

    function setMobileOpen(open, restoreFocus = false) {
      if (!mobileMedia.matches) return;
      mobileOpen = Boolean(open);
      elements.search.classList.toggle('is-open', mobileOpen);
      elements.searchToggle.setAttribute('aria-expanded', String(mobileOpen));
      elements.searchSurface.setAttribute('aria-hidden', String(!mobileOpen));
      elements.searchSurface.inert = !mobileOpen;
      if (mobileOpen) {
        if (elements.layerPanel?.classList.contains('is-open')) setPanelOpen(false);
        window.requestAnimationFrame(() => elements.searchInput.focus());
      } else {
        closeResults();
        if (restoreFocus) elements.searchToggle.focus();
        else if (elements.searchSurface.contains(document.activeElement)) {
          elements.map.focus({ preventScroll: true });
        }
      }
    }

    function syncResponsiveMode() {
      const focusWasInSurface = elements.searchSurface.contains(document.activeElement);
      closeResults();
      mobileOpen = false;
      elements.search.classList.remove('is-open');
      elements.searchToggle.setAttribute('aria-expanded', 'false');
      if (mobileMedia.matches) {
        if (focusWasInSurface) elements.searchToggle.focus({ preventScroll: true });
        elements.searchSurface.setAttribute('aria-hidden', 'true');
        elements.searchSurface.inert = true;
      } else {
        elements.searchSurface.setAttribute('aria-hidden', 'false');
        elements.searchSurface.inert = false;
      }
    }

    function selectResult(entry) {
      elements.searchInput.value = entry.label;
      elements.searchClear.hidden = false;
      closeResults();
      setStatus(`${entry.kindLabel}「${entry.label}」を選択しました。`);
      if (mobileMedia.matches) {
        setMobileOpen(false, false);
        elements.map.focus({ preventScroll: true });
      }
      focusSearchTarget(entry, searchTargets.get(entry.key));
    }

    function renderResults() {
      elements.searchResults.replaceChildren();
      activeIndex = -1;

      if (!results.length) {
        const empty = document.createElement('p');
        empty.className = 'map-search__empty';
        empty.setAttribute('role', 'option');
        empty.setAttribute('aria-disabled', 'true');
        empty.textContent = '該当する場所はありません。';
        elements.searchResults.append(empty);
        setResultsExpanded(true);
        return;
      }

      results.forEach((entry, index) => {
        const option = document.createElement('div');
        option.id = `map-search-option-${index}`;
        option.className = 'map-search__option';
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.setAttribute('tabindex', '-1');

        const copy = document.createElement('span');
        copy.className = 'map-search__option-copy';
        const name = document.createElement('strong');
        name.textContent = entry.label;
        copy.append(name);
        if (entry.context) {
          const context = document.createElement('small');
          context.textContent = entry.context;
          copy.append(context);
        }
        const kind = document.createElement('span');
        kind.className = 'map-search__option-kind';
        kind.textContent = entry.kindLabel;
        option.append(copy, kind);
        option.addEventListener('pointerdown', event => event.preventDefault());
        option.addEventListener('click', () => selectResult(entry));
        elements.searchResults.append(option);
      });
      setResultsExpanded(true);
      updateActiveOption(0);
    }

    function refreshResults() {
      const query = elements.searchInput.value;
      elements.searchClear.hidden = !query;
      if (!Core.normalizeMapSearchText(query)) {
        results = [];
        closeResults();
        setStatus('');
        return;
      }
      results = Core.filterMapSearchEntries(searchEntries, query, 8);
      renderResults();
      setStatus(results.length ? `${results.length}件の候補があります。` : '該当する場所はありません。');
    }

    elements.searchToggle.addEventListener('click', () => {
      if (!mobileMedia.matches) return;
      setMobileOpen(!mobileOpen, mobileOpen);
    });
    elements.searchInput.addEventListener('focus', () => {
      if (Core.normalizeMapSearchText(elements.searchInput.value)) refreshResults();
    });
    elements.searchInput.addEventListener('input', event => {
      if (composing || event.isComposing) return;
      refreshResults();
    });
    elements.searchInput.addEventListener('compositionstart', () => {
      composing = true;
    });
    elements.searchInput.addEventListener('compositionend', () => {
      composing = false;
      refreshResults();
    });
    elements.searchInput.addEventListener('keydown', event => {
      if (composing || event.isComposing || event.keyCode === 229) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (!Core.normalizeMapSearchText(elements.searchInput.value)) return;
        event.preventDefault();
        event.stopPropagation();
        if (elements.searchResults.hidden) refreshResults();
        if (results.length) updateActiveOption(
          event.key === 'ArrowDown' ? activeIndex + 1 : (activeIndex < 0 ? results.length - 1 : activeIndex - 1)
        );
      } else if (event.key === 'Enter') {
        if (!results.length || elements.searchResults.hidden) return;
        event.preventDefault();
        event.stopPropagation();
        selectResult(results[activeIndex >= 0 ? activeIndex : 0]);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        if (!elements.searchResults.hidden) closeResults();
        else if (mobileMedia.matches && mobileOpen) setMobileOpen(false, true);
      } else if (event.key === 'Tab') {
        closeResults();
      }
    });
    elements.searchSurface.addEventListener('keydown', event => {
      if (event.target === elements.searchInput || event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      if (!elements.searchResults.hidden) closeResults();
      else if (mobileMedia.matches && mobileOpen) setMobileOpen(false, true);
      else elements.searchInput.focus();
    });
    elements.searchClear.addEventListener('click', () => {
      elements.searchInput.value = '';
      elements.searchClear.hidden = true;
      results = [];
      closeResults();
      setStatus('検索語を消去しました。');
      elements.searchInput.focus();
    });
    elements.searchClose.addEventListener('click', () => {
      setMobileOpen(false, true);
    });
    document.addEventListener('pointerdown', event => {
      if (elements.search.contains(event.target)) return;
      closeResults();
      if (mobileMedia.matches && mobileOpen) setMobileOpen(false, false);
    });
    if (typeof mobileMedia.addEventListener === 'function') {
      mobileMedia.addEventListener('change', syncResponsiveMode);
    } else {
      mobileMedia.addListener(syncResponsiveMode);
    }
    window.visualViewport?.addEventListener('resize', syncMobileViewportHeight);

    elements.searchInput.disabled = false;
    syncMobileViewportHeight();
    syncResponsiveMode();
    return Object.freeze({
      close({ restoreFocus = false } = {}) {
        closeResults();
        if (mobileMedia.matches && mobileOpen) setMobileOpen(false, restoreFocus);
      },
      focus() {
        if (mobileMedia.matches && !mobileOpen) setMobileOpen(true);
        else elements.searchInput.focus();
      }
    });
  }

  function createRegionRasterManager(index, pixelMapping, worldNativeZoom) {
    const rasters = Array.isArray(index?.rasters) ? index.rasters : [];
    const rootId = index?.rootId || 'sheet_world';
    const fallbackNativeZoom = Number.isFinite(Number(worldNativeZoom))
      ? Number(worldNativeZoom)
      : LEGACY_WORLD_NATIVE_ZOOM;
    const byId = new Map(rasters.map(entry => [entry.id, entry]));
    const states = new Map();
    const failedIds = new Set();
    const coarsePointer = window.matchMedia('(pointer: coarse)');
    let generation = 0;
    let active = true;

    function zoomOffset() {
      return map.getZoom() - map.getBoundsZoom(worldBounds, false, [18, 18]);
    }

    function thresholds() {
      const fitZoom = map.getBoundsZoom(worldBounds, false, [18, 18]);
      const worldNativeOffset = fallbackNativeZoom - fitZoom;
      const visible = Math.min(REGION_RASTER_VISIBLE_OFFSET, worldNativeOffset);
      const prefetch = Math.min(REGION_RASTER_PREFETCH_OFFSET, visible - 0.25);
      const unload = Math.min(REGION_RASTER_UNLOAD_OFFSET, prefetch - 0.25);
      return { unload, prefetch, visible };
    }

    function currentViewportBounds() {
      const bounds = map.getBounds();
      return Core.leafletBoundsToEaWorldBounds({
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth()
      }, pixelMapping);
    }

    function tileLeafletBounds(bounds) {
      const width = Number(pixelMapping.image_width);
      const height = Number(pixelMapping.image_height);
      const west = bounds[0] / Core.EA_WORLD_EXTENT * width;
      const north = bounds[1] / Core.EA_WORLD_EXTENT * height;
      const east = bounds[2] / Core.EA_WORLD_EXTENT * width;
      const south = bounds[3] / Core.EA_WORLD_EXTENT * height;
      return [[-south, west], [-north, east]];
    }

    function removeTile(tileState) {
      tileState.controller?.abort('sheet tile no longer intersects the viewport');
      if (tileState.overlay && map.hasLayer(tileState.overlay)) map.removeLayer(tileState.overlay);
      if (tileState.objectUrl) window.URL.revokeObjectURL(tileState.objectUrl);
      tileState.overlay = null;
      tileState.objectUrl = null;
    }

    function clearTiles(state) {
      state.tiles.forEach(removeTile);
      state.tiles.clear();
      state.requiredTileKeys.clear();
      state.requiredNativeZoom = null;
      state.visible = false;
    }

    function stateViewportReady(state) {
      return state.visible && !state.disposed &&
        Core.allRequiredTilesReady(state.requiredTileKeys, state.tiles);
    }

    function disposeState(id) {
      const state = states.get(id);
      if (!state) return;
      state.disposed = true;
      state.manifestController?.abort('sheet is no longer selected');
      clearTiles(state);
      states.delete(id);
    }

    function unloadAll() {
      [...states.keys()].forEach(disposeState);
    }

    function syncNativeZoomLimit(viewportBounds = currentViewportBounds()) {
      const readyNativeZooms = new Map([...states.values()]
        .filter(stateViewportReady)
        .map(state => [state.entry.id, state.requiredNativeZoom]));
      const nextLimit = Core.nativeZoomLimitForViewport(
        rasters,
        viewportBounds,
        fallbackNativeZoom,
        readyNativeZooms
      );
      if (Math.abs(map.getMaxZoom() - nextLimit) > 0.001) map.setMaxZoom(nextLimit);
      if (map.getZoom() > nextLimit) map.setZoom(nextLimit, { animate: false });
      return nextLimit;
    }

    function markFailed(entry, state, error) {
      if (states.get(entry.id) !== state || state.disposed || state.status === 'failed') return;
      state.status = 'failed';
      state.manifestController?.abort('sheet failed');
      clearTiles(state);
      failedIds.add(entry.id);
      const readyIds = [rootId, ...[...states.values()]
        .filter(candidate => stateViewportReady(candidate) && candidate !== state)
        .map(candidate => candidate.entry.id)];
      const fallbackId = Core.nearestReadyParentId(rasters, entry.id, readyIds, rootId) || rootId;
      console.warn(
        `[InteractiveMapV3] Sheet tiles unavailable; retaining nearest parent ${fallbackId}: ${entry.id}`,
        error
      );
      syncNativeZoomLimit();
      window.requestAnimationFrame(evaluate);
    }

    async function validateTileBlob(blob, signal) {
      if (signal.aborted) throw new DOMException('tile request aborted', 'AbortError');
      const mimeType = String(blob?.type || '').split(';', 1)[0].trim().toLowerCase();
      if (mimeType !== 'image/webp') {
        throw new Error(`sheet tile MIME must be image/webp (received ${mimeType || 'empty'})`);
      }
      if (typeof window.createImageBitmap !== 'function') {
        throw new Error('sheet tile decoder is unavailable');
      }
      const bitmap = await window.createImageBitmap(blob);
      try {
        if (bitmap.width !== Core.EXPECTED_TILE_SIZE || bitmap.height !== Core.EXPECTED_TILE_SIZE) {
          throw new Error(
            `sheet tile dimensions must be ${Core.EXPECTED_TILE_SIZE}x${Core.EXPECTED_TILE_SIZE}`
          );
        }
      } finally {
        bitmap.close();
      }
      if (signal.aborted) throw new DOMException('tile request aborted', 'AbortError');
    }

    function beginTile(state, tile) {
      const controller = new AbortController();
      const tileState = {
        key: tile.key,
        controller,
        overlay: null,
        objectUrl: null,
        status: 'loading'
      };
      state.tiles.set(tile.key, tileState);
      Core.fetchBlobWithTimeout(tile.url, {
        cacheKey: runtimeCacheKey,
        documentUrl: window.location.href,
        timeoutMs: REQUEST_TIMEOUT_MS,
        signal: controller.signal
      }).then(async blob => {
        if (state.disposed || state.tiles.get(tile.key) !== tileState) return;
        await validateTileBlob(blob, controller.signal);
        if (state.disposed || state.tiles.get(tile.key) !== tileState) return;
        const objectUrl = window.URL.createObjectURL(blob);
        tileState.objectUrl = objectUrl;
        const overlay = window.L.imageOverlay(objectUrl, tileLeafletBounds(tile.bounds), {
          pane: `sheetRasterPaneV3-${state.entry.depth}`,
          opacity: 1,
          interactive: false,
          className: 'ea-sheet-tile',
          alt: `${state.entry.name}の高詳細地図タイル`
        });
        tileState.overlay = overlay;
        overlay.once('load', () => {
          if (state.disposed || state.tiles.get(tile.key) !== tileState) return;
          tileState.status = 'ready';
          const viewportReady = stateViewportReady(state);
          state.status = viewportReady ? 'ready' : 'tiles-loading';
          syncNativeZoomLimit();
          if (viewportReady) window.requestAnimationFrame(evaluate);
        });
        overlay.once('error', error => markFailed(state.entry, state, error));
        overlay.addTo(map);
        state.visible = true;
      }).catch(error => {
        if (controller.signal.aborted || state.disposed || state.tiles.get(tile.key) !== tileState) return;
        markFailed(state.entry, state, error);
      });
    }

    function syncTiles(state, viewportBounds) {
      if (!state.manifest || state.disposed || state.status === 'failed') return;
      const displayZoom = map.getZoom();
      // At the current gate, prefetch exactly the next integer source level.
      // This avoids unlocking a depth before its complete viewport tile set is
      // ready, while still allowing the gate to advance one verified level.
      const sourceRequestZoom = displayZoom >= map.getMaxZoom() - 1e-7
        ? displayZoom + 1e-4
        : displayZoom;
      const desired = Core.sheetTilesForViewport(
        state.entry,
        state.manifest,
        viewportBounds,
        sourceRequestZoom
      );
      const desiredKeys = new Set(desired.map(tile => tile.key));
      state.requiredTileKeys = desiredKeys;
      state.requiredNativeZoom = desired.length > 0 ? desired[0].zoom : null;
      [...state.tiles.keys()].filter(key => !desiredKeys.has(key)).forEach(key => {
        removeTile(state.tiles.get(key));
        state.tiles.delete(key);
      });
      desired.forEach(tile => {
        if (!state.tiles.has(tile.key)) beginTile(state, tile);
      });
      state.visible = desired.length > 0;
      state.status = stateViewportReady(state) ? 'ready' : 'tiles-loading';
    }

    function beginManifest(entry, viewportBounds) {
      const controller = new AbortController();
      const state = {
        entry,
        status: 'manifest-loading',
        manifestController: controller,
        manifest: null,
        tiles: new Map(),
        requiredTileKeys: new Set(),
        requiredNativeZoom: null,
        visible: false,
        disposed: false
      };
      states.set(entry.id, state);
      fetchJson(entry.manifestUrl, { signal: controller.signal }).then(manifest => {
        if (state.disposed || states.get(entry.id) !== state) return;
        state.manifest = Core.normalizeSheetTileManifest(
          { manifest, url: entry.manifestUrl },
          entry,
          pixelMapping,
          window.location.href,
          fallbackNativeZoom
        );
        state.status = 'manifest-ready';
        syncTiles(state, currentViewportBounds() || viewportBounds);
      }).catch(error => {
        if (controller.signal.aborted || state.disposed) return;
        markFailed(entry, state, error);
      });
    }

    function parentReady(entry) {
      if (entry.parentId === rootId) return true;
      const parentState = states.get(entry.parentId);
      if (!parentState || !stateViewportReady(parentState)) return false;
      const parent = byId.get(entry.parentId);
      return !parent || map.getZoom() >= parent.nativeZoom - 0.5;
    }

    function evaluate() {
      if (!active) return;
      generation += 1;
      const offset = zoomOffset();
      const activation = thresholds();
      if (offset < activation.unload) {
        unloadAll();
        syncNativeZoomLimit();
        return;
      }
      const viewportBounds = currentViewportBounds();
      if (!viewportBounds) {
        unloadAll();
        syncNativeZoomLimit(null);
        return;
      }
      if (offset < activation.prefetch) {
        unloadAll();
        syncNativeZoomLimit(viewportBounds);
        return;
      }

      const limit = coarsePointer.matches ? REGION_RASTER_COARSE_LIMIT : REGION_RASTER_DESKTOP_LIMIT;
      const leaves = Core.rankRegionRasters(rasters, viewportBounds)
        .filter(entry => !failedIds.has(entry.id) && parentReady(entry))
        .slice(0, limit);
      const selected = Core.expandRasterSelectionWithParents(rasters, leaves.map(entry => entry.id));
      const selectedIds = new Set(selected.map(entry => entry.id));
      [...states.keys()].filter(id => !selectedIds.has(id)).forEach(disposeState);
      selected.forEach(entry => {
        const state = states.get(entry.id);
        if (!state) beginManifest(entry, viewportBounds);
        else syncTiles(state, viewportBounds);
      });
      syncNativeZoomLimit(viewportBounds);
    }

    function destroy() {
      active = false;
      generation += 1;
      map.off('moveend', evaluate);
      map.off('zoomend', evaluate);
      map.off('resize', evaluate);
      unloadAll();
      syncNativeZoomLimit();
    }

    map.on('moveend', evaluate);
    map.on('zoomend', evaluate);
    map.on('resize', evaluate);
    evaluate();

    return Object.freeze({
      evaluate,
      destroy,
      getState() {
        const sheetStates = [...states.values()]
          .map(state => ({
            id: state.entry.id,
            status: state.status,
            viewportReady: stateViewportReady(state),
            visible: state.visible,
            requiredNativeZoom: state.requiredNativeZoom,
            requiredTileCount: state.requiredTileKeys.size,
            readyTileCount: [...state.tiles.values()].filter(tile => tile.status === 'ready').length
          }))
          .sort((left, right) => left.id.localeCompare(right.id));
        return {
          generation,
          available: rasters.length,
          loading: [...states.values()].filter(state =>
            state.status === 'manifest-loading' || state.status === 'manifest-ready' ||
            state.status === 'tiles-loading').length,
          ready: [...states.values()].filter(stateViewportReady).length,
          failed: failedIds.size,
          failedIds: [...failedIds].sort(),
          visible: [...states.values()].filter(state => state.visible).map(state => state.entry.id),
          sheets: sheetStates,
          maxNativeZoom: map.getMaxZoom()
        };
      }
    });
  }

  function setPanelOpen(open) {
    const panel = elements.layerPanel;
    if (!panel) return;
    panel.classList.toggle('is-open', open);
    panel.setAttribute('aria-hidden', String(!open));
    panel.inert = !open;
    elements.layerButton.setAttribute('aria-expanded', String(open));
    elements.layerButton.setAttribute('aria-label', open ? '表示レイヤーを閉じる' : '表示レイヤーを開く');
    elements.scrim.hidden = !open;
    window.setTimeout(() => {
      if (panel.classList.contains('is-open') !== open) return;
      const focusTarget = open ? elements.layerClose : elements.layerButton;
      focusTarget?.focus({ preventScroll: true });
    }, 50);
  }

  function initializeUi() {
    elements.reload?.addEventListener('click', () => window.location.reload());
    elements.layerButton?.addEventListener('click', () => {
      searchController?.close();
      setPanelOpen(!elements.layerPanel.classList.contains('is-open'));
    });
    elements.layerClose?.addEventListener('click', () => setPanelOpen(false));
    elements.scrim?.addEventListener('click', () => setPanelOpen(false));
    elements.helpButton?.addEventListener('click', () => {
      searchController?.close();
      if (typeof elements.helpDialog?.showModal === 'function') elements.helpDialog.showModal();
    });
    elements.fitButton?.addEventListener('click', () => {
      if (map && worldBounds) map.fitBounds(worldBounds, { padding: [18, 18], animate: !reducedMotion });
    });
    document.querySelectorAll('[data-map-layer]').forEach(input => {
      input.addEventListener('change', () => {
        layerEnabled[input.dataset.mapLayer] = input.checked;
        applyLayerVisibility();
        announce(`${input.closest('label')?.querySelector('strong')?.textContent || 'レイヤー'}を${input.checked ? '有効' : '無効'}にしました。`);
      });
    });
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      if (elements.layerPanel?.classList.contains('is-open')) setPanelOpen(false);
      else map?.closePopup();
    });
  }

  function createMap(imageWidth, imageHeight, tileManifest, regionRasterIndex) {
    const padding = Math.max(imageWidth, imageHeight) * MAX_BOUNDS_PADDING_RATIO;
    worldBounds = window.L.latLngBounds([[-imageHeight, 0], [0, imageWidth]]);
    const nativeZoom = tileManifest?.nativeZoom ?? LEGACY_WORLD_NATIVE_ZOOM;
    const pixelCrs = window.L.Util.extend({}, window.L.CRS.Simple, {
      scale: zoom => Core.scaleAtZoom(zoom, nativeZoom),
      zoom: scale => Core.zoomAtScale(scale, nativeZoom)
    });
    map = window.L.map(elements.map, {
      crs: pixelCrs,
      minZoom: -6,
      maxZoom: nativeZoom,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      wheelPxPerZoomLevel: 90,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: false,
      keyboard: true,
      keyboardPanDelta: 90,
      tapTolerance: 20,
      bounceAtZoomLimits: false,
      zoomAnimation: !reducedMotion,
      fadeAnimation: !reducedMotion,
      markerZoomAnimation: !reducedMotion,
      maxBounds: [[-imageHeight - padding, -padding], [padding, imageWidth + padding]],
      maxBoundsViscosity: 0.78
    });

    window.L.control.zoom({ position: 'bottomright', zoomInTitle: '拡大', zoomOutTitle: '縮小' }).addTo(map);
    map.createPane('rasterFallbackPaneV3').style.zIndex = '200';
    map.createPane('rasterTilePaneV3').style.zIndex = '210';
    for (let depth = 1; depth <= 4; depth += 1) {
      const pane = map.createPane(`sheetRasterPaneV3-${depth}`);
      pane.style.zIndex = String(220 + depth);
      pane.style.pointerEvents = 'none';
    }
    map.createPane('hazardPaneV3').style.zIndex = '390';
    map.createPane('routePaneV3').style.zIndex = '410';
    map.createPane('poiPaneV3').style.zIndex = '430';
    map.createPane('nodePaneV3').style.zIndex = '450';
    map.createPane('labelPaneV3').style.zIndex = '470';
    map.getPane('labelPaneV3').style.pointerEvents = 'none';

    window.L.imageOverlay(LEGACY_MAP_URL, worldBounds, {
      pane: 'rasterFallbackPaneV3',
      opacity: 1,
      interactive: false,
      alt: 'エターナル・アルカディア世界地図'
    }).addTo(map);

    if (tileManifest) {
      let loadedTiles = 0;
      let failedTiles = 0;
      const tileLayer = window.L.tileLayer(tileManifest.urlTemplate, {
        pane: 'rasterTilePaneV3',
        tileSize: tileManifest.tileSize,
        minZoom: -6,
        // Leaflet must retain the world parent while deeper sheets are shown.
        // maxNativeZoom clamps the requested source to the world resolution;
        // maxZoom keeps that fallback visible through the Phase 5 contract depth.
        maxZoom: Core.worldBaseTileLayerMaxZoom(tileManifest.maxNativeZoom, 8),
        minNativeZoom: tileManifest.minNativeZoom,
        maxNativeZoom: tileManifest.maxNativeZoom,
        bounds: worldBounds,
        noWrap: true,
        keepBuffer: 3,
        updateWhenIdle: window.matchMedia('(pointer: coarse)').matches,
        attribution: tileManifest.attribution
      });
      tileLayer.on('tileload', () => {
        loadedTiles += 1;
        if (loadedTiles === 1) {
          elements.baseBadge.textContent = '512px 深度タイル';
          elements.baseBadge.className = 'status-badge status-badge--tiles';
        }
      });
      tileLayer.on('tileerror', () => {
        failedTiles += 1;
        if (failedTiles === 1) {
          elements.baseDescription.textContent = '欠損タイルは既存の高解像度画像で補完しています。';
          announce('一部の深度タイルを読み込めないため、既存画像で補完します。');
        }
      });
      tileLayer.addTo(map);
      elements.baseBadge.textContent = '深度タイル読込中';
      elements.baseBadge.className = 'status-badge status-badge--loading';
      elements.baseDescription.textContent = `512px WebPタイル（Z${tileManifest.minNativeZoom}–${tileManifest.maxNativeZoom}）を使用します。`;
    } else {
      elements.baseBadge.textContent = '既存画像（準備版）';
      elements.baseBadge.className = 'status-badge status-badge--legacy';
      elements.baseDescription.textContent = 'タイルmanifestが未配置のため、world-map-hires.jpgを安全に表示しています。';
    }

    map.fitBounds(worldBounds, { padding: [18, 18], animate: false });
    const fitZoom = map.getBoundsZoom(worldBounds, false, [18, 18]);
    map.setMinZoom(Math.max(-6, fitZoom - 0.5));

    map.on('zoomend', updateLod);
    map.on('resize', updateLod);
    map.on('mousemove', event => {
      const x = Math.round(event.latlng.lng);
      const y = Math.round(-event.latlng.lat);
      elements.coordinateReadout.textContent = `X ${x.toLocaleString()} / Y ${y.toLocaleString()}`;
    });
    map.on('mouseout', () => {
      elements.coordinateReadout.textContent = 'X ---- / Y ----';
    });
    map.on('popupopen', event => {
      const closeButton = event.popup.getElement()?.querySelector('.leaflet-popup-close-button');
      if (closeButton) {
        closeButton.setAttribute('aria-label', '詳細を閉じる');
        closeButton.setAttribute('title', '詳細を閉じる');
      }
    });
  }

  async function init() {
    if (!Core) throw new Error('地図コアモジュールを読み込めませんでした。');
    if (!window.L) throw new Error('Leafletを読み込めませんでした。');
    if (!elements.map) throw new Error('地図表示要素がありません。');
    initializeUi();
    setLoading('地理データとタイル構成を確認しています…');

    const releaseConfiguration = worldReleaseConfiguration();
    runtimeCacheKey = releaseConfiguration.cacheKey;
    const optionalIndexController = new AbortController();
    window.addEventListener('pagehide', () => optionalIndexController.abort('page hidden'), { once: true });
    // Intentionally start, but do not await, the optional deep-sheet index.
    const sheetTileIndexPromise = findSheetTileIndex(
      releaseConfiguration,
      optionalIndexController.signal
    );
    const [nodes, routes, hazards, continents, regions, pois, pixelMapping] = await Promise.all([
      fetchJson(`${DATA_BASE}nodes.json`),
      fetchJson(`${DATA_BASE}routes.json`),
      fetchJson(`${DATA_BASE}hazards.json`),
      fetchJson(`${DATA_BASE}continents.json`),
      fetchJson(`${DATA_BASE}regions.json`),
      fetchJson(`${DATA_BASE}pois.json`, { optional: true }),
      fetchJson(`${DATA_BASE}pixel-mapping.json`)
    ]);

    const datasets = {
      nodes: ensureArray(nodes, 'nodes.json'),
      routes: ensureArray(routes, 'routes.json'),
      hazards: ensureArray(hazards, 'hazards.json'),
      continents: ensureArray(continents, 'continents.json'),
      regions: ensureArray(regions, 'regions.json'),
      pois: Array.isArray(pois) ? pois : []
    };
    const imageWidth = Number(pixelMapping.image_width);
    const imageHeight = Number(pixelMapping.image_height);
    if (!Number.isFinite(imageWidth) || imageWidth <= 0 || !Number.isFinite(imageHeight) || imageHeight <= 0) {
      throw new Error('pixel-mapping.json の画像寸法が不正です。');
    }

    const worldRelease = await findWorldTileManifest(releaseConfiguration, pixelMapping);
    const tileManifest = worldRelease?.manifest || null;
    const emptySheetTileIndex = Object.freeze({
      schemaVersion: Core.SHEET_TILE_INDEX_SCHEMA_VERSION,
      coordinateReferenceSystem: 'EA-WORLD-1',
      rootId: 'sheet_world',
      sheets: Object.freeze([]),
      rasters: Object.freeze([])
    });
    let regionRasterIndex = emptySheetTileIndex;

    setLoading('ベクターレイヤーを構築しています…');
    // The world base and vectors become usable before the optional sheet index resolves.
    createMap(imageWidth, imageHeight, tileManifest, emptySheetTileIndex);
    const vectors = createVectorLayers(datasets, pixelMapping, regionRasterIndex);

    layerRoots = {
      routes: window.L.layerGroup([vectors.routes]),
      nodes: window.L.layerGroup(),
      pois: window.L.layerGroup(),
      labels: window.L.layerGroup(),
      hazards: window.L.layerGroup([vectors.hazards])
    };
    nodeLodLayers = { primary: vectors.nodesPrimary, secondary: vectors.nodesSecondary };
    poiLodLayers = { primary: vectors.poisPrimary, secondary: vectors.poisSecondary };
    labelLodLayers = {
      continent: vectors.labelsContinent,
      region: vectors.labelsRegion,
      node: vectors.labelsNode
    };
    const searchEntries = Core.createMapSearchIndex(datasets);
    searchController = createMapSearchController(searchEntries, vectors.searchTargets);

    elements.featureCount.textContent = [
      `${vectors.renderedCounts.nodes}拠点`,
      `${vectors.renderedCounts.routes}路線`,
      `${vectors.renderedCounts.pois} POI`
    ].join(' · ');

    updateLod();
    map.invalidateSize();
    elements.loading.classList.add('is-complete');
    announce('深度世界地図を読み込みました。');

    const publicApi = window.EternalArcadiaMapV3 = {
      map,
      layers: layerRoots,
      datasets,
      worldBounds,
      worldRelease: worldRelease?.releaseId || 'legacy-image',
      worldReleaseConfiguration: releaseConfiguration,
      tileManifest,
      regionRasterIndex,
      regionRasters: null,
      search: {
        entries: searchEntries,
        targets: vectors.searchTargets,
        focus: () => searchController.focus()
      },
      pixelToLatLng,
      setLayerVisible(name, visible) {
        const input = document.querySelector(`[data-map-layer="${CSS.escape(name)}"]`);
        if (!input || !(name in layerEnabled)) return false;
        input.checked = Boolean(visible);
        layerEnabled[name] = Boolean(visible);
        applyLayerVisibility();
        return true;
      },
      fitWorld() {
        map.fitBounds(worldBounds, { padding: [18, 18], animate: !reducedMotion });
      }
    };

    void sheetTileIndexPromise.then(result => {
      if (!result || optionalIndexController.signal.aborted) return;
      try {
        regionRasterIndex = Core.normalizeSheetTileIndex(
          result,
          pixelMapping,
          window.location.href,
          tileManifest?.nativeZoom ?? LEGACY_WORLD_NATIVE_ZOOM
        );
        Core.assertSheetTileIndexWorldIdentity(regionRasterIndex, worldRelease);
        regionRasterManager?.destroy();
        regionRasterManager = createRegionRasterManager(
          regionRasterIndex,
          pixelMapping,
          tileManifest?.nativeZoom ?? LEGACY_WORLD_NATIVE_ZOOM
        );
        datasets.regions.forEach(region => {
          const target = vectors.searchTargets.get(`region:${region.id}`);
          if (target) {
            target.bounds = Core.mapSearchRegionLeafletBounds(
              regionRasterIndex.rasters,
              region.id,
              pixelMapping
            );
          }
        });
        publicApi.regionRasterIndex = regionRasterIndex;
        publicApi.regionRasters = regionRasterManager;
      } catch (error) {
        console.warn('[InteractiveMapV3] Invalid sheet tile index; retaining world base.', error);
      }
    }).catch(error => {
      if (!optionalIndexController.signal.aborted) {
        console.info('[InteractiveMapV3] Optional sheet tile index unavailable; world remains ready.', error);
      }
    });
  }

  init().catch(showFatalError);
})();
