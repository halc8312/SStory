---
type: "analysis"
category: "analysis"
title: "地図画風候補B v2 平面形状ロック編集プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "plan-view", "cartography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補B v1の道路階層・配色・余白を固定し、斜視表現だけを平面化"
base_files: ["world/map-production/candidates/style-candidate-b-v1.png", "world/map-production/qa/style-candidate-b-v1-review2.json"]
methodology: "独立第二回QAで検出した即時不合格に対し、一度に一変更だけを適用"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 候補B v2 平面形状ロック

Built-in ImageGenでは画像1を編集対象とし、次の単一変更だけを指示します。

```text
Use case: precise-object-edit
Asset type: SStory golden fantasy map style board, candidate B v2.
Input images: Image 1 is the edit target, candidate B v1.

Primary request: Change only the projection of every vertically raised feature into a strict 90-degree plan-view cartographic footprint. Preserve everything else.

Single targeted change — plan-view geometry lock:
- Mountains and cliffs: replace every pictorial peak and visible slope face with top-down contour rings, ridgeline traces, hachures contained inside the footprint, scree dots, and plan-view relief marks. No mountain front faces or side faces.
- Floating islands: show only their top footprints/top surfaces as separated plan-view land shapes with a thin neutral cartographic halo if needed. Remove every hanging rock, underside, cliff face, side wall, and drop shadow.
- Walled city, buildings, towers, gates, and port: show only roof footprints, wall footprints, courtyards, streets, piers, and top surfaces. Remove every façade, front face, side face, tower wall, oblique roof, and perspective projection.
- Lighting: use flat internal hatching only. No cast shadows and no oblique shadows.

Invariants — keep unchanged:
- exact canvas, crop, coastline, river, delta branches, roads, road hierarchy, bridges, fields, forest distribution, city location and footprint, port location and footprint, floating-island top footprints, color palette, paper grain, ink line weights, negative-space corridors, overall density, and restrained watercolor character;
- keep candidate B's clearly distinguishable coastline, blue-gray rivers, warm cased roads, quiet label corridors, and handcrafted warmth;
- do not move, add, remove, or rename any geographic feature other than replacing its visual projection as specified.

Hard validation rule: The image must look like it was viewed from infinitely high directly above at exactly 90 degrees. If any front face, side face, underside, façade, vertical wall surface, horizon, isometric form, or oblique shadow is visible anywhere, the edit has failed.

Constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, decorative border, or frame. No modern objects. No clone clusters or repeating texture.
Avoid: redesigning the map, changing composition, adding landmarks, changing roads or rivers, increasing density, reducing label space, pictorial mountains, visible island undersides, isometric buildings, oblique perspective.
```
