---
title: "poi-authoring-template"
version: "0.1.0"
created: "2026-05-08"
last_updated: "2026-05-08"
author: "halc8312"
category: "maps"
status: "draft"
---

<!-- cspell:disable -->

# POI追加依頼テンプレート

AIにPOI追加を依頼する際は、以下のテンプレートをそのまま使い、必要箇所だけを書き換えてください。

## テンプレート

```md
## POI追加依頼

対象地域:
例: アストラリス首都圏 / エリュシオン街道沿い / カオス・リア紅海砂漠

追加件数:
例: 5件

追加したいカテゴリ:
例: 宿屋、飲食店、市場、神殿、ギルド

参照すべき設定:
- world/map-data/poi-design-guidelines.md
- world/map-data/docs/poi-data-spec.md
- world/map-data/data/nodes.json
- world/map-data/data/regions.json

必須条件:
- 既存の大陸・地域・交通設定と矛盾しない
- 各POIに lore_basis を入れる
- 各POIに historical_reason を入れる
- 各POIに economic_role を入れる
- 各POIに cultural_role を入れる
- 各POIに transport_role を入れる
- 各POIに risk_context を入れる
- JSON Schema検証を通す
- world側とdocs側のpois.jsonを同期する

禁止:
- なんとなくRPGっぽい施設を追加しない
- 既存設定と矛盾する施設を追加しない
- 大量追加しすぎない
- POI IDに日本語を使わない
```

## 依頼時の補足

- 対象地域は `continent_id` / `region_id` / `nearest_node_id` が推定できる粒度で指定する
- 追加件数は最初から増やしすぎず、1回あたり 3〜8 件程度を目安にする
- 交通結節点・市場・神殿・学院など、既存設定の中核施設を優先する
- 王都や主要都市では、政治・交易・宗教・文化・交通のバランスを意識する

## 追加後の最低確認

1. `world/map-data/data/pois.json` を更新する
2. `docs/data/map/pois.json` に同期する
3. JSON構文チェックを実行する
4. Schema検証を実行する
5. Leaflet上で `focusPoi()` を確認する
6. [`poi-review-checklist.md`](./poi-review-checklist.md) でレビューする

<!-- cspell:enable -->
