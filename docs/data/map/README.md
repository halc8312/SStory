# Map Data ディレクトリ

このディレクトリには、エターナル・アルカディア世界の地図データ（JSON/GeoJSON形式）を格納します。

## ファイル構成（予定）

以下のファイルを配置する予定です：

- `nodes.json` - すべての地点（都市、村、港、転送ゲートなど）の座標・属性データ
- `routes.json` - 地点間を結ぶ経路（陸路・海路・空路）の接続情報と距離・所要時間
- `hazards.json` - 危険区域（海獣出没地帯、異常気象域、魔物棲息地など）のポリゴンデータ
- `continents.json` - 五大陸の境界ポリゴンと基本情報
- `regions.json` - 地域・国・州などの行政区画データ

## データ形式

### nodes.json
```json
{
  "nodes": [
    {
      "id": "elysion_capital",
      "name": "エリュシオン首都",
      "type": "city",
      "x": 0.5,
      "y": 0.5,
      "continent": "elysion",
      "population": 500000,
      "transport_hubs": ["port", "airport", "gate"]
    }
  ]
}
```

### routes.json
```json
{
  "routes": [
    {
      "from": "elysion_capital",
      "to": "lumiera_forest",
      "type": "land",
      "distance": 120.5,
      "duration_hours": 48,
      "seasonal_restrictions": ["winter"]
    }
  ]
}
```

### hazards.json (GeoJSON)
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "海獣出没海域",
        "level": "dangerous"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [...]
      }
    }
  ]
}
```

## 利用方法

### Python ツール（ローカル/CI用）
```bash
python tools/map/route_finder.py --from elysion_capital --to atlantis_port
```

### Web ブラウザ（GitHub Pages上）
将来的には、JavaScript からこれらの JSON ファイルを Fetch で読み込み、
Leaflet 等の地図ライブラリで表示する予定です。

```javascript
fetch('/SStory/docs/data/map/nodes.json')
  .then(response => response.json())
  .then(data => {
    // 地図上にノードを表示
  });
```

## 現在のステータス

v0.1 時点では、このディレクトリに実際の JSON データファイルは配置されていません。
Map Data の仕様定義のみがこの README に記載されています。

実際のデータ生成は、今後の開発フェーズで行います。

## 関連リンク

- [Map Data 紹介ページ](../../pages/map-data.html)
- [開発ロードマップ](../../pages/roadmap.html)
- [world/map-data/](../../../world/map-data/) - 設定資料
- [tools/map/](../../../tools/map/) - データ生成・ルート検索ツール
