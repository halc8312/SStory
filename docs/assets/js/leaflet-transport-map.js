(() => {
  const BASE_PATH = '../data/map/';
  const CACHE_BUSTER = '20260506a';
  const WORLD_BOUNDS = [[0, 0], [10000, 10000]];
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

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  }

  function toLatLng(position) {
    return [Number(position?.y ?? 0), Number(position?.x ?? 0)];
  }

  function formatMonths(months) {
    return Array.isArray(months) && months.length > 0 ? months.join(', ') : 'なし';
  }

  function formatCoordinate(position) {
    if (!position || position.x === undefined || position.y === undefined) {
      return 'X: ?, Y: ?';
    }
    return `X: ${position.x}, Y: ${position.y}`;
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

  function createLeafletUnavailableApi(reason = 'Leaflet unavailable') {
    return {
      isAvailable: false,
      reason,
      map: null,
      routeLayerById: new Map(),
      nodeMarkerById: new Map(),
      fitWorld() {},
      clearHighlights() {},
      highlightRouteIds() {},
      focusNodeIds() {}
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

   const nodeMarkerById = new Map();
   const routeLayerById = new Map();
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

      map.fitBounds(WORLD_BOUNDS, { padding: [24, 24] });
      map.setMaxBounds([[-1200, -1200], [11200, 11200]]);

      const WORLD_MAP_IMAGE_URL = '../assets/images/maps/world/world-map.svg';
      const worldMapLayer = L.imageOverlay(WORLD_MAP_IMAGE_URL, WORLD_BOUNDS, {
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

    function bindPopupAndInteractions(layer, html, detailCallback) {
      layer.bindPopup(html, { maxWidth: 360 });
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
        radius: Number(hazard.radius),
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

      const layersControl = L.control.layers(null, {
        '世界地図背景': worldMapLayer,
        'ノード': nodeLayer,
        '陸路': roadLayer,
        '鉄道': railLayer,
        '海路': seaLayer,
        '空路': airLayer,
        '特殊交通': specialLayer,
        '危険区域': hazardLayer
      }, { collapsed: window.matchMedia("(max-width: 720px)").matches }).addTo(map);

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
          worldMapLayer,
          fitWorld() {
            map.fitBounds(WORLD_BOUNDS, { padding: [24, 24] });
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
