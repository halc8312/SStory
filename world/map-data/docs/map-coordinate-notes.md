# Map Coordinate Notes

Leaflet版交通マップのノード座標と背景世界地図の整合確認メモ。

## 2026-05-07 暫定結論

- `continent_id` / `region_id` / popup参照は `continents.json` / `regions.json` から正しく解決される
- `warrior_port` を含むカオス・リア系ノードは、元データ座標のままなら南大陸側にまとまる
- 既存の Leaflet 全体補正 (`scaleX: 0.95`, `scaleY: 0.85`, `offsetX: -300`, `offsetY: -200`) が代表ノード群を系統的に西寄り・北寄りへずらしていた
- そのため、今回の主因は **C. 背景世界地図とデータ座標の変換がズレている** と判断する
- アトランティス東端や `emerald_city` 付近は、背景画像側の大陸ポリゴンが狭めで、後続Issueで **D. 背景地図画像側の仮配置** として再確認する余地がある

## 確認方法

- 対象: `docs/assets/images/maps/world/world-map.svg`
- 対象: `world/map-data/data/nodes.json`
- 代表ノードと全ノードを、大陸ごとの背景ポリゴンと照合
- `window.EternalArcadiaLeafletMap.focusNodeIds([...])` と `focusPoi(id)` は継続利用可能

## 代表ノード確認メモ

### エリュシオン

- `astralis`
- `port_zephia`
- `granrock`
- `silverport`
- `stormhold`

元座標で背景大陸内に収まる。

### カオス・リア

- `blood_fort`
- `jade_oasis`
- `jade_capital`
- `warrior_port`
- `jade_port`
- `red_sea_desert_supply_station`

元座標で南大陸側にまとまる。`warrior_port` は個別修正不要。

### リュミエラ

- `moonlight_grace`
- `moonport`
- `moonlight_platform`
- `lumiera_arch_air_terminal`

元座標で背景大陸内に収まる。`emerald_city` は背景ポリゴン東南端の近傍。

### アトランティス

- `marineport`
- `iron_mountain_port`
- `atlantia_undersea_city`
- `glacier_city`
- `atlantis_floating_base`

ノード群の相対位置は西大陸としてまとまるが、背景画像ポリゴン東端がやや狭い。

### グリモワール

- `time_port`
- `time_airport`
- `labyrinth_of_time`
- `ethernia_core`
- `sealed_lands`

元座標で背景大陸北部に収まる。全体補正適用時のズレが特に大きかった。

## 暫定座標範囲メモ

```yaml
elysion:
  expected_x_range: 4700-5600
  expected_y_range: 4800-5600

chaos_ria:
  expected_x_range: 4600-5900
  expected_y_range: 6300-7500

lumiera:
  expected_x_range: 6900-7500
  expected_y_range: 5000-6100

atlantis:
  expected_x_range: 2400-3300
  expected_y_range: 4300-4900

grimoire:
  expected_x_range: 4900-5200
  expected_y_range: 2100-2300
```

## 影響範囲

- `transformPosition()` / `toLatLng()` に依存するノード、POI、ルート、危険区域へ同じ補正が適用される
- そのため、今回はノード個別修正ではなく全体補正の解消を優先した
- JSONデータ自体は変更していないため、`world/` と `docs/` の Map Data 同期差分はなし
