---
type: "analysis"
category: "analysis"
title: "Map Vision QA - Style Candidate A v1"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-18"
author: "Codex Vision QA"
tags: ["map-production", "vision-qa", "image-generation"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "地図画風候補A v1の画像品質、地図可読性、採用可否"
base_files: ["world/map-production/candidates/style-candidate-a-v1.png", "world/map-production/spec/qa-policy.md"]
methodology: "Codex Visionによる原寸・領域別観察と100点採点"
findings: []
summary: "地図画風候補A v1のCodex Vision QA結果です。"
---

# Map Vision QA: style-candidate-a-v1

- Image: `candidates/style-candidate-a-v1.png`
- Reviewer: Codex Vision QA
- Result: `revise` — 93/100（採用閾値94）
- File integrity: 1536 x 1024 PNG、4,524,948 bytes、SHA-256 `ab4af104987ebabfb3196cebcd49ddd4f935f5b169949dec89c7729b03a3700c`

## Vision所見

羊皮紙、水彩、銅版画風の線密度は一貫しており、海岸、三角州、山地、森林、農地、城塞都市、港、浮島を一枚の画面で高密度に描き分けています。AI文字、透かし、署名、明確な複製模様、内部継ぎ目は見つかりませんでした。

一方、山地と城塞都市の一部が軽い斜視表現で、厳密な真上視点から少し外れます。森林・市街の密度が高い領域はベクターラベルの余白が少なく、細い道路は河川や地形線と判別しづらい箇所があります。

## 採点

| 軸 | 得点 | 満点 | 根拠 |
|---|---:|---:|---|
| 正典・地形形状との一致 | 23 | 25 | 既存世界図の画風をよく継承。合成スタイルボードのため正典形状は未検証 |
| 親子ズームの連続性 | 14 | 15 | 色・線密度は親図と高い互換性 |
| 隣接画像の継ぎ目 | 14 | 15 | 外枠なしで拡張しやすいが、隣接合成は未実施 |
| 画風・色・線密度 | 15 | 15 | 全バイオームで非常に一貫 |
| 縮尺相応の情報量 | 10 | 10 | 微細な地物が豊富 |
| 生成破綻・反復模様 | 9 | 10 | 大きな破綻なし。密集部は本番縮尺で再確認が必要 |
| ベクター重畳時の可読性 | 8 | 10 | 道路階層とラベル余白に改善余地 |
| **合計** | **93** | **100** | **候補B/Cとの比較後に再判定** |

## 必須修正

1. 道路を明瞭化し、河川・地形線との視覚階層を分ける。
2. ラベルとPOIのための静かな余白回廊を確保する。
3. 山地と城塞都市をより厳密な真上視点へ寄せる。
4. 採用候補では制御図重畳、隣接合成、デスクトップ、モバイル表示を検証する。

詳細な機械可読記録は `style-candidate-a-v1.json` を参照してください。
