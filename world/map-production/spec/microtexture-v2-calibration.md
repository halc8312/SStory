---
type: "overview"
category: "maps"
title: "Microtexture v2-r6 候補非依存較正契約"
version: "0.9.0"
created: "2026-07-25"
last_updated: "2026-07-30"
author: "Codex"
tags: ["maps", "quality-assurance", "microtexture", "vision-qa", "calibration"]
status: "review"
document_kind: "navigation"
summary: "Google Maps級deep zoom用の微細表現を、画像生成・Root/独立Vision・単一threshold・未使用holdoutで安全に固定する運用navigationです。"
---

# Microtexture v2-r6 候補非依存較正契約

規範的authorityは `scripts/map-production/microtexture-v2-r6/preregistered-spec.json` です。
実装・exact rubric・endpoint・hash binding・失敗処理は同directoryの `README.md`、
`PREREGISTERED-SPEC.md`、`implementation-bindings.json` を参照します。この文書はPhase計画から
規範authorityへ到達するためのnavigationであり、矛盾時はJSONとhash-bound implementationが優先します。

## 現在地

- r3、r4、r5: one-shot calibrationでfailed-and-closed。controls、keys、labels、thresholds、foundations、
  locked sources、holdoutsを再利用しません。
- dev-r6: population safety gate不合格、`measurement_started=false`で測定前に閉鎖。
- dev-r7: 両splitのpopulation gate合格。Rootと独立Visionが全440 recordsを確認してlabelをsealし、
  一度だけ測定しましたが、clamp score saturationによりendpoint-admissible thresholdが存在せず閉鎖。
  thresholdは`null`、holdout endpoint performanceは未評価です。
- dev-r7 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r7-development-failure.json`
- dev-r8: fresh root/keyで一度だけ生成し、Rootと独立Visionが全440 recordsを匿名確認・照合しました。
  label seal後のpre-measurement population gateでtiny-speck-visible rejectがcalibration `3 < 6`、
  holdout `1 < 6`となり、`measurement_started=false`のままfailed-and-closedです。再生成、再label、
  top-up、subset、key resampling、rerunは禁止します。
- dev-r8 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r8-development-failure.json`
- dev-r9: reject-tier speckの固定個数を強化し、両splitのpopulation floorを通過して一度だけ測定しました。
  calibrationでwarning acceptanceとseverity-3 detectionを同時に満たすscalar thresholdがなく、thresholdと
  holdout endpoint performanceを`null`のまま測定後に閉鎖しました。
- dev-r9 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r9-development-failure.json`
- dev-r10: 一回限りgenerationを開始しましたが、monitor session喪失後に対応process不在を確認し、終了原因を特定しないままsummary / seal / completionへ未到達。
  generation未完了、Vision review、label seal、private reveal、analysis、measurement、threshold search未開始のまま
  消費・閉鎖しました。rootを不変に保持し、rerun、resume、top-up、root削除、別key、partial output流用を禁止します。
- dev-r10 sanitized closure evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r10-development-failure.json`
- dev-r11: generation、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label sealを一度だけ完了。
  private reveal後、population audit前のsentinel auditでholdout exact-zero protocol sentinel 1件へのsealed nonclean /
  tiny-speck false positiveを検出し、数値測定前にfailed-and-closedです。400%の極めて薄い点状印象を、無補正の
  native `full-200`で各coreが直接見えるというrubricを満たさないまま数えたことがfailure boundaryです。
- dev-r11 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r11-development-failure.json`
  `measurement_started=false`、threshold / holdout performanceは`null`で、population aggregationも未開始です。
  raw private postmortem、code/page/rowからprivate identity/pixelへのbinding、private labels/identities/pixelsは追跡せず、
  rerun、resume、relabel、retune、subset、top-up、key resamplingと全dev-r11素材の再利用を禁止します。
- dev-r12: generation、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
  auditを一度だけ完了し、両private auditはpassしました。しかしpre-measurement population auditでcalibration warningは
  `10`（formal minimum `10` pass / development floor `13` fail）、holdout warningは`9`（formal minimum `10` / development
  floor `13`ともにfail）でした。他の全population endpointはformal minimumとdevelopment floorをpassしました。
- dev-r12 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json`
  `measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを開始せず、threshold / holdout
  performanceは`null`です。閉鎖後にsanitized read-only postmortemを一度だけ実行しました。rootは不変に保持し、rerun、
  resume、relabel、retune、subset、top-up、key resamplingと全dev-r12素材・identity・nonce・public surfaceの再利用を禁止します。
- dev-r13: warning capacityだけをfresh identityで一度確認するsuccessorです。metric、single threshold、population floors、
  endpoint counts/ratesは変更しません。authorityをcommit/pushし、Ubuntu/Windows CIが同じcommitで両方成功するまで
  generationを開始しません。
- formal r6: 未開始。formal CLI、one-shot marker、threshold freeze、v18 numeric measurementはいずれも未使用です。

## ImageGen入力の境界

r6 control/reference foundationは、Rootと2件の独立Visionで事前qualifyしたImageGen v15、v16、v17だけです。
各1536×1024画像の中央 `[512,320,512,384]` cropを使い、その中央
`[128,96,256,192]`だけをdetectorとVisionの共通decision windowにします。

locked-clean referenceは独立生成したImageGen v18です。calibrationとthreshold selectionへ入れず、
threshold freeze前のdecode・数値測定を禁止します。v15～v18はvalidation-onlyであり、production donor、
Golden input、master、tile、最終pixelへ転送しません。

生成画像は毎回、exact bytesを次の順で扱います。

1. 生成prompt、入力順、generation receipt、SHA-256を保存する。
2. Rootが画像そのものをVision確認する。
3. 別agentが独立Vision確認する。
4. 規定scoreと即時不合格条件を満たしたexact bytesだけをauthorityへbindする。
5. 不合格画像は別versionとして残し、既存採用画像を上書きしない。

## dev-r8 control population

この節は閉鎖済みdev-r8の事前登録契約を記録します。実行結果は、両splitでtiny-speck-visible rejectだけが
development safety floorとformal minimumを下回り、その他のpopulation endpointはすべて合格でした。
metric、threshold探索、holdout endpoint評価は開始していません。

各splitは220 records、118 private condition clustersです。

| role | records | clusters | 用途 |
|---|---:|---:|---|
| synthetic injection | 200 | 100 | 5 families × 20 conditions × dark/light polarity |
| protocol-zero | 16 | 16 | exact clean sentinel |
| duplicate-audit | 4 | 2 | clean/obvious-artifact semantic replicate |

injection familiesはfine-grain、speck、microblob、short-dash、parallel-bundleです。
各familyはdesign tierを `5 clean-candidate / 4 warning-candidate / 7 clear-reject-candidate /
4 dominant-reject-candidate` としてcoverage設計しますが、tierはVision truthではありません。
全100 clustersを採否選別せずreview/evaluateし、subsetting、top-up、replacement、key resamplingを禁止します。

dev-r8はdev-r7と異なる次の入力を必須とします。

- exact root: `tmp/map-production/microtexture-v2-r6-dev-r8`
- tracked runnerが生成するfresh cryptographic 32-byte key。生成と一回限りanalysisを結ぶため
  `private/development-key.bin`だけへ保持し、Git追跡・log・Vision processでの読取り・再利用は禁止。
  書込み前にroot `.gitignore`のcaptured-HEAD byte binding、HEAD/index非存在、exact `/tmp*/` ignoreを検証
- public nonce revision 3
- HMAC/cluster/public-commitment domain revision 3/4
- fresh parameter nonce rangesとfoundation mod-3残基を保つfamily別variant permutation
- fresh controls、private references、placements、identities、opaque codes、labels、measurements
- tracked `development_probe.py` と、そのimplementation binding
- formal root/environmentの不存在

dev-r7のkey、controls、labels、pixels、identities、measurements、diagnostic threshold、parameter nonce、
development rootはdev-r8にもformal r6にも渡しません。
development rootはGit-ignored private evidenceとして閉鎖後も不変に保持し、formal keyは従来どおりartifact/logへ
永続化しません。

## dev-r12 closure and dev-r13 successor schedule

dev-r12は両private auditをpassしましたが、warning populationがcalibration 10、holdout 9となり、両splitでdevelopment
floor 13に不足し、holdoutではformal minimum 10にも不足しました。その他の全formal endpoint minimumとdevelopment
safety floorはpassしました。all-or-nothing gateによりmetricとthreshold searchは開始せず、閉鎖後にsanitized read-only
postmortemを一度だけ実行しました。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json`です。dev-r12 rootを不変に保持し、素材、
identity、nonce、public surfaceをdev-r13またはformalへ再利用しません。

dev-r13は各familyのtier数`5 clean-candidate / 4 warning-candidate / 7 clear-reject-candidate /
4 dominant-reject-candidate`を維持します。変更対象は`artifact-speck`、`artifact-microblob`、`artifact-short-dash`、
`artifact-parallel-bundle`の既存warning-candidateをsplitごとに各4件、計16件だけです。各対象は単なるtier metadata変更ではなく、
family invariantを保った弱いがnative full-200で直接知覚可能なwarning-capacity morphology anchorへ実パラメータ変更します。
fine-grain warning、全clean-candidate、全clear/dominant-reject morphologyは変更しません。splitごとの16 anchors対development floor 13の
構造上のmiss budgetは3ですが、design tierはVision truth、warning label、endpoint membershipを保証・予告しません。
metric、rubric、single-threshold rule、formal endpoint minimum、development safety floor、endpoint counts/ratesは不変です。

dev-r9で固定したspeck reject anchorsとdev-r10で事前登録したgrain reject periodsは変更しません。speck reject側の
count scheduleは次のままです。

| split | clear-reject 7 conditions | dominant-reject 4 conditions |
|---|---|---|
| calibration | 32, 36, 40, 44, 48, 52, 56 | 64, 72, 80, 88 |
| holdout | 34, 38, 42, 46, 50, 54, 58 | 68, 76, 84, 90 |

1px hard core、最大12 L、0.08 axial shoulder、exact polarity、4象限stratification、minimum separation 10pxを維持します。
11 reject anchors対floor 6の構造上のmiss budgetは5ですが、これもVision truthの保証ではありません。

fresh dev-r13境界は次のexact identityです。

- root: `tmp/map-production/microtexture-v2-r6-dev-r13`
- key: `tmp/map-production/microtexture-v2-r6-dev-r13/private/development-key.bin`
- schedule revision: `dev-r13-warning-acceptance-anchor-schedule-v1`
- public nonce: `r6-calibration-v8` / `r6-holdout-v8`
- cluster domain: `microtexture-v2-r6/private-condition-cluster/v8/`
- render domain: `microtexture-v2-r6/render-seed/v8/`
- code domain: `microtexture-v2-r6/opaque-code/v8/`
- private-reference-transform domain: `private-reference-transform-v8/`
- public commitment domain:
  `microtexture-v2-r6/public-payload-commitment/v9/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`
- key commitment: `microtexture-v2-r6/key-commitment/v7`
- foundation offset/assignment lanes: `foundation-offset-v7` / `foundation-assignment-v7`
- delta lane: `delta-v7`
- private-control-id domain: `microtexture-v2-r6/private-control-id/v7/`
- protocol-zero nonces: calibration `551000..551015`、holdout `561000..561015`
- artifact nonces: calibration `573000..573419`、holdout `583000..583419`
- duplicate-audit nonces: calibration `591000..591002`、holdout `601000..601002`

dev-r8/dev-r9/dev-r10/dev-r11/dev-r12のkey、control、reference、label、decision、pixel、identity、placement、nonce、
commitment、rootを読み替え・再利用しません。

## 全件Visionとmeasurement gate

Rootと独立Visionは各splitの全220 anonymous codesを、full 200%とNW/NE/SW/SE 400%で確認します。
5 viewは同じcode順、nearest-neighbor拡大、完全なquadrant partitionを持ちます。`review-crops`は同じcontact-sheet
bytesからcrop-only derivativeとして各rowのnative 512×384 full-200 panelを出します。dev-r13はこのnative panelを
無補正・contrast強調なしで先に判定し、400%は同位置の再同定だけに使います。400%だけで推測できる極めて薄い点状印象は
visible morphologyへ数えません。Rootは各recordを
`clean|warning|reject`、severity 0..3、5 visible flags、EV3 locatorsで決定し、独立reviewerとの差を
画像へ戻ってreconcileし、両splitとも全220件のRoot/独立decisionがexact logical agreementにならなければ
preflightを通しません。private identityをrevealする前に両splitのlabel bytesをsealします。

private reveal後、polarity pairを `reject > warning > clean`、最大severity、visible flag ORでcluster truthへ
集約します。次のdevelopment safety floorを一つでも満たさないsplitは、metricを一度も呼ばず閉鎖します。

| population | minimum clusters / split |
|---|---:|
| clean | 19 |
| warning | 13 |
| reject | 38 |
| severity 3 | 6 |
| grain-visible reject | 10 |
| tiny-speck-visible reject | 6 |
| microblob-visible reject | 6 |
| spot-visible reject | 10 |
| short-line-visible reject | 10 |
| parallel-bundle-visible reject | 8 |

## soft-unit detector

raw detectorは中央192×256 float32 luminance residualだけを読みます。各raw evidence `x`は、
観測値を分母にせず、固定half-scale reference `ref`を使って次へ写します。

```text
unit_soft(x, ref) = 0                                      when x <= 0
unit_soft(x, ref) = (2 / pi) * atan(x / ref)              when x > 0
```

これは有限正値に厳密単調、`[0,1)`に有界、`x=ref`でexact 0.5です。dev-r7で起きたwarning/rejectの
hard ceiling同点化を構造的に除きます。grain、spot、finite-line、parallel-bundle branchのmax/min構成と
raw filterは維持し、唯一のhard metricは4 branchの最大です。

closed dev-r7のaggregate-only診断から変更するhalf-scaleは `grain_rms_l 0.7 -> 0.875`、
`tiny_mass_l 20 -> 15`、`finite_line_top4_mean_l 4.5 -> 2.25` の3件だけです。他6 reference、raw metrics、
branch構成、単一threshold、endpoint count/rateは不変です。dev-r8はmetric call前、dev-r9はthreshold選択失敗後、
dev-r10はgeneration中断、dev-r11はprivate sentinel audit失敗、dev-r12はpopulation audit失敗でmetric call前に閉鎖したため、
fresh dev-r13でのblindな再検証を必須とします。

```text
reject = max(grain_score, spot_score,
             finite_line_score, parallel_bundle_score) > frozen_threshold
```

branch別threshold、追加OR gate、diagnostic hard rejectorは禁止します。calibrationはclean acceptance 0.95、
warning acceptance 0.75を含む全endpoint count/rateを満たす候補だけから、事前登録objectiveで1 scalarを選びます。
候補がなければthresholdを`null`のままeditionを閉じます。holdoutはcalibrationでfreezeした値を変更しません。

## 安全な実行順序

1. dev-r7/r8/r9 failure audits、dev-r10 generation-interruption audit、sanitized dev-r11/dev-r12 premeasurement failure audits、
   dev-r13 spec/code/tests/runner、既存ImageGen provenance、Root/独立Vision QA authorityをcommitする。closed editionの
   code-to-private bindingやraw private materialは作成・追跡しない。
2. branchへpushし、Ubuntu/Windows CIの両方が成功したことを確認する。
3. formal root/environmentとdev-r13 root/keyが存在せず、closed dev-r10/dev-r11/dev-r12 rootsが不変に保持されていることを確認する。
4. fresh keyを作り、public byteより前にexclusive `generation-start.dev.json`を書く。
5. dev-r13 calibration/holdout controlsを一度だけ生成し、generation summary → seal → exclusive completionの順で閉じる。
   catchableな失敗はexclusive failureへ記録し、failure/completion共存またはsummary/seal/completion欠落を拒否する。
6. complete generation transactionを検証してから、Rootと独立Visionが全440 recordsを匿名確認し、Root decisionsを
   画像へ戻ってreconcileする。
7. 両splitのlabelsをsealし、private auditとpopulation safety floorを実行する。
8. gate合格時だけcalibrationを測定し、thresholdを一度だけ選択する。
9. calibration選択thresholdを変えずdevelopment holdoutへ一度だけ適用する。
10. dev-r13失敗時はsanitized failure auditをcommitし、formalへ進まない。
11. dev-r13成功時はdevelopment-only success auditをcommitし、dev-r13を閉じる。
12. success auditをpushし、Ubuntu/Windows CIの両方を再度成功させる。
13. spec SHA、trust-root tests、全implementation hashesを再計算し、formal authority freeze commitを作る。
14. push後、Ubuntu/Windows CIが再度成功してからfresh formal key/rootを作る。
15. formal calibration生成・Root Vision・one-shot評価を各一度だけ行う。
16. pass時だけthresholdをfreezeし、v18 locked-cleanを一度だけ数値validateする。
17. preregistered independent authorityがcalibration/v18を監査し、tracked receiptを作る。
18. receipt commit/push/CI成功後、fresh formal holdoutを一度だけ生成・Root Vision・評価する。
19. formal holdout pass後も、production residual derivationとuntouched production holdoutを別specで固定する。
20. その後にのみGolden、master、deep-zoom tilesへ接続する。

dev-r8/dev-r9は各failure gate、dev-r10はgeneration中断、dev-r11はprivate sentinel audit、dev-r12はpopulation auditで
閉鎖しました。上記はfresh dev-r13から再開する順序であり、dev-r13 success auditをcommit/pushして両CIを通すまで
手順13以降へ進めません。

generation start後、marker後の例外、通常endpoint failure、completion欠落はeditionを消費します。失敗後のresume、
regeneration、relabel、remeasurement、rerun、別key、threshold変更は禁止です。

## Production / Golden boundary

synthetic holdout passだけではproduction microtextureを承認しません。production source/reference、
protected-feature mask、filter-support erosion、tile overlap/halo/seam、color/alpha/resampling、zoom coverage、
master aggregation、untouched production holdoutを候補測定前に別途事前登録します。

道路、河川、海岸、文字、記号、集落、正典geometryをprotected maskから漏らしません。production derivationと
untouched holdoutを同じfrozen detector/thresholdで通過し、Rootと2件の独立Visionがexact Golden pixelsを
採用するまで、既存公開地図を上書きしません。
