(() => {
  const BASE_PATH = '../data/map/';
  const CACHE_BUSTER = '20260506a';
  const WORLD_BOUNDS = [[0, 0], [10000, 10000]];
  const DEFAULT_MESSAGE = 'Leaflet版交通マップを読み込めませんでした。';

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

  document.addEventListener('DOMContentLoaded', async () => {
    const mapElement = document.getElementById('leaflet-transport-map');
    const messageElement = document.getElementById('leaflet-transport-map-message');

    if (!mapElement) {
      return;
    }

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

    if (!window.L) {
      showLeafletMessage('Leafletを読み込めませんでした。ネットワーク接続を確認してください。');
      return;
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

    const continentsById = Object.fromEntries((datasets.continents || []).filter(item => item?.id).map(item => [item.id, item]));
    const regionsById = Object.fromEntries((datasets.regions || []).filter(item => item?.id).map(item => [item.id, item]));
    const nodeById = Object.fromEntries((datasets.nodes || []).filter(item => item?.id).map(item => [item.id, item]));

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

    const nodeLayer = L.layerGroup().addTo(map);
    const roadLayer = L.layerGroup().addTo(map);
    const railLayer = L.layerGroup().addTo(map);
    const seaLayer = L.layerGroup().addTo(map);
    const airLayer = L.layerGroup().addTo(map);
    const specialLayer = L.layerGroup().addTo(map);
    const hazardLayer = L.layerGroup().addTo(map);

    function getNodeStyle(node) {
      const type = node?.type || 'unknown';
      if (type === 'capital') return { radius: 9, fillColor: '#d5b34b', color: '#8c6a10', weight: 2.2, fillOpacity: 0.95 };
      if (type === 'port' || type === 'seaport') return { radius: 7, fillColor: '#4f89cb', color: '#234f7f', weight: 2, fillOpacity: 0.92 };
      if (type === 'airport' || type === 'air_terminal') return { radius: 7.5, fillColor: '#9664cf', color: '#5e3794', weight: 2, fillOpacity: 0.92 };
      if (type === 'oasis') return { radius: 7, fillColor: '#57a36b', color: '#2f6d3f', weight: 2, fillOpacity: 0.92 };
      if (type === 'forbidden_gate' || type === 'warp_gate' || type === 'warp_terminal') {
        return { radius: 7.5, fillColor: '#a65190', color: '#692558', weight: 2, fillOpacity: 0.92 };
      }
      return { radius: 6, fillColor: '#c18857', color: '#7d5130', weight: 1.8, fillOpacity: 0.9 };
    }

    function getRouteDefinition(route) {
      const type = route?.type || 'unknown';
      if (type === 'road') return { group: roadLayer, label: '陸路', style: { color: '#9d5a31', weight: 4.5, opacity: 0.9 } };
      if (type === 'caravan') return { group: roadLayer, label: '陸路', style: { color: '#bb8a43', weight: 4, opacity: 0.9, dashArray: '10 8 2 8' } };
      if (type === 'ice_road') return { group: roadLayer, label: '陸路', style: { color: '#8aa7bf', weight: 4, opacity: 0.9, dashArray: '10 6' } };
      if (type === 'rail') return { group: railLayer, label: '鉄道', style: { color: '#4b4f5a', weight: 5.5, opacity: 0.9 } };
      if (type === 'sea') return { group: seaLayer, label: '海路', style: { color: '#317fcb', weight: 4, opacity: 0.85, dashArray: '12 10' } };
      if (type === 'air') return { group: airLayer, label: '空路', style: { color: '#8558c7', weight: 4, opacity: 0.85, dashArray: '8 10' } };
      if (type === 'submarine') return { group: specialLayer, label: '特殊交通', style: { color: '#1f9aa1', weight: 4, opacity: 0.85, dashArray: '8 6' } };
      if (type === 'tunnel') return { group: specialLayer, label: '特殊交通', style: { color: '#67636a', weight: 4, opacity: 0.9, dashArray: '8 8' } };
      if (type === 'underwater_tunnel') return { group: specialLayer, label: '特殊交通', style: { color: '#2389a8', weight: 4, opacity: 0.9, dashArray: '8 8' } };
      if (type === 'forbidden_path') return { group: specialLayer, label: '特殊交通', style: { color: '#9b3441', weight: 4, opacity: 0.9, dashArray: '6 8 2 8' } };
      return { group: specialLayer, label: '特殊交通', style: { color: '#9150b8', weight: 4, opacity: 0.88, dashArray: '6 10' } };
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

    L.control.layers(null, {
      ノード: nodeLayer,
      陸路: roadLayer,
      鉄道: railLayer,
      海路: seaLayer,
      空路: airLayer,
      特殊交通: specialLayer,
      危険区域: hazardLayer
    }, { collapsed: false }).addTo(map);

    window.EternalArcadiaLeafletMap = {
      map,
      routeLayerById,
      nodeMarkerById,
      fitWorld() {
        map.fitBounds(WORLD_BOUNDS, { padding: [24, 24] });
      },
      clearHighlights,
      highlightRouteIds(routeIds = []) {
        highlightRoutes(routeIds);
      },
      focusNodeIds(nodeIds = []) {
        highlightNodes(nodeIds);
        focusNodes(nodeIds);
      }
    };

    if (!datasets.nodes.length && !datasets.routes.length && !datasets.hazards.length) {
      showLeafletMessage(DEFAULT_MESSAGE);
    }
  });
})();
