---
type: "overview"
category: "maps"
title: "Microtexture v2-r6 候補非依存較正契約"
version: "0.7.0"
created: "2026-07-25"
last_updated: "2026-07-28"
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
- dev-r8: generation前。tracked runner、soft-unit metric、revision-3 schedule/nonces、fresh-root契約を
  commit/pushしUbuntu/Windows CIが成功した後にだけ開始します。
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

## 全件Visionとmeasurement gate

Rootと独立Visionは各splitの全220 anonymous codesを、full 200%とNW/NE/SW/SE 400%で確認します。
5 viewは同じcode順、nearest-neighbor拡大、完全なquadrant partitionを持ちます。Rootは各recordを
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
branch構成、単一threshold、endpoint count/rateは不変で、fresh dev-r8によるblindな再検証を必須とします。

```text
reject = max(grain_score, spot_score,
             finite_line_score, parallel_bundle_score) > frozen_threshold
```

branch別threshold、追加OR gate、diagnostic hard rejectorは禁止します。calibrationはclean acceptance 0.95、
warning acceptance 0.75を含む全endpoint count/rateを満たす候補だけから、事前登録objectiveで1 scalarを選びます。
候補がなければthresholdを`null`のままeditionを閉じます。holdoutはcalibrationでfreezeした値を変更しません。

## 安全な実行順序

1. dev-r7 failure audit、r8 spec/code/tests/runner、ImageGen provenance、Root/独立Vision QAをcommitする。
2. branchへpushし、Ubuntu/Windows CIの成功を確認する。
3. formal root/environmentとdev-r8 rootが存在しないことを確認する。
4. fresh keyでdev-r8 calibration/holdout controlsを一度だけ生成する。
5. Rootと独立Visionが全440 recordsを匿名確認し、Root decisionsを画像へ戻ってreconcileする。
6. 両splitのlabelsをsealし、private auditとpopulation safety floorを実行する。
7. gate合格時だけcalibrationを測定し、thresholdを一度だけ選択する。
8. calibration選択thresholdを変えずdevelopment holdoutへ一度だけ適用する。
9. dev-r8失敗時はsanitized failure auditをcommitし、formalへ進まない。
10. dev-r8成功時はdevelopment-only success auditをcommitし、dev-r8を閉じる。
11. spec SHA、trust-root tests、全implementation hashesを再計算し、formal authority freeze commitを作る。
12. push後、Ubuntu/Windows CIが再度成功してからfresh formal key/rootを作る。
13. formal calibration生成・Root Vision・one-shot評価を各一度だけ行う。
14. pass時だけthresholdをfreezeし、v18 locked-cleanを一度だけ数値validateする。
15. preregistered independent authorityがcalibration/v18を監査し、tracked receiptを作る。
16. receipt commit/push/CI成功後、fresh formal holdoutを一度だけ生成・Root Vision・評価する。
17. formal holdout pass後も、production residual derivationとuntouched production holdoutを別specで固定する。
18. その後にのみGolden、master、deep-zoom tilesへ接続する。

marker後の例外、通常endpoint failure、completion欠落はeditionを消費します。失敗後のregeneration、
relabel、remeasurement、rerun、threshold変更は禁止です。

## Production / Golden boundary

synthetic holdout passだけではproduction microtextureを承認しません。production source/reference、
protected-feature mask、filter-support erosion、tile overlap/halo/seam、color/alpha/resampling、zoom coverage、
master aggregation、untouched production holdoutを候補測定前に別途事前登録します。

道路、河川、海岸、文字、記号、集落、正典geometryをprotected maskから漏らしません。production derivationと
untouched holdoutを同じfrozen detector/thresholdで通過し、Rootと2件の独立Visionがexact Golden pixelsを
採用するまで、既存公開地図を上書きしません。
