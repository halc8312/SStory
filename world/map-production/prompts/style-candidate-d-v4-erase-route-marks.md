---
type: "analysis"
category: "analysis"
title: "地図画風候補D v4 破線状マーク消去プロンプト"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Codex"
tags: ["maps", "prompt", "image-edit", "mask", "artifact-removal"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "候補D v3で目視確定した44個の濃色二重輪郭マークだけを消去し、直下の紙面を復元"
base_files: ["world/map-production/candidates/style-candidate-d-v3-detached-fragments.png", "world/map-production/controls/style-candidate-d-v3-mark-mask-v1.png", "world/map-production/qa/style-candidate-d-v3-detached-fragments.json", "world/map-production/qa/style-candidate-d-v3-detached-fragments-review2.json"]
methodology: "D v3差分候補を原寸・400%で全件分類し、木の誤検出1件を除外、未検出5件を追加した明示allowlistマスクで破線状アーティファクトだけを一回変更"
findings: []
metrics: {"golden_threshold": 94, "candidate_attempt": 4, "reviewed_target_marks": 44, "replacement_marks": 0}
ratings: {}
recommendations: []
---

# 候補D v4 破線状マーク消去

画像1を唯一の編集対象、画像2を原寸・400%で目視確認した44個の濃色マークだけを囲む狭域編集マスクとして使います。生成後は画像2と同じマスクで画像1へ決定論的に再合成し、マスク外を画像1のまま画素固定します。

```text
Use case: precise-object-removal.
Asset type: SStory golden fantasy map style-board intermediate, Candidate D v4 route-like mark removal.

Input images:
- Image 1: sole authoritative edit target, Candidate D v3. Its 1536x1024 canvas, crop, geography, paper, palette, broad relief substrate, roads, city, port, fields, vegetation, rocks, and all other content are locked.
- Image 2: aligned reviewed mask enumerating all forty-four visually verified unwanted route-like marks. Each reviewed target has an opaque white core covering the mark and its one-to-two-pixel antialias area; neighboring cores or outer feathers may overlap, so the raster is not required to contain forty-four disconnected components. A narrow gray feather exists only outside each core. BLACK is locked. The mask is control data only; never draw its gray values, edge, shape, blur, or boundary. The reviewed control explicitly excludes the tree false positive and includes five visually verified omissions.

Exactly one permitted change: completely erase every visually verified dark double-outline capsule-like mark enumerated by Image 2 and restore only the parchment and faint natural terrain texture that would continue beneath it. Add no replacement crest, hatch, dash, line, dot, contour, symbol, or other mark.

Removal contract:
- Process every one of the forty-four reviewed target cores exactly once. After the edit, zero dark capsules and zero replacement marks remain inside those targets.
- Remove both dark edges and the pale enclosed center of each capsule, including at most its one-pixel antialias ring.
- Reconstruct the tiny covered area only by continuing the immediately adjacent paper grain and faint pre-existing terrain texture across the gap. Use the nearest 1-3px perimeter as the sole texture and color authority.
- Do not smooth, blur, brighten, darken, recolor, shade, or repaint the broader mask neighborhood.
- At 100%, 200%, and 400%, no residual rhythm may read as a dashed road, travel route, administrative boundary, pseudo-writing, repeated symbol, or continuous trajectory.

Absolute invariants:
- Preserve every pixel outside the reviewed mask alpha support for all forty-four targets from Image 1.
- Preserve the broad tonal mountain footprints already present in Image 1; this attempt removes only the route-like ink artifacts and does not strengthen or redesign mountain relief.
- Preserve all small natural rocks, trees, fields, coastlines, sea texture, rivers, deltas, actual roads, bridges, cities, ports, and negative-space corridors.
- Keep both protected roads continuous, visually primary, and unobstructed.
- Preserve strict 90-degree top-down projection with no directional lighting, side face, summit silhouette, or cast shadow.

This attempt deliberately does not claim the missing 30-crest/10-hatch role grammar. Automated extraction returned forty candidates but included one tree and omitted five route-like marks; the reviewed authority is therefore the explicit forty-four-target allowlist rather than an accidental detection count. Inventing roles after generation is forbidden. A later attempt may change broad relief as a separate single change only after this artifact-removal result is visually reviewed.

Hard failure if any dark capsule, outline, hollow center, replacement mark, repeated stamp, or mask edge remains; if the local repair becomes visibly blurred or cloned; if the broad relief substrate is repainted; or if any non-target feature changes.

Constraints: no text, letters, numbers, pseudo-writing, labels, legend, title, compass, scale bar, signature, watermark, logo, UI, border, frame, modern object, new landmark, control color, or mask artifact.
Avoid: dashed routes, road symbols, administrative boundaries, capsules, outlined pills, hollow marks, new hatches, new crests, contour rings, scenic mountains, pictorial peaks, side-view relief, isometric form, dense hatching, tubes, trenches, channels, cracks, rivers, roots, and repeating texture.
```
