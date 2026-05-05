/**
 * Interactive Map v0.1
 * SVG描画・表示制御・詳細パネル担当
 *
 * 機能：
 * - Map Data読み込み
 * - SVG地図描画（ノード・ルート・危険区域）
 * - レイヤー切替
 * - クリックで詳細表示
 * - エラーハンドリング
 */

document.addEventListener('DOMContentLoaded', () => {
  const BASE_PATH = '../data/map/';
  const DATA_FILES = [
    { key: 'continents', url: 'continents.json' },
    { key: 'regions', url: 'regions.json' },
    { key: 'nodes', url: 'nodes.json' },
    { key: 'routes', url: 'routes.json' },
    { key: 'hazards', url: 'hazards.json' }
  ];

  const mapData = {};
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

  // SVG関連要素
  const svgElement = document.getElementById('transport-map-svg');
  const detailPanel = document.getElementById('map-detail-panel');
  const detailContent = document.getElementById('map-detail-content');

  // レイヤー切替チェックボックス
  const layerToggles = document.querySelectorAll('input[data-layer-toggle]');

  // HTMLエスケープ
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // エラーメッセージ表示
  function showError(message) {
    if (messageElement) {
      messageElement.textContent = message;
      messageElement.hidden = false;
    }
    console.error('[InteractiveMap]', message);
  }

  // 警告メッセージ表示（コンソール＋ページ内）
  function showWarning(message) {
    console.warn('[InteractiveMap]', message);
    if (messageElement) {
      const warningEl = document.createElement('p');
      warningEl.className = 'map-warning';
      warningEl.textContent = message;
      warningEl.style.cssText = 'color: #c00; font-size: 0.85rem; margin-top: 0.5rem;';
      messageElement.appendChild(warningEl);
      messageElement.hidden = false;
    }
  }

  // 個別データ読み込み
  function fetchData(key, url) {
    return fetch(BASE_PATH + url)
      .then(response => {
        if (!response.ok) {
          throw new Error(`${key}: HTTP ${response.status} - ${response.statusText}`);
        }
        return response.json();
      })
      .then(data => {
        if (Array.isArray(data)) {
          mapData[key] = data;
          return data.length;
        } else if (typeof data === 'object' && data !== null) {
          mapData[key] = data;
          if (data.nodes) return data.nodes.length;
          if (data.routes) return data.routes.length;
          if (data.hazards) return data.hazards.length;
          return Object.keys(data).length;
        }
        return 0;
      });
  }

  // ===== SVG描画関数群 =====

  // ノード描画
  function renderNodes(svg, nodes) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('id', 'layer-nodes');
    g.setAttribute('data-layer', 'nodes');

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

      // 主要ノード判定
      const isMajor = type === 'capital' ||
                      transportRoles.includes('major_hub') ||
                      transportRoles.includes('road_hub') ||
                      tags.includes('major_hub');

      // ノード種別からクラス判定
      let nodeClass = 'node-city';
      if (type === 'capital') nodeClass = 'node-capital';
      else if (type === 'port' || type === 'seaport') nodeClass = 'node-port';
      else if (type === 'airport' || type === 'air_terminal') nodeClass = 'node-airport';
      else if (type === 'oasis') nodeClass = 'node-oasis';
      else if (type === 'floating_island') nodeClass = 'node-floating-island';
      else if (type === 'underwater_city') nodeClass = 'node-underwater-city';
      else if (type === 'forbidden_gate' || type === 'warp_gate') nodeClass = 'node-warp-gate';

      // 円の半径
      const radius = type === 'capital' ? 30 : (isMajor ? 20 : 12);

      // ノードグループ（円＋ラベル）
      const nodeGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      nodeGroup.setAttribute('class', `map-node ${nodeClass}`);
      nodeGroup.setAttribute('data-layer', 'nodes');
      nodeGroup.setAttribute('data-node-id', node.id);
      nodeGroup.style.cursor = 'pointer';

      // 円
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', x);
      circle.setAttribute('cy', y);
      circle.setAttribute('r', radius);
      circle.setAttribute('stroke', '#333');
      circle.setAttribute('stroke-width', type === 'capital' ? 3 : 2);
      circle.setAttribute('fill', getNodeColor(type, nodeClass));

      // ホバー効果用の透明円（当たり判定拡大）
      const hitCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      hitCircle.setAttribute('cx', x);
      hitCircle.setAttribute('cy', y);
      hitCircle.setAttribute('r', radius + 10);
      hitCircle.setAttribute('fill', 'transparent');
      hitCircle.style.pointerEvents = 'all';

      nodeGroup.appendChild(circle);
      nodeGroup.appendChild(hitCircle);

      // 主要ノードのみラベル表示
      if (isMajor) {
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', x);
        text.setAttribute('y', y - radius - 5);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('font-size', type === 'capital' ? '24' : '18');
        text.setAttribute('fill', '#333');
        text.setAttribute('font-weight', type === 'capital' ? 'bold' : 'normal');
        text.textContent = name;
        nodeGroup.appendChild(text);
      }

      // クリックイベント
      nodeGroup.addEventListener('click', (e) => {
        e.stopPropagation();
        showNodeDetail(node);
      });

      g.appendChild(nodeGroup);
    });

    svg.appendChild(g);
  }

  // ノードの色を取得
  function getNodeColor(type, nodeClass) {
    if (type === 'capital') return '#FFD700'; // 金
    if (nodeClass.includes('port')) return '#4169E1'; // 青
    if (nodeClass.includes('airport') || nodeClass.includes('air')) return '#9370DB'; // 紫
    if (nodeClass.includes('oasis')) return '#228B22'; // 緑
    if (nodeClass.includes('warp') || nodeClass.includes('forbidden')) return '#FF4500'; // 橙赤
    if (nodeClass.includes('underwater') || nodeClass.includes('floating')) return '#20B2AA'; // 青緑
    return '#CD853F'; // 茶（default都市）
  }

   // ルート描画
   function renderRoutes(svg, routes, nodes) {
     const nodeById = {};
     nodes.forEach(node => {
       if (node.id && node.position) {
         nodeById[node.id] = node;
       }
     });

     // レイヤー別にグループ分け
     const layers = {
       road: document.createElementNS('http://www.w3.org/2000/svg', 'g'),
       sea: document.createElementNS('http://www.w3.org/2000/svg', 'g'),
       air: document.createElementNS('http://www.w3.org/2000/svg', 'g'),
       special: document.createElementNS('http://www.w3.org/2000/svg', 'g')
     };

     // 各レイヤーグループにdata-layerを設定
     layers.road.setAttribute('data-layer', 'road');
     layers.sea.setAttribute('data-layer', 'sea');
     layers.air.setAttribute('data-layer', 'air');
     layers.special.setAttribute('data-layer', 'special');

    routes.forEach(route => {
      const fromNode = nodeById[route.from];
      const toNode = nodeById[route.to];

      if (!fromNode || !toNode) {
        showWarning(`ルート ${route.id || 'unknown'}: from/toのノードが見つかりません、スキップします`);
        return;
      }

      if (!fromNode.position || !toNode.position) {
        showWarning(`ルート ${route.id}: ノードのpositionデータが不足、スキップします`);
        return;
      }

      const x1 = fromNode.position.x;
      const y1 = fromNode.position.y;
      const x2 = toNode.position.x;
      const y2 = toNode.position.y;

      const type = route.type || 'unknown';
      const mode = route.mode || '';
      const name = route.name || route.id || 'unnamed';

      // ルート種別からレイヤーとクラスを判定
      let layer, routeClass, stroke, strokeWidth, strokeDasharray;

      if (type === 'road' || type === 'rail' || type === 'caravan' || type === 'ice_road') {
        layer = 'road';
        routeClass = `route-${type}`;
        stroke = type === 'rail' ? '#2F4F4F' : '#8B4513'; // 鉄道:暗灰色, 陸路:茶色
        strokeWidth = type === 'rail' ? 6 : 3;
        strokeDasharray = type === 'caravan' || type === 'ice_road' ? '8,4' : 'none';
      } else if (type === 'sea') {
        layer = 'sea';
        routeClass = 'route-sea';
        stroke = '#1E90FF'; // 青
        strokeWidth = 2;
        strokeDasharray = '6,4'; // 破線
      } else if (type === 'air') {
        layer = 'air';
        routeClass = 'route-air';
        stroke = '#9370DB'; // 紫
        strokeWidth = 2;
        strokeDasharray = '6,4'; // 破線
      } else {
        layer = 'special';
        routeClass = `route-${type}`;
        // 特殊交通の種別ごとに色を分ける
        if (type === 'submarine' || type === 'underwater_tunnel') {
          stroke = '#00CED1'; // 青緑
        } else if (type === 'warp' || type === 'forbidden_path') {
          stroke = '#FF4500'; // 橙赤
        } else if (type === 'tunnel') {
          stroke = '#696969'; // 灰色
        } else {
          stroke = '#8A2BE2'; // 紫（デフォルト）
        }
        strokeWidth = 3;
        strokeDasharray = type.includes('warp') || type.includes('forbidden') ? '4,2' : 'none';
      }

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      path.setAttribute('x1', x1);
      path.setAttribute('y1', y1);
      path.setAttribute('x2', x2);
      path.setAttribute('y2', y2);
      path.setAttribute('stroke', stroke);
      path.setAttribute('stroke-width', strokeWidth);
      if (strokeDasharray !== 'none') {
        path.setAttribute('stroke-dasharray', strokeDasharray);
      }
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('class', `map-route ${routeClass}`);
      path.setAttribute('data-layer', layer);
      path.setAttribute('data-route-id', route.id);
      path.style.cursor = 'pointer';

      // クリックイベント
      path.addEventListener('click', (e) => {
        e.stopPropagation();
        showRouteDetail(route, fromNode, toNode);
      });

      layers[layer].appendChild(path);
    });

    Object.values(layers).forEach(layerGroup => {
      if (layerGroup.childNodes.length > 0) {
        svg.appendChild(layerGroup);
      }
    });
  }

  // 危険区域描画
  function renderHazards(svg, hazards) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('id', 'layer-hazards');
    g.setAttribute('data-layer', 'hazards');

    hazards.forEach(hazard => {
      if (!hazard.center || hazard.center.x === undefined || hazard.center.y === undefined) {
        showWarning(`危険区域 ${hazard.id || 'unknown'}: centerデータ不足、スキップします`);
        return;
      }

      if (!hazard.radius) {
        showWarning(`危険区域 ${hazard.id || 'unknown'}: radiusデータ不足、スキップします`);
        return;
      }

      const x = hazard.center.x;
      const y = hazard.center.y;
      const radius = hazard.radius;
      const type = hazard.type || 'unknown';
      const name = hazard.name || hazard.id || 'unnamed';
      const severity = hazard.severity || 1;

      // 危険区域クラス
      let hazardClass = `hazard-${type}`;

      // 色と透明度を危険度に応じて設定
      const opacity = 0.2 + (severity * 0.15); // severity 1-5 で 0.35-0.95
      const fillColor = getHazardColor(type);

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', x);
      circle.setAttribute('cy', y);
      circle.setAttribute('r', radius);
      circle.setAttribute('fill', fillColor);
      circle.setAttribute('fill-opacity', opacity);
      circle.setAttribute('stroke', fillColor);
      circle.setAttribute('stroke-width', 2);
      circle.setAttribute('class', `map-hazard ${hazardClass}`);
      circle.setAttribute('data-layer', 'hazards');
      circle.setAttribute('data-severity', severity);
      circle.style.cursor = 'pointer';

      // クリックイベント
      circle.addEventListener('click', (e) => {
        e.stopPropagation();
        showHazardDetail(hazard);
      });

      g.appendChild(circle);
    });

    svg.appendChild(g);
  }

  // 危険区域の色を取得
  function getHazardColor(type) {
    if (type === 'sandstorm') return '#D2691E'; // チョコレート
    if (type === 'pirate_sea' || type === 'pirate') return '#8B0000'; // 暗赤
    if (type === 'ice_sea' || type === 'ice') return '#4682B4'; // 鋼青
    if (type === 'time_distortion') return '#8A2BE2'; // 藍紫
    if (type === 'forbidden_zone') return '#4B0082'; // インディゴ
    if (type === 'volcanic_zone') return '#FF4500'; // オレンジ赤
    return '#808080'; // 灰色（デフォルト）
  }

   // 大陸・地域描画（簡易：ラベルのみ）
   function renderContinents(svg, continents) {
     const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
     g.setAttribute('id', 'layer-continents');
     g.setAttribute('data-layer', 'continents');

     continents.forEach(continent => {
       const name = continent.name || continent.id || 'unknown';
       // continent.center を使用
       const center = continent.center;
       let x = 5000, y = 5000;
       if (center && center.x !== undefined && center.y !== undefined) {
         x = center.x;
         y = center.y;
       }

       const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
       text.setAttribute('x', x);
       text.setAttribute('y', y);
       text.setAttribute('text-anchor', 'middle');
       text.setAttribute('font-size', '48');
       text.setAttribute('fill', '#666');
       text.setAttribute('font-weight', 'bold');
       text.setAttribute('opacity', '0.3');
       text.textContent = name;
       g.appendChild(text);
     });

     svg.appendChild(g);
   }

  // メイン描画関数
  function renderTransportMap() {
    // 既存の内容をクリア
    svgElement.innerHTML = '';

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

    // 描画順序: 大陸 → 危険区域 → ルート → ノード
    renderContinents(svgElement, continents);
    renderHazards(svgElement, hazards);
    renderRoutes(svgElement, routes, nodes);
    renderNodes(svgElement, nodes);
  }

  // ===== 詳細パネル表示関数群 =====

  function showNodeDetail(node) {
    if (!detailContent || !detailPanel) return;
    const continent = mapData.continents?.find(c => c.id === node.continent_id) || null;
    const region = mapData.regions?.find(r => r.id === node.region_id) || null;

    let html = `
      <h3>${escapeHtml(node.name || node.id)}</h3>
      <dl class="detail-list">
        <dt>ID</dt><dd>${escapeHtml(node.id)}</dd>
        <dt>種別</dt><dd>${escapeHtml(node.type)}</dd>
        <dt>大陸</dt><dd>${continent ? escapeHtml(continent.name) : escapeHtml(node.continent_id || '不明')}</dd>
        <dt>地域</dt><dd>${region ? escapeHtml(region.name) : escapeHtml(node.region_id || '不明')}</dd>
        <dt>座標</dt><dd>X: ${node.position?.x ?? '?'}, Y: ${node.position?.y ?? '?'}, Z: ${node.position?.z ?? 0}</dd>
        <dt>交通ロール</dt><dd>${(node.transport_roles || []).join(', ') || 'なし'}</dd>
        <dt>施設</dt><dd>${(node.facilities || []).join(', ') || 'なし'}</dd>
        <dt>タグ</dt><dd>${(node.tags || []).join(', ') || 'なし'}</dd>
      </dl>
      <p class="detail-description">${escapeHtml(node.description || '説明なし')}</p>
    `;

    detailContent.innerHTML = html;
    detailPanel.hidden = false;
  }

  function showRouteDetail(route, fromNode, toNode) {
    if (!detailContent || !detailPanel) return;
    let html = `
      <h3>${escapeHtml(route.name || route.id)}</h3>
      <dl class="detail-list">
        <dt>ID</dt><dd>${escapeHtml(route.id)}</dd>
        <dt>種別</dt><dd>${escapeHtml(route.type)}</dd>
        <dt>交通モード</dt><dd>${escapeHtml(route.mode || '未設定')}</dd>
        <dt>出発地</dt><dd>${escapeHtml(fromNode?.name || fromNode?.id || route.from)}</dd>
        <dt>到着地</dt><dd>${escapeHtml(toNode?.name || toNode?.id || route.to)}</dd>
        <dt>距離</dt><dd>${route.distance_km ?? '?'} km</dd>
        <dt>所要時間</dt><dd>${route.estimated_time_hours ?? '?'} 時間</dd>
        <dt>費用</dt><dd>${route.cost_gold ?? '?'} GP</dd>
        <dt>危険度</dt><dd>${route.danger_level ?? '?'}</dd>
        <dt>状態</dt><dd><span class="status-badge status-${escapeHtml(route.status || 'unknown')}">${escapeHtml(route.status || 'unknown')}</span></dd>
        <dt>季節運行</dt><dd>${route.seasonal ? 'はい' : 'いいえ'}</dd>
        ${route.active_months ? `<dt>運行月</dt><dd>${route.active_months.join(', ')}</dd>` : ''}
        <dt>運営者</dt><dd>${(route.operators || []).join(', ') || '不明'}</dd>
        <dt>タグ</dt><dd>${(route.tags || []).join(', ') || 'なし'}</dd>
      </dl>
      <p class="detail-description">${escapeHtml(route.description || '説明なし')}</p>
    `;

    detailContent.innerHTML = html;
    detailPanel.hidden = false;
  }

  function showHazardDetail(hazard) {
    if (!detailContent || !detailPanel) return;
    const continent = mapData.continents?.find(c => c.id === hazard.continent_id) || null;

    let html = `
      <h3>${escapeHtml(hazard.name || hazard.id)}</h3>
      <dl class="detail-list">
        <dt>ID</dt><dd>${escapeHtml(hazard.id)}</dd>
        <dt>種別</dt><dd>${escapeHtml(hazard.type)}</dd>
        <dt>大陸</dt><dd>${continent ? escapeHtml(continent.name) : escapeHtml(hazard.continent_id || '不明')}</dd>
        <dt>中心座標</dt><dd>X: ${hazard.center?.x ?? '?'}, Y: ${hazard.center?.y ?? '?'}</dd>
        <dt>半径</dt><dd>${hazard.radius ?? '?'}</dd>
        <dt>危険度</dt><dd><span class="severity-badge">Severity ${hazard.severity ?? '?'}</span></dd>
        <dt>季節性</dt><dd>${hazard.seasonal ? 'あり' : 'なし'}</dd>
        ${hazard.active_months ? `<dt>活跃月</dt><dd>${hazard.active_months.join(', ')}</dd>` : ''}
        <dt>効果</dt><dd>${formatEffects(hazard.effects)}</dd>
      </dl>
      <p class="detail-description">${escapeHtml(hazard.description || '説明なし')}</p>
    `;

    detailContent.innerHTML = html;
    detailPanel.hidden = false;
  }

  function formatEffects(effects) {
    if (!effects || Object.keys(effects).length === 0) return 'なし';
    return Object.entries(effects)
      .map(([key, value]) => `${key}: ${value}`)
      .join(', ');
  }

  // ===== レイヤー切替機能 =====

  function setupLayerToggles() {
    if (!svgElement) return;
    layerToggles.forEach(toggle => {
      toggle.addEventListener('change', (e) => {
        const layer = e.target.getAttribute('data-layer-toggle');
        const isVisible = e.target.checked;

        const layerElements = svgElement.querySelectorAll(`[data-layer="${layer}"]`);
        layerElements.forEach(el => {
          if (isVisible) {
            el.classList.remove('map-hidden');
          } else {
            el.classList.add('map-hidden');
          }
        });
      });
    });
  }

  // ===== 既存のプレビュー関数群 =====

  function renderNodesPreview(nodes) {
    const container = previewContainers.nodes;
    if (!container) return;
    const items = nodes.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    const html = items.map(node => {
      const name = node.name || node.id || ' unnamed';
      const type = node.type || 'unknown';
      const location = node.continent_id || node.region_id || '';
      return `<div class="data-preview-card">
        <strong>${escapeHtml(name)}</strong>
        <span class="type-badge">${escapeHtml(type)}</span>
        ${location ? `<span class="location">${escapeHtml(location)}</span>` : ''}
      </div>`;
    }).join('');

    container.innerHTML = html;
  }

  function renderRoutesPreview(routes) {
    const container = previewContainers.routes;
    if (!container) return;
    const items = routes.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    const html = items.map(route => {
      const name = route.name || route.id || ' unnamed';
      const type = route.type || 'unknown';
      const status = route.status || 'unknown';
      return `<div class="data-preview-card">
        <strong>${escapeHtml(name)}</strong>
        <span class="type-badge">${escapeHtml(type)}</span>
        <span class="status-badge status-${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>`;
    }).join('');

    container.innerHTML = html;
  }

  function renderHazardsPreview(hazards) {
    const container = previewContainers.hazards;
    if (!container) return;
    const items = hazards.slice(0, 10);

    if (items.length === 0) {
      container.innerHTML = '<p>データがありません</p>';
      return;
    }

    const html = items.map(hazard => {
      const name = hazard.name || hazard.id || ' unnamed';
      const type = hazard.type || 'unknown';
      const severity = hazard.severity || '?';
      return `<div class="data-preview-card">
        <strong>${escapeHtml(name)}</strong>
        <span class="type-badge">${escapeHtml(type)}</span>
        <span class="severity-badge">severity ${severity}</span>
      </div>`;
    }).join('');

    container.innerHTML = html;
  }

  // ステータス更新
  function updateCount(key, count) {
    const el = countElements[key];
    if (el) {
      el.textContent = `${count}件`;
      el.classList.add('status-ok');
    }
  }

  function setErrorCount(key) {
    const el = countElements[key];
    if (el) {
      el.textContent = 'エラー';
      el.classList.add('status-error');
    }
  }

  // ===== メイン処理 =====

  async function loadAllData() {
    const promises = DATA_FILES.map(file => {
      return fetchData(file.key, file.url)
        .then(count => ({ key: file.key, count }))
        .catch(err => {
          console.error(`Failed to load ${file.key}:`, err);
          setErrorCount(file.key);
          // エラーでも継続
          return { key: file.key, count: 0 };
        });
    });

    try {
      const results = await Promise.all(promises);
      results.forEach(({ key, count }) => {
        updateCount(key, count);
      });
    } catch (error) {
      showError('データ読み込み中にエラーが発生しました。');
    }

    // プレビュー表示
    if (mapData.nodes && Array.isArray(mapData.nodes)) {
      renderNodesPreview(mapData.nodes);
    }
    if (mapData.routes && Array.isArray(mapData.routes)) {
      renderRoutesPreview(mapData.routes);
    }
    if (mapData.hazards && Array.isArray(mapData.hazards)) {
      renderHazardsPreview(mapData.hazards);
    }

    // SVG描画実行
    if (svgElement) {
      try {
        renderTransportMap();
        setupLayerToggles();
        console.log('[InteractiveMap] SVG rendering completed');
      } catch (err) {
        showError('SVG描画に失敗しました: ' + err.message);
        console.error('[InteractiveMap] Render error:', err);
      }
    } else {
      showError('SVG描画領域が見つかりません。interactive-map.html を確認してください。');
    }
  }

  // 実行
  loadAllData();
});
