/**
 * Interactive Map v0.1
 * Map Data読み込み・表示担当
 *
 * 機能：
 * - 5つのJSONファイルをfetch
 * - 件数表示
 * - 先頭10件の簡易一覧表示
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

  // 読み込んだデータを保持するオブジェクト
  const mapData = {};

  // 件数表示要素
  const countElements = {
    continents: document.getElementById('count-continents'),
    regions: document.getElementById('count-regions'),
    nodes: document.getElementById('count-nodes'),
    routes: document.getElementById('count-routes'),
    hazards: document.getElementById('count-hazards')
  };

  // メッセージ表示要素
  const messageElement = document.getElementById('map-data-message');

  // プレビュー容器
  const previewContainers = {
    nodes: document.getElementById('nodes-preview'),
    routes: document.getElementById('routes-preview'),
    hazards: document.getElementById('hazards-preview')
  };

  // エラーメッセージ表示
  function showError(message) {
    messageElement.textContent = message;
    messageElement.hidden = false;
    console.error('[InteractiveMap]', message);
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
        // 配列かオブジェクトかを判定
        if (Array.isArray(data)) {
          mapData[key] = data;
          return data.length;
        } else if (typeof data === 'object' && data !== null) {
          // オブジェクトの場合は配列として扱うか、そのまま保持
          mapData[key] = data;
          // continents.json, regions.json が配列かどうかを確認
          if (data.nodes) return data.nodes.length;
          if (data.routes) return data.routes.length;
          if (data.hazards) return data.hazards.length;
          // continents/regions の場合、features か要素数不明なので概算
          return Object.keys(data).length;
        }
        return 0;
      });
  }

  // ノード一覧表示
  function renderNodesPreview(nodes) {
    const container = previewContainers.nodes;
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

  // ルート一覧表示
  function renderRoutesPreview(routes) {
    const container = previewContainers.routes;
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

  // 危険区域一覧表示
  function renderHazardsPreview(hazards) {
    const container = previewContainers.hazards;
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

  // HTMLエスケープ
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ステータスバッジ更新
  function updateCount(key, count) {
    const el = countElements[key];
    if (el) {
      el.textContent = `${count}件`;
      // 成功時はOKクラスを付与
      el.classList.add('status-ok');
    }
  }

  // エラー時更新
  function setErrorCount(key, message) {
    const el = countElements[key];
    if (el) {
      el.textContent = `エラー`;
      el.classList.add('status-error');
    }
  }

  // メイン処理
  async function loadAllData() {
    const promises = DATA_FILES.map(file => {
      return fetchData(file.key, file.url)
        .then(count => ({ key: file.key, count }))
        .catch(err => {
          console.error(`Failed to load ${file.key}:`, err);
          setErrorCount(file.key, err.message);
          throw err;
        });
    });

    let hasError = false;

    try {
      const results = await Promise.all(promises);
      results.forEach(({ key, count }) => {
        updateCount(key, count);
      });
    } catch (error) {
      hasError = true;
      showError('一部のデータの読み込みに失敗しました。コンソールを確認してください。');
    }

    // プレビュー表示（エラーがあっても表示できるものから）
    if (mapData.nodes && Array.isArray(mapData.nodes)) {
      renderNodesPreview(mapData.nodes);
    }
    if (mapData.routes && Array.isArray(mapData.routes)) {
      renderRoutesPreview(mapData.routes);
    }
    if (mapData.hazards && Array.isArray(mapData.hazards)) {
      renderHazardsPreview(mapData.hazards);
    }

    if (!hasError) {
      console.log('[InteractiveMap] All data loaded:', {
        continents: mapData.continents ? (Array.isArray(mapData.continents) ? mapData.continents.length : 'object') : 'missing',
        regions: mapData.regions ? (Array.isArray(mapData.regions) ? mapData.regions.length : 'object') : 'missing',
        nodes: mapData.nodes ? mapData.nodes.length : 'missing',
        routes: mapData.routes ? mapData.routes.length : 'missing',
        hazards: mapData.hazards ? mapData.hazards.length : 'missing'
      });
    }
  }

  // 実行
  loadAllData();
});
