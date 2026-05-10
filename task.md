# Deep Zoom Implementation Progress

## Current Phase: Implementing overlay switching for Elysion

## Bounds Mapping (world map pixel coords, 4096x2730)

### Elysion Continent Overlay (L1, zoom 0~1)
- Bounds: x=[1050, 2150], y=[600, 1700] (with ocean padding)
- Image: continents/elysion-continent.jpg (generated, 1264x848)

### Elysion Region Overlays (L2, zoom 2~3)
Region images are 1536x1024, aspect ratio 3:2
Need to map each to its world-map position:

| Region | File | Approx pixel bounds (x1,y1,x2,y2) |
|--------|------|-------------------------------------|
| astralis-region | Astralis & surrounds | 1550,850,1950,1120 |
| moonshadow-forest | NW Elysion forest | 1200,750,1600,1020 |
| silver-plains | South Elysion | 1400,1150,1800,1420 |
| tensho-mountains | East mountains | 1700,750,2100,1020 |
| iron-mountains | West border | 1050,850,1450,1120 |

### Other Continent Regions (for later)
| Region | Continent |
|--------|-----------|
| emerald-belt | Lumiera |
| lumiera-arch | Lumiera |
| red-sea-desert | Chaos Ria |
| lands-of-fire | Chaos Ria |
| labyrinth-of-time | Grimoire |

## Done
- [x] Generate Elysion continent map image
- [x] Convert to JPG
- [x] Analyze world map pixel bounds

## Next
- [ ] Implement zoom-level overlay switching in HTML
- [ ] Test overlay positioning
- [ ] Refine bounds by visual testing
- [ ] Push to GitHub
