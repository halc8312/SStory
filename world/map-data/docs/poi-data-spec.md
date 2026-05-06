---
type: "canon-document"
category: "maps"
title: "POI Data Specification v0.1"
version: "0.1.0"
created: "2026-05-06"
last_updated: "2026-05-06"
author: "halc8312"
contributors: []
tags: ["map-data", "poi", "specification", "v0.1"]
status: "draft"
---

<!-- cspell:disable -->

## Purpose

This document defines the data specification for POIs (Points of Interest) and spots
in the Eternal Arcadia world map. It establishes the JSON structure, required fields,
validation rules, and semantic guidelines for adding POI data that remains consistent
with canon lore, geography, transportation, religion, politics, economics, magic systems,
and hazard settings.

This specification v0.1 establishes the foundation for future POI data entry and
Leaflet-based map display. It should not be considered final; subsequent versions
may refine fields, enums, and validation rules based on trial data entry experience.

## Scope

This specification covers:

- Basic POI JSON structure and data types
- Required and optional fields
- Category and type classifications
- Importance and status definitions
- Position and coordinate system
- Transportation node relationships
- Lore basis and justification fields (must-have evidence)
- Naming conventions for IDs and display names
- JSON Schema validation rules

**Out of scope for v0.1:**

- Large-scale POI data entry (only sample entries allowed)
- Leaflet POI layer implementation
- POI search and filtering functionality
- POI-specific icon design
- World map image modifications

## Core Principle

### POIs exist as a result of world settings

POIs must not be added merely to make the map feel busier or more RPG-like.

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

When a POI cannot be explained through existing settings, it should not be added yet.

## Data File Locations

- **Master data**: `world/map-data/data/pois.json`
- **GitHub Pages copy**: `docs/data/map/pois.json`
- **Schema**: `world/map-data/schemas/poi.schema.json`
- **This spec**: `world/map-data/docs/poi-data-spec.md`

## Basic Structure

A POI entry is a JSON object with the following top-level structure:

```json
{
  "id": "astralis_grand_market",
  "name": "アストラリス大市場",
  "category": "market",
  "type": "commercial",
  "continent_id": "elysion",
  "region_id": "royal_capital_region",
  "nearest_node_id": "astralis",
  "position": {
    "x": 5240,
    "y": 4380,
    "z": 0
  },
  "importance": 5,
  "status": "draft",
  "description": "王都アストラリス最大の市場。中央街道と王都交通網の結節点として、各大陸からの交易品が集まる。",
  "lore_basis": [
    "王都アストラリスが政治・交通の中心であること",
    "中央街道と王都交通網が接続していること",
    "エリュシオンが秩序ある交易圏であること"
  ],
  "historical_reason": "王都拡張期に街道交易と王宮御用商人の集積地として形成された。",
  "economic_role": "広域交易、市民市場、王宮納品、冒険者向け物資供給。",
  "cultural_role": "王都市民の日常生活と祭礼市の中心。",
  "transport_role": "中央街道と王都交通網から徒歩圏内にある。",
  "risk_context": "王都内のため治安は比較的安定しているが、祭礼期は混雑対策が必要。",
  "tags": ["trade", "capital", "market", "elysion"]
}
```

## Required Fields

The following fields are **mandatory** for every POI entry:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (lowercase snake_case) |
| `name` | string | Display name in Japanese |
| `category` | string | Major category (enum, see below) |
| `type` | string | Subtype (lowercase snake_case) |
| `continent_id` | string | Parent continent ID |
| `region_id` | string | Parent region ID |
| `nearest_node_id` | string | ID of nearest transport node |
| `position` | object | X/Y/Z coordinates |
| `importance` | integer | Importance level 1-5 |
| `status` | string | Status (enum, see below) |
| `description` | string | Brief Japanese description |
| `lore_basis` | array[] | Justification from existing lore |
| `historical_reason` | string | Historical origin explanation |
| `economic_role` | string | Economic function |
| `cultural_role` | string | Cultural/religious/social function |
| `transport_role` | string | Transportation network relation |
| `risk_context` | string | Hazard/security context |
| `tags` | array[] | Keywords for filtering |

### Required Evidence Fields (Justification)

The following are collectively called **evidence fields** — they prove the POI's
existence is grounded in existing world settings:

- **`lore_basis`**: Array of canon facts supporting this POI. Each item should reference
  a specific established setting (e.g., "王都アストラリスが政治・交通の中心であること").

- **`historical_reason`**: Narrative explaining when and why this facility was created.

- **`economic_role`**: What economic need does this POI serve? (trade, supply, services, etc.)

- **`cultural_role`**: How does this POI relate to faith, festivals, education, arts, or local identity?

- **`transport_role`**: How does this POI connect to roads, ports, air routes, warp gates, etc.?

- **`risk_context`**: Any hazard, security, seal, or disaster relation. If none, write `none` or `特筆すべき危険要素はない`.

These fields ensure every POI can answer: "Why does this exist in this world?"

## Optional Fields

The following fields may be included for extended information:

| Field | Type | Description |
|-------|------|-------------|
| `aliases` | array[string] | Alternative names |
| `short_name` | string | Abbreviated label for maps |
| `owner` | string | Owner/operator organization |
| `faction_id` | string | Controlling faction reference |
| `related_node_ids` | array[string] | Other connected node IDs |
| `related_route_ids` | array[string] | Route IDs serving this POI |
| `related_hazard_ids` | array[string] | Hazard IDs affecting this POI |
| `opening_hours` | string | Operating hours/season |
| `access_rules` | string | Permits, fees, restrictions |
| `security_level` | integer | 0-5 (open to locked) |
| `price_level` | integer | 1-5 (cheap to expensive) |
| `services` | array[string] | Services offered |
| `products` | array[string] | Products available |
| `linked_pages` | array[string] | URLs to related setting docs |
| `image` | string | Image path or URL |
| `icon` | string | Icon identifier for map |
| `notes` | string | Internal editor notes |

Optional fields may be added in future schema versions without breaking existing data.

## Category Enum

`category` must be one of the following values:

| Category | Description | Example Types |
|----------|-------------|---------------|
| `government` | Administrative offices, bureaus, city hall | city_hall, tax_office |
| `military` | Knight orders, forts, barracks, watchtowers | fortress, guard_post |
| `transport` | Stations, ports, airports, terminals | railway_station, sky_harbor |
| `market` | Markets, exchanges, trading posts | grand_market, black_market |
| `shop` | Retail stores, specialty shops | weapon_shop, magic_tool_shop |
| `inn` | Lodging: inns, hotels, caravanserais | wayside_inn, luxury_hotel |
| `food` | Restaurants, taverns, cafes, eateries | tavern, fine_dining |
| `guild` | Adventurer guilds, trade unions | adventurer_guild, mages_guild |
| `academy` | Schools, academies, research institutes | magic_academy, university |
| `temple` | Shrines, temples, sanctuaries | grand_cathedral, spirit_shrine |
| `culture` | Theaters, libraries, galleries, halls | opera_house, central_library |
| `entertainment` | Amusement parks, festival grounds, game halls | carnival_grounds, colosseum |
| `industry` | Workshops, mines, factories, plants | blacksmith_workshop, mine |
| `research` | Labs, observatories, recording stations | moon_observatory, field_lab |
| `hazard_support` | Shelters, rescue stations, disaster response | storm_shelter, evacuation_center |
| `dungeon` | Dungeon entrances, ruins, labyrinths | ruin_entrance, monster_lair |
| `landmark` | Tourist spots, monuments, natural features | waterfall, monument |
| `residential` | Neighborhoods, districts, residential zones | noble_quarter, commoner_district |
| `utility` | Waterworks, quarantine, power, supply | water_tower, power_station |
| `restricted` | Forbidden zones, sealed facilities, restricted access | sealed_archive, forbidden_laboratory |

**Note:** Category choices should align with the POI's primary function. If uncertain, refer to `poi-design-guidelines.md` continental tendencies.

## Type Field

`type` is a lowercase `snake_case` string providing a subcategory label.

Examples:

```json
{ "category": "food", "type": "tavern" }
{ "category": "inn", "type": "caravanserai" }
{ "category": "transport", "type": "air_harbor" }
{ "category": "research", "type": "moon_observatory" }
{ "category": "restricted", "type": "sealed_archive" }
```

`type` values are free-form but must:
- Be lowercase alphanumeric + underscores only (no spaces, no Japanese)
- Be descriptive and consistent across similar POIs
- Prefer existing type values when available

## Importance Scale

`importance` is an integer from 1 to 5:

| Value | Meaning | Example |
|-------|---------|---------|
| 1 | Local — serves immediate neighborhood or village | Small shrine, village grocer |
| 2 | Neighborhood — known to nearby settlements | Roadside inn, local market |
| 3 | Regional — important to city/region | City market, regional temple |
| 4 | Continental — significant across a continent | Capital academy, major port |
| 5 | World — of major canonical importance | Royal palace, world-famous landmark, central warp gate |

Importance influences map symbol sizing, detail level, and listing priority.

## Status Enum

`status` indicates operational or historical condition:

| Status | Meaning | Usage |
|--------|---------|-------|
| `draft` | Trial/uncertain entry | Use for test data pending review |
| `active` | Currently operating | Normal functioning POI |
| `historical` | Historically significant, no longer operating | Preserved sites, former capitals |
| `ruined` | In ruins or severely damaged | Abandoned ruins, destroyed facilities |
| `restricted` | Access limited by permit or conditions | Military zone, members-only |
| `sealed` | Magically or administratively sealed | Forbidden areas, sealed archives |
| `abandoned` | Fully deserted | Ghost towns, derelict buildings |
| `seasonal` | Operates only during certain seasons | Summer resort, winter shelter |
| `hidden` | Concealed/secret | Hidden guild halls, secret passages |

## Position Specification

`position` is an object with three numeric coordinates:

```json
"position": {
  "x": 5240,
  "y": 4380,
  "z": 0
}
```

- **`x`**: East-west coordinate (0 = west edge, 10000 = east edge)
- **`y`**: North-south coordinate (0 = south edge, 10000 = north edge)
- **`z`**: Vertical layer
  - `0` = ground / sea level
  - Positive values = above ground / floating / altitude
  - Negative values = underground / underwater / depth

All coordinates are integers within the 0–10000 range. Floating-point values are permitted only for generated exports; source data should use integers when possible.

## Transportation Node Relationship

Every POI must specify `nearest_node_id` — the ID of the closest transport node
(city, port, airport, terminal, etc.). This establishes connectivity to the
transportation network.

Optional auxiliary arrays:

- `related_node_ids`: Other nodes directly associated (e.g., multiple nearby cities)
- `related_route_ids`: Routes that serve this POI directly (e.g., a road that ends at this inn)

**Rule:** POIs should not be completely isolated; each should have at least one
meaningful connection to a transport node or route.

## Lore Basis and Justification Fields

These six fields collectively prove the POI's world-integration:

### `lore_basis` (array of strings)

Cite specific, pre-existing canon facts that justify this POI's presence.
Each item should be a concise statement like:

- "王都アストラリスが政治・交通の中心であること"
- "中央街道と港湾交易が接続していること"
- "カオス・リアの砂漠隊商路が水場と護衛拠点に依存していること"
- "リュミエラに月読信仰が根付いていること"

**Minimum 1 item required.** Be precise; avoid vague statements.

### `historical_reason` (string)

Explain the historical circumstances that led to this POI's creation.
Example: "王都拡張期に街道交易と王宮御用商人の集積地として形成された。"

### `economic_role` (string)

Describe the POI's function in the economy: what it produces, trades, supplies, or consumes.
Example: "広域交易、市民市場、王宮納品、冒険者向け物資供給。"

### `cultural_role` (string)

Describe religious, festival, academic, artistic, or daily-life significance.
Example: "王都市民の日常生活と祭礼市の中心。"

### `transport_role` (string)

Describe the POI's relationship to transportation infrastructure.
Example: "中央街道と王都交通網から徒歩圏内にある。"

### `risk_context` (string)

Describe any hazard, security, seal, disaster, or monster-related context.
If there is no meaningful risk, write `none` or `特筆すべき危険要素はない`.
Example: "王都内のため治安は比較的安定しているが、祭礼期は混雑対策が必要。"

## Naming Conventions

### ID Rules (`id` field)

- **Lowercase only**
- **snake_case only** (underscores, no spaces/hyphens)
- No Japanese characters
- Use location prefix when possible: `{place_name}_{poi_type}`
- No spaces, no special characters except `_`

**Good examples:**

- `astralis_grand_market`
- `astralis_royal_academy`
- `red_sea_caravanserai`
- `marine_port_customs`
- `time_port_sealed_archive`

**Bad examples:**

- `AstralisGrandMarket` (camelCase)
- `astralis-grand-market` (hyphens)
- `アストラリス大市場` (Japanese in ID)
- `grand market` (space)

### Display Name (`name` field)

- Japanese is encouraged and expected
- Should match local language/culture of the region
- Avoid overly generic names like "商店" (generic shop) without modifier
- Prefer specific, lore-consistent names

**Good:** アストラリス大市場、月影観測所、紅海隊商宿

**Bad:** ただの市場、適当な宿、謎の施設

## Optional Field Guidelines

When using optional fields, follow these patterns:

- `aliases`: ["旧市街市場", "中央市場"]
- `short_name`: "大市場" (for tight map labels)
- `owner`: "アストラリス商業組合"
- `faction_id`: "astralis_merchant_guild"
- `related_node_ids`: ["astralis", "astralis_carriage_plaza"]
- `related_route_ids`: ["central_highway", "royal_magiline"]
- `related_hazard_ids`: ["low_level_curse_zone"]
- `opening_hours`: "6:00-20:00 (祭礼期は22:00まで)"
- `access_rules`: "王都居住者証が必要、外国人は税関許可を要する"
- `security_level`: 3 (1=open, 5=maximum)
- `price_level`: 3 (1=cheap, 5=premium)
- `services`: ["荷物預かり", "為替", "宿泊"]
- `products`: ["穀物", "魔术薬", "工芸品"]
- `linked_pages`: ["../world/locations/astralis.md"]
- `icon`: "market"
- `notes`: "Editor: verify exact coordinates against city map v2"

## Continent and Region IDs

Use the IDs defined in `world/map-data/data/continents.json` and `regions.json`:

**Continents:**

- `elysion` — エリュシオン (中央大陸)
- `lumiera` — リュミエラ (東大陸)
- `chaos_ria` — カオス・リア (南大陸)
- `atlantis` — アトランティス (西大陸)
- `grimoire` — グリモワール (北大陸)

**Regions** (partial list; see `regions.json` for full set):

- `royal_capital_region` — 王都地方
- `silver_plains_region` — 銀の平野
- `soaring_mountains_region` — 天翔山脈
- `spirit_forest_region` — 精霊の森地域 (Lumiera)
- `red_sea_desert_region` — 紅海砂漠地域 (Chaos Ria)
- `jade_kingdom_region` — 翡翠王国地域
- `deep_sea_region` — 深海域 (Atlantis)
- `time_distortion_region` — 時空歪曲地域 (Grimoire)

Always verify against the current `regions.json`.

## Node IDs

`nearest_node_id` must reference an existing node from `nodes.json`. Common nodes:

- `astralis` — アストラリス (首都)
- `port_zephia` — ポートゼフィア
- `silverport` — シルバーポート
- `granrock` — グランロック
- `moonlight_grace` — ムーンライト・グレイス (Lumiera city)
- `moonshadow_floating_island` — 月影浮島 (Lumiera)
- `jade_capital` — 翡翠王都 (Chaos Ria)
- `jade_port` — 翡翠港
- `marineport` — マリンポート (Atlantis port)
- `atlantia_undersea_city` — アトランティア (海底都市)
- `time_port` — 時空の港 (Grimoire)
- `labyrinth_of_time` — 時の迷宮

See `world/map-data/data/nodes.json` for the complete list.

## Validation

All `pois.json` entries must validate against `world/map-data/schemas/poi.schema.json`.

### Manual Validation

```bash
# Validate JSON syntax
python -m json.tool world/map-data/data/pois.json > /dev/null

# Copy to GitHub Pages location
cp world/map-data/data/pois.json docs/data/map/pois.json
```

### Schema Validation (Future)

A validation script will be added to `tools/map/validate_map_data.py` in a future update.

The schema enforces:

- Array of objects structure
- All required fields present
- `id` matches `^[a-z][a-z0-9_]*$` pattern
- `category` is one of the 21 allowed enums
- `status` is one of the 9 allowed enums
- `importance` is integer 1–5
- `position.x`, `position.y`, `position.z` are numbers within range
- `lore_basis` is a non-empty array
- `tags` is a non-empty array
- No additional properties beyond defined optional fields

## Sample Entries

Two sample entries are provided in `pois.json`:

1. **Astralis Grand Market** (`astralis_grand_market`)
   - Category: `market`, Type: `commercial`
   - Importance: 5 (world-significant)
   - Status: `draft`
   - Demonstrates full field usage with rich justification

2. **Moonshadow Observatory** (`moonshadow_observatory`)
   - Category: `research`, Type: `observatory`
   - Importance: 3 (regional)
   - Status: `draft`
   - Located on floating island in Lumiera with positive Z coordinate

These are template examples; replace with real data in future issues.

## Relationship to POI Design Guidelines

This specification implements the design rules defined in
[`poi-design-guidelines.md`](../poi-design-guidelines.md).

Key alignments:

- Evidence fields (`lore_basis`, `historical_reason`, etc.) come directly from guidelines
- Category list matches proposed categories
- Naming rules match guidelines
- Importance definition aligns with settlement-scale guidelines
- Continental tendencies inform appropriate category/type choices

Always read `poi-design-guidelines.md` before adding new POIs.

## Future Evolution

v0.1 is intentionally conservative. Future versions may add:

- `confidence` field (canon/estimated/inferred/placeholder) akin to node schema
- `transport_roles` array for multi-role classification
- `facilities` array for fine-grained feature flags
- Relations to regions via `region_id` enforcement
- GeoJSON export extensions
- Linkage to `nodes.json` (some POIs may become nodes themselves)
- Custom icon mappings
- Opening hours structured format
- Multi-language name fields (`name_en`)

Changes will be documented in subsequent specification versions.

## Alignment Checklist

Before adding any POI, verify:

- [ ] Lore basis cites 2+ existing canon settings
- [ ] Historical reason explains origin timeline
- [ ] Economic role is clear and non-vacuous
- [ ] Cultural role is specific (not "none" without thought)
- [ ] Transport role references actual routes/nodes
- [ ] Risk context is honest (even if "none")
- [ ] Category and type fit continental tendencies
- [ ] ID follows lowercase_snake_case with prefix
- [ ] Position coordinates within 0-10000 range
- [ ] Nearest node ID exists in `nodes.json`
- [ ] Importance rating matches actual significance
- [ ] Status correctly reflects operational state
- [ ] Description is informative (1+ sentences)

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-05-06 | Initial specification draft; schema and sample data created |

## Related Documents

- [`world/map-data/poi-design-guidelines.md`](../poi-design-guidelines.md) — Design philosophy and rules
- [`world/map-data/schemas/poi.schema.json`](../schemas/poi.schema.json) — Machine-readable validation
- [`world/map-data/data/pois.json`](../data/pois.json) — Current POI dataset
- [`docs/data/map/pois.json`](../../docs/data/map/pois.json) — GitHub Pages copy
- [`world/map-data/README.md`](../README.md) — Map Data overview

<!-- cspell:enable -->
