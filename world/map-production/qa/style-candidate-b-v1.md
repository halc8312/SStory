---
type: "analysis"
category: "analysis"
title: "Map Vision QA - Style Candidate B v1"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-18"
author: "Codex Vision QA"
tags: ["map-production", "vision-qa", "image-generation", "readability"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "地図画風候補B v1の画像品質、地図可読性、採用可否"
base_files: ["world/map-production/candidates/style-candidate-b-v1.png", "world/map-production/spec/qa-policy.md"]
methodology: "Codex Visionによる原寸・領域別観察と100点採点"
findings: []
summary: "地図画風候補B v1の第一回Codex Vision QA結果です。"
---

# Map Vision QA: style-candidate-b-v1

- Image: `world/map-production/candidates/style-candidate-b-v1.png`
- Reviewer: Codex Vision QA
- First-review result: `accepted` — 94/100（採用閾値94）
- File integrity: 1536 x 1024 PNG、4,180,383 bytes、SHA-256 `4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003`

## Vision所見

候補Aより海岸、河川、道路の階層が明瞭で、道路を連続して追跡できます。都市周辺、平野、森林縁、街道沿いにはベクターラベルを置ける静かな余白があり、三角州、港、市街、農地にも高倍率で観察できる細部があります。文字、偽文字、枠、透かし、署名、明確な複製模様、内部継ぎ目は見つかりませんでした。

山と浮島は厳密な平面記号より絵画的ですが、画面内で急な視点変化はありません。本番地理では制御図とベクター形状を優先し、これらをさらに平面化します。

## 採点

| 軸 | 得点 | 満点 |
|---|---:|---:|
| 正典・地形形状との一致 | 23 | 25 |
| 親子ズームの連続性 | 14 | 15 |
| 隣接画像の継ぎ目 | 14 | 15 |
| 画風・色・線密度 | 14 | 15 |
| 縮尺相応の情報量 | 10 | 10 |
| 生成破綻・反復模様 | 9 | 10 |
| ベクター重畳時の可読性 | 10 | 10 |
| **合計** | **94** | **100** |

候補Bは現時点の首位です。候補Cとの同条件比較と、独立した第二回確認を通過するまではゴールデン画風へ遷移しません。

詳細な機械可読記録は `style-candidate-b-v1.json` を参照してください。
