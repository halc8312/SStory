async page => {
  const options = __PHASE6_OPTIONS_JSON__;
  const started = Date.now();
  const consoleMessages = [];
  const pageErrors = [];
  const networkEvents = [];
  page.__sstoryPhase6EvidenceCollector = {
    console: consoleMessages,
    pageErrors,
    network: networkEvents
  };
  const responseCaptures = [];
  const expectedResponses = new Map(
    options.expectedResponses.map(item => [item.pathname, item])
  );
  const servedBodies = new Map(
    options.expectedResponses.map(item => [item.label, []])
  );
  const servedHashes = new Map(
    options.expectedResponses.map(item => [item.label, []])
  );
  const servedTileBodies = [];
  const servedTiles = [];
  let delayedTileRequests = 0;
  let failureResponseCount = 0;

  const royalChildSegment = `/sheets/${options.royalChildId}/`;
  const isWorldV3Tile = url => {
    try {
      const parsed = new URL(url);
      return parsed.pathname.includes('/tiles/world-v3/') && parsed.pathname.endsWith('.webp');
    } catch (_error) {
      return false;
    }
  };
  const isRoyalChildTile = url => isWorldV3Tile(url) && new URL(url).pathname.includes(royalChildSegment);

  page.on('console', message => {
    consoleMessages.push({
      type: message.type(),
      text: message.text(),
      location: message.location()
    });
  });
  page.on('pageerror', error => {
    pageErrors.push(String(error && error.stack ? error.stack : error));
  });
  page.on('requestfailed', request => {
    networkEvents.push({
      kind: 'requestfailed',
      method: request.method(),
      url: request.url(),
      error: request.failure()?.errorText || 'unknown request failure'
    });
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      networkEvents.push({
        kind: 'response',
        method: response.request().method(),
        url: response.url(),
        status: response.status()
      });
    }
    if (response.status() !== 200) return;
    let pathname;
    try {
      pathname = new URL(response.url()).pathname;
    } catch (_error) {
      return;
    }
    const expected = expectedResponses.get(pathname);
    if (expected) {
      responseCaptures.push(
        response.body()
          .then(body => servedBodies.get(expected.label).push([...body]))
          .catch(error => pageErrors.push(
            `served ${expected.repositoryPath} body capture failed: ${error}`
          ))
      );
    }
    if (isWorldV3Tile(response.url())) {
      responseCaptures.push(
        response.body()
          .then(body => servedTileBodies.push({ urlPath: pathname, body: [...body] }))
          .catch(error => pageErrors.push(`served tile body capture failed: ${error}`))
      );
    }
  });

  if (options.mode === 'slow_tiles' || options.mode === 'royal_child_failure') {
    await page.route('**/*', async route => {
      const url = route.request().url();
      if (options.mode === 'royal_child_failure' && isRoyalChildTile(url)) {
        failureResponseCount += 1;
        await route.fulfill({
          status: 503,
          contentType: 'text/plain; charset=utf-8',
          body: 'intentional Phase 6 Royal child-tile failure'
        });
        return;
      }
      if (options.mode === 'slow_tiles' && isWorldV3Tile(url)) {
        delayedTileRequests += 1;
        await new Promise(resolve => setTimeout(resolve, options.delayMs));
      }
      await route.continue();
    });
  }

  await page.goto(options.testedUrl, {
    waitUntil: 'domcontentloaded',
    timeout: options.navigationTimeoutMs
  });
  await page.waitForFunction(
    () => window.EternalArcadiaMapV3?.worldRelease === 'world-v3',
    null,
    { timeout: options.readinessTimeoutMs }
  );
  await page.waitForFunction(
    () => window.EternalArcadiaMapV3?.regionRasters !== null,
    null,
    { timeout: options.readinessTimeoutMs }
  );
  await page.waitForFunction(
    () => document.querySelector('#baseModeBadge')?.classList.contains(
      'status-badge--tiles'
    ),
    null,
    { timeout: options.readinessTimeoutMs }
  );

  const readState = () => page.evaluate(() => {
    const api = window.EternalArcadiaMapV3;
    const index = api?.regionRasterIndex;
    const rasterState = api?.regionRasters?.getState?.() || null;
    const mapElement = document.querySelector('#mapV3');
    const mapBox = mapElement?.getBoundingClientRect();
    const loading = document.querySelector('#loadingPanel');
    const fatal = document.querySelector('#mapError');
    const searchToggle = document.querySelector('#mapSearchToggle');
    const baseBadge = document.querySelector('#baseModeBadge');
    const baseDescription = document.querySelector('#baseLayerDescription');
    return {
      selectedRelease: api?.worldRelease || null,
      activeRelease: api?.worldReleaseConfiguration?.activeRelease || null,
      targetRelease: api?.worldReleaseConfiguration?.targetRelease || null,
      previewRelease: api?.worldReleaseConfiguration?.previewRelease || null,
      indexReleaseId: index?.releaseId || index?.release_id || null,
      boundedSheetCount: index ? 1 + (Array.isArray(index.sheets) ? index.sheets.length : 0) : 0,
      rasterState,
      mapVisible: Boolean(mapBox && mapBox.width >= 250 && mapBox.height >= 250),
      loadingComplete: Boolean(loading?.classList.contains('is-complete')),
      fatalVisible: Boolean(fatal && !fatal.hidden),
      mobileMedia: window.matchMedia('(max-width: 760px)').matches,
      mobileToggleVisible: Boolean(
        searchToggle && getComputedStyle(searchToggle).display !== 'none'
      ),
      baseTilesDecoded: Boolean(
        baseBadge?.classList.contains('status-badge--tiles')
      ),
      baseTileFallbackUsed: Boolean(
        baseDescription?.textContent?.includes('欠損タイル')
      ),
      viewport: { width: window.innerWidth, height: window.innerHeight },
      userAgent: navigator.userAgent
    };
  });

  const moveToSheet = async (sheetId, requestedZoom) => page.evaluate(
    ({ targetId, zoom }) => {
      const api = window.EternalArcadiaMapV3;
      const core = window.EternalArcadiaMapV3Core;
      const entry = api.regionRasterIndex.rasters.find(candidate => candidate.id === targetId);
      if (!entry) throw new Error(`missing runtime sheet ${targetId}`);
      const width = api.worldBounds.getEast() - api.worldBounds.getWest();
      const height = api.worldBounds.getNorth() - api.worldBounds.getSouth();
      const centerX = ((entry.bounds[0] + entry.bounds[2]) / 2 / core.EA_WORLD_EXTENT) * width;
      const centerY = ((entry.bounds[1] + entry.bounds[3]) / 2 / core.EA_WORLD_EXTENT) * height;
      api.map.setView([-centerY, centerX], Math.min(zoom, api.map.getMaxZoom()), {
        animate: false
      });
      api.regionRasters.evaluate();
    },
    { targetId: sheetId, zoom: requestedZoom }
  );

  const waitForRuntime = async predicate => {
    const deadline = Date.now() + options.readinessTimeoutMs;
    let state = await readState();
    while (!predicate(state) && Date.now() < deadline) {
      await page.waitForTimeout(100);
      state = await readState();
    }
    return state;
  };
  const sheetState = (state, sheetId) =>
    state?.rasterState?.sheets?.find(candidate => candidate.id === sheetId) || null;
  const sheetReady = (state, sheetId) => {
    const candidate = sheetState(state, sheetId);
    return Boolean(
      candidate &&
      candidate.status === 'ready' &&
      candidate.viewportReady === true &&
      candidate.visible === true &&
      candidate.requiredTileCount >= 1 &&
      candidate.readyTileCount === candidate.requiredTileCount
    );
  };

  let parentBefore = null;
  let parentAfter = null;
  if (options.mode === 'slow_tiles' || options.mode === 'royal_child_failure') {
    await moveToSheet(options.royalParentId, 3);
    parentBefore = await waitForRuntime(state =>
      sheetReady(state, options.royalParentId) &&
      state.rasterState?.maxNativeZoom >= 4
    );
  }
  if (options.mode === 'royal_child_failure') {
    await moveToSheet(options.royalChildId, 4);
    parentAfter = await waitForRuntime(state =>
      failureResponseCount >= 1 &&
      state.rasterState?.failedIds?.includes(options.royalChildId) &&
      sheetReady(state, options.royalParentId)
    );
    await page.waitForTimeout(250);
    parentAfter = await readState();
  } else if (options.mode === 'slow_tiles') {
    parentAfter = await waitForRuntime(state =>
      delayedTileRequests >= 1 &&
      sheetReady(state, options.royalParentId)
    );
  }

  try {
    await page.waitForLoadState('networkidle', { timeout: options.readinessTimeoutMs });
  } catch (error) {
    pageErrors.push(`network did not become idle before evidence capture: ${error}`);
  }
  const finalState = await readState();
  await Promise.all([...responseCaptures]);
  const sha256Bytes = values => page.evaluate(async bytes => {
    if (!window.crypto?.subtle) throw new Error('browser Web Crypto SHA-256 is unavailable');
    const digest = await window.crypto.subtle.digest('SHA-256', new Uint8Array(bytes));
    return [...new Uint8Array(digest)]
      .map(value => value.toString(16).padStart(2, '0'))
      .join('');
  }, values);
  for (const [label, bodies] of servedBodies) {
    for (const body of bodies) {
      try {
        servedHashes.get(label).push(await sha256Bytes(body));
      } catch (error) {
        pageErrors.push(`served ${label} hash capture failed: ${error}`);
      }
    }
  }
  for (const tile of servedTileBodies) {
    try {
      servedTiles.push({
        url_path: tile.urlPath,
        sha256: await sha256Bytes(tile.body)
      });
    } catch (error) {
      pageErrors.push(`served tile hash capture failed: ${error}`);
    }
  }
  const expectedByLabel = new Map(
    options.expectedResponses.map(item => [item.label, item])
  );
  const responseExact = label => {
    const expected = expectedByLabel.get(label);
    const hashes = servedHashes.get(label) || [];
    return Boolean(expected && hashes.length >= 1 && hashes.every(hash => hash === expected.sha256));
  };
  const exactWarning =
    `[InteractiveMapV3] Sheet tiles unavailable; retaining nearest parent ` +
    `${options.royalParentId}: ${options.royalChildId}`;
  const isExactFallbackWarning = message =>
    message.type === 'warning' &&
    (message.text === exactWarning || message.text.startsWith(`${exactWarning} `));
  const expectedWarning = consoleMessages.filter(message =>
    options.mode === 'royal_child_failure' &&
    isExactFallbackWarning(message)
  );
  const expectedNetworkFailures = networkEvents.filter(event =>
    isRoyalChildTile(event.url) && event.kind === 'response' && event.status === 503
  );
  const unexpectedConsole = consoleMessages.filter(message => {
    if (message.type === 'error') return true;
    if (message.type !== 'warning') return false;
    return !(
      options.mode === 'royal_child_failure' &&
      isExactFallbackWarning(message)
    );
  });
  const unexpectedNetwork = networkEvents.filter(event => !(
    options.mode === 'royal_child_failure' &&
    isRoyalChildTile(event.url) &&
    event.kind === 'response' &&
    event.status === 503
  ));
  const viewport = await page.viewportSize();
  const lastHash = label => (servedHashes.get(label) || []).at(-1) || null;
  const servedRuntimeSha256 = Object.fromEntries(
    options.runtimeResponseLabels.map(label => [
      expectedByLabel.get(label).repositoryPath,
      lastHash(label)
    ])
  );
  const servedProbeManifestSha256 = {};
  if (lastHash('royalParentManifest')) {
    servedProbeManifestSha256[options.royalParentId] = lastHash('royalParentManifest');
  }
  if (lastHash('royalChildManifest')) {
    servedProbeManifestSha256[options.royalChildId] = lastHash('royalChildManifest');
  }
  const assertions = {
    viewport_exact: Boolean(
      viewport && viewport.width === options.viewport.width && viewport.height === options.viewport.height
    ),
    page_ready: finalState.loadingComplete && !finalState.fatalVisible,
    world_v3_selected: finalState.selectedRelease === 'world-v3' &&
      finalState.previewRelease === 'world-v3' &&
      finalState.activeRelease === 'world-v1' &&
      finalState.targetRelease === 'world-v3',
    index_23_bound: finalState.indexReleaseId === 'world-v3' && finalState.boundedSheetCount === 23,
    served_html_hash_exact: responseExact('html'),
    served_index_hash_exact: responseExact('index'),
    served_world_manifest_hash_exact: responseExact('worldManifest'),
    served_runtime_dependencies_exact: options.runtimeResponseLabels.every(responseExact),
    served_tiles_hash_exact: servedTiles.length >= 1,
    base_tiles_decoded: finalState.baseTilesDecoded,
    base_tile_fallback_unused: !finalState.baseTileFallbackUsed,
    map_visible: finalState.mapVisible,
    no_unexpected_console_errors: unexpectedConsole.length === 0,
    no_page_errors: pageErrors.length === 0,
    no_unexpected_network_errors: unexpectedNetwork.length === 0
  };
  if (options.mode === 'mobile') {
    assertions.responsive_mobile_layout = finalState.mobileMedia && finalState.mobileToggleVisible;
  }
  if (options.mode === 'slow_tiles') {
    assertions.slow_tiles_observed = delayedTileRequests >= 1;
    assertions.slow_tiles_recovered = Boolean(
      sheetReady(parentAfter, options.royalParentId)
    );
    assertions.served_parent_manifest_hash_exact = responseExact('royalParentManifest');
  }
  if (options.mode === 'royal_child_failure') {
    assertions.failure_injected = failureResponseCount >= 1;
    assertions.nearest_parent_ready_before = sheetReady(parentBefore, options.royalParentId);
    assertions.nearest_parent_ready_after = sheetReady(parentAfter, options.royalParentId);
    assertions.nearest_parent_visible_after = Boolean(
      sheetState(parentAfter, options.royalParentId)?.visible
    );
    assertions.child_not_visible_after = Boolean(
      parentAfter?.rasterState?.failedIds?.includes(options.royalChildId) &&
      !sheetState(parentAfter, options.royalChildId)?.visible
    );
    assertions.fallback_warning_exact = expectedWarning.length >= 1;
    assertions.served_parent_manifest_hash_exact = responseExact('royalParentManifest');
    assertions.served_child_manifest_hash_exact = responseExact('royalChildManifest');
  }

  const passed = Object.values(assertions).every(Boolean);
  return JSON.stringify({
    id: options.mode,
    result: passed ? 'pass' : 'fail',
    viewport: options.viewport,
    assertions,
    diagnostics: {
      console_errors: unexpectedConsole.map(message => `${message.type}: ${message.text}`),
      page_errors: pageErrors,
      network_errors: unexpectedNetwork.map(event => JSON.stringify(event)),
      expected_console_warnings: expectedWarning.map(message => message.text),
      expected_network_failures: expectedNetworkFailures.map(event => JSON.stringify(event))
    },
    metrics: {
      selected_release: finalState.selectedRelease,
      index_release_id: finalState.indexReleaseId,
      bounded_sheet_count: finalState.boundedSheetCount,
      served_html_sha256: lastHash('html'),
      served_index_sha256: lastHash('index'),
      served_world_manifest_sha256: lastHash('worldManifest'),
      served_runtime_sha256: servedRuntimeSha256,
      served_probe_manifest_sha256: servedProbeManifestSha256,
      served_tiles: servedTiles,
      base_tiles_decoded: finalState.baseTilesDecoded,
      base_tile_fallback_used: finalState.baseTileFallbackUsed,
      available_sheet_count: finalState.rasterState?.available ?? null,
      elapsed_ms: Date.now() - started,
      configured_delay_ms: options.delayMs,
      timeout_ms: options.readinessTimeoutMs,
      delay_ms: options.mode === 'slow_tiles' ? options.delayMs : 0,
      delayed_tile_requests: delayedTileRequests,
      injected_status: options.mode === 'royal_child_failure' ? 503 : 0,
      failed_child_id: options.mode === 'royal_child_failure' ? options.royalChildId : null,
      nearest_parent_id: options.mode === 'royal_child_failure' &&
        sheetReady(parentAfter, options.royalParentId)
        ? options.royalParentId
        : null,
      failure_response_count: failureResponseCount,
      parent_status_before: sheetState(parentBefore, options.royalParentId)?.status || null,
      parent_status_after: sheetState(parentAfter, options.royalParentId)?.status || null,
      failed_sheet_ids: parentAfter?.rasterState?.failedIds || [],
      visible_sheet_ids: parentAfter?.rasterState?.visible || [],
      browser_user_agent: finalState.userAgent
    },
    raw: {
      console: consoleMessages,
      pageErrors,
      network: networkEvents
    }
  });
}
