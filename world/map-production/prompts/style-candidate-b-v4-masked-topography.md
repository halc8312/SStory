---
type: "analysis"
category: "analysis"
title: "地図画風候補B v4 マスク限定平面地形編集プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "topography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補B v2を親に、山岳マスク内だけを平面地形線へ置換"
base_files: ["world/map-production/candidates/style-candidate-b-v2-plan-view.png", "world/map-production/controls/style-candidate-b-mountain-mask-v1.png", "world/map-production/qa/style-candidate-b-v3-mountain-relief.json"]
methodology: "二値マスクを生成時の視覚指示と生成後の決定論的合成に共用し、マスク外画素を完全固定"
findings: []
metrics: {"parent_score": 84, "golden_threshold": 94, "attempt": 4}
ratings: {}
recommendations: []
---

# 候補B v4 マスク限定平面地形修正

Built-in ImageGenでは画像1を編集対象、画像2を編集可能領域のマスク参照として使います。生成後は同じマスクでB v2へ決定論的に合成し、黒領域の画素を完全に保護します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate B v4 masked topography.
Input images:
- Image 1: sole edit target, candidate B v2 plan view.
- Image 2: edit-area control mask. White means mountain relief may change; black means absolutely protected. The black road corridors crossing white areas are also protected.

Primary request: Inside the WHITE areas of Image 2 only, remove the repeated bullseye mountain symbols and replace them with relief marks that look like ink lines printed flat on a topographic map. Do not depict mountains as objects, peaks, cones, cliffs, or scenery. Do not change anything in BLACK areas.

Single targeted change — flat topographic linework:
- Erase the isolated concentric targets, center dots, diamonds, volcano icons, and circular hill symbols inside the white mask.
- Draw a few long, thin, irregular ridge-spine lines that branch and reconnect across each range.
- Add thinner valley and drainage-notch lines between the ridge spines.
- Add sparse broken contour fragments that follow the whole range, not individual peaks. Contours may curve, but must not form repeated closed rings around centers.
- All lines must be nearly uniform-width antique ink strokes lying flat on paper. Use no filled dark wedges, no directional lighting, and no shaded face.
- Keep open quiet areas between line groups for future vector labels.

Forbidden mountain vocabulary:
- no triangular, pyramidal, pointed, fan-shaped, star-shaped, radial, or pictorial peak marks;
- no front face, side face, underside, cliff wall, horizon, aerial perspective, isometric projection, cast shadow, or oblique shadow;
- no repeated rings, bullseyes, craters, mandalas, center dots, center diamonds, or rows of separate mountain icons;
- no dense hatching that could read as a dark slope face.

Absolute invariants:
- Keep Image 1's exact 1536x1024 canvas and crop.
- Every pixel in BLACK areas of Image 2 is protected: coastline, islands, sea texture, delta, river, roads, bridges, city, port, forests, fields, palette, paper grain, and all non-mountain details must remain visually identical.
- Keep the black road corridors that cross the white mask identical and uninterrupted.
- Preserve the existing mountain footprint boundaries; edit only their internal relief vocabulary.
- Maintain the strict infinitely high 90-degree plan view.

Hard validation rule: The edit fails if any pictorial peak, dark slope face, repeated target, or mountain icon remains; if any black-mask feature changes; or if any text appears.

Constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, decorative border, or frame. No modern objects. No clone clusters or repeating texture.
Avoid: scenic mountains, elevation rendering, hillshade, perspective, individual peak symbols, repeated contour centers, changing roads, changing rivers, changing islands, changing city or port, changing overall density.
```
