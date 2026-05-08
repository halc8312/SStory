---
title: "poi-review-checklist"
version: "0.1.0"
created: "2026-05-08"
last_updated: "2026-05-08"
author: "halc8312"
category: "maps"
status: "draft"
---

<!-- cspell:disable -->

# POIレビュー用チェックリスト

## データ構造

- [ ] `id` は lowercase snake_case か
- [ ] 地域 prefix が付いているか
- [ ] `name` は自然な日本語か
- [ ] `category` は許可カテゴリか
- [ ] `status` は許可ステータスか
- [ ] `importance` は 1〜5 か

## 世界観整合

- [ ] 既存の大陸設定と矛盾しないか
- [ ] 既存の地域設定と矛盾しないか
- [ ] 交通網と関係があるか
- [ ] 経済・文化・宗教・危険文脈が自然か

## 根拠フィールド

- [ ] `lore_basis` が既存設定を具体的に参照しているか
- [ ] `historical_reason` が成立理由を説明しているか
- [ ] `economic_role` が地域経済との関係を示しているか
- [ ] `cultural_role` が社会・宗教・学術・祭礼との関係を示しているか
- [ ] `transport_role` が実在ノードや交通動線に結びついているか
- [ ] `risk_context` が危険の有無を明記しているか

## 地図表示

- [ ] 座標が対象地域にあるか
- [ ] POIが密集しすぎていないか
- [ ] Leaflet上で見えるか
- [ ] `focusPoi()` で開けるか

## 検証

- [ ] `python -m json.tool world/map-data/data/pois.json` が通るか
- [ ] `python -m json.tool docs/data/map/pois.json` が通るか
- [ ] `python -m json.tool world/map-data/schemas/poi.schema.json` が通るか
- [ ] Schema validation が通るか
- [ ] world / docs の `pois.json` が同期されているか

<!-- cspell:enable -->
