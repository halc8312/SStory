---
type: "overview"
category: "maps"
title: "高精細地図制作"
version: "1.1.0"
created: "2026-07-18"
last_updated: "2026-07-30"
author: "halc8312"
tags: ["maps", "deep-zoom", "image-generation", "geojson", "tiles"]
status: "draft"
document_kind: "readme"
summary: "正典地理、生成ラスタ、ベクター表示を分離した高精細地図の制作・検証・公開手順です。"
---

<!-- cspell:words metatiles -->

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
- `k3-v246-imagegen-ground-material-donor-v5.png`: ImageGen由来の条件付き地表位相donorです。Root Vision 94点で、相対的な低・中周波輝度だけを使用できます。RGB、色相、絶対輝度、12px未満の細部、生画素、意味形状、完成画像への直接転写は禁止します。Microtexture v2-r3～r6の較正からは除外し、r6 formal holdout合格後にも別途事前登録するproduction derivationでだけ検討できます。
- `microtexture-v2-calibration-positive-imagegen-v4.png`: ImageGen由来の目視比較専用smooth anchorです。threshold選択と数値holdoutには使用せず、高密度texture、制作候補、Golden、最終画素にも使用しません。
- `microtexture-v2-calibration-positive-imagegen-v5.png`: r3で使用済みの旧false-reject sourceです。Root Vision 94点、独立Vision 95点ですが、r3の閉鎖に伴いdevelopment historyへ固定し、r4/r5では数値・locked・productionのいずれにも再利用しません。
- `microtexture-v2-locked-clean-reference-imagegen-v7.png`: failed-and-closed r4で登録されていた旧locked-clean候補です。r4の閉鎖に伴いhistory-onlyで、r5 authority、threshold、holdout、production、Golden、最終画素には使用しません。
- `microtexture-v2-r5-foundation-imagegen-v10.png` / `v11.png` / `v12.png`: Rootと独立Visionで事前qualifyしたr5専用のfresh control/reference foundationsです。中央512×384 cropだけをsecret HMACでcontrolへ割り当てます。Control-onlyであり、threshold外の制作評価、production donor、Golden、最終画素への利用は禁止します。
- `microtexture-v2-locked-clean-reference-imagegen-v14.png`: r5 foundation corpusと独立したfresh locked-clean referenceです。Root / independent Visionは完了していますが、数値validationはcalibration threshold freeze後に一回だけ行うpending stageです。Threshold選択、production donor、Golden、最終画素への利用は禁止します。
- `microtexture-v2-r6-foundation-imagegen-v15.png` / `v16.png` / `v17.png`: Rootと2件の独立Visionで94点以上を確認したr6専用fresh control/reference foundationsです。中央512×384 cropだけをsecret HMACで割り当て、control-onlyとして使用します。
- `microtexture-v2-r6-locked-clean-reference-imagegen-v18.png`: r6 foundation corpusと独立したfresh locked-clean referenceです。Rootと独立Visionによる事前qualification済みですが、正式threshold freeze前のdecode・数値測定は禁止します。
- `highland-detail-exemplar-v1.png`: 拡大時の素材密度の比較用です。正典形状やGolden判定の代用にはしません。
- `phase5-cartographic-material-atlas-v1.png`: Phase 5 の紙、インク、植生、地表素材の比較用です。

各資産の生成プロンプト、入力順、SHA-256、Root Visionの採用範囲は `prompts/` と `qa/` に固定します。

Microtexture v2-r3、r4、r5は一回限りcalibrationで不合格となり、各failure auditへ証拠を固定した
failed-and-closed editionsです。pre-formal `dev-r6`はpopulation不足で測定前に閉鎖し、`dev-r7`は全440 recordsの
Root/独立Visionと一回限り測定後、hard-clamp score saturationによりendpoint-admissible thresholdが存在せず閉鎖しました。
`dev-r8`もfresh root/keyで全440 recordsをRoot/独立Vision確認しましたが、pre-measurement population gateで
tiny-speck-visible rejectがcalibration 3件、holdout 1件となり、測定前に閉鎖しました。`dev-r9`は一回限りの
測定まで完了したもののendpoint-admissible thresholdを得られず閉鎖しました。既存履歴のsanitized証拠は
`qa/microtexture-v2-r6-dev-r7-development-failure.json`、
`qa/microtexture-v2-r6-dev-r8-development-failure.json`、
`qa/microtexture-v2-r6-dev-r9-development-failure.json`です。

`dev-r10`は生成中のmonitor session喪失後に対応process不在を確認し、終了原因を特定しないままterminal summary、seal、completionへ到達せず、消費済み・閉鎖となりました。
Rootは閉鎖証拠として保持しますが、再実行、resume、top-up、root削除、同じkeyの使用、部分生成物の流用を禁止します。
Root/独立Vision、label seal、private reveal、analysis、測定、threshold探索は開始していません。sanitized closure証拠は
`qa/microtexture-v2-r6-dev-r10-development-failure.json`です。過去editionのcontrols、keys、labels、pixels、
identities、measurements、thresholds、holdouts、development rootsは、閉鎖証拠として保持する場合を除き再利用しません。
r6用として既にqualify済みのImageGen foundation authorityは、fresh controls/referencesの入力としてのみ継続します。

`dev-r11`はgenerationと全440 recordsのRoot/独立Vision review、reconciliation、preflight、label sealを一度だけ
完了しましたが、private reveal直後、population auditより前のsentinel auditで、holdoutのexact-zero protocol
sentinel 1件にsealed nonclean / tiny-speck判定があることを検出しました。400%での極めて薄い点状印象を、無補正の
`full-200`で各coreが直接見えるというrubricを満たさないまま数えたVision false positiveです。population aggregation、
数値metric、threshold search、holdout endpoint evaluationは未開始で、`measurement_started=false`、thresholdとholdout
performanceは`null`のままfailed-and-closedです。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r11-development-failure.json`です。匿名code/page/rowからprivate identity/pixelへのbinding、
blind key、private labels/identities/pixelsを追跡せず、raw private postmortemを起動・記録しません。rerun、resume、
relabel、retune、subset、top-up、key resampling、root削除後の再生成、およびdev-r11のroot/key/control/reference/pixel/
identity/code/commitment/label/decision/measurement/nonce/public surfaceの後続edition・formalへの再利用を禁止します。

`dev-r12`はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
auditを一度だけ完了し、両private auditはpassしました。しかしpre-measurement population auditでcalibration warningは
`10`（formal minimum `10` pass / development floor `13` fail）、holdout warningは`9`（formal minimum `10` / development
floor `13`ともにfail）でした。他の全population endpointはformal minimumとdevelopment floorをpassしました。
`measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを開始せず、thresholdとholdout
performanceは`null`です。閉鎖後にsanitized read-only postmortemを一度だけ実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json`です。dev-r12 rootを不変に保持し、rerun、
resume、relabel、retune、subset、top-up、key resamplingと、全素材・identity・nonce・public surfaceの再利用を禁止します。

`dev-r13`もgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
auditを一度だけ完了し、両private auditはpassしました。calibration warning `14`はformal minimum `10` / development floor
`13`をpassし、holdout warning `12`はformal minimum `10`をpassしてdevelopment floor `13`だけをfailしました。その他の
全endpointは両splitでformal minimumとdevelopment floorをpassしました。all-or-nothing gateにより
`measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを開始せず、thresholdとholdout
performanceは`null`です。閉鎖後にsanitized read-only postmortemを一度だけ実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json`です。dev-r13 rootは不変に保持し、rerun、
resume、relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびroot/key/control/
reference/pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputの再利用を禁止します。

唯一のsuccessor authorityは`scripts/map-production/microtexture-v2-r6/`、運用概要は
`spec/microtexture-v2-calibration.md`です。r6は各split 220 records / 118 private clustersで、200 injection records
（5 morphology families × 20 nonzero conditions × dark/light polarity）、16 exact protocol-zero sentinels、4
duplicate-audit recordsを持ちます。Rootはfull 200%と4象限400%の計185 view-pages相当を全code確認し、closed
`dev-r8`では独立Visionも全件確認しました。Detectorはgrain / spot / finite-line / parallel-bundleの4 branchを、固定
half-scale arctangent soft-unitで飽和させず最大合成し、1個のscalar thresholdだけをcalibrationでfreezeします。

r6のhonest-reviewer blindは運用上の分離です。公開manifestはopaque codeとdomain-separated HMAC commitmentsだけを
持ち、個別control/reference path・raw SHAをmarker前に出しません。closed `dev-r6`から`dev-r14`はformalへ昇格できません。

`dev-r14`はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
auditを一度だけ完了し、両private auditはpassしました。calibrationはclean `35`、warning `15`、reject `50`、severity-3
`13`、grain `12`、tiny-speck `12`、microblob `4`、spot `16`、short-line `22`、parallel-bundle `11`でした。
microblob-visible reject `4`はformal minimum `4`をpassしましたがdevelopment floor `6`をfailし、他のcalibration endpointは
両minimumをpassしました。holdoutはclean `31`、warning `16`、reject `53`、severity-3 `20`、grain `11`、tiny-speck `11`、
microblob `9`、spot `20`、short-line `22`、parallel-bundle `11`で全endpointが両minimumをpassしました。all-or-nothing
gateにより`measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを開始せず閉鎖しました。
閉鎖後のsanitized read-only postmortemは一度だけで、auditは
`world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json`です。dev-r14 rootを不変に保持し、rerun、resume、
relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびroot/key/control/reference/pixel/
identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputの後続edition・formalへの再利用を禁止します。

fresh successorは`dev-r15`です。変更するのはcalibration `artifact-microblob`の既存clear-reject 7件だけで、compact finite
Gaussian matrixはfinal index順に`9:(res0,d4,L11.4,count64,r2,sep12)`、`1:(res1,d4,L11.6,count64,r2,sep13)`、
`2:(res2,d4,L11.8,count64,r2,sep14)`、`18:(res0,d6,L11.4,count44,r3,sep15)`、
`13:(res1,d6,L11.6,count44,r3,sep16)`、`17:(res2,d6,L11.8,count44,r3,sep17)`、
`16:(res1,d5,L12.0,count52,r3,sep15)`です。calibration microblobの4 dominant-reject、全clean/warning、holdout、
他family、renderer、placement、metric、唯一のscalar threshold、tier数`5/4/7/4`、population floors、endpoint
minima/counts/ratesは変更しません。この設計はVision truth、microblob flag、reject label、endpoint membershipを保証しません。

development rootは`tmp/map-production/microtexture-v2-r6-dev-r15`、keyはそのroot内の
`private/development-key.bin`だけに置きます。schedule revisionは
`dev-r15-calibration-microblob-reject-anchor-schedule-v1`、microblob anchor revisionは
`dev-r15-calibration-quantized-microblob-reject-v1`で、変更しないwarning anchor revision
`dev-r14-quantized-direct-visible-sparse-warning-v1`を継承します。public noncesは`r6-calibration-v10` /
`r6-holdout-v10`、cluster/render/code domainsは`microtexture-v2-r6/private-condition-cluster/v10/`、
`microtexture-v2-r6/render-seed/v10/`、`microtexture-v2-r6/opaque-code/v10/`、private-reference-transform domainは
`private-reference-transform-v10/`です。public commitmentは
`microtexture-v2-r6/public-payload-commitment/v11/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`、key commitmentは
`microtexture-v2-r6/key-commitment/v9`、foundation lanesは`foundation-offset-v9` / `foundation-assignment-v9`、delta
laneは`delta-v9`、private-control-idは`microtexture-v2-r6/private-control-id/v9/`です。protocol nonceはcalibration
`751000..751015` / holdout `761000..761015`、artifact nonceは`773000..773419` / `783000..783419`、
duplicate-audit nonceは`791000..791002` / `801000..801002`です。

dev-r15生成は、tracked authorityとrunnerをfresh authority commitへfreezeしてpushし、Ubuntu/Windowsの両CIがそのexact
commitで成功した後にだけ開始します。
fresh root/keyを作り、公開byteを一つでも書く前に排他的な`generation-start.dev.json`を確定し、両splitを生成してから
summary → seal → completionの順に排他的に確定します。catchableな失敗は排他的なfailureへ固定し、failure/completionの
共存、summary/seal/completionの欠落、または外部中断はそのeditionを消費済みとして閉鎖します。transaction検証前には
Vision/analysisを開始しません。`review-crops`が同じcontact-sheet bytesからcrop-onlyで各rowへ出すnative 512×384
full-200 cropを無補正で先に判定し、
400%は同位置の再同定だけに使います。閉鎖editionの続行、再生成、key再利用、部分出力流用は禁止です。development成功後も
証拠をcommit/pushしてUbuntu/Windowsの両CIを通し、その後にだけformal authorityを別commitで最終freezeします。現時点では
formal readinessまたはformal authorityを主張しません。
fresh calibration、v18 locked-clean validation、独立threshold authority receipt、fresh holdoutは各一度だけ実行します。
全stageと別途preregisterするproduction residual derivationが合格するまで、v246候補、Golden、master、最終pixelへ
接続しません。runnerは書込み前にroot `.gitignore`をcaptured HEADへbyte-bindし、exact pathのHEAD/index非存在と
exact `/tmp*/` ignoreを検証します。development keyは値のlog・Git追跡・Visionでの読取り・後続edition/formalへの
再利用を禁止し、formal keyは生成物やlogへ永続化しません。

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

### Golden v2受入後からfinalまでの完全runbook

すべてリポジトリrootから `node scripts/run-python.js` 経由で実行します。`python` の直接起動、`--force`、preview renderer flagは正規制作に使いません。開始条件は、Golden v2 master、automated QA、Root review、匿名view packet、異なる2名のblind-independent review、acceptance receiptがtrackedされ、production manifestでacceptedになっていることです。

最初に全正典controlと23枚のVision focus registryを再検証します。

```powershell
node scripts/run-python.js scripts/map-production/validate_resolution_contract.py --check-catalog --json
node scripts/run-python.js scripts/map-production/render_phase5_metatile_controls.py --verify-existing
node scripts/run-python.js scripts/map-production/render_phase5_parent_control_masks.py --verify-existing
node scripts/run-python.js scripts/map-production/validate_phase5_vision_focus_boxes.py --json
```

direct 17枚はignored TEMPへ一括レンダーし、各renderer reportからcanonical provenanceを作ってから、版付きtracked master rootへ昇格します。以下は同じPowerShell sessionで続けて実行します。

```powershell
$golden = "world/map-production/candidates/style-candidate-k-v3-golden-v2.png"
$goldenSha = (Get-FileHash -LiteralPath $golden -Algorithm SHA256).Hash.ToLowerInvariant()
$render = "tmp/map-production/phase5-reviewed-v2/world-v3-direct17-v1"
$masters = "world/map-production/masters/world-v3-direct17-v1"

node scripts/run-python.js scripts/map-production/render_phase5_reviewed_master.py --all-generation --emit-masks --output-dir $render --golden-style $golden --golden-style-sha256 $goldenSha --material-atlas world/map-production/style-assets/phase5-cartographic-material-atlas-v1.png --highland-detail-exemplar --canonical-control-index world/map-production/controls/phase5-metatiles/index.json

Get-ChildItem -LiteralPath $render -Filter "sheet_*.report.json" -File | ForEach-Object {
  $rendererReport = $_.FullName
  $sid = (Get-Content -LiteralPath $rendererReport -Raw | ConvertFrom-Json).sheet.sheet_id
  node scripts/run-python.js scripts/map-production/build_phase5_assets.py canonical-provenance --renderer-report $rendererReport --output "$render/$sid.canonical-provenance.json" --canonical-control-index world/map-production/controls/phase5-metatiles/index.json
}

node scripts/run-python.js scripts/map-production/promote_phase5_renderer_outputs.py $render $masters
git add -- $masters
```

`git add` はcommitではなく、exact-five emitterが `git ls-files` でsourceを固定するための必須順序です。reviewer IDは実担当者のIDを環境変数へ入れます。Unicode NFKC、whitespace圧縮、casefold後にもA/Bが異なる必要があります。90点・1名のstandard directは `sheet_region_atlantia_region`、`sheet_region_emerald_plains_region`、`sheet_region_ethernia_core_region` の3枚だけで、それ以外のdirect 14枚は94点・異なる2名です。

```powershell
$run = "phase5-world-v3-v1"
$evidence = "world/map-production/qa/evidence/$run"
$vision = "world/map-production/qa/$run/vision"
$automated = "world/map-production/qa/automated/$run"
$tempVisionRoot = "tmp/map-production/phase5-vision/$run"
$reviewerA = $env:PHASE5_REVIEWER_A
$reviewerB = $env:PHASE5_REVIEWER_B
if ([string]::IsNullOrWhiteSpace($reviewerA) -or [string]::IsNullOrWhiteSpace($reviewerB)) {
  throw "Set PHASE5_REVIEWER_A and PHASE5_REVIEWER_B to the two reviewer IDs."
}

$standardDirect = @(
  "sheet_region_atlantia_region"
  "sheet_region_emerald_plains_region"
  "sheet_region_ethernia_core_region"
)
$directSids = @(
  Get-ChildItem -LiteralPath $masters -Filter "sheet_*.report.json" -File |
    ForEach-Object { (Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json).sheet.sheet_id }
)
if ($directSids.Count -ne 17) {
  throw "Expected 17 promoted renderer reports, found $($directSids.Count)."
}

# The receipt emitter owns creation of each $evidence/$sid directory.
New-Item -ItemType Directory -Force $tempVisionRoot, $evidence, $vision, $automated | Out-Null
if ($IsLinux) {
  $chmod = Get-Command chmod -CommandType Application -ErrorAction Stop
  $setfacl = Get-Command setfacl -CommandType Application -ErrorAction Stop
  foreach ($secureParent in @($tempVisionRoot, $evidence)) {
    & $setfacl.Source --remove-all -- $secureParent
    if (-not $?) {
      throw "Removing the access ACL failed for $secureParent."
    }
    & $setfacl.Source --remove-default -- $secureParent
    if (-not $?) {
      throw "Removing the default ACL failed for $secureParent."
    }
    & $chmod.Source 700 -- $secureParent
    if (-not $?) {
      throw "Final chmod 0700 failed for $secureParent."
    }
  }
}
foreach ($sid in $directSids) {
  $master = "$masters/$sid.png"
  $masterSha = (Get-FileHash -LiteralPath $master -Algorithm SHA256).Hash.ToLowerInvariant()
  $jobId = "phase5-$($sid.Substring(6))-v1"
  $threshold = if ($standardDirect -contains $sid) { 90 } else { 94 }
  $reviewerIds = if ($threshold -eq 90) { @($reviewerA) } else { @($reviewerA, $reviewerB) }
  $receipt = "$evidence/$sid/view-bundle.json"
  $tempViews = "$tempVisionRoot/$sid"

  node scripts/run-python.js scripts/map-production/audit_phase5_master.py --sheet-id $sid --source-kind canonical_render_master --master $master --provenance-report "$masters/$sid.canonical-provenance.json" --land-sea-control "world/map-production/controls/phase5-metatiles/$sid/qa/land-sea-control.png" --land-sea-observed "$masters/$sid.observed-land-sea-mask.png" --transport-control "world/map-production/controls/phase5-metatiles/$sid/qa/transport-control.png" --transport-observed "$masters/$sid.observed-transport-mask.png" --canonical-control-index world/map-production/controls/phase5-metatiles/index.json --base-manifest world/map-production/production-manifest.json --output "$automated/$sid.phase5.json"
  node scripts/run-python.js scripts/map-production/emit_phase5_vision_views.py $master $tempViews --source-sha256 $masterSha --sheet-id $sid --evidence-receipt $receipt
  git add -- $receipt

  for ($reviewIndex = 0; $reviewIndex -lt $reviewerIds.Count; $reviewIndex++) {
    $reviewLetter = @("a", "b")[$reviewIndex]
    $reviewerId = $reviewerIds[$reviewIndex]
    node scripts/run-python.js scripts/map-production/create_qa_report.py --job-id $jobId --image $master --image-sha256 $masterSha --vision-bundle-receipt $receipt --review-mode blind-independent --threshold $threshold --reviewer $reviewerId --format json --output "$vision/$jobId-review-$reviewLetter.json"
  }
}
```

LinuxではTEMP親を所有者専用mode 0700へ固定し、`setfacl`（通常は`acl` package）でaccess/default ACLを除去します。emitterも各実行時に所有者・mode・ACLを再検証するため、`chmod` / `setfacl`のどれかが失敗したら続行しません。`create_qa_report.py` はreceiptの現在bytesとGit indexのblobが完全一致することを要求するため、emitter直後の `git add -- $receipt` は順序上必須です。ここで停止し、各reviewerが5枚すべてを実際に確認してから、自分のreportの `vision_bundle.reviewer_confirmed_exact_five` を `true` にし、10 review views、8 immediate-failure gates、全scoreとsummaryを完成させます。各report filenameはassemblerが発見できる `$jobId-review-a.json` / `$jobId-review-b.json` の形から変えません。TEMP PNGはcommitしません。全reportがacceptedになった後、reportと自動QAをstageし、direct bundleとidx17を作ります。receiptは各emitter直後に正規filenameを個別stage済みであり、transaction debrisを含み得るevidence root全体はstageしません。

```powershell
git add -- world/map-production/qa/$run world/map-production/qa/automated/$run
node scripts/run-python.js scripts/map-production/assemble_phase5_direct_records.py --masters-root $masters --automated-root world/map-production/qa/automated/$run --vision-root $vision --output world/map-production/releases/world-v3-source-indexes/world-v3-direct17-records-v1.json
node scripts/run-python.js scripts/map-production/write_phase5_source_indexes.py --stage idx17 --records world/map-production/releases/world-v3-source-indexes/world-v3-direct17-records-v1.json --golden-style $golden --output world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx17.json
git add -- world/map-production/releases/world-v3-source-indexes
```

以後は必ず `idx17 -> idx22 -> idx23 -> final` の順です。idx22/idx23 build直後に `validate` と `git add` を済ませてから、その段階で新規作成したcompositeだけを自動QA・exact-five・blind reviewします。composite automated QAには直前のchild source indexと `world/map-production/controls/phase5-parents/index.json` を必ず指定し、Vision reviewerはGoldenの両reviewerと別人にします。composite reportは各sheetにつきassemblerが要求するexact 1件だけを `$jobId-review-a.json` として作ります。

```powershell
$compositeReviewer = $env:PHASE5_COMPOSITE_REVIEWER
if ([string]::IsNullOrWhiteSpace($compositeReviewer)) {
  throw "Set PHASE5_COMPOSITE_REVIEWER to an ID distinct from both Golden reviewers."
}

function New-Phase5CompositeReviewTemplate {
  param(
    [Parameter(Mandatory = $true)][string]$SheetId,
    [Parameter(Mandatory = $true)][string]$StageRoot,
    [Parameter(Mandatory = $true)][string]$ChildIndex
  )

  $master = "$StageRoot/masters/$SheetId.png"
  $masterSha = (Get-FileHash -LiteralPath $master -Algorithm SHA256).Hash.ToLowerInvariant()
  $jobId = "phase5-$($SheetId.Substring(6))-v1"
  $receipt = "$evidence/$SheetId/view-bundle.json"
  $tempViews = "$tempVisionRoot/$SheetId"

  node scripts/run-python.js scripts/map-production/audit_phase5_master.py --sheet-id $SheetId --source-kind composite_master --master $master --provenance-report "$StageRoot/build-report.json" --land-sea-control "world/map-production/controls/phase5-parents/$SheetId/qa/land-sea-control.png" --land-sea-observed "$StageRoot/qa/observed-masks/$SheetId.land-sea.png" --transport-control "world/map-production/controls/phase5-parents/$SheetId/qa/transport-control.png" --transport-observed "$StageRoot/qa/observed-masks/$SheetId.transport.png" --child-source-index $ChildIndex --parent-control-index world/map-production/controls/phase5-parents/index.json --output "$automated/$SheetId.phase5.json"
  node scripts/run-python.js scripts/map-production/emit_phase5_vision_views.py $master $tempViews --source-sha256 $masterSha --sheet-id $SheetId --evidence-receipt $receipt
  git add -- $receipt
  node scripts/run-python.js scripts/map-production/create_qa_report.py --job-id $jobId --image $master --image-sha256 $masterSha --vision-bundle-receipt $receipt --review-mode blind-independent --threshold 90 --reviewer $compositeReviewer --format json --output "$vision/$jobId-review-a.json"
}
```

idx22では5大陸だけを新規合成し、build rootをstageしてからexact-fiveを作ります。

```powershell
$idx17 = "world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx17.json"
$idx22Root = "world/map-production/releases/world-v3-idx22-build-v1"
$idx22Records = "world/map-production/releases/world-v3-source-indexes/world-v3-idx22-composite-records-v1.json"
$idx22 = "world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx22.json"
$continentSids = @(
  "sheet_continent_elysion"
  "sheet_continent_lumiera"
  "sheet_continent_chaos_ria"
  "sheet_continent_atlantis"
  "sheet_continent_grimoire"
)

node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage idx22 --source-index $idx17 --output-root $idx22Root --release-id world-v3
node scripts/run-python.js scripts/map-production/build_phase5_assets.py validate $idx22Root
git add -- $idx22Root
foreach ($sid in $continentSids) {
  New-Phase5CompositeReviewTemplate -SheetId $sid -StageRoot $idx22Root -ChildIndex $idx17
}
```

ここで5件のreportを実見してacceptedへ完成させます。各receiptはhelper内のemitter直後に正規filenameだけを個別stage済みです。reportと自動QAをstageしてからbundle/indexを書きます。

```powershell
git add -- "world/map-production/qa/$run" $automated
node scripts/run-python.js scripts/map-production/assemble_phase5_composite_records.py --stage idx22 --base-index $idx17 --build-report "$idx22Root/build-report.json" --masters-root "$idx22Root/masters" --automated-root $automated --vision-root $vision --output $idx22Records
node scripts/run-python.js scripts/map-production/write_phase5_source_indexes.py --stage idx22 --base-index $idx17 --records $idx22Records --output $idx22
git add -- world/map-production/releases/world-v3-source-indexes
```

idx23ではworldだけを新規合成します。

```powershell
$idx23Root = "world/map-production/releases/world-v3-idx23-build-v1"
$idx23Records = "world/map-production/releases/world-v3-source-indexes/world-v3-idx23-composite-records-v1.json"
$idx23 = "world/map-production/releases/world-v3-source-indexes/world-v3-source-index-idx23.json"

node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage idx23 --source-index $idx22 --output-root $idx23Root --release-id world-v3
node scripts/run-python.js scripts/map-production/build_phase5_assets.py validate $idx23Root
git add -- $idx23Root
New-Phase5CompositeReviewTemplate -SheetId "sheet_world" -StageRoot $idx23Root -ChildIndex $idx22
```

ここでworld reportを実見してacceptedへ完成させます。world receiptはhelper内で個別stage済みなので、reportと自動QAをstageしてからbundle/indexを書きます。

```powershell
git add -- "world/map-production/qa/$run" $automated
node scripts/run-python.js scripts/map-production/assemble_phase5_composite_records.py --stage idx23 --base-index $idx22 --build-report "$idx23Root/build-report.json" --masters-root "$idx23Root/masters" --automated-root $automated --vision-root $vision --output $idx23Records
node scripts/run-python.js scripts/map-production/write_phase5_source_indexes.py --stage idx23 --base-index $idx22 --records $idx23Records --output $idx23
git add -- world/map-production/releases/world-v3-source-indexes
```

finalは合成を行わず、exact idx23から23 masters / 1350 tilesを作ってbuild rootをstageします。

```powershell
$finalRoot = "world/map-production/releases/world-v3-phase5-v1"
node scripts/run-python.js scripts/map-production/build_phase5_assets.py build --target-stage final --tiles --source-index $idx23 --output-root $finalRoot --release-id world-v3
node scripts/run-python.js scripts/map-production/build_phase5_assets.py validate $finalRoot
git add -- $finalRoot
```

build rootの `qa/*.json` / `qa/*.md` は未割当のscaffoldであり、不変buildの中では編集・採用しません。採用判断の正規場所は `$vision`、view hash evidenceの正規場所は `$evidence` です。既存output rootは上書きせず、新しい版付きpathを使います。

Phase 7へ進むときは、finalizerより先に検証済みfinal buildを`docs/`へpublishします。`PHASE5_PREVIEW_URL`にはqueryを含まないrelease-candidate previewのbase URLを設定し、Browser QAの出力先には存在しないか空の版付きTEMP directoryを使います。

```powershell
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

- `release-readiness.json` が `in-progress` の間は、制作中のmanifestと実在アセットを検査しつつ最終公開条件だけを保留します。全23 bounded sheetが `accepted` 以上になった場合、またはmanifestのjobが `staging` / `published` へ進んだ場合は、保留を継続できません。
- `release-readiness.json` を `release-candidate` へ変更すると、CIは `npm run map:production:release` と同じ厳格検査を必須化し、ゴールデンの独立二回確認、QA整合、SHA/寸法/タイル再計算、bounds確定済み23 sheetのcoverageを要求します。`published` 宣言では23 sheetすべての `published` 状態も要求します。
- 最終化は上の `publish -> release-candidate -> Browser QA -> published -> receipt` の順です。ブラウザQAは固定版Playwright CLI 0.1.17で1440×1000デスクトップ、390×844モバイル、400ms以上の低速タイル応答、Royal子タイル503時のエリュシオン親sheet保持を確認します。world-v3基底tileはHTTP成功だけでなくLeafletの実decode完了とfallback未使用を必須にし、console/network/page errorは最終スクリーンショット後に再収集します。受領証は実デコードした非blankスクリーンショット、snapshot、raw evidenceから再導出する診断、release/index、実行時JS/CSS/JSON、Royal親子manifest、実配信tile、QAハーネスのSHA-256を固定します。`published` 遷移は検証済みbundleを `world/map-production/releases/world-v3-phase6-browser-qa/` へコピーし、そのreceipt/tree hashをreadinessとpublication receiptへ永続化します。公開後もruntime依存物とworld-v3 release treeを同じSHA-256へ再照合し、publication receiptの時刻がブラウザQA完了より前なら拒否します。
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
