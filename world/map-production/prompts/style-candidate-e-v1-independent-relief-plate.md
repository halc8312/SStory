---
type: "analysis"
category: "analysis"
title: "地図画風候補E v1 独立低周波レリーフプレート"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-generation", "low-frequency-relief", "substrate"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "詳細地図を編集せず、候補D v4へ決定論的に転写するための広域・無輪郭・低周波な明度場だけを独立生成"
base_files: ["world/map-production/candidates/style-candidate-d-v4-erase-route-marks.png", "world/map-production/controls/style-candidate-e-v1-relief-mask-v1.json", "world/map-production/qa/automated/style-candidate-d-v5-rejection-audit.json"]
methodology: "ImageGenには地図ではなく1536x1024の特徴物を持たない明度プレートだけを生成させ、候補D v4を差し引かずプレートの地域中心化輝度だけを信号として、128px重複窓中央値、粗格子3×3中央値、2セルGaussian、24px/128px band-pass、地域別正規化、整数場5×5中央値、経路トポロジー検査を通った等色低周波場だけを候補D v4へ最大±6階調で転写"
findings: []
metrics: {"golden_threshold": 94, "candidate_series": 5, "candidate_attempt": 1, "minimum_raw_q90_q10_percent": 12, "maximum_raw_q90_q10_percent": 16, "maximum_final_luminance_delta": 6}
ratings: {}
recommendations: []
---

# 候補E v1 独立低周波レリーフプレート

候補D v5では詳細地図の編集を要求したため、ImageGenが地図全体を再合成した一方、必要な広域明度差は北東2階調・南東1階調しか残りませんでした。候補E v1で変えるのは生成入力の意味だけです。地図画像もマスク画像も入力せず、地物・記号・線を一切持たない独立した低周波明度プレートを生成します。E専用制御は候補D v4を信号から差し引かず、プレートの地域中央値を引いた輝度だけを読みます。最終的な地図上の変更、マスク形状、道路保護、範囲、最大階調、採用ゲートは候補D v5から変えません。

~~~text
Use case: generate.
Asset type: standalone low-frequency luminance plate for deterministic fantasy-map relief transfer.

Create a brand-new exact 1536x1024 landscape raster. This is not a map, landscape scene, illustration, mask, height-map rendering, or finished artwork. It is only a flat two-dimensional scalar luminance substrate.

Required canvas:
- Use a nearly uniform neutral warm-gray base.
- Keep the red, green, and blue channels equal or nearly equal; hue variation is unnecessary.
- Across the full canvas, create only very broad irregular tonal variation at approximately 160-320 px scale. This intermediate plate is intentionally stronger than the final map: within each right-side field its input-plate Q90-Q10 luminance span must be 31-40 levels, approximately 12-16%, while the deterministic transfer will normalize the adopted result to at most six levels.
- In the upper-right field, approximately x=55-100% and y=0-62%, form one continuous asymmetric scalar field with one dominant broad tonal zone, 2-4 subordinate overlapping zones, and transitions 64-80 px wide. The variation must cover at least 70% of that field without implying physical terrain.
- In the lower-right field, approximately x=48-100% and y=74-100%, form a different continuous asymmetric scalar field with one dominant broad tonal zone, 2-4 subordinate overlapping zones, and transitions 64-80 px wide. The variation must cover at least 70% of that field without implying physical terrain.
- Every quadrant of each right-side coordinate field must contain part of a broad positive or negative tonal zone; no quadrant may remain flat.
- Let every mass extend softly beyond those coordinate windows so no rectangular, polygonal, mask-like, or clipped boundary is visible.
- Use balanced positive and negative tonal variation around the same neutral median. There is no light source, direction, near side, far side, highlight, or shadow.

Absolute prohibitions:
- No map, coastline, river, road, route, boundary, contour, ridge spine, crest, line, stroke, hatch, dash, dot, capsule, ring, outline, crack, root, or trajectory.
- No mountain icon, triangular peak, rock, tree, field, building, city, port, bridge, wall, object, symbol, letter, number, label, pseudo-writing, watermark, logo, UI, border, or frame.
- No perspective, horizon, scenic terrain, three-dimensional surface, side face, cliff, hillshade, directional lighting, cast shadow, bevel, embossing, or isometric form.
- No radial gradient, spotlight, vignette, cloudy sky, smoke, marble veins, fabric folds, repeated blobs, tiling pattern, paper fibers, grain, speckles, scratches, or high-frequency texture.
- No visible edge around any tonal mass and no continuously traceable bright or dark path at 100%.

Quality target:
- At 100%, the plate reads only as quiet, broad, edgeless areal variation.
- At 200% and 400%, no discrete mark, line, repeated unit, edge, or texture appears.
- The two right-side coordinate fields each retain several overlapping broad tonal zones rather than one flat wash or one radial gradient.
- The input-plate Q90-Q10 luminance span inside each right-side field is 31-40 levels, approximately 12-16%; this is an intermediate signal target, not the final map contrast.
- Exact 1536x1024 canvas; no crop, padding, border, text, signature, or transparency.
~~~

生成結果の画素は地図へ直接コピーしません。E専用転写モードは候補D v4を差し引かず、プレートの地域中心化輝度だけから低周波の等色明度場を抽出し、候補D v5と同一形状の北東・南東マスク内へ最大±6階調で適用します。道路の完成描画とマスク外は候補D v4と画素一致させます。入力プレート幅、必要信号、線状トポロジー、四象限、高周波残差、道路差、範囲外差のいずれかが不合格なら成果物を公開しません。
