const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const core = require('../docs/assets/js/interactive-map-v3-core.js');

const pixelMapping = { image_width: 4096, image_height: 2730 };
const SHA_MASTER = 'a'.repeat(64);
const SHA_MANIFEST = 'b'.repeat(64);
const SHA_TILES = 'c'.repeat(64);
const SHA_EVIDENCE = 'd'.repeat(64);

function manifestLevels(width, height, minZoom, maxZoom) {
  const levels = [];
  for (let zoom = minZoom; zoom <= maxZoom; zoom += 1) {
    const factor = 2 ** (maxZoom - zoom);
    const levelWidth = Math.max(1, Math.ceil(width / factor));
    const levelHeight = Math.max(1, Math.ceil(height / factor));
    const columns = Math.ceil(levelWidth / 512);
    const rows = Math.ceil(levelHeight / 512);
    levels.push({
      zoom,
      width: levelWidth,
      height: levelHeight,
      columns,
      rows,
      tile_count: columns * rows
    });
  }
  return levels;
}

function generatedManifest({
  mapId = 'eternal-arcadia-world',
  width = 4096,
  height = 2730,
  minZoom = 0,
  maxZoom = 3,
  bounds = [0, 0, 10000, 10000],
  releaseId = 'world-v3',
  masterSha256 = SHA_MASTER,
  tileSetSha256 = SHA_TILES
} = {}) {
  const levels = manifestLevels(width, height, minZoom, maxZoom);
  return {
    schema_version: '1.0.0',
    type: 'sstory-xyz-raster',
    generated_by: 'sstory-map-production/generate_tiles.py@1',
    generated_at: '2026-07-20T00:00:00Z',
    release_id: releaseId,
    map_id: mapId,
    scheme: 'xyz',
    format: 'webp',
    tile_size: 512,
    minzoom: minZoom,
    maxzoom: maxZoom,
    native_zoom: maxZoom,
    tiles: ['{z}/{x}/{y}.webp'],
    coordinate_reference_system: 'EA-WORLD-1',
    coordinate_system: 'EA-WORLD-1',
    bounds,
    master: { path: `masters/${mapId}.png`, sha256: masterSha256, width, height, mode: 'RGBA' },
    encoding: { background: '#00000000' },
    levels,
    tile_count: levels.reduce((total, level) => total + level.tile_count, 0),
    tile_set_sha256: tileSetSha256
  };
}

function evidenceFor(id) {
  return {
    provenance: { path: `world/map-production/provenance/${id}.json`, sha256: SHA_EVIDENCE },
    automated_qa: { path: `world/map-production/qa/automated/${id}.json`, sha256: SHA_EVIDENCE },
    vision_reviews: [
      { path: `world/map-production/qa/vision/${id}.json`, sha256: SHA_EVIDENCE }
    ]
  };
}

function publishedSheet({
  id,
  sheetType,
  parentId,
  bounds,
  zoomRange,
  nativeZoom,
  sourceFeatureId = `${id}_feature`,
  secondaryParentIds = [],
  priority = 1,
  tileCount = 100
}) {
  return {
    id,
    sheet_id: id,
    name: id,
    sheet_type: sheetType,
    parent_id: parentId,
    secondary_parent_ids: secondaryParentIds,
    source_feature_id: sourceFeatureId,
    bounds,
    zoom_range: zoomRange,
    native_zoom: nativeZoom,
    review_status: 'accepted',
    status: 'tiled',
    manifest_url: `../../assets/images/maps/tiles/world-v3/sheets/${id}/metadata.json`,
    priority,
    master_sha256: SHA_MASTER,
    manifest_sha256: SHA_MANIFEST,
    tile_set_sha256: SHA_TILES,
    tile_count: tileCount,
    evidence: evidenceFor(id)
  };
}

function sheetIndexFixture() {
  const continents = Array.from({ length: 5 }, (_value, index) => publishedSheet({
    id: index === 0 ? 'sheet_continent_elysion' : `sheet_continent_${index + 1}`,
    sheetType: 'continent',
    parentId: 'sheet_world',
    bounds: [1000, 1000, 9000, 9000],
    zoomRange: [3, 4],
    nativeZoom: 4
  }));
  const regionIds = [
    'sheet_region_royal',
    'sheet_region_port',
    ...Array.from({ length: 12 }, (_value, index) => `sheet_region_${index + 3}`)
  ];
  const regions = regionIds.map((id, index) => publishedSheet({
    id,
    sheetType: 'region',
    parentId: index < 4 ? 'sheet_continent_elysion' : `sheet_continent_${(index % 4) + 2}`,
    bounds: id === 'sheet_region_royal' || id === 'sheet_region_port'
      ? [3000, 3000, 7000, 7000]
      : [2000, 2000, 8000, 8000],
    zoomRange: [4, 5],
    nativeZoom: 5,
    sourceFeatureId: id === 'sheet_region_royal' ? 'royal' : `${id}_feature`,
    priority: 2,
    tileCount: id === 'sheet_region_royal' ? 152 : 100
  }));
  const corridor = publishedSheet({
    id: 'sheet_corridor_royal_port',
    sheetType: 'corridor',
    parentId: 'sheet_region_royal',
    secondaryParentIds: ['sheet_region_port'],
    bounds: [3500, 3500, 6500, 6500],
    zoomRange: [5, 7],
    nativeZoom: 7,
    priority: 3
  });
  const settlements = [
    publishedSheet({
      id: 'sheet_settlement_astralis',
      sheetType: 'settlement',
      parentId: 'sheet_region_royal',
      bounds: [4000, 4000, 5000, 5000],
      zoomRange: [7, 8],
      nativeZoom: 8,
      sourceFeatureId: 'astralis',
      priority: 4
    }),
    publishedSheet({
      id: 'sheet_settlement_port',
      sheetType: 'settlement',
      parentId: 'sheet_region_port',
      bounds: [5000, 5000, 6000, 6000],
      zoomRange: [7, 8],
      nativeZoom: 8,
      priority: 4
    })
  ];
  return {
    $schema: 'https://sstory.example/schemas/sheet-tile-index.schema.json',
    schema_version: '2.0.0',
    type: 'sstory-sheet-tile-index',
    coordinate_reference_system: 'EA-WORLD-1',
    bounds_order: ['min_x', 'min_y', 'max_x', 'max_y'],
    generated_by: 'sstory-map-production/build_phase5_assets.py@1',
    generated_at: '2026-07-20T00:00:00Z',
    release_id: 'world-v3',
    bounded_sheet_count: 23,
    root_id: 'sheet_world',
    root: {
      id: 'sheet_world',
      sheet_id: 'sheet_world',
      name: 'World',
      sheet_type: 'world',
      parent_id: null,
      secondary_parent_ids: [],
      source_feature_id: null,
      bounds: [0, 0, 10000, 10000],
      zoom_range: [0, 3],
      native_zoom: 3,
      review_status: 'accepted',
      status: 'tiled',
      manifest_url: '../../assets/images/maps/tiles/world-v3/metadata.json',
      priority: 3000,
      master_sha256: SHA_MASTER,
      manifest_sha256: SHA_MANIFEST,
      tile_set_sha256: SHA_TILES,
      tile_count: 65,
      evidence: evidenceFor('sheet_world')
    },
    description: 'Complete immutable release fixture.',
    sheets: [...continents, ...regions, corridor, ...settlements]
  };
}

test('normalizes generate_tiles.py metadata and resolves its relative XYZ template', () => {
  const normalized = core.normalizeTileManifest({
    url: '../assets/images/maps/tiles/world/metadata.json',
    manifest: generatedManifest()
  }, pixelMapping, 'https://example.test/docs/pages/interactive-map-v3.html');

  assert.equal(normalized.schemaVersion, '1.0.0');
  assert.equal(normalized.tileSize, 512);
  assert.equal(normalized.imageWidth, 4096);
  assert.equal(normalized.imageHeight, 2730);
  assert.equal(normalized.minNativeZoom, 0);
  assert.equal(normalized.maxNativeZoom, 3);
  assert.equal(normalized.nativeZoom, 3);
  assert.equal(normalized.levels.length, 4);
  assert.equal(
    normalized.urlTemplate,
    'https://example.test/docs/assets/images/maps/tiles/world/{z}/{x}/{y}.webp'
  );
});

test('rejects permissive preview manifests and incomplete generated schemas fail-closed', () => {
  assert.throws(() => core.normalizeTileManifest({
    url: 'https://example.test/maps/metadata.json',
    manifest: {
      tile_size: 512,
      image_width: 4096,
      image_height: 2730,
      min_zoom: 0,
      max_zoom: 3,
      url_template: 'tiles/{z}/{x}/{y}.webp'
    }
  }, pixelMapping, 'https://example.test/viewer.html'), /schema_version/);
});

test('rejects a metadata master that cannot align with vector pixel mapping', () => {
  assert.throws(() => core.normalizeTileManifest({
    url: 'https://example.test/metadata.json',
    manifest: generatedManifest({ width: 2048, height: 1365, maxZoom: 2 })
  }, pixelMapping, 'https://example.test/viewer.html'), /画像寸法が一致しません/);
});

test('custom CRS scale is one at native zoom and round-trips zoom values', () => {
  assert.equal(core.scaleAtZoom(3, 3), 1);
  assert.equal(core.scaleAtZoom(2, 3), 0.5);
  assert.equal(core.scaleAtZoom(4, 3), 2);

  for (const zoom of [-1, 0, 1.25, 3, 5]) {
    assert.equal(core.zoomAtScale(core.scaleAtZoom(zoom, 3), 3), zoom);
  }
});

test('LOD selection follows offsets from fit zoom instead of absolute zoom', () => {
  const definitions = [
    { id: 'world', minOffset: -Infinity },
    { id: 'continent', minOffset: 0.75 },
    { id: 'region', minOffset: 2.25 },
    { id: 'detail', minOffset: 3.75 }
  ];

  assert.equal(core.selectLod(definitions, 1.5, 1.5).id, 'world');
  assert.equal(core.selectLod(definitions, 2.25, 1.5).id, 'continent');
  assert.equal(core.selectLod(definitions, 3.75, 1.5).id, 'region');
  assert.equal(core.selectLod(definitions, 5.25, 1.5).id, 'detail');
  assert.equal(core.selectLod(definitions, -1.25, -2).id, 'continent');
});

test('converts EA-WORLD-1 bounds to Leaflet pixels and back without changing orientation', () => {
  const eaBounds = [2500, 2000, 7500, 8000];
  assert.deepEqual(core.eaWorldBoundsToPixelBounds(eaBounds, pixelMapping), [1024, 546, 3072, 2184]);
  assert.deepEqual(core.eaWorldBoundsToLeafletBounds(eaBounds, pixelMapping), [
    [-2184, 1024],
    [-546, 3072]
  ]);

  const roundTrip = core.leafletBoundsToEaWorldBounds({
    west: 1024,
    south: -2184,
    east: 3072,
    north: -546
  }, pixelMapping);
  assert.deepEqual(roundTrip, eaBounds);
});

test('normalizes accepted per-sheet manifests, rejects full-image URLs and resolves from index URL', () => {
  const normalized = core.normalizeSheetTileIndex({
    url: '../data/map/sheet-tiles-v3.json',
    index: sheetIndexFixture()
  }, pixelMapping, 'https://example.test/docs/pages/interactive-map-v3.html', 3);

  assert.equal(normalized.coordinateReferenceSystem, 'EA-WORLD-1');
  assert.equal(normalized.releaseId, 'world-v3');
  assert.equal(normalized.boundedSheetCount, 23);
  assert.equal(normalized.rootId, 'sheet_world');
  assert.equal(normalized.rasters.length, 22);
  assert.deepEqual([
    normalized.rasters.find(entry => entry.id === 'sheet_continent_elysion').depth,
    normalized.rasters.find(entry => entry.id === 'sheet_region_royal').depth,
    normalized.rasters.find(entry => entry.id === 'sheet_settlement_astralis').depth
  ], [1, 2, 3]);
  assert.equal(
    normalized.rasters.find(entry => entry.id === 'sheet_region_royal').manifestUrl,
    'https://example.test/docs/assets/images/maps/tiles/world-v3/sheets/sheet_region_royal/metadata.json'
  );
  assert.equal('url' in normalized.rasters[0], false);
});

test('rejects a malformed accepted sheet instead of partially publishing the index', () => {
  const index = sheetIndexFixture();
  index.sheets[1].manifest_url = '../images/continent.webp';
  assert.throws(() => core.normalizeSheetTileIndex({
    url: 'https://example.test/map/sheet-index.json',
    index
  }, pixelMapping, 'https://example.test/viewer.html', 3), /must point|JSON を指す/);

  const missingParent = sheetIndexFixture();
  missingParent.sheets[1].parent_id = 'sheet_missing';
  assert.throws(() => core.normalizeSheetTileIndex({
    url: 'https://example.test/map/sheet-index.json',
    index: missingParent
  }, pixelMapping, 'https://example.test/viewer.html', 3), /accepted parent/);

  const partial = sheetIndexFixture();
  partial.sheets.pop();
  assert.throws(() => core.normalizeSheetTileIndex({
    url: 'https://example.test/docs/data/map/sheet-index.json',
    index: partial
  }, pixelMapping, 'https://example.test/viewer.html', 3), /完全な22件/);

  const rejected = sheetIndexFixture();
  rejected.sheets[0].review_status = 'rejected';
  assert.throws(() => core.normalizeSheetTileIndex({
    url: 'https://example.test/docs/data/map/sheet-index.json',
    index: rejected
  }, pixelMapping, 'https://example.test/viewer.html', 3), /accepted/);
});

test('schema2 index rejects missing release metadata, wrong counts, root identity and evidence hashes', () => {
  const mutations = [
    [index => { delete index.release_id; }, /release_id/],
    [index => { index.generated_by = 'another-generator'; }, /generated_by/],
    [index => { index.bounds_order = ['min_y', 'min_x', 'max_y', 'max_x']; }, /bounds_order/],
    [index => { index.bounded_sheet_count = 22; }, /bounded_sheet_count/],
    [index => { index.root.sheet_id = 'sheet_other'; }, /id と sheet_id|root/],
    [index => { index.sheets[0].sheet_type = 'region'; }, /型別件数|sheet_type/],
    [index => { index.sheets[0].master_sha256 = 'ABC'; }, /SHA-256/],
    [index => { index.sheets[0].tile_count = 0; }, /tile_count/],
    [index => { index.sheets[0].evidence.vision_reviews = []; }, /vision_reviews/],
    [index => { index.sheets[0].id = '3_invalid'; index.sheets[0].sheet_id = '3_invalid'; }, /安全な小文字ID/]
  ];
  mutations.forEach(([mutate, pattern]) => {
    const index = sheetIndexFixture();
    mutate(index);
    assert.throws(() => core.normalizeSheetTileIndex({
      url: 'https://example.test/docs/data/map/sheet-index.json',
      index
    }, pixelMapping, 'https://example.test/viewer.html', 3), pattern);
  });
});

test('attaches a schema2 index only to its exact loaded immutable world release', () => {
  const index = core.normalizeSheetTileIndex({
    url: 'https://example.test/docs/data/map/sheet-tiles-v3.json',
    index: sheetIndexFixture()
  }, pixelMapping, 'https://example.test/docs/pages/viewer.html', 3);
  const manifestUrl = 'https://example.test/docs/assets/images/maps/tiles/world-v3/metadata.json';
  const manifest = core.normalizeTileManifest({
    url: manifestUrl,
    manifest: generatedManifest({ mapId: 'sheet_world', releaseId: 'world-v3' })
  }, pixelMapping, 'https://example.test/docs/pages/viewer.html');
  const worldRelease = {
    releaseId: 'world-v3',
    manifestUrl,
    manifestSha256: SHA_MANIFEST,
    manifest
  };
  assert.equal(core.assertSheetTileIndexWorldIdentity(index, worldRelease), true);
  assert.throws(() => core.assertSheetTileIndexWorldIdentity(index, {
    ...worldRelease,
    releaseId: 'world-v2'
  }), /release_id/);
  assert.throws(() => core.assertSheetTileIndexWorldIdentity(index, {
    ...worldRelease,
    manifestUrl: 'https://example.test/docs/assets/images/maps/tiles/world-v3-copy/metadata.json'
  }), /root/);
});

test('validates a sheet tile manifest against index identity, bounds, density and transparency', () => {
  const index = core.normalizeSheetTileIndex({
    url: 'https://example.test/map/sheet-index.json',
    index: sheetIndexFixture()
  }, pixelMapping, 'https://example.test/viewer.html', 3);
  const sheet = index.rasters.find(entry => entry.id === 'sheet_region_royal');
  const manifest = generatedManifest({
    mapId: sheet.id,
    width: 6554,
    height: 4368,
    minZoom: 4,
    maxZoom: 5,
    bounds: [...sheet.bounds]
  });
  const normalized = core.normalizeSheetTileManifest({
    url: sheet.manifestUrl,
    manifest
  }, sheet, pixelMapping, 'https://example.test/viewer.html', 3);

  assert.equal(normalized.sheetId, sheet.id);
  assert.equal(normalized.tileSize, 512);
  assert.equal(normalized.levels.length, 2);
  assert.equal(
    normalized.urlTemplate,
    'https://example.test/assets/images/maps/tiles/world-v3/sheets/sheet_region_royal/{z}/{x}/{y}.webp'
  );

  manifest.encoding.background = '#000000';
  assert.throws(() => core.normalizeSheetTileManifest({
    url: sheet.manifestUrl,
    manifest
  }, sheet, pixelMapping, 'https://example.test/viewer.html', 3), /透明/);
});

test('expands a selected child to parent lineage and resolves nearest ready fallback', () => {
  const index = core.normalizeSheetTileIndex({
    url: 'https://example.test/map/sheet-index.json',
    index: sheetIndexFixture()
  }, pixelMapping, 'https://example.test/viewer.html', 3);
  assert.deepEqual(
    core.sheetLineage(index.rasters, 'sheet_settlement_astralis').map(entry => entry.id),
    ['sheet_continent_elysion', 'sheet_region_royal', 'sheet_settlement_astralis']
  );
  assert.deepEqual(
    core.expandRasterSelectionWithParents(index.rasters, ['sheet_settlement_astralis'])
      .map(entry => entry.id),
    ['sheet_continent_elysion', 'sheet_region_royal', 'sheet_settlement_astralis']
  );
  assert.equal(core.nearestReadyParentId(
    index.rasters,
    'sheet_settlement_astralis',
    ['sheet_world', 'sheet_continent_elysion', 'sheet_region_royal']
  ), 'sheet_region_royal');
  assert.equal(core.nearestReadyParentId(
    index.rasters,
    'sheet_settlement_astralis',
    ['sheet_world']
  ), 'sheet_world');
});

test('enumerates only intersecting 512px sheet tiles at the clamped source-native zoom', () => {
  const sheet = {
    id: 'sheet_region_royal',
    bounds: [3000, 3000, 7000, 7000]
  };
  const manifest = {
    sheetId: sheet.id,
    minNativeZoom: 4,
    maxNativeZoom: 5,
    levels: [
      { zoom: 4, width: 1024, height: 1024, columns: 2, rows: 2 },
      { zoom: 5, width: 2048, height: 2048, columns: 4, rows: 4 }
    ],
    urlTemplate: 'https://example.test/tiles/{z}/{x}/{y}.webp'
  };
  assert.equal(core.sourceNativeZoomForMapZoom(4, 4, 5), 4);
  assert.equal(core.sourceNativeZoomForMapZoom(4 + 1e-9, 4, 5), 4);
  assert.equal(core.sourceNativeZoomForMapZoom(4.01, 4, 5), 5);
  assert.equal(core.sourceNativeZoomForMapZoom(4.75, 4, 5), 5);
  assert.equal(core.sourceNativeZoomForMapZoom(99, 4, 5), 5);
  const tiles = core.sheetTilesForViewport(sheet, manifest, [3000, 3000, 4999, 4999], 4.75);
  assert.deepEqual(tiles.map(tile => [tile.zoom, tile.x, tile.y]), [
    [5, 0, 0], [5, 0, 1], [5, 1, 0], [5, 1, 1]
  ]);
  assert.equal(tiles[0].url, 'https://example.test/tiles/5/0/0.webp');
  assert.deepEqual(tiles[0].bounds, [3000, 3000, 4000, 4000]);
  assert.deepEqual(core.sheetTilesForViewport(
    sheet,
    manifest,
    [6500, 6500, 7500, 7500],
    99
  ).map(tile => [tile.zoom, tile.x, tile.y]), [[5, 3, 3]]);
  assert.deepEqual(core.sheetTilesForViewport(sheet, manifest, [0, 0, 1000, 1000], 5), []);
});

test('requires every current viewport tile before releasing a sheet and keeps the world parent to Z8', () => {
  const required = new Set(['a', 'b', 'c']);
  const states = new Map([
    ['a', { status: 'ready' }],
    ['b', { status: 'loading' }],
    ['c', { status: 'ready' }]
  ]);
  assert.equal(core.allRequiredTilesReady(required, states), false);
  states.get('b').status = 'ready';
  assert.equal(core.allRequiredTilesReady(required, states), true);
  assert.equal(core.allRequiredTilesReady(new Set(), states), false);

  const leafletLikeOptions = {
    maxNativeZoom: 3,
    maxZoom: core.worldBaseTileLayerMaxZoom(3, 8)
  };
  const leafletLikeSourceZoom = displayZoom => displayZoom > leafletLikeOptions.maxZoom
    ? null
    : Math.min(Math.round(displayZoom), leafletLikeOptions.maxNativeZoom);
  assert.equal(leafletLikeOptions.maxZoom, 8);
  assert.equal(leafletLikeSourceZoom(8), 3);
  assert.equal(leafletLikeSourceZoom(9), null);
});

test('tests strict bounds intersection and ranks visible region rasters deterministically', () => {
  assert.equal(core.boundsIntersect([0, 0, 100, 100], [100, 0, 200, 100]), false);
  assert.equal(core.boundsIntersect([0, 0, 101, 100], [100, 0, 200, 100]), true);
  assert.equal(core.boundsIntersectionArea([0, 0, 100, 100], [50, 25, 150, 75]), 2500);

  const rasters = [
    { id: 'far', bounds: [0, 0, 4000, 4000], priority: 0 },
    { id: 'near', bounds: [3500, 3500, 6500, 6500], priority: 0 },
    { id: 'priority', bounds: [8000, 8000, 9000, 9000], priority: 5 },
    { id: 'outside', bounds: [0, 8000, 1000, 9000], priority: 99 }
  ];
  const ranked = core.rankRegionRasters(rasters, [3000, 3000, 8500, 8500]);
  assert.deepEqual(ranked.map(raster => raster.id), ['priority', 'near', 'far']);
});

test('clamps native zoom to the world until an accepted intersecting raster is eligible', () => {
  const rasters = [
    {
      id: 'region-ready', reviewStatus: 'accepted', nativeZoom: 5,
      bounds: [3000, 3000, 7000, 7000]
    },
    {
      id: 'settlement-ready', review_status: 'accepted', native_zoom: 8,
      bounds: [4500, 4500, 5500, 5500]
    },
    {
      id: 'rejected-detail', reviewStatus: 'rejected', nativeZoom: 9,
      bounds: [4500, 4500, 5500, 5500]
    },
    {
      id: 'outside', reviewStatus: 'accepted', nativeZoom: 7,
      bounds: [8000, 8000, 9000, 9000]
    }
  ];
  const viewport = [4000, 4000, 6000, 6000];

  assert.equal(core.nativeZoomLimitForViewport(rasters, viewport, 3), 8);
  assert.equal(core.nativeZoomLimitForViewport(rasters, viewport, 3, []), 3);
  assert.equal(core.nativeZoomLimitForViewport(rasters, viewport, 3, ['region-ready']), 5);
  assert.equal(core.nativeZoomLimitForViewport(rasters, viewport, 3, ['settlement-ready']), 8);
  assert.equal(core.nativeZoomLimitForViewport(
    rasters,
    viewport,
    3,
    new Map([['region-ready', 4], ['settlement-ready', 7]])
  ), 7);
  assert.equal(core.nativeZoomLimitForViewport(rasters, [7000, 7000, 8000, 8000], 3), 3);
  assert.equal(core.nativeZoomLimitForViewport(rasters, [0, 0, 2000, 2000], 3), 3);
});

test('rejects invalid world zoom and eligible-ID inputs for the native zoom clamp', () => {
  assert.throws(
    () => core.nativeZoomLimitForViewport([], [0, 0, 1000, 1000], Number.NaN),
    /world native zoom/
  );
  assert.throws(
    () => core.nativeZoomLimitForViewport([], [0, 0, 1000, 1000], 3, 'region'),
    /eligible raster IDs/
  );
  assert.throws(
    () => core.nativeZoomLimitForViewport([], [0, 0, 1000, 1000], 3, new Map([['region', 3.5]])),
    /native zooms/
  );
});

test('normalizes versioned world release order and resolves rollback URLs', () => {
  const configuration = core.normalizeWorldReleaseConfiguration({
    activeRelease: 'world-v3',
    targetRelease: 'world-v3',
    cacheKey: 'world-v3-20260720a',
    releases: [
      { id: 'world-v3', manifestUrl: '../tiles/world-v3/metadata.json' },
      { id: 'world-v2', manifestUrl: '../tiles/world-v2/metadata.json' },
      { id: 'world-v1', manifestUrl: '../tiles/world-v1/metadata.json' }
    ],
    fallbackReleaseIds: ['world-v2', 'world-v1'],
    sheetTileIndexUrl: './sheet-tiles-v3.json'
  }, 'https://example.test/docs/map/viewer.html');

  assert.equal(configuration.activeRelease, 'world-v3');
  assert.deepEqual(configuration.manifestCandidates.map(entry => entry.id), [
    'world-v3', 'world-v2', 'world-v1'
  ]);
  assert.equal(
    configuration.manifestCandidates[2].manifestUrl,
    'https://example.test/docs/tiles/world-v1/metadata.json'
  );
  assert.equal(
    configuration.sheetTileIndexUrl,
    'https://example.test/docs/map/sheet-tiles-v3.json'
  );
});

test('accepts only one exact target world release preview query', () => {
  const target = 'world-v3';
  assert.equal(core.worldReleasePreviewFromUrl(
    'https://example.test/docs/map.html?release-preview=world-v3',
    target
  ), target);
  assert.equal(core.worldReleasePreviewFromUrl(
    'https://example.test/docs/map.html?release-preview=world-v2',
    target
  ), null);
  assert.equal(core.worldReleasePreviewFromUrl(
    'https://example.test/docs/map.html?release-preview=world-v3&release-preview=world-v3',
    target
  ), null);
  assert.equal(core.worldReleasePreviewFromUrl(
    'https://example.test/docs/map.html?release-preview=%20world-v3',
    target
  ), null);
  assert.equal(core.worldReleasePreviewFromUrl(
    'https://example.test/docs/map.html?release-preview=world-v3',
    'release-candidate'
  ), null);
  assert.equal(core.worldReleasePreviewFromUrl('not a URL', target), null);
});

test('puts an accepted preview target first without changing rollback order', () => {
  const configuration = core.normalizeWorldReleaseConfiguration({
    activeRelease: 'world-v1',
    targetRelease: 'world-v3',
    previewRelease: 'world-v3',
    cacheKey: 'world-v3-preview',
    releases: [
      { id: 'world-v3', manifestUrl: '../tiles/world-v3/metadata.json' },
      { id: 'world-v2', manifestUrl: '../tiles/world-v2/metadata.json' },
      { id: 'world-v1', manifestUrl: '../tiles/world-v1/metadata.json' }
    ],
    fallbackReleaseIds: ['world-v2', 'world-v1']
  }, 'https://example.test/docs/map/viewer.html');

  assert.equal(configuration.previewRelease, 'world-v3');
  assert.deepEqual(configuration.manifestCandidates.map(entry => entry.id), [
    'world-v3', 'world-v2', 'world-v1'
  ]);
});

test('ignores invalid preview overrides and preserves the published order', () => {
  const base = {
    activeRelease: 'world-v1',
    targetRelease: 'world-v3',
    cacheKey: 'world-v3-published',
    releases: [
      { id: 'world-v3', manifestUrl: '../tiles/world-v3/metadata.json' },
      { id: 'world-v2', manifestUrl: '../tiles/world-v2/metadata.json' },
      { id: 'world-v1', manifestUrl: '../tiles/world-v1/metadata.json' }
    ],
    fallbackReleaseIds: ['world-v2', 'world-v1']
  };

  for (const previewRelease of [undefined, 'world-v2', 'WORLD-V3', 'world-v03']) {
    const configuration = core.normalizeWorldReleaseConfiguration(
      { ...base, previewRelease },
      'https://example.test/docs/map/viewer.html'
    );
    assert.equal(configuration.previewRelease, null);
    assert.deepEqual(configuration.manifestCandidates.map(entry => entry.id), [
      'world-v1', 'world-v2'
    ]);
  }
});

test('world manifest selection rejects mismatched or missing release identity and continues rollback', async () => {
  const configuration = core.normalizeWorldReleaseConfiguration({
    activeRelease: 'world-v1',
    targetRelease: 'world-v3',
    previewRelease: 'world-v3',
    cacheKey: 'world-v3-identity-fallback',
    releases: [
      { id: 'world-v3', manifestUrl: '../tiles/world-v3/metadata.json' },
      { id: 'world-v2', manifestUrl: '../tiles/world-v2/metadata.json' },
      { id: 'world-v1', manifestUrl: '../tiles/world-v1/metadata.json' }
    ],
    fallbackReleaseIds: ['world-v2', 'world-v1']
  }, 'https://example.test/docs/map/viewer.html');

  const withoutReleaseId = manifest => {
    const result = structuredClone(manifest);
    delete result.release_id;
    return result;
  };
  const attempts = [];
  const rejected = [];
  const manifests = new Map([
    ['world-v3', generatedManifest({ releaseId: 'world-v2' })],
    ['world-v2', withoutReleaseId(generatedManifest({ releaseId: 'world-v2' }))],
    ['world-v1', withoutReleaseId(generatedManifest({ releaseId: 'world-v1' }))]
  ]);

  const selected = await core.selectWorldTileManifestRelease(
    configuration,
    pixelMapping,
    'https://example.test/docs/map/viewer.html',
    async candidate => {
      attempts.push(candidate.id);
      return { json: manifests.get(candidate.id), sha256: SHA_MANIFEST };
    },
    (candidate, error) => rejected.push([candidate.id, error.message])
  );

  assert.equal(selected.releaseId, 'world-v1');
  assert.equal(selected.manifest.releaseId, null);
  assert.deepEqual(attempts, ['world-v3', 'world-v2', 'world-v1']);
  assert.deepEqual(rejected.map(([id]) => id), ['world-v3', 'world-v2']);
  rejected.forEach(([_id, message]) => assert.match(message, /release_id must exactly match/));
});

test('world manifest selection accepts exact v2 identity after rejecting missing v3 identity', async () => {
  const configuration = core.normalizeWorldReleaseConfiguration({
    activeRelease: 'world-v1',
    targetRelease: 'world-v3',
    previewRelease: 'world-v3',
    cacheKey: 'world-v3-exact-identity',
    releases: [
      { id: 'world-v3', manifestUrl: '../tiles/world-v3/metadata.json' },
      { id: 'world-v2', manifestUrl: '../tiles/world-v2/metadata.json' },
      { id: 'world-v1', manifestUrl: '../tiles/world-v1/metadata.json' }
    ],
    fallbackReleaseIds: ['world-v2', 'world-v1']
  }, 'https://example.test/docs/map/viewer.html');
  const attempts = [];

  const selected = await core.selectWorldTileManifestRelease(
    configuration,
    pixelMapping,
    'https://example.test/docs/map/viewer.html',
    async candidate => {
      attempts.push(candidate.id);
      const manifest = generatedManifest({ releaseId: candidate.id });
      if (candidate.id === 'world-v3') delete manifest.release_id;
      return {
        json: manifest,
        sha256: SHA_MANIFEST
      };
    }
  );

  assert.equal(selected.releaseId, 'world-v2');
  assert.equal(selected.manifest.releaseId, 'world-v2');
  assert.deepEqual(attempts, ['world-v3', 'world-v2']);
});

test('fetch helper resolves URLs, adds the cache pointer and returns JSON', async () => {
  let request;
  const value = await core.fetchJsonWithTimeout('../data/test.json?lang=ja', {
    documentUrl: 'https://example.test/docs/pages/map.html',
    cacheKey: 'world-v3-a',
    timeoutMs: 100,
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, status: 200, json: async () => ({ ready: true }) };
    }
  });
  assert.deepEqual(value, { ready: true });
  assert.equal(request.url, 'https://example.test/docs/data/test.json?lang=ja&v=world-v3-a');
  assert.equal(request.options.credentials, 'same-origin');
  assert.equal(request.options.signal.aborted, false);
});

test('fetch helper times out and aborts an in-flight request', async () => {
  let requestSignal;
  const fetchImpl = (_url, { signal }) => {
    requestSignal = signal;
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('transport aborted')), { once: true });
    });
  };
  await assert.rejects(core.fetchJsonWithTimeout('https://example.test/slow.json', {
    timeoutMs: 10,
    fetchImpl
  }), error => error.name === 'TimeoutError' && error.code === 'ETIMEDOUT');
  assert.equal(requestSignal.aborted, true);
});

test('fetch helper propagates external cancellation to AbortController', async () => {
  const external = new AbortController();
  let requestSignal;
  const promise = core.fetchJsonWithTimeout('https://example.test/stale.json', {
    timeoutMs: 1000,
    signal: external.signal,
    fetchImpl: (_url, { signal }) => {
      requestSignal = signal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('transport aborted')), { once: true });
      });
    }
  });
  external.abort('viewport changed');
  await assert.rejects(promise, error => error.name === 'AbortError' && error.code === 'ABORT_ERR');
  assert.equal(requestSignal.aborted, true);
});

test('builds searchable node, region and POI entries with human-readable context', () => {
  const index = core.createMapSearchIndex({
    continents: [{ id: 'elysion', name: 'エリュシオン' }],
    regions: [{ id: 'royal_capital_region', name: '王都地方', continent_id: 'elysion' }],
    nodes: [{
      id: 'astralis', name: 'アストラリス', region_id: 'royal_capital_region', continent_id: 'elysion',
      aliases: ['王都']
    }],
    pois: [{
      id: 'astralis_market', name: 'アストラリス大市場', category: 'market', nearest_node_id: 'astralis'
    }]
  });

  assert.deepEqual(index.map(entry => [entry.key, entry.kindLabel, entry.context]), [
    ['node:astralis', '拠点', '王都地方 · エリュシオン'],
    ['region:royal_capital_region', '地域', 'エリュシオン'],
    ['poi:astralis_market', '施設', 'market · アストラリス']
  ]);
});

test('map search normalizes Japanese width and whitespace and returns no results for blank input', () => {
  assert.equal(core.normalizeMapSearchText('  ｱｽﾄﾗﾘｽ　中央  '), 'アストラリス 中央');
  const index = core.createMapSearchIndex({
    nodes: [{ id: 'astralis', name: 'アストラリス' }]
  });
  assert.deepEqual(core.filterMapSearchEntries(index, ''), []);
  assert.deepEqual(core.filterMapSearchEntries(index, '　'), []);
  assert.equal(core.filterMapSearchEntries(index, 'ｱｽﾄﾗ')[0].id, 'astralis');
});

test('map search ranks exact display names before prefixes, substrings, aliases and IDs', () => {
  const index = core.createMapSearchIndex({
    nodes: [
      { id: 'capital', name: '王都', aliases: ['アストラリス'] },
      { id: 'astralis', name: 'アストラリス' },
      { id: 'astralis_gate', name: 'アストラリス門' },
      { id: 'old_astralis', name: '旧アストラリス街道' }
    ],
    regions: [{ id: 'astralis_region', name: 'アストラリス地方' }],
    pois: [{ id: 'poi_astralis', name: '中央市場' }]
  });

  assert.deepEqual(core.filterMapSearchEntries(index, 'アストラリス').map(entry => entry.id), [
    'astralis',
    'astralis_gate',
    'astralis_region',
    'old_astralis',
    'capital'
  ]);
  assert.equal(core.filterMapSearchEntries(index, 'poi_astralis')[0].id, 'poi_astralis');
  assert.equal(core.filterMapSearchEntries(index, 'ア', 2).length, 2);
});

test('map search returns regions to semantic context while retaining deep point zoom', () => {
  assert.equal(core.mapSearchTargetZoom('region', 1.5, 8, 9), 3.75);
  assert.equal(core.mapSearchTargetZoom('node', 1.5, 8, 9), 8);
  assert.equal(core.mapSearchTargetZoom('poi', 1.5, 2, 9), 5.25);
  assert.equal(core.mapSearchTargetZoom('poi', 1.5, 8, 6), 6);
  assert.throws(() => core.mapSearchTargetZoom('region', 1.5, Number.NaN, 9));
});

test('map search merges available region raster footprints into Leaflet bounds', () => {
  const bounds = core.mapSearchRegionLeafletBounds([
    { regionId: 'royal', bounds: [1000, 2000, 3000, 4000] },
    { region_id: 'royal', bounds: [2500, 1500, 5000, 4500] },
    { regionId: 'other', bounds: [0, 0, 1000, 1000] },
    { regionId: 'royal', bounds: [1, 2, 1, 4] }
  ], 'royal', { image_width: 4000, image_height: 2000 });

  assert.deepEqual(bounds, [[-900, 400], [-300, 2000]]);
  assert.equal(core.mapSearchRegionLeafletBounds([], 'royal', {
    image_width: 4000,
    image_height: 2000
  }), null);
});

test('mobile search exposes an unobstructed close control wired to focus restoration', () => {
  const repoRoot = path.resolve(__dirname, '..');
  const html = fs.readFileSync(
    path.join(repoRoot, 'docs/pages/interactive-map-v3.html'),
    'utf8'
  );
  const script = fs.readFileSync(
    path.join(repoRoot, 'docs/assets/js/interactive-map-v3.js'),
    'utf8'
  );
  const styles = fs.readFileSync(
    path.join(repoRoot, 'docs/assets/css/interactive-map-v3.css'),
    'utf8'
  );

  assert.match(html, /id="mapSearchClose"/);
  assert.match(html, /aria-label="場所の検索を閉じる"/);
  assert.match(script, /searchClose:\s*document\.getElementById\('mapSearchClose'\)/);
  assert.match(script, /elements\.searchClose\.addEventListener\('click',[\s\S]*setMobileOpen\(false, true\)/);
  assert.match(styles, /@media \(max-width: 760px\)[\s\S]*\.map-search__close\s*\{\s*display:\s*grid;/);
});

test('runtime fixture initializes world before optional sheet index and uses cancellable tiles', () => {
  const repoRoot = path.resolve(__dirname, '..');
  const html = fs.readFileSync(path.join(repoRoot, 'docs/pages/interactive-map-v3.html'), 'utf8');
  const script = fs.readFileSync(path.join(repoRoot, 'docs/assets/js/interactive-map-v3.js'), 'utf8');

  assert.match(html, /name="ea-map-world-release" content="world-v1"/);
  assert.match(html, /name="ea-map-world-target-release" content="world-v3"/);
  assert.match(html, /name="ea-map-world-fallback-releases" content="world-v2,world-v1"/);
  assert.match(html, /name="ea-map-cache-key" content="world-v3-contract-20260720"/);
  assert.match(html, /name="ea-map-sheet-tile-index"/);
  assert.match(script, /Core\.worldReleasePreviewFromUrl\(window\.location\.href, HTML_TARGET_WORLD_RELEASE\)/);
  assert.match(script, /previewRelease: PREVIEW_WORLD_RELEASE/);

  const optionalStart = script.indexOf('const sheetTileIndexPromise = findSheetTileIndex');
  const worldCreated = script.indexOf('createMap(imageWidth, imageHeight, tileManifest, emptySheetTileIndex)');
  const optionalAttached = script.indexOf('void sheetTileIndexPromise.then');
  assert.ok(optionalStart >= 0 && optionalStart < worldCreated && worldCreated < optionalAttached);
  assert.match(script, /Core\.fetchBlobWithTimeout\(tile\.url/);
  assert.match(script, /Core\.fetchArrayBufferWithTimeout\(url/);
  assert.match(script, /window\.crypto\.subtle\.digest\('SHA-256', buffer\)/);
  assert.match(script, /tileState\.controller\?\.abort/);
  assert.match(script, /Core\.allRequiredTilesReady\(state\.requiredTileKeys, state\.tiles\)/);
  assert.match(script, /sourceRequestZoom = displayZoom >= map\.getMaxZoom\(\) - 1e-7/);
  assert.match(script, /new Map\(\[\.\.\.states\.values\(\)\]/);
  assert.match(script, /mimeType !== 'image\/webp'/);
  assert.match(script, /bitmap\.width !== Core\.EXPECTED_TILE_SIZE/);
  assert.match(script, /Core\.worldBaseTileLayerMaxZoom\(tileManifest\.maxNativeZoom, 8\)/);
  assert.match(script, /Core\.assertSheetTileIndexWorldIdentity\(regionRasterIndex, worldRelease\)/);
  assert.match(script, /Core\.nearestReadyParentId/);
  assert.match(script, /viewportReady:\s*stateViewportReady\(state\)/);
  assert.match(script, /failedIds:\s*\[\.\.\.failedIds\]\.sort\(\)/);
  assert.match(script, /sheets:\s*sheetStates/);
  assert.doesNotMatch(script, /decodeRegionImage|new window\.Image\(\)|entry\.url/);
});
