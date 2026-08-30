---
type: "analysis"
category: "analysis"
title: "地図画風候補D v2 平面尾根帯プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "plan-view"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補D v1の同じ十本の尾根について、横顔表現だけを真上視点の平面地形帯へ変更"
base_files: ["world/map-production/candidates/style-candidate-d-v1-guided-ridge-chains.png", "world/map-production/controls/style-candidate-d-mountain-mask-v1.png", "world/map-production/controls/style-candidate-d-ridge-guide-v1.png", "world/map-production/qa/style-candidate-d-v1-guided-ridge-chains.json", "world/map-production/qa/style-candidate-d-v1-guided-ridge-chains-review2.json"]
methodology: "v1で合格した位置・分離・道路保護・継ぎ目を固定し、失敗した尾根の投影表現だけを再編集"
findings: []
metrics: {"golden_threshold": 94, "candidate_attempt": 2, "v1_score_high": 86, "v1_score_low": 73}
ratings: {}
recommendations: []
---

# 候補D v2 平面尾根帯

Built-in ImageGenでは画像1を唯一の編集対象、画像2を編集可能領域、画像3を、既存十本それぞれの中心軌跡、約40±3pxの帯幅、一本の短いハッチのおおよその配置だけを確認する幾何参照として使います。v1の失敗原因である投影表現以外は変更しません。

生成後は画像2と同じ版管理マスクで生成結果を画像1へ決定論的に合成し、BLACK領域と道路は画像1の画素をそのまま使用します。WHITE領域だけに修正を採用し、GRAY領域では同じ修正の端部だけをアルファ合成します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate D v2 flat relief bands.

Input images:
- Image 1: sole edit target and authoritative current artwork, candidate D v1 composite. Its geography, roads, ten ridge locations, spacing, palette, paper, vegetation, rocks, and quiet label corridors are locked.
- Image 2: edit-area mask aligned pixel-for-pixel to Image 1. WHITE permits the one requested ridge-rendering correction. GRAY permits only a softly attenuated continuation of that same correction. BLACK is locked and must remain identical. Never draw or reveal the mask.
- Image 3: geometry-only reminder. Each broad cyan band indicates one existing ridge's center trajectory and approximate 40±3 px tonal-band footprint; each thin cyan tick indicates only the approximate zone for that ridge's single detached hatch. Do not trace any guide edge or pixel, or copy its cyan color, opacity, or smooth capsule styling. Image 1 remains authoritative for placement and endpoints; do not move, add, join, split, lengthen, or shorten any ridge.

Exactly one permitted change: flatten the visual projection of the same ten existing ridge drawings. Replace only their pictorial side-faced mountain rendering with strict 90-degree plan-view parchment relief. Do not redesign or repaint any other feature inside or outside the mask.

Required flat relief construction for each of the same ten ridges:
- Keep the existing location, trajectory, approximate footprint, endpoints, irregular width, and large gaps.
- Make the landform read first as a broad, very low-contrast irregular warm-parchment tonal band, about the guide's 40±3 px visual width, with softly broken edges and no enclosing outline.
- Place only two or three short discontinuous sepia crest fragments near the middle trajectory. No fragment may span more than one quarter of the ridge length, and fragments may not touch each other.
- Place exactly one short oblique cross-slope hatch per ridge in approximately the guide-indicated area. It must be fully detached from every crest fragment and band edge by visible parchment.
- Give both sides of the ridge comparable ink density. Use no directional light, dark side, near side, far side, face, wall, or shadow.
- At a glance and when isolated, the mark must read as a flat landform texture, never as a horizon silhouette, mountain icon, or scenic range.

Remove from all ten ridges: every continuous dark summit line, saw-tooth crest, triangular peak, profile edge, closed outline, touching hatch, parallel hatch comb, side face, dark slope wedge, cast shadow, and directional shading cue. Do not replace these with contours, rings, cracks, rivers, roots, channels, or branching networks.

Absolute invariants:
- Preserve the exact 1536x1024 canvas, crop, alignment, and strict top-down projection.
- Preserve every coastline, island, sea texture, river, delta branch, actual road, bridge, city, port, forest, field, tree, rock, floating-island footprint, mountain-field boundary, palette, paper grain, and negative-space corridor from Image 1.
- Preserve the number of ridges at exactly five in the north-east field and five in the south-east field, all mutually disconnected.
- Keep both protected roads identical, continuous, visually primary, and unobstructed.
- Treat the parchment substrate outside the ten ridge marks as locked. Do not globally clean, blur, recolor, sharpen, or alter its texture.

Hard failure if any ridge has a continuous dominant center line; a triangular or serrated scenic crest; a visible side face; touching crest and hatch strokes; one-sided shading; a closed contour or bullseye; Y/T/branch topology; or if any road, tree, rock, field, city, coast, river, guide color, text, or mask boundary changes.

Constraints: no text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, border, frame, modern object, extra landmark, clone cluster, or new repeated texture.
Avoid: pictorial mountains, side-view relief, isometric form, DEM hillshade, dense hatching, uniform tubes, roads, trenches, channels, fingerprints, wood grain, contour rings, and scenic illustration.
```
