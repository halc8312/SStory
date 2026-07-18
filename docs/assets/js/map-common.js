/**
 * Map Common Utilities
 * interactive-map.js / leaflet-transport-map.js / route-search.js で共有する
 * 汎用ヘルパー。map系スクリプトより先に読み込むこと。
 */

(() => {
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function isFiniteNumber(value) {
    return Number.isFinite(Number(value));
  }

  function normalizeNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatMonths(months) {
    return Array.isArray(months) && months.length > 0 ? months.join(', ') : 'なし';
  }

  function buildLookupById(items) {
    return Object.fromEntries((items || []).filter(item => item?.id).map(item => [item.id, item]));
  }

  function createJsonFetcher(basePath, cacheBuster) {
    return async function fetchJson(name) {
      const response = await fetch(`${basePath}${name}?v=${cacheBuster}`);
      if (!response.ok) {
        throw new Error(`${name}: HTTP ${response.status}`);
      }
      return response.json();
    };
  }

  window.EternalArcadiaMapCommon = {
    escapeHtml,
    clamp,
    isFiniteNumber,
    normalizeNumber,
    formatMonths,
    buildLookupById,
    createJsonFetcher
  };
})();
