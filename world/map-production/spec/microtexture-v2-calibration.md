---
type: "overview"
category: "maps"
title: "Microtexture v2-r5 候補非依存較正契約"
version: "0.6.0"
created: "2026-07-25"
last_updated: "2026-07-26"
author: "Codex"
tags: ["maps", "quality-assurance", "microtexture", "vision-qa", "calibration"]
status: "review"
document_kind: "navigation"
summary: "r3/r4の一回限り不合格を履歴へ固定し、fresh foundations、匿名control、Root Vision、独立locked-clean、未使用holdoutでr5の四分岐composite thresholdを凍結する運用概要です。"
---

# Microtexture v2-r5 候補非依存較正契約

規範的authorityは`scripts/map-production/microtexture-v2-r5/preregistered-spec.json`です。
この文書は運用navigationであり、矛盾時はr5 JSONと、その
`implementation-bindings.json`に固定された実装・schema・templateが優先します。

## 履歴と現在地

r3は2026-07-25に一度だけcalibrationされ、不合格のまま閉鎖しました。追跡証拠は
`world/map-production/qa/microtexture-v2-r3-calibration-failure.json`です。

| r3結果 | 実績 |
| --- | ---: |
| clean acceptance | 22 / 22 = 100% |
| warning acceptance | 15 / 19 = 78.9% |
| reject detection | 12 / 25 = 48.0% |
| severity-3 detection | 4 / 4 = 100% |
| speck / short / parallel hard detector | 0件検出 |

r4も2026-07-25に一度だけcalibrationされ、threshold候補は選べたもののendpoint failureで
failed-and-closedになりました。追跡証拠は
`world/map-production/qa/microtexture-v2-r4-calibration-failure.json`です。

| r4結果 | 実績 |
| --- | ---: |
| clean acceptance | 100% |
| warning acceptance | 100% |
| reject detection | 48.3% |
| severity-3 detection | 60.0% |
| tiny-speck / microblob detection | 0% / 5.0% |
| short-line / parallel-bundle detection | 55.0% / 73.3% |

r4では、Visionがsynthetic foundationを含むabsolute controlを判定した一方、単一occupancy
metricはcontrol-reference residualだけを測りました。そのためfoundation上のアーティファクトが数値上消え、
zero/duplicate protocol recordsにも不整合labelが生じました。また1 scalar channelではgrain、
sparse spot、blob、finite line、parallel bundleを同時に表現できず、tiny-speckの必要cluster数も不足しました。

r3/r4の再実行、再label、retune、threshold freeze、locked validation、holdoutは禁止です。両editionの
controls、keys、labels、thresholds、foundations、locked sources、holdoutsはdevelopment-onlyです。
r4 corpusはr5の固定morphology channelsとreference constantsを設計する開発資料に限って参照され、
r5の正式判断へpixelや数値を持ち込みません。

現在の唯一のsuccessor authorityはr5です。r5はfresh spec、key、foundations、controls、labels、
locked-clean reference、authority receipt、holdoutを持つ独立one-shot editionです。

## ImageGen input authority

r5のfresh foundation corpusは、Rootと独立Visionで事前qualifyしSHA固定したImageGen `v10`、
`v11`、`v12`だけです。各sourceは1536×1024で、control/referenceへ使用できるのは中央
`[512,320,512,384]` cropだけです。その内部のdetector/Vision unitは
`[128,96,256,192]`です。

foundationはsecret HMACで3画像へ割り当てますが、各recordはfull private record identity（polarityと
replicateを含む）を入力とするfull-output HMAC-SHA-256 counter-mode PRFで固有のprivate referenceを作ります。
7×9 coefficient gridを滑らかに補間し、最大1.75 pxのwarpと最大0.75 Lのtone shiftだけを加えます。各splitの
140 reference SHA、140 control SHA、および5 viewそれぞれの140 panel SHAは全件一意でなければなりません。
`v10`～`v12`はcontrol-onlyであり、production art、
texture donor、Golden input、final pixelsへ使用・転送しません。

公開manifest schemaは`microtexture-v2-r5-control-manifest/3`です。各recordが公開するのはopaque codeと、
`control` / `reference` / `delta`のper-code/per-lane HMAC-SHA-256 commitment 3件だけです。420 commitmentsを
全件一意にし、個別control/referenceのpath、file、raw bytes、raw SHAをmarker前に作成・公開しません。raw
SHAはdurable markerとlabel seal後のprivate revealだけへ出します。

このblindの目的はhonest reviewerが指定されたsurfaceだけを見る運用分離です。technical / cryptographic
blindや、同じOS principalで悪意あるreviewerに対するsecrecyは主張しません。fresh keyは専用の長寿命
custodian processだけが保持し、Vision processへ継承・公開しません。marker前のreview surfaceは120
contact-sheet pagesとcode-only label formだけです。label sealまではsource、authority code、個別
control/reference、raw extraction、filesystem、hash/diff、identity regenerationをVision processから禁止します。

ImageGen `v14`はfoundation corpusと独立したfresh locked-clean referenceです。Root / independent Vision
qualificationは完了していますが、数値validationは未実行のpending post-freeze stageです。calibration
populationとthreshold selectionから除外し、threshold freeze前のdecode・測定・数値参照を禁止します。
freeze後に中央256×192を一度だけ測定し、hard compositeがacceptしなければr5を閉鎖します。
`v14`もproduction donor、Golden input、final pixelsには使用しません。

foundation候補`v8`、`v9`とlocked-clean predecessor `v13`はVisionで不採用です。r4の旧`v7`を含め、
r5 control、reference、threshold、holdout、productionへ再利用しません。

## Control corpus: 140 records / 78 clusters

calibrationとholdoutはそれぞれ140 records、78 unique private condition clustersです。

| private role | records | clusters | 用途 |
| --- | ---: | ---: | --- |
| `artifact` | 120 | 60 | threshold selectionとendpoint evaluation |
| protocol-zero | 16 | 16 | exact-zero foundation/label protocol sentinel |
| duplicate-audit | 4 | 2 | distinct-reference semantic-replicate consistency audit |

120 `artifact` recordsは5 morphology familiesから成ります。

- `artifact-fine-grain`
- `artifact-speck`
- `artifact-microblob`
- `artifact-short-dash`
- `artifact-parallel-bundle`

formal one-shot前のdevelopment Visionで、各familyの12 nonzero conditionsを低・中・高強度へ再配分し、
corpus coverageとして固定します。calibrationとholdoutはsplit別のfrozen schedulesを使います。fine-grainは
fine-band / halftoneの各patternにつき最低強度の1 conditionだけをmetric-window内のdeterministic nonzero
sparse support（`support_fraction=0.001`）とし、残り10 conditionsはfull supportです。これはformal labelの
期待値や事前指定ではなく、endpoint最低population/rate、blind、one-shot契約は不変です。

各familyは12 nonzero conditions、各conditionはdark/lightのpaired polaritiesを持つため24 recordsです。
60 `artifact` clustersの全controlはreferenceと異なり、zero-count `artifact` conditionはありません。
polarity pairは異なるprivate referenceを使いますが、position、angle、unsigned geometryからrequested deltaを
exact sign inverseとして作ります。decoded `control-reference` int16 residualもexact inverse、対応metricsも
exact equalityでなければ生成を拒否します。polarityは独立clusterとして数えません。

16 protocol-zero recordsはcontrol bytesとreference bytesが完全一致します。Rootは必ずclean、severity 0、
visible flagsなしとlabelしなければなりません。duplicate-auditはcleanと`obvious-artifact`の2 groupsで、
各groupに異なるopaque codeの2 semantic replicatesがあります。replicate間のprivate reference/controlは
異なり、requested delta、decoded residual、metricsはexact equalityです。Rootのdisposition、severity、
全visible flagsも一致しなければfail closedです。protocol-zeroとduplicate-auditは
threshold candidates、selection objective、`artifact` endpointsから除外します。

sentinel membershipやraw hash equalityはmarker前のlabel補正に使いません。semantic auditは必ず
durable marker → exact label-byte seal → 全control/referenceのin-memory regeneration → exact contact-sheet byte
binding → private audit → control/reference measurement
の順です。protocol-zeroとclean duplicateはclean、`obvious-artifact` duplicateは両方ともseverity 2/3 rejectかつ
`short_line_visible=true`を要求します。違反はpost-marker failureとしてone-shot editionを閉じます。

calibrationとholdoutはpublic/parameter nonce、HMAC identities、opaque codes、control IDs、delta hashesを
分離します。endpoint performanceはeligibleな`artifact` recordsをcluster内で平均し、その後unique clustersを
等重みで集計します。

## Root Vision: 120 pages / split

control canvasは512×384 L-modeで、decision-critical cropは中央`[128,96,256,192]`です。Rootは各splitの
全140 anonymous codesを次の5 viewsで確認します。

- `full-200`: metric window全体を200%表示、24 pages
- `northwest-400`: 北西128×96を400%表示、24 pages
- `northeast-400`: 北東128×96を400%表示、24 pages
- `southwest-400`: 南西128×96を400%表示、24 pages
- `southeast-400`: 南東128×96を400%表示、24 pages

合計は120 pages / splitです。4 quadrantはgapとoverlapなくmetric window全域を覆います。実装はview ID、
順序、integer crop/scale、nearest-neighbor resize、pageごとのcode順をruntimeで再検証します。

Root labelは`clean|warning|reject`、grain/tiny-speck/microblob/short-line/parallel-bundleの5 visible flags、
severity 0..3、200% review、全400% quadrant review、notesを要求します。全120 pagesと全codesを確認するまで
評価を開始しません。validated label fileはgeneratorが出したexact regular pathだけから読み、marker直後、
新しいdecode/reveal/measurementより前にsplit別sealed pathへexclusive copyします。

## Four branches, one threshold

r5は中央256×192 luminance residualの固定raw metricsから4 branch scoresを作ります。

1. `grain_score`
2. `spot_score`
3. `finite_line_score`
4. `parallel_bundle_score`

spot component floor、finite-line response floor、parallel-pair response floorはいずれもabsolute `4.5 L`です。
coherent fine patternはdirectional coherenceを含むgrain branchが担当します。split-specific schedulesとこれらの
floorは、fresh formal key、controls、labelsより前に明示的なnon-formal development keysでfreezeしました。
そのcorpusはdevelopment-onlyで、formal labels、threshold、resultsは未確定であり予告しません。既存のblind、
one-shot、endpoint、failed-r3/r4契約は不変です。

parallel branchはraw deltaへcore-only line kernelを適用します。weaker-pair peakとmatched-pair countは同一の
angle/length filter内でcoupleし、別filterのpeak/countを混ぜません。matched pairsが2未満ならcanonical
`parallel_pair_peak_l=0`、`parallel_matched_pair_count=0`です。

唯一のhard scalarは次です。

```text
hard_composite_score = max(
  grain_score,
  spot_score,
  finite_line_score,
  parallel_bundle_score
)
reject = hard_composite_score > frozen scalar threshold
```

branch別thresholdや追加OR gateはありません。raw/diagnostic metricsを独立hard rejectorにしません。
calibrationはexact floor `0`、distinctなnonnegative minimum-epsilon、adjacent-value midpoints、upper outward sentinelから候補を作り、
clean-cluster acceptance 0.95以上かつwarning-cluster acceptance 0.75以上の候補だけを許可します。
その上で、5 Vision morphology endpointsの最小detection、combined spot、overall reject、severity-3、clean、
warning、より厳しいthresholdの固定順で一意に選びます。

threshold candidates、selection、全endpointに入るprivate roleは`artifact`だけです。protocol-zeroと
duplicate-auditは完全に除外します。全endpointのminimum cluster countとrateはblockingです。不足population、0 denominator、vacuous pass、
admissible candidate不在、endpoint failureはthreshold freezeを禁止してeditionを閉じます。holdoutはfreezeした
1 thresholdを変更せず使います。

## Authorityとone-shot

実行rootは`scripts/map-production/microtexture-v2-r5/`です。各formal operationは次を要求します。

- HEADがcurrent branch upstreamと一致し、authority working bytesがcaptured HEADと一致する
- code rootと`artifact root`がspec固定のexact pathである
- foundation/locked provenanceとVision reviewsがtracked SHAへ一致する
- 全formal stagesが同一machineと同一runtime fingerprintを使う
- blind keyが暗号学的に安全なfresh 32 bytesで、専用の長寿命custodian processだけが保持し、Vision processへ
  継承・公開・保存・log出力されない
- 操作中のHEADが不変である

Ubuntu/Windows CIはstatic、unit、golden-vector preflightであり、formal controlsを作ったりformal runを
継続したりしません。両CIがauthority commitで成功してから開始します。

各stageはmarker write自体をpost-marker failure guardの`try`内で行い、durable markerをcurrent target decode、
private identity reveal、新しいnumeric measurement、threshold selection、endpoint evaluationより前に書きます。
calibration/holdoutではlabel seal、in-memory regeneration、exact contact-sheet byte binding、private sentinel
auditsもmarker後かつmeasurement前です。terminal completionを書いた直後は`require_completion=True`でauthorityを
reloadします。marker後のexception、通常endpoint failure、
completion欠落はいずれもeditionを消費します。失敗後のregeneration、relabel、remeasurement、rerun、
threshold changeは禁止です。reportはsealed labels、manifest、regenerated control/reference SHA、exact contact-sheet bytes、marker、
HEAD/runtime、threshold/receipt、secret-derived identityへ再結合してから最終completionを書きます。

## Formal execution order

1. r5 authority、v10～v12 foundations、v14、全generation provenance、Root/independent Vision reviewsを
   commit/pushし、tracked bytes・upstream HEAD・Ubuntu/Windows CIをpreflightする。
2. 同一machine/runtimeを固定し、fresh 32-byte blind keyを専用custodian processだけに置き、Vision processへ
   継承させない。exact `artifact root`はformal processへ設定する。
3. calibration 140 controlsを一度だけ生成する。
4. Rootがcalibrationの全120 pages / 140 codesを匿名状態でlabelする。
5. calibrationを一度だけ評価する。失敗時はr5を閉じ、thresholdをfreezeしない。
6. pass時だけ1 scalar thresholdをfreezeし、`v14` locked-cleanを一度だけ数値validationする。
7. eligible independent authorityがfrozen calibrationとlocked-clean reportを監査し、tracked receiptを作る。
8. receiptをcommit/pushし、そのHEADでUbuntu/Windows CIを再度通す。
9. receiptと`v14` provenance/reviewsを再検証し、fresh holdout 140 controlsを一度だけ生成する。
10. Rootがholdoutの全120 pages / 140 codesを匿名状態でlabelする。
11. frozen thresholdを変えず、holdoutを一度だけ評価する。失敗しても変更・再実行しない。
12. r5 pass後も、production residual derivationとuntouched production holdoutを別specで事前登録する。

## Production / Golden boundary

r5 detectorが扱うのは、別途preregisterされたbackground referenceから得る完全な256×192 float32
luminance residual windowです。道路、河川、海岸、文字、記号、集落、正典geometryをprotected-feature maskと
filter-support erosionで除外し、partial windowやdenominator renormalizationを禁止します。

r5のsynthetic holdout passだけではproduction derivation、v246 family、Golden candidate、final pixelsを
承認しません。production source/reference、mask、filter support、tile overlap/halo/seam、boundary、color/alpha/
resampling、zoom/tile coverage、deterministic outputs、window-to-master aggregation、untouched production holdoutを
候補測定前に別途固定し、同じ実装とfrozen thresholdでsynthetic/production holdoutの両方を通過する必要があります。
