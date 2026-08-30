---
type: "analysis"
category: "analysis"
title: "地図画風候補B v3 山岳レリーフ編集プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mountains", "cartography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補B v2の平面性と全構図を固定し、山岳の反復記号だけを自然な平面レリーフへ置換"
base_files: ["world/map-production/candidates/style-candidate-b-v2-plan-view.png", "world/map-production/qa/style-candidate-b-v2-plan-view.json"]
methodology: "Vision QAで検出したrepetition即時不合格に対し、一度に一変更だけを適用"
findings: []
metrics: {"parent_score": 84, "golden_threshold": 94, "attempt": 3}
ratings: {}
recommendations: []
---

# 候補B v3 山岳レリーフ修正

Built-in ImageGenでは画像1を編集対象とし、次の単一変更だけを指示します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, candidate B v3.
Input image: Image 1 is the sole edit target, candidate B v2 plan view.

Primary request: Change ONLY the cartographic drawing inside the existing mountain and hill footprints. Replace the repeated bullseye mountain symbols with natural, irregular, connected top-down relief. Preserve every non-mountain feature and the strict 90-degree plan view exactly.

Single targeted change — mountain relief vocabulary:
- Remove every isolated concentric circle, centered dot, central diamond, target, crater-chain, mandala, and repeated ring symbol from all mountain and hill areas.
- Within the SAME existing mountain footprints, draw irregular connected ridgelines that branch and merge; varied saddles and passes; short valley and drainage notches; broken, nonconcentric contour fragments; unevenly spaced hachures that follow slope direction; sparse scree and rock stipple.
- Make each range read as one coherent landform network rather than a row of separate volcanoes or icons.
- Vary ridge length, curvature, spacing, hatching density, and junction shape organically. No two mountain units may share the same internal pattern.
- Keep relief subtle enough that future vector labels and route lines remain legible.

Absolute invariants — do not change these pixels or semantics except where mountain marks directly overlap:
- exact 1536x1024 canvas, crop, coastline, all islands and floating-island top footprints, sea texture, river and delta branches, every road and bridge, city and port geometry, forests, fields, palette, paper grain, ink weights, negative-space corridors, overall detail density, and watercolor character;
- keep the candidate B v2 city, port, roads, river, coastline, floating-island treatment, and all non-mountain terrain exactly as they are;
- do not move, enlarge, shrink, add, or remove any mountain footprint; change only its internal relief marks;
- retain the strict infinitely high 90-degree overhead view. Show no front face, side face, underside, facade, vertical wall, horizon, isometric form, cast shadow, or oblique shadow.

Hard validation rule: If any concentric target-like mountain symbol remains, if a new repeated motif appears, if any non-mountain feature changes, or if any perspective/side face returns, the edit has failed.

Constraints: No text, letters, numbers, labels, pseudo-writing, legend, title, compass, scale bar, signature, watermark, logo, UI, decorative border, or frame. No modern objects. No clone clusters or repeating texture.
Avoid: volcano icons, bullseyes, contour targets, isolated circular hills, diamonds at ridge centers, pictorial mountain peaks, redesigning the map, moving geography, changing floating-island semantics, changing roads or rivers, changing city or port, increasing overall density, reducing label space.
```
