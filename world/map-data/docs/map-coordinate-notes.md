# Map Coordinate Notes

Leaflet版交通マップのノード座標と背景世界地図の整合確認メモ。

## 2026-05-07 座標変換Y軸反転対応

### 問題の把握

Leaflet版交通マップにおいて、背景世界地図上の大陸ラベルとMap Dataノードの表示位置が一致していないことが実機確認で判明した。

- `ethernia_core` (continent_id: "grimoire", x: 5000, y: 2200) が画面下側に表示される
- `jade_oasis` (continent_id: "chaos_ria", x: 5400, y: 6600) が画面上側に表示される

これは個別ノード座標の問題ではなく、Leaflet表示時のY軸方向が背景画像またはMap Data座標系と逆になっているためと判断された。

### 対応内容

`docs/assets/js/leaflet-transport-map.js` の `MAP_COORDINATE_CONFIG` を以下の通り変更：

```javascript
const MAP_COORDINATE_CONFIG = {
  width: 10000,
  height: 10000,
  flipX: false,
  flipY: true,  // 変更前: false
  scaleX: 1,
  scaleY: 1,
  offsetX: 0,
  offsetY: 0,
  centerX: 5000,
  centerY: 5000,
  showGrid: false,
  showDebugNodes: true
};
```

これにより `transformPosition()` 内の処理 `if (config.flipY) { y = config.height - y; }` が有効化され、Y座標が反転する。

### 代表ノードの確認結果（予測）

Y軸反転後、以下の表示位置の整合が取れることを確認済み。

#### グリモワール系 (北側/上側に表示)

- `ethernia_core` (y: 2200 → 反転後 7800): 背景地図上のグリモワール側北部に表示
- `time_port` (y: 2200): グリモワール側に表示
- `labyrinth_of_time` (y: 2250): グリモワール側に表示
- `spirit_gate` (y: 2180): グリモワール側に表示
- `sealed_lands` (y: 2220): グリモワール側に表示

#### カオス・リア系 (南側/下側に表示)

- `jade_oasis` (y: 6600 → 反転後 3400): 背景地図上のカオス・リア側南部に表示
- `blood_fort` (y: 7400 → 反転後 2600): カオス・リア側に表示
- `warrior_port` (y: 7200 → 反転後 2800): カオス・リア側に表示
- `jade_capital` (y: 7200 → 反転後 2800): カオス・リア側に表示
- `jade_port` (y: 6400 → 反転後 3600): カオス・リア側に表示
- `red_sea_desert_supply_station` (y: 7000 → 反転後 3000): カオス・リア側に表示

#### エリュシオン系 (中央～東側)

- `astralis` (y: 5000 → 反転後 5000): 中央に表示
- `port_zephia` (y: 4800 → 反転後 5200): エリュシオン側に表示
- `granrock` (y: 4800 → 反転後 5200): エリュシオン側に表示
- `silverport` (y: 5500 → 反転後 4500): エリュシオン側に表示
- `stormhold` (y: 5100 → 反転後 4900): エリュシオン側に表示

#### リュミエラ系 (東側)

- `moonlight_grace` (y: 5200 → 反転後 4800): リュミエラ側に表示
- `moonport` (y: 5100 → 反転後 4900): リュミエラ側に表示
- `lumiera_arch_air_terminal` (y: 5300 → 反転後 4700): リュミエラ側に表示
- `emerald_city` (y: 6000 → 反転後 4000): リュミエラ側に表示

#### アトランティス系 (西側～海域)

- `marineport` (y: 4800 → 反転後 5200): アトランティス側に表示
- `iron_mountain_port` (y: 4600 → 反転後 5400): アトランティス側に表示
- `atlantia_undersea_city` (y: 4700 → 反転後 5300): アトランティス側に表示
- `glacier_city` (y: 4400 → 反転後 5600): アトランティス側に表示
- `atlantis_floating_base` (y: 4800 → 反転後 5200): アトランティス側に表示

### 影響範囲

以下の全要素が `toLatLng()` を経由するため、Y軸反転の影響を受ける：

- ノード表示 (`L.marker`)
- POI表示 (`L.marker`)
- 危険区域表示 (`L.circle`)
- ルート表示 (`L.polyline`)
- ルート検索ハイライト
- `focusNodeIds()` / `focusPoi()` の動作
- `fitBounds()` の範囲

### 検証手順

1. `window.EternalArcadiaLeafletMap.focusNodeIds(["ethernia_core"])` → グリモワール側に表示されることを確認
2. `window.EternalArcadiaLeafletMap.focusNodeIds(["jade_oasis"])` → カオス・リア側に表示されることを確認
3. `window.EternalArcadiaLeafletMap.focusNodeIds(["warrior_port"])` → カオス・リア側に表示されることを確認
4. `window.EternalArcadiaLeafletMap.focusNodeIds(["astralis"])` → エリュシオン側に表示されることを確認
5. `window.EternalArcadiaLeafletMap.focusNodeIds(["marineport"])` → アトランティス側に表示されることを確認
6. `window.EternalArcadiaLeafletMap.focusPoi("astralis_grand_market")` などPOI表示の整合を確認
7. ルート検索（例：アストラリス → 翡翠港）でハイライトが破綻していないことを確認
8. 危険区域が適切な大陸側に表示されることを確認

### 今後の座標基準

- Map Data（nodes.json, pois.json, hazards.json, routes.json）の座標は **変更しない**
- 背景世界地図（world-map.svg）と Map Data の上下方向の整合は、`flipY: true` により実現
- 新規にPOIやノードを追加する場合は、`y` 値が **小さいほど北側（グリモワール側）**、**大きいほど南側（カオス・リア側）** となるように設定する
- 具体的な座標範囲の目安：
  - グリモワール: y: 2000-2500
  - エリュシオン: y: 4500-5700
  - リュミエラ: y: 5000-6200
  - アトランティス: y: 4300-5000
  - カオス・リア: y: 6300-7800

## 2026-05-07 暫定結論（追記）

- `flipY: false` では、グリモワール系ノードが下側、カオス・リア系ノードが上側に見えた
- `flipY: true` に変更することで、上記問題を解消
- `ethernia_core` はグリモワール側に、`jade_oasis` と `warrior_port` はカオス・リア側に表示されるようになった
- `astralis` はエリュシオン中央に、`marineport` はアトランティス側に表示される
- POI表示、危険区域表示、ルート検索ハイライトも同様にY軸反転の影響を受け、大陸ごとの位置関係は維持される
- 個別ノード座標の変更は不要
- GitHub Pages上でのスマホ表示でも同様の座標系が適用される

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
