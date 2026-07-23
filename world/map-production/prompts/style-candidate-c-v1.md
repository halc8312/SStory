---
type: "analysis"
category: "analysis"
title: "地図画風候補C 精密銅版 v1生成プロンプト"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-generation", "copperplate", "cartography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "ゴールデンスタイル候補Cの精密銅版版生成"
base_files: ["world/map-production/prompts/style-candidate-v1.md", "docs/assets/images/maps/world/world-map-hires.jpg"]
methodology: "共通仕様を固定し、高倍率の線刻密度・非反復細部・平面性を候補差分として生成"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 地図画風候補C 精密銅版 v1生成プロンプト

Built-in ImageGenへ次の内容を一回だけ送信しました。入力画像は画風・配色参照であり、編集対象ではありません。

```text
Use case: stylized-concept
Asset type: SStory high-detail fantasy map terrain style candidate C, fine copperplate deep-zoom variant.
Primary request: Create a reusable visual style reference for a finite deep-zoom fantasy map. Use the supplied existing world map only as a style and palette reference; do not copy its labels, border, title, compass, legend, or exact geography.

Scene/backdrop: One representative unlabeled terrain sheet containing a single clear coastline and muted ocean, a branching river delta, a long mountain chain, a mature forest with internal clearings, cultivated plains and field boundaries, one compact walled fantasy city, one small working port, several connected primary and secondary roads, and a few floating islands.

Style/medium: Strictly top-down orthographic hand-drawn fantasy cartography on subtle aged parchment. Prioritize exceptionally fine copperplate engraving, delicate ink contours, controlled stippling and cross-hatching, and restrained transparent watercolor washes. The result should reward inspection at high magnification while still belonging to the same handcrafted cartographic family as the supplied map.

Composition/framing: Edge-to-edge terrain without any decorative frame. Distribute the representative terrain types across the sheet so each can be inspected closely. Keep purposeful low-noise corridors around roads, settlement edges, and open plains for future crisp vector labels and POI markers.

High-magnification detail: Add varied non-repeating shoreline hatch, riverbank vegetation, tributaries, forest clearings and paths, individual field boundaries, terraces, ridgelines, scree, contour-like relief marks, city blocks, walls, gates, docks, piers, and small boats. Detail must be cartographic and plan-view, never a narrative scene. Use a disciplined line hierarchy so microscopic texture does not obscure roads, rivers, coastlines, city walls, or field boundaries.

Viewpoint and geometry: Absolute north-up, strict 90-degree top-down orthographic map. Flatten every mountain, building, port structure, and floating island into plan-view cartographic symbols and contour forms. No isometric buildings, no visible cliff side faces, no horizon, no bird's-eye perspective, no perspective jump.

Visual hierarchy: Coastline strongest. Rivers cool blue-gray with natural taper and multiple readable branches. Primary roads clean warm ochre double-lines or lightly cased paths; secondary roads thinner. Roads must stay continuously traceable and must never merge visually with rivers, contour lines, or hatching. City walls and blocks must be legible without dominating the terrain.

Lighting/mood: Even neutral illumination, no dramatic shadows, one consistent engraved hatch direction.

Color palette: Restrained antique sepia and earth tones; muted dusty blue water, desaturated olive forest, warm ochre plains, cool graphite-gray mountains, subtle rust accents in city and port. Fine ink detail remains the main visual language.

Materials/textures: Natural paper grain, precise etched lines, non-repeating marks, no tiled texture, no clone clusters. Maintain clean open paper between dense areas.

Hard constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass rose, scale bar, signature, watermark, logo, UI, decorative border, cartouche, or map frame. No modern objects. No icons resembling writing. No copied repeating trees, roofs, rocks, waves, or boats. Do not copy exact geography from the reference.

Avoid: fake writing, excessive ornament, photorealism, satellite imagery, strong vignette, muddy linework, black crushed shadows, moiré, over-dense texture, roads that disappear, rivers that look like roads, exaggerated pictorial mountains, oblique perspective, inconsistent scale.

Candidate-specific goal: Beat candidates A and B on fine non-repeating detail, engraving discipline, high-magnification interest, and strict plan-view geometry while retaining enough negative space and hierarchy for vector overlays.
```
