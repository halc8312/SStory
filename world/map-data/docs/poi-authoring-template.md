---
title: "poi-authoring-template"
version: "0.2.0"
created: "2026-05-08"
last_updated: "2026-05-09"
author: "halc8312"
category: "maps"
status: "draft"
---

<!-- cspell:disable -->

# POI追加依頼テンプレート

AIエージェントにPOI追加を依頼する際は、このテンプレートか
GitHub Issue Form を使って、対象地域・件数・参照設定・禁止事項を明示してください。

関連資料:

- [`../poi-design-guidelines.md`](../poi-design-guidelines.md)
- [`./poi-data-spec.md`](./poi-data-spec.md)
- [`./poi-ai-addition-workflow.md`](./poi-ai-addition-workflow.md)
- [`./poi-review-checklist.md`](./poi-review-checklist.md)

## 依頼テンプレート

```md
## POI追加依頼

対象地域:
例: アストラリス首都圏 / エリュシオン中央街道沿い / ポートゼフィア港湾区

追加件数:
例: 5件

追加したいカテゴリ:
例: 宿屋、飲食店、市場、神殿、ギルド

追加したい雰囲気・役割:
例: 王都近郊の旅人・巡礼者・商人を支える、秩序ある街道施設群

参照必須:
- world/map-data/poi-design-guidelines.md
- world/map-data/docs/poi-data-spec.md
- world/map-data/data/nodes.json
- world/map-data/data/regions.json
- world/map-data/data/continents.json

近くの交通ノード:
例: astralis / astralis_carriage_plaza / 中央街道西門

必須条件:
- 既存の大陸・地域・交通設定と矛盾しない
- 各POIに lore_basis を入れる
- 各POIに historical_reason を入れる
- 各POIに economic_role を入れる
- 各POIに cultural_role を入れる
- 各POIに transport_role を入れる
- 各POIに risk_context を入れる
- world/map-data/data/pois.json を編集する
- docs/data/map/pois.json へ同期する
- JSON構文チェックとSchema検証を通す
- Leaflet上で focusPoi() を確認する

禁止:
- なんとなくRPGっぽい施設を追加しない
- 既存設定と矛盾する施設を追加しない
- 地域の歴史・交通と無関係な大型施設を追加しない
- POI IDに日本語を使わない

備考:
例: 今回は街道沿いの旅客・巡礼需要を優先し、王宮近辺の高機密施設は対象外
```

## 依頼例

### 良い依頼例

> エリュシオンのアストラリスからポートゼフィアへ向かう街道沿いに、
> 宿場・小市場・巡礼者向け神殿を合計5件追加してください。
> 中央街道、王都交通、エリュシオンの秩序ある交易圏という設定と矛盾しないようにしてください。
> 各POIには lore_basis, historical_reason, economic_role, cultural_role, transport_role, risk_context を必ず入れてください。

良い点:

- 対象地域が明確
- 件数上限が明確
- カテゴリと役割が具体的
- 参照すべき世界観・交通設定が読める
- 必須フィールドと検証条件が明示されている

### 悪い依頼例

> 適当に面白そうな店を50個追加してください。

悪い点:

- 対象地域が不明
- 件数が多すぎる
- 既存設定との整合条件がない
- 交通・歴史・経済・文化との接続がない
- AIが「雰囲気だけ」で量産しやすい

## AIエージェントへの明示的な禁止事項

- 依頼範囲を超える大量追加をしない
- 「なんとなくRPGっぽい」だけの施設を追加しない
- `continent_id` / `region_id` / `nearest_node_id` を推測だけで埋めない
- 既存POIと役割・座標・名称が重複する施設を増やさない
- 交通・歴史・政治・宗教・危険文脈と無関係な大型施設を置かない
- `world/map-data/data/pois.json` だけ更新して `docs/data/map/pois.json` を放置しない
- JSON構文チェック、Schema検証、Leaflet確認を省略しない

## 追加件数の上限目安

- 小規模依頼: 1〜3件
- 標準依頼: 3〜8件
- 多めの依頼: 8〜10件まで
- 10件超の依頼は分割を推奨

特に新規地域での初回投入は、少数から始めてレビューしながら拡張してください。

## 地域ごとの参照ファイル

- 全件共通:
  - `world/map-data/poi-design-guidelines.md`
  - `world/map-data/docs/poi-data-spec.md`
  - `world/map-data/data/continents.json`
  - `world/map-data/data/regions.json`
  - `world/map-data/data/nodes.json`
- エリュシオン主要都市・街道:
  - `world/transportation/land-transportation.md`
  - `world/transportation/stations-and-terminals.md`
- 港湾・海路沿い:
  - `world/transportation/sea-routes.md`
- 空路・浮島関連:
  - `world/transportation/air-transportation.md`
  - `world/transportation/sky-routes.md`
- 追加先が危険地域に近い場合:
  - `world/map-data/data/hazards.json`

## 出力後の検証チェック

1. 依頼件数を超えていないか確認する
2. 既存POIとID・名前・役割・座標が過度に重複していないか確認する
3. `world/map-data/data/pois.json` を更新する
4. `python world/map-data/scripts/sync_pois_to_docs.py` で docs 側へ同期する
5. `python -m json.tool world/map-data/data/pois.json` を実行する
6. `python -m json.tool docs/data/map/pois.json` を実行する
7. `python -m json.tool world/map-data/schemas/poi.schema.json` を実行する
8. `python world/map-data/scripts/validate_pois.py` を実行する
9. Leaflet上で `focusPoi()` を確認する
10. [`poi-review-checklist.md`](./poi-review-checklist.md) でレビューする

<!-- cspell:enable -->
