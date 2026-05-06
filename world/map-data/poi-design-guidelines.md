---
type: "canon-document"
category: "maps"
title: "POI / Spot Design Guidelines"
version: "1.0.0"
created: "2026-05-06"
last_updated: "2026-05-06"
author: "halc8312"
contributors: []
tags: ["map-data", "poi", "guidelines"]
status: "stable"
---

<!-- cspell:disable -->

## Purpose

This document defines the design rules for adding POIs and spots to the
Leaflet-based world map.

The goal is to ensure that future POI additions remain consistent with canon
lore, map data, geography, transportation, religion, politics, economics,
magic systems, and hazard settings.

This guideline is a preparation step for future `pois.json` design, trial data
entry, and Leaflet display work.

## Core Principle

### POIs exist as a result of world settings

POIs must not be added just to make the map feel busier or more RPG-like.

Each POI must be justified by one or more of the following:

- transportation necessity
- historical origin
- economic function
- religious or spiritual meaning
- magical-system necessity
- political or military role
- hazard response
- daily-life infrastructure
- tourism or cultural value
- exploration or adventure guidance

When a POI cannot be explained through existing settings, it should not be
added yet.

## Alignment Requirements

Every POI must be checked against the following before it is accepted:

- continental history
- city and regional roles
- transportation networks
- geography and climate
- religion and local beliefs
- magic systems
- political structure
- economic sphere
- hazard zones
- existing Map Data
- canon setting documents

## Required Lore Basis Fields

Future `pois.json` entries are expected to include the following basis fields.

### `lore_basis`

Describes which existing settings justify the POI.

Examples:

- "王都アストラリスが政治・交通の中心であること"
- "中央街道と港湾交易が接続していること"
- "カオス・リアの砂漠隊商路が水場と護衛拠点に依存していること"

### `historical_reason`

Explains why the facility came into existence in historical terms.

Example:

王都拡張期に街道交易と王宮御用商人の集積地として形成された。

### `economic_role`

Explains the POI's function in the regional economy.

Example:

広域交易、市民市場、王宮納品、冒険者向け物資供給。

### `cultural_role`

Explains its role in religion, festivals, scholarship, arts, customs, or local
identity.

### `transport_role`

Explains how the POI relates to roads, stations, ports, air routes, submarine
traffic, caravan routes, or other transport nodes.

### `risk_context`

Explains the POI's relationship to hazards, disasters, monsters, seals, public
security, checkpoints, or other risk factors.

For POIs with no meaningful risk relation, this field may be empty or `none`.

## Continental POI Tendencies

### Elysion

Likely POIs:

- royal facilities
- knightly order facilities
- regulated markets
- roadside inns
- temples
- magic academies
- administrative facilities
- trade facilities
- law-and-order facilities

Examples:

- 王宮
- 中央市場
- 騎士団本部
- 王立魔法学院
- 街道駅馬車広場
- 大聖堂
- 王立劇場
- 行政区

Avoid:

- large numbers of black markets in core urban districts
- lawless facilities that contradict capital security settings
- giant entertainment complexes unrelated to transport demand

### Lumiera

Likely POIs:

- lunar magic facilities
- spirit-faith facilities
- forest settlements
- air-route facilities
- observatories
- quiet inns
- esoteric laboratories
- sanctuaries

Examples:

- 月読観測所
- 精霊樹の祠
- 月魔法学院分舎
- 森の結界宿
- 空中港連絡塔
- 銀湖祭礼場

Avoid:

- dense clusters of large industrial facilities
- disorderly commercial districts unrelated to forests or spirit faith
- excessive urbanization that breaks Lumiera's calm atmosphere

### Chaos Ria

Likely POIs:

- caravanserais
- desert markets
- oasis facilities
- mercenary hubs
- forts
- mining facilities
- water-control facilities
- sandstorm shelters
- hazard-response facilities

Examples:

- 隊商宿
- 水売り組合
- 砂嵐避難塔
- 傭兵斡旋所
- 砦市場
- 鉱山町の鍛冶場
- オアシス神殿

Avoid:

- facilities that imply unlimited water access
- entertainment sites that ignore desert conditions
- large commercial hubs disconnected from caravan routes

### Atlantis

Likely POIs:

- port facilities
- submarine terminals
- underwater-city facilities
- pressure-adjustment facilities
- tidal power facilities
- marine research institutes
- sea temples
- underwater warehouses
- overwater lodgings

Examples:

- マリンポート税関
- 潜水艇発着場
- 気圧調整宿
- 潮力発電列車試験駅
- 海底資料院
- 海神殿
- 深潮市場

Avoid:

- copying land-city structures without underwater adaptation
- shops that ignore seabed conditions or currents
- giant land entertainment complexes unrelated to submarine traffic

### Grimoire

Likely POIs:

- forbidden libraries
- sealing facilities
- watchtowers
- survey bases
- time-port facilities
- checkpoints
- hazard-border facilities
- researcher dormitories
- magical-disaster response facilities

Examples:

- 禁書閲覧所
- 封印監視塔
- 時空港管理局
- 調査隊宿舎
- 禁域検問所
- 魔法災害観測所
- 歪曲地帯記録室

Avoid:

- large-scale public tourism facilities
- defenseless shopping streets inside dangerous zones
- amusement facilities that ignore taboo and seal strictness

## POI Capacity by Settlement Scale

### Capital and major city

Allowed categories:

- government facilities
- major markets
- luxury inns
- theaters
- academies
- temples
- guild headquarters
- transport terminals
- specialist shops
- landmarks

Guideline:

- expandable to roughly 20 to 80 POIs
- initial rollout should stay around 10 to 20 POIs

### Mid-sized city and port town

Allowed categories:

- markets
- inns
- taverns
- temples
- guild branches
- port facilities
- warehouses
- checkpoints
- workshops

Guideline:

- roughly 8 to 30 POIs

### Small settlement

Allowed categories:

- small inns
- shrines
- shared wells
- trade posts
- watch posts
- small markets

Guideline:

- roughly 3 to 10 POIs

### Hazard-adjacent base

Allowed categories:

- watch stations
- shelters
- survey bases
- supply depots
- checkpoints
- sealing facilities

Guideline:

- roughly 3 to 15 POIs
- general entertainment facilities should remain rare

## POIs Common Around Transport Nodes

### Capital node

- 王宮
- 行政区
- 中央市場
- 主要神殿
- 学院
- 劇場
- ギルド本部
- 高級宿
- 交通ターミナル

### Port node

- 税関
- 倉庫街
- 船員宿
- 魚市場
- 港湾組合
- 灯台
- 海神殿
- 検疫所

### Airport or sky-port node

- 空路管制塔
- 発着場
- 風読み観測所
- 空路宿
- 魔力補給施設
- 貨物浮遊倉庫

### Caravan-route node

- 隊商宿
- 水場
- 護衛斡旋所
- 物資補給所
- 砂嵐避難所
- 荷役場

### Submarine-traffic node

- 潜水艇駅
- 気圧調整施設
- 潮流観測所
- 海底倉庫
- 潜水許可局
- 救難拠点

### Warp or time-space node

- 管理局
- 封印施設
- 監視塔
- 記録室
- 検問所
- 研究者宿舎

## Proposed POI Categories

Recommended categories for future `pois.json` data:

- `government`
- `military`
- `transport`
- `market`
- `shop`
- `inn`
- `food`
- `guild`
- `academy`
- `temple`
- `culture`
- `entertainment`
- `industry`
- `research`
- `hazard_support`
- `dungeon`
- `landmark`
- `residential`
- `utility`
- `restricted`

Category notes:

- `government`: 行政、役所、管理局
- `military`: 騎士団、砦、兵舎、監視所
- `transport`: 駅、港、空港、発着場、連絡塔
- `market`: 市場、大市場、交易所
- `shop`: 商店、専門店
- `inn`: 宿泊施設
- `food`: 飲食店、酒場、食堂
- `guild`: 冒険者ギルド、職能組合
- `academy`: 学院、学校、研究教育施設
- `temple`: 神殿、祠、聖域
- `culture`: 劇場、図書館、資料院、美術施設
- `entertainment`: 娯楽、祭礼、遊園地相当施設
- `industry`: 工房、鉱山、発電、造船、製造
- `research`: 研究所、観測所、記録室
- `hazard_support`: 避難所、救難所、災害対応施設
- `dungeon`: ダンジョン入口、迷宮、遺跡入口
- `landmark`: 観光名所、記念碑、自然景観
- `residential`: 居住区、地区
- `utility`: 水利、検疫、気圧調整、補給
- `restricted`: 禁域、封印施設、立入制限施設

## Naming Rules

### ID

POI IDs should follow these rules:

- lowercase only
- snake_case only
- use region or city name as prefix when possible
- do not use Japanese characters
- do not use spaces

Examples:

- `astralis_grand_market`
- `astralis_royal_academy`
- `red_sea_caravanserai`
- `marine_port_pressure_inn`
- `time_port_archive_gate`

### Display name

Display names may use Japanese.

Examples:

- アストラリス大市場
- 王立魔法学院
- 紅海隊商宿
- 気圧調整宿
- 時空港記録門

## Planned POI Data Format

This issue does not introduce full `pois.json` data yet, but future work should
target a structure like the following:

```json
{
  "id": "astralis_grand_market",
  "name": "アストラリス大市場",
  "category": "market",
  "type": "commercial",
  "continent_id": "elysion",
  "region_id": "astralis_region",
  "nearest_node_id": "astralis",
  "position": {
    "x": 5240,
    "y": 4380,
    "z": 0
  },
  "importance": 5,
  "status": "active",
  "description": "王都アストラリス最大の市場。中央街道と王都交通網の結節点として、各大陸からの交易品が集まる。",
  "lore_basis": [
    "王都アストラリスが政治・交通の中心であること",
    "中央街道・港湾・魔導交通網と接続していること",
    "エリュシオンが秩序ある交易圏であること"
  ],
  "historical_reason": "王都拡張期に街道交易と王宮御用商人の集積地として形成された。",
  "economic_role": "広域交易、市民市場、王宮納品、冒険者向け物資供給。",
  "cultural_role": "王都市民の日常生活と祭礼市の中心。",
  "transport_role": "中央街道と王都交通網から徒歩圏にある。",
  "risk_context": "王都内のため治安は比較的安定しているが、祭礼期は混雑対策が必要。",
  "tags": ["trade", "capital", "market", "elysion"]
}
```

## Rules Against Shallow POI Additions

Avoid the following:

- adding generic RPG-like shops without ties to existing settings
- placing giant entertainment facilities in deserts without water logic
- filling forbidden areas with ordinary tourist shops
- copying land-city facilities into underwater cities without adaptation
- over-industrializing Lumiera's quiet cultural sphere
- mass-placing lawless facilities in royal urban cores
- placing giant markets away from meaningful transport links
- building large temples without historical justification

## Follow-up Issue Order

Recommended sequence:

1. create POI data specification v0.1
2. add 10 to 15 trial POIs to the Astralis capital area
3. add a POI layer to the Leaflet transportation map
4. review Astralis POIs and lock POI specification v1
5. add major Elysion POIs
6. add major Chaos Ria POIs
7. add major Lumiera, Atlantis, and Grimoire POIs
8. add POI search and category filters
9. add POI detail pages and links to setting documents

<!-- cspell:enable -->
