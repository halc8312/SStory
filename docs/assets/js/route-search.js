/**
 * Route Search v0.1
 * nodes/routes からグラフを構築し、条件付きDijkstra探索と結果表示を担当する。
 */

(() => {
  const SEARCH_RESULT_EMPTY_HTML = `<p class="route-search-empty">条件を指定して「検索」を押すと、結果がここに表示されます。</p>`;
  const NODE_SELECT_PLACEHOLDER_HTML = '<option value="">選択してください</option>';
  const ROUTE_SELECTED_CLASS = 'map-route--selected';
  const NODE_START_CLASS = 'map-node--start';
  const NODE_GOAL_CLASS = 'map-node--goal';
  const NODE_VIA_CLASS = 'map-node--via';
  const DEFAULT_NODE_TYPE = 'unknown';
  const DEFAULT_ROUTE_COST = 9999;
  const MINIMUM_EDGE_COST = 0.1;

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  }

  function normalizeNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function unique(values) {
    return [...new Set(values.filter(Boolean))];
  }

  function getRouteLabel(route, fallback = 'unnamed') {
    return route?.name || route?.id || fallback;
  }

  function formatNodeLabel(node) {
    return `${node.name} / ${node.type || DEFAULT_NODE_TYPE}`;
  }

  function createSeasonalWarning(routeLabel) {
    return `月指定がないため、${routeLabel} の季節運行は判定していません。`;
  }

  function createSeasonalFallbackWarning(routeLabel, month) {
    return `${routeLabel} は active_months がないため、月指定 ${month} 月でも利用可能として扱いました。`;
  }

  function createPriorityQueue() {
    const heap = [];

    function swap(leftIndex, rightIndex) {
      [heap[leftIndex], heap[rightIndex]] = [heap[rightIndex], heap[leftIndex]];
    }

    function bubbleUp(index) {
      let currentIndex = index;
      while (currentIndex > 0) {
        const parentIndex = Math.floor((currentIndex - 1) / 2);
        if (heap[parentIndex].cost <= heap[currentIndex].cost) {
          break;
        }
        swap(parentIndex, currentIndex);
        currentIndex = parentIndex;
      }
    }

    function bubbleDown(index) {
      let currentIndex = index;
      while (true) {
        const leftChildIndex = currentIndex * 2 + 1;
        const rightChildIndex = currentIndex * 2 + 2;
        let smallestIndex = currentIndex;

        if (leftChildIndex < heap.length && heap[leftChildIndex].cost < heap[smallestIndex].cost) {
          smallestIndex = leftChildIndex;
        }
        if (rightChildIndex < heap.length && heap[rightChildIndex].cost < heap[smallestIndex].cost) {
          smallestIndex = rightChildIndex;
        }
        if (smallestIndex === currentIndex) {
          break;
        }
        swap(currentIndex, smallestIndex);
        currentIndex = smallestIndex;
      }
    }

    return {
      push(value) {
        heap.push(value);
        bubbleUp(heap.length - 1);
      },
      pop() {
        if (heap.length === 0) {
          return null;
        }
        if (heap.length === 1) {
          return heap.pop();
        }

        const first = heap[0];
        heap[0] = heap.pop();
        bubbleDown(0);
        return first;
      },
      get size() {
        return heap.length;
      }
    };
  }

  function getValidSelectableNodes(nodes) {
    return (Array.isArray(nodes) ? nodes : [])
      .filter(node => node?.id && node?.name && node?.position && node.position.x !== undefined && node.position.y !== undefined)
      .slice()
      .sort((left, right) => String(left.name).localeCompare(String(right.name), 'ja'));
  }

  function fillNodeSelect(selectElement, nodes) {
    if (!selectElement) return;

    const currentValue = selectElement.value;
    const options = [NODE_SELECT_PLACEHOLDER_HTML];

    nodes.forEach(node => {
      options.push(
        `<option value="${escapeHtml(node.id)}">${escapeHtml(formatNodeLabel(node))}</option>`
      );
    });

    selectElement.innerHTML = options.join('');
    if (currentValue && nodes.some(node => node.id === currentValue)) {
      selectElement.value = currentValue;
    }
  }

  function getMetricValue(route, priorityKeys) {
    for (const key of priorityKeys) {
      const value = normalizeNumber(route?.[key]);
      if (value !== null) {
        return value;
      }
    }
    return DEFAULT_ROUTE_COST;
  }

  function computeRouteCost(route, weight) {
    if (weight === 'distance') {
      return getMetricValue(route, ['distance_km', 'estimated_time_hours']);
    }

    if (weight === 'safety') {
      const baseCost = getMetricValue(route, ['estimated_time_hours', 'distance_km']);
      const dangerLevel = Math.max(0, normalizeNumber(route?.danger_level) ?? 0);
      return baseCost + dangerLevel * 100;
    }

    return getMetricValue(route, ['estimated_time_hours', 'distance_km']);
  }

  function isSeasonalRoute(route) {
    return route?.seasonal === true || Array.isArray(route?.active_months);
  }

  function evaluateRoute(route, options) {
    const status = route?.status || 'active';

    if (status === 'forbidden') {
      return { allowed: false, warnings: [] };
    }

    if (status === 'restricted' && !options.allowRestricted) {
      return { allowed: false, warnings: [] };
    }

    if (options.noAir && route?.type === 'air') {
      return { allowed: false, warnings: [] };
    }

    if (options.noSea && route?.type === 'sea') {
      return { allowed: false, warnings: [] };
    }

    const warnings = [];
    if (isSeasonalRoute(route)) {
      const activeMonths = Array.isArray(route.active_months) ? route.active_months : [];
      const routeLabel = getRouteLabel(route, '季節ルート');

      if (options.month === null) {
        warnings.push(createSeasonalWarning(routeLabel));
      } else if (activeMonths.length > 0) {
        if (!activeMonths.includes(options.month)) {
          return { allowed: false, warnings: [] };
        }
      } else {
        warnings.push(createSeasonalFallbackWarning(routeLabel, options.month));
      }
    }

    if (status === 'restricted') {
      warnings.push(`${getRouteLabel(route, 'restricted route')} は restricted route です。`);
    }

    return {
      allowed: true,
      warnings,
      cost: computeRouteCost(route, options.weight)
    };
  }

  function buildGraph(nodes, routes, options) {
    const nodeById = {};
    (Array.isArray(nodes) ? nodes : []).forEach(node => {
      if (node?.id) {
        nodeById[node.id] = node;
      }
    });

    const graph = {};
    Object.keys(nodeById).forEach(nodeId => {
      graph[nodeId] = [];
    });

    (Array.isArray(routes) ? routes : []).forEach(route => {
      if (!route?.from || !route?.to) {
        return;
      }

      const fromNode = nodeById[route.from];
      const toNode = nodeById[route.to];
      if (!fromNode || !toNode) {
        return;
      }

      const evaluation = evaluateRoute(route, options);
      if (!evaluation.allowed) {
        return;
      }

      const edge = {
        route,
        cost: Math.max(MINIMUM_EDGE_COST, evaluation.cost || MINIMUM_EDGE_COST),
        warnings: evaluation.warnings || []
      };

      graph[route.from].push({
        to: route.to,
        route: edge.route,
        cost: edge.cost,
        warnings: edge.warnings
      });
      graph[route.to].push({
        to: route.from,
        route: edge.route,
        cost: edge.cost,
        warnings: edge.warnings
      });
    });

    return { graph, nodeById };
  }

  function reconstructSegments(previous, startId, goalId, nodeById) {
    const segments = [];
    const warnings = [];
    let currentId = goalId;

    while (currentId !== startId) {
      const entry = previous[currentId];
      if (!entry) {
        return null;
      }

      segments.push({
        route: entry.route,
        fromNode: nodeById[entry.from],
        toNode: nodeById[currentId]
      });
      warnings.push(...(entry.warnings || []));
      currentId = entry.from;
    }

    segments.reverse();
    return { segments, warnings: unique(warnings) };
  }

  function findRoute({ nodes, routes, fromId, toId, weight, month, noAir, noSea, allowRestricted }) {
    if (fromId === toId) {
      return {
        found: false,
        message: '出発地と目的地が同じです。',
        warnings: []
      };
    }

    const { graph, nodeById } = buildGraph(nodes, routes, { weight, month, noAir, noSea, allowRestricted });

    if (!nodeById[fromId] || !nodeById[toId]) {
      return {
        found: false,
        message: '出発地または目的地のノードが見つかりませんでした。',
        warnings: []
      };
    }

    const distances = { [fromId]: 0 };
    const previous = {};
    const queue = createPriorityQueue();
    const visited = new Set();
    queue.push({ nodeId: fromId, cost: 0 });

    while (queue.size > 0) {
      const current = queue.pop();
      if (!current || visited.has(current.nodeId)) {
        continue;
      }

      visited.add(current.nodeId);
      if (current.nodeId === toId) {
        break;
      }

      const edges = graph[current.nodeId] || [];
      edges.forEach(edge => {
        const nextCost = current.cost + edge.cost;
        if (nextCost < (distances[edge.to] ?? Number.POSITIVE_INFINITY)) {
          distances[edge.to] = nextCost;
          previous[edge.to] = {
            from: current.nodeId,
            route: edge.route,
            warnings: edge.warnings || []
          };
          queue.push({ nodeId: edge.to, cost: nextCost });
        }
      });
    }

    if (!previous[toId]) {
      return {
        found: false,
        message: '条件に一致するルートが見つかりませんでした。',
        warnings: []
      };
    }

    const reconstructed = reconstructSegments(previous, fromId, toId, nodeById);
    if (!reconstructed) {
      return {
        found: false,
        message: '条件に一致するルートが見つかりませんでした。',
        warnings: []
      };
    }

    const totalDistanceKm = reconstructed.segments.reduce((sum, segment) => {
      return sum + Math.max(0, normalizeNumber(segment.route?.distance_km) ?? 0);
    }, 0);
    const totalTimeHours = reconstructed.segments.reduce((sum, segment) => {
      return sum + Math.max(0, normalizeNumber(segment.route?.estimated_time_hours) ?? 0);
    }, 0);
    const maxDangerLevel = reconstructed.segments.reduce((max, segment) => {
      return Math.max(max, Math.max(0, normalizeNumber(segment.route?.danger_level) ?? 0));
    }, 0);

    return {
      found: true,
      totalCost: distances[toId],
      totalDistanceKm,
      totalTimeHours,
      maxDangerLevel,
      segments: reconstructed.segments,
      warnings: reconstructed.warnings
    };
  }

  function formatNumber(value, digits = 0) {
    const number = normalizeNumber(value);
    if (number === null) {
      return '?';
    }
    return number.toLocaleString('ja-JP', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function renderWarnings(warnings) {
    if (!warnings.length) {
      return '';
    }

    return `
      <div class="route-search-warnings">
        <h3>注意</h3>
        <ul>
          ${warnings.map(warning => `<li>${escapeHtml(warning)}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  function renderResult(result) {
    if (!result?.found) {
      return `
        <div class="route-search-message route-search-message-error">
          <p>${escapeHtml(result?.message || '条件に一致するルートが見つかりませんでした。')}</p>
          ${renderWarnings(result?.warnings || [])}
        </div>
      `;
    }

    const pathNames = [];
    result.segments.forEach((segment, index) => {
      if (index === 0) {
        pathNames.push(segment.fromNode?.name || segment.fromNode?.id || '不明');
      }
      pathNames.push(segment.toNode?.name || segment.toNode?.id || '不明');
    });

     return `
       <article class="route-search-summary">
         <header>
           <p class="route-search-path">${pathNames.map(name => escapeHtml(name)).join(' → ')}</p>
           <dl class="route-search-metrics">
             <div><dt>総距離</dt><dd>${formatNumber(result.totalDistanceKm)} km</dd></div>
             <div><dt>推定所要時間</dt><dd>${formatNumber(result.totalTimeHours, 1)} 時間</dd></div>
             <div><dt>最大危険度</dt><dd>${formatNumber(result.maxDangerLevel)}</dd></div>
             <div><dt>区間数</dt><dd>${formatNumber(result.segments.length)}</dd></div>
           </dl>
         </header>

         <div class="route-search-map-actions">
           <button type="button" id="route-scroll-to-leaflet" class="route-search-map-button">
             Leaflet地図で見る
           </button>
         </div>

         <ol class="route-search-segments">
          ${result.segments.map(segment => {
            const routeName = segment.route?.name || segment.route?.id || 'unnamed';
            const fromName = segment.fromNode?.name || segment.fromNode?.id || segment.route?.from || '不明';
            const toName = segment.toNode?.name || segment.toNode?.id || segment.route?.to || '不明';
            return `
              <li class="route-search-segment">
                <strong>${escapeHtml(routeName)}</strong>
                <span>${escapeHtml(`${fromName}〜${toName}`)}</span>
                <span>type: ${escapeHtml(segment.route?.type || 'unknown')}</span>
                <span>status: ${escapeHtml(segment.route?.status || 'active')}</span>
                <span>danger: ${escapeHtml(segment.route?.danger_level ?? '?')}</span>
              </li>
            `;
          }).join('')}
        </ol>

        ${renderWarnings(result.warnings || [])}
      </article>
    `;
  }

  function updateMessage(messageElement, message, { isError = false } = {}) {
    if (!messageElement) return;

    if (!message) {
      messageElement.innerHTML = '';
      messageElement.hidden = true;
      messageElement.classList.remove('route-search-message-error');
      return;
    }

    messageElement.innerHTML = `<p>${escapeHtml(message)}</p>`;
    messageElement.hidden = false;
    messageElement.classList.toggle('route-search-message-error', isError);
  }

  function clearHighlights(svgElement) {
    if (!svgElement) return;
    svgElement.querySelectorAll(`.${ROUTE_SELECTED_CLASS}`).forEach(element => element.classList.remove(ROUTE_SELECTED_CLASS));
    svgElement.querySelectorAll(`.${NODE_START_CLASS}`).forEach(element => element.classList.remove(NODE_START_CLASS));
    svgElement.querySelectorAll(`.${NODE_GOAL_CLASS}`).forEach(element => element.classList.remove(NODE_GOAL_CLASS));
    svgElement.querySelectorAll(`.${NODE_VIA_CLASS}`).forEach(element => element.classList.remove(NODE_VIA_CLASS));
  }

  function applyHighlights(svgElement, result) {
    if (!svgElement || !result?.found) return;

    clearHighlights(svgElement);

    const routeIds = unique(result.segments.map(segment => segment.route?.id));
    routeIds.forEach(routeId => {
      svgElement.querySelectorAll(`[data-route-id="${CSS.escape(routeId)}"]`).forEach(element => {
        element.classList.add(ROUTE_SELECTED_CLASS);
      });
    });

    const startId = result.segments[0]?.fromNode?.id;
    const goalId = result.segments[result.segments.length - 1]?.toNode?.id;
    const viaIds = unique(result.segments.slice(0, -1).map(segment => segment.toNode?.id))
      .filter(nodeId => nodeId && nodeId !== startId && nodeId !== goalId);

    if (startId) {
      svgElement.querySelectorAll(`[data-node-id="${CSS.escape(startId)}"]`).forEach(element => {
        element.classList.add(NODE_START_CLASS);
      });
    }

    if (goalId) {
      svgElement.querySelectorAll(`[data-node-id="${CSS.escape(goalId)}"]`).forEach(element => {
        element.classList.add(NODE_GOAL_CLASS);
      });
    }

    viaIds.forEach(nodeId => {
      svgElement.querySelectorAll(`[data-node-id="${CSS.escape(nodeId)}"]`).forEach(element => {
        element.classList.add(NODE_VIA_CLASS);
      });
    });
  }

  function parseFormOptions(formElements) {
    const monthValue = formElements.monthSelect?.value ? Number(formElements.monthSelect.value) : null;
    return {
      fromId: formElements.fromSelect?.value || '',
      toId: formElements.toSelect?.value || '',
      weight: formElements.weightSelect?.value || 'time',
      month: Number.isInteger(monthValue) ? monthValue : null,
      noAir: Boolean(formElements.noAirCheckbox?.checked),
      noSea: Boolean(formElements.noSeaCheckbox?.checked),
      allowRestricted: Boolean(formElements.allowRestrictedCheckbox?.checked)
    };
  }

  function initializeRouteSearch({ nodes, routes, svgElement }) {
    const form = document.getElementById('route-search-form');
    const messageElement = document.getElementById('route-search-message');
    const resultElement = document.getElementById('route-search-result');
    const clearButton = document.getElementById('route-clear-button');
    const formElements = {
      fromSelect: document.getElementById('route-from-select'),
      toSelect: document.getElementById('route-to-select'),
      weightSelect: document.getElementById('route-weight-select'),
      monthSelect: document.getElementById('route-month-select'),
      noAirCheckbox: document.getElementById('route-no-air'),
      noSeaCheckbox: document.getElementById('route-no-sea'),
      allowRestrictedCheckbox: document.getElementById('route-allow-restricted')
    };

    if (!form || !resultElement || !formElements.fromSelect || !formElements.toSelect) {
      return null;
    }

    const selectableNodes = getValidSelectableNodes(nodes);
    fillNodeSelect(formElements.fromSelect, selectableNodes);
    fillNodeSelect(formElements.toSelect, selectableNodes);

    if (!form.dataset.routeSearchBound) {
      form.addEventListener('submit', event => {
        event.preventDefault();
        const options = parseFormOptions(formElements);
        clearHighlights(svgElement);

        if (!options.fromId || !options.toId) {
          updateMessage(messageElement, '出発地と目的地を選択してください。', { isError: true });
          resultElement.innerHTML = renderResult({
            found: false,
            message: '出発地と目的地を選択してください。',
            warnings: []
          });
          return;
        }

        const result = findRoute({
          nodes,
          routes,
          ...options
        });

         resultElement.innerHTML = renderResult(result);
         if (result.found) {
           updateMessage(messageElement, `${result.segments.length} 区間のルートを地図上でハイライトしています。`);
           applyHighlights(svgElement, result);
           // Leaflet highlight
           if (window.EternalArcadiaLeafletMap?.highlightRoute) {
             window.EternalArcadiaLeafletMap.highlightRoute(result);
           }
           // Attach click handler for "View on Map" button
           const mapButton = resultElement.querySelector('#route-scroll-to-leaflet');
           if (mapButton) {
             mapButton.addEventListener('click', () => {
               const leafletMap = document.getElementById('leaflet-transport-map');
               if (leafletMap) {
                 leafletMap.scrollIntoView({ behavior: 'smooth', block: 'center' });
               }
             });
           }
         } else {
           updateMessage(messageElement, result.message || '条件に一致するルートが見つかりませんでした。', { isError: true });
         }
      });

       clearButton?.addEventListener('click', () => {
         clearHighlights(svgElement);
         updateMessage(messageElement, '');
         resultElement.innerHTML = SEARCH_RESULT_EMPTY_HTML;
         if (window.EternalArcadiaLeafletMap?.clearRouteHighlight) {
           window.EternalArcadiaLeafletMap.clearRouteHighlight();
         }
       });

      form.dataset.routeSearchBound = 'true';
    }

    resultElement.innerHTML = resultElement.innerHTML.trim() || SEARCH_RESULT_EMPTY_HTML;
    updateMessage(messageElement, '');

    return {
      fillNodeSelects() {
        fillNodeSelect(formElements.fromSelect, selectableNodes);
        fillNodeSelect(formElements.toSelect, selectableNodes);
      },
       clear() {
         clearHighlights(svgElement);
         resultElement.innerHTML = SEARCH_RESULT_EMPTY_HTML;
         if (window.EternalArcadiaLeafletMap?.clearRouteHighlight) {
           window.EternalArcadiaLeafletMap.clearRouteHighlight();
         }
       },
      renderResult,
      findRoute
    };
  }

  window.initializeRouteSearch = initializeRouteSearch;
})();
