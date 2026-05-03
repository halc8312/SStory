# Map Data 紹介

エターナル・アルカディアの地理・交通データを**機械可読なJSON形式**で管理しています。

## Map Data とは？

**Map Data** は、この世界の地理情報を構造化データとして定義したJSONファイル群です。

### 目的

1. **Web地図の基盤**: 将来的なインタラクティブマップのデータソース
2. **プログラム的な利用**: ルート検索、データ解析、シミュレーション
3. **標準化**: 世界設定の地理情報を一貫した形式で管理
4. **拡張性**: 新データの追加が容易

---

## データファイル一覧

`world/map-data/data/` に以下のJSONファイルがあります：

### 1. nodes.json

**地点データ**: 都市、村、拠点、天然 phenomena などの位置情報。

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "node_001",
      "properties": {
        "name": "アストラリス",
        "type": "city",
        "population": 500000,
        "continent": "elysion",
        "region": "central",
        "transportation": ["land", "sea", "air"],
        "description": "ゼフィア連合共和国の首都"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [125.3, 38.7]
      }
    }
  ]
}
```

**主要フィールド**:
- `id`: ノードID
- `name`: 名称
- `type`: タイプ（city, village, station, ruin, natural など）
- `population`: 人口（都市の場合）
- `continent`: 所属大陸
- `region`: 所属地域
- `transportation`: 利用可能な交通手段（land, sea, air）
- `description`: 説明文
- `geometry`: 座標（GeoJSON形式）

---

### 2. routes.json

**経路データ**: 街道、航路、空路などのリンク情報。

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "route_001",
      "properties": {
        "name": "中央街道（アストラリス～ムーンフォール）",
        "type": "land_road",
        "start_node": "node_001",
        "end_node": "node_015",
        "distance_km": 1200,
        "travel_time_hours": 72,
        "difficulty": "easy",
        "hazards": []
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [125.3, 38.7],
          [126.1, 39.2],
          ...
        ]
      }
    }
  ]
}
```

**主要フィールド**:
- `id`: ルートID
- `name`: ルート名
- `type`: タイプ（land_road, sea_route, air_route, railway）
- `start_node`: 開始ノードID
- `end_node`: 終了ノードID
- `distance_km`: 距離（km）
- `travel_time_hours`: 標準所要時間（hours）
- `difficulty`: 難易度（easy, medium, hard, dangerous）
- `hazards`: 危険区域IDリスト
- `geometry`: 経路の座標点列（GeoJSON LineString）

---

### 3. hazards.json

**危険区域データ**: monsters 棲息地、災害危険地帯、通行禁止区域。

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "hazard_001",
      "properties": {
        "name": "呪われた森",
        "type": "monster_territory",
        "danger_level": "high",
        "monsters": ["goblin", "wolf", "undead"],
        "restricted": true,
        "required_level": 10
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [125.5, 38.0],
            [125.8, 38.0],
            [125.8, 38.3],
            [125.5, 38.3],
            [125.5, 38.0]
          ]
        ]
      }
    }
  ]
}
```

**主要フィールド**:
- `id`: ハザードID
- `name`: 区域名
- `type`: タイプ（monster_territory, disaster_zone, forbidden, magical_hazard）
- `danger_level`: 危険度（low, medium, high, extreme）
- `monsters`: 出现モンスターリスト
- `restricted`: 通行制限有無（true/false）
- `required_level`: 推奨冒険者レベル
- `geometry`: 区域形状（Polygon, MultiPolygon）

---

### 4. continents.json

**大陸情報**: 五大陸のメタデータ。

```json
{
  "continents": [
    {
      "id": "elysion",
      "name": "エリュシオン",
      "name_en": "Elysion",
      "capital": "アストラリス",
      "area_km2": 12000000,
      "population": 50000000,
      "climate": "temperate",
      "description": "中央大陸。政治・経済の中心"
    }
    // ...
  ]
}
```

---

### 5. regions.json

**地域情報**: 大陸内の地域メタデータ。

```json
{
  "regions": [
    {
      "id": "central_elysion",
      "name": "中央地域",
      "continent": "elysion",
      "major_cities": ["node_001", "node_002", "node_003"],
      "description": "エリュシオンの中央部"
    }
    // ...
  ]
}
```

---

## GeoJSON 形式について

Map Data は **GeoJSON** 形式に準拠しています。

### GeoJSON の利点

1. **標準形式**: GIS ソフトウェアで直接読込可能
2. **Web地図対応**: Leaflet, OpenLayers などで扱える
3. **拡張性**: 任意のプロパティを追加可能
4. **人間可読**: JSON は読解しやすい

### 座標系

- **WGS84** (EPSG:4326) を使用
- `[経度, 緯度]` 形式（**経度先、緯度後**の順）
- 単位: 度（decimal degrees）

---

## Python ツール

Map Data は、Python スクリプトで生成・管理されています。

### 利用可能なスクリプト

`tools/map/` ディレクトリ内に以下があります：

- **`validate_map_data.py`**: データの整合性チェック
- **`export_geojson.py`**: 各種形式からGeoJSONへ変換
- **`route_finder.py`**: ルート検索アルゴリズム（Python版）

### 実行例

```bash
# データ検証
python tools/map/validate_map_data.py

# GeoJSONエクスポート
python tools/map/export_geojson.py --output world/map-data/exports/

# ルート検索（例）
python tools/map/route_finder.py --start アストラリス --end ムーンフォール
```

---

## Map Data の利用方法

### 1. Webサイトで表示（予定）

将来的な Webインタラクティブマップでの利用：

```javascript
// Leaflet での表示例（将来実装）
fetch('/data/map/nodes.json')
  .then(response => response.json())
  .then(data => {
    // ノードを地図上に表示
    L.geoJSON(data).addTo(map);
  });
```

---

### 2. ルート検索

**route_finder.py** のロジックを JavaScript へ移植し、Web上でのルート検索を実装予定。

現在のPython版：

```bash
python route_finder.py --start "アストラリス" --end "ムーンフォール" --type land
```

---

### 3. カスタムスクリプトでの利用

#### Node.js / JavaScript

```javascript
import fs from 'fs';

const nodes = JSON.parse(fs.readFileSync('world/map-data/data/nodes.json'));
const routes = JSON.parse(fs.readFileSync('world/map-data/data/routes.json'));

// ノードをIDで検索
function findNode(id) {
  return nodes.features.find(n => n.id === id);
}
```

#### Python

```python
import json

with open('world/map-data/data/nodes.json') as f:
    nodes = json.load(f)

with open('world/map-data/data/routes.json') as f:
    routes = json.load(f)
```

---

## データの更新と追加

### データ追加手順

1. `world/map-data/data/` の適切なJSONファイルを編集
2. `tools/map/validate_map_data.py` で検証
3. 変更をコミット
4. GitHub Actions で自動検証（予定）

### データ形式のルール

- **必須フィールド**: `id`, `type`, `geometry`
- **IDの命名**: `node_001`, `route_001`, `hazard_001` など
- **一意性**: 全IDは重複しないこと
- **座標**: WGS84、[経度, 緯度] 形式

---

## データと正史資料の関係

Map Data は**正史設定資料の構造化版**です。

- **node** = 都市・村・拠点などの地点 → `world/` の各都市説明と対応
- **route** = 街道・航路 → `world/transportation/` の記述と対応
- **hazard** = 危険区域 → `world/creatures/bestiary.md` の棲息地と対応

**重要**: Map Data は正史資料に**記述された内容を数値・座標化したもの**です。正史は `world/` 配下のMarkdownが本体です。

---

## 将来のWebマップ実装計画

### v0.1 (現在)
- Map Data 紹介ページ作成（本ページ）
- データファイルの整備
- 将来実装のプレースホルダー

### v0.2 (予定)
- 簡易HTMLビューア（Leaflet導入）
- nodes の表示
- routes の表示
- クリックでプロパティ表示

### v0.3 (予定)
- ルート検索UI（JavaScript実装）
- レイヤー切り替え（nodes, routes, hazards）
- ズーム・パン操作

### v1.0 (将来)
- 地図画像オーバーレイ
- タイルマップ対応
- 詳細情報ポップアップ
- 印刷・保存機能

詳細: [インタラクティブマップ計画](interactive-map-plan.md)

---

## 技術仕様

### ファイルサイズ制限

- 1JSONファイルあたり最大 **10MB**（Git LFS推奨）
- 現在の `nodes.json`: 約20KB（約200ノード）
- 将来のデータ増加を見越した分割も検討

### バージョン管理

- データ変更時は **semver** 形式でバージョン管理を推奨
- 破壊的変更時は `major` アップデート
- マイナー変更時は `minor` アップデート

### データ整合性

- CI で `validate_map_data.py` を自動実行（予定）
- 座標の妥当性（大陸内に収まるか）
- 参照整合性（routeのstart_node, end_nodeが存在するか）
- 重複IDチェック

---

## よくある質問 (FAQ)

### Q: Map Data と world/ のMarkdown、どちらが正しい？
**A**: 両方が正史です。Markdownが**記述**、Map Dataが**構造化データ**です。矛盾がある場合はMarkdownが優先。

### Q: 新しいノードを追加するには？
**A**: `nodes.json` にエントリを追加し、`validate_map_data.py` で検証後、コミット。

### Q: Webマップはいつ使えるようになる？
**A**: v0.2で簡易ビューア、v0.3でルート検索、v1.0でフル機能を予定。詳細はロードマップ参照。

### Q: 座標の基準は？
**A**: WGS84（GPSと同じ）。地図画像と重ねる際は座標変換が必要な場合あり。

---

## 関連ページ

- [インタラクティブマップ計画](interactive-map-plan.md)
- [地図ギャラリー](gallery.md)
- [交通](../world/transportation.md) - route の内容元
- [地理](../world/geography.md) - node の内容元

## 正史資料

Map Data の管理に関する詳細は、以下を参照：

```
world/map-data/
├── data/                    # 本番データ（本リポジトリ）
│   ├── nodes.json
│   ├── routes.json
│   ├── hazards.json
│   ├── continents.json
│   └── regions.json
├── examples/                # 使用例
├── exports/                 # エクスポート成果物
├── schemas/                 # JSONスキーマ定義
│   ├── node-schema.json
│   ├── route-schema.json
│   └── hazard-schema.json
└── README.md                # Map Data 全体説明（予定）
```

---

**次のステップ**: [インタラクティブマップの計画を見る](interactive-map-plan.md) | [地図ギャラリーを閲覧](../maps/gallery.md) | [交通データを理解](../world/transportation.md)
