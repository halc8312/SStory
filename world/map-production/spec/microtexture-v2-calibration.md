---
type: "overview"
category: "maps"
title: "Microtexture v2-r6 候補非依存較正契約"
version: "0.9.0"
created: "2026-07-25"
last_updated: "2026-08-15"
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
- dev-r13: generation、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
  auditを一度だけ完了し、両private auditはpassしました。calibration warning `14`はformal minimum `10` / development floor
  `13`をpassし、holdout warning `12`はformal minimum `10`をpassしましたがdevelopment floor `13`をfailしました。その他の
  全endpointは両splitでformal minimumとdevelopment floorをpassしました。all-or-nothing gateにより測定前に閉鎖しました。
- dev-r13 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json`
  `measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを開始せず、threshold / holdout
  performanceは`null`です。閉鎖後にsanitized read-only postmortemを一度だけ実行しました。rootは不変に保持し、rerun、
  resume、relabel、retune、replacement、subset、top-up、key resamplingと全dev-r13素材・identity・nonce・public surface・
  postmortem outputの再利用を禁止します。
- dev-r14: generation、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
  auditを一度だけ完了し、両private auditはpassしました。calibrationはclean `35`、warning `15`、reject `50`、severity-3
  `13`、grain `12`、tiny-speck `12`、microblob `4`、spot `16`、short-line `22`、parallel-bundle `11`でした。
  microblob-visible rejectはformal minimum `4`をpassしましたがdevelopment floor `6`をfailし、他のcalibration endpointは
  両minimumをpassしました。holdoutはclean `31`、warning `16`、reject `53`、severity-3 `20`、grain `11`、tiny-speck
  `11`、microblob `9`、spot `20`、short-line `22`、parallel-bundle `11`で全endpointが両minimumをpassしました。
  all-or-nothing gateにより`measurement_started=false`のままmetric、threshold search、holdout endpoint evaluationを
  開始せず閉鎖しました。
- dev-r14 sanitized evidence:
  `world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json`
  閉鎖後のsanitized read-only postmortemは一度だけです。r14のroot/key/control/reference/pixel/identity/code/commitment/
  label/decision/measurement/nonce/public surface/postmortem outputを後続editionまたはformalへ再利用しません。
- dev-r15: 一回限りのgenerationを完了し、Rootと独立Visionがそれぞれ全440 public recordsを独立確認した`440 × 2`
  review、全差分のreconciliation、official preflight、label seal、両splitのprivate auditを一度だけ完了しました。
  両private auditはpassしました。独立initial decisionの`lp` delimiter drift（calibration 29行、holdout 30行）はinitial
  snapshot/receiptに不変保存し、正規`l,p`への修正はfinal official-valid decision filesだけへ適用しました。
  pre-measurement population auditではcalibration warning `12`がformal minimum `10`をpassしてdevelopment floor `13`を
  failし、holdout warning `9`はformal minimum `10`とdevelopment floor `13`の両方をfailしました。他の全endpointは
  両splitで両minimumをpassしました。数値metric、measurement、threshold searchは開始せず、thresholdは存在しません。
  閉鎖後のsanitized read-only postmortemは一度だけです。auditは
  `world/map-production/qa/microtexture-v2-r6-dev-r15-development-failure.json`（raw SHA-256
  `faa420e63af8b3f647e045ae4d71ac2fbe32316175e68999cc16b3e278311200`）です。r15のroot/key/control/reference/
  pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputを後続editionまたはformalへ
  一切再利用しません。
- dev-r16: 一回限りのgeneration、Root/独立Visionによる各440-record blind review、reconciliation、official preflight、
  label seal、private revealを各一度だけ完了しました。両official initial snapshots/receiptsは不変です。calibration
  protocol-zeroは`16/16` clean、holdoutは`15/16` cleanでしたが、残るexact-zero 1件がseverity-1 short-line warningとなる
  localized-line false positiveでした。duplicate-auditは両splitともpassしました。population aggregation、numeric measurement、
  threshold searchは未開始のまま`failed-and-closed-before-measurement`で閉鎖し、read-only postmortemを一度だけ実行しました。
  auditは`world/map-production/qa/microtexture-v2-r6-dev-r16-development-failure.json`、raw SHA-256は
  `4637978a7ac5d59c99ec076e527b7be6e5d2ad1c0477077e2587fda7091ca169`です。r16素材・private materialは一切再利用しません。
- dev-r17: 一回限りのgenerationで両split合計440 public recordsを生成し、Root/Independentが各440件を独立確認した
  `440 × 2` reviewを完了しました。両official initial snapshots/receiptsは不変です。全差分（calibration: logical 97件 +
  notes-only 17件、holdout: logical 84件 + notes-only 60件）をreconcileし、final bilateral initial visible-flag intersection gate、
  official preflight、両splitのprivate auditはpassしました。
  population counts（clean、warning、reject、severity 3、grain、tiny-speck、microblob、spot、short-line、parallel-bundle）は、
  calibration `27, 22, 51, 11, 11, 11, 10, 20, 20, 10`で全formal minimum / development floorをpass、holdout
  `30, 30, 40, 28, 11, 0, 9, 9, 20, 10`でした。holdout tiny-speck `0`はformal `4` / development `6`をfail、spot `9`は
  formal `8`をpassしてdevelopment `10`をfailし、他endpointは両minimumをpassしました。all-or-nothing gateにより数値metricを
  呼ばず、thresholdを作らないままfailed-and-closedです。閉鎖後のsanitized read-only postmortemは一度だけです。auditは
  `world/map-production/qa/microtexture-v2-r6-dev-r17-development-failure.json`（raw SHA-256
  `2177b04b6f79b75394cbdef6204423194603cd81e3a84b5a673c58393ccf5856`）です。r17の全素材・outputはformalまたは
  後続editionへ一切再利用しません。
- dev-r18: statusは`failed-and-closed-before-population-audit`です。exact roleは
  `development-only prepopulation private-audit failure evidence; generation, both blind 440-record reviews, bilateral reconciliation, official preflight, label sealing, private reveal, regeneration, and protocol-zero audits each completed exactly once, but calibration's obvious-artifact duplicate pair had identical reject dispositions and short-line flags with ordinal severities 2 and 3, so the then-exact severity semantic check failed before population audit or any numeric measurement; one read-only postmortem ran exactly once, all initial snapshots and receipts remain immutable, and no dev-r18 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
  です。auditは`world/map-production/qa/microtexture-v2-r6-dev-r18-development-failure.json`、raw SHA-256は
  `7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122`です。
- dev-r19: statusは`failed-and-closed-before-population-audit`です。exact roleは
  `development-only prepopulation private-audit failure evidence; generation, both blind 440-record reviews, bilateral reconciliation, official preflight, label sealing, private reveal, regeneration, and protocol-zero audits each completed exactly once, calibration clean and obvious-artifact duplicate groups plus the holdout clean duplicate group passed, but holdout's obvious-artifact duplicate pair was clean severity 0 with no visible flags, so the required rejected short-line artifact contract failed before population audit or any numeric measurement; one read-only postmortem ran exactly once, all initial snapshots and receipts remain immutable, and no dev-r19 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
  です。auditは`world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json`、raw SHA-256は
  `96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0`です。calibrationのclean / `obvious-artifact` duplicate groupsとholdoutのclean duplicate groupはpassしました。holdout obvious pairは両方`clean`、severity `0`、visible flagなしで、population / measurementは未開始、postmortemはread-onlyで一度だけです。
- dev-r20: statusは`failed-and-closed-before-measurement`です。両private auditはpassしましたが、calibration / holdout tiny-speck population `0` / `1`がformal minimum `4`とdevelopment floor `6`をともにmissしました。他の全endpointは両minimumをpassし、numeric metricとthreshold searchは未開始です。auditは`world/map-production/qa/microtexture-v2-r6-dev-r20-development-failure.json`、raw SHA-256は`e8689321135e8c5d3fb038fbaa7c3ccbe644999905f4a3d3834fa30969ff27c8`です。
- formal r6: dev-r20 population failure後もblockedで、dev-r20はformal authorityを供給できません。formal CLI、one-shot marker、threshold
  freeze、v18 numeric measurementはいずれも未使用です。

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

## Closed dev-r14/dev-r15/dev-r16/dev-r17/dev-r18/dev-r19/dev-r20 evidence

dev-r14は両private auditをpassしました。calibration cluster countsはclean `35`、warning `15`、reject `50`、severity-3
`13`、grain `12`、tiny-speck `12`、microblob `4`、spot `16`、short-line `22`、parallel-bundle `11`です。
microblob-visible reject `4`はformal minimum `4`をpassしましたがdevelopment floor `6`をfailしました。他のcalibration
endpointはformal minimumとdevelopment safety floorをpassしました。holdoutはclean `31`、warning `16`、reject `53`、
severity-3 `20`、grain `11`、tiny-speck `11`、microblob `9`、spot `20`、short-line `22`、parallel-bundle `11`で、
全endpointが両minimumをpassしました。all-or-nothing gateによりmetricとthreshold searchは開始せず、
`measurement_started=false`、threshold / holdout performanceは`null`のまま閉鎖しました。閉鎖後のsanitized read-only
postmortemは一度だけです。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json`です。dev-r14 rootを不変に保持し、rerun、resume、
relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびroot/key/control/reference/pixel/
identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputを後続editionまたはformalへ再利用しません。

closed dev-r15は各familyのtier数`5 clean-candidate / 4 warning-candidate / 7 clear-reject-candidate /
4 dominant-reject-candidate`を維持します。変更対象はcalibration `artifact-microblob`の既存clear-reject-candidate
7件だけです。r14の直径7–13px、support radius 6–11pxの広いGaussianを、tiny-speckの1px hard coreと区別できる
compact finite Gaussianへ次のとおり置換しました。

| final index | residue | diameter | amplitude L | count | support radius | minimum separation |
|---:|---:|---:|---:|---:|---:|---:|
| 9 | 0 | 4 | 11.4 | 64 | 2 | 12 |
| 1 | 1 | 4 | 11.6 | 64 | 2 | 13 |
| 2 | 2 | 4 | 11.8 | 64 | 2 | 14 |
| 18 | 0 | 6 | 11.4 | 44 | 3 | 15 |
| 13 | 1 | 6 | 11.6 | 44 | 3 | 16 |
| 17 | 2 | 6 | 11.8 | 44 | 3 | 17 |
| 16 | 1 | 5 | 12.0 | 52 | 3 | 15 |

closed dev-r15ではcalibration microblobの4 dominant-reject、全clean/warning、holdout全morphology、他family、renderer、placement、rubric、
metric、single-threshold rule、formal endpoint minimum、development safety floor、endpoint counts/ratesを変更しませんでした。
7 anchors対development floor 6の構造上のmiss budgetは1ですが、design tierはVision truth、microblob flag、reject label、
endpoint membershipを保証・予告しません。schedule revisionは
`dev-r15-calibration-microblob-reject-anchor-schedule-v1`、microblob anchor revisionは
`dev-r15-calibration-quantized-microblob-reject-v1`です。変更しないwarning anchor revisionは
`dev-r14-quantized-direct-visible-sparse-warning-v1`を継承します。

dev-r9で固定したspeck reject anchorsとdev-r10で事前登録したgrain reject periodsは変更しません。speck reject側の
count scheduleは次のままです。

| split | clear-reject 7 conditions | dominant-reject 4 conditions |
|---|---|---|
| calibration | 32, 36, 40, 44, 48, 52, 56 | 64, 72, 80, 88 |
| holdout | 34, 38, 42, 46, 50, 54, 58 | 68, 76, 84, 90 |

1px hard core、最大12 L、0.08 axial shoulder、exact polarity、4象限stratification、minimum separation 10pxを維持します。
11 reject anchors対floor 6の構造上のmiss budgetは5ですが、これもVision truthの保証ではありません。

closed dev-r15が使用したexact identityは次のとおりです。このidentityや生成物はr16へ再利用しません。

- root: `tmp/map-production/microtexture-v2-r6-dev-r15`
- key: `tmp/map-production/microtexture-v2-r6-dev-r15/private/development-key.bin`
- schedule revision: `dev-r15-calibration-microblob-reject-anchor-schedule-v1`
- microblob anchor revision: `dev-r15-calibration-quantized-microblob-reject-v1`
- inherited warning anchor revision: `dev-r14-quantized-direct-visible-sparse-warning-v1`
- public nonce: `r6-calibration-v10` / `r6-holdout-v10`
- cluster domain: `microtexture-v2-r6/private-condition-cluster/v10/`
- render domain: `microtexture-v2-r6/render-seed/v10/`
- code domain: `microtexture-v2-r6/opaque-code/v10/`
- private-reference-transform domain: `private-reference-transform-v10/`
- public commitment domain:
  `microtexture-v2-r6/public-payload-commitment/v11/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`
- key commitment: `microtexture-v2-r6/key-commitment/v9`
- foundation offset/assignment lanes: `foundation-offset-v9` / `foundation-assignment-v9`
- delta lane: `delta-v9`
- private-control-id domain: `microtexture-v2-r6/private-control-id/v9/`
- protocol-zero nonces: calibration `751000..751015`、holdout `761000..761015`
- artifact nonces: calibration `773000..773419`、holdout `783000..783419`
- duplicate-audit nonces: calibration `791000..791002`、holdout `801000..801002`

closed dev-r16が使用しclosed dev-r17がartifact morphologyを不変継承したwarning scheduleのwarning revisionは
`dev-r16-six-per-sparse-family-direct-visible-warning-v1`、conversion revisionは
`dev-r16-one-clean-one-clear-per-sparse-family-v1`です。r14から継承した16 warning anchorsのSHA-256は
`5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6`、r16 active 48 warning anchorsのSHA-256は
`bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df`、16 conversionsのSHA-256は
`0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7`です。predecessor full morphology SHA-256は
`7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b`、184 nonconversion morphologiesは
`b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd`、144 preserved nonwarning sparse morphologiesは
`72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4`へ固定します。

各conversionは`warning-candidate`で、source tierはfamilyごと・splitごとにclean 1件とclear-reject 1件です。

| split | family | index (source) | warning parameters |
|---|---|---|---|
| calibration | speck | 0 (clean) | d1, L7.5, count4, shoulder0.05, separation13 |
| calibration | speck | 1 (clear) | d1, L7.6, count4, shoulder0.05, separation15 |
| calibration | microblob | 15 (clean) | d4, L7.0, count4, radius2, separation12 |
| calibration | microblob | 16 (clear) | d6, L7.2, count4, radius3, separation15 |
| calibration | short-dash | 9 (clean) | length6, width1, L7.4, count2, separation10 |
| calibration | short-dash | 16 (clear) | length16, width1, L6.4, count1, separation20 |
| calibration | parallel-bundle | 3 (clean) | length8, width1, spacing6, L7.4, pair1, separation14 |
| calibration | parallel-bundle | 10 (clear) | length10, width1, spacing6, L6.4, pair1, separation14 |
| holdout | speck | 19 (clean) | d1, L7.5, count4, shoulder0.05, separation14 |
| holdout | speck | 17 (clear) | d1, L8.0, count4, shoulder0.05, separation16 |
| holdout | microblob | 13 (clean) | d4, L7.1, count4, radius2, separation13 |
| holdout | microblob | 11 (clear) | d6, L7.3, count4, radius3, separation16 |
| holdout | short-dash | 7 (clean) | length6, width1, L7.5, count2, separation10 |
| holdout | short-dash | 5 (clear) | length16, width1, L6.5, count1, separation20 |
| holdout | parallel-bundle | 8 (clean) | length8, width1, spacing6, L7.5, pair1, separation14 |
| holdout | parallel-bundle | 13 (clear) | length10, width1, spacing4, L6.5, pair1, separation14 |

fine-grain tierは`5/4/7/4`、各sparse familyは`4/6/6/4`、warning anchorsはsplitあたり24件（6/family）、
warning floor 13に対するmiss budgetは11です。r15 source microblob manifest 7件とSHA
`dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833`はprovenanceとして保持します。そのうちactive
indices `[1,2,9,13,17,18]`の6-condition diameter-4/diameter-6 ladderはbyte-identicalで、active SHA-256は
`2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c`です。singleton index `16`だけをclear-to-warningへ
変換しました。speck reject anchorsはsource 11件からactive 10件となり、clear countsはcalibration
`[36,40,44,48,52,56]`、holdout `[34,38,42,46,50,58]`、dominant countsは不変、floor 6に対するmiss budgetは4です。
これらはdesign coverageであり、Vision truth、label、population membershipまたは合格を保証しません
（`truth guarantee=false`）。

closed dev-r16境界は次のexact identityです。

- root: `tmp/map-production/microtexture-v2-r6-dev-r16`
- key: `tmp/map-production/microtexture-v2-r6-dev-r16/private/development-key.bin`
- public nonce: `r6-calibration-v11` / `r6-holdout-v11`
- cluster domain: `microtexture-v2-r6/private-condition-cluster/v11/`
- render domain: `microtexture-v2-r6/render-seed/v11/`
- code domain: `microtexture-v2-r6/opaque-code/v11/`
- private-reference-transform domain: `private-reference-transform-v11/`
- public commitment domain:
  `microtexture-v2-r6/public-payload-commitment/v12/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`
- key commitment: `microtexture-v2-r6/key-commitment/v10`
- foundation offset/assignment lanes: `foundation-offset-v10` / `foundation-assignment-v10`
- delta lane: `delta-v10`
- private-control-id domain: `microtexture-v2-r6/private-control-id/v10/`
- protocol-zero nonces: calibration `851000..851015`、holdout `861000..861015`
- artifact nonces: calibration `873000..873419`、holdout `883000..883419`
- duplicate-audit nonces: calibration `891000..891002`、holdout `901000..901002`

closed dev-r17が使用した境界は次のexact identityです。

- schedule revision: `dev-r17-protocol-zero-reference-prequalification-schedule-v1`
- root: `tmp/map-production/microtexture-v2-r6-dev-r17`
- key: `tmp/map-production/microtexture-v2-r6-dev-r17/private/development-key.bin`
- public nonce: `r6-calibration-v12` / `r6-holdout-v12`
- cluster domain: `microtexture-v2-r6/private-condition-cluster/v12/`
- render domain: `microtexture-v2-r6/render-seed/v12/`
- code domain: `microtexture-v2-r6/opaque-code/v12/`
- private-reference-transform domain: `private-reference-transform-v12/`
- public commitment domain:
  `microtexture-v2-r6/public-payload-commitment/v13/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`
- key commitment: `microtexture-v2-r6/key-commitment/v11`
- foundation offset/assignment lanes: `foundation-offset-v11` / `foundation-assignment-v11`
- delta lane: `delta-v11`
- private-control-id domain: `microtexture-v2-r6/private-control-id/v11/`
- protocol-zero nonces: calibration `951000..951015`、holdout `961000..961015`
- 生成物nonces: calibration `973000..973419`、holdout `983000..983419`
- duplicate-audit nonces: calibration `991000..991002`、holdout `1001000..1001002`

private-reference prequalification revisionは
`dev-r17-role-agnostic-private-reference-coefficient-prequalification-v1`です。生成物 / protocol-zero / duplicate-auditへ
同一適用し、7×9 coefficient grid、domain `candidate/{index:02d}/`から8候補を作ります。pixel、requested delta、label/
decision、private roleを選択へ使わず、displacement-y/x weight 7、tone weight 3で、maximum/sum orthogonal-neighbor jump、
maximum/sum centered coefficient magnitude、candidate indexのlexicographic minimumを選びます。candidate 0より悪いscoreは
選べず、truth保証はありません。manifest SHA-256は
`a3cfdec84b58bebec38f581c03fbe9947975bf93e11741477cd3bb22f0931119`、static score SHA-256は
`1413b6a4f7dba56cc264a5a5c32a6f101041fa77c8ac82541baaa6843dc81d1f`です。dev-r16の200件の生成物morphologyは変更0、
preserved SHA-256は`c60917c79ae36278d17cc7ccaa93d798cac17500d2d678b41b0cdea34ff66b30`です。

initial gate revisionは`dev-r17-bilateral-initial-visible-flag-intersection-gate-v1`です。Root/Independentのofficial initial
snapshots `decisions-root.initial.dev.txt` / `decisions-independent.initial.dev.txt`と各`.sha256` receiptを両splitで必須にし、
receiptはlowercase SHA-256、two spaces、snapshot basename、LFです。initialはofficial parser、coverage、anonymous-code bindingを
passしなければなりません。final `vision-decisions.dev.txt` / `decisions-root.dev.txt` /
`decisions-independent.dev.txt`はthree-way exact bytesで、各recordのfinal `g,t,b,l,p` setはRoot/Independent initial flag
intersectionのsubsetです。disposition、severity、notesのreconciliationはこのsubset gateで固定しません。gate manifest SHA-256は
`f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd`、label-seal schemaは
`microtexture-v2-r6-development-label-seal/3`です。

dev-r8/dev-r9/dev-r10/dev-r11/dev-r12/dev-r13/dev-r14/dev-r15/dev-r16/dev-r17/dev-r18/dev-r19のkey、control、reference、label、decision、pixel、identity、
placement、nonce、commitment、rootまたはprivate materialを読み替え・再利用しません。

## 全件Visionとmeasurement gate

Rootと独立Visionは各splitの全220 anonymous codesを、full 200%とNW/NE/SW/SE 400%で確認します。
5 viewは同じcode順、nearest-neighbor拡大、完全なquadrant partitionを持ちます。`review-crops`は同じcontact-sheet
bytesからcrop-only derivativeとして各rowのnative 512×384 full-200 panelを出します。closed dev-r15/dev-r16/dev-r17/dev-r18/dev-r19へ適用した規約では、
native panelを無補正・contrast強調なしで先に判定し、400%は同位置の再同定だけに使います。400%だけで推測できる極めて薄い点状印象は
visible morphologyへ数えません。RootとIndependentは各recordを
`clean|warning|reject`、severity 0..3、5 visible flags、EV3 locatorsで独立決定します。reconciliation前に両者それぞれのofficial
initial snapshotとSHA receiptを作り、official parser、220-record coverage、anonymous-code bindingを検証します。差分は画像へ戻って
reconcileしますが、final visible flag setは各recordで両initial flag setのintersectionのsubsetに限定します。final三ファイルの
exact bytesと全220件のlogical agreementがなければpreflightを通しません。private identityをrevealする前に
`microtexture-v2-r6-development-label-seal/3`で両splitのlabel bytesをsealします。

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
dev-r10はgeneration中断、dev-r11/dev-r16はprivate sentinel audit失敗、dev-r12/dev-r13/dev-r14/dev-r15/dev-r17はpopulation audit失敗、dev-r18/dev-r19はprivate duplicate audit失敗でmetric call前に閉鎖しました。

```text
reject = max(grain_score, spot_score,
             finite_line_score, parallel_bundle_score) > frozen_threshold
```

branch別threshold、追加OR gate、diagnostic hard rejectorは禁止します。calibrationはclean acceptance 0.95、
warning acceptance 0.75を含む全endpoint count/rateを満たす候補だけから、事前登録objectiveで1 scalarを選びます。
候補がなければthresholdを`null`のままeditionを閉じます。holdoutはcalibrationでfreezeした値を変更しません。

## dev-r18/dev-r19/dev-r20 closure and formal block

dev-r18はgeneration、両reviewerの`440 × 2` blind review、immutable bilateral initial receipts、全差分reconciliation、final
intersection gate、official preflight、label sealing、private reveal、regeneration、protocol-zero auditを各一度だけ完了しました。
calibrationの明白なアーティファクトのduplicate pairはdisposition `reject`と`short_line_visible=true`で一致しましたが、ordinal severityが
`2` / `3`に分かれ、当時のexact semantic equality checkをfailしました。population audit、numeric measurement、threshold searchを
開始せず`failed-and-closed-before-population-audit`で閉鎖し、read-only postmortemを一度だけ実行しました。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r18-development-failure.json`、raw SHA-256は
`7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122`です。rerun、resume、relabel、別key、subsetting、top-up、
素材・output再利用は禁止です。

dev-r18では各splitで既存reject-tier speck 10条件だけを対称に置換し、内訳はclear-reject 6条件 + dominant-reject 4条件でした。全targetは
diameter `1`、hard core count `4..7`、center amplitude L `11.2..12.0`、shoulder fraction `0.42..0.56`、encoded axial
shoulder magnitude L `>=5`、minimum separation `>=30`、quadrant-stratified placementです。truth、endpoint membership、またはgate通過は
保証しません。sanitized r17 aggregateに対するtiny-speck structural miss budgetは`4`、spotは`9`からdevelopment floor `10`へ
必要な増分が`1`です。他180件の生成物morphology、tier cardinality、population minimum、metric、threshold、rate、r17
role-agnostic reference prequalification、bilateral initial flag gateはすべて不変です。

dev-r18のschedule revisionは`dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1`、reinforcement revisionは
`dev-r18-symmetric-reject-speck-direct-visible-cross-v1`です。reinforcement manifest SHA-256は
`355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4`、full 200 morphology SHA-256は
`9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365`、preserved 180 morphology SHA-256は
`03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf`、sanitized r17 basis SHA-256は
`88860fea0dbdf5ebfa454bf7f038aae53c957808d4c4d344b1ea0fc8e54042e9`です。

dev-r18 rootは`tmp/map-production/microtexture-v2-r6-dev-r18`、public noncesは`r6-calibration-v13` / `r6-holdout-v13`です。
condition-cluster / render-seed / opaque-code / private-reference-transformはv13、public payload commitmentはv14、key commitment /
foundation-offset / foundation-assignment / delta / private-control-idはv12です。protocol-zero nonce basesは`1051000` /
`1061000`、生成物basesは`1073000` / `1083000`、duplicate-audit noncesは`1091000..1091002` /
`1101000..1101002`です。このroot、key、private materialと全outputは後続editionまたはformalへ一切再利用しません。

dev-r19はgeneration、両reviewerの`440 × 2` blind review、immutable bilateral initial receipts、全差分reconciliation、final intersection gate、official preflight、label sealing、private reveal、regeneration、protocol-zero auditを各一度だけ完了しました。calibrationのclean duplicateと`obvious-artifact` duplicate、holdoutのclean duplicateはpassしました。calibration obvious pairは両方`reject`、severity `3`、visible flagは`l`のみでしたが、holdout obvious pairは両方`clean`、severity `0`、visible flagなしでした。各memberに必須の`reject`、severity `2` / `3`、`short_line_visible=true`契約をfailしたため、population audit、numeric measurement、metric evaluation、threshold searchを開始せず`failed-and-closed-before-population-audit`で閉鎖しました。read-only sanitized postmortemは一度だけです。exact roleは
`development-only prepopulation private-audit failure evidence; generation, both blind 440-record reviews, bilateral reconciliation, official preflight, label sealing, private reveal, regeneration, and protocol-zero audits each completed exactly once, calibration clean and obvious-artifact duplicate groups plus the holdout clean duplicate group passed, but holdout's obvious-artifact duplicate pair was clean severity 0 with no visible flags, so the required rejected short-line artifact contract failed before population audit or any numeric measurement; one read-only postmortem ran exactly once, all initial snapshots and receipts remain immutable, and no dev-r19 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
です。auditは`world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json`、raw SHA-256は
`96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0`です。dev-r19の全root / key / private material / outputは後続editionまたはformalへ再利用しません。

このfailureからpreregisterした唯一のsuccessorがfresh dev-r20 one-shot probeでした。dev-r20はそのauthorityどおり一度だけ実行され、statusは`failed-and-closed-before-measurement`です。exact roleは
`development-only premeasurement population failure evidence; both private audits passed, calibration tiny-speck population 0 and holdout tiny-speck population 1 each missed formal minimum 4 and development floor 6, every other endpoint passed both minima, no numeric metric or threshold search started, one read-only postmortem ran exactly once, all Root and Independent initial snapshots and receipts remain immutable, and no dev-r20 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
です。

r20のschedule / sentinel revisionsは`dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1` /
`dev-r20-keyed-axial-short-line-duplicate-sentinel-v1`です。`obvious-artifact` duplicateだけを当該editionのfresh-keyed positive `+12.0 L`のaxial bar `12`本へ変更し、各barはencoded `24×3 px`、各exact metric quadrantに`3`本、各quadrantにhorizontal / verticalの両方を含みます。center間Chebyshev distanceは`>=32 px`、support guardは`>=2 px`、nonzero supportは計`864 px`です。pairはrequested delta、decoded residual、metricがexactに等しく、reference、control、anonymous code、control IDは異なります。このgeometry contractと両private auditはpassしましたが、アーティファクトpopulation全体のVision truthは保証されず、tiny-speck population gateをfailしました。

clean duplicate、dev-r19 reject severity-band policy、全200アーティファクト形態、全design tier、metric、threshold、population、rate contractは不変です。fullアーティファクト形態 / sanitized r19 basis / sentinel manifest SHA-256は
`9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365` /
`8a99bb7038b5936ac7e44ac339114dc46f78e5d2a8df923a7be0674693d85933` /
`2ee513f2a3182741fbf9df569a2c5137a7f25b4fd27d3fbba6b00344497b85a1`です。population-anchor schedule keyset / changed-values / probe authority SHA-256は
`b5c8211902bb03838e7fe402bbb48e0e7f7a9db37acd1856be3dca2c67b82134` /
`3b87c5aabee0c8c8641d80496123a4f2dd58ca60f6da2bcf822e6bc7dfa80368` /
`584deb41c74d8beeff030c33f1ed0116c4e583c9c60a41e010fb6233972b05a2`です。

消費済みclosed rootは`tmp/map-production/microtexture-v2-r6-dev-r20`、public noncesは`r6-calibration-v15` / `r6-holdout-v15`です。condition-cluster / render-seed / opaque-code / private-reference-transformはv15、public payload commitmentはv16、key commitment / foundation-offset / foundation-assignment / delta / private-control-idはv14です。protocol-zero nonce basesは`1251000` / `1261000`、アーティファクトbasesは`1273000` / `1283000`、duplicate-audit noncesは`1291000..1291002` / `1301000..1301002`です。fresh cryptographic blind key、identities、domains、nonces、controls、references、commitments、labels、decisionsをfresh isolated rootで一度だけ作り、過去editionから再利用しませんでした。両private audit後のpopulation auditでcalibration / holdout tiny-speck population `0` / `1`がformal minimum `4`とdevelopment floor `6`をmissし、他の全endpointは両minimumをpassしました。numeric measurementとthreshold searchは開始していません。auditは`world/map-production/qa/microtexture-v2-r6-dev-r20-development-failure.json`、raw SHA-256は`e8689321135e8c5d3fb038fbaa7c3ccbe644999905f4a3d3834fa30969ff27c8`です。dev-r20はformal authorityを供給できず、全素材・outputを再利用しません。successorはpreregisterしておらず、formal stageはblockedです。

generation start後、marker後の例外、通常endpoint failure、completion欠落はeditionを消費します。失敗後のresume、
regeneration、relabel、remeasurement、rerun、別key、threshold変更は禁止です。

## Production / Golden boundary

synthetic holdout passだけではproduction microtextureを承認しません。production source/reference、
protected-feature mask、filter-support erosion、tile overlap/halo/seam、color/alpha/resampling、zoom coverage、
master aggregation、untouched production holdoutを候補測定前に別途事前登録します。

道路、河川、海岸、文字、記号、集落、正典geometryをprotected maskから漏らしません。production derivationと
untouched holdoutを同じfrozen detector/thresholdで通過し、Rootと2件の独立Visionがexact Golden pixelsを
採用するまで、既存公開地図を上書きしません。
