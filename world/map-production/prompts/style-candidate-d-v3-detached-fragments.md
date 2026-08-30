---
type: "analysis"
category: "analysis"
title: "地図画風候補D v3 三断片尾根プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "ridge-fragments"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補D v2の連続した疑似文字状稜線だけを、十本各三断片と一本の離れたハッチへ置換"
base_files: ["world/map-production/candidates/style-candidate-d-v2-localized-base.png", "world/map-production/controls/style-candidate-d-ridge-edit-mask-v2.png", "world/map-production/controls/style-candidate-d-ridge-fragment-guide-v2.png", "world/map-production/qa/style-candidate-d-v2-flat-relief-bands.json", "world/map-production/qa/style-candidate-d-v2-flat-relief-bands-review2.json"]
methodology: "同一欠陥が二回続いたため、広域マスクを十本の局所マスクへ縮小し、制御図で三つの稜線断片と一本のハッチを明示"
findings: []
metrics: {"golden_threshold": 94, "candidate_attempt": 3, "crest_fragments_total": 30, "hatches_total": 10}
ratings: {}
recommendations: []
---

# 候補D v3 三断片尾根

画像1を唯一の編集対象、画像2を十本の局所編集マスク、画像3を断片数と位置の制御図として使います。生成後は画像2と同じ版管理マスクで画像1へ決定論的に再合成し、BLACK領域の1,194,316ピクセルと道路を画像1のまま固定します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate D v3 detached ridge fragments.

Input images:
- Image 1: sole edit target and authoritative localized D v2 base. Its canvas, crop, geography, roads, cities, vegetation, rocks, parchment, color, and the locations, endpoints, broad tonal footprints, and mutual separation of the ten ridges are locked. Only the defective ridge-specific ink marks identified below may change.
- Image 2: aligned local edit mask. WHITE permits correction only inside ten ridge neighborhoods. GRAY permits only the soft edge of that same correction. BLACK is locked and must remain pixel-identical to Image 1. The black road cuts are also locked. Never draw or reveal this mask.
- Image 3: count-and-placement control only. Each soft cyan haze is one ridge's approximate 40px landform zone, not a visible edge or color instruction. Each of the three magenta dashes is one allowed crest-fragment zone. Each single lime tick is one allowed detached hatch zone. Never copy cyan, magenta, or lime colors, pixels, opacity, blur, or capsule styling.

Exactly one permitted change: remove the continuous scalloped, serrated, script-like ridge-axis marks and all touching comb strokes from the same ten ridges in Image 1, then replace only those removed ridge-specific marks with the exact detached mark count encoded by Image 3.

Exact output count and construction:
- Preserve exactly five mutually separated ridge landforms in the north-east field and five in the south-east field.
- For each ridge, draw exactly three and only three short plain sepia crest fragments in the three magenta zones: thirty crest fragments total across the map.
- Each crest fragment is a simple gently curved ink dash 12-18px long and 1-2px visually thick. It has no peak, tooth, arch sequence, glyph, fork, outline, or attached stroke.
- Keep at least 24px of visibly quiet parchment along the trajectory between crest fragments. No two fragments may touch or visually bridge, even with faint ink.
- For each ridge, draw exactly one and only one short oblique sepia hatch in its lime zone: ten hatches total. Each hatch is 8-14px long and remains visibly detached from every crest fragment and from the ridge-zone edge.
- Use no other new ridge-specific line, hatch, dot, contour, edge, or symbol anywhere in a cyan zone.
- Retain the broad landform only as the existing extremely subtle irregular parchment-tonal texture from Image 1. Do not outline, refill, recolor, brighten, shade, or repaint the cyan footprint.

Within those same ten ridge drawings only, erase every ridge-specific ink mark that forms or resembles a continuous or near-continuous center trajectory; repeated m, n, u, w, arch, scallop, tooth, chevron, or pseudo-letter unit; parallel comb; attached hatch; side-face cue; scenic summit; triangular peak; shadow wedge; closed ring; contour; bullseye; fingerprint-like, crack-like, river-like, root-like, or channel-like line; Y/T branch; or pseudo-writing. This instruction never applies to actual mapped rivers, roads, vegetation, rocks, or parchment substrate.

Absolute invariants:
- Preserve all non-ridge pixels from Image 1, including paper grain and the small natural rock and vegetation marks already present inside the edit neighborhoods.
- Preserve every coastline, island, sea texture, river, delta branch, actual road, bridge, city, port, forest, field, tree, rock, floating-island footprint, palette, and negative-space corridor.
- Keep both protected roads identical, continuous, visually primary, and unobstructed.
- Preserve strict 90-degree top-down projection with no directional light or side face.
- Do not add, remove, move, merge, split, lengthen, or shorten any ridge's broad tonal landform footprint; this does not protect the defective ink marks that must be replaced.

Hard failure if the map contains other than exactly thirty detached crest fragments and ten detached hatches for these ten ridges; if any fragment or hatch touches another; if any continuous scripted axis remains; if broad substrate is repainted; or if any protected feature changes.

Constraints: no text, letters, numbers, pseudo-writing, labels, legend, title, compass, scale bar, signature, watermark, logo, UI, border, frame, modern object, new landmark, control color, or mask artifact.
Avoid: scenic mountains, pictorial peaks, side-view relief, isometric form, dense hatching, outlines, tubes, trenches, channels, contour rings, and repeating texture.
```
