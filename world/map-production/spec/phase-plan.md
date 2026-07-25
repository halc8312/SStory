---
type: "overview"
category: "maps"
title: "高精細ディープズーム地図 Phase 0–7 制作計画"
version: "1.2.0"
created: "2026-07-19"
last_updated: "2026-07-25"
author: "Codex"
tags: ["maps", "deep-zoom", "image-generation", "vision-qa", "github-pages"]
status: "draft"
document_kind: "navigation"
summary: "画像生成、Vision QA、正典照合、タイル化、公開を一つの再現可能な工程として管理する計画です。"
---

<!-- cspell:words metatiles -->

# 高精細ディープズーム地図 Phase 0–7 制作計画

## 目標

既存の一枚絵を、世界から地域・都市へ段階的に拡大できる有限ディープズーム地図へ移行します。Google Maps と同じ世界測量サービスを作る計画ではなく、SStory の正典範囲について、ズーム時に新しい意味情報が現れ、輪郭がぼやけない同等の操作感と情報階層を実現します。

画像生成は地形・植生・建築の画風にだけ使用します。座標、海岸線、河川、主要道路、都市外周、地名、POI は正典データとブラウザのベクター層で固定します。

## 全体フェーズ

| Phase | 成果物 | 完了ゲート | 状態 |
| --- | --- | --- | --- |
| 0 | 現行地図、データ、表示、テストの基準線 | 退避可能、デスクトップ/モバイル基準画像、全テスト成功 | 完了 |
| 1 | EA-WORLD-1 地理正本、地名辞書、25 map sheets | ID・親子関係・出典・推定状態が検証可能 | 完了 |
| 2 | manifest、QA schema、形状検証、タイル生成、制御図 | 同じ入力から再現でき、CIで不整合を停止 | 完了 |
| 3 | Leaflet 深度地図 v3、512 px WebP pyramid | z0–z3実読込、フォールバック、モバイルUI、エラー0 | 完了 |
| 4 | ゴールデン画風と代表回廊/地域 | 94点以上、即時不合格0、独立二回確認 | 実施中 |
| 5 | 全14地域、世界・5大陸合成、回廊・2都市の高精細ラスタ | 23 bounded sheetをaccepted以上で網羅し、各地域90点以上、新生態域初回94点以上、正典照合 | 未着手 |
| 6 | 世界・大陸・地域・都市ラスタの遅延読込とズーム遷移 | 親子連続性、隣接継ぎ目、負荷、操作性を実ブラウザで合格 | 未着手 |
| 7 | GitHub CI、PR、Pages公開、切戻し手順 | Linux/Windows CI成功、公開URL確認、旧版保持 | 実施中（Draft PR準備） |

## Phase 4: ゴールデン画風

1. 共通style boardを三案生成し、可読性、線密度、平面性を比較します。
2. 最良候補を編集元として固定し、再試行では一度に一つだけ変更します。
3. 90度真上視点、文字なし、正典形状を動かさない、ベクター用余白を必須条件にします。
4. 代表回廊 `sheet_corridor_astralis_port_zephia` と、その親地域で画風を再現します。
5. 制御図、親画像、隣接画像、ラベル/道路/POI重畳、デスクトップ/モバイルの全確認を終えてからゴールデン指定します。

### Phase 4 の分離制作単位

全体図を一度の画像生成で完成させようとすると、正典形状の移動、山岳の斜視化、8山系の結合、矩形パネル、反復模様が同時に発生します。そのため、ゴールデン候補は次の独立資産に分けて作ります。

1. `canonical base` — 海岸、河川、島、森林端、都市、道路、耕地を固定した座標基準。画像生成の出力で置換しません。
2. `ground material` — 北東高地の平坦な矩形下地だけを、周囲へ連続する紙・土・インク粒子へ再構成した背景資産。
3. `eight-system scalar relief` — 正確に8群へ分離した、90度真上視点の連続標高資産。各群は主稜線、支稜、鞍部、谷、静かな斜面を持ちます。
4. `microtexture carrier` — 拡大時の情報量だけを補う非意味的な微細素材。白粒、短線束、指紋、シダ、反復タイルを禁止します。
5. `protected composite` — canonical body mask と protected-feature mask により許可領域だけを合成した候補。許可外は基準画像とバイト一致させます。

ImageGenは `ground material` と `eight-system scalar relief` の候補作成・編集に使い、座標ロックと最終合成は決定論的な処理で行います。生成画像は完成マスターとして直接昇格させず、役割を限定した donor としてSHA-256固定します。

### Phase 4 の採用順序

```text
背景素材の単独Vision合格
  -> 8山系標高の単独Vision合格
  -> canonical baseへ保護合成
  -> 固定数値gate
  -> Root Vision 94点以上
  -> SHA非開示の独立Blind Vision 2名が双方94点以上
  -> Golden固定
```

背景または標高の単独審査で落ちた資産は、合成や数値調整へ進めません。数値gateを通っても、Vision上で地形として読めなければ不採用です。

### Microtexture v2-r4 の先行凍結

r3は一回限りcalibrationでreject detection 48%となり、不合格のまま閉鎖しました。再実行・再label・retuneは行いません。新しいGolden候補を生成する前に、freshな候補・foundation非依存authority `scripts/map-production/microtexture-v2-r4/` をGitへ凍結します。Calibrationとholdoutは各140 controls、full 200% 24頁と4象限400%各24頁、計120頁です。実装は5 viewのexact ID / order / integer crop / scale、4象限のgap / overlapなし、page間code順をruntimeでも証明します。私が全5 viewの全頁・全codeを匿名状態で確認し、固定regular pathのreviewed label bytesをmarker後・測定前に別の固定pathへexclusive封印して、calibration、fresh ImageGen v7 locked clean reference、事前登録済み独立reviewer receipt、未使用holdoutをそれぞれ一回だけ実行します。全candidate、per-code result、endpoint count / rate、最終passは保存前とauthority再読込時に入力から再計算し、terminal holdoutもactual artifactsとsecret-derived identityまでread-back再結合します。各stageは全検証後にexact-schema completionを最後の操作として書き、normal failも`passed:false`で完了を記録します。例外時はcompletionを欠き、failure reportとの共存もauthority loaderが拒否します。Sparse familyは0..9のexact count、位置は全てsecret-derived、paired polarityは同一reference / unsigned geometryの符号反転だけです。一段でも失敗した版はthresholdを調整せず閉じ、marker後の例外も専用failure reportへ残します。

r4は、200%で見た領域と完全一致する中央256×192だけを測り、単一の高周波占有率hard gateを完全compositeとして選びます。Blob・finite-line・parallel-pairは非blocking diagnosticです。v7 locked clean referenceはexact metric windowの全4象限400%確認を含めRoot / independent Visionとも97点ですが、freeze前の数値計測、threshold選択、production donor、Golden、最終pixelへの利用を禁止します。Holdout control生成時とholdout marker前の双方で、current receipt HEADにあるv7本体とgeneration chain / receipt、Root / independent Vision QAをtracked bytesとspec SHAへ再照合します。`k3-v246-imagegen-ground-material-donor-v5.png` も較正から除外し、r4 holdout合格後にreference / mask erosion / overlap-seam / color-alpha-resampling / production holdoutを新規事前登録するproduction residual derivationでだけ使用できます。

## Phase 5: 14地域の生成順

最初にエリュシオンの6地域で、都市、平原、山岳、森林、港の主要生態表現を固めます。その後、浮島、熱帯、砂漠、オアシス、海洋/海底、時空地域へ展開します。

1. 王都地方
2. 銀の平野
3. 天翔山脈
4. 月影の森
5. 翡翠平原
6. ポートゼフィア港湾圏
7. リュミエラ・アーチ
8. エメラルド・ベルト
9. 紅海砂漠
10. 翡翠のオアシス
11. マリンポート地方
12. アトランティア
13. 時空の港
14. エターニア・コア

各生成には、同じゴールデン画像、当該地域の制御図、親ズーム画像、四方向の隣接重複帯、地域固有の正典要件を渡します。画像へ地名は描かせません。公開用ラベルは `gazetteer.json` のみを使います。

### 採用する制作経路

Phase 5 の実制作は、ImageGenを99枚の地理正本そのものへ使う方式ではなく、次のハイブリッド方式とします。

1. ImageGen由来の代表画像を、独立二回のVision QAで94点以上となるGolden画風として固定します。
2. 海岸線、河川、主要道路、都市外周などの意味を持つ形状は、正典GeoJSONから契約解像度へ直接かつ決定論的に描画します。
3. 紙、インク、植生、地形記号、微細な質感だけをGolden画風へ合わせます。テクスチャの乱数はEA-WORLD-1座標へ固定し、親子・隣接画像で同じ座標が同じ見え方になるようにします。
4. この経路は `deterministic-canonical-render` として、renderer、設定、seed、Golden、制御図、全正典ソース、出力、QAのSHA-256を記録します。
5. 既存の99 metatile ImageGen経路とreceipt検証は将来の再生成用に保持しますが、Phase 5の採用品を装うための疑似receiptや拡大画像は作りません。

この変更は解像度契約を弱めません。99 metatileを個別生成した場合のrawだけで約0.9GBとなり、現行の画像生成出力寸法とも一致しません。ハイブリッド方式では契約どおり233.8MPの23 masterを保ちながら、生成揺れ、継ぎ目、正典形状の移動を抑え、公開用には採用済みWebPとタイルだけを配置できます。

14地域の採用後、ゴールデン回廊1枚、アストラリス市街1枚、ポートゼフィア市街・港湾1枚を合わせたdirect master 17枚を `idx17` source indexへ固定します。その17枚から世界を先に作らず、独立確認済みの大陸5枚を決定論的に合成して `idx22` を作り、最後にその5大陸から独立確認済みの世界1枚を合成して `idx23` を作ります。依存連鎖は `17 direct -> idx17 -> 5 continent -> idx22 -> world -> idx23 -> 23 sheets / 1350 tiles` です。

三つのsource indexと最終build rootは、いずれも追跡対象の `world/map-production/releases/` 以下に版付きで保存します。最終タイルbuildは23件を厳密に含む `idx23` を `--source-index` で指定した場合だけ実施し、作業用 `tmp/` や非追跡の出力を公開候補には使いません。boundsが確定している23 map sheetsを公開ゲートで網羅し、bounds未解決の地区・街区2枚は推測生成せず、`planned/unresolved`のまま別の正典レビュー対象とします。

## 画像生成とVision QAの反復

```text
正典データ + 制御図 + ゴールデン画像 + 版管理プロンプト
  -> 1候補を生成
  -> 寸法・形式・ハッシュ・manifest検査
  -> 私が原寸/拡大/九領域をVision確認
  -> 制御図・親・隣接・ベクター重畳を確認
  -> accepted / revise / rejected
  -> revise時は問題を一つだけ変えて次版を生成
```

通常地域は90点以上、ゴールデン画像と新しい生態域の最初の画像は94点以上かつ独立二回確認を要求します。海岸・河川・主要道路・城壁の移動、必須地点欠落、AI文字、透かし、遠近法、継ぎ目、不自然な反復は点数に関係なく不採用です。

各map候補は必ず同一native PNGから次の5枚だけを作り、私が5枚すべてを確認してから次の生成へ進みます。

| View | 用途 | 主な確認 |
| --- | --- | --- |
| native | 全体と正典保護 | 海岸・河川・都市・道路・耕地、全体の色と境界 |
| full25 | 最小表示 | 8群の可算性、主従、地図全体でのノイズ量 |
| full50 | 中間表示 | 背景への馴染み、群間の分離、道路との干渉 |
| highland200 | 地域拡大 | 稜線・支稜・鞍部・谷の階層、素材の自然さ |
| highland400 | 最大確認 | 新しい情報の増加、反復・穴・線束・生成破綻 |

次は点数に関係なく即時不採用です。

- 8山系の結合、分裂、9群目、または25%で8群を数えられない状態
- 斜視の三角山、山の側面、台座、切抜き輪郭、共有された投影方向
- 矩形パネル、硬い継ぎ目、body halo、白い粒・錠剤・穴・クレーター
- 根、川、血管、指紋、等高線ループ、シダ、魚骨、短線束、反復タイル
- 200%から400%で意味のある地理情報が増えない状態
- protected geometry の移動、欠落、追加、または許可外のピクセル差分

自動QAの連続量・正典gateは固定したまま維持します。Primary gateは `coverage50/25 >= 365/338`、`quiet = .908–.925`、`orientation <= .14`、`texture4 = .615–.64`、`texture8 = 1.10–1.20` です。A/unit/totalの `sub8_energy_fraction <= .42`、A/unit repetition `<= .05`、total repetition `<= .07`、各bodyのunit sigma4 energy `>= 29`、sigma8 energy `>= 34`、exact-eight geometry、permission/protected/road/lock不変、closed loop・white crest particleゼロも維持します。

r4 holdout合格後は、旧 `sub8 component == 0`、raw `dash == 0`、raw short-bundle pair `== 0` をlegacy diagnosticへ降格し、preregistered residual referenceとeligible-background mask上の単一 `microartifact_occupancy_per_mp` gateへ置換します。Blob・finite-line・parallel-pairとraw件数はreceiptへ残しますがhard判定へ混ぜません。r4合格前にこの置換を先取りせず、合格後もthresholdを候補に合わせて変更しません。

一画像は最大5回までとします。同じ欠陥が2回続けば画像編集を中止し、制御図かプロンプトを直します。採用画像だけを `masters/` と公開アセットへ昇格し、不採用画像は制作記録として残します。

## Phase 6: 表示統合

- 世界地図は軽量なz0–z3タイルを最初に表示します。
- 大陸/地域/都市ズームへ入った時だけ、表示範囲と交差する採用済み画像を遅延読込します。
- 公開境界はschema 2の `sstory-sheet-tile-index` とし、世界root 1枚は切戻し可能なbase release、残り22枚は親子関係付きの遅延読込sheetとして扱います。23枚すべてがaccepted以上でなければruntime indexを生成しません。
- 各sheetは固有の `metadata.json` と相対 `{z}/{x}/{y}.webp` を持つ512px pyramidとして `docs/assets/images/maps/tiles/{release-id}/` 以下のversion directoryへ固定し、full-master WebPをブラウザへ渡しません。詳細は `sheet-tile-publication-contract.json` に従います。
- ラスタ画像は地形背景、GeoJSON/JSONは道路、拠点、POI、危険区域、地名として重ねます。
- 地域画像が未生成、通信失敗、またはmanifest不正の場合は親ズーム画像へ戻します。
- デスクトップ、390×844モバイル、キーボード操作、低速回線相当で検証します。

## Phase 7: GitHub公開

1. `idx23` を必須入力にした版付き・追跡対象release rootの最終buildで、23 sheet、1350 tile、寸法、ハッシュ、出典、QA判定を再検証し、`$finalRoot`を`git add`します。
2. `node scripts/run-python.js scripts/map-production/publish_phase5_tiles.py $finalRoot --docs-root docs` で、不変の版付きタイルtreeを `docs/assets/images/maps/tiles/{release-id}/` へ配置します。publishを省略してfinalizerを先に実行してはいけません。
3. `npm run map:production:finalize -- release-candidate $finalRoot` を実行し、厳格なrelease-candidate検証を通します。
4. 公開既定値を切り替えないrelease-candidate専用URLに対し、`npm run map:production:browser-qa -- --url "${previewBaseUrl}?release-preview=world-v3" --output-dir $browserQaRoot` を実行します。固定版Playwright CLI 0.1.17のハーネスは1440×1000デスクトップ、390×844モバイル、400ms以上の低速タイル応答、Royal子タイル503時のエリュシオン親保持を実ブラウザで確認します。world-v3基底tileはHTTP 200だけでなくLeafletの実decode完了とfallback未使用を必須にし、console/network/page errorは最終スクリーンショット後に固定collectorから再収集します。受領証は実デコード可能な非blankスクリーンショット、アクセシビリティsnapshot、raw evidenceから再導出する診断に加え、release/index、実行時JS/CSS/JSON、Royal親子manifest、実配信tile、QAハーネスのSHA-256を固定します。ここまでの検証に失敗した場合は停止し、`published` へ進めません。
5. ブラウザQA合格後だけ `npm run map:production:finalize -- published $browserQaReceipt` を実行します。finalizerはreceiptと現在のrelease-candidate全バイトを再照合し、検証済みbundleを `world/map-production/releases/world-v3-phase6-browser-qa/` へコピーしてreceipt/tree hashをpublished readinessへ固定します。PASSでなければ一切変更しません。直後に `npm run map:production:receipt` をリポジトリへの最後の書き込みとして実行し、同じbrowser QA bindingをpublication receiptへ継承します。公開後の検証でもruntime依存物とworld-v3 release treeをPhase 6時点のSHA-256へ再照合し、publication時刻がbrowser QA完了時刻より前なら拒否します。receipt永続化前の `published` readinessはfail-closedで失敗します。
6. 全Node/Pythonテスト、frontmatter、map production検証をローカルで成功させ、専用ブランチへ意図した変更だけをcommit/pushしてDraft PRを作成します。
7. Ubuntu / WindowsのGitHub Actions成功後にPRをReadyへ切り替えてsquash mergeし、続けて `main` CI成功を確認します。
8. `main:/docs` のGitHub Pagesで実タイル、モバイルUI、フォールバック、公開URLを確認します。
9. 公開後の切り戻しは公開commitに対する `git revert` のPRで行い、v1/v2を残したままv3だけを戻します。修正版では既存version directoryを上書きせず、新しいrelease IDを使います。

手順2–5の変数と実行順は次で固定します。`PHASE5_PREVIEW_URL`にはqueryを含まないpreview base URLを設定します。

```powershell
$finalRoot = "world/map-production/releases/world-v3-phase5-v1"
$previewBaseUrl = $env:PHASE5_PREVIEW_URL
if ([string]::IsNullOrWhiteSpace($previewBaseUrl)) {
  throw "Set PHASE5_PREVIEW_URL to the query-free release-candidate preview base URL."
}
$browserQaRoot = "tmp/map-production/phase6-browser-qa/world-v3-v1"
$browserQaReceipt = "$browserQaRoot/phase6-browser-qa-receipt.json"

node scripts/run-python.js scripts/map-production/publish_phase5_tiles.py $finalRoot --docs-root docs
git add -- docs/assets/images/maps/tiles/world-v3 docs/data/map/sheet-tiles-v3.json docs/data/map/region-rasters.json
npm run map:production:finalize -- release-candidate $finalRoot
npm run map:production:browser-qa -- --url "${previewBaseUrl}?release-preview=world-v3" --output-dir $browserQaRoot
npm run map:production:finalize -- published $browserQaReceipt
npm run map:production:receipt
```

### Phase 5実行順序（Golden v2受入直後から）

buildは必須の `--target-stage` で段階を固定します。ただし実行はidx22から始まりません。Golden v2がexact master、automated QA、Root review、匿名packet、異なる2名のblind-independent review、acceptance receiptを伴ってtracked manifestでacceptedになった直後から、次の順序を一つも省略せず実行します。全Python toolは環境差を避けるため `node scripts/run-python.js` 経由で起動します。

1. `validate_resolution_contract --check-catalog`、metatile/parent controlの`--verify-existing`、`validate_phase5_vision_focus_boxes`を実行します。
2. `render_phase5_reviewed_master --all-generation --emit-masks`でdirect 17と各枚のobserved land/transport maskを`tmp/map-production/phase5-reviewed-v2/`へ生成します。Golden preview、full-spatial preview、global-neutral previewの各flagは禁止です。
3. 17 renderer reportsから`build_phase5_assets canonical-provenance`を作り、`promote_phase5_renderer_outputs.py`で`world/map-production/masters/world-v3-direct17-v1/`へ昇格します。
4. master rootを先に`git add`します。これはcommit指示ではなく、exact-five emitterがsourceを`git ls-files`で固定するための入力条件です。
5. direct各枚でautomated QAを通した後、canonical registryのfocusを使って`native/full25/full50/focus200/focus400`を確認します。TEMP PNGはcommitせず、emitter自身が`$evidence/$sid/view-bundle.json`とそのsheet directoryをatomicに作ります。callerは`$evidence` version parentだけを先に作り、sheet directoryを作りません。`create_qa_report`はtracked receiptだけを受理するため、emitter直後にそのreceiptを`git add`してから、採否JSONを`$vision/$jobId-review-a.json`、strict時の二件目を`$vision/$jobId-review-b.json`へ保存します。
6. 5枚すべてを実際に見たreviewerだけが`reviewer_confirmed_exact_five=true`にできます。90点・1名のstandard directは`sheet_region_atlantia_region`、`sheet_region_emerald_plains_region`、`sheet_region_ethernia_core_region`の3枚だけで、残る14枚は94点・異なる2名を要求します。
7. `assemble_phase5_direct_records`からexact 17 recordsを作り、`write_phase5_source_indexes --stage idx17`でidx17を固定します。
8. idx22 buildで5大陸だけを合成し、validate・build rootのstage・独立parent-control automated QA・exact-five・Golden reviewersとは別人のblind review exact 1件を完了します。新しいreceipt/report/automated QAを再度`git add`してから、composite recordsとidx22を書きます。
9. idx23 buildで世界だけを合成し、同じQA順序を完了します。worldのreceipt/report/automated QAを再度`git add`してからworld recordとidx23を書きます。
10. exact idx23だけを入力にfinal buildを行い、合成せず23 masters / 1350 tilesを再検証して、final build rootを`git add`します。

主要コマンドは次の順です。各`$sid`のautomated QA、exact-five、job-prefixed review templateを作る完全なPowerShell loopは[`../README.md`](../README.md#golden-v2受入後からfinalまでの完全runbook)を正規runbookとします。

```powershell
node scripts/run-python.js scripts/map-production/validate_resolution_contract.py --check-catalog --json
node scripts/run-python.js scripts/map-production/render_phase5_metatile_controls.py --verify-existing
node scripts/run-python.js scripts/map-production/render_phase5_parent_control_masks.py --verify-existing
node scripts/run-python.js scripts/map-production/validate_phase5_vision_focus_boxes.py --json

$golden = "world/map-production/candidates/style-candidate-k-v3-golden-v2.png"
$goldenSha = (Get-FileHash -LiteralPath $golden -Algorithm SHA256).Hash.ToLowerInvariant()
$finalRoot = "world/map-production/releases/world-v3-phase5-v1"
node scripts/run-python.js scripts/map-production/render_phase5_reviewed_master.py --all-generation --emit-masks --output-dir tmp/map-production/phase5-reviewed-v2/world-v3-direct17-v1 --golden-style $golden --golden-style-sha256 $goldenSha --material-atlas world/map-production/style-assets/phase5-cartographic-material-atlas-v1.png --highland-detail-exemplar --canonical-control-index world/map-production/controls/phase5-metatiles/index.json
# 17 reports: canonical-provenance, then promotion and git add of tracked masters
# 17 masters: READMEのloopでautomated QA、exact-five receipt、job-prefixed blind-independent reports
node scripts/run-python.js scripts/map-production/assemble_phase5_direct_records.py --masters-root world/map-production/masters/world-v3-direct17-v1 --automated-root world/map-production/qa/automated/phase5-world-v3-v1 --vision-root world/map-production/qa/phase5-world-v3-v1/vision --output world/map-production/releases/world-v3-source-indexes/world-v3-direct17-records-v1.json
node scripts/run-python.js scripts/map-production/write_phase5_source_indexes.py --stage idx17 --records world/map-production/releases/world-v3-source-indexes/world-v3-direct17-records-v1.json --golden-style $golden --output world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx17.json

node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage idx22 --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx17.json --output-root world/map-production/releases/world-v3-idx22-build-v1 --release-id world-v3
# validate+stage, 5 continent automated/exact-five/review, QA rootsを再stage, composite bundle, idx22 writer
node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage idx23 --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx22.json --output-root world/map-production/releases/world-v3-idx23-build-v1 --release-id world-v3
# validate+stage, world automated/exact-five/review, QA rootsを再stage, composite bundle, idx23 writer
node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage final --tiles --source-index world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx23.json --output-root $finalRoot --release-id world-v3
node scripts/run-python.js scripts/map-production/build_phase5_assets.py validate $finalRoot
git add -- $finalRoot
node scripts/run-python.js scripts/map-production/publish_phase5_tiles.py $finalRoot --docs-root docs
```

idx22/idx23ではtilesを禁止し、finalでは`--tiles`を必須にします。三つのbuild rootはいずれも追跡対象の`world/map-production/releases/`以下へ版付き・不変で保存します。buildが作る`qa/*.json` / `qa/*.md`は未割当scaffoldであり、build root内で編集しません。採用判断はcanonical Vision root、exact-five evidenceはcanonical evidence rootだけに記録します。既存rootを`--force`で上書きせず版を上げます。

`publish_phase5_tiles.py` は全manifest・tile・SHA・親子関係を再検証し、既存version directoryを上書きせずに公開します。既存HTMLが参照する `region-rasters.json` は、full-WebP indexではなくcanonical `sheet-tiles-v3.json` と同一内容の互換aliasへ置換します。Phase 7 finalizerの順序は必ず `release-candidate -> Browser QA -> published -> receipt` とし、receipt後にはファイルを書き換えません。

## 報告単位

生成のたびに、対象、版、変更した一点、画像パス、ハッシュ、Vision点数、採否、次の一変更を記録します。Phaseの完了時には、成果物、テスト結果、未解決リスク、GitHub上の状態をまとめます。
