---
title: "poi-ai-addition-workflow"
version: "0.1.0"
created: "2026-05-09"
last_updated: "2026-05-09"
author: "halc8312"
category: "maps"
status: "draft"
---

<!-- cspell:disable -->
<!-- markdownlint-disable MD025 -->

# AI向けPOI追加ワークフロー

この文書は、AIエージェントが `pois.json` にPOIを追加する際の標準手順を定義します。
目的は、世界観・歴史・交通設定と矛盾しない形で、追加・同期・検証・レビューを毎回同じ流れで行うことです。

## 事前原則

- 新規POIを「雰囲気だけ」で量産しない
- Issueまたは依頼文の対象地域・件数・禁止事項を守る
- `world/map-data/data/pois.json` を正とし、`docs/data/map/pois.json` を必ず同期する
- 根拠フィールドを省略しない
- 検証とLeaflet確認を省略しない

## 標準手順

1. `world/map-data/poi-design-guidelines.md` を読む
2. `world/map-data/docs/poi-data-spec.md` を読む
3. 対象地域の `continent_id` / `region_id` / `nearest_node_id` を、`continents.json` / `regions.json` / `nodes.json` で確認する
4. `world/map-data/data/pois.json` を確認し、既存POIと重複しないか調べる
5. 依頼に書かれた追加件数を守る
6. 各POIに `lore_basis` / `historical_reason` / `economic_role` / `cultural_role` / `transport_role` / `risk_context` を書く
7. `world/map-data/data/pois.json` を編集する
8. `python world/map-data/scripts/sync_pois_to_docs.py` を実行して `docs/data/map/pois.json` へ同期する
9. `python -m json.tool world/map-data/data/pois.json` と `python -m json.tool docs/data/map/pois.json` を実行して JSON 構文チェックを行う
10. `python world/map-data/scripts/validate_pois.py` を実行して Schema 検証・参照整合・同期確認を行う
11. Leaflet上で `focusPoi()` を使って表示確認を行う
12. [`poi-review-checklist.md`](./poi-review-checklist.md) でレビューする

## 参照ファイルの確認順

最初に最低限読むべきファイル:

- `world/map-data/poi-design-guidelines.md`
- `world/map-data/docs/poi-data-spec.md`
- `world/map-data/docs/poi-authoring-template.md`
- `world/map-data/data/continents.json`
- `world/map-data/data/regions.json`
- `world/map-data/data/nodes.json`
- `world/map-data/data/pois.json`

必要に応じて追加で参照するファイル:

- `world/transportation/land-transportation.md`
- `world/transportation/sea-routes.md`
- `world/transportation/air-transportation.md`
- `world/transportation/sky-routes.md`
- `world/transportation/stations-and-terminals.md`
- `world/map-data/data/hazards.json`

## 追加前チェック

- 対象地域が曖昧な場合は、先に依頼内容を明確化する
- 同じ地域に近すぎる座標でPOIを過密配置しない
- 既存POIと似すぎた役割や名称を避ける
- 交通ノードとの接続理由が説明できない施設は追加しない
- 地域の歴史・文化・宗教・危険文脈を説明できない施設は追加しない

## 同期と検証コマンド

```bash
python world/map-data/scripts/sync_pois_to_docs.py
python -m json.tool world/map-data/data/pois.json
python -m json.tool docs/data/map/pois.json
python -m json.tool world/map-data/schemas/poi.schema.json
python world/map-data/scripts/validate_pois.py
```

## Leaflet確認

- `docs/pages/interactive-map.html` を開く
- 対象POIが検索候補に表示されることを確認する
- `window.EternalArcadiaLeafletMap.focusPoi("<poi_id>")` で対象POIへ移動できることを確認する
- ポップアップやマーカー表示が壊れていないことを確認する

## レビュー完了条件

- 依頼件数を守っている
- world/docs の `pois.json` が同期されている
- JSON構文チェックが通る
- Schema検証が通る
- 参照IDがすべて存在する
- Leaflet上で `focusPoi()` が機能する
- レビュー項目に未解決が残っていない

<!-- cspell:enable -->
