---
type: "analysis"
category: "analysis"
title: "地図画風候補D v1 制御尾根鎖プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "ridge-guide"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補Bの五回上限後に、実道路マスクと非接続尾根トポロジーから候補Dを開始"
base_files: ["world/map-production/candidates/style-candidate-b-v2-plan-view.png", "world/map-production/controls/style-candidate-d-mountain-mask-v1.png", "world/map-production/controls/style-candidate-d-ridge-guide-v1.png", "world/map-production/qa/style-candidate-b-v5-sparse-ridges.json", "world/map-production/qa/style-candidate-b-v5-sparse-ridges-review2.json"]
methodology: "親地理を決定論的合成で固定し、生成モデルには編集域と尾根中心線を別画像で明示"
findings: []
metrics: {"golden_threshold": 94, "candidate_attempt": 1}
ratings: {}
recommendations: []
---

# 候補D v1 制御尾根鎖

Built-in ImageGenでは画像1を編集対象、画像2を編集可能領域、画像3を尾根トポロジー参照として使います。生成後は画像2と同じ版管理マスクで画像1へ決定論的に合成します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate D v1 guided ridge chains.
Input images:
- Image 1: sole edit target and locked parent geography, candidate B v2 plan-view map.
- Image 2: edit-area mask. WHITE is full-strength edit space. GRAY is deterministic blend space: continue the same guided ridge naturally through it when Image 3 crosses it, but add no independent feature there. BLACK is locked, including the accurately traced road corridors. Never draw or reveal this mask.
- Image 3: geometry-only topology guide, never a style, palette, or pixel source. Its saturated hue marks guide geometry only. Create exactly one independent ridge chain for each separate colored band and no extra chain. Use each band only as a center trajectory and approximate footprint; do not trace its edges or any guide pixel as a literal visible line. Follow its location, length, separation, and non-connection. Sample only dark sepia ink and warm parchment from Image 1; no saturated guide hue may appear.

Single permitted change: replace only the mountain-relief mark vocabulary inside the WHITE cores and their guided GRAY continuations in Image 2. Do not clean up, restyle, or improve anything else. Erase the parent's repeated peak targets and contour waves, then create the exact small set of separate mountain ridge chains encoded by Image 3.

Mountain vocabulary:
- Make each chain one long, low-contrast warm-parchment ridge band whose length is much greater than its width. The band, not a dark center line, carries the mountain shape.
- The smooth cyan capsule is not the desired appearance. Vary the parchment ridge band's width and edge irregularity, taper free interior ends, and never preserve a uniform tube, road, or channel silhouette.
- Within each band, use a few discontinuous sepia crest fragments and isolated short oblique cross-slope marks. Keep the marks away from the crest trajectory, alternate sides irregularly, never pair them, and never join them.
- Keep every chain independent and separated by large irregular quiet areas for vector labels.
- Taper only free interior ends. A chain that reaches the image edge or mountain-footprint edge may continue naturally beyond it.
- Use the parent's antique ink character and muted parchment color with no directional light or shadow.

Absolute invariants:
- Preserve the exact 1536x1024 canvas and crop.
- Preserve every coastline, island, sea texture, river, delta branch, actual road, bridge, city, port, forest, field, floating-island footprint, mountain footprint boundary, palette, paper grain, and negative-space corridor.
- Treat all BLACK pixels of Image 2 as locked and keep both protected roads identical, continuous, and unobstructed.
- Treat the parchment substrate as locked outside the restrained ridge bands: do not globally repaint, recolor, blur, or change its texture.
- Maintain an infinitely high exact 90-degree plan view. Add no landmark or geographic feature.

Forbidden mountain vocabulary: no joined or branching line network; no river, tributary, crack, fault, root, lightning, fingerprint, wood-grain, comb, ring, bullseye, repeated contour, triangular peak, pictorial mountain, side face, cast shadow, isometric form, dense hatching, or dark slope wedge.

Hard validation rule: The edit fails if separate ridge bands connect; if a literal dark center line dominates; if relief resembles cracks, rivers, roots, or drainage; if any old repeated mountain symbol remains in a white core; if a protected road or other geography changes; if guide colors or mask pixels appear; or if any text appears.

Constraints: Do not add text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, decorative border, frame, modern object, clone cluster, or repeating texture.
Avoid: changing non-mountain geography, copying guide colors, redrawing roads, changing paper grain, increasing density, reducing label space, scenic mountains, photorealistic or DEM elevation rendering, and hillshade.
```
