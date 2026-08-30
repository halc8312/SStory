/**
 * Pure helpers shared by the Eternal Arcadia v3 map and its Node tests.
 * Keep this file free of DOM and Leaflet dependencies.
 */
(function exposeMapV3Core(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.EternalArcadiaMapV3Core = api;
})(typeof globalThis === 'object' ? globalThis : this, () => {
  'use strict';

  const EXPECTED_TILE_SIZE = 512;
  const EA_WORLD_EXTENT = 10000;
  const TILE_MANIFEST_SCHEMA_VERSION = '1.0.0';
  const TILE_MANIFEST_TYPE = 'sstory-xyz-raster';
  const TILE_MANIFEST_GENERATOR = 'sstory-map-production/generate_tiles.py@1';
  const SHEET_TILE_INDEX_SCHEMA_VERSION = '2.0.0';
  const SHEET_TILE_INDEX_TYPE = 'sstory-sheet-tile-index';
  const SHEET_TILE_INDEX_SCHEMA_URL =
    'https://sstory.example/schemas/sheet-tile-index.schema.json';
  const SHEET_TILE_INDEX_GENERATOR = 'sstory-map-production/build_phase5_assets.py@1';
  const EXPECTED_BOUNDED_SHEET_COUNT = 23;
  const EXPECTED_DESCENDANT_TYPE_COUNTS = Object.freeze({
    continent: 5,
    region: 14,
    corridor: 1,
    settlement: 2
  });
  const PUBLICATION_STATUSES = new Set(['accepted', 'tiled', 'staging', 'published']);
  const SHA256_PATTERN = /^[a-f0-9]{64}$/;
  const ISO_UTC_DATE_TIME_PATTERN =
    /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?Z$/;
  const SHEET_TYPE_ORDER = Object.freeze({
    world: 0,
    continent: 1,
    region: 2,
    corridor: 3,
    settlement: 4
  });
  // Keep the browser boundary identical to every publication JSON schema:
  // identifiers must start with a lowercase ASCII letter.
  const SAFE_ID_PATTERN = /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$/;
  const WORLD_RELEASE_ID_PATTERN = /^world-v[1-9][0-9]*$/;

  function isObject(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
  }

  function readNumber(sources, keys, fallback = null) {
    for (const source of sources) {
      for (const key of keys) {
        if (source?.[key] === null || source?.[key] === undefined || source?.[key] === '') continue;
        const value = Number(source[key]);
        if (Number.isFinite(value)) return value;
      }
    }
    return fallback;
  }

  function readString(sources, keys) {
    for (const source of sources) {
      for (const key of keys) {
        const value = source?.[key];
        if (typeof value === 'string' && value.trim()) return value.trim();
      }
    }
    return null;
  }

  function firstTileTemplate(sources) {
    for (const source of sources) {
      const direct = readString([source], ['url_template', 'urlTemplate', 'template']);
      if (direct) return direct;

      const tiles = source?.tiles;
      if (typeof tiles === 'string' && tiles.trim()) return tiles.trim();
      if (Array.isArray(tiles)) {
        const template = tiles.find(value => typeof value === 'string' && value.trim());
        if (template) return template.trim();
      }
    }
    return null;
  }

  function resolveUrlTemplate(template, manifestUrl, documentUrl) {
    const pageUrl = documentUrl || 'http://localhost/';
    const manifestAbsoluteUrl = new URL(manifestUrl, pageUrl);
    const tokens = new Map([
      ['{z}', '__EA_V3_Z__'],
      ['{x}', '__EA_V3_X__'],
      ['{y}', '__EA_V3_Y__'],
      ['{-y}', '__EA_V3_NEG_Y__'],
      ['{r}', '__EA_V3_RETINA__'],
      ['{s}', '__EA_V3_SUBDOMAIN__']
    ]);
    let protectedTemplate = template;
    tokens.forEach((token, original) => {
      protectedTemplate = protectedTemplate.split(original).join(token);
    });
    let resolved = new URL(protectedTemplate, manifestAbsoluteUrl).href;
    tokens.forEach((token, original) => {
      resolved = resolved.split(token).join(original);
    });
    return resolved;
  }

  function requireHttpUrl(value, baseUrl, label) {
    if (typeof value !== 'string' || !value.trim()) {
      throw new Error(`${label} がありません。`);
    }
    let resolved;
    try {
      resolved = new URL(value.trim(), baseUrl || 'http://localhost/');
    } catch (_error) {
      throw new Error(`${label} がURLとして不正です。`);
    }
    if (!['http:', 'https:'].includes(resolved.protocol)) {
      throw new Error(`${label} は HTTP(S) URL である必要があります。`);
    }
    return resolved.href;
  }

  function exactString(source, key, expected, label = key) {
    const value = source?.[key];
    if (value !== expected) {
      throw new Error(`${label} は ${expected} である必要があります（${String(value)}）。`);
    }
    return value;
  }

  function requireSha256(value, label) {
    if (typeof value !== 'string' || !SHA256_PATTERN.test(value)) {
      throw new Error(`${label} は小文字64桁の SHA-256 である必要があります。`);
    }
    return value;
  }

  function normalizeManifestLevels(manifest, imageWidth, imageHeight, minZoom, maxZoom) {
    if (!Array.isArray(manifest.levels) || manifest.levels.length !== maxZoom - minZoom + 1) {
      throw new Error('tile manifest の levels がズーム範囲を完全に記述していません。');
    }
    const byZoom = new Map();
    manifest.levels.forEach(level => {
      if (!isObject(level) || !Number.isInteger(level.zoom) || byZoom.has(level.zoom)) {
        throw new Error('tile manifest の levels に不正または重複した zoom があります。');
      }
      byZoom.set(level.zoom, level);
    });

    const levels = [];
    for (let zoom = minZoom; zoom <= maxZoom; zoom += 1) {
      const level = byZoom.get(zoom);
      if (!level) throw new Error(`tile manifest の level Z${zoom} がありません。`);
      const factor = 2 ** (maxZoom - zoom);
      const expectedWidth = Math.max(1, Math.ceil(imageWidth / factor));
      const expectedHeight = Math.max(1, Math.ceil(imageHeight / factor));
      const expectedColumns = Math.ceil(expectedWidth / EXPECTED_TILE_SIZE);
      const expectedRows = Math.ceil(expectedHeight / EXPECTED_TILE_SIZE);
      const values = [level.width, level.height, level.columns, level.rows, level.tile_count];
      if (!values.every(Number.isInteger) ||
          level.width !== expectedWidth || level.height !== expectedHeight ||
          level.columns !== expectedColumns || level.rows !== expectedRows ||
          level.tile_count !== expectedColumns * expectedRows) {
        throw new Error(`tile manifest の level Z${zoom} の寸法またはタイル数が不正です。`);
      }
      levels.push(Object.freeze({
        zoom,
        width: level.width,
        height: level.height,
        columns: level.columns,
        rows: level.rows,
        tileCount: level.tile_count
      }));
    }
    return Object.freeze(levels);
  }

  /** Normalize the generated, versioned 512 px world XYZ manifest fail-closed. */
  function normalizeTileManifest(result, pixelMapping, documentUrl) {
    if (!result?.manifest || !result?.url) return null;
    const rootManifest = result.manifest;
    if (!isObject(rootManifest)) throw new Error('tile manifest のルートはオブジェクトである必要があります。');

    exactString(rootManifest, 'schema_version', TILE_MANIFEST_SCHEMA_VERSION, 'tile manifest schema_version');
    exactString(rootManifest, 'type', TILE_MANIFEST_TYPE, 'tile manifest type');
    exactString(rootManifest, 'scheme', 'xyz', 'tile manifest scheme');
    exactString(rootManifest, 'format', 'webp', 'tile manifest format');
    exactString(
      rootManifest,
      'coordinate_reference_system',
      'EA-WORLD-1',
      'tile manifest coordinate_reference_system'
    );
    if (!isObject(rootManifest.master)) {
      throw new Error('tile manifest の master はオブジェクトである必要があります。');
    }
    const master = rootManifest.master;
    const tileSize = rootManifest.tile_size;
    const imageWidth = master.width;
    const imageHeight = master.height;
    const minNativeZoom = rootManifest.minzoom;
    const maxNativeZoom = rootManifest.maxzoom;
    const nativeZoom = rootManifest.native_zoom;
    const template = firstTileTemplate([rootManifest]);

    if (tileSize !== EXPECTED_TILE_SIZE) {
      throw new Error(`タイルサイズは${EXPECTED_TILE_SIZE}pxである必要があります（${tileSize}px）。`);
    }
    if (!template || !template.includes('{z}') || !template.includes('{x}') || !template.includes('{y}')) {
      throw new Error('tile manifest の tiles/url_template に {z}/{x}/{y} が必要です。');
    }
    if (!Number.isInteger(minNativeZoom) || !Number.isInteger(maxNativeZoom) ||
        !Number.isInteger(nativeZoom) || minNativeZoom < 0 || maxNativeZoom < minNativeZoom ||
        nativeZoom < minNativeZoom || nativeZoom > maxNativeZoom) {
      throw new Error('tile manifest のズーム範囲が不正です。');
    }
    if (!Number.isFinite(imageWidth) || imageWidth <= 0 ||
        !Number.isFinite(imageHeight) || imageHeight <= 0) {
      throw new Error('tile manifest の master 画像寸法が不正です。');
    }

    const { imageWidth: mappingWidth, imageHeight: mappingHeight } = normalizePixelMapping(pixelMapping);
    if (imageWidth !== mappingWidth || imageHeight !== mappingHeight) {
      throw new Error('tile manifest と pixel-mapping.json の画像寸法が一致しません。');
    }

    const bounds = normalizeBounds(rootManifest.bounds);
    if (!bounds || bounds.some((value, index) => value !== [0, 0, EA_WORLD_EXTENT, EA_WORLD_EXTENT][index])) {
      throw new Error('world tile manifest の bounds は EA-WORLD-1 全域である必要があります。');
    }
    const levels = normalizeManifestLevels(
      rootManifest,
      imageWidth,
      imageHeight,
      minNativeZoom,
      maxNativeZoom
    );
    const declaredTileCount = rootManifest.tile_count;
    const computedTileCount = levels.reduce((total, level) => total + level.tileCount, 0);
    if (declaredTileCount !== undefined &&
        (!Number.isInteger(declaredTileCount) || declaredTileCount !== computedTileCount)) {
      throw new Error('tile manifest の tile_count が levels の合計と一致しません。');
    }
    const urlTemplate = resolveUrlTemplate(template, result.url, documentUrl);
    requireHttpUrl(urlTemplate, documentUrl, 'tile URL template');
    const manifestUrl = requireHttpUrl(result.url, documentUrl, 'tile manifest URL');
    const mapIdValue = readString([rootManifest], ['map_id']);
    const mapId = mapIdValue === null ? null : normalizeSafeId(mapIdValue, 'tile manifest map_id');
    const releaseId = rootManifest.release_id === undefined
      ? null
      : normalizeSafeId(rootManifest.release_id, 'tile manifest release_id');
    const masterSha256 = rootManifest.master.sha256 === undefined
      ? null
      : requireSha256(rootManifest.master.sha256, 'tile manifest master.sha256');
    const tileSetSha256 = rootManifest.tile_set_sha256 === undefined
      ? null
      : requireSha256(rootManifest.tile_set_sha256, 'tile manifest tile_set_sha256');

    return Object.freeze({
      schemaVersion: TILE_MANIFEST_SCHEMA_VERSION,
      manifestUrl,
      releaseId,
      mapId,
      tileSize,
      imageWidth,
      imageHeight,
      minNativeZoom,
      maxNativeZoom,
      nativeZoom,
      bounds: Object.freeze(bounds),
      levels,
      masterSha256,
      tileSetSha256,
      tileCount: declaredTileCount ?? computedTileCount,
      urlTemplate,
      attribution: readString([rootManifest], ['attribution']) || 'Eternal Arcadia deep-zoom tiles'
    });
  }

  /** At nativeZoom, one projected source pixel is exactly one display pixel. */
  function scaleAtZoom(zoom, nativeZoom) {
    return 2 ** (Number(zoom) - Number(nativeZoom));
  }

  function zoomAtScale(scale, nativeZoom) {
    if (!(Number(scale) > 0)) throw new Error('scale must be greater than zero');
    return Math.log2(Number(scale)) + Number(nativeZoom);
  }

  function selectLod(definitions, zoom, fitZoom) {
    if (!Array.isArray(definitions) || definitions.length === 0) {
      throw new Error('LOD definitions are required');
    }
    const offset = Number(zoom) - Number(fitZoom);
    return [...definitions].reverse().find(definition => offset >= definition.minOffset) || definitions[0];
  }

  function normalizeBounds(value) {
    if (!Array.isArray(value) || value.length !== 4) return null;
    const bounds = value.map(Number);
    if (!bounds.every(Number.isFinite)) return null;
    const [minX, minY, maxX, maxY] = bounds;
    if (minX < 0 || minY < 0 || maxX > EA_WORLD_EXTENT || maxY > EA_WORLD_EXTENT ||
        minX >= maxX || minY >= maxY) return null;
    return bounds;
  }

  function normalizePixelMapping(pixelMapping) {
    const imageWidth = Number(pixelMapping?.image_width ?? pixelMapping?.imageWidth);
    const imageHeight = Number(pixelMapping?.image_height ?? pixelMapping?.imageHeight);
    if (!(imageWidth > 0) || !(imageHeight > 0)) {
      throw new Error('pixel mapping の画像寸法が不正です。');
    }
    return { imageWidth, imageHeight };
  }

  /** Convert [minX,minY,maxX,maxY] in EA-WORLD-1 to source-image pixels. */
  function eaWorldBoundsToPixelBounds(bounds, pixelMapping) {
    const normalized = normalizeBounds(bounds);
    if (!normalized) throw new Error('EA-WORLD-1 bounds が不正です。');
    const { imageWidth, imageHeight } = normalizePixelMapping(pixelMapping);
    const [minX, minY, maxX, maxY] = normalized;
    return [
      minX / EA_WORLD_EXTENT * imageWidth,
      minY / EA_WORLD_EXTENT * imageHeight,
      maxX / EA_WORLD_EXTENT * imageWidth,
      maxY / EA_WORLD_EXTENT * imageHeight
    ];
  }

  /** Leaflet CRS.Simple uses [lat,lng] = [-pixelY,pixelX]. */
  function eaWorldBoundsToLeafletBounds(bounds, pixelMapping) {
    const [minX, minY, maxX, maxY] = eaWorldBoundsToPixelBounds(bounds, pixelMapping);
    return [[-maxY, minX], [-minY, maxX]];
  }

  /** Convert a plain Leaflet viewport {west,south,east,north} back to EA-WORLD-1. */
  function leafletBoundsToEaWorldBounds(bounds, pixelMapping) {
    const { imageWidth, imageHeight } = normalizePixelMapping(pixelMapping);
    const west = Number(bounds?.west);
    const south = Number(bounds?.south);
    const east = Number(bounds?.east);
    const north = Number(bounds?.north);
    if (![west, south, east, north].every(Number.isFinite)) {
      throw new Error('Leaflet bounds が不正です。');
    }
    const clamp = value => Math.min(EA_WORLD_EXTENT, Math.max(0, value));
    const converted = [
      clamp(west / imageWidth * EA_WORLD_EXTENT),
      clamp(-north / imageHeight * EA_WORLD_EXTENT),
      clamp(east / imageWidth * EA_WORLD_EXTENT),
      clamp(-south / imageHeight * EA_WORLD_EXTENT)
    ];
    if (converted[0] >= converted[2] || converted[1] >= converted[3]) return null;
    return converted;
  }

  function boundsIntersect(first, second) {
    const a = normalizeBounds(first);
    const b = normalizeBounds(second);
    if (!a || !b) return false;
    return a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
  }

  function boundsIntersectionArea(first, second) {
    if (!boundsIntersect(first, second)) return 0;
    const a = normalizeBounds(first);
    const b = normalizeBounds(second);
    return Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
      Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  }

  function boundsArea(bounds) {
    const normalized = normalizeBounds(bounds);
    return normalized ? (normalized[2] - normalized[0]) * (normalized[3] - normalized[1]) : 0;
  }

  function boundsCenter(bounds) {
    const normalized = normalizeBounds(bounds);
    if (!normalized) return null;
    return [(normalized[0] + normalized[2]) / 2, (normalized[1] + normalized[3]) / 2];
  }

  function boundsContain(outer, inner) {
    const a = normalizeBounds(outer);
    const b = normalizeBounds(inner);
    return Boolean(a && b && a[0] <= b[0] && a[1] <= b[1] && a[2] >= b[2] && a[3] >= b[3]);
  }

  function normalizeSafeId(value, label) {
    if (typeof value !== 'string' || !SAFE_ID_PATTERN.test(value)) {
      throw new Error(`${label} は安全な小文字IDである必要があります。`);
    }
    return value;
  }

  function requireSafeRelativePath(value, label, { json = false, allowParent = false } = {}) {
    if (typeof value !== 'string' || value !== value.trim() || !value) {
      throw new Error(`${label} は空白のない相対パスである必要があります。`);
    }
    if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(value) || value.startsWith('/') ||
        value.includes('\\') || value.includes('?') || value.includes('#')) {
      throw new Error(`${label} は安全なリポジトリ相対パスである必要があります。`);
    }
    const segments = value.split('/');
    if (segments.some(segment => !segment || segment === '.' || (!allowParent && segment === '..'))) {
      throw new Error(`${label} は安全なリポジトリ相対パスである必要があります。`);
    }
    for (const segment of segments) {
      let decoded;
      try {
        decoded = decodeURIComponent(segment);
      } catch (_error) {
        throw new Error(`${label} に不正なURLエンコードがあります。`);
      }
      if (decoded === '.' || (!allowParent && decoded === '..') ||
          decoded.includes('/') || decoded.includes('\\')) {
        throw new Error(`${label} はパストラバーサルを含められません。`);
      }
    }
    if (json && !value.toLowerCase().endsWith('.json')) {
      throw new Error(`${label} は JSON を指す必要があります。`);
    }
    return value;
  }

  function normalizeEvidenceArtifact(value, label) {
    if (!isObject(value)) throw new Error(`${label} はオブジェクトである必要があります。`);
    return Object.freeze({
      path: requireSafeRelativePath(value.path, `${label}.path`),
      sha256: requireSha256(value.sha256, `${label}.sha256`)
    });
  }

  function normalizePublicationEvidence(value, label) {
    if (!isObject(value)) throw new Error(`${label} はオブジェクトである必要があります。`);
    if (!Array.isArray(value.vision_reviews) || value.vision_reviews.length < 1) {
      throw new Error(`${label}.vision_reviews には1件以上の査読証跡が必要です。`);
    }
    return Object.freeze({
      provenance: normalizeEvidenceArtifact(value.provenance, `${label}.provenance`),
      automatedQa: normalizeEvidenceArtifact(value.automated_qa, `${label}.automated_qa`),
      visionReviews: Object.freeze(value.vision_reviews.map((artifact, index) =>
        normalizeEvidenceArtifact(artifact, `${label}.vision_reviews[${index}]`)))
    });
  }

  function normalizePublishedSheetEntry(
    entry,
    entryIndex,
    rootId,
    indexUrl,
    worldNativeZoom,
    releaseId,
    { root = false } = {}
  ) {
    const label = root ? 'sheet tile index root' : `sheet tile index sheets[${entryIndex}]`;
    if (!isObject(entry)) throw new Error(`${label} はオブジェクトである必要があります。`);
    const id = normalizeSafeId(entry.id, `${label}.id`);
    const sheetId = normalizeSafeId(entry.sheet_id, `${label}.sheet_id`);
    if (sheetId !== id) throw new Error(`${label}: id と sheet_id が一致しません。`);
    const name = readString([entry], ['name']);
    if (!name) throw new Error(`${id}: name がありません。`);
    const sheetType = entry.sheet_type;
    if (!(sheetType in SHEET_TYPE_ORDER) || (root ? sheetType !== 'world' : sheetType === 'world')) {
      throw new Error(`${id}: sheet_type が不正です。`);
    }
    let parentId = null;
    if (root) {
      if (entry.parent_id !== null) throw new Error(`${id}: world parent_id は null である必要があります。`);
    } else {
      parentId = normalizeSafeId(entry.parent_id, `${id}.parent_id`);
      if (parentId === id) throw new Error(`${id}: 自身を parent_id に指定できません。`);
    }
    if (!Array.isArray(entry.secondary_parent_ids)) {
      throw new Error(`${id}.secondary_parent_ids は配列である必要があります。`);
    }
    const secondaryParentIds = entry.secondary_parent_ids.map((parent, secondaryIndex) =>
      normalizeSafeId(parent, `${id}.secondary_parent_ids[${secondaryIndex}]`));
    if (new Set(secondaryParentIds).size !== secondaryParentIds.length ||
        secondaryParentIds.includes(id) || secondaryParentIds.includes(parentId)) {
      throw new Error(`${id}: secondary_parent_ids が重複または循環しています。`);
    }
    const sourceFeatureId = entry.source_feature_id === null
      ? null
      : normalizeSafeId(entry.source_feature_id, `${id}.source_feature_id`);
    const bounds = normalizeBounds(entry.bounds);
    if (!bounds) throw new Error(`${id}: EA-WORLD-1 bounds が不正です。`);
    if (!Array.isArray(entry.zoom_range) || entry.zoom_range.length !== 2 ||
        !entry.zoom_range.every(Number.isInteger)) {
      throw new Error(`${id}: zoom_range は2整数である必要があります。`);
    }
    const [minNativeZoom, maxNativeZoom] = entry.zoom_range;
    const nativeZoom = entry.native_zoom;
    if (!Number.isInteger(nativeZoom) || minNativeZoom < 0 || minNativeZoom > nativeZoom ||
        maxNativeZoom !== nativeZoom || nativeZoom > 24) {
      throw new Error(`${id}: zoom_range/native_zoom が不正です。`);
    }
    if ((root && nativeZoom !== worldNativeZoom) || (!root && minNativeZoom < worldNativeZoom)) {
      throw new Error(`${id}: world native zoom との解像度契約が不正です。`);
    }
    if (entry.review_status !== 'accepted') {
      throw new Error(`${id}: review_status は accepted である必要があります。`);
    }
    if (!PUBLICATION_STATUSES.has(entry.status)) {
      throw new Error(`${id}: status が公開契約外です。`);
    }
    const rawManifestUrl = requireSafeRelativePath(
      entry.manifest_url,
      `${id}.manifest_url`,
      { json: true, allowParent: true }
    );
    const manifestUrl = requireHttpUrl(rawManifestUrl, indexUrl, `${id}.manifest_url`);
    const expectedManifestPath = root
      ? `../../assets/images/maps/tiles/${releaseId}/metadata.json`
      : `../../assets/images/maps/tiles/${releaseId}/sheets/${id}/metadata.json`;
    if (rawManifestUrl !== expectedManifestPath) {
      throw new Error(`${id}.manifest_url が immutable release directory と一致しません。`);
    }
    const priority = entry.priority;
    if (!Number.isInteger(priority) || priority < 0) throw new Error(`${id}.priority が不正です。`);
    const tileCount = entry.tile_count;
    if (!Number.isInteger(tileCount) || tileCount < 1) {
      throw new Error(`${id}.tile_count は1以上の整数である必要があります。`);
    }
    return {
      id,
      sheetId,
      name,
      sheetType,
      parentId,
      secondaryParentIds,
      sourceFeatureId,
      regionId: sourceFeatureId || id,
      reviewStatus: 'accepted',
      status: entry.status,
      bounds,
      minNativeZoom,
      maxNativeZoom,
      nativeZoom,
      rawManifestUrl,
      manifestUrl,
      priority,
      masterSha256: requireSha256(entry.master_sha256, `${id}.master_sha256`),
      manifestSha256: requireSha256(entry.manifest_sha256, `${id}.manifest_sha256`),
      tileSetSha256: requireSha256(entry.tile_set_sha256, `${id}.tile_set_sha256`),
      tileCount,
      evidence: normalizePublicationEvidence(entry.evidence, `${id}.evidence`)
    };
  }

  /**
   * Normalize the optional per-sheet tile index. The index is an acceptance
   * boundary, so malformed accepted data rejects the complete index instead of
   * silently publishing only a convenient subset.
   */
  function normalizeSheetTileIndex(result, pixelMapping, documentUrl, worldNativeZoom = 3) {
    const index = isObject(result?.index) ? result.index : result;
    if (!isObject(index)) throw new Error('sheet tile index のルートはオブジェクトである必要があります。');
    exactString(index, '$schema', SHEET_TILE_INDEX_SCHEMA_URL, 'sheet tile index $schema');
    exactString(index, 'schema_version', SHEET_TILE_INDEX_SCHEMA_VERSION, 'sheet tile index schema_version');
    exactString(index, 'type', SHEET_TILE_INDEX_TYPE, 'sheet tile index type');
    exactString(
      index,
      'coordinate_reference_system',
      'EA-WORLD-1',
      'sheet tile index coordinate_reference_system'
    );
    if (!Array.isArray(index.bounds_order) ||
        index.bounds_order.length !== 4 ||
        index.bounds_order.some((value, position) =>
          value !== ['min_x', 'min_y', 'max_x', 'max_y'][position])) {
      throw new Error('sheet tile index bounds_order が不正です。');
    }
    exactString(index, 'generated_by', SHEET_TILE_INDEX_GENERATOR, 'sheet tile index generated_by');
    if (typeof index.generated_at !== 'string' ||
        !ISO_UTC_DATE_TIME_PATTERN.test(index.generated_at) ||
        !Number.isFinite(Date.parse(index.generated_at))) {
      throw new Error('sheet tile index generated_at が不正です。');
    }
    const releaseId = normalizeSafeId(index.release_id, 'sheet tile index release_id');
    if (index.bounded_sheet_count !== EXPECTED_BOUNDED_SHEET_COUNT) {
      throw new Error(`sheet tile index bounded_sheet_count は${EXPECTED_BOUNDED_SHEET_COUNT}である必要があります。`);
    }
    if (typeof index.description !== 'string' || !index.description.trim()) {
      throw new Error('sheet tile index description がありません。');
    }
    normalizePixelMapping(pixelMapping);
    if (!Number.isInteger(worldNativeZoom) || worldNativeZoom < 0) {
      throw new Error('world native zoom must be a non-negative integer');
    }
    if (!Array.isArray(index.sheets) || index.sheets.length !== EXPECTED_BOUNDED_SHEET_COUNT - 1) {
      throw new Error('sheet tile index の sheets は完全な22件である必要があります。');
    }
    const rootId = normalizeSafeId(index.root_id, 'sheet tile index root_id');
    if (rootId !== 'sheet_world') throw new Error('sheet tile index root_id は sheet_world である必要があります。');
    const indexUrl = requireHttpUrl(result?.url || documentUrl, documentUrl, 'sheet tile index URL');
    const rootEntry = normalizePublishedSheetEntry(
      index.root,
      -1,
      rootId,
      indexUrl,
      worldNativeZoom,
      releaseId,
      { root: true }
    );
    if (rootEntry.id !== rootId || rootEntry.sheetId !== rootId ||
        rootEntry.sourceFeatureId !== null || rootEntry.secondaryParentIds.length !== 0 ||
        !boundsEqual(rootEntry.bounds, [0, 0, EA_WORLD_EXTENT, EA_WORLD_EXTENT])) {
      throw new Error('sheet tile index root の完全identityが不正です。');
    }
    const accepted = index.sheets.map((entry, entryIndex) => normalizePublishedSheetEntry(
      entry,
      entryIndex,
      rootId,
      indexUrl,
      worldNativeZoom,
      releaseId
    ));
    const allIds = [rootId, ...accepted.map(entry => entry.id)];
    if (new Set(allIds).size !== EXPECTED_BOUNDED_SHEET_COUNT) {
      throw new Error('sheet tile index に重複IDまたは root の再定義があります。');
    }
    const typeCounts = Object.fromEntries(Object.keys(EXPECTED_DESCENDANT_TYPE_COUNTS)
      .map(type => [type, accepted.filter(entry => entry.sheetType === type).length]));
    if (Object.entries(EXPECTED_DESCENDANT_TYPE_COUNTS)
      .some(([type, count]) => typeCounts[type] !== count)) {
      throw new Error('sheet tile index の型別件数は continent/region/corridor/settlement = 5/14/1/2 が必要です。');
    }

    const byId = new Map([[rootId, rootEntry], ...accepted.map(entry => [entry.id, entry])]);
    const depthMemo = new Map();
    function depthFor(entry, trail = new Set()) {
      if (entry.id === rootId) return 0;
      if (depthMemo.has(entry.id)) return depthMemo.get(entry.id);
      if (trail.has(entry.id)) throw new Error(`sheet tile index の親子関係が循環しています（${entry.id}）。`);
      trail.add(entry.id);
      const parent = byId.get(entry.parentId);
      if (!parent) throw new Error(`${entry.id}: accepted parent ${entry.parentId} がありません。`);
      const parentDepth = depthFor(parent, trail);
      const parentType = parent.sheetType;
      const parentBounds = parent.bounds;
      const parentNativeZoom = parent.nativeZoom;
      trail.delete(entry.id);
      if (SHEET_TYPE_ORDER[entry.sheetType] <= SHEET_TYPE_ORDER[parentType]) {
        throw new Error(`${entry.id}: sheet_type が親より詳細ではありません。`);
      }
      if (!boundsContain(parentBounds, entry.bounds)) {
        throw new Error(`${entry.id}: bounds が親シートの範囲外です。`);
      }
      if (entry.nativeZoom <= parentNativeZoom) {
        throw new Error(`${entry.id}: native_zoom が親より深くありません。`);
      }
      entry.secondaryParentIds.forEach(secondaryId => {
        const secondary = byId.get(secondaryId);
        if (!secondary) throw new Error(`${entry.id}: accepted secondary parent ${secondaryId} がありません。`);
        if (SHEET_TYPE_ORDER[secondary.sheetType] >= SHEET_TYPE_ORDER[entry.sheetType]) {
          throw new Error(`${entry.id}: secondary parent の階層が不正です。`);
        }
        if (!boundsContain(secondary.bounds, entry.bounds)) {
          throw new Error(`${entry.id}: bounds が secondary parent ${secondaryId} の範囲外です。`);
        }
      });
      const depth = parentDepth + 1;
      depthMemo.set(entry.id, depth);
      return depth;
    }

    const sheets = Object.freeze(accepted
      .map(entry => Object.freeze({
        ...entry,
        releaseId,
        bounds: Object.freeze([...entry.bounds]),
        secondaryParentIds: Object.freeze([...entry.secondaryParentIds]),
        evidence: entry.evidence,
        depth: depthFor(entry)
      }))
      .sort((a, b) => a.depth - b.depth || a.id.localeCompare(b.id)));
    return Object.freeze({
      schemaVersion: SHEET_TILE_INDEX_SCHEMA_VERSION,
      coordinateReferenceSystem: 'EA-WORLD-1',
      generatedBy: SHEET_TILE_INDEX_GENERATOR,
      releaseId,
      boundedSheetCount: EXPECTED_BOUNDED_SHEET_COUNT,
      rootId,
      root: Object.freeze({
        ...rootEntry,
        releaseId,
        bounds: Object.freeze([...rootEntry.bounds]),
        secondaryParentIds: Object.freeze([]),
        depth: 0
      }),
      sheets,
      // Retain the neutral raster collection name for search/native-zoom helpers.
      rasters: sheets
    });
  }

  /** Refuse to mix a rollback world with an index from a different immutable release. */
  function assertSheetTileIndexWorldIdentity(index, worldRelease) {
    const rootEntry = index?.root;
    const worldManifest = worldRelease?.manifest;
    if (!isObject(index) || !isObject(rootEntry) || !isObject(worldRelease) || !isObject(worldManifest)) {
      throw new Error('world release と sheet tile index のidentityが不足しています。');
    }
    const actualReleaseId = normalizeSafeId(worldRelease.releaseId, 'loaded world release');
    if (!worldManifest.releaseId || index.releaseId !== actualReleaseId ||
        worldManifest.releaseId !== actualReleaseId) {
      throw new Error('sheet tile index release_id が実際に読み込んだ world release と一致しません。');
    }
    const actualManifestUrl = requireHttpUrl(
      worldRelease.manifestUrl || worldManifest.manifestUrl,
      worldManifest.manifestUrl,
      'loaded world manifest URL'
    );
    const actualManifestSha256 = requireSha256(
      worldRelease.manifestSha256,
      'loaded world manifest SHA-256'
    );
    if (rootEntry.id !== index.rootId || rootEntry.sheetId !== index.rootId ||
        worldManifest.mapId !== index.rootId || rootEntry.manifestUrl !== actualManifestUrl ||
        rootEntry.manifestSha256 !== actualManifestSha256 ||
        rootEntry.nativeZoom !== worldManifest.nativeZoom ||
        rootEntry.minNativeZoom !== worldManifest.minNativeZoom ||
        rootEntry.maxNativeZoom !== worldManifest.maxNativeZoom ||
        !boundsEqual(rootEntry.bounds, worldManifest.bounds) ||
        !worldManifest.masterSha256 || rootEntry.masterSha256 !== worldManifest.masterSha256 ||
        !worldManifest.tileSetSha256 || rootEntry.tileSetSha256 !== worldManifest.tileSetSha256 ||
        rootEntry.tileCount !== worldManifest.tileCount) {
      throw new Error('sheet tile index root が実際に読み込んだ world manifest のidentityと一致しません。');
    }
    return true;
  }

  function boundsEqual(first, second, tolerance = 1e-6) {
    const a = normalizeBounds(first);
    const b = normalizeBounds(second);
    return Boolean(a && b && a.every((value, index) => Math.abs(value - b[index]) <= tolerance));
  }

  /** Normalize one accepted sheet's generated 512 px XYZ metadata. */
  function normalizeSheetTileManifest(result, sheet, pixelMapping, documentUrl, worldNativeZoom = 3) {
    if (!isObject(sheet) || sheet.reviewStatus !== 'accepted') {
      throw new Error('accepted sheet entry が必要です。');
    }
    if (!result?.manifest || !result?.url || !isObject(result.manifest)) {
      throw new Error(`${sheet.id}: tile manifest がありません。`);
    }
    const manifest = result.manifest;
    exactString(manifest, 'schema_version', TILE_MANIFEST_SCHEMA_VERSION, `${sheet.id} schema_version`);
    exactString(manifest, 'type', TILE_MANIFEST_TYPE, `${sheet.id} type`);
    exactString(manifest, 'generated_by', TILE_MANIFEST_GENERATOR, `${sheet.id} generated_by`);
    if (typeof manifest.generated_at !== 'string' ||
        !ISO_UTC_DATE_TIME_PATTERN.test(manifest.generated_at) ||
        !Number.isFinite(Date.parse(manifest.generated_at))) {
      throw new Error(`${sheet.id}: generated_at が不正です。`);
    }
    if (normalizeSafeId(manifest.release_id, `${sheet.id} release_id`) !== sheet.releaseId) {
      throw new Error(`${sheet.id}: manifest release_id が index と一致しません。`);
    }
    exactString(manifest, 'scheme', 'xyz', `${sheet.id} scheme`);
    exactString(manifest, 'format', 'webp', `${sheet.id} format`);
    exactString(manifest, 'coordinate_reference_system', 'EA-WORLD-1', `${sheet.id} CRS`);
    exactString(manifest, 'coordinate_system', 'EA-WORLD-1', `${sheet.id} coordinate_system`);
    if (manifest.map_id !== sheet.id) throw new Error(`${sheet.id}: manifest map_id が一致しません。`);
    if (manifest.tile_size !== EXPECTED_TILE_SIZE) {
      throw new Error(`${sheet.id}: タイルサイズは${EXPECTED_TILE_SIZE}pxである必要があります。`);
    }
    if (manifest.minzoom !== sheet.minNativeZoom || manifest.maxzoom !== sheet.maxNativeZoom ||
        manifest.native_zoom !== sheet.nativeZoom) {
      throw new Error(`${sheet.id}: manifest のズーム契約が index と一致しません。`);
    }
    if (!boundsEqual(manifest.bounds, sheet.bounds)) {
      throw new Error(`${sheet.id}: manifest bounds が index と一致しません。`);
    }
    if (!isObject(manifest.master) || !Number.isInteger(manifest.master.width) ||
        !Number.isInteger(manifest.master.height) || manifest.master.width <= 0 ||
        manifest.master.height <= 0) {
      throw new Error(`${sheet.id}: manifest master の寸法が不正です。`);
    }
    if (manifest.master.mode !== 'RGBA' ||
        requireSha256(manifest.master.sha256, `${sheet.id} master.sha256`) !== sheet.masterSha256) {
      throw new Error(`${sheet.id}: manifest master identity が index と一致しません。`);
    }
    const transparentBackground = manifest.encoding?.background;
    if (transparentBackground !== '#00000000' && transparentBackground !== 'transparent') {
      throw new Error(`${sheet.id}: 端タイルのパディングは透明である必要があります。`);
    }
    const worldPixels = eaWorldBoundsToPixelBounds(sheet.bounds, pixelMapping);
    const scale = 2 ** (sheet.nativeZoom - worldNativeZoom);
    const expectedWidth = (worldPixels[2] - worldPixels[0]) * scale;
    const expectedHeight = (worldPixels[3] - worldPixels[1]) * scale;
    if (Math.abs(manifest.master.width - expectedWidth) > 2 ||
        Math.abs(manifest.master.height - expectedHeight) > 2) {
      throw new Error(`${sheet.id}: master 画素密度が EA-WORLD-1/native_zoom と一致しません。`);
    }
    const template = firstTileTemplate([manifest]);
    if (!template || !template.includes('{z}') || !template.includes('{x}') || !template.includes('{y}')) {
      throw new Error(`${sheet.id}: tiles に {z}/{x}/{y} が必要です。`);
    }
    const urlTemplate = resolveUrlTemplate(template, result.url, documentUrl);
    requireHttpUrl(urlTemplate, documentUrl, `${sheet.id} tile URL template`);
    const levels = normalizeManifestLevels(
      manifest,
      manifest.master.width,
      manifest.master.height,
      manifest.minzoom,
      manifest.maxzoom
    );
    const computedTileCount = levels.reduce((total, level) => total + level.tileCount, 0);
    if (manifest.tile_count !== computedTileCount || manifest.tile_count !== sheet.tileCount) {
      throw new Error(`${sheet.id}: manifest tile_count が index/levels と一致しません。`);
    }
    if (requireSha256(manifest.tile_set_sha256, `${sheet.id} tile_set_sha256`) !==
        sheet.tileSetSha256) {
      throw new Error(`${sheet.id}: manifest tile_set_sha256 が index と一致しません。`);
    }
    return Object.freeze({
      sheetId: sheet.id,
      releaseId: sheet.releaseId,
      tileSize: EXPECTED_TILE_SIZE,
      imageWidth: manifest.master.width,
      imageHeight: manifest.master.height,
      minNativeZoom: manifest.minzoom,
      maxNativeZoom: manifest.maxzoom,
      nativeZoom: manifest.native_zoom,
      bounds: Object.freeze([...sheet.bounds]),
      levels,
      urlTemplate
    });
  }

  /** Rank intersecting rasters by explicit priority, visible coverage and proximity. */
  function rankRegionRasters(rasters, viewportBounds) {
    const viewport = normalizeBounds(viewportBounds);
    if (!viewport || !Array.isArray(rasters)) return [];
    const viewportCenter = boundsCenter(viewport);
    return rasters
      .filter(raster => normalizeBounds(raster?.bounds) && boundsIntersect(raster.bounds, viewport))
      .map(raster => {
        const center = boundsCenter(raster.bounds);
        const overlapArea = boundsIntersectionArea(raster.bounds, viewport);
        const coverage = overlapArea / Math.max(1, boundsArea(raster.bounds));
        const centerDistance = Math.hypot(center[0] - viewportCenter[0], center[1] - viewportCenter[1]);
        return { raster, coverage, centerDistance, area: boundsArea(raster.bounds) };
      })
      .sort((a, b) =>
        (Number(b.raster.priority) || 0) - (Number(a.raster.priority) || 0) ||
        b.coverage - a.coverage ||
        a.centerDistance - b.centerDistance ||
        a.area - b.area ||
        String(a.raster.id).localeCompare(String(b.raster.id))
      )
      .map(candidate => candidate.raster);
  }

  function sheetLineage(rasters, sheetId) {
    if (!Array.isArray(rasters)) return [];
    const byId = new Map(rasters.map(raster => [raster?.id, raster]).filter(pair => pair[0]));
    const lineage = [];
    const visited = new Set();
    let current = byId.get(sheetId);
    while (current) {
      if (visited.has(current.id)) throw new Error(`sheet hierarchy cycle: ${current.id}`);
      visited.add(current.id);
      lineage.unshift(current);
      current = byId.get(current.parentId ?? current.parent_id);
    }
    return lineage;
  }

  /** Expand visible leaves with every accepted in-index parent, parent-first. */
  function expandRasterSelectionWithParents(rasters, selectedIds) {
    if (!Array.isArray(rasters) || typeof selectedIds?.[Symbol.iterator] !== 'function') return [];
    const selected = new Map();
    for (const id of selectedIds) {
      sheetLineage(rasters, id).forEach(entry => selected.set(entry.id, entry));
    }
    return [...selected.values()].sort((a, b) =>
      (Number(a.depth) || 0) - (Number(b.depth) || 0) || String(a.id).localeCompare(String(b.id)));
  }

  /** Return the closest loaded parent, or the external world root when available. */
  function nearestReadyParentId(rasters, sheetId, readyIds, rootId = 'sheet_world') {
    if (typeof readyIds?.[Symbol.iterator] !== 'function') {
      throw new Error('ready IDs must be iterable');
    }
    const ready = new Set(readyIds);
    const lineage = sheetLineage(rasters, sheetId);
    for (let index = lineage.length - 2; index >= 0; index -= 1) {
      if (ready.has(lineage[index].id)) return lineage[index].id;
    }
    return ready.has(rootId) ? rootId : null;
  }

  function tileUrl(template, zoom, x, y, rows) {
    return template
      .split('{z}').join(String(zoom))
      .split('{x}').join(String(x))
      .split('{y}').join(String(y))
      .split('{-y}').join(String(rows - y - 1))
      .split('{r}').join('')
      .split('{s}').join('');
  }

  function sourceNativeZoomForMapZoom(mapZoom, minNativeZoom, maxNativeZoom) {
    const requested = Number(mapZoom);
    if (!Number.isFinite(requested) || !Number.isInteger(minNativeZoom) ||
        !Number.isInteger(maxNativeZoom) || minNativeZoom > maxNativeZoom) return null;
    const nearestInteger = Math.round(requested);
    const withoutFloatingPointNoise = Math.abs(requested - nearestInteger) <= 1e-7
      ? nearestInteger
      : requested;
    return Math.min(maxNativeZoom, Math.max(minNativeZoom, Math.ceil(withoutFloatingPointNoise)));
  }

  /**
   * List only the local 512 px sheet tiles intersecting the current viewport.
   * Tile bounds intentionally include transparent edge padding, preserving the
   * source pixel scale without stretching the last row/column.
   */
  function sheetTilesForViewport(sheet, manifest, viewportBounds, mapZoom) {
    const viewport = normalizeBounds(viewportBounds);
    if (!viewport || !boundsIntersect(sheet?.bounds, viewport)) return [];
    if (!manifest || manifest.sheetId !== sheet.id || !Array.isArray(manifest.levels)) return [];
    const zoom = sourceNativeZoomForMapZoom(
      mapZoom,
      manifest.minNativeZoom,
      manifest.maxNativeZoom
    );
    if (!Number.isInteger(zoom)) return [];
    const level = manifest.levels.find(candidate => candidate.zoom === zoom);
    if (!level) return [];
    const intersection = [
      Math.max(sheet.bounds[0], viewport[0]),
      Math.max(sheet.bounds[1], viewport[1]),
      Math.min(sheet.bounds[2], viewport[2]),
      Math.min(sheet.bounds[3], viewport[3])
    ];
    const spanX = sheet.bounds[2] - sheet.bounds[0];
    const spanY = sheet.bounds[3] - sheet.bounds[1];
    const pixelMinX = (intersection[0] - sheet.bounds[0]) / spanX * level.width;
    const pixelMinY = (intersection[1] - sheet.bounds[1]) / spanY * level.height;
    const pixelMaxX = (intersection[2] - sheet.bounds[0]) / spanX * level.width;
    const pixelMaxY = (intersection[3] - sheet.bounds[1]) / spanY * level.height;
    const minTileX = Math.max(0, Math.floor(pixelMinX / EXPECTED_TILE_SIZE));
    const minTileY = Math.max(0, Math.floor(pixelMinY / EXPECTED_TILE_SIZE));
    const maxTileX = Math.min(level.columns - 1, Math.max(minTileX, Math.ceil(pixelMaxX / EXPECTED_TILE_SIZE) - 1));
    const maxTileY = Math.min(level.rows - 1, Math.max(minTileY, Math.ceil(pixelMaxY / EXPECTED_TILE_SIZE) - 1));
    const tiles = [];
    for (let x = minTileX; x <= maxTileX; x += 1) {
      for (let y = minTileY; y <= maxTileY; y += 1) {
        const west = sheet.bounds[0] + x * EXPECTED_TILE_SIZE / level.width * spanX;
        const north = sheet.bounds[1] + y * EXPECTED_TILE_SIZE / level.height * spanY;
        const east = sheet.bounds[0] + (x + 1) * EXPECTED_TILE_SIZE / level.width * spanX;
        const south = sheet.bounds[1] + (y + 1) * EXPECTED_TILE_SIZE / level.height * spanY;
        tiles.push(Object.freeze({
          key: `${sheet.id}:${zoom}:${x}:${y}`,
          sheetId: sheet.id,
          zoom,
          x,
          y,
          url: tileUrl(manifest.urlTemplate, zoom, x, y, level.rows),
          bounds: Object.freeze([west, north, east, south])
        }));
      }
    }
    return Object.freeze(tiles);
  }

  /** True only after every tile required by the current viewport has decoded and displayed. */
  function allRequiredTilesReady(requiredKeys, tileStates) {
    if (typeof requiredKeys?.[Symbol.iterator] !== 'function' ||
        typeof tileStates?.get !== 'function') return false;
    const keys = [...requiredKeys];
    return keys.length > 0 && keys.every(key => tileStates.get(key)?.status === 'ready');
  }

  /** Keep the world parent available while accepted sheets unlock deeper display zooms. */
  function worldBaseTileLayerMaxZoom(worldMaxNativeZoom, safeDeepZoom = 8) {
    const worldMaximum = Number(worldMaxNativeZoom);
    const safeMaximum = Number(safeDeepZoom);
    if (!Number.isInteger(worldMaximum) || worldMaximum < 0 ||
        !Number.isInteger(safeMaximum) || safeMaximum < worldMaximum) {
      throw new Error('world base tile layer zoom contract is invalid');
    }
    return safeMaximum;
  }

  /**
   * Resolve a one-page preview request without persisting or constructing any
   * release URL from query-string input. Duplicate parameters fail closed.
   */
  function worldReleasePreviewFromUrl(documentUrl, targetRelease) {
    if (typeof targetRelease !== 'string' || !WORLD_RELEASE_ID_PATTERN.test(targetRelease)) {
      return null;
    }
    try {
      const values = new URL(documentUrl).searchParams.getAll('release-preview');
      return values.length === 1 && values[0] === targetRelease ? targetRelease : null;
    } catch (_error) {
      return null;
    }
  }

  function normalizeWorldReleaseConfiguration(config, documentUrl) {
    if (!isObject(config)) throw new Error('world release configuration is required');
    const activeRelease = normalizeSafeId(config.activeRelease, 'active world release');
    const targetRelease = config.targetRelease === undefined
      ? activeRelease
      : normalizeSafeId(config.targetRelease, 'target world release');
    if (typeof config.cacheKey !== 'string' || !/^[a-zA-Z0-9._-]{1,80}$/.test(config.cacheKey)) {
      throw new Error('world release cache key is invalid');
    }
    if (!Array.isArray(config.releases) || config.releases.length === 0) {
      throw new Error('world releases are required');
    }
    const releases = new Map();
    config.releases.forEach((release, index) => {
      if (!isObject(release)) throw new Error(`world release[${index}] is invalid`);
      const id = normalizeSafeId(release.id, `world release[${index}].id`);
      if (releases.has(id)) throw new Error(`duplicate world release: ${id}`);
      const manifestUrl = requireHttpUrl(release.manifestUrl, documentUrl, `${id}.manifestUrl`);
      if (!new URL(manifestUrl).pathname.toLowerCase().endsWith('.json')) {
        throw new Error(`${id}.manifestUrl must point to JSON`);
      }
      releases.set(id, Object.freeze({ id, manifestUrl }));
    });
    if (!releases.has(activeRelease) || !releases.has(targetRelease)) {
      throw new Error('active/target world release is not declared');
    }
    const fallbackReleaseIds = Array.isArray(config.fallbackReleaseIds)
      ? config.fallbackReleaseIds.map((id, index) => normalizeSafeId(id, `fallbackReleaseIds[${index}]`))
      : [];
    if (new Set(fallbackReleaseIds).size !== fallbackReleaseIds.length ||
        fallbackReleaseIds.some(id => !releases.has(id))) {
      throw new Error('world release fallback order is invalid');
    }
    const publishedOrder = [
      activeRelease,
      ...fallbackReleaseIds.filter(id => id !== activeRelease)
    ];
    const previewRelease = typeof config.previewRelease === 'string' &&
      WORLD_RELEASE_ID_PATTERN.test(config.previewRelease) &&
      config.previewRelease === targetRelease &&
      releases.has(config.previewRelease)
      ? config.previewRelease
      : null;
    const order = previewRelease
      ? [
          previewRelease,
          ...fallbackReleaseIds.filter(id => id !== previewRelease),
          ...publishedOrder.filter(id => id !== previewRelease && !fallbackReleaseIds.includes(id))
        ]
      : publishedOrder;
    const sheetTileIndexUrl = config.sheetTileIndexUrl
      ? requireHttpUrl(config.sheetTileIndexUrl, documentUrl, 'sheet tile index URL')
      : null;
    return Object.freeze({
      activeRelease,
      targetRelease,
      previewRelease,
      cacheKey: config.cacheKey,
      releases: Object.freeze([...releases.values()]),
      manifestCandidates: Object.freeze(order.map(id => releases.get(id))),
      sheetTileIndexUrl
    });
  }

  function assertWorldManifestCandidateIdentity(candidate, manifest) {
    const candidateId = candidate?.id;
    if (typeof candidateId !== 'string' || !WORLD_RELEASE_ID_PATTERN.test(candidateId)) {
      throw new Error('world manifest candidate release_id is invalid');
    }
    if (!manifest || typeof manifest !== 'object') {
      throw new Error(`${candidateId} tile manifest was not normalized`);
    }
    const isLegacyWorldV1 = candidateId === 'world-v1' && manifest.releaseId === null;
    if (!isLegacyWorldV1 && manifest.releaseId !== candidateId) {
      throw new Error(
        `${candidateId} tile manifest release_id must exactly match its release candidate`
      );
    }
  }

  /**
   * Load candidates in their declared order and accept only an identity-bound
   * world manifest. The sole compatibility exception is the retained legacy
   * world-v1 manifest, which predates release_id.
   */
  async function selectWorldTileManifestRelease(
    configuration,
    pixelMapping,
    documentUrl,
    loadCandidate,
    onInvalid = null
  ) {
    if (!Array.isArray(configuration?.manifestCandidates)) {
      throw new Error('world manifest candidates are required');
    }
    if (typeof loadCandidate !== 'function') {
      throw new Error('world manifest candidate loader is required');
    }
    if (onInvalid !== null && typeof onInvalid !== 'function') {
      throw new Error('world manifest rejection handler must be a function');
    }

    for (const candidate of configuration.manifestCandidates) {
      try {
        const fetched = await loadCandidate(candidate);
        if (!fetched) continue;
        const manifest = normalizeTileManifest(
          { manifest: fetched.json, url: candidate.manifestUrl },
          pixelMapping,
          documentUrl
        );
        assertWorldManifestCandidateIdentity(candidate, manifest);
        return Object.freeze({
          releaseId: candidate.id,
          manifestUrl: candidate.manifestUrl,
          manifestSha256: fetched.sha256,
          manifest
        });
      } catch (error) {
        if (onInvalid) onInvalid(candidate, error);
      }
    }
    return null;
  }

  function appendCacheKey(url, cacheKey, documentUrl) {
    const resolved = new URL(requireHttpUrl(url, documentUrl, 'resource URL'));
    if (cacheKey) resolved.searchParams.set('v', cacheKey);
    return resolved.href;
  }

  async function fetchResourceWithTimeout(url, options, parseResponse) {
    const fetchImpl = options.fetchImpl || globalThis.fetch;
    const AbortControllerImpl = options.AbortControllerImpl || globalThis.AbortController;
    if (typeof fetchImpl !== 'function' || typeof AbortControllerImpl !== 'function') {
      throw new Error('fetch and AbortController are required');
    }
    const timeoutMs = options.timeoutMs === undefined ? 8000 : Number(options.timeoutMs);
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('timeoutMs must be positive');
    const requestUrl = appendCacheKey(url, options.cacheKey, options.documentUrl);
    const controller = new AbortControllerImpl();
    const externalSignal = options.signal;
    let timedOut = false;
    let abortReject;
    const abortPromise = new Promise((_resolve, reject) => { abortReject = reject; });
    const abortWith = (name, code, message, reason) => {
      const error = new Error(message, reason === undefined ? undefined : { cause: reason });
      error.name = name;
      error.code = code;
      abortReject(error);
      controller.abort(reason);
    };
    const onExternalAbort = () => abortWith(
      'AbortError',
      'ABORT_ERR',
      `request aborted: ${requestUrl}`,
      externalSignal.reason
    );
    if (externalSignal?.aborted) onExternalAbort();
    else externalSignal?.addEventListener('abort', onExternalAbort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      abortWith('TimeoutError', 'ETIMEDOUT', `request timed out after ${timeoutMs}ms: ${requestUrl}`);
    }, timeoutMs);

    try {
      const response = await Promise.race([
        fetchImpl(requestUrl, { credentials: options.credentials || 'same-origin', signal: controller.signal }),
        abortPromise
      ]);
      if (!response?.ok) {
        const status = Number(response?.status) || 0;
        if (options.optional && status === 404) return null;
        throw new Error(`${requestUrl}: HTTP ${status}`);
      }
      return await Promise.race([parseResponse(response), abortPromise]);
    } catch (error) {
      if (options.optional && !externalSignal?.aborted && !timedOut) return null;
      throw error;
    } finally {
      clearTimeout(timer);
      externalSignal?.removeEventListener('abort', onExternalAbort);
    }
  }

  function fetchJsonWithTimeout(url, options = {}) {
    return fetchResourceWithTimeout(url, options, response => response.json());
  }

  function fetchBlobWithTimeout(url, options = {}) {
    return fetchResourceWithTimeout(url, options, response => response.blob());
  }

  function fetchArrayBufferWithTimeout(url, options = {}) {
    return fetchResourceWithTimeout(url, options, response => response.arrayBuffer());
  }

  /**
   * Return the deepest source-native zoom that may be shown in a viewport.
   *
   * The world raster is the hard fallback. A deeper limit is granted only by
   * an accepted raster whose bounds intersect the viewport. Callers may pass
   * eligibleRasterIds to restrict the grant to decoded/visible overlays. A Map
   * of ID -> decoded source zoom grants only the exact native level whose full
   * viewport tile set is ready; an empty iterable keeps the world clamp.
   */
  function nativeZoomLimitForViewport(
    rasters,
    viewportBounds,
    worldNativeZoom,
    eligibleRasterIds = null
  ) {
    const fallbackZoom = Number(worldNativeZoom);
    if (!Number.isFinite(fallbackZoom) || fallbackZoom < 0) {
      throw new Error('world native zoom must be a non-negative finite number');
    }

    const viewport = normalizeBounds(viewportBounds);
    if (!viewport || !Array.isArray(rasters)) return fallbackZoom;

    let eligibleIds = null;
    let eligibleNativeZooms = null;
    if (eligibleRasterIds !== null && eligibleRasterIds !== undefined) {
      if (typeof eligibleRasterIds === 'string' ||
          typeof eligibleRasterIds?.[Symbol.iterator] !== 'function') {
        throw new Error('eligible raster IDs must be an iterable of IDs');
      }
      if (eligibleRasterIds instanceof Map) {
        eligibleNativeZooms = new Map();
        eligibleRasterIds.forEach((zoom, id) => {
          if (typeof id !== 'string' || !Number.isInteger(zoom) || zoom < fallbackZoom) {
            throw new Error('eligible raster native zooms must map IDs to non-negative integers');
          }
          eligibleNativeZooms.set(id, zoom);
        });
        eligibleIds = new Set(eligibleNativeZooms.keys());
      } else {
        eligibleIds = new Set(eligibleRasterIds);
      }
    }

    return rasters.reduce((limit, raster) => {
      const status = readString(
        [raster],
        ['reviewStatus', 'review_status', 'qaStatus', 'qa_status', 'status']
      );
      if (status?.toLowerCase() !== 'accepted') return limit;

      const id = readString([raster], ['id', 'regionId', 'region_id', 'sheetId', 'sheet_id']);
      if (eligibleIds && (!id || !eligibleIds.has(id))) return limit;
      if (!boundsIntersect(raster?.bounds, viewport)) return limit;

      const nativeZoom = readNumber([raster], ['nativeZoom', 'native_zoom']);
      if (!Number.isFinite(nativeZoom) || nativeZoom < fallbackZoom) return limit;
      const grantedZoom = eligibleNativeZooms
        ? Math.min(nativeZoom, eligibleNativeZooms.get(id))
        : nativeZoom;
      return Math.max(limit, grantedZoom);
    }, fallbackZoom);
  }

  function normalizeMapSearchText(value) {
    return String(value ?? '')
      .normalize('NFKC')
      .toLocaleLowerCase('ja')
      .replace(/[\s\u3000]+/g, ' ')
      .trim();
  }

  function compactMapSearchText(value) {
    return normalizeMapSearchText(value).replace(/[\s\-_/・·.]+/g, '');
  }

  function searchAliases(item) {
    const arrays = [item?.aliases, item?.alternate_names, item?.alternateNames];
    const values = [item?.reading, item?.name_en, item?.nameEn];
    arrays.forEach(array => {
      if (Array.isArray(array)) values.push(...array);
    });
    return [...new Set(values
      .filter(value => typeof value === 'string' && value.trim())
      .map(value => value.trim()))];
  }

  /** Build display-ready search entries from the three searchable map catalogs. */
  function createMapSearchIndex(datasets) {
    const nodes = Array.isArray(datasets?.nodes) ? datasets.nodes : [];
    const regions = Array.isArray(datasets?.regions) ? datasets.regions : [];
    const pois = Array.isArray(datasets?.pois) ? datasets.pois : [];
    const continents = Array.isArray(datasets?.continents) ? datasets.continents : [];
    const continentNames = new Map(continents.map(item => [item?.id, item?.name]).filter(pair => pair[0]));
    const regionNames = new Map(regions.map(item => [item?.id, item?.name]).filter(pair => pair[0]));
    const nodeNames = new Map(nodes.map(item => [item?.id, item?.name]).filter(pair => pair[0]));
    const entries = [];

    function add(kind, kindLabel, item, contextParts) {
      const id = typeof item?.id === 'string' ? item.id.trim() : '';
      const label = typeof item?.name === 'string' ? item.name.trim() : '';
      if (!id || !label) return;
      const aliases = searchAliases(item);
      entries.push(Object.freeze({
        key: `${kind}:${id}`,
        kind,
        kindLabel,
        id,
        label,
        context: contextParts.filter(value => typeof value === 'string' && value.trim()).join(' · '),
        normalizedLabel: normalizeMapSearchText(label),
        compactLabel: compactMapSearchText(label),
        normalizedId: normalizeMapSearchText(id),
        aliases: Object.freeze(aliases),
        normalizedAliases: Object.freeze(aliases.map(normalizeMapSearchText)),
        compactAliases: Object.freeze(aliases.map(compactMapSearchText))
      }));
    }

    nodes.forEach(item => add('node', '拠点', item, [
      regionNames.get(item?.region_id) || item?.region_id,
      continentNames.get(item?.continent_id) || item?.continent_id
    ]));
    regions.forEach(item => add('region', '地域', item, [
      continentNames.get(item?.continent_id) || item?.continent_id
    ]));
    pois.forEach(item => add('poi', '施設', item, [
      item?.category,
      nodeNames.get(item?.nearest_node_id) || item?.nearest_node_id
    ]));
    return Object.freeze(entries);
  }

  function mapSearchMatchScore(entry, query, compactQuery) {
    const label = entry.normalizedLabel;
    const compactLabel = entry.compactLabel;
    if (label === query || compactLabel === compactQuery) return 0;
    if (label.startsWith(query) || compactLabel.startsWith(compactQuery)) return 10;
    if (label.split(' ').some(token => token.startsWith(query))) return 20;
    if (label.includes(query) || compactLabel.includes(compactQuery)) return 30;

    const aliases = Array.isArray(entry.normalizedAliases) ? entry.normalizedAliases : [];
    const compactAliases = Array.isArray(entry.compactAliases) ? entry.compactAliases : [];
    if (aliases.some(alias => alias === query) || compactAliases.some(alias => alias === compactQuery)) return 40;
    if (aliases.some(alias => alias.startsWith(query)) || compactAliases.some(alias => alias.startsWith(compactQuery))) return 50;
    if (aliases.some(alias => alias.includes(query)) || compactAliases.some(alias => alias.includes(compactQuery))) return 60;
    if (entry.normalizedId === query) return 70;
    if (entry.normalizedId.startsWith(query)) return 80;
    if (entry.normalizedId.includes(query)) return 90;
    return null;
  }

  function filterMapSearchEntries(entries, queryValue, limit = 8) {
    const query = normalizeMapSearchText(queryValue);
    const compactQuery = compactMapSearchText(queryValue);
    if (!query || !compactQuery || !Array.isArray(entries)) return [];
    const safeLimit = Number.isInteger(limit) && limit > 0 ? Math.min(limit, 50) : 8;
    const kindOrder = { node: 0, region: 1, poi: 2 };
    return entries
      .map((entry, sourceIndex) => ({
        entry,
        sourceIndex,
        score: mapSearchMatchScore(entry, query, compactQuery)
      }))
      .filter(candidate => candidate.score !== null)
      .sort((a, b) =>
        a.score - b.score ||
        a.entry.label.length - b.entry.label.length ||
        (kindOrder[a.entry.kind] ?? 99) - (kindOrder[b.entry.kind] ?? 99) ||
        a.entry.label.localeCompare(b.entry.label, 'ja') ||
        a.sourceIndex - b.sourceIndex
      )
      .slice(0, safeLimit)
      .map(candidate => candidate.entry);
  }

  /**
   * Pick the semantic search zoom. Region navigation deliberately returns to
   * regional context, while point targets retain an already-deeper zoom.
   */
  function mapSearchTargetZoom(kind, fitZoom, currentZoom, maxZoom) {
    const fit = Number(fitZoom);
    const current = Number(currentZoom);
    const maximum = Number(maxZoom);
    if (![fit, current, maximum].every(Number.isFinite)) {
      throw new Error('map search zoom values must be finite');
    }
    const offsets = { region: 2.25, node: 3, poi: 3.75 };
    const desired = fit + (offsets[kind] ?? 2.25);
    const zoom = kind === 'region' ? desired : Math.max(current, desired);
    return Math.min(maximum, zoom);
  }

  /** Merge available raster footprints for a region into plain Leaflet bounds. */
  function mapSearchRegionLeafletBounds(rasters, regionId, pixelMapping) {
    if (!Array.isArray(rasters) || typeof regionId !== 'string' || !regionId.trim()) return null;
    let merged = null;
    rasters.forEach(raster => {
      const candidateRegionId = raster?.regionId ?? raster?.region_id ?? raster?.source_feature_id ?? raster?.id;
      if (candidateRegionId !== regionId) return;
      const bounds = normalizeBounds(raster?.bounds);
      if (!bounds) return;
      merged = merged
        ? [
            Math.min(merged[0], bounds[0]),
            Math.min(merged[1], bounds[1]),
            Math.max(merged[2], bounds[2]),
            Math.max(merged[3], bounds[3])
          ]
        : [...bounds];
    });
    return merged ? eaWorldBoundsToLeafletBounds(merged, pixelMapping) : null;
  }

  return Object.freeze({
    EXPECTED_TILE_SIZE,
    EA_WORLD_EXTENT,
    TILE_MANIFEST_SCHEMA_VERSION,
    SHEET_TILE_INDEX_SCHEMA_VERSION,
    normalizeTileManifest,
    normalizeSheetTileIndex,
    assertSheetTileIndexWorldIdentity,
    normalizeRegionRasterIndex: normalizeSheetTileIndex,
    normalizeSheetTileManifest,
    normalizeWorldReleaseConfiguration,
    selectWorldTileManifestRelease,
    resolveUrlTemplate,
    appendCacheKey,
    fetchJsonWithTimeout,
    fetchBlobWithTimeout,
    fetchArrayBufferWithTimeout,
    scaleAtZoom,
    zoomAtScale,
    selectLod,
    eaWorldBoundsToPixelBounds,
    eaWorldBoundsToLeafletBounds,
    leafletBoundsToEaWorldBounds,
    boundsIntersect,
    boundsIntersectionArea,
    rankRegionRasters,
    sheetLineage,
    expandRasterSelectionWithParents,
    nearestReadyParentId,
    sheetTilesForViewport,
    sourceNativeZoomForMapZoom,
    allRequiredTilesReady,
    worldBaseTileLayerMaxZoom,
    worldReleasePreviewFromUrl,
    nativeZoomLimitForViewport,
    normalizeMapSearchText,
    createMapSearchIndex,
    filterMapSearchEntries,
    mapSearchTargetZoom,
    mapSearchRegionLeafletBounds
  });
});
