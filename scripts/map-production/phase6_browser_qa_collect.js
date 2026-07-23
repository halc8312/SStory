async page => {
  const collector = page.__sstoryPhase6EvidenceCollector;
  if (!collector) {
    return JSON.stringify({
      collector_ready: false,
      console: [],
      pageErrors: ['Phase 6 final diagnostics collector is unavailable'],
      network: [],
      baseTilesDecoded: false,
      baseTileFallbackUsed: true
    });
  }
  const baseState = await page.evaluate(() => {
    const badge = document.querySelector('#baseModeBadge');
    const description = document.querySelector('#baseLayerDescription');
    return {
      decoded: Boolean(badge?.classList.contains('status-badge--tiles')),
      fallbackUsed: Boolean(description?.textContent?.includes('欠損タイル'))
    };
  });
  return JSON.stringify({
    collector_ready: true,
    console: [...collector.console],
    pageErrors: [...collector.pageErrors],
    network: [...collector.network],
    baseTilesDecoded: baseState.decoded,
    baseTileFallbackUsed: baseState.fallbackUsed
  });
}
