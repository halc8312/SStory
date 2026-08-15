# Microtexture v2-r6 preregistration summary

規範的 authority は `preregistered-spec.json` です。この文書は
`implementation-bindings.json` に hash-bind される readable summary であり、矛盾時は JSON が優先します。

## Edition boundary and image inputs

r6 は r3/r4/r5 の rerun ではなく fresh one-shot edition です。r3、r4、r5 は failed-and-closed、development-only
であり、過去の controls、keys、labels、thresholds、foundations、locked sources、holdouts は再利用しません。
r5 の revealed failure を参照したのは、r6 key/control/label/measurement の生成前に bounded-unit scores、
condition-cluster truth aggregation、population feasibility gate、coverage scheduleを定義した開発段階だけです。

freeze前のnon-formal `dev-r6`もfailed-and-closedです。両splitのlabel sealとprivate reveal後、数値metricを一度も
呼ぶ前のpopulation auditで、calibrationのtiny-speck rejectが3件、holdoutのcleanが12件、tiny-speck rejectが
0件、spot rejectが7件となり当時の最低値を満たしませんでした。failure artifactは
`measurement_started=false`でeditionを閉じ、thresholdを作っていません。そのkey、controls、labels、pixels、
measurementを再利用しません。fresh `dev-r7` は両splitのpopulation safety floorを通過し、Rootと独立Visionで
全440 recordsを確認してsealした後、一度だけ測定しました。しかしcalibrationのwarning 8/19 clustersとreject
55/56 clustersがclamp ceiling `1.0`へ同点化し、全endpointを満たすthresholdが存在しなかったため
failed-and-closedです。thresholdは`null`で、holdout endpoint performanceは未評価です。sanitized failure evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r7-development-failure.json`へhash-bindします。

fresh `dev-r8` は両splitの全440 recordsを新規生成し、全件Vision reviewとlabel seal、private auditを終えた後、
最初のmetric callより前のpopulation gateで`failed-and-closed-before-measurement`になりました。
tiny-speck-visible reject clusterはcalibration 3、holdout 1でdevelopment-only floor 6を下回り、他の全population
endpointは両splitでpassしました。`measurement_started=false`のまま、raw metrics、hard composite、candidate search、
threshold selection、holdout endpoint evaluationを行わず、thresholdを作っていません。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r8-development-failure.json`へhash-bindします。dev-r8のroot、key、
controls、references、pixels、identities、opaque codes、labels、measurements、noncesはformalまたは後続editionへ
再利用せず、閉鎖rootだけをforensic reproducibilityのため不変のまま保持します。

fresh `dev-r9` はspeck population deficitを解消し、両splitの全population floorを通過して一度だけ測定しました。
しかしcalibrationではwarning acceptance `>=0.75`とseverity-3 detection `=1.0`を同じ単一thresholdで満たす候補が
ありませんでした。selected thresholdとholdout endpoint performanceは`null`で、editionは
`failed-and-closed-after-measurement`です。sanitized evidenceを
`world/map-production/qa/microtexture-v2-r6-dev-r9-development-failure.json`へhash-bindし、dev-r9のroot、key、controls、
labels、pixels、identities、measurements、diagnostics、nonces、commitmentsを再利用しません。

fresh `dev-r10` は一回限りのgenerationを開始しましたが、monitor session喪失後に対応process不在を確認し、終了原因を
特定しないままterminal generation summary / seal / completionへ到達しませんでした。generationは未完了で、Vision review、label seal、private reveal、analysis、
measurement、threshold searchは未開始です。dev-r10は消費・閉鎖し、exact root
`tmp/map-production/microtexture-v2-r6-dev-r10`を不変に保持します。generate再実行、resume、欠損splitのtop-up、
root削除後の再生成、別key、partial controls / references / pixels / codes / commitmentsの流用を禁止します。
sanitized closure evidenceは`world/map-production/qa/microtexture-v2-r6-dev-r10-development-failure.json`へhash-bindします。

fresh `dev-r11` はgenerationと全440 recordsのRoot/独立Vision review、reconciliation、preflight、label sealを一度だけ
完了しました。しかしprivate reveal後、population auditより前のprivate sentinel auditで、holdoutのexact-zero
protocol sentinel 1件にsealed nonclean / tiny-speck判定があることを検出しました。極めて薄い400%上の点状印象を、
無補正の`full-200`で各coreが直接見えるというrubricを満たさないままcross-scale morphologyとして数えたVision
false positiveです。dev-r11は`private-sentinel-audit-before-population-audit`でfailed-and-closedとなり、population
aggregation、raw metric、threshold search、holdout endpoint evaluationは未開始、`measurement_started=false`、
thresholdとholdout performanceは`null`です。sanitized evidenceを
`world/map-production/qa/microtexture-v2-r6-dev-r11-development-failure.json`へbindします。このauditにはblind key、
匿名code/page/rowからprivate identity/pixelへのbinding、private labels/identities/pixelsを記録せず、raw private
postmortemは起動・追跡しません。dev-r11のrerun、resume、relabel、retune、replacement、subset、top-up、key resampling、
root削除後の再生成、またはroot/key/control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/
public surfaceのformal・後続editionへの再利用を禁止します。

fresh `dev-r12` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitの
private auditを一度だけ完了し、両private auditはpassしました。しかし最初のmetric callより前のpopulation auditで、
calibration warningは`10`（formal minimum `10`はpass、development floor `13`はfail）、holdout warningは`9`
（formal minimum `10`とdevelopment floor `13`の両方をfail）でした。両splitのその他すべてのformal endpoint minimumと
development-only floorはpassしました。`measurement_started=false`のままraw metric、hard composite、threshold search、
holdout endpoint evaluationを開始せず、thresholdとholdout performanceは`null`です。閉鎖後にsanitized read-only
postmortemを一度だけ実行し、metric call、private identity bindingの公開、r12の再評価は行っていません。sanitized evidenceを
`world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json`へbindします。dev-r12 rootは不変に保持し、
rerun、resume、relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、またはdev-r12の
root/key/control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/public surfaceのformal・後続editionへの
再利用を禁止します。

`dev-r13` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
auditを一度だけ完了し、両private auditはpassしました。しかしpre-measurement population auditでcalibration warningは
`14`（formal minimum `10` / development floor `13`ともにpass）、holdout warningは`12`（formal minimum `10`はpass /
development floor `13`はfail）でした。その他の全endpointは両splitでformal minimumとdevelopment floorをpassしました。
all-or-nothing gateにより`measurement_started=false`のままmetric、hard composite、threshold search、holdout endpoint
evaluationを開始せず、thresholdとholdout performanceは`null`です。閉鎖後にsanitized read-only postmortemを一度だけ
実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json`です。dev-r13 rootは不変に保持し、rerun、
resume、relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびdev-r13のroot/key/
control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputのformal・
後続editionへの再利用を禁止します。

`dev-r14` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitのprivate
auditを一回だけ完了し、両private auditはpassしました。しかし最初のmetric callより前のpopulation auditで、calibrationは
clean `35`、warning `15`、reject `50`、severity 3 `13`、grain-visible reject `12`、tiny-speck-visible reject `12`、
microblob-visible reject `4`、spot-visible reject `16`、short-line-visible reject `22`、parallel-bundle-visible reject
`11`でした。microblobはformal minimum `4`をpassしましたがdevelopment floor `6`をfailし、calibrationのその他の
endpointはformal minimumとdevelopment floorをpassしました。holdoutはclean `31`、warning `16`、reject `53`、
severity 3 `20`、grain-visible reject `11`、tiny-speck-visible reject `11`、microblob-visible reject `9`、
spot-visible reject `20`、short-line-visible reject `22`、parallel-bundle-visible reject `11`で、全endpointがformal
minimumとdevelopment floorをpassしました。all-or-nothing gateにより`measurement_started=false`のままmeasurement、
hard composite、threshold search、holdout endpoint evaluationを開始せず、thresholdを作っていません。閉鎖後のsanitized
read-only postmortemは一度だけです。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json`です。dev-r14 rootは不変に保持し、rerun、
resume、relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびdev-r14のroot/key/
control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputのformal・後続editionへの
再利用を禁止します。

`dev-r15`は一回限りのgenerationを完了し、Rootと独立Visionがそれぞれ全440 public recordsを独立確認した
`440 × 2` review、全差分のreconciliation、official preflight、label seal、両splitのprivate auditを一度だけ完了しました。
両private auditはpassしました。独立initial decisionの`lp` delimiter drift（calibration 29行、holdout 30行）はinitial
snapshot/receiptに不変保存し、正規`l,p`への修正はfinal official-valid decision filesだけへ適用しました。
pre-measurement population auditではcalibration warning `12`がformal minimum `10`をpassしてdevelopment floor `13`を
failし、holdout warning `9`はformal minimum `10`とdevelopment floor `13`の両方をfailしました。他の全endpointは
両splitで両minimumをpassしました。数値metric、measurement、threshold searchを開始せず、thresholdは存在しません。
閉鎖後のsanitized read-only postmortemは一度だけです。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r15-development-failure.json`（raw SHA-256
`faa420e63af8b3f647e045ae4d71ac2fbe32316175e68999cc16b3e278311200`）です。dev-r15のroot/key/control/reference/
pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputは後続editionまたはformalへ
一切再利用しません。

`dev-r16`は一回限りのgeneration、Root/独立Visionによる各440 recordsのblind review、全差分のreconciliation、official
preflight、label seal、private revealを各一度だけ完了しました。両reviewerのofficial initial snapshotsとSHA receiptsは
不変です。private auditではcalibrationのprotocol-zero `16/16`がclean、holdoutは`15/16`がcleanでしたが、残る1件の
exact-zero sentinelが`warning`、severity 1、`short_line_visible=true`となったlocalized-line false positiveでした。
duplicate-auditは両splitともpassしました。このためpopulation aggregation、numeric measurement、threshold searchを一度も
開始せず`failed-and-closed-before-measurement`で閉鎖し、sanitized read-only postmortemを一度だけ実行しました。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r16-development-failure.json`（raw SHA-256
`4637978a7ac5d59c99ec076e527b7be6e5d2ad1c0477077e2587fda7091ca169`）です。dev-r16のroot/key/secret/control/reference/
pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem output/private materialを後続editionまたは
formalへ一切再利用しません。

`dev-r17`は一回限りのgenerationで両split合計440 public recordsを生成し、Root/Independentが各440件を独立確認した
`440 × 2` reviewを完了しました。両者のofficial initial snapshotsとSHA receiptsは不変です。全差分
（calibration: logical 97件 + notes-only 17件、holdout: logical 84件 + notes-only 60件）をreconcileし、final bilateral
initial visible-flag intersection gate、official preflight、両splitのprivate auditはpassしました。

pre-measurement population counts（clean、warning、reject、severity 3、grain、tiny-speck、microblob、spot、short-line、
parallel-bundle）は、calibrationが`27, 22, 51, 11, 11, 11, 10, 20, 20, 10`で全formal minimumとdevelopment floorをpass、
holdoutが`30, 30, 40, 28, 11, 0, 9, 9, 20, 10`でした。holdout tiny-speck `0`はformal minimum `4` / development floor
`6`をfailし、spot `9`はformal minimum `8`をpassしてdevelopment floor `10`をfailしました。holdoutの他endpointは全formal
minimumとdevelopment floorをpassしました。all-or-nothing gateにより数値metricを一度も呼ばず、thresholdを作らないまま
`failed-and-closed-before-measurement`で閉鎖しました。閉鎖後のsanitized read-only postmortemは一度だけです。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r17-development-failure.json`（raw SHA-256
`2177b04b6f79b75394cbdef6204423194603cd81e3a84b5a673c58393ccf5856`）です。dev-r17の全素材・identity・decision・
public/private outputはformalまたは後続editionへ一切再利用しません。formal stageはblockedです。

`dev-r18`のstatusは`failed-and-closed-before-population-audit`です。exact roleは
`development-only prepopulation private-audit failure evidence; generation, both blind 440-record reviews, bilateral reconciliation, official preflight, label sealing, private reveal, regeneration, and protocol-zero audits each completed exactly once, but calibration's obvious-artifact duplicate pair had identical reject dispositions and short-line flags with ordinal severities 2 and 3, so the then-exact severity semantic check failed before population audit or any numeric measurement; one read-only postmortem ran exactly once, all initial snapshots and receipts remain immutable, and no dev-r18 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
です。sanitized auditは`world/map-production/qa/microtexture-v2-r6-dev-r18-development-failure.json`、raw SHA-256は
`7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122`です。

dev-r18では各splitの既存`artifact-speck` reject-tier 10条件だけを対称に置換し、内訳はclear-reject 6 / dominant-reject 4でした。
diameterは1 px、core countは4..7、center amplitudeは11.2..12.0 L、shoulder fractionは0.42..0.56、encoded axial
shoulder magnitudeは5 L以上、minimum separationは30 px以上とし、coreを4象限へstratifyします。これはcoverage reinforcementであり
Vision truthを保証しません。tiny-speck development floor 6に対する構造上のmiss budgetは4、sanitized r17 holdoutのspot
`9`からdevelopment floor `10`へ必要な増分は1です。clean / warning / 全non-speckを含む他180 morphology、tier cardinality、
population minima、metric、threshold、rate、r17 role-agnostic reference prequalification、bilateral initial flag gateは不変です。

dev-r18のschedule revisionは`dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1`、reinforcement revisionは
`dev-r18-symmetric-reject-speck-direct-visible-cross-v1`です。reinforcement manifest SHA-256は
`355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4`、full 200 morphology SHA-256は
`9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365`、preserved 180 morphology SHA-256は
`03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf`、sanitized r17 basis SHA-256は
`88860fea0dbdf5ebfa454bf7f038aae53c957808d4c4d344b1ea0fc8e54042e9`です。

dev-r18 rootは`tmp/map-production/microtexture-v2-r6-dev-r18`、public noncesは`r6-calibration-v13` / `r6-holdout-v13`です。
condition-cluster / render-seed / opaque-code / private-reference-transformはv13、public payload commitmentはv14、key commitment /
foundation-offset / foundation-assignment / delta / private-control-idはv12です。protocol-zero nonce basesは`1051000` / `1061000`、
artifact basesは`1073000` / `1083000`、duplicate-audit noncesは`1091000..1091002` / `1101000..1101002`です。
このroot、key、private material、controls、references、pixels、identities、codes、commitments、labels、decisions、measurements、
nonces、public surfaces、postmortem outputは後続editionまたはformalへ一切再利用しません。

唯一のpreregistered successor `dev-r19`のstatusは`fresh-development-only`で、fresh isolated one-shot development-only probeです。exact roleは
`fresh one-shot development role used only as a duplicate semantic-equivalence correction probe after the closed dev-r18 prepopulation private-audit failure; it preserves every dev-r18 morphology, design tier, metric, threshold, population, and rate contract, changes only duplicate semantic equivalence so reject severities 2 and 3 share one reject ordinal band while clean and warning severities remain exact and disposition plus all five visible flags remain exact, requires a fresh isolated root, cryptographic blind key, identities, domains, nonces, controls, references, commitments, labels, decisions, and measurements, and can never become or supply formal authority`
です。

r19のschedule revisionは`dev-r19-duplicate-reject-severity-band-equivalence-schedule-v1`、duplicate-equivalence policy revisionは
`dev-r19-reject-ordinal-band-duplicate-equivalence-v1`です。obvious-artifact duplicate pairはdispositionをexact比較し、5つのvisible flagを
pairwise exactとしたうえで、両memberの`short_line_visible=true`を必須とします。他4 flagの値はfalseへ固定しません。各memberのseverity 2 / 3を同じreject ordinal bandとして扱います。clean duplicate pairとwarning semanticsは
exactのままです。dev-r18の全200 artifact morphologies、全design tier、metric、threshold、population、rate contractを保持し、
morphology change countは`0`、full artifact morphology SHA-256は
`9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365`のままです。
sanitized r18 basis SHA-256は`f4f4c80a406818da30ab18ac270eb466dda2ef42b4f301bde6ce2dea8698ade1`、
duplicate-equivalence policy manifest SHA-256は`292ebced789826a46ac792a10f716c70c1a4ed5960d5a299dd7a89e816143cc6`、
population-anchor schedule keyset / changed-values SHA-256は
`15e87ae2c17897bccae75722f1a8ffa9dd8f3aea2d8632929d83a62ac0675b0d` /
`7065534770044e408d02dd82a4b96adbc74ba77a5e154a2c42697bb43c679c3c`、probe authority manifest SHA-256は
`b96a98c0c6a35f227a9b81c80220af9ffa99621828a71d10a2ddecb84cccb963`です。

fresh rootは`tmp/map-production/microtexture-v2-r6-dev-r19`、public noncesは`r6-calibration-v14` / `r6-holdout-v14`です。
condition-cluster / render-seed / opaque-code / private-reference-transformはv14、public payload commitmentはv15、key commitment /
foundation-offset / foundation-assignment / delta / private-control-idはv13です。protocol-zero nonce basesは`1151000` / `1161000`、
artifact basesは`1173000` / `1183000`、duplicate-audit noncesは`1191000..1191002` / `1201000..1201002`です。
generation前にexact authority commitをpushし、同じcommitのUbuntu/Windows CIを両方passさせます。dev-r19はone-shotで、
successしてもformal authorityを供給できず、formal stageは引き続きblockedです。

fresh foundation corpus は、非数値の Vision review を通過し SHA-bind された ImageGen `v15`、`v16`、`v17`
のみです。source は 1536×1024、許可される foundation crop は `[512,320,512,384]`、その中の metric window は
`[128,96,256,192]` です。foundation は secret HMAC で割り当てますが、各recordはfull private record identity
（polarityとreplicateを含む）を入力とするfull-output HMAC-SHA-256 counter-mode PRFで固有のprivate
referenceを生成します。7×9 coefficient gridを滑らかに補間し、最大1.75 pxのwarpと最大0.75 Lのtone shift
だけを加えます。
事前の画像資格基準は94/100以上で、Rootと2件の独立Vision reviewを通過したexact bytesだけを採用します。

locked-clean reference は別系統の ImageGen `v18` です。`v18` は calibration population と threshold selection に
含めず、threshold freeze 前の decode・測定・数値参照を禁止し、freeze 後に一度だけ hard composite で
accept を確認します。foundation と locked-clean の全 pixel は validation-only であり、production art、
Golden input、texture donor、final pixels への利用・転送を禁止します。
locked-cleanの事前画像資格基準も94/100です。Independent Aはformal preflightの直接必須review、
Independent Bはgeneration receiptにhash-bindされた補足reviewです。

## Blinded control design

各 split は 220 records、118 unique condition clusters です。規範的 `control_families` は compact schema で、
artifact family entry は `id`、`private_role`、`polarities`、`expected_clusters_per_split`、
`expected_records_per_split` だけを持ちます。

- `artifact-fine-grain`: 20 clusters、40 paired records
- `artifact-speck`: 20 clusters、40 paired records
- `artifact-microblob`: 20 clusters、40 paired records
- `artifact-short-dash`: 20 clusters、40 paired records
- `artifact-parallel-bundle`: 20 clusters、40 paired records

dev-r16でfreezeしclosed dev-r17がmorphologyを変更せず継承したdevelopment Vision scheduleでは、各familyの20 nonzero conditionsを4つのdesign tierへ割り当て、
fine-grainを`5 / 4 / 7 / 4`、4つのsparse familyを各`4 / 6 / 6 / 4`としてcorpus coverageをfreezeします。calibrationとholdoutはspecに
記録されたsplit別のfrozen scheduleとpublic nonceを使います。このtierは幅広いperceptual marginを作るための
design-only区分であり、`clean`、`warning`、`reject`、severity、visible flagのtruthを指定・予告しません。
全scheduleを一体としてblind reviewし、結果を見たsubsetting、top-up、key resamplingを禁止します。

dev-r9のspeck scheduleは両splitでtiny-speck population floorを通過しました。dev-r10では
`artifact-fine-grain`のfull-support reject-tier 3条件だけを事前に変更し、calibrationのperiod `14.0`を`11.6`、
holdoutの`12.6`を`11.4`、`14.6`を`11.8`へ置換しました。全11 reject-tier grain conditionsは、変更しない
coherence support `2..13`のguard-bandedな内側`3..12`へ入ります。dev-r10はgeneration中断、dev-r11はprivate sentinel
audit失敗によりpopulation aggregationとmetricへ到達せず、どちらのcorpusからもscheduleを評価・調整しません。
dev-r12は両private auditとwarning以外の全population endpointをpassしましたが、warning population不足で測定前に
閉鎖しました。dev-r13も両private auditをpassし、calibration warning `14`はformal minimum `10` / development floor `13`を
pass、holdout warning `12`はformal minimum `10`をpassしてdevelopment floor `13`だけをfailしたため測定前に閉鎖しました。
その他の全endpointは両splitで両minimumをpassしました。dev-r14もtier数`5/4/7/4`を維持して一体生成・blind reviewし、
両private auditをpassしましたが、calibrationのmicroblob-visible rejectが`4`でformal minimum `4`だけをpassし、development
floor `6`をfailしたため測定前に閉鎖しました。calibrationのその他のendpointとholdoutの全endpointはformal minimumと
development floorをpassしました。

closed dev-r15は、calibration `artifact-microblob`の7 clear-reject candidateだけを次のcompact finite Gaussian matrixへ置換しました。

| calibration index | diameter px | amplitude L | count | support radius px | separation px |
|---:|---:|---:|---:|---:|---:|
| 9 | 4 | 11.4 | 64 | 2 | 12 |
| 1 | 4 | 11.6 | 64 | 2 | 13 |
| 2 | 4 | 11.8 | 64 | 2 | 14 |
| 18 | 6 | 11.4 | 44 | 3 | 15 |
| 13 | 6 | 11.6 | 44 | 3 | 16 |
| 17 | 6 | 11.8 | 44 | 3 | 17 |
| 16 | 5 | 12.0 | 52 | 3 | 15 |

closed dev-r15ではcalibrationの4 dominant candidate、全clean/warning candidate、holdout全体、他family、renderer/placement、metric、
single-threshold rule、population minima、endpoint counts/ratesを変更しませんでした。r15のtier数も`5/4/7/4`のままでした。この
scheduleはblindなgeneration coverageであり、Vision truth、microblob label、endpoint membership、またはgate通過を
保証・予告しませんでした。r15のruntime outputsは閉鎖済みであり、top-up、relabel、retuneまたは後続editionへの再利用を
認めません。

dev-r16の16 exact warning conversionsはすべて`warning-candidate`です。

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

r14 inherited warning revisionは`dev-r14-quantized-direct-visible-sparse-warning-v1`、その16-warning manifest SHA-256は
`5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6`、active 48-warning manifestは
`bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df`、conversion-16 manifestは
`0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7`です。predecessor full morphologyは
`7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b`、184 nonconversion morphologiesは
`b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd`、144 preserved nonwarning sparse morphologiesは
`72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4`へ固定します。r15 source schedule / microblob revisionは
`dev-r15-calibration-microblob-reject-anchor-schedule-v1` / `dev-r15-calibration-quantized-microblob-reject-v1`、その7-manifest SHA-256は
`dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833`、active six ladder indices
`[1,2,9,13,17,18]`のSHA-256は`2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c`です。
speck reject active clear countsはcalibration `[36,40,44,48,52,56]`、holdout `[34,38,42,46,50,58]`、dominant countsは
不変で、source 11件からactive 10件、floor 6に対するmiss budgetは4です。

closed dev-r16 exact rootは`tmp/map-production/microtexture-v2-r6-dev-r16`、key pathは
`tmp/map-production/microtexture-v2-r6-dev-r16/private/development-key.bin`です。
public noncesは`r6-calibration-v11` / `r6-holdout-v11`、cluster domainは
`microtexture-v2-r6/private-condition-cluster/v11/`、render domainは`microtexture-v2-r6/render-seed/v11/`、code domainは
`microtexture-v2-r6/opaque-code/v11/`、private-reference-transform domainは`private-reference-transform-v11/`です。public
commitment domainは`microtexture-v2-r6/public-payload-commitment/v12/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`、
key commitmentは`microtexture-v2-r6/key-commitment/v10`、foundation lanesは`foundation-offset-v10` / `foundation-assignment-v10`、
delta laneは`delta-v10`、private-control-id domainは`microtexture-v2-r6/private-control-id/v10/`です。protocol-zero noncesは
calibration `851000..851015` / holdout `861000..861015`、artifactは`873000..873419` / `883000..883419`、
duplicate-auditは`891000..891002` / `901000..901002`です。

closed dev-r17が使用したschedule revisionは`dev-r17-protocol-zero-reference-prequalification-schedule-v1`、exact root/keyは
`tmp/map-production/microtexture-v2-r6-dev-r17` /
`tmp/map-production/microtexture-v2-r6-dev-r17/private/development-key.bin`です。public noncesは
`r6-calibration-v12` / `r6-holdout-v12`、cluster domainは`microtexture-v2-r6/private-condition-cluster/v12/`、render domainは
`microtexture-v2-r6/render-seed/v12/`、code domainは`microtexture-v2-r6/opaque-code/v12/`、private-reference-transform domainは
`private-reference-transform-v12/`です。public commitment domainは
`microtexture-v2-r6/public-payload-commitment/v13/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`、key commitmentは
`microtexture-v2-r6/key-commitment/v11`、foundation lanesは`foundation-offset-v11` / `foundation-assignment-v11`、delta laneは
`delta-v11`、private-control-id domainは`microtexture-v2-r6/private-control-id/v11/`です。protocol-zero noncesはcalibration
`951000..951015` / holdout `961000..961015`、artifactは`973000..973419` / `983000..983419`、duplicate-auditは
`991000..991002` / `1001000..1001002`です。

private-reference prequalification revisionは
`dev-r17-role-agnostic-private-reference-coefficient-prequalification-v1`です。artifact / protocol-zero / duplicate-auditの
全private rolesへ、同じ7×9 coefficient gridからdomain `candidate/{index:02d}/`で8候補を作ります。pixel、requested delta、
label/decision、private roleを一切入力・分岐に使わず、displacement-y/xを各7、toneを3でinteger weightingし、maximum/sum
orthogonal-neighbor jump、maximum/sum centered coefficient magnitude、candidate indexの順でlexicographic minimumを選びます。
選択scoreはcandidate 0より悪化できず、Vision truthを保証しません。manifest SHA-256は
`a3cfdec84b58bebec38f581c03fbe9947975bf93e11741477cd3bb22f0931119`、static score SHA-256は
`1413b6a4f7dba56cc264a5a5c32a6f101041fa77c8ac82541baaa6843dc81d1f`です。dev-r16の全200 artifact morphologyは
変更せず、preserved SHA-256は`c60917c79ae36278d17cc7ccaa93d798cac17500d2d678b41b0cdea34ff66b30`です。

initial-decision gate revisionは`dev-r17-bilateral-initial-visible-flag-intersection-gate-v1`です。各splitでRoot/
Independentの`decisions-{root|independent}.initial.dev.txt`と、lowercase SHA-256・two spaces・snapshot basename・LF形式の
`.sha256` receiptを両方必須とし、official parser、220-record coverage、anonymous-code bindingを通します。final
`vision-decisions.dev.txt` / `decisions-root.dev.txt` / `decisions-independent.dev.txt`はthree-way exact bytesとし、各recordのfinal
`g,t,b,l,p` setはRoot initialとIndependent initialのflag intersectionのsubsetでなければなりません。disposition、severity、
notesのreconciliation自体はこのsubset gateで固定しません。gate manifest SHA-256は
`f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd`、label-seal schemaは
`microtexture-v2-r6-development-label-seal/3`です。

各familyのmorphology invariantはtier間でも不変です。fine-grainはfield-wideな反復/coherenceを保ち、spot/lineへ
移しません。speckは分離した同程度のpoint-like hard coreを3個以上保ち、blurでmicroblob化させません。microblobは
compactな中心/境界を保ち、diffuse cloudやspeck列へ変えません。short-dashは有限straight strokeと端点を保ちます。
parallel-bundleは同極性・非接触の有限stroke pairを保ち、散在、交差、接触、merged形態を条件数へ数えません。
このcoverage設計はformal labelの期待値や事前指定ではなく、endpoint最低population/rate、blind、one-shot契約を
変えません。

この5 familyで100 artifact clusters、200 artifact recordsです。各 cluster は dark/light
`polarities=[-1,1]` を持ち、両recordは異なるprivate referenceを使います。同じ位置、角度、unsigned geometry
からrequested deltaをexact sign inverseとして作り、decoded `control-reference` int16 residualもexact inverse、
対応metricsもexact equalityでなければなりません。100 clusters はすべて nonzero injection で、各record内の
control/reference bytes が異なります。
artifact population 内の zero-count variant は禁止です。sparse parameter は count、size/length、amplitude、
width、spacing を固定された非単調 permutation で交差させ、位置・角度は secret HMAC から導出します。

残りは artifact endpoint へ入らない protocol records です。

- `protocol-zero`: 16 records = 16 clusters。control/reference bytes と requested delta zero を厳密検証し、
  Root label は clean、severity 0、visible flags all false でなければなりません。
- `duplicate-audit`: 4 records = 2 clusters。clean と obvious-artifact が各1 cluster、各 cluster は
  異なる opaque code の2 semantic replicatesを持ちます。replicate間のprivate reference/control SHAは異なり、
  requested delta、decoded residual、metricsはexact equalityです。Root labelのdisposition、severity、5 visible
  flagsも一致しなければなりません。

以上で `100 + 16 + 2 = 118` clusters、`200 + 16 + 4 = 220` records です。protocol-zero と
duplicate-audit は foundation/label protocol の検査専用で、threshold candidates、objective、artifact
endpoints から除外します。

private cluster identity は split、public nonce、role、family、variant、parameters、duplicate group、foundation を
HMAC-SHA-256 に bind し、polarity と replicate を除外します。公開 manifest、record、contact sheet、label
には family/role/polarity/parameter/cluster/foundation/duplicate identity を出しません。validated labels と
durable one-shot marker の後だけ reveal できます。calibration と holdout は public nonce、parameter nonce、HMAC
identity、opaque code、control ID、nonzero requested-delta hash が互いに独立です。parameter value/range 自体の
分離は主張しません。意図的なexact-zero sentinelだけはcanonical all-zero requested-delta hashを共有します。

artifact polarity pairのrecord-level Vision labelsは、reveal後にcondition cluster単位の保守的truthへ一度だけ
集約します。dispositionは`reject > warning > clean`、severityは最大、5 visible flagsはORです。pairのraw
metric payloadは完全一致を要求し、1 clusterに1 score・1 predictionだけを持たせます。したがって同一metric
conditionがaccept populationとreject populationへ同時に入ることはありません。

closed `dev-r8` / `dev-r9` / `dev-r12` / `dev-r13` / `dev-r14` / `dev-r15` / `dev-r16` / `dev-r17` のanalysisには、formal common endpoint minimaを変更しない
development-only safety gateを加えます。dev-r10はanalysis前、dev-r11はprivate sentinel auditでpopulation aggregation前に
閉鎖し、dev-r18もprivate duplicate semantic auditでpopulation aggregation前に閉鎖したため、このgateの結果を持ちません。両splitの
label bytesをsealし、private revealとsemantic auditを終えた後、最初のmetric call
より前に集約済みcondition-cluster truthで、splitごとにclean 19、warning 13、reject 38、severity 3が6、
grain-visible reject 10、tiny-speck-visible reject 6、microblob-visible reject 6、spot-visible reject 10、
short-line-visible reject 10、parallel-bundle-visible reject 8以上を要求します。

dev-r8ではtiny-speck-visible rejectだけがcalibration 3、holdout 1で不足し、他の全endpointはpassしました。
gateはall-or-nothingなので`measurement_started=false`のまま消費・閉鎖し、metric、threshold探索、holdout endpoint
evaluationへ進みませんでした。dev-r9は全floorを通過しましたが、warning acceptanceとseverity-3 detectionを
同時に満たすcalibration thresholdがなく、測定後に閉鎖しました。dev-r10はgeneration中断、dev-r11はprivate sentinel
audit失敗でgateへ到達していません。dev-r12は両private auditをpassした後、calibration warning `10 < 13`、holdout
warning `9 < 13`でgateをfailしました。dev-r13も両private auditをpassしましたが、calibration warning `14`はformal minimum
10 / development floor 13をpass、holdout warning `12`はformal minimum 10をpassしてdevelopment floor 13だけをfailしました。
dev-r13のその他の全endpointはformal minimumとdevelopment floorをpassしました。dev-r14も両private auditをpassしましたが、
calibration microblob-visible reject `4`はformal minimum `4`をpassしてdevelopment floor `6`をfailしました。
calibrationの他endpointとholdout全endpointは両minimumをpassし、`measurement_started=false`のまま閉鎖しました。
dev-r15も両private auditをpassした後、calibration warning `12`がformal minimum `10`をpassしてdevelopment floor `13`を
failし、holdout warning `9`が両minimumをfailしたため、他の全endpointが両minimumをpassしていても測定前に閉鎖しました。
dev-r16はprivate exact-zero sentinel false positiveでpopulation gate前に閉鎖しました。dev-r17は両private auditをpassしましたが、
holdout tiny-speck `0`とspot `9`がdevelopment floorを満たさず消費・閉鎖しました。測定、threshold探索、ラベル変更、top-up、
別keyでの再生成をしません。このsafety marginとgrain support scheduleはdevelopment専用でVision truthではなく、
formalのpopulation/rate、metric、candidate selection、one-shot契約を変えません。

公開manifest schemaは`microtexture-v2-r6-control-manifest/3`です。各recordが持つのはopaque codeと、secret
key・code・lane (`control|reference|delta`)・raw SHAをdomain-separateしたHMAC-SHA-256 commitment 3件だけ
です。660 commitmentsは全件一意で、個別control/referenceのpath、file、raw bytes、raw SHAをmarker前に
作成・公開しません。各splitの220 reference SHA、220 control SHA、および5 viewそれぞれの220 panel SHAも
全件一意でなければなりません。raw SHAはmarkerとlabel seal後のprivate revealだけへ出します。

ここでのblindはhonest reviewerに対する運用上のblindであり、technical / cryptographic blindでも、同じOS
principalで悪意あるreviewerに対するsecrecyでもありません。fresh keyは専用の長寿命custodian processだけが
保持し、Vision processへ継承・公開しません。marker前のreview surfaceは185 contact-sheet view-pages
（各view 37 pages）とcode-only
label formだけです。Vision processはlabel sealまでsource、authority code、個別control/reference、raw
extraction、filesystem、hash/diff、identity regenerationを使用してはいけません。

## Vision observation contract

decision-critical unit は 512×384 control の中央 `[128,96,256,192]` crop です。Root は各 split について、
この全体を示す `full-200` と、隙間・重複なく分割する NW/NE/SW/SE の4つの 400% view を確認します。
`review-crops`は同じcontact-sheet bytesからcrop-only derivativeとして、各rowのfull-200表示pixelを追加拡大なしのnative 512×384
`review-page-...-row-...-full-200-native.png`として切り出します。closed dev-r15/dev-r16/dev-r17/dev-r18へ適用した規約では、このnative cropを無補正・contrast強調なしで
先に判定し、400% viewは同位置の再同定だけに使います。
各 view は37 pages、合計185 contact-sheet view-pagesです。development helperは同じpage indexの5 viewを
横並びにした37 review boardsも作ります。5 viewの ID、順序、integer scale/crop、nearest-neighbor resize、
page ごとの code 順序が一致しない場合は fail-closed です。各512×384 panelの直前に30px code headerを置き、
codeをpanel下へ置くことやheader/panel overlapを禁止します。

Root label schema は `clean|warning|reject`、grain/tiny-speck/microblob/short-line/parallel-bundle の visible
flags、severity 0..3、200% review、全400% quadrant review、notes を要求します。label file は generator が
出した exact split path の regular non-link file でなければなりません。one-shot marker の直後、新規 decode/
reveal/measurement より前に exact sealed path へ exclusive copy し、以後の report と authority reload は
その immutable bytes を使います。

RootとIndependentはreconciliation前に各splitのofficial initial snapshot
`decisions-root.initial.dev.txt` / `decisions-independent.initial.dev.txt`と対応する`.sha256` receiptを作成します。receiptは
`lowercase-sha256 two-spaces snapshot-basename newline`、両snapshotはofficial parser、220-record coverage、anonymous-code
bindingをpassしなければなりません。reconciliation後の`vision-decisions.dev.txt` / `decisions-root.dev.txt` /
`decisions-independent.dev.txt`はthree-way exact bytesとし、各recordのfinal `g,t,b,l,p` setはRoot initialとIndependent
initialのflag intersectionのsubsetでなければなりません。disposition、severity、notesはこのsubset gateの対象外ですが、通常の
schema/semantic validationを通します。private roleはこのgateの入力にせず、label sealは
`microtexture-v2-r6-development-label-seal/3`を使用します。

全 anonymous record には、規範 `labels.vision_observation_rubric`
`microtexture-v2-r6-injected-morphology-only/3` を reveal 前に同一適用します。許容clean substrateは、境界のない広い
低周波・非周期のpaper clouding、smooth mottling、gentle tone drift、疎で孤立したsoft・irregular・low-contrast
organic fleckです。これらだけならclean/0/all flags falseであり、400%で初めて気付くfaint diffuse/soft-edge pinprickや
absolute nonuniformityだけをartifactにしません。形態を数えるには、contrast強調なしでfull-200に直接見え、対応400%
quadrantの同位置で再同定できることが必須で、400%だけの印象はflagを立てません。

grainは高周波の反復・周期・方向/coherenceです。tiny-speckは、同程度のfootprint/polarityを持つ独立したpoint-like
hard coreを3個以上それぞれ位置指定できる場合だけです。各coreは400%で一意に位置指定でき、全方向で概ね1 core幅以内に
背景へ戻り、soft substrateより明確にsharp/high-contrastで、full-200の同位置にも見える必要があります。diffuse、
feathered、irregular soft fleck、孤立した単独core、単なるtone extremaは除外します。
microblobは局所中心/境界を持つcompact blob、short-lineは端点/長軸を持つ有限straight dashです。parallel-bundleは、
full-200で個別に見える同極性・非接触の2 strokeを同一400% quadrantで一緒に再同定でき、無向軸角差10°以下、
edge-to-edge垂直gapが2本の可視centerline長の算術平均以下かつ正、mean axis投影が短い方の50%以上重なるpairだけです。
散在、交差、接触、merged、異極性、単に似た角度のdashは除外し、`p=true`なら`l=true`も必須です。broad edge-free
cloud、smooth contour、許容fiber-like variationも対応flagへ入れません。flagは非排他的です。

notesはASCII固定形 `ev3:g=<set>;t=<set>;b=<set>;l=<set>;p=<set>` だけを許します。locatorは
`(NW|NE|SW|SE)-R[1-3]C[1-3]-N(01..99)`、空集合は`-`です。clauseはg,t,b,l,p順、locatorはquadrant
NW/NE/SW/SE、row、column、ordinal順で、空白・自由文・重複は禁止します。true flagは非空set、false flagは`-`、
tiny-speckは3 distinct locators以上です。parallel pairは2 stroke midpointでsectorを選び、同じlocatorをlとpへ記録します。
stroke全体のsector内包は要求しません。位置を記録できなければflagはfalseです。全predicateを満たす形態が弱い場合だけwarning/1とし、
warningを「不確か」の退避先にしません。明瞭な局在・反復はreject/2、
支配的・高contrast・field-wideはreject/3です。source/reference/hash/diff/family/role/polarity/sentinel/duplicateの
推測・比較は禁止します。各判定は次pageへ進む前に印字anonymous codeへ直接記録・照合し、page/rowだけの遅延転記を
禁止します。private audit失敗はeditionを閉じ、relabelを許可しません。

marker 前に検証できるのはschema、authority、code coverage、review completeness、reviewed-view boolean、各record内の
semantic整合、canonical `ev3` syntax、public flag/evidence binding、tiny-speck cardinality、parallelのl/p locator binding
だけです。raw hash equalityやprivate sentinel membershipを使ったlabel修正は禁止します。semantic
sentinel/replicate auditの順序は marker → label seal → 全control/referenceのin-memory regeneration → exact
contact-sheet byte binding → private audit → measurement
です。16 protocol-zeroとclean duplicateはclean必須、obvious-artifact duplicateは同一semantic label、
severity 2/3 reject、`short_line_visible=true` 必須です。違反はpost-marker failureとしてeditionを閉じます。

## Four branches and one hard scalar

metric window は 192×256 float32 luminance residual です。固定 raw metrics を artifact-derived denominator なしで、
固定half-scale referenceに対する `unit_soft(x,ref)=0 (x<=0), otherwise (2/pi)*atan(x/ref)` へ正規化します。
これは有限の正の証拠に厳密単調、`0..1`未満に有界で、`x=ref`をexact `0.5`へ写し、次の4 branch scoreを得ます。

closed dev-r7のaggregate-only診断から変更するhalf-scaleは3件だけです。`grain_rms_l`を`0.7 -> 0.875`、
`tiny_mass_l`を`20 -> 15`、`finite_line_top4_mean_l`を`4.5 -> 2.25`とし、他6件、raw metrics、branch構成、
単一threshold、endpoint count/rateは変更しません。単一reference変更は全候補不合格、2-reference変更で唯一通った
組に、decision-boundary距離を増すgrain 1件を加えました。dev-r8はpopulation gateでmeasurement前に閉鎖し、dev-r9は
同じmetricを一度だけ実行したもののthresholdを選べず閉鎖しました。dev-r10はgeneration中断、dev-r11はprivate
sentinel audit、dev-r12/dev-r13/dev-r14/dev-r15はpopulation audit、dev-r16はprivate sentinel audit、dev-r17はpopulation audit、dev-r18はprivate duplicate semantic auditで
metricを呼ぶ前に閉鎖しました。closed editionのthreshold、diagnostic、measurement、generation/review outputをformal判断へ移しません。

- `grain_score`: `max(min(unit occupancy, unit RMS), coherence * unit RMS)`
- `spot_score`: tiny component mass、tiny component count、multiscale blob strength のunit score最大
- `finite_line_score`: finite-line peak と top-4 mean の最大
- `parallel_bundle_score`: raw deltaへのcore-only responseから得る、同一angle/length filter内の
  weaker-pair peak とmatched-pair countの最小。matched pairsが2未満なら両raw evidenceをcanonical zeroにする

spot component floor、finite-line response floor、parallel-pair response floorはいずれもabsolute `4.5 L`です。
coherent fine patternはdirectional coherenceを含むgrain branchが担当し、spot/line branchへ役割を移しません。
split-specific schedulesとこれらのfloorは、fresh formal key、controls、labelsが存在する前に、明示的な
non-formal development keysでfreezeします。closed `dev-r6`～`dev-r15` corporaはdevelopment-onlyのfailure
evidenceに限定します。dev-r10はgeneration中断、dev-r11はprivate sentinel audit失敗、dev-r12/dev-r13/dev-r14/dev-r15はpopulation
audit失敗によりmetric evidenceを持ちません。dev-r16もprivate sentinel audit失敗、dev-r18もprivate duplicate semantic audit失敗によりmetric evidenceを持ちません。closed `dev-r17` は
`dev-r17-protocol-zero-reference-prequalification-schedule-v1`全scheduleをsubsettingなしで一回生成・reviewしました。artifact morphologyはdev-r16から
変更せず、dev-r16で行った変更は4 sparse familyで
各1 clean / 1 clear-rejectをwarningへ変えるexact 16 morphologiesだけで、184 nonconversion morphologiesは不変です。
formal labels、threshold、resultsは未確定であり、design tierからVision truthを保証・予告しません。既存のmetric、half-scale、
absolute floor、endpoint minima/rate、blind、one-shot、failed-r3/r4/r5およびclosed development境界は変更しません。

唯一の hard metric は次です。

```text
hard_composite_score = max(grain_score, spot_score,
                           finite_line_score, parallel_bundle_score)
```

`hard_composite_score > frozen_threshold` のときだけ reject します。4 branch の個別 threshold はなく、
freeze する scalar は1個です。parallel ratioを含む diagnostic values は非blockingで、追加 hard gate に
してはいけません。

calibration candidate は exact domain floor `0`、distinctな場合のnonnegative minimum-epsilon、観測値の
adjacent midpoints、upper outward sentinelから作ります。parallel evidenceはfilterを跨いでpeak/countを
合成しません。全endpointのminimum unique-cluster countとcalibration rateを満たすcandidateだけを
authority-admissibleとし、次の順で決定論的に最適化します。

1. grain、tiny-speck、microblob、short-line、parallel-bundle reject-cluster detection の最小値
2. combined spot reject-cluster detection
3. overall reject-cluster detection
4. severity-3 cluster detection
5. clean-cluster acceptance
6. warning-cluster acceptance
7. より厳しい lower threshold

全 endpoint は preregistered minimum unique-cluster count と calibration/holdout rate を満たさなければなりません。
threshold candidates、selection、全endpointのeligible roleはartifactだけで、protocol-zeroとduplicate-auditは
完全に除外します。artifact pairのtruthはclusterごとに `reject > warning > clean`、最大severity、visible flag ORへ
集約し、metric-equivalent pairには1 predictionだけを割り当てます。unique clustersは等重みです。count不足は
label seal・private audit後、数値測定とthreshold探索の前に検出し、post-marker failureとしてthresholdを作らず
editionを閉じます。countが充足していても全endpointを満たすcandidateがない場合は`hard_threshold:null`、
`selection_status:no-endpoint-admissible-threshold`で閉鎖し、最良の不合格候補はdiagnostic auditにだけ残します。
holdout は frozen single threshold を変更せず評価します。

dev-r17はgenerationと`440 × 2` reviewを一回だけ完了し、immutable bilateral initial receiptsを固定しました。calibrationの
logical 97件 + notes-only 17件、holdoutのlogical 84件 + notes-only 60件をすべてreconcileし、final intersection gate、official
preflight、両private auditをpassしました。しかしholdoutのtiny-speck / spot development floorsを満たさず、metricとthresholdへ
進まずfailed-and-closedです。sanitized read-only postmortemは一度だけで、hash-bound failure audit以外を後続判断へ使いません。
dev-r17のrerun、resume、relabel、別key、subsetting、top-up、および全素材・outputの再利用は禁止です。このfailureから
preregisterしたdev-r18は上記のscheduleを一回だけ実行しました。

dev-r18はgeneration、`440 × 2` blind review、bilateral reconciliation、official preflight、label sealing、private reveal、
regeneration、protocol-zero auditを各一度だけ完了しました。calibration obvious-artifact duplicate pairのdispositionとshort-line
flagは一致しましたがseverityが`2` / `3`に分かれ、当時のexact semantic checkをfailしました。population auditとnumeric metricを
開始せず`failed-and-closed-before-population-audit`で閉鎖しました。read-only postmortemは一度だけで、auditは
`world/map-production/qa/microtexture-v2-r6-dev-r18-development-failure.json`（raw SHA-256
`7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122`）です。全initial snapshots/receiptsを不変保存し、
dev-r18のrerun、resume、relabel、別key、subsetting、top-up、および全素材・outputの再利用を禁止します。このfailureから
preregisterした唯一の後続editionは、上記のfresh dev-r19 one-shot probeです。

## Formal stage order

dev-r18はprivate duplicate semantic auditをfailしてpopulation audit前に閉鎖し、fresh dev-r19はまだformal authorityではないため、
以下のformal stageはすべてblockedです。dev-r19 authority commitのpushとUbuntu/Windows CI成功より前にgenerationを開始できず、
dev-r19が成功してもそのoutputをformal authorityへ流用できません。

1. authority、bindings、ImageGen provenance、Vision reviews を tracked SHA/captured upstream HEAD に freeze し、
   working bytes と HEAD を preflightする。Ubuntu/Windows CI は formal run を生成せず、static/unit/golden-vector
   preflight のみを担当する。
2. 同一 machine/runtime fingerprint を全 formal stages に固定し、安全な fresh 32-byte blind key を専用の
   長寿命custodian processだけに置く。Vision processへkeyまたは環境を継承しない。
3. calibration controls を一度だけ生成する。
4. Root が calibration の全185 contact-sheet view-pages相当を確認し、exact label artifact を完成する。
5. calibration を一度だけ実行する。marker → label seal → secret regeneration → private audits → identity reveal → measurement → candidate selection →
   endpoint evaluation → report → completion の順を変えない。
6. calibration pass と threshold freeze 後に限り、locked-clean `v18` を一度だけ評価する。
7. allow-list の external authority が frozen calibration と locked-clean report を審査し、hash-bound tracked
   receipt を書く。
8. receipt を commit/push し、その HEAD で両CIを通す。
9. receipt と `v18` provenance/reviews を preflightして fresh holdout controls を一度だけ生成する。
   この preflight は stored authority の再検証であり `v18` の再測定ではない。
10. Root が holdout の全185 contact-sheet view-pages相当を確認し、exact label artifact を完成する。
11. holdout marker 後、frozen threshold を変えず一度だけ評価し、terminal report を actual files、sealed labels、
    marker、threshold、receipt、HEAD/runtime、secret-derived identity に再bindしてから completion を書く。

各stage markerのwrite自体をpost-marker failure guardの`try`内で行い、current-stage private identity reveal、
target decode、新規numeric measurement、selection、endpoint evaluationより前にdurableに書きます。terminal
completionを書いた直後は必ず`require_completion=True`でauthorityをreloadします。prior authority の stored decisions を marker 前に再計算して
整合確認することはできますが、source image の再測定ではありません。post-marker exception は failure report
を試み、通常 endpoint failure は `passed:false` completion を書きます。completion 欠落または failure coexistence
も fail-closed です。いずれの失敗も edition を消費し、regeneration、relabel、rerun、threshold change を禁止します。

## Production boundary

r6 detector は、別途 preregister された background reference から得た完全な 256×192 eligible-background
residual window のみを対象にします。roads、rivers、coasts、labels、symbols、settlements、その他 canonical
geometry を mask と filter-support erosion で除外し、partial window や denominator renormalization を禁止します。

r6 synthetic holdout pass は production derivation を直接承認しません。production source/reference、mask、
filter support、tile overlap/halo/seam、boundary、color/alpha/quantization/resampling、zoom/tile coverage、deterministic
outputs、window-to-master aggregation、untouched production holdout を候補測定前に別途 preregister しなければ
なりません。promotion には、実装と frozen threshold を変えず synthetic holdout と production holdout の両方を
通過することが必要です。
