---
type: "overview"
category: "maps"
title: "高精細地図制作"
version: "1.0.0"
created: "2026-07-18"
last_updated: "2026-07-22"
author: "halc8312"
tags: ["maps", "deep-zoom", "image-generation", "geojson", "tiles"]
status: "draft"
document_kind: "readme"
summary: "正典地理、生成ラスタ、ベクター表示を分離した高精細地図の制作・検証・公開手順です。"
---

# 高精細地図制作

このディレクトリは、世界地図を有限ディープズーム対応の地図へ移行するための正本と制作記録を管理します。

## 三層構成

1. `source/`: 海岸線、河川、道路、境界、都市外周などの決定論的な地理正本
2. `masters/`: 正本へ画風を与えた採用済みラスタ画像
3. `docs/assets/images/maps/tiles/`: 公開用の 512 px WebP タイルとベクター表示データ

画像生成は地形、建築、紙質、陰影などの視覚表現に限定します。地名、道路名、POI、縮尺、凡例は画像へ焼き込まず、ブラウザでベクター表示します。

## アセット状態

```text
planned
  -> inputs-ready
  -> generated
  -> automated-qa
  -> vision-qa
  -> accepted / revise / rejected
  -> tiled
  -> staging
  -> published
```

`accepted` になるまで既存の公開地図を上書きしません。修正は常に新しい版として保存します。

## 画風・地形の参照資産

`style-assets/` の画像はすべて役割を限定して使います。ファイル名に `golden` が含まれていても、Root Vision と独立Blind Visionのゲートを通らない画像はGoldenではありません。

- `k3-v18-reconstruction-base.png`: 海岸、河川、島、都市、道路、耕地の座標基準。最終合成のbaseです。
- `k3-v55-topographic-contour-atlas.png`: 正確な8山系の輪郭・峰・鞍部・谷の位相権威です。完成画の背景や4×2配置は転写しません。
- `k3-v64-integrated-orthographic-relief-donor.png`: 北東高地を周囲へ自然に接続する統合素材と連続した広域起伏のdonorです。反復するシダ状細部と全体図の生画素は使用しません。
- `k3-v159-scalar-relief-structure-donor.png`: ImageGen由来の条件付き標高構造donorです。各bodyの正規化した低・中周波だけを使用し、生画素、絶対輝度、白い峰、シダ状微細模様、halo、背景は使用しません。
- `highland-detail-exemplar-v1.png`: 拡大時の素材密度の比較用です。正典形状やGolden判定の代用にはしません。
- `phase5-cartographic-material-atlas-v1.png`: Phase 5 の紙、インク、植生、地表素材の比較用です。

各資産の生成プロンプト、入力順、SHA-256、Root Visionの採用範囲は `prompts/` と `qa/` に固定します。

## Golden 候補の二段階昇格

`scripts/map-production/promote_style_candidate_k3_golden.py` は K3 v20 の昇格を二段階に分離します。

1. `prepare` は、固定 TEMP root の exact v20 receipt/候補/mask/contact と全入力を SHA-256 で固定します。さらに v19 は、固定 v18、生成 layout control、exact ImageGen prompt、generation receipt、全 authority を列挙した永続 receipt と `scripts/map-production/build_style_candidate_k3_sparse_ridgeline_v19.py` の byte-exact replay が必要です。この v19 契約が未作成の間は `missing exact v19 provenance contract` で停止します。raw/final の同一バイト、永続パスだけの正規化 receipt、自動検査を確認しても、manifest は `planned -> inputs-ready -> generated -> automated-qa` までしか進みません。
2. `accept` は、同じ master SHA-256 を確認した、別 reviewer による二つの `blind-independent` Vision QA を要求します。manifest input role は `independent-vision-review-a` と `independent-vision-review-b` のちょうど二つで、primary report もそのどちらかでなければなりません。reviewer 同一性は Unicode NFKC、全 whitespace の圧縮、casefold 後に比較します。両方が個別に 94 点以上かつ即時不合格ゼロの場合だけ、`vision-qa -> accepted` を記録します。

TEMP receipt、TEMP 画像、自動検査は Golden 採用の証拠にはなりません。昇格ツールやポリシーが存在すること自体も、候補の採用、Phase 5 入力化、公開準備完了を意味しません。

## ディレクトリ

```text
world/map-production/
  baseline/       現行版の基準値と確認記録
  source/         EA-WORLD-1 地理正本
  schemas/        制作 manifest と QA のスキーマ
  spec/           画風、品質、座標系、公開方針
  prompts/        生成用プロンプトと版
  manifests/      画像ごとの入力、状態、ハッシュ、採否
  masters/        採用済み原寸画像
  qa/             自動検査と Vision QA の結果
  releases/       追跡対象の版付きsource indexと最終build root
```

## 互換性

- 現行 v1/v2 は保全し、新しい v3 を別ページとして構築します。
- 既存の `world/map-data/data/*.json` の ID は変更しません。
- 正典にない形状は `estimated` または `provisional` として明示します。
- GitHub Pages では公開用タイルだけを配信し、候補画像や作業キャッシュは配信しません。

詳細な工程、画像生成の反復規則、14地域の制作順、GitHub公開ゲートは [`spec/phase-plan.md`](spec/phase-plan.md) を正本とします。

## Phase 7 プレビュー公開

- 公開ページ: [`docs/pages/interactive-map-v3.html`](../../docs/pages/interactive-map-v3.html)
- GitHub Pages URL: `https://halc8312.github.io/SStory/pages/interactive-map-v3.html`
- v3 は Preview として追加し、現行 v1 と試験版 v2 のページ・導線を保持します。
- タイルmanifestを指定できない場合は、既存の高解像度世界地図を表示して操作系を維持します。
- `.github/workflows/lint.yml` は Linux / Windows の両方でリポジトリ検証、Node/Pythonテスト、地図制作検証を個別に実行します。
- 14地域、1回廊、2都市のdirect master 17枚を `idx17` に固定し、独立確認済みの5大陸を加えた `idx22`、さらに独立確認済みの世界を加えた `idx23` を順に作ります。最終buildは、追跡対象の `world/map-production/releases/` 以下にある版付き `idx23` source indexを必須入力とし、同じく版付きで追跡対象のrelease rootへ23 sheetを出力します。
- `idx23` を入力にした最終buildだけが、世界1・大陸5・direct 17の計23 sheetから512 px WebPタイル1350枚を生成できます。公開先は `docs/assets/images/maps/tiles/{release-id}/`、正規indexは `docs/data/map/sheet-tiles-v3.json`、互換indexは同一バイトの `docs/data/map/region-rasters.json` です。

正規buildは `--target-stage` 必須で、次の順序以外を拒否します。`idx22` / `idx23` では `--tiles` を指定できず、`final` では逆に `--tiles` が必須です。候補buildも後続のcomposite evidenceになるため、既定の `tmp/` ではなく追跡対象の版付きrelease rootへ出力します。

```powershell
python scripts/map-production/build_phase5_assets.py build --target-stage idx22 --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx17.json --output-root world/map-production/releases/world-v3-idx22-build-v1 --release-id world-v3
python scripts/map-production/build_phase5_assets.py build --target-stage idx23 --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx22.json --output-root world/map-production/releases/world-v3-idx23-build-v1 --release-id world-v3
python scripts/map-production/build_phase5_assets.py build --target-stage final --tiles --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx23.json --output-root world/map-production/releases/world-v3-phase5-v1 --release-id world-v3
```

- `release-readiness.json` が `in-progress` の間は、制作中のmanifestと実在アセットを検査しつつ最終公開条件だけを保留します。全23 bounded sheetが `accepted` 以上になった場合、またはmanifestのjobが `staging` / `published` へ進んだ場合は、保留を継続できません。
- `release-readiness.json` を `release-candidate` へ変更すると、CIは `npm run map:production:release` と同じ厳格検査を必須化し、ゴールデンの独立二回確認、QA整合、SHA/寸法/タイル再計算、bounds確定済み23 sheetのcoverageを要求します。`published` 宣言では23 sheetすべての `published` 状態も要求します。
- 最終化は `npm run map:production:finalize -- release-candidate <phase5-build-root>`、`npm run map:production:browser-qa -- --url <preview-url>?release-preview=world-v3 --output-dir <TEMP/output-dir>`、`npm run map:production:finalize -- published <phase6-browser-qa-receipt>`、`npm run map:production:receipt` の順です。ブラウザQAは固定版Playwright CLI 0.1.17で1440×1000デスクトップ、390×844モバイル、400ms以上の低速タイル応答、Royal子タイル503時のエリュシオン親sheet保持を確認します。world-v3基底tileはHTTP成功だけでなくLeafletの実decode完了とfallback未使用を必須にし、console/network/page errorは最終スクリーンショット後に再収集します。受領証は実デコードした非blankスクリーンショット、snapshot、raw evidenceから再導出する診断、release/index、実行時JS/CSS/JSON、Royal親子manifest、実配信tile、QAハーネスのSHA-256を固定します。`published` 遷移は検証済みbundleを `world/map-production/releases/world-v3-phase6-browser-qa/` へコピーし、そのreceipt/tree hashをreadinessとpublication receiptへ永続化します。公開後もruntime依存物とworld-v3 release treeを同じSHA-256へ再照合し、publication receiptの時刻がブラウザQA完了より前なら拒否します。
- `published` finalizerは `phase6-browser-qa-receipt.schema.json` と現在のrelease-candidate全バイトを再検証します。4シナリオの一つでも失敗、証拠欠落、SHA変化、別release、重複preview queryなら公開状態を一切変更しません。
- release-candidateの作成、厳格検証、またはプレビューQAのどれかが失敗した場合はそこで停止し、`published` へ進めません。finalizer自体はpublication receiptを作らず、`published` 遷移直後の `npm run map:production:receipt` をリポジトリに対する最後の書き込みにします。receiptが永続化されるまで `published` readiness検証は意図どおり失敗します。
- GitHubではDraft PRを作成し、Ubuntu / Windows CI成功後にReadyへ切り替え、squash mergeします。続けて `main` CI成功を確認してから、`main:/docs` のGitHub Pagesで公開URLを検証します。
- 公開後の切り戻しはGitHub上の履歴を消さず、公開commitを `git revert` するPRで行います。v1/v2のページ・アセット・導線は常に保持し、修正版は既存の版付きrelease directoryを上書きせず新しいrelease IDで作ります。
- GitHub Pages は `main` ブランチの `/docs` を公開元とする静的配信です。Pages用ビルドワークフローは不要です。

## 完了条件

- 世界、大陸、地域、都市、重要街区のズーム階層が連続する
- 全ラベルが正典の地名辞書に由来する
- 採用画像が自動検査と Vision QA を通過する
- デスクトップとモバイルでパン、ズーム、検索、レイヤー切替が動作する
- 旧版へ切り戻せる状態で段階公開される
