---
type: "analysis"
category: "analysis"
title: "地図画風候補B 高可読 v1生成プロンプト"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-18"
author: "Codex"
tags: ["maps", "prompt", "image-generation", "readability", "cartography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "ゴールデンスタイル候補Bの高可読版生成"
base_files: ["world/map-production/prompts/style-candidate-v1.md", "docs/assets/images/maps/world/world-map-hires.jpg"]
methodology: "共通仕様を固定し、道路階層・ラベル余白・真上視点だけを候補Aから変更"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 地図画風候補B 高可読 v1生成プロンプト

Built-in ImageGenへ次の内容を一回だけ送信しました。入力画像は画風・配色参照であり、編集対象ではありません。

```text
Use case: stylized-concept
Asset type: SStory high-detail fantasy map terrain style candidate B, high-readability variant.
Primary request: Create a reusable visual style reference for a finite deep-zoom fantasy map. Use the supplied existing world map only as a style and palette reference; do not copy its labels, border, title, compass, legend, or exact geography.

Scene/backdrop: One representative unlabeled terrain sheet containing a single clear coastline and muted ocean, a branching river delta, a mountain chain, an olive forest, cultivated plains and field patterns, one compact walled fantasy city, one small port, several clearly connected roads, and a few floating islands.

Style/medium: Strictly top-down orthographic hand-drawn cartography on subtle aged parchment, with fine ink line work, restrained watercolor fills, and controlled cross-hatching. It must feel like the same cartographic family as the supplied map while being cleaner and more readable.

Composition/framing: Edge-to-edge terrain with no decorative frame. All terrain types must be large enough for close visual inspection. Reserve calm, lightly textured corridors near major settlements, roads, and open regions so crisp vector labels and POI markers can be overlaid later.

Visual hierarchy: This is the high-readability candidate. Make coastline, rivers, and roads immediately distinguishable by line weight, color, and casing: coastlines strongest, rivers cool blue-gray with natural taper, primary roads warm light double-line or clean ochre paths, minor roads thinner. Keep roads continuously traceable and never let them merge ambiguously into rivers or contour lines. Simplify terrain marks enough to remain legible at small display sizes. Use distinct but restrained color fields for water, forest, plains, mountain, and urban areas. Maintain generous negative space without making the sheet empty.

Viewpoint and geometry: Absolute north-up, strict 90-degree top-down orthographic map. Flatten mountain and city symbols into plan-view cartographic forms; no isometric buildings, no horizon, no bird's-eye perspective, no perspective jump.

Lighting/mood: Even neutral illumination with one consistent engraved shading direction and no dramatic shadows.

Color palette: Restrained sepia and earth tones; muted dusty blue water, olive forest, warm ochre plains, cool gray mountains, slightly warmer compact city fabric.

Materials/textures: Natural non-repeating paper grain, clean non-repeating terrain marks, precise river branching, readable field boundaries, varied but restrained tree symbols.

Hard constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass rose, scale bar, signature, watermark, logo, UI, decorative border, or map frame. No modern objects. Do not invent a narrative scene. Do not place icons that resemble letters. No repeated clone clusters of trees, roofs, rocks, or waves.

Avoid: fake writing, ornate cartouches, excessive decoration, photorealism, satellite imagery, strong vignette, overly dense forest texture, overly busy city texture, muddy roads, rivers that look like roads, exaggerated mountains, oblique perspective, inconsistent scale.

Candidate-specific goal: Beat candidate A on road clarity, vector-overlay readability, quiet label corridors, and strict top-down consistency while preserving handcrafted warmth and high close-zoom detail.
```
