---
type: "analysis"
category: "analysis"
title: "Map Style Candidates - Independent Vision QA Review 2"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Independent Codex Vision QA"
tags: ["map-production", "vision-qa", "image-generation", "style-selection"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "地図画風候補A/B/Cの独立第二回採否判定"
base_files: ["world/map-production/candidates/style-candidate-a-v1.png", "world/map-production/candidates/style-candidate-b-v1.png", "world/map-production/candidates/style-candidate-c-v1.png"]
methodology: "三候補を原寸で独立再検査し、QA方針の7軸と即時不合格ゲートで比較"
findings: []
summary: "候補Bを改訂ベースに選び、平面形状ロックだけを変更する結論です。"
---

# 独立Vision QA 第2回比較

| 順位 | 候補 | 得点 | 判定 | 主因 |
|---:|---|---:|---|---|
| 1 | B 高可読 | 89 | `revise` | 可読性は首位だが、山と浮島の側面が見える |
| 2 | C 精密銅版 | 85 | `rejected` | 線刻密度が高すぎ、斜視も残る |
| 3 | A 既存継承 | 84 | `rejected` | 道路とラベル余白が弱く、斜視も残る |

三候補とも文字、偽文字、透かし、署名、装飾枠、明確な内部継ぎ目はありません。しかし山、浮島、建築に垂直面が見えるため、「厳密な90度真上視点」の即時不合格条件を満たします。

Bの道路階層、配色、余白、密度を固定し、次の一変更だけを行います。

> Plan-view geometry lock: every feature must show only its top footprint or top surface. No front face, side face, underside, façade, vertical face, or oblique shadow may be visible.

第1回のB 94点は暫定判断として保存し、Manifestの現行判定はこの独立第2回結果へ更新しました。
