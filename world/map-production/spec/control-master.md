---
type: "analysis"
category: "analysis"
title: "世界地図制御マスター仕様"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "halc8312"
tags: ["maps", "geojson", "quality-assurance", "rendering"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "EA-WORLD-1正準形状の生成制御とQA重ね合わせ"
base_files: ["world/map-production/source/landmasses.geojson", "world/map-production/source/transport-geometries.geojson"]
methodology: "正準GeoJSONの決定論的ラスタ化"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 世界地図制御マスター仕様

`render_world_master.py` の出力は、画像生成とQAで位置を比較するための制御マスターです。公開用の完成地図ではありません。

## 用途

- EA-WORLD-1の海岸線、地形、河川、交通路、集落外周を同じ座標で重ねる
- 生成画像との位置差、欠落、正典にない追加物を検出する
- 5大陸、14地域、33路線が入力へ揃っていることを機械検査する
- 同一シードから同一のPNGを再生成し、比較の基準を固定する

## 公開用ラスタとの境界

- 制御マスターの低頂点多角形、集落外周、交通線は正準入力を可視化したものです。
- `masters/` へ採用する公開ラスタは、別途画像生成とVision QAを通過させます。
- 制御マスターを公開タイルの背景画像として採用しません。
- ラスタ内へ文字、数字、凡例、装飾枠を描画しません。

## 出力

既定出力は `world/map-production/controls/world-control-v1.png` と同名のJSONです。JSONは入力ファイルのSHA-256、全ID、座標変換、固定シード、出力PNGのSHA-256を記録します。既存ファイルは上書きしません。
