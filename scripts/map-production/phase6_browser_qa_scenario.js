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

  const interactionRequired = options.mode === 'desktop' || options.mode === 'mobile';
  const interactionTimeoutMs = Math.min(options.readinessTimeoutMs, 5000);
  const interactionEvidence = {
    required: interactionRequired,
    mode: options.mode,
    focus_traversal: {
      known_start: null,
      steps: [],
      transfers: []
    },
    keyboard: {
      focused: false,
      pan_key: 'ArrowRight',
      center_before: null,
      center_after: null,
      zoom_key: 'Equal',
      zoom_before: null,
      zoom_after: null
    },
    search: {
      query: null,
      surface_available: false,
      result_count: 0,
      active_option_id: null,
      active_option_label: null,
      active_option_key: null,
      selected_entry_key: null,
      selected_entry_kind: null,
      selected_label: null,
      result_selected: false,
      oracle_source: options.searchOracle.source,
      expected_target: null,
      runtime_target: null,
      zoom_inputs: null,
      expected_zoom: null,
      final_center: null,
      final_bounds: null,
      final_zoom: null,
      target_visible: false,
      center_target_ratio: null,
      popup: {
        open: false,
        lat: null,
        lng: null,
        label_visible: false
      },
      moveend_count: 0,
      quiescent_ms: 0,
      map_animating: null,
      map_focused_after_selection: false
    },
    layer_panel: {
      open_trigger: 'Enter',
      trigger_actionable: false,
      opened: false,
      close_button_focused_after_open: false,
      close_trigger: 'Enter',
      closed: false,
      focus_restored: false
    },
    mobile_search_focus: {
      required: options.mode === 'mobile',
      open_trigger: 'Enter',
      opened: false,
      input_focused: false,
      close_button_focused: false,
      close_trigger: 'Enter',
      closed: false,
      focus_restored: false
    },
    errors: []
  };
  const readFocusState = () => page.evaluate(() => {
    const element = document.activeElement;
    const selector = (() => {
      if (!element) return null;
      if (element === document.body) return 'body';
      if (element.matches?.('a.skip-link')) return 'a.skip-link';
      if (element.matches?.('a.brand')) return 'a.brand';
      return element.id ? `#${element.id}` : element.tagName?.toLowerCase() || null;
    })();
    const rect = element?.getBoundingClientRect?.();
    const style = element ? getComputedStyle(element) : null;
    const visible = Boolean(
      rect &&
      rect.width > 0 &&
      rect.height > 0 &&
      style?.display !== 'none' &&
      style?.visibility !== 'hidden' &&
      style?.opacity !== '0'
    );
    const withinViewport = Boolean(
      visible &&
      rect.bottom > 0 &&
      rect.right > 0 &&
      rect.top < window.innerHeight &&
      rect.left < window.innerWidth
    );
    const enabled = Boolean(
      element &&
      !element.disabled &&
      element.getAttribute?.('aria-disabled') !== 'true'
    );
    const notInert = Boolean(
      element &&
      element.inert !== true &&
      !element.closest?.('[inert]')
    );
    return {
      selector,
      active: Boolean(element && element === document.activeElement),
      visible,
      within_viewport: withinViewport,
      enabled,
      not_inert: notInert,
      actionable: Boolean(
        visible &&
        withinViewport &&
        enabled &&
        notInert &&
        style?.pointerEvents !== 'none'
      )
    };
  });
  const traverseFocus = async (key, expectedSelector) => {
    await page.keyboard.press(key);
    const state = await readFocusState();
    interactionEvidence.focus_traversal.steps.push({
      key,
      expected_selector: expectedSelector,
      ...state
    });
    if (state.selector !== expectedSelector || state.actionable !== true) {
      throw new Error(
        `${key} focus traversal expected ${expectedSelector}, observed ${state.selector}`
      );
    }
    return state;
  };
  const captureFocusTransfer = async (cause, expectedSelector) => {
    const state = await readFocusState();
    interactionEvidence.focus_traversal.transfers.push({
      cause,
      expected_selector: expectedSelector,
      ...state
    });
    if (state.selector !== expectedSelector || state.actionable !== true) {
      throw new Error(
        `${cause} focus transfer expected ${expectedSelector}, observed ${state.selector}`
      );
    }
    return state;
  };
  const readMapView = () => page.evaluate(() => {
    const map = window.EternalArcadiaMapV3?.map;
    if (!map) return null;
    const center = map.getCenter();
    return { lat: center.lat, lng: center.lng, zoom: map.getZoom() };
  });
  const recordInteractionError = (stage, error) => {
    const detail = String(error && error.stack ? error.stack : error);
    const message = `interaction ${stage} failed: ${detail}`;
    interactionEvidence.errors.push(message);
    pageErrors.push(message);
  };

  if (interactionRequired) {
    try {
      const knownStart = await readFocusState();
      interactionEvidence.focus_traversal.known_start = knownStart;
      if (knownStart.selector !== 'body' || knownStart.active !== true) {
        throw new Error(`focus traversal must start at body, observed ${knownStart.selector}`);
      }
      await traverseFocus('Tab', 'a.skip-link');
      await traverseFocus('Tab', 'a.brand');
      if (options.mode === 'mobile') {
        await traverseFocus('Tab', '#mapSearchToggle');
      } else {
        await traverseFocus('Tab', '#mapSearchInput');
      }
    } catch (error) {
      recordInteractionError('focus-start', error);
    }

    try {
      const searchQuery = options.searchOracle.label;
      if (!searchQuery) throw new Error('no searchable map entry is available');
      interactionEvidence.search.query = searchQuery;
      if (options.mode === 'mobile') {
        await page.keyboard.press('Enter');
        await page.waitForFunction(
          () => document.querySelector('#mapSearchToggle')?.getAttribute('aria-expanded') === 'true' &&
            document.activeElement === document.querySelector('#mapSearchInput'),
          null,
          { timeout: interactionTimeoutMs }
        );
        await captureFocusTransfer('search-open', '#mapSearchInput');
      }
      interactionEvidence.search.surface_available = await page.evaluate(() => {
        const surface = document.querySelector('#mapSearchSurface');
        return Boolean(
          surface &&
          surface.getAttribute('aria-hidden') !== 'true' &&
          surface.inert !== true
        );
      });
      await page.keyboard.press('Control+A');
      await page.keyboard.press('Backspace');
      await page.keyboard.insertText(searchQuery);
      await page.waitForFunction(
        () => document.querySelector('#mapSearchInput')?.getAttribute('aria-expanded') === 'true' &&
          document.querySelectorAll('#mapSearchResults [role="option"]:not([aria-disabled="true"])').length >= 1,
        null,
        { timeout: interactionTimeoutMs }
      );
      await page.keyboard.press('ArrowDown');
      await page.waitForFunction(
        () => Boolean(document.querySelector('#mapSearchInput')?.getAttribute('aria-activedescendant')),
        null,
        { timeout: interactionTimeoutMs }
      );
      const resultState = await page.evaluate(oracle => {
        const api = window.EternalArcadiaMapV3;
        const core = window.EternalArcadiaMapV3Core;
        const input = document.querySelector('#mapSearchInput');
        const options = [...document.querySelectorAll(
          '#mapSearchResults [role="option"]:not([aria-disabled="true"])'
        )];
        const activeOptionId = input?.getAttribute('aria-activedescendant') || null;
        const activeOption = activeOptionId ? document.getElementById(activeOptionId) : null;
        const activeIndex = Number(activeOptionId?.match(/-(\d+)$/)?.[1]);
        const matches = core?.filterMapSearchEntries(api?.search?.entries, input?.value, 8) || [];
        const entry = Number.isInteger(activeIndex) ? matches[activeIndex] : null;
        const runtimeTarget = entry ? api?.search?.targets?.get(entry.key) : null;
        const fitZoom = api?.map && api?.worldBounds
          ? api.map.getBoundsZoom(api.worldBounds, false, [18, 18])
          : null;
        return {
          count: options.length,
          activeOptionId,
          activeOptionLabel: activeOption?.querySelector('strong')?.textContent?.trim() || null,
          activeOptionKey: entry?.key || null,
          activeOptionKind: entry?.kind || null,
          runtimeTarget: runtimeTarget?.latlng
            ? { lat: runtimeTarget.latlng.lat, lng: runtimeTarget.latlng.lng }
            : null,
          zoomInputs: api?.map && Number.isFinite(fitZoom)
            ? {
                kind: entry?.kind || null,
                fitZoom,
                currentZoom: api.map.getZoom(),
                maxZoom: api.map.getMaxZoom()
              }
            : null,
          oracle
        };
      }, options.searchOracle);
      const zoomInputs = resultState.zoomInputs;
      const expectedZoom = zoomInputs && [
        zoomInputs.fitZoom,
        zoomInputs.currentZoom,
        zoomInputs.maxZoom,
        options.searchOracle.zoomOffset
      ].every(Number.isFinite)
        ? Math.min(
            zoomInputs.maxZoom,
            Math.max(
              zoomInputs.currentZoom,
              zoomInputs.fitZoom + options.searchOracle.zoomOffset
            )
          )
        : null;
      interactionEvidence.search.result_count = resultState.count;
      interactionEvidence.search.active_option_id = resultState.activeOptionId;
      interactionEvidence.search.active_option_label = resultState.activeOptionLabel;
      interactionEvidence.search.active_option_key = resultState.activeOptionKey;
      interactionEvidence.search.selected_entry_key = resultState.activeOptionKey;
      interactionEvidence.search.selected_entry_kind = resultState.activeOptionKind;
      interactionEvidence.search.expected_target = options.searchOracle.target;
      interactionEvidence.search.runtime_target = resultState.runtimeTarget;
      interactionEvidence.search.zoom_inputs = zoomInputs
        ? {
            kind: zoomInputs.kind,
            fit_zoom: zoomInputs.fitZoom,
            current_zoom: zoomInputs.currentZoom,
            max_zoom: zoomInputs.maxZoom
          }
        : null;
      interactionEvidence.search.expected_zoom = expectedZoom;
      const oracleTarget = options.searchOracle.target;
      if (
        resultState.activeOptionKey !== options.searchOracle.key ||
        resultState.activeOptionKind !== options.searchOracle.kind ||
        resultState.activeOptionLabel !== options.searchOracle.label ||
        !resultState.runtimeTarget ||
        Math.abs(resultState.runtimeTarget.lat - oracleTarget.lat) > 0.000001 ||
        Math.abs(resultState.runtimeTarget.lng - oracleTarget.lng) > 0.000001 ||
        !Number.isFinite(expectedZoom)
      ) {
        throw new Error('active search result does not match the canonical POI oracle');
      }
      await page.evaluate(({ entryKey }) => {
        const api = window.EternalArcadiaMapV3;
        const map = api?.map;
        const target = api?.search?.targets?.get(entryKey);
        if (!map || !target?.latlng) throw new Error(`missing search target ${entryKey}`);
        const tracker = {
          entryKey,
          moveendCount: 0,
          lastMoveendAt: null,
          startedAt: performance.now(),
          handler: null
        };
        tracker.handler = () => {
          tracker.moveendCount += 1;
          tracker.lastMoveendAt = performance.now();
        };
        map.on('moveend', tracker.handler);
        window.__sstoryPhase6SearchMoveTracker = tracker;
      }, { entryKey: resultState.activeOptionKey });
      await page.keyboard.press('Enter');
      await page.waitForFunction(
        expectedLabel => {
          const input = document.querySelector('#mapSearchInput');
          const results = document.querySelector('#mapSearchResults');
          return input?.value === expectedLabel &&
            input.getAttribute('aria-expanded') === 'false' &&
            results?.hidden === true;
        },
        resultState.activeOptionLabel,
        { timeout: interactionTimeoutMs }
      );
      await page.waitForFunction(
        ({ entryKey, label, oracleTarget }) => {
          const api = window.EternalArcadiaMapV3;
          const map = api?.map;
          const tracker = window.__sstoryPhase6SearchMoveTracker;
          const popup = map?._popup;
          const popupLatLng = popup?.getLatLng?.();
          const popupLabel = popup?.getElement?.()
            ?.querySelector('.v3-popup h3')?.textContent?.trim();
          const quietFor = tracker?.lastMoveendAt === null
            ? 0
            : performance.now() - tracker.lastMoveendAt;
          return Boolean(
            tracker?.entryKey === entryKey &&
            tracker.moveendCount >= 1 &&
            quietFor >= 300 &&
            !map?._animatingZoom &&
            !map?._panAnim?._inProgress &&
            popup &&
            map.hasLayer(popup) &&
            popupLatLng &&
            Math.abs(popupLatLng.lat - oracleTarget.lat) <= 0.000001 &&
            Math.abs(popupLatLng.lng - oracleTarget.lng) <= 0.000001 &&
            popupLabel === label
          );
        },
        {
          entryKey: resultState.activeOptionKey,
          label: resultState.activeOptionLabel,
          oracleTarget: options.searchOracle.target
        },
        { timeout: interactionTimeoutMs }
      );
      const selectionState = await page.evaluate(({ entryKey, label, oracleTarget }) => {
        const api = window.EternalArcadiaMapV3;
        const map = api.map;
        const tracker = window.__sstoryPhase6SearchMoveTracker;
        const center = map.getCenter();
        const bounds = map.getBounds();
        const spanLat = Math.max(Math.abs(bounds.getNorth() - bounds.getSouth()), 0.000001);
        const spanLng = Math.max(Math.abs(bounds.getEast() - bounds.getWest()), 0.000001);
        const popup = map._popup;
        const popupLatLng = popup?.getLatLng?.();
        const popupLabel = popup?.getElement?.()
          ?.querySelector('.v3-popup h3')?.textContent?.trim();
        const state = {
          selectedLabel: document.querySelector('#mapSearchInput')?.value || null,
          mapFocused: document.activeElement === document.querySelector('#mapV3'),
          finalCenter: { lat: center.lat, lng: center.lng },
          finalBounds: {
            south: bounds.getSouth(),
            west: bounds.getWest(),
            north: bounds.getNorth(),
            east: bounds.getEast()
          },
          finalZoom: map.getZoom(),
          targetVisible: bounds.contains([oracleTarget.lat, oracleTarget.lng]),
          centerTargetRatio: Math.max(
            Math.abs(center.lat - oracleTarget.lat) / spanLat,
            Math.abs(center.lng - oracleTarget.lng) / spanLng
          ),
          popup: {
            open: Boolean(popup && map.hasLayer(popup)),
            lat: popupLatLng?.lat ?? null,
            lng: popupLatLng?.lng ?? null,
            labelVisible: popupLabel === label
          },
          moveendCount: tracker?.moveendCount ?? 0,
          quiescentMs: tracker?.lastMoveendAt === null
            ? 0
            : performance.now() - tracker.lastMoveendAt,
          mapAnimating: Boolean(map._animatingZoom || map._panAnim?._inProgress)
        };
        if (tracker?.handler) map.off('moveend', tracker.handler);
        delete window.__sstoryPhase6SearchMoveTracker;
        return state;
      }, {
        entryKey: resultState.activeOptionKey,
        label: resultState.activeOptionLabel,
        oracleTarget: options.searchOracle.target
      });
      interactionEvidence.search.selected_label = selectionState.selectedLabel;
      interactionEvidence.search.result_selected = Boolean(
        resultState.activeOptionLabel &&
        selectionState.selectedLabel === resultState.activeOptionLabel
      );
      interactionEvidence.search.final_center = selectionState.finalCenter;
      interactionEvidence.search.final_bounds = selectionState.finalBounds;
      interactionEvidence.search.final_zoom = selectionState.finalZoom;
      interactionEvidence.search.target_visible = selectionState.targetVisible;
      interactionEvidence.search.center_target_ratio = selectionState.centerTargetRatio;
      interactionEvidence.search.popup = {
        open: selectionState.popup.open,
        lat: selectionState.popup.lat,
        lng: selectionState.popup.lng,
        label_visible: selectionState.popup.labelVisible
      };
      interactionEvidence.search.moveend_count = selectionState.moveendCount;
      interactionEvidence.search.quiescent_ms = selectionState.quiescentMs;
      interactionEvidence.search.map_animating = selectionState.mapAnimating;
      interactionEvidence.search.map_focused_after_selection = selectionState.mapFocused;
      if (options.mode === 'mobile') {
        await captureFocusTransfer('search-selection', '#mapV3');
      }
    } catch (error) {
      recordInteractionError('search-selection', error);
    }

    const operateLayerPanel = async () => {
      const triggerState = await readFocusState();
      interactionEvidence.layer_panel.trigger_actionable = Boolean(
        triggerState.selector === '#layerPanelButton' && triggerState.actionable
      );
      await page.keyboard.press('Enter');
      await page.waitForFunction(
        () => document.querySelector('#layerPanelButton')?.getAttribute('aria-expanded') === 'true' &&
          document.querySelector('#layerPanel')?.classList.contains('is-open') &&
          document.querySelector('#layerPanel')?.getAttribute('aria-hidden') === 'false' &&
          document.querySelector('#layerPanel')?.inert !== true &&
          document.activeElement === document.querySelector('#layerPanelClose'),
        null,
        { timeout: interactionTimeoutMs }
      );
      interactionEvidence.layer_panel.opened = true;
      const closeFocus = await readFocusState();
      interactionEvidence.layer_panel.close_button_focused_after_open = Boolean(
        closeFocus.selector === '#layerPanelClose' && closeFocus.actionable
      );
      if (!interactionEvidence.layer_panel.close_button_focused_after_open) {
        throw new Error(
          `layer panel open expected #layerPanelClose, observed ${closeFocus.selector}`
        );
      }
      await page.keyboard.press('Enter');
      await page.waitForFunction(
        () => document.querySelector('#layerPanelButton')?.getAttribute('aria-expanded') === 'false' &&
          !document.querySelector('#layerPanel')?.classList.contains('is-open') &&
          document.querySelector('#layerPanel')?.getAttribute('aria-hidden') === 'true' &&
          document.querySelector('#layerPanel')?.inert === true &&
          document.activeElement === document.querySelector('#layerPanelButton'),
        null,
        { timeout: interactionTimeoutMs }
      );
      interactionEvidence.layer_panel.closed = true;
      interactionEvidence.layer_panel.focus_restored = true;
    };

    try {
      if (options.mode === 'mobile') {
        await traverseFocus('Shift+Tab', '#layerPanelButton');
        await operateLayerPanel();
        await traverseFocus('Shift+Tab', '#helpButton');
        await traverseFocus('Shift+Tab', '#mapSearchToggle');
        await page.keyboard.press('Enter');
        await page.waitForFunction(
          () => document.querySelector('#mapSearchToggle')?.getAttribute('aria-expanded') === 'true' &&
            document.activeElement === document.querySelector('#mapSearchInput'),
          null,
          { timeout: interactionTimeoutMs }
        );
        await captureFocusTransfer('mobile-search-open', '#mapSearchInput');
        const openState = await page.evaluate(() => ({
          opened: document.querySelector('#mapSearchToggle')?.getAttribute('aria-expanded') === 'true' &&
            document.querySelector('#mapSearchSurface')?.getAttribute('aria-hidden') === 'false' &&
            document.querySelector('#mapSearchSurface')?.inert !== true,
          inputFocused: document.activeElement === document.querySelector('#mapSearchInput')
        }));
        interactionEvidence.mobile_search_focus.opened = openState.opened;
        interactionEvidence.mobile_search_focus.input_focused = openState.inputFocused;
        await traverseFocus('Tab', '#mapSearchClear');
        await traverseFocus('Tab', '#mapSearchClose');
        interactionEvidence.mobile_search_focus.close_button_focused = true;
        await page.keyboard.press('Enter');
        await page.waitForFunction(
          () => document.querySelector('#mapSearchToggle')?.getAttribute('aria-expanded') === 'false' &&
            document.querySelector('#mapSearchSurface')?.getAttribute('aria-hidden') === 'true' &&
            document.querySelector('#mapSearchSurface')?.inert === true &&
            document.activeElement === document.querySelector('#mapSearchToggle'),
          null,
          { timeout: interactionTimeoutMs }
        );
        await captureFocusTransfer('mobile-search-close', '#mapSearchToggle');
        interactionEvidence.mobile_search_focus.closed = true;
        interactionEvidence.mobile_search_focus.focus_restored = true;
        await traverseFocus('Tab', '#helpButton');
        await traverseFocus('Tab', '#layerPanelButton');
        await traverseFocus('Tab', '#mapV3');
      } else {
        await traverseFocus('Tab', '#mapSearchClear');
        await traverseFocus('Tab', '#fitMapButton');
        await traverseFocus('Tab', '#helpButton');
        await traverseFocus('Tab', '#layerPanelButton');
        await operateLayerPanel();
        await traverseFocus('Tab', '#mapV3');
      }
    } catch (error) {
      recordInteractionError('focus-controls', error);
    }

    try {
      const mapFocus = await readFocusState();
      interactionEvidence.keyboard.focused = Boolean(
        mapFocus.selector === '#mapV3' && mapFocus.actionable
      );
      const beforePan = await readMapView();
      interactionEvidence.keyboard.center_before = beforePan
        ? { lat: beforePan.lat, lng: beforePan.lng }
        : null;
      await page.keyboard.press('ArrowRight');
      await page.waitForFunction(
        before => {
          const map = window.EternalArcadiaMapV3?.map;
          if (!map || !before) return false;
          const center = map.getCenter();
          return Math.abs(center.lat - before.lat) > 0.000001 ||
            Math.abs(center.lng - before.lng) > 0.000001;
        },
        beforePan,
        { timeout: interactionTimeoutMs }
      );
      await page.waitForFunction(
        () => !window.EternalArcadiaMapV3?.map?._panAnim?._inProgress,
        null,
        { timeout: interactionTimeoutMs }
      );
      const afterPan = await readMapView();
      interactionEvidence.keyboard.center_after = afterPan
        ? { lat: afterPan.lat, lng: afterPan.lng }
        : null;
      interactionEvidence.keyboard.zoom_before = afterPan?.zoom ?? null;
      await page.keyboard.press('Equal');
      await page.waitForFunction(
        beforeZoom => window.EternalArcadiaMapV3?.map?.getZoom() > beforeZoom + 0.000001,
        interactionEvidence.keyboard.zoom_before,
        { timeout: interactionTimeoutMs }
      );
      interactionEvidence.keyboard.zoom_after = (await readMapView())?.zoom ?? null;
    } catch (error) {
      recordInteractionError('keyboard-map', error);
    }
  }

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
  if (interactionRequired) {
    const keyboardBefore = interactionEvidence.keyboard.center_before;
    const keyboardAfter = interactionEvidence.keyboard.center_after;
    const expectedFocusSteps = options.mode === 'mobile'
      ? [
          ['Tab', 'a.skip-link'],
          ['Tab', 'a.brand'],
          ['Tab', '#mapSearchToggle'],
          ['Shift+Tab', '#layerPanelButton'],
          ['Shift+Tab', '#helpButton'],
          ['Shift+Tab', '#mapSearchToggle'],
          ['Tab', '#mapSearchClear'],
          ['Tab', '#mapSearchClose'],
          ['Tab', '#helpButton'],
          ['Tab', '#layerPanelButton'],
          ['Tab', '#mapV3']
        ]
      : [
          ['Tab', 'a.skip-link'],
          ['Tab', 'a.brand'],
          ['Tab', '#mapSearchInput'],
          ['Tab', '#mapSearchClear'],
          ['Tab', '#fitMapButton'],
          ['Tab', '#helpButton'],
          ['Tab', '#layerPanelButton'],
          ['Tab', '#mapV3']
        ];
    assertions.keyboard_focus_traversal_operable = Boolean(
      interactionEvidence.focus_traversal.known_start?.selector === 'body' &&
      interactionEvidence.focus_traversal.known_start?.active === true &&
      interactionEvidence.focus_traversal.steps.length === expectedFocusSteps.length &&
      expectedFocusSteps.every(([key, selector], index) => {
        const step = interactionEvidence.focus_traversal.steps[index];
        return step?.key === key &&
          step?.expected_selector === selector &&
          step?.selector === selector &&
          step?.active === true &&
          step?.visible === true &&
          step?.within_viewport === true &&
          step?.enabled === true &&
          step?.not_inert === true &&
          step?.actionable === true;
      })
    );
    assertions.keyboard_pan_operable = Boolean(
      interactionEvidence.keyboard.focused &&
      keyboardBefore &&
      keyboardAfter &&
      (
        Math.abs(keyboardAfter.lat - keyboardBefore.lat) > 0.000001 ||
        Math.abs(keyboardAfter.lng - keyboardBefore.lng) > 0.000001
      )
    );
    assertions.keyboard_zoom_operable = Boolean(
      Number.isFinite(interactionEvidence.keyboard.zoom_before) &&
      Number.isFinite(interactionEvidence.keyboard.zoom_after) &&
      interactionEvidence.keyboard.zoom_after > interactionEvidence.keyboard.zoom_before
    );
    assertions.search_keyboard_selection_operable = Boolean(
      interactionEvidence.search.surface_available &&
      interactionEvidence.search.result_count >= 1 &&
      interactionEvidence.search.active_option_id &&
      interactionEvidence.search.active_option_label === interactionEvidence.search.query &&
      interactionEvidence.search.active_option_key ===
        interactionEvidence.search.selected_entry_key &&
      interactionEvidence.search.selected_entry_key?.startsWith(
        `${interactionEvidence.search.selected_entry_kind}:`
      ) &&
      interactionEvidence.search.selected_label === interactionEvidence.search.active_option_label &&
      interactionEvidence.search.result_selected &&
      interactionEvidence.search.expected_target &&
      interactionEvidence.search.final_center &&
      interactionEvidence.search.final_bounds &&
      Number.isFinite(interactionEvidence.search.expected_zoom) &&
      Number.isFinite(interactionEvidence.search.final_zoom) &&
      Math.abs(
        interactionEvidence.search.final_zoom - interactionEvidence.search.expected_zoom
      ) <= 0.001 &&
      interactionEvidence.search.target_visible &&
      Number.isFinite(interactionEvidence.search.center_target_ratio) &&
      interactionEvidence.search.center_target_ratio <= 0.25 &&
      interactionEvidence.search.popup.open &&
      interactionEvidence.search.popup.label_visible &&
      Number.isFinite(interactionEvidence.search.popup.lat) &&
      Number.isFinite(interactionEvidence.search.popup.lng) &&
      Math.abs(
        interactionEvidence.search.popup.lat - interactionEvidence.search.expected_target.lat
      ) <= 0.000001 &&
      Math.abs(
        interactionEvidence.search.popup.lng - interactionEvidence.search.expected_target.lng
      ) <= 0.000001 &&
      interactionEvidence.search.moveend_count >= 1 &&
      interactionEvidence.search.quiescent_ms >= 300 &&
      interactionEvidence.search.map_animating === false
    );
    assertions.layer_panel_keyboard_toggle_operable = Boolean(
      interactionEvidence.layer_panel.trigger_actionable &&
      interactionEvidence.layer_panel.opened &&
      interactionEvidence.layer_panel.close_button_focused_after_open &&
      interactionEvidence.layer_panel.closed &&
      interactionEvidence.layer_panel.focus_restored
    );
  }
  if (options.mode === 'mobile') {
    assertions.mobile_search_open_focus = Boolean(
      interactionEvidence.mobile_search_focus.opened &&
      interactionEvidence.mobile_search_focus.input_focused &&
      interactionEvidence.mobile_search_focus.close_button_focused
    );
    assertions.mobile_search_close_focus_restored = Boolean(
      interactionEvidence.mobile_search_focus.closed &&
      interactionEvidence.mobile_search_focus.focus_restored
    );
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
      interaction_evidence: interactionEvidence,
      browser_user_agent: finalState.userAgent
    },
    raw: {
      console: consoleMessages,
      pageErrors,
      network: networkEvents
    }
  });
}
