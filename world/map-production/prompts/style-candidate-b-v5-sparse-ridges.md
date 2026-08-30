---
type: "analysis"
category: "analysis"
title: "地図画風候補B v5 疎な分岐稜線編集プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "ridge-lines"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補B v4bの保護済み地理を固定し、山岳内部の反復線だけを疎な分岐稜線へ置換"
base_files: ["world/map-production/candidates/style-candidate-b-v4b-mask-refinement.png", "world/map-production/controls/style-candidate-b-mountain-mask-v2.png", "world/map-production/qa/style-candidate-b-v4b-mask-refinement.json"]
methodology: "同一マスクと決定論的合成条件を維持し、独立QAで即時不合格となった反復線の語彙だけを変更"
findings: []
metrics: {"parent_score": 83, "golden_threshold": 94, "attempt": 5}
ratings: {}
recommendations: []
---

# 候補B v5 疎な分岐稜線

Built-in ImageGenでは画像1を編集対象、画像2を編集可能領域のマスク参照として使います。生成後は同じマスクv2で親地理へ決定論的に合成し、マスク外画素と道路を完全に固定します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate B v5 sparse ridges.
Input images:
- Image 1: sole edit target, candidate B v4b mask-refined plan-view map.
- Image 2: edit-area control mask v2. WHITE means only the relief ink strokes may change. GRAY means preserve the parent's paper and color while only the ends of changed ink strokes may fade naturally. BLACK means completely locked, including every black road corridor. Never draw, copy, or reveal the mask itself in the output.

Primary request: Change only the repetitive fingerprint-like line groups inside the WHITE mountain areas of Image 2. Replace them with sparse, irregular, branching ridge-spine networks and short broken valley marks. Preserve every other visual property of Image 1.

Single targeted change — internal relief-line vocabulary only:
- Remove every long, continuous, equally spaced wave, parallel wood-grain stripe, repeated arc, loop, ring, and fingerprint pattern.
- In each of the two white edit regions, draw only 3 to 7 irregular main ridge-spine networks in total. Each main spine must bend unevenly, fork asymmetrically, taper into short branches, and end at different positions.
- Add a small number of short broken valley or drainage-notch marks between the ridge spines. Keep each secondary mark discontinuous and clearly shorter than a main spine.
- Leave irregular quiet gaps of approximately 20 to 40 pixels between separate main networks. This spacing does not apply to branches within one network. Do not fill the gaps with contour bands.
- Prevent any two line groups from remaining parallel for a long span. Do not reconnect branches into closed loops.
- Keep the existing nearly uniform antique-ink stroke width, flat paper printing, local line color, local paper color, watercolor softness, and overall mountain footprint exactly consistent with Image 1.
- Treat the parchment substrate as locked: erase and redraw only the relief ink strokes; do not repaint, recolor, blur, or change the paper texture beneath them.

Absolute invariants:
- Keep Image 1's exact 1536x1024 canvas and crop.
- Keep every coastline, island, sea texture, river, delta branch, road, bridge, city, port, forest, field, floating-island footprint, paper grain, palette, line weight, and negative-space corridor visually identical.
- Do not change the mountain footprint boundaries, the mask feather transition, or either road corridor crossing the mountain areas.
- Keep the strict infinitely high 90-degree plan view. Relief is flat cartographic ink on paper, never a depicted object.
- Keep the existing amount and placement of non-mountain detail. Add no landmark or feature.

Forbidden relief vocabulary within the white edit cores only:
- no triangular, pyramidal, pointed, radial, fan-shaped, star-shaped, or pictorial peak;
- no front face, side face, underside, cliff wall, horizon, aerial perspective, isometric form, directional lighting, cast shadow, or oblique shadow;
- no bullseye, target, crater, mandala, center dot, center diamond, closed contour, repeated icon, fingerprint, wood grain, comb pattern, or long parallel wave field;
- no dense hatching or filled dark wedge that reads as a slope face.

Hard validation rule: The edit fails if a repeated wave field, fingerprint pattern, closed relief loop, pictorial peak, slope face, or perspective appears; if any protected feature changes; if road continuity changes; or if any text appears.

Constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, decorative border, or frame. No modern objects. No clone clusters or repeating texture.
Avoid: changing geography, recoloring, changing paper grain, changing roads or rivers, changing mask boundaries, increasing density, lowering label space, redrawing non-mountain areas, scenic mountains, elevation rendering, hillshade.
```
