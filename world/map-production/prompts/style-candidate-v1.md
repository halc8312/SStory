---
type: "analysis"
category: "analysis"
title: "地図画風候補生成プロンプト"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-18"
author: "halc8312"
tags: ["maps", "prompt", "image-generation", "style", "cartography"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "ゴールデンスタイル候補の生成"
base_files: ["world/map-production/spec/style-bible.md", "docs/assets/images/maps/world/world-map-hires.jpg"]
methodology: "同一要件から三つの画風候補を個別生成し、Vision QAで比較"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 地図画風候補生成プロンプト

## 共通仕様

```text
Use case: stylized-concept
Asset type: SStory high-detail fantasy map terrain style candidate
Primary request: Create a reusable visual style reference for a finite deep-zoom fantasy map.
Input images: Image 1 is a style reference only; do not copy its labels, border, title, compass, legend, or exact geography.
Scene/backdrop: A representative unlabeled terrain sheet containing one coastline, ocean, river delta, mountain chain, forest, cultivated plain, walled fantasy city, small port, and a few floating islands.
Style/medium: Strictly top-down orthographic hand-drawn cartography on subtle aged parchment.
Composition/framing: Edge-to-edge terrain without a decorative frame. All terrain types must be large enough for close visual inspection.
Lighting/mood: Even neutral illumination with one consistent engraved shading direction.
Color palette: Restrained sepia and earth tones; muted dusty blue water, olive forest, warm ochre plains, cool gray mountains.
Materials/textures: Fine ink line work, restrained cross-hatching, natural paper grain, non-repeating terrain marks.
Constraints: No text, letters, numbers, labels, legend, title, compass rose, scale bar, signature, watermark, UI, or border. No perspective view. No modern objects. Do not invent a narrative scene. Keep roads, rivers, and coastlines visually distinct.
Avoid: fake writing, symbols resembling writing, excessive ornament, copied repeating trees or buildings, photorealism, satellite imagery, strong vignette, dramatic lighting.
```

## 候補差分

- A 既存継承: 既存世界図に近い柔らかな彩色と古地図の温度感
- B 高可読: 色面と線を整理し、小さい表示でも地形を判別しやすくする
- C 精密銅版: 線刻と細部を増やし、高倍率で観察できる密度を優先する

候補は別々の画像生成呼び出しで作り、共通仕様を変更せず差分だけを追加します。
