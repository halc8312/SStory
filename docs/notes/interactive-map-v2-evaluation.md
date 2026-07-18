# Leaflet v2 インタラクティブマップ評価メモ

最終更新: 2026-07-18

---

## 1. このメモの目的

- `interactive-map-v2.html` を正式評価用の試験版ページとして整理する
- v1 / v2 の役割分担を明文化する
- v2 が実際に読んでいる Map Data と、v2 固有の仮実装を切り分ける
- 今後の改善 Issue を切りやすくする

---

## 2. v1 / v2 の役割分担

| ページ | 現在の役割 |
| --- | --- |
| `docs/pages/interactive-map.html` | 現行安定版。Leaflet 主表示、POI 検索、ルート検索、旧 SVG デバッグ表示、`window.EternalArcadiaLeafletMap` を維持する |
| `docs/pages/interactive-map-v2.html` | Beta / Experimental。フルスクリーン地図、Google Maps 風 UI、レイヤーパネル、統合検索バー、ミニマップなど次世代候補を評価する |

補足:

- この Issue では v1 を削除しない
- 旧 SVG デバッグ表示も v1 側に残す
- v2 は「置き換え済み」ではなく「主表示候補の試験版」として扱う

---

## 3. v2 が利用しているデータとアセット

### 3.1 v2 が fetch している JSON

`interactive-map-v2.html` は以下を `../data/map/` から読み込む。

| ファイル | 用途 | v1 と同一ソース |
| --- | --- | --- |
| `nodes.json` | ノード表示、検索、ルート検索候補 | ✅ |
| `routes.json` | 交通路表示、Dijkstra ルート検索 | ✅ |
| `hazards.json` | 危険区域表示 | ✅ |
| `continents.json` | 大陸情報 | ✅ |
| `regions.json` | 地域情報 | ✅ |
| `pois.json` | POI 表示、検索候補 | ✅ |
| `pixel-mapping.json` | 世界地図のピクセル座標対応表 | ✅ |

### 3.2 背景地図・詳細地図

- 世界地図背景: `docs/assets/images/maps/world/world-map-hires.jpg`
- ミニマップ画像: `docs/assets/images/maps/world/world-map-medium.jpg`
- 詳細マップ: `docs/assets/images/maps/continents/` と
  `docs/assets/images/maps/regions/` の画像を v2 側で直接指定

### 3.3 v2 固有の仮実装 / ハードコード

- `world/map-data/data/pixel-mapping.json` にノード・大陸・危険区域の表示座標を持ち、公開コピーへ同期する
- 深度ズーム用オーバーレイの画像パスと bounds は HTML 内にハードコード
- 大陸名ラベル、色、UI テキスト、ズーム閾値も HTML 内にハードコード
- POI 位置は `pois.json` の座標を直接使わず、`nearest_node_id` のピクセル座標から
  オフセット近似している

補足:

- v1 / v2 とも、GitHub Pages 上で参照する公開用コピーは `docs/data/map/`
- 正典データ本体は `world/map-data/data/` にあり、`sync_map_data.py` が7ファイルを同期・検査する

---

## 4. 座標系確認

### 4.1 実装差分

- v1: `docs/assets/js/leaflet-transport-map.js` で `flipY: true`
- v2: `toLatLng()` / `pixelToLatLng()` で `[IMG_H - y, x]` を使用

どちらも Y 軸反転を前提にしている。

### 4.2 代表ノード確認メモ

コード上の `pixel-mapping.json` と `nodes.json` の対応は以下。

- `astralis` → `continent_id: elysion`
- `port_zephia` → `continent_id: elysion`
- `jade_oasis` → `continent_id: chaos_ria`
- `warrior_port` → `continent_id: chaos_ria`
- `ethernia_core` → `continent_id: grimoire`
- `marineport` → `continent_id: atlantis`
- `time_port` → `continent_id: lumiera`

コード上は v1 と同じ向きで配置される想定。
実ブラウザでの見た目確認は継続タスクとして残す。

---

## 5. v1 / v2 の機能差分

| 項目 | v1 | v2 | メモ |
| --- | --- | --- | --- |
| 世界地図背景 | ✅ | ✅ | v2 は画像オーバーレイ方式 |
| フルスクリーン地図 | ❌ | ✅ | v2 の主目的 |
| 交通ノード表示 | ✅ | ✅ | どちらも `nodes.json` |
| ルート表示 | ✅ | ✅ | どちらも `routes.json` |
| 危険区域表示 | ✅ | ✅ | どちらも `hazards.json` |
| POI 表示 | ✅ | ✅ | v2 は近似配置 |
| POI 検索 | ✅ | ✅ | v1 は専用 UI、v2 は統合検索バー |
| POI focus | ✅ | ⚠️ | v2 は検索結果クリックで移動するが、v1 の専用 focus API ほど明示的ではない |
| ルート検索 | ✅ | ✅ | どちらも Dijkstra |
| ルート検索結果ハイライト | ✅ | ✅ | どちらも fitBounds 相当あり |
| 月指定 | ✅ | ✅ | 共通ルート計算規則を使用 |
| 空路なし / 海路なし / restricted 含む | ✅ | ✅ | 共通ルート計算規則を使用 |
| レイヤー切替 | ✅ | ✅ | v2 はパネル UI |
| 座標グリッド | ✅ | ✅ | v2 は初期 OFF |
| 大陸名ラベル | ❌ | ✅ | v2 独自 |
| 詳細マップ切替 | ❌ | ✅ | v2 独自 |
| ミニマップ | ❌ | ✅ | v2 独自 |
| スケールバー | ✅ | ✅ | v1 は Leaflet control、v2 は独自 UI |
| 旧 SVG デバッグ表示 | ✅ | ❌ | この Issue では v1 側に残す |
| 公開 API | ✅ | ✅ | v1 は `window.EternalArcadiaLeafletMap`、v2 は `window.EternalArcadiaMap` |
| スマホ向け CSS / タッチ最適化 | ⚠️ | ✅ | v2 の方が専用調整が多い |

---

## 6. 代表 POI 確認メモ

対象 POI:

- `astralis_grand_market`
- `astralis_royal_palace`
- `astralis_zephia_road_first_inn`
- `astralis_zephia_road_trade_yard`

確認結果:

- v2 は `pois.json` を読み込み、検索対象にも POI を含めている
- POPUP 実装もあり、POI をクリックすると名前・カテゴリ・説明を表示できる
- ただし POI 位置は親ノード基準の近似配置で、厳密な地図合わせは未完了
- POI はズーム 0.5 未満では非表示になる

評価メモ:

- 「表示はあるが位置精度は要改善」という前提で評価する
- v1 と同じ `pois.json` を使っている点は満たしている

---

## 7. ルート検索確認メモ

実装状況:

- v1 / v2 は `route-planner.js` の同じ Dijkstra 実装を使用
- 条件は `time` / `distance` / `safety` / `cost` の 4 種
- `forbidden` / `experimental` / `dangerous` / `closed` は常時除外し、`restricted` は明示許可時のみ使用
- 季節ルートは月未指定なら警告付きで候補、月指定時は `active_months` に含まれる場合だけ使用
- 検索結果は地図上でゴールドのハイライトを描き、fitBounds で全体表示する

v1 との差分:

- 表示UIとハイライト方式は異なるが、経路の可否・季節・重み計算は同じ共通モジュールを使う
- `pixel-mapping.json` は正典IDを全件含むことを Map Data validator で検査する

後続 Issue 候補:

- v1 / v2 の画面上の検索結果差分確認
- 代表ケースのスクリーンショット付き検証

---

## 8. スマホ表示確認メモ

実装上の確認:

- `@media (max-width: 768px)` / `480px` でレスポンシブ調整あり
- `isMobile` 判定でズーム挙動・慣性・タップ許容値を切り替え
- ミニマップはモバイルで非表示
- 情報パネルは下部シート風に変形
- 検索入力は iOS のズーム対策で 16px

未確認事項:

- 実機でのタップ操作のしやすさ
- ルート検索パネルとポップアップの重なり
- 長い検索結果や情報パネルの可読性

---

## 9. v2 を主表示化するための条件

必須条件:

- [x] v1 と同じ公開 Map Data を使う
- [x] `nodes` / `routes` / `hazards` / `pois` を表示できる
- [x] ルート検索と地図ハイライトが動く
- [x] Y 軸反転が v1 と整合する
- [x] v1 相当の検索オプションを揃える
- [ ] POI の位置精度を改善する
- [ ] 代表ノード・代表 POI・代表ルートの実ブラウザ確認を完了する
- [ ] スマホ実機で操作確認する
- [ ] GitHub Pages 上で継続的に致命的エラーなく動作することを確認する

推奨条件:

- [ ] 他大陸の詳細マップ画像を揃える
- [ ] v1 より見やすいことをレビューで確認する
- [ ] v1 / v2 の API 方針を整理する

---

## 10. JS / CSS 分離方針メモ

候補構成:

```text
docs/pages/interactive-map-v2.html
docs/assets/css/interactive-map-v2.css
docs/assets/js/interactive-map-v2.js
```

現時点の判断:

- 経路探索規則は `docs/assets/js/route-planner.js` に分離し、v1 / v2 で共有済み
- v2 固有の地図描画とスタイルは、評価中のため引き続き単体 HTML に置く
- 主表示化の判断後に、v2 固有CSSと描画エンジンも外部ファイルへ分離する

---

## 11. この Issue の非目標再確認

- v1 を削除しない
- 旧 SVG デバッグ表示を削除しない
- v2 に大規模な新機能を追加しない
- MapLibre を導入しない
- 背景世界地図の再生成をしない
- POI を大量追加しない
