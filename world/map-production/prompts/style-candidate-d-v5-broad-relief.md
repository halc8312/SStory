---
type: "analysis"
category: "analysis"
title: "地図画風候補D v5 広域面状レリーフプロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "low-frequency-relief"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補D v4の山地だけに、線や記号を伴わない広域・低周波・平面視の明度階層を追加"
base_files: ["world/map-production/candidates/style-candidate-d-v4-erase-route-marks.png", "world/map-production/controls/style-candidate-d-v5-generation-mask-v1.png", "world/map-production/controls/style-candidate-d-v5-relief-mask-v1.json", "world/map-production/qa/style-candidate-d-v4-erase-route-marks.json", "world/map-production/qa/style-candidate-d-v4-erase-route-marks-review2.json"]
methodology: "生成画素を直接採用せず、道路周囲を信号推定から除外した128px重複窓中央値を64px間隔で標本化し、粗格子3×3中央値と2セルGaussian、24px平滑化、128px大域差引き、整数場5×5中央値で低周波明度場だけを抽出して、経路トポロジー検査・地域中央値補正・最大±6階調・道路完全保護付きでD v4へ決定論的に転写"
findings: []
metrics: {"golden_threshold": 94, "candidate_attempt": 5, "inner_blur_px": 24, "outer_blur_px": 128, "maximum_luminance_delta": 6}
ratings: {}
recommendations: []
---

# 候補D v5 広域面状レリーフ

Built-in ImageGenでは画像1を唯一の編集対象、画像2を道路状の黒線を含まない山地全体の編集許可範囲として使用します。線状の尾根ガイド、断片ガイド、道路除外線は入力しません。生成結果はそのまま採用せず、画像1との差を128px重複窓の中央値へ縮約して細線・記号を捨て、64〜256px程度の低周波明度場だけを最大±6階調で画像1へ転写します。

```text
Use case: precise-object-edit.
Asset type: SStory golden fantasy map style board, Candidate D v5 broad mountain-relief substrate.

Input images:
- Image 1: sole authoritative edit target, Candidate D v4. The position, geometry, topology, edge structure, and high-frequency identity of every discrete feature are locked, including every rock, tree, field, road, city, port, coastline, river, paper-grain mark, and the forty-four repaired locations. The final pipeline may pass only an equal-channel low-frequency tint of at most six levels beneath those pixels; it may never redraw, move, blur, sharpen, or replace them.
- Image 2: aligned polygon-only edit-permission mask. WHITE and GRAY permit only the requested edgeless tonal-substrate change. BLACK is locked. The mask contains no road exclusions, ridge paths, or fragment guides. It is not geography, relief geometry, style, color, or a visible shape. Never trace, reveal, imitate, or draw its outer edge, gray transition, or two-region silhouette.

Exactly one permitted change: strengthen only the already present broad mountain-field relief signal as an inkless, edgeless, low-frequency parchment-tone field beneath the existing rocks and vegetation. Add, remove, redraw, move, replace, or reinterpret no discrete mark.

Required construction:
- Use only very broad irregular tonal variation at approximately 64-200 px visual scale and no more than about four percent contrast from adjacent parchment.
- Make the change read as an areal highland tint integrated into the paper, not as a drawn object, path, ridge symbol, or shaded mountain illustration.
- Use several overlapping asymmetric soft areas with no centerline, enclosing edge, repeated unit, regular spacing, or continuously traceable trajectory.
- Make broad massifs, intervening saddles, and gentle elevation-density hierarchy readable at 100%, while leaving all fine map symbols fully intact.
- Keep both sides of every broad form visually balanced. Use no light source, bright side, dark side, highlight-shadow pair, slope face, cast shadow, or near-versus-far side.
- Preserve the position, geometry, edge structure, and high-frequency identity of every existing small rock, tree, field, road, city, port, coastline, paper-grain detail, and ink stroke from Image 1. The new tone must visually pass beneath them without softening, redrawing, or displacing them.

Absolute prohibitions:
- No new ink line, ridge spine, crest, hatch, dash, dot, capsule, scallop, chevron, contour, ring, outline, route, boundary, river-like path, crack, root, pseudo-letter, pseudo-writing, or repeated symbol.
- No triangular peak, mountain icon, scenic range, side face, cliff wall, isometric form, three-dimensional elevation, DEM hillshade, directional shading, or perspective.
- No geometric or high-frequency change to existing rocks, trees, roads, fields, cities, ports, repaired parchment, coastline, rivers, or paper grain. Both complete rendered roads and their antialias margins are pixel-locked by the final transfer.
- No text, label, number, legend, title, compass, scale bar, signature, watermark, logo, UI, border, frame, modern object, guide color, or mask artifact.

Hard failure if the new relief can be followed as a straight, curved, winding, dashed, or closed line, route, boundary, ring, or contour at 100%; if any new discrete mark exists at 200% or 400%; if any existing feature is redrawn, moved, or softened; if either complete rendered road changes; if the mask edge or a road-parallel halo becomes visible; if a side face or directional light appears; or if the broad mountain hierarchy is still unreadable at 100%.

Constraints: exact 1536x1024 canvas, identical crop and alignment, strict 90-degree top-down projection, unchanged palette and geography, no lettering or symbols.
Avoid: paths, contours, outlines, dashes, capsules, scallops, mountain icons, pictorial peaks, hatching, repeated blobs, radial gradients, spotlighting, cloudy sky texture, vignette, blur, clone marks, and global recoloring.
```

後処理では生成画像の高周波成分を採用しません。道路周囲64pxを信号推定から除外し、128px窓の中央値を64px間隔で重ねて標本化し、粗格子へ3×3中央値と2セルGaussianを適用してから24pxで平滑化し、128pxの大域成分を引きます。北東・南東を別々に中央値0へ戻して正規化し、整数化した明度場へ5×5中央値を一度だけ適用して、地域内Q90-Q10を5〜9階調、最大絶対差を6階調へ制限します。長い直線、蛇行、閉ループ、低占有率の経路状成分は不透明部とフェザー部の低周波場から拒否し、完全な道路描画とマスク外は画像1と一致させます。不合格時は候補PNGを公開せず、成功時だけ一括確定します。
