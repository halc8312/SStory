# Map Data ディレクトリ

このディレクトリは、GitHub Pages上のインタラクティブ交通マップで読み込むための**公開用Map Data**です。

## 位置づけ

- **編集上の正本データ**: `world/map-data/data/` にあります
- **公開用コピー**: `docs/data/map/` はブラウザからFetch可能な形式でコピーされたデータです
- **同期**: データ更新時は `python world/map-data/scripts/sync_map_data.py` を実行してください
- **検証**: CI が `sync_map_data.py --check` で同期漏れを検出します

## ファイル一覧

以下のJSONファイルが配置されています：

- `continents.json` - 大陸情報
- `regions.json` - 地域情報
- `nodes.json` - 地点（都市、村、港など）
- `routes.json` - 経路（陸路・海路・空路）
- `hazards.json` - 危険区域
- `pois.json` - 施設・スポット
- `pixel-mapping.json` - 高解像度世界地図上の正典ID別ピクセル座標

## 利用方法

GitHub Pages上のJavaScriptからFetchで読み込みます：

```javascript
fetch('../data/map/nodes.json')
  .then(response => response.json())
  .then(data => {
    console.log(`Nodes: ${data.length}件`);
  });
```

## 関連

- [インタラクティブ交通マップ準備ページ](../../pages/interactive-map.html)
- [Map Data紹介ページ](../../pages/map-data.html)
- [開発ロードマップ](../../pages/roadmap.html)
- [編集上の正本データ（GitHub）](https://github.com/halc8312/SStory/tree/main/world/map-data)
