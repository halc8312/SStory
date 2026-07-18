/**
 * Shared route-planning rules for every browser map.
 *
 * Keep this module free of DOM dependencies so the same behavior can be
 * exercised by Node's test runner as well as by the v1 and v2 map UIs.
 */
(function initializeRoutePlanner(root, factory) {
  const api = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.EternalArcadiaRoutePlanner = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  'use strict';

  const DEFAULT_ROUTE_COST = 9999;
  const MINIMUM_EDGE_COST = 0.1;
  const BLOCKED_STATUSES = new Set(['forbidden', 'experimental', 'dangerous', 'closed']);

  function normalizeNumber(value) {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function unique(values) {
    return [...new Set(values.filter(Boolean))];
  }

  function getRouteLabel(route, fallback = 'unnamed') {
    return route?.name || route?.id || fallback;
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

  function computeRouteCost(route, weight = 'time') {
    if (weight === 'distance') {
      return getMetricValue(route, ['distance_km', 'estimated_time_hours']);
    }

    if (weight === 'safety') {
      const baseCost = getMetricValue(route, ['estimated_time_hours', 'distance_km']);
      const dangerLevel = Math.max(0, normalizeNumber(route?.danger_level) ?? 0);
      return baseCost * ((dangerLevel + 1) ** 2);
    }

    if (weight === 'cost') {
      return getMetricValue(route, ['cost_gold', 'estimated_time_hours', 'distance_km']);
    }

    return getMetricValue(route, ['estimated_time_hours', 'distance_km']);
  }

  function isSeasonalRoute(route) {
    return route?.status === 'seasonal'
      || route?.seasonal === true
      || Array.isArray(route?.active_months);
  }

  function normalizeOptions(options = {}) {
    const monthValue = normalizeNumber(options.month);
    const month = Number.isInteger(monthValue) && monthValue >= 1 && monthValue <= 12
      ? monthValue
      : null;

    return {
      weight: ['time', 'distance', 'safety', 'cost'].includes(options.weight) ? options.weight : 'time',
      month,
      noAir: Boolean(options.noAir),
      noSea: Boolean(options.noSea),
      allowRestricted: Boolean(options.allowRestricted),
      avoidDangerLevel: normalizeNumber(options.avoidDangerLevel)
    };
  }

  function evaluateRoute(route, rawOptions = {}) {
    const options = normalizeOptions(rawOptions);
    const status = route?.status || 'active';

    if (BLOCKED_STATUSES.has(status)) {
      return { allowed: false, warnings: [], reason: `status:${status}` };
    }

    if (status === 'restricted' && !options.allowRestricted) {
      return { allowed: false, warnings: [], reason: 'status:restricted' };
    }

    if (options.noAir && route?.type === 'air') {
      return { allowed: false, warnings: [], reason: 'type:air' };
    }

    if (options.noSea && route?.type === 'sea') {
      return { allowed: false, warnings: [], reason: 'type:sea' };
    }

    const dangerLevel = Math.max(0, normalizeNumber(route?.danger_level) ?? 0);
    if (options.avoidDangerLevel !== null && dangerLevel >= options.avoidDangerLevel) {
      return { allowed: false, warnings: [], reason: 'danger' };
    }

    const warnings = [];
    if (isSeasonalRoute(route)) {
      const activeMonths = Array.isArray(route?.active_months)
        ? route.active_months.filter(month => Number.isInteger(month) && month >= 1 && month <= 12)
        : [];
      const routeLabel = getRouteLabel(route, '季節ルート');

      if (options.month === null) {
        warnings.push(`月指定がないため、${routeLabel} の季節運行は判定していません。`);
      } else if (!activeMonths.includes(options.month)) {
        return { allowed: false, warnings: [], reason: 'season' };
      }
    }

    if (status === 'restricted') {
      warnings.push(`${getRouteLabel(route, 'restricted route')} は restricted route です。`);
    }

    return {
      allowed: true,
      warnings,
      cost: Math.max(MINIMUM_EDGE_COST, computeRouteCost(route, options.weight))
    };
  }

  function buildGraph(nodes, routes, rawOptions = {}) {
    const options = normalizeOptions(rawOptions);
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
      if (!route?.from || !route?.to || !nodeById[route.from] || !nodeById[route.to]) {
        return;
      }

      const evaluation = evaluateRoute(route, options);
      if (!evaluation.allowed) {
        return;
      }

      const edge = {
        route,
        cost: evaluation.cost,
        warnings: evaluation.warnings || []
      };
      graph[route.from].push({ to: route.to, ...edge });
      graph[route.to].push({ to: route.from, ...edge });
    });

    return { graph, nodeById };
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
        if (heap[parentIndex].cost <= heap[currentIndex].cost) break;
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
        if (smallestIndex === currentIndex) break;
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
        if (heap.length === 0) return null;
        if (heap.length === 1) return heap.pop();
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

  function reconstructSegments(previous, startId, goalId, nodeById) {
    const segments = [];
    const warnings = [];
    let currentId = goalId;

    while (currentId !== startId) {
      const entry = previous[currentId];
      if (!entry) return null;

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

  function findRoute({ nodes, routes, fromId, toId, ...rawOptions }) {
    if (fromId === toId) {
      return { found: false, message: '出発地と目的地が同じです。', warnings: [] };
    }

    const { graph, nodeById } = buildGraph(nodes, routes, rawOptions);
    if (!nodeById[fromId] || !nodeById[toId]) {
      return { found: false, message: '出発地または目的地のノードが見つかりませんでした。', warnings: [] };
    }

    const distances = { [fromId]: 0 };
    const previous = {};
    const queue = createPriorityQueue();
    const visited = new Set();
    queue.push({ nodeId: fromId, cost: 0 });

    while (queue.size > 0) {
      const current = queue.pop();
      if (!current || visited.has(current.nodeId)) continue;
      visited.add(current.nodeId);
      if (current.nodeId === toId) break;

      (graph[current.nodeId] || []).forEach(edge => {
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

    const reconstructed = reconstructSegments(previous, fromId, toId, nodeById);
    if (!reconstructed) {
      return { found: false, message: '条件に一致するルートが見つかりませんでした。', warnings: [] };
    }

    const totalDistanceKm = reconstructed.segments.reduce(
      (sum, segment) => sum + Math.max(0, normalizeNumber(segment.route?.distance_km) ?? 0),
      0
    );
    const totalTimeHours = reconstructed.segments.reduce(
      (sum, segment) => sum + Math.max(0, normalizeNumber(segment.route?.estimated_time_hours) ?? 0),
      0
    );
    const totalCostGold = reconstructed.segments.reduce(
      (sum, segment) => sum + Math.max(0, normalizeNumber(segment.route?.cost_gold) ?? 0),
      0
    );
    const maxDangerLevel = reconstructed.segments.reduce(
      (max, segment) => Math.max(max, Math.max(0, normalizeNumber(segment.route?.danger_level) ?? 0)),
      0
    );

    return {
      found: true,
      totalCost: distances[toId],
      totalDistanceKm,
      totalTimeHours,
      totalCostGold,
      maxDangerLevel,
      segments: reconstructed.segments,
      warnings: reconstructed.warnings
    };
  }

  return {
    BLOCKED_STATUSES,
    DEFAULT_ROUTE_COST,
    MINIMUM_EDGE_COST,
    buildGraph,
    computeRouteCost,
    evaluateRoute,
    findRoute,
    isSeasonalRoute,
    normalizeOptions
  };
});
