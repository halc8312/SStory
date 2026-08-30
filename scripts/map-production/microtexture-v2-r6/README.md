# Microtexture v2-r6 authority

`preregistered-spec.json` が規範的 authority であり、この README は正式運用のための要約です。
r6 は fresh one-shot formal edition です。r3、r4、r5 は failed-and-closed の開発資料に限定され、
その control、key、label、threshold、foundation、locked source、holdout は r6 に再利用できません。
r5 の revealed failure は、r6 の bounded-unit score、condition-cluster truth aggregation、
population feasibility gate、corpus coverage を正式生成前に設計するためだけに使用しました。

freeze 前の non-formal development edition `dev-r6` も、label seal と private reveal 後、最初の数値metric callより
前の population audit で failed-and-closed になりました。calibration は tiny-speck reject cluster が3件、
holdout は clean 12件、tiny-speck reject 0件、spot reject 7件で当時の最低値に届かず、
`measurement_started=false` のまま threshold を作らず閉鎖しました。`dev-r6` の key、controls、labels、pixels、
measurementsをformal判断へ再利用しません。fresh `dev-r7` は両splitのpopulation safety floorを通過し、Rootと
独立Visionで全440 recordsを確認してlabelをsealした後、一度だけ測定しました。しかしclamp正規化により
calibrationのwarning 8/19 clustersとreject 55/56 clustersが同じscore `1.0`へ飽和し、全endpointを同時に満たす
thresholdが存在しなかったためfailed-and-closedです。thresholdは`null`、holdout endpoint performanceは未評価です。
sanitized evidenceは`world/map-production/qa/microtexture-v2-r6-dev-r7-development-failure.json`へ固定します。

fresh `dev-r8` は両splitの全440 recordsを新規生成・全件Vision・sealした後、最初の数値metric callより前の
population gateでfailed-and-closed-before-measurementになりました。tiny-speck-visible reject clusterは
calibration `3`、holdout `1`で、両方ともdevelopment-only floor `6`に届きませんでした。残る全
development-only population endpointは両splitで合格しました。`measurement_started=false`のまま、raw metrics、
hard composite score、threshold candidate search、development holdout endpoint evaluationを一度も実行せず、thresholdを
作成していません。sanitized auditは
`world/map-production/qa/microtexture-v2-r6-dev-r8-development-failure.json`へ固定します。dev-r8のroot、key、
controls、references、pixels、identities、codes、labels、measurements、noncesはformalまたは後続editionへ
再利用せず、閉鎖rootだけをforensic reproducibilityのため不変のまま保持します。

fresh `dev-r9` は speck population deficit を解消し、両splitの全population floorを通過して一度だけ測定しました。
しかしcalibrationではwarning acceptance `>=0.75`を初めて満たす候補でseverity-3 detectionが`25/26`となり、
severity-3を`26/26`に保てる候補ではwarning acceptanceが最大`12/18`でした。同じ単一thresholdで両方を満たせる
候補が0件だったため`failed-and-closed-after-measurement`です。selected thresholdとholdout endpoint performanceは
`null`で、sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r9-development-failure.json`へ固定します。dev-r9のroot、key、
controls、labels、pixels、identities、measurements、diagnostic threshold、nonces、commitmentsは再利用しません。

fresh `dev-r10` は一回限りのgenerationを開始しましたが、monitor session喪失後に対応process不在を確認し、terminal
generation summary / seal / completionへ到達しませんでした。終了原因は特定していません。generationは未完了、Vision review、label seal、private reveal、
analysis、measurement、threshold searchは未開始です。dev-r10はこの時点で消費・閉鎖し、exact root
`tmp/map-production/microtexture-v2-r6-dev-r10`を不変のまま保持します。generateの再実行、途中からのresume、
欠損splitのtop-up、root削除後の再生成、別key、partial controls / references / pixels / codes / commitmentsの流用を
禁止します。sanitized closure evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r10-development-failure.json`へhash-bindします。

fresh `dev-r11` はgenerationと全440 recordsのRoot/独立Vision review、reconciliation、preflight、label sealまで
一回だけ完了しました。しかしprivate reveal後、population auditより前のsentinel auditで、holdoutのexact-zero
protocol sentinel 1件にsealed nonclean / tiny-speck判定があることを検出しました。極めて薄い400%上の点状印象を、
無補正の`full-200`で各coreが直接見えるというrubricを満たさないままcross-scale morphologyとして数えたVision
false positiveです。dev-r11は`private-sentinel-audit-before-population-audit`でfailed-and-closedとなり、population
aggregation、raw metric、threshold search、holdout endpoint evaluationは未開始、`measurement_started=false`、
thresholdとholdout performanceは`null`です。sanitized evidenceを
`world/map-production/qa/microtexture-v2-r6-dev-r11-development-failure.json`へ固定します。匿名code/page/rowから
private identity/pixelへのbinding、private labels/identities/pixels、blind keyをsanitized auditへ記録せず、raw private
postmortemは起動・追跡しません。dev-r11のrerun、resume、relabel、retune、replacement、subset、top-up、key resampling、
root削除後の再生成、およびroot/key/control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/
public surfaceのformalまたは後続editionへの再利用を禁止します。

fresh `dev-r12` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitの
private auditを一度だけ完了しました。両private auditはpassしましたが、最初のmetric callより前のpopulation auditで、
calibration warningは`10`（formal minimum `10`はpass、development floor `13`はfail）、holdout warningは`9`
（formal minimum `10`とdevelopment floor `13`の両方をfail）でした。両splitのその他すべてのformal endpoint minimumと
development-only floorはpassしました。`measurement_started=false`のままraw metric、hard composite、threshold search、
holdout endpoint evaluationを開始せず、thresholdとholdout performanceは`null`です。閉鎖後のsanitized read-only
postmortemは一度だけ実行し、metricを呼ばず、private identity bindingも公開していません。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json`へ固定します。dev-r12 rootは不変に保持し、
rerun、resume、relabel、retune、subset、top-up、key resampling、root削除後の再生成、およびdev-r12の全素材・identity・
nonce・public surfaceのformalまたは後続editionへの再利用を禁止します。

`dev-r13` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitの
private auditを一度だけ完了し、両private auditはpassしました。しかしpre-measurement population auditでcalibration
warningは`14`（formal minimum `10` / development floor `13`ともにpass）、holdout warningは`12`（formal minimum
`10`はpass / development floor `13`はfail）でした。その他の全endpointは両splitでformal minimumとdevelopment floorを
passしました。all-or-nothing gateにより`measurement_started=false`のままmetric、hard composite、threshold search、
holdout endpoint evaluationを開始せず、thresholdとholdout performanceは`null`です。閉鎖後にsanitized read-only
postmortemを一度だけ実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json`です。dev-r13 rootは不変に保持し、rerun、
resume、relabel、retune、replacement、subset、top-up、key resampling、root削除後の再生成、およびdev-r13のroot/key/
control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/public surface/postmortem outputのformal・
後続editionへの再利用を禁止します。

`dev-r14` はgeneration、全440 recordsのRoot/独立Vision review、reconciliation、preflight、label seal、両splitの
private auditを一回だけ完了し、両private auditはpassしました。しかし最初のmetric callより前のpopulation auditで、
calibrationはclean `35`、warning `15`、reject `50`、severity 3 `13`、grain-visible reject `12`、tiny-speck-visible
reject `12`、microblob-visible reject `4`、spot-visible reject `16`、short-line-visible reject `22`、
parallel-bundle-visible reject `11`でした。microblobはformal minimum `4`をpassしましたがdevelopment floor `6`を
failし、calibrationのその他のendpointはformal minimumとdevelopment floorをpassしました。holdoutはclean `31`、
warning `16`、reject `53`、severity 3 `20`、grain-visible reject `11`、tiny-speck-visible reject `11`、
microblob-visible reject `9`、spot-visible reject `20`、short-line-visible reject `22`、parallel-bundle-visible
reject `11`で、全endpointがformal minimumとdevelopment floorをpassしました。all-or-nothing gateにより
`measurement_started=false`のままmeasurement、hard composite、threshold search、holdout endpoint evaluationを開始せず、
thresholdを作っていません。閉鎖後のsanitized read-only postmortemは一度だけです。sanitized evidenceは
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

`dev-r19`のstatusは`failed-and-closed-before-population-audit`です。exact roleは
`development-only prepopulation private-audit failure evidence; generation, both blind 440-record reviews, bilateral reconciliation, official preflight, label sealing, private reveal, regeneration, and protocol-zero audits each completed exactly once, calibration clean and obvious-artifact duplicate groups plus the holdout clean duplicate group passed, but holdout's obvious-artifact duplicate pair was clean severity 0 with no visible flags, so the required rejected short-line artifact contract failed before population audit or any numeric measurement; one read-only postmortem ran exactly once, all initial snapshots and receipts remain immutable, and no dev-r19 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
です。calibrationのclean duplicate groupとobvious-artifact duplicate group、holdoutのclean duplicate groupはpassしました。calibrationのobvious pairは両方`reject`、severity `3`、visible flagは`l`のみでしたが、holdoutのobvious pairは両方`clean`、severity `0`、visible flagなしでした。そのためpopulation aggregation、numeric measurement、metric evaluation、threshold searchを開始せずに閉鎖し、read-only sanitized postmortemを一度だけ実行しました。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json`、raw SHA-256は
`96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0`です。`dev-r19`のroot、key、private material、control、reference、pixel、identity、code、commitment、label、decision、measurement、nonce、public surface、postmortem outputは後続editionまたはformalへ一切再利用しません。

`dev-r20`のstatusは`failed-and-closed-before-measurement`です。exact roleは
`development-only premeasurement population failure evidence; both private audits passed, calibration tiny-speck population 0 and holdout tiny-speck population 1 each missed formal minimum 4 and development floor 6, every other endpoint passed both minima, no numeric metric or threshold search started, one read-only postmortem ran exactly once, all Root and Independent initial snapshots and receipts remain immutable, and no dev-r20 root, key, private material, control, reference, pixel, identity, code, commitment, label, decision, measurement, nonce, public surface, or postmortem output is reusable`
です。generation、両reviewerの`440 × 2` blind review、bilateral reconciliation、official preflight、label sealing、private reveal、regeneration、protocol-zero / duplicate auditsを各一度だけ完了し、両private auditはpassしました。premeasurement population auditではcalibration tiny-speck population `0`とholdout tiny-speck population `1`がformal minimum `4` / development floor `6`をともにmissし、他の全endpointは両minimumをpassしました。numeric metricとthreshold searchを開始せず閉鎖し、read-only sanitized postmortemは一度だけです。auditは
`world/map-production/qa/microtexture-v2-r6-dev-r20-development-failure.json`、raw SHA-256は
`e8689321135e8c5d3fb038fbaa7c3ccbe644999905f4a3d3834fa30969ff27c8`です。dev-r20はこのままfailed-and-closedであり、唯一preregisterしたsuccessorはfresh development-only `dev-r21`です。

`dev-r20`はschedule revisionは`dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1`、sentinel revisionは
`dev-r20-keyed-axial-short-line-duplicate-sentinel-v1`です。obvious-artifact duplicateだけを、当該editionのfresh keyとsplit / condition identityから決定するpositive `+12.0 L`のaxial bar `12`本へ変更しました。各barはencoded `24×3 px`、metric windowの各exact quadrantに`3`本、各quadrantにhorizontal / verticalの両方を含み、center間Chebyshev distanceは`>=32 px`、support guardは`>=2 px`、nonzero supportは計`864 px`です。pairはrequested delta、decoded residual、metricをexactに等しくし、reference、control、anonymous code、control IDは異ならせました。有限pixel geometry契約と両private auditはpassしましたが、artifact population全体のVision truthは保証されず、tiny-speck population gateをfailしました。

clean duplicate construction、`dev-r19`のreject severity-band policy、全200 artifact morphologies、全design tier、metric、threshold、population、rate contractは不変です。full artifact morphology SHA-256は
`9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365`、sanitized r19 basis SHA-256は
`8a99bb7038b5936ac7e44ac339114dc46f78e5d2a8df923a7be0674693d85933`、sentinel manifest SHA-256は
`2ee513f2a3182741fbf9df569a2c5137a7f25b4fd27d3fbba6b00344497b85a1`です。population-anchor schedule keyset / changed-values SHA-256は
`b5c8211902bb03838e7fe402bbb48e0e7f7a9db37acd1856be3dca2c67b82134` /
`3b87c5aabee0c8c8641d80496123a4f2dd58ca60f6da2bcf822e6bc7dfa80368`、probe authority manifest SHA-256は
`584deb41c74d8beeff030c33f1ed0116c4e583c9c60a41e010fb6233972b05a2`です。

消費済みclosed rootは`tmp/map-production/microtexture-v2-r6-dev-r20`、public noncesは`r6-calibration-v15` / `r6-holdout-v15`です。condition-cluster / render-seed / opaque-code / private-reference-transformはv15、public payload commitmentはv16、key commitment / foundation-offset / foundation-assignment / delta / private-control-idはv14です。protocol-zero nonce basesは`1251000` / `1261000`、artifact basesは`1273000` / `1283000`、duplicate-audit noncesは`1291000..1291002` / `1301000..1301002`です。generationはexact authority commitのpushと同一commitのUbuntu / Windows CI両方のgreen後に一度だけ実行済みです。`dev-r20`はformal authorityを供給できず、全root / key / material / outputを再利用しません。formal stageはblockedです。

`dev-r21`のstatusは`fresh-development-only`です。exact roleは
`fresh one-shot development role used only to strengthen the reject-tier artifact-speck population after the closed dev-r20 premeasurement tiny-speck population miss; it changes exactly the ten preregistered reject-speck conditions per split to the encoded hard-plus overlay, preserves the other 180 artifact morphologies, every design tier cardinality, metric, threshold, population and rate contract, the dev-r19 reject severity-band duplicate policy, and both r20 duplicate constructions; Vision truth is not guaranteed, all identities and audit roles remain private, and it can never supply formal authority`
です。schedule revisionは`dev-r21-symmetric-hard-point-speck-population-schedule-v1`、overlay revisionは`dev-r21-reject-speck-encoded-hard-plus-v1`です。各splitの既存reject-tier speck 10条件だけを、diameter `1`、center amplitude `12.0 L`、shoulder fraction `0.92`（encoded center `12 L` / 四つのencoded axial shoulder各`11 L`）、count `12..21`のhard-plusへ置換します。calibrationの`index:count/separation`は`3:12/30, 5:13/32, 7:14/34, 8:15/31, 15:16/33, 19:17/35, 6:18/30, 12:19/32, 16:20/34, 17:21/36`、holdoutは`3:12/31, 4:13/33, 6:14/35, 10:15/32, 11:16/34, 18:17/36, 1:18/31, 9:19/33, 13:20/35, 14:21/37`です。他180 artifact morphologies、両duplicate construction、tier cardinality、formal/development minima、metric、threshold、rateは変更しません。このcoverage設計はVision truthや通過を保証しません。

fresh root / keyは`tmp/map-production/microtexture-v2-r6-dev-r21` / `tmp/map-production/microtexture-v2-r6-dev-r21/private/development-key.bin`です。public noncesは`r6-calibration-v16` / `r6-holdout-v16`、condition-cluster / render-seed / opaque-code / private-reference-transformはv16、public payload commitmentはv17、key commitment / foundation-offset / foundation-assignment / delta / private-control-idはv15です。protocol-zero nonce basesは`1351000` / `1361000`、artifact basesは`1373000` / `1383000`、duplicate-audit noncesは`1391000..1391002` / `1401000..1401002`です。keyはtracked runner内で`secrets.token_bytes(32)`により一度だけ新規生成し、r20以前のroot、key、private material、identity、nonce、control、reference、commitment、label、decision、measurement、outputを再利用しません。

dev-r21はauthority登録だけの状態です。generation、Root/Independent Vision、reconciliation、preflight、label seal、private reveal、measurement、threshold search、failure/success auditはいずれも未開始で、生成物やaudit outputは存在しません。exact authority commitをpushし、その同一commitでUbuntu / Windows CIが両方greenになるまでgenerationは禁止です。dev-r21がdevelopment gateを通過したという主張はなく、formal stageは引き続きblockedです。

dev-r21のsanitized dev-r20 basis / reject-speck overlay manifest / preserved dev-r20 morphology / full dev-r21 artifact morphologyのcanonical SHA-256は、それぞれ`60a781e4a74ce4b31a4513b66bfbae1362c39fe373c3f8ff3f5a4a9c587ce610` / `9f85d79300a23b9c6f7cec27048d91cd8b1bcce98e395f792797a795156210cc` / `03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf` / `99aa3643bdddc0cd1257cbda0b5784cf08f90b80f947ef34ca90c71093046595`です。r21 catalog bindingのcanonical SHA-256は`62f9694518072db42601b57f3a88b97c34c34eda344142b0809e3c636b11ff4f`です。

## ImageGen authority

正式な fresh foundation corpus は、Vision-qualified 済みの ImageGen `v15`、`v16`、`v17`
だけです。各画像は 1536×1024 で、control/reference の基礎として使える範囲は中央
`[512,320,512,384]` crop に限定されます。その内部の detector/Vision 対象は
`[128,96,256,192]`、すなわち元画像上の `[640,416,256,192]` です。
事前の画像資格基準は 94/100 以上で、Root と2件の独立Vision reviewを通過したexact bytesだけを採用します。

foundation は secret HMAC で `v15`～`v17` に割り当てますが、各 record の reference はさらに full private
record identity（polarity と replicate を含む）を入力とする full-output HMAC-SHA-256 counter-mode PRF から
個別生成します。7×9 coefficient grid を滑らかに補間し、最大 1.75 px の warp と最大 0.75 L の tone shift
だけを加えます。各 split の220 reference SHA、220 control SHA、および5 viewそれぞれの220 panel SHAは
すべて一意でなければなりません。

この blind は、honest reviewer が割り当てられた review surface だけを見るための**運用上の blind**です。
technical / cryptographic blind や、同じ OS principal で悪意ある reviewer に対する secrecy は主張しません。
formal fresh key は専用の長寿命 custodian process だけが保持し、artifactやlogへ永続化せず、Vision processへ
継承・公開しません。closed dev-r8/dev-r9/dev-r10/dev-r11/dev-r12/dev-r13/dev-r14/dev-r15/dev-r16 keyは各Git-ignored private rootにだけ保持して
再利用せず、closed dev-r17/dev-r18/dev-r19/dev-r20 keyも各Git-ignored private rootに保持するforensic evidenceだけとし、
既存または後続operationへ一切再利用しません。fresh dev-r21 keyは別のGit-ignored private rootとtracked custodian runnerだけが保持し、r20以前のkeyを継承しません。marker 前の
review surface は185 contact-sheet view-pages（各view 37 pages）とcode-only label formだけです。manifest schema
`microtexture-v2-r6-control-manifest/3` が公開する record 情報は opaque code と code別の
`control` / `reference` / `delta` HMAC commitment 3件だけで、個別control/referenceのpath、file、raw bytes、
raw SHAは公開しません。Vision process はlabel sealまでsource、authority code、raw extraction、hash/diff、
filesystem比較、identity regenerationを使用してはいけません。

`v18` は foundation corpus とは別の、Vision-qualified 済み locked-clean reference です。
その固定 path は
`world/map-production/style-assets/microtexture-v2-r6-locked-clean-reference-imagegen-v18.png`
です。calibration と threshold selection から完全に除外し、threshold freeze 前の decode、測定、
数値参照を禁止します。freeze 後に一度だけ検証し、hard composite が accept しなければ r6 は閉じます。
事前の画像資格基準は同じく94/100です。Independent Aはformal preflightが直接再検証する必須review、
Independent Bはgeneration receiptがhash-bindする補足reviewです。

`v15`～`v17` と `v18` はいずれも validation-only です。production art、Golden input、texture donor、
final pixel として使ったり、そこへ pixel を転送したりしてはいけません。正式 calibration/holdout 中に
production candidate、Golden candidate、または未登録画像を読むことも禁止です。

## Control population

calibration と holdout はそれぞれ 220 records、118 unique private clusters です。

| private role | records | clusters | 契約 |
|---|---:|---:|---|
| artifact | 200 | 100 | 5 morphology families × 20 nonzero conditions × dark/light pair |
| protocol-zero | 16 | 16 | control bytes が reference bytes と完全一致する exact-zero sentinel |
| duplicate-audit | 4 | 2 | clean 1組と obvious-artifact 1組、各2 distinct-reference semantic replicates |

artifact の5 family は、compact `control_families` schema の次の ID だけです。

- `artifact-fine-grain`
- `artifact-speck`
- `artifact-microblob`
- `artifact-short-dash`
- `artifact-parallel-bundle`

dev-r16でfreezeしclosed dev-r17がmorphologyを変更せず継承したdevelopment Vision scheduleでは、各familyの20 nonzero conditionsを4つのdesign tierへ配分し、
fine-grainを`5 / 4 / 7 / 4`、4つのsparse familyを各`4 / 6 / 6 / 4`としてcorpus coverageを固定します。calibrationとholdoutはspecに記録された
split別のfrozen scheduleとpublic nonceを使います。tierはperceptual marginを広く試すための生成設計であり、
`clean`、`warning`、`reject`、severityその他のVision truthを予告・割当するものではありません。
全scheduleを一体として生成・blind reviewし、結果を見てsubsetting、top-up、key resamplingしてはいけません。

dev-r9で固定したspeck scheduleはpopulation floorを両splitで通過しました。dev-r10では
`artifact-fine-grain`のfull-support reject-tier 3条件だけを事前に変更し、calibrationのperiod `14.0`を`11.6`、
holdoutの`12.6`を`11.4`、`14.6`を`11.8`へ置き換えました。これにより全11 reject-tier grain conditionsは、
変更しないcoherence metric support `2..13`のguard-bandedな内側`3..12`へ入ります。dev-r10はgeneration中断で
Vision/analysisへ到達せず、dev-r11はprivate sentinel auditでpopulation aggregationとmetricより前に閉鎖したため、
いずれのcorpusからもscheduleを評価・調整しません。dev-r12は両private auditとwarning以外の全population endpointを
passしましたが、warning population不足で測定前に閉鎖しました。dev-r13も両private auditをpassし、calibration warning
`14`をformal minimum `10` / development floor `13`の両方でpass、holdout warning `12`をformal minimum `10`でpassしましたが、
holdout development floor `13`だけをfailしたため測定前に閉鎖しました。その他の全endpointは両splitで両minimumをpassしました。
dev-r14もtier数`5/4/7/4`を維持して一体生成・blind reviewし、両private auditをpassしましたが、calibrationの
microblob-visible rejectが`4`でformal minimum `4`だけをpassし、development floor `6`をfailしたため測定前に閉鎖しました。
calibrationのその他のendpointとholdoutの全endpointはformal minimumとdevelopment floorをpassしました。

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
scheduleはblindなgeneration coverageであり、Vision truth、microblob label、endpoint membership、またはgate通過を保証・予告しませんでした。
r15 runtime outputsは閉鎖済みであり、top-up、relabel、retuneまたは後続editionへの再利用を認めません。

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

family identityを保つmorphology invariantsも全tierで不変です。fine-grainはfield-wideな反復/coherenceを保ち、
spotやlineへ形態を移しません。speckは互いに分離した同程度のpoint-like hard coreを3個以上保ち、blurでmicroblob化
させません。microblobはcompactな中心/境界を保ち、diffuse cloudやspeck列へ変えません。short-dashは有限の
straight strokeと端点を保ちます。parallel-bundleは同極性・非接触の有限stroke pairを保ち、散在、交差、
接触、merged shapeで本数を水増ししません。

各 artifact family は `private_role=artifact`、`polarities=[-1,1]`、20 clusters、40 records です。
全100 artifact cluster は nonzero requested delta を持ち、control は reference と異なります。
artifact family に zero-count condition はありません。dark/light は別々の private reference を使いますが、
同じ位置・角度・unsigned geometryから requested deltaをexact sign inverseとして作ります。量子化後のdecoded
`control-reference` int16 residualもexact inverse、対応metricsもexact equalityでなければgenerationを拒否します。

16 protocol-zero は foundation/label protocol の sentinel です。各record内ではcontrolとreferenceが一致し、
必ず `clean`、severity 0、visible flagなしでなければなりません。4 duplicate-audit records は blind
consistency audit です。同じsemantic conditionを持つ2 recordsはprivate reference/controlが互いに異なる一方、
requested delta、decoded residual、metricsがexact equalityであり、2 labelのdisposition、severity、全visible
flagも一致しなければなりません。protocol-zero と
duplicate-audit は artifact endpoint、threshold candidate、threshold objective から除外されます。
これらの semantic audit は公開 manifest の image equality から marker 前に補正しません。順序は
durable marker → exact label-byte seal → 全control/referenceのin-memory regeneration → exact contact-sheet byte
binding → private sentinel/semantic-replicate audit → control/reference measurement です。obvious-artifact replicate
は両方とも severity 2/3 の reject、かつ
`short_line_visible=true` を要求し、不一致は edition を消費する post-marker failure です。

calibration と holdout は public nonce、parameter nonce、HMAC identity、opaque code、control ID、nonzero
requested-delta hash が分離されています。parameter value/range 自体の分離は主張しません。意図的な
exact-zero sentinelだけはcanonical all-zero requested-delta hashを共有します。polarity と
replicate は独立 cluster と数えません。artifact polarity pairのVision truthは
condition clusterごとに `reject > warning > clean` のworst-case disposition、最大severity、visible flagsのORへ
保守的に集約し、metric-equivalent pairには1 predictionだけを割り当てます。その後unique clustersを等重みで
集計します。1 clusterをaccept/reject endpointの双方へ入れることは禁止です。

closed `dev-r8` / `dev-r9` / `dev-r12` / `dev-r13` / `dev-r14` / `dev-r15` / `dev-r16` / `dev-r17` の一回限りのanalysisには、formal specのendpoint最低populationを
一切変更せず、さらに厳しいdevelopment-only safety floorを上乗せします。dev-r10はanalysis前、dev-r11はprivate
sentinel audit、dev-r18/dev-r19はprivate duplicate auditでpopulation aggregation前に閉鎖したため、このgateの結果を持ちません。label bytesを両splitともsealし、private identityを
revealしてsemantic auditを終えた後、最初のmetric callより前にcondition-cluster truthで次を検査します。

| development-only population | minimum unique clusters / split |
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

`dev-r8`ではtiny-speck-visible rejectがcalibration 3、holdout 1でfloor 6を下回り、他の全population endpointは
passしました。したがってgate全体をfailとして`measurement_started=false`のまま
`failed-and-closed-before-measurement`で消費・閉鎖しました。raw metrics、composite、candidate、threshold探索、
holdout endpoint evaluationは一切行わず、authority thresholdも作っていません。sanitized failure evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r8-development-failure.json`です。dev-r8のkey、controls、
references、pixels、identities、opaque codes、labels、measurementsはdev-r9以降またはformalへ再利用しません。

dev-r9はこのgateを両splitで通過しましたが、calibrationでendpoint-admissible thresholdが存在せず、測定後に
閉鎖しました。dev-r10はgeneration中断、dev-r11はprivate sentinel audit失敗のためgateへ到達していません。
dev-r12は両private auditをpassした後、calibration warning `10 < 13`、holdout warning `9 < 13`でgateをfailし、
`measurement_started=false`のまま閉鎖しました。dev-r13も両private auditをpassしましたが、calibration warning `14`は
formal minimum 10 / development floor 13をpass、holdout warning `12`はformal minimum 10をpassしてdevelopment floor 13だけを
failしたため、`measurement_started=false`のまま閉鎖しました。dev-r13のその他の全endpointはformal minimumとdevelopment
floorをpassしました。dev-r14も両private auditをpassしましたが、calibration microblob-visible reject `4`はformal
minimum `4`をpassしてdevelopment floor `6`をfailしました。calibrationの他endpointとholdout全endpointは両minimumを
passし、`measurement_started=false`のまま閉鎖しました。dev-r15も両private auditをpassした後、calibration warning `12`が
formal minimum `10`をpassしてdevelopment floor `13`をfailし、holdout warning `9`が両minimumをfailしたため、他の全endpointが
両minimumをpassしていても測定前に閉鎖しました。dev-r16はprivate exact-zero sentinel false positiveでpopulation gate前に
閉鎖しました。dev-r17は両private auditをpassしましたが、holdout tiny-speck `0`とspot `9`がdevelopment floorを
満たさなかったため、`measurement_started=false`のまま消費・閉鎖しました。数値metric、threshold探索、ラベル修正、
top-up、別keyでの再生成へ進みません。このmargin gateとgrain support scheduleはdevelopment専用であり、
Vision truthではありません。formal common endpoint minima、rate、metric、candidate selection、one-shot契約を
変更しません。

## Root Vision review

Root は各 split の全220 codesを、次の5 viewで漏れなく確認します。

- `full-200`: metric window 全体を 200% 表示。`review-crops`は同じcontact-sheet bytesからcrop-only derivativeとして
  各rowの表示pixelを追加拡大なしのnative
  512×384 `review-page-...-row-...-full-200-native.png`として切り出す
- `northwest-400`、`northeast-400`、`southwest-400`、`southeast-400`: metric window を隙間・重複なく4分割し 400% 表示

1 view は37 pages、合計は split あたり 185 contact-sheet view-pagesです。development helperは同じpage indexの
5 viewを横並びにした37 review boardsも作ります。全 view は同じ code 順序を持ち、nearest-neighbor
で拡大されます。closed dev-r15/dev-r16/dev-r17/dev-r18へ適用した規約では、native 512×384 full-200 cropを無補正・contrast強調なしで先に確認し、400%は
同位置の再同定だけに使います。各512×384 panelの直前には30pxのcode headerがあり、codeをpanel下へ置くこと、headerとpanelを
重ねることは禁止します。Root は生成された exact path の label stub に、`disposition`、5種の visible flag、
severity、200%確認、全400% quadrant確認、notes を記入します。全185 view-pages相当を確認する前に one-shot
evaluation を開始してはいけません。

RootとIndependentはreconciliation前に各splitのofficial initial snapshot
`decisions-root.initial.dev.txt` / `decisions-independent.initial.dev.txt`と対応する`.sha256` receiptを作成します。receiptは
`lowercase-sha256 two-spaces snapshot-basename newline`、両snapshotはofficial parser、220-record coverage、anonymous-code
bindingをpassしなければなりません。reconciliation後の`vision-decisions.dev.txt` / `decisions-root.dev.txt` /
`decisions-independent.dev.txt`はthree-way exact bytesとし、各recordのfinal `g,t,b,l,p` setはRoot initialとIndependent
initialのflag intersectionのsubsetでなければなりません。disposition、severity、notesはこのsubset gateの対象外ですが、通常の
schema/semantic validationを通します。private roleはこのgateの入力にせず、label sealは
`microtexture-v2-r6-development-label-seal/3`を使用します。

Root は全 anonymous record に、規範 `labels.vision_observation_rubric`
`microtexture-v2-r6-injected-morphology-only/3` を reveal 前に同一適用します。判定対象は、許容clean substrateから
視覚的に分離できる synthetic morphology です。境界のない広い低周波・非周期のpaper clouding、滑らかなmottling、
緩いtone drift、疎で孤立したsoft・irregular・low-contrast organic fleckだけなら `clean`、severity 0、全flag falseです。
絶対的な非一様性だけをartifactにしてはいけません。400%で初めて気付くfaint diffuse/soft-edge pinprickもcleanです。
形態を数えるには、contrast強調なしで`full-200`に直接見え、対応400% quadrantの同位置で再同定できることが必須です。
400%だけの印象はflagを立てません。

- grain: 広い領域に続く高周波の反復、周期、方向性、coherenceを持つ縞・格子・halftone
- tiny speck: 同程度のfootprint/polarityを持つ独立したpoint-like hard coreを3個以上それぞれ位置指定できること。
  各coreは400%で一意に位置指定でき、全方向で概ね1 core幅以内に背景へ戻り、soft substrateより明確に
  sharp/high-contrastで、`full-200`の同位置にも見えること。diffuse、feathered、irregular soft fleck、孤立した
  単独core、単なるtone extremaは除外
- microblob: 局所中心または境界を持つcompact blob。広いedge-free cloudingは除外
- short line: 端点と長軸を持つ有限のstraight dash/line。滑らかなtone contourや許容fiber-like variationは除外
- parallel bundle: full-200で個別に見える同極性・非接触の2 strokeを同一400% quadrantで一緒に再同定でき、
  無向軸角差10°以下、edge-to-edge垂直gapが2本の可視centerline長の算術平均以下かつ正、mean axis上の投影が
  短い方の50%以上重なるpairだけ。散在、交差、接触、merged、異極性、単に似た角度だけでは不足し、`p` は必ず
  `l` もtrueにする

flagは非排他的です。notesはASCII固定形
`ev3:g=<set>;t=<set>;b=<set>;l=<set>;p=<set>` だけを許し、locatorは
`(NW|NE|SW|SE)-R[1-3]C[1-3]-N(01..99)`、空集合は`-`です。clauseはg,t,b,l,p順、locatorは
quadrant NW/NE/SW/SE、row、column、ordinal順で、空白・自由文・重複を禁止します。true flagは非空set、false flagは
`-`、tiny-speckは3 distinct locators以上です。parallel pairは2 stroke midpointでsectorを選び、同じlocatorをlとpへ
記録します。stroke全体がsector内に収まる必要はありません。根拠位置を記録できなければflagはfalseです。
marker前には、このcanonical `ev3` syntax、flag/evidence binding、tiny-speckの3-locator cardinality、parallelの
l/p locator bindingもpublic schema/coverage/semantic整合とともに検証します。raw hash equalityやprivate sentinel
membershipをlabel修正へ使うことは禁止します。
対象形態が全predicateを満たすが
弱い場合だけwarning/severity 1とし、warningを「不確か」の退避先にしません。
明瞭な局在・反復ならreject/severity 2、支配的・高contrast・field-wideならreject/severity 3です。source/reference/hash/
diff/family/role/polarity/sentinel/duplicateの推測・比較は禁止します。各判定は次のpageへ進む前に印字anonymous codeへ
直接記録・照合し、page/rowだけを記憶して後からまとめて転記してはいけません。private audit失敗はeditionを閉じるだけで、
relabelを許可しません。

## Hard detector

detector は中央 256×192 luminance-residual window に対し、固定 raw metrics から4 branch scoreを作ります。

1. `grain_score`
2. `spot_score`
3. `finite_line_score`
4. `parallel_bundle_score`

spot component floor、finite-line response floor、parallel-pair response floor はすべてabsolute `4.5 L`です。
coherent fine patternはspot/line branchではなく、directional coherenceを含むgrain branchが担当します。
split-specific morphology schedulesとこれらのabsolute floorは、fresh formal key、controls、labelsより前に
明示的なnon-formal development keysでfreezeします。closed `dev-r6`～`dev-r15` corporaは正式判断に使いません。
dev-r10はgeneration中断、dev-r11/dev-r16はprivate sentinel audit失敗、dev-r18/dev-r19はprivate duplicate audit失敗によりmetric evidenceを持たず、dev-r12/dev-r13/dev-r14/dev-r15もpopulation
gate失敗によりmetric evidenceを持ちません。closed `dev-r17` は
`dev-r17-protocol-zero-reference-prequalification-schedule-v1`の全scheduleをsubsettingなしで一回だけ生成・reviewしました。artifact morphologyはdev-r16から
変更せず、dev-r16で行った変更は4 sparse familyで
各1 clean / 1 clear-rejectをwarningへ変えるexact 16 morphologiesだけで、184 nonconversion morphologiesは不変です。
formal labels、threshold、resultsは未確定であり、design tierからVision truthを保証・予告しません。既存のmetric、half-scale、
absolute floor、endpoint minima/rate、blind、one-shot、failed-r3/r4/r5およびclosed development境界は不変です。

各 branch は固定half-scale referenceに対する
`unit_soft(x,ref)=0 (x<=0), otherwise (2/pi)*atan(x/ref)` で正規化します。有限の正の証拠に対して厳密単調で
`0..1`未満に有界、`x=ref`はexact `0.5`です。観測値を分母に使わず、warning/rejectの強度差を有限値で
同一ceilingへ潰しません。grain coherenceは0..1のraw係数をRMS soft-unit scoreへ乗じます。唯一の hard scalar は

r7の閉鎖済みaggregate診断から変更するhalf-scaleは3件だけです。`grain_rms_l: 0.7 -> 0.875`、
`tiny_mass_l: 20 -> 15`、`finite_line_top4_mean_l: 4.5 -> 2.25` とし、他6件、raw metrics、branch構成、
単一threshold、全endpoint count/rateは不変です。単一reference変更は全候補不合格、2-reference変更で唯一通った組へ、
判定境界を広げるgrain 1件を加えたrevisionです。dev-r8はpopulation gateでmeasurement前に閉鎖し、dev-r9は
同じmetricを一度だけ実行したもののthresholdを選べず閉鎖しました。dev-r10はmetricを呼ぶ前のgeneration中断で
閉鎖しました。dev-r11/dev-r16はprivate sentinel audit、dev-r12/dev-r13/dev-r14/dev-r15/dev-r17はpopulation audit、dev-r18/dev-r19はprivate duplicate auditでmetric前に閉鎖しました。
dev-r17/dev-r18/dev-r19では数値metricを一度も呼ばず、thresholdを作りませんでした。closed editionのthreshold、diagnostic、measurement、
generation/review outputをformalへ使用しません。

```text
hard_composite_score = max(
  grain_score,
  spot_score,
  finite_line_score,
  parallel_bundle_score
)
reject = hard_composite_score > frozen scalar threshold
```

です。parallel branch は raw delta の core-only line response を使い、pair peak と matched-pair countを
同じ angle/length filter 内で結合します。matched pairs が2未満なら canonical `(peak,count)=(0,0)` です。
別filterの強いpeakとcountを混ぜません。branch ごとの独立 threshold や OR gate はなく、freeze する threshold はこの最大 composite の
1個だけです。raw/diagnostic metrics を追加の hard rejector にしてはいけません。calibration は clean
cluster acceptance 0.95以上、warning cluster acceptance 0.75以上を含む、全endpoint count/rateを満たす候補だけから、規範specの固定
objective order により1値を選びます。candidate set は exact domain floor `0` を必ず
含み、minimum-epsilon、adjacent midpoint、upper outward sentinel を加えます。selection と全endpointに
eligibleなのは `private_role=artifact` だけです。holdout はその値を変更せず使用します。
population countはlabel seal・private audit後、数値測定とthreshold探索の前に検査します。一つでも不足すれば
post-marker failureとしてauthority thresholdを作らず閉鎖します。countが充足していても全endpoint-admissible
candidateがなければ`hard_threshold:null`で閉鎖します。最良の不合格候補はdiagnostic auditにだけ記録し、
freezeや後続stageへ渡しません。

## Development closure

dev-r8は全440 decisionsをreview、seal、private auditした後、最初のmetric callより前のpopulation gateで
`failed-and-closed-before-measurement`となりました。tiny-speck-visible rejectはcalibration 3、holdout 1で、
他のdevelopment-only population endpointsは全てpassしました。失敗後のgenerate/analyze再実行、decision変更、
別key、subsetting、top-up、artifact再利用は禁止です。

dev-r9も一回限りで測定後に閉鎖しました。両population gateはpassしましたが、warning acceptanceとseverity-3
detectionを同時に満たすcalibration thresholdはありませんでした。dev-r9の再実行、再label、別key、subset、top-up、
diagnostic threshold昇格、holdout measurementの再解析を禁止します。

dev-r10は一回だけgenerationを開始しましたが、monitor session喪失後に対応process不在を確認し、終了原因を特定しないままsummary / seal / completionへ到達せず、
Vision、label seal、private reveal、analysis、measurementを開始せず消費・閉鎖しました。closed rootは不変に保持し、
generateの再実行、resume、欠損分top-up、root削除、別key、partial outputの再利用を禁止します。

dev-r11は全Vision decisionのseal後、最初のprivate sentinel auditでexact-zero sentinelへのsealed false positiveを
検出し、population aggregationと全数値metricより前に消費・閉鎖しました。sanitized audit以外のraw private postmortemを
追跡せず、dev-r11の再実行、resume、relabel、decision修正、別key、subset、top-up、artifact/identity/nonce再利用を禁止します。

dev-r12は両splitのprivate auditをpassしましたが、warning populationがcalibration 10、holdout 9でdevelopment floor 13に
届かず、holdoutはformal minimum 10にも届かなかったため、metricとthreshold searchを開始せず消費・閉鎖しました。
閉鎖後にsanitized read-only postmortemを一度だけ実行し、rootを不変に保持します。dev-r12の再実行、resume、relabel、
retune、decision修正、別key、subset、top-up、または素材・identity・nonce・public surfaceの再利用を禁止します。

dev-r13は両splitのprivate auditをpassし、calibration warning `14`はformal minimum 10 / development floor 13をpass、
holdout warning `12`はformal minimum 10をpassしてdevelopment floor 13だけをfailしました。他の全endpointは両splitで
formal minimumとdevelopment floorをpassしました。metricとthreshold searchを開始せず`measurement_started=false`で
消費・閉鎖し、閉鎖後にsanitized read-only postmortemを一度だけ実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json`です。dev-r13のrerun、resume、relabel、retune、
decision修正、別key、subset、top-up、およびroot/key/control/reference/pixel/identity/code/commitment/label/decision/
measurement/nonce/public surface/postmortem outputの再利用を禁止します。

dev-r14は両splitのprivate auditをpassしました。calibrationはclean `35`、warning `15`、reject `50`、severity 3 `13`、
grain `12`、tiny-speck `12`、microblob `4`、spot `16`、short-line `22`、parallel-bundle `11`でした。microblobはformal
minimum `4`をpassしてdevelopment floor `6`だけをfailし、他endpointは両minimumをpassしました。holdoutはclean `31`、
warning `16`、reject `53`、severity 3 `20`、grain `11`、tiny-speck `11`、microblob `9`、spot `20`、short-line `22`、
parallel-bundle `11`で全endpointが両minimumをpassしました。measurementとthreshold searchを開始せず
`measurement_started=false`で消費・閉鎖し、sanitized read-only postmortemを一度だけ実行しました。sanitized evidenceは
`world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json`です。dev-r14のrerun、resume、relabel、retune、
replacement、別key、subset、top-up、およびroot/key/control/reference/pixel/identity/code/commitment/label/decision/measurement/nonce/
public surface/postmortem outputの再利用を禁止します。

dev-r15はwarning population gate failureとして測定前に閉鎖済みであり、続行、再生成、修正または成果物の再利用を
認めません。dev-r16もprivate exact-zero sentinelへのseverity-1 short-line warning false positiveにより、population aggregation、
measurement、threshold searchを開始せず閉鎖済みです。両official initial snapshots/receiptsを不変保存し、read-only postmortemを
一度だけ実行しました。dev-r16の続行、再生成、decision修正または素材再利用を認めません。

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
dev-r18のrerun、resume、relabel、別key、subsetting、top-up、および全素材・outputの再利用を禁止します。

dev-r19はgeneration、`440 × 2` blind review、bilateral reconciliation、official preflight、label sealing、private reveal、regeneration、protocol-zero auditを各一度だけ完了しました。calibrationのclean / obvious-artifact duplicate groupsとholdoutのclean duplicate groupはpassしましたが、holdout obvious-artifact pairは両方`clean`、severity `0`、visible flagなしで、各memberに必須の`reject`、severity `2` / `3`、`short_line_visible=true`契約をfailしました。population auditとnumeric metricは開始せず`failed-and-closed-before-population-audit`で閉鎖し、read-only postmortemは一度だけです。auditは`world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json`、raw SHA-256は`96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0`です。dev-r19の全素材・outputは再利用できません。

dev-r20はgeneration、`440 × 2` blind review、bilateral reconciliation、official preflight、label sealing、private reveal、regeneration、両private audit、premeasurement population auditを各一度だけ実行しました。両private auditはpassしましたが、calibration / holdoutのtiny-speck populationは`0` / `1`で、formal minimum `4`とdevelopment floor `6`をともにmissしました。他の全endpointは両minimumをpassしました。numeric metricとthreshold searchを開始せず`failed-and-closed-before-measurement`で閉鎖し、read-only postmortemは一度だけです。auditは`world/map-production/qa/microtexture-v2-r6-dev-r20-development-failure.json`、raw SHA-256は`e8689321135e8c5d3fb038fbaa7c3ccbe644999905f4a3d3834fa30969ff27c8`です。dev-r20の全素材・outputは再利用できません。fresh development-only dev-r21をpreregisterしましたが、generationもVisionも開始しておらず、formal authorityではありません。

## Formal operator order

dev-r20は両private auditをpassしましたが両splitのtiny-speck population gateをfailし、numeric measurement前に閉鎖しました。
fresh development-only dev-r21は登録済みですが、まだgeneration前でありformal authorityではありません。以下のformal stageはすべてblockedです。dev-r20以前またはdev-r21のroot、key、controls、labels、decisions、measurements、threshold、public surfaces、postmortem outputをformal authorityへ流用できません。

1. authority files、implementation bindings、foundation/locked provenance、Vision reviews を Git で freeze し、
   working tree の対象 bytes、captured upstream HEAD、tracked SHA を preflight します。Ubuntu/Windows CI は
   static/unit/golden-vector preflight として両方 pass させます。formal stages は同一 machine・同一 runtime
   fingerprint で実行します。
2. 暗号学的に安全な fresh 32-byte key を専用の長寿命custodian process内で作り、formal generation/evaluation
   にだけ渡します。Vision processへ環境を継承させず、keyの永続化・ログ出力・公開は禁止です。
   `MICROTEXTURE_V2_R6_ARTIFACT_ROOT` は
   `tmp/map-production/microtexture-v2-r6-artifacts` に固定します。
3. calibration controls を一度だけ生成します。

   ```powershell
   python scripts/map-production/microtexture-v2-r6/generate_controls.py --split calibration
   ```

4. Root が calibration の全185 contact-sheet view-pages相当を確認し、生成された
   `controls/calibration/labels-calibration.json` を完成させます。
5. calibration を一度だけ実行します。marker、label sealing、secret regeneration、private audits、identity
   reveal、測定、候補選択の順は
   harness が fail-closed で固定します。

   ```powershell
   python scripts/map-production/microtexture-v2-r6/calibration_harness.py calibrate --labels tmp/map-production/microtexture-v2-r6-artifacts/controls/calibration/labels-calibration.json
   ```

6. calibration が pass し threshold が freeze された場合に限り、`v18` を一度だけ数値検証します。

   ```powershell
   python scripts/map-production/microtexture-v2-r6/calibration_harness.py locked-clean-reference
   ```

7. eligible external authority (`Cicero the 2nd` または `Descartes the 2nd`) が frozen calibration と
   locked-clean report を blind-independent mode で審査し、tracked receipt
   `world/map-production/qa/microtexture-v2-r6-threshold-authority.json` を作成します。
8. receipt を commit/push し、その receipt HEAD で Ubuntu/Windows CI を pass させます。
9. receipt が有効な場合に限り、fresh holdout controls を一度だけ生成します。生成 preflight は `v18` と
   provenance/review bytes を再検証しますが、`v18` を再測定しません。

   ```powershell
   python scripts/map-production/microtexture-v2-r6/generate_controls.py --split holdout
   ```

10. Root が holdout の全185 contact-sheet view-pages相当を確認し、`controls/holdout/labels-holdout.json` を完成させます。
11. frozen threshold を変更せず、holdout を一度だけ評価します。

   ```powershell
   python scripts/map-production/microtexture-v2-r6/calibration_harness.py holdout --labels tmp/map-production/microtexture-v2-r6-artifacts/controls/holdout/labels-holdout.json
   ```

各 one-shot stage はmarker write自体をpost-marker failure guardの`try`内で行い、durable markerを新しいidentity
reveal、target decode、numeric measurement、selection、endpoint evaluationより先に書きます。terminal
completionを書いた直後は必ず`require_completion=True`でauthorityをreloadします。catchableなpost-marker
exception、通常のendpoint failure、欠落・不整合completionはeditionを消費してr6を閉じます。regeneration、
relabel、再測定、rerun、threshold変更は禁止です。

## Production scope

r6 が検証するのは、別途 preregister された background reference から得る 256×192 float32 luminance
residual window です。semantic map pixels を直接・無maskで評価してはいけません。production への昇格には、
source/reference、protected-feature mask と erosion、filter support、tile halo/overlap/seam、color/alpha/
resampling、zoom/tile coverage、deterministic hashes、window/master aggregation、および untouched production
holdout を別途 preregister する必要があります。roads、rivers、coasts、labels、symbols、settlements などの
canonical geometry は eligible background から除外します。r6 synthetic holdout の pass だけでは production
derivation や Golden pixel を承認しません。
