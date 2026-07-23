---
type: "analysis"
category: "analysis"
title: "地図画風候補E v2 南東プレート明度幅補正"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-generation", "low-frequency-relief", "substrate"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補E v1の独立低周波プレートで不足した南東フィールドの明度幅だけを強める"
base_files: ["world/map-production/candidates/style-candidate-e-v1-independent-relief-plate-raw.png", "world/map-production/controls/style-candidate-e-v2-relief-mask-v1.json"]
methodology: "候補E v1を編集対象にし、x=48-100%, y=74-100%の南東フィールドだけで既存の広域明暗ゾーンを強める。北東を含む残りのキャンバス、ゾーン形状、尺度、滑らかさ、色相を維持し、候補E v1と同一の決定論的転写ゲートで評価する"
findings: []
metrics: {"golden_threshold": 94, "candidate_series": 5, "candidate_attempt": 2, "target_south_east_q10_min": 105, "target_south_east_q10_max": 109, "target_south_east_q90_min": 141, "target_south_east_q90_max": 145, "required_input_q90_q10_min": 31, "required_input_q90_q10_max": 40, "maximum_final_luminance_delta": 6}
ratings: {}
recommendations: []
---

# 候補E v2 南東プレート明度幅補正

候補E v1は北東フィールドの入力Q90-Q10が33階調で合格した一方、南東は17階調しかなく、31–40階調の契約を満たしませんでした。候補E v2で変えるのは南東フィールドの既存広域明暗ゾーンの振幅だけです。地図へ転写する形状、最大±6階調、道路保護、マスク、帯域、線状トポロジー、高周波、四象限の各ゲートは変えません。

~~~text
Use case: precise-object-edit.
Asset type: standalone low-frequency luminance plate for deterministic fantasy-map relief transfer.

Input image:
- Image 1 is the exact 1536x1024 Candidate E v1 scalar luminance plate and is the edit target.

Primary request:
- Change only the amplitude of the existing broad tonal variation in the south-east coordinate field, approximately x=48-100% and y=74-100%.
- Preserve the entire canvas outside that south-east field, especially the already-valid north-east field, as closely as possible in position, scale, median luminance, color, and smoothness.
- Do not add a new visual structure. Reuse the existing south-east broad masses and only deepen their broad dark zones and lift their broad light zones.

South-east numeric target:
- Keep the south-east regional median near the existing neutral value, approximately 124-127.
- Make the south-east opaque-core Q10 approximately 105-109 and Q90 approximately 141-145, so every allowed endpoint pair keeps Q90-Q10 within 32-40 luminance levels.
- Achieve the range with balanced positive and negative changes, not a one-sided wash.
- Keep all tonal masses broad at approximately 160-320 px scale with edgeless 64-80 px transitions.
- Every quadrant of the south-east field must retain part of a broad positive or negative zone; no quadrant may be flat.

Locked invariants:
- Exact 1536x1024 landscape raster; no crop, padding, border, or transparency.
- Preserve the north-east field's existing broad tonal layout and input range; do not strengthen, weaken, move, redraw, or reinterpret it.
- Preserve the left side and the entire upper 74% of the plate as closely as possible.
- Keep red, green, and blue channels equal or nearly equal; no new hue variation.
- Keep the image a flat two-dimensional scalar substrate with no light source, direction, near side, far side, highlight, or shadow.

Absolute prohibitions:
- No map, coastline, river, road, route, boundary, contour, ridge spine, crest, line, stroke, hatch, dash, dot, capsule, ring, outline, crack, root, or trajectory.
- No mountain, triangular peak, rock, tree, field, building, city, object, symbol, letter, number, label, pseudo-writing, watermark, logo, UI, border, or frame.
- No perspective, horizon, terrain scene, three-dimensional surface, side face, cliff, hillshade, directional lighting, cast shadow, bevel, embossing, or isometric form.
- Do not introduce any new radial gradient, spotlight, vignette, cloud, smoke, marble vein, fabric fold, repeated blob, tiling pattern, paper fiber, grain, speckle, scratch, or high-frequency texture.
- The input already contains faint cloudy and repeated diffuse variation. Outside the south-east amplitude change, leave those residual shapes and positions unchanged; do not sharpen, multiply, move, redraw, or reinterpret them.
- No visible edge around any tonal mass and no continuously traceable bright or dark path at 100%.

Quality target:
- At 100%, only the south-east broad tonal amplitude is stronger; no new object or path is readable.
- At 200% and 400%, no new discrete mark, line, repeated unit, edge, or texture appears, and no pre-existing residual becomes sharper.
- The north-east field remains visually unchanged and its Q90-Q10 remains within 31-40 levels.
- The south-east field reaches Q90-Q10 of 31-40 levels while retaining several overlapping asymmetric zones.
- No text, signature, watermark, crop, padding, border, or transparency.
~~~

生成結果の画素は地図へ直接コピーしません。候補E v1と同じ低周波抽出・地域中心化・等色量子化・道路保護・原子公開を通し、全ゲート合格時だけ候補D v4へ最大±6階調で転写します。中間プレートに残る既存の雲状残差は採用根拠にせず、最終転写場の高周波・線状トポロジー・四象限ゲートで除去または却下します。
