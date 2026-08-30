---
type: "analysis"
category: "analysis"
title: "高精細地図品質保証方針"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-21"
author: "halc8312"
tags: ["maps", "quality-assurance", "vision", "tiles", "validation"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "生成画像、メタタイル、公開地図の採否判定"
base_files: ["world/map-production/spec/style-bible.md"]
methodology: "形状検査、隣接比較、原寸視覚確認、実ブラウザ確認"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# 高精細地図品質保証方針

## 採点

| 評価軸 | 点数 |
| --- | ---: |
| 正典と地形形状の一致 | 25 |
| 親子ズームの連続性 | 15 |
| 隣接画像の継ぎ目 | 15 |
| 画風、色、線密度の統一 | 15 |
| 縮尺に合う情報量 | 10 |
| 生成破綻と反復模様の少なさ | 10 |
| ベクター重畳時の可読性 | 10 |

- 90 点以上: `accepted`
- 82〜89 点: `revise`
- 81 点以下: `rejected`
- ゴールデンタイルと新しい生態域の最初の画像: 94 点以上かつ独立した二回の確認

## Golden 証拠契約

Golden 候補は、通常の採点に加えて次をすべて満たす場合だけ `accepted` にできます。

- 二つの Vision QA JSON はどちらも `review_mode: "blind-independent"` とし、空白と大文字小文字を正規化した reviewer 名が互いに異なること
- 二つの JSON が `image_path` だけでなく、manifest の master と同じ `image_sha256` を記録すること
- 各レビューが個別に 94 点以上で、全 review view が完了し、即時不合格がゼロであること。一方の点数で他方を補完しないこと
- 生成直後の raw と最終 PNG は別パスに保存し、SHA-256 と実バイトが一致すること
- TEMP receipt、TEMP contact sheet、自動検査、自己レビューは独立 Vision QA の回数に数えないこと

`94` 点しきい値や二回確認だけで `golden_reference` にはなりません。Direct17 などの通常 master は `golden_reference: false` のまま、同じ exact `image_sha256` と `blind-independent` の証拠契約を満たします。`golden_reference: true` は、manifest が選択した Golden master そのもののレビューだけに使用します。

永続化は二段階で行います。第1段階は TEMP 入力をバイト固定し、追跡可能なパスだけを持つ receipt と自動検査を作り、manifest を `automated-qa` で停止します。この段階に採用権限はありません。第2段階は上記二つの永続 Vision QA JSON を再検証し、初めて `vision-qa`、`accepted` の順で記録します。第2段階が失敗した場合、manifest は `automated-qa` 以前に留めます。

## 即時不合格

- 海岸線、河川、主要道路、城壁の大きな移動
- 必須地点の欠落、または正典外の主要地点の追加
- 読める文字、偽文字、透かし、署名、装飾枠
- 100% 表示で認識できる継ぎ目
- 遠近法化、縮尺や光源の急変
- 現代物または不自然な反復模様

## 自動検査の初期目標

- 陸海制御マスクとの一致率: 0.98 以上
- 海岸、河川、道路の 95%: 制御線から 8 px 以内
- 隣接重複領域の構造類似度: 0.90 以上
- 色差の平均: 4 以下、95 パーセンタイル: 10 以下
- 512 px WebP: 平均 220 KB 以下、95 パーセンタイル 350 KB 以下

数値はゴールデン縦断の実測結果で再調整します。ノード、POI、ルートの位置精度は生成画像ではなくベクター層で保証します。

## Vision QA

候補ごとに次を確認します。

1. 全体像
2. 原寸、200%、400%
3. 中央、四隅、四辺の九領域
4. 制御図を半透明で重ねた比較
5. 親画像との並列比較
6. 四方向の隣接合成
7. ラベル、道路、POI を重ねた実表示
8. デスクトップとモバイルの Leaflet 表示

結果には点数、`PASS` / `REVISE` / `REJECT`、問題座標、重要度、次の一変更だけを記録します。Golden の結果には、確認した画像の SHA-256 と review mode も記録します。

## 再試行

一つのメタタイルにつき最大五回です。

1. 初回生成
2. 局所修正一回目
3. 局所修正二回目
4. 制御図からの再生成
5. 新候補の局所修正

同じ欠陥が二回続いた場合は画像編集を止め、制御図またはプロンプトを修正します。隣接三枚以上で同じ欠陥が出た場合は、そのバッチを停止します。
