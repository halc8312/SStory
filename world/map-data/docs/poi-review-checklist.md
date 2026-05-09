---
title: "poi-review-checklist"
version: "0.2.0"
created: "2026-05-08"
last_updated: "2026-05-09"
author: "halc8312"
category: "maps"
status: "draft"
---

<!-- cspell:disable -->

# POIレビュー用チェックリスト

## 依頼スコープ

- [ ] 追加件数が依頼範囲内か
- [ ] 追加件数が多すぎないか
- [ ] このIssueの対象外地域や対象外カテゴリを勝手に増やしていないか
- [ ] 「なんとなくRPGっぽい施設」を追加していないか

## データ構造

- [ ] `id` は lowercase snake_case か
- [ ] 地域 prefix が付いているか
- [ ] POI IDに地域prefixがあるか
- [ ] `name` は自然な日本語か
- [ ] `category` は許可カテゴリか
- [ ] `status` は許可ステータスか
- [ ] `importance` は 1〜5 か
- [ ] 必須フィールドが欠けていないか
- [ ] タグが多すぎないか

## 参照整合

- [ ] `nearest_node_id` が実在するか
- [ ] `continent_id` が実在するか
- [ ] `region_id` が実在するか
- [ ] `continent_id` / `region_id` / `nearest_node_id` の組み合わせが対象地域と整合するか

## 世界観整合

- [ ] 既存の大陸設定と矛盾しないか
- [ ] 既存の地域設定と矛盾しないか
- [ ] 交通網と関係があるか
- [ ] 経済・文化・宗教・危険文脈が自然か

## 根拠フィールド

- [ ] `lore_basis` が既存設定を具体的に参照しているか
- [ ] `lore_basis` が具体的か
- [ ] `historical_reason` が成立理由を説明しているか
- [ ] `historical_reason` が成立理由になっているか
- [ ] `economic_role` が地域経済との関係を示しているか
- [ ] `economic_role` が地域経済と接続しているか
- [ ] `cultural_role` が社会・宗教・学術・祭礼との関係を示しているか
- [ ] `cultural_role` が地域文化と接続しているか
- [ ] `transport_role` が実在ノードや交通動線に結びついているか
- [ ] `transport_role` が交通網と接続しているか
- [ ] `risk_context` が危険の有無を明記しているか
- [ ] `risk_context` が治安・危険・災害と接続しているか

## 地図表示

- [ ] 座標が対象地域にあるか
- [ ] POIが密集しすぎていないか
- [ ] 同じ座標に密集しすぎていないか
- [ ] Leaflet上で見えるか
- [ ] Leafletで表示できるか
- [ ] `focusPoi()` で開けるか

## 検証

- [ ] `python -m json.tool world/map-data/data/pois.json` が通るか
- [ ] `python -m json.tool docs/data/map/pois.json` が通るか
- [ ] `python -m json.tool world/map-data/schemas/poi.schema.json` が通るか
- [ ] `python world/map-data/scripts/validate_pois.py` が通るか
- [ ] Schema validation が通るか
- [ ] world / docs の `pois.json` が同期されているか

<!-- cspell:enable -->
