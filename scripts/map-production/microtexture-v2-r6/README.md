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

fresh successor `dev-r13` のexact rootは`tmp/map-production/microtexture-v2-r6-dev-r13`、key pathはその
`private/development-key.bin`、schedule revisionは`dev-r13-warning-acceptance-anchor-schedule-v1`です。public noncesは
`r6-calibration-v8` / `r6-holdout-v8`、cluster/render/code domainsはそれぞれ
`microtexture-v2-r6/private-condition-cluster/v8/`、`microtexture-v2-r6/render-seed/v8/`、
`microtexture-v2-r6/opaque-code/v8/`、private-reference-transform domainは`private-reference-transform-v8/`、
public commitment domainは
`microtexture-v2-r6/public-payload-commitment/v9/{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}`、key commitmentは
`microtexture-v2-r6/key-commitment/v7`です。foundation lanesは`foundation-offset-v7` / `foundation-assignment-v7`、
delta laneは`delta-v7`、private-control-id domainは`microtexture-v2-r6/private-control-id/v7/`です。parameter nonce
rangesはcalibrationがartifact `573000..573419`、protocol-zero `551000..551015`、duplicate-audit
`591000..591002`、holdoutがartifact `583000..583419`、protocol-zero `561000..561015`、duplicate-audit
`601000..601002`です。metric、single-threshold rule、population floors、endpoint counts/ratesは変更しません。規範JSON、
bindings、code、tests、runnerをauthority commitへfreezeしてpushし、同じcommitのUbuntu/Windows CIが両方成功するまで
dev-r13をgenerateしてはいけません。formal keyの非永続化契約も変更しません。

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
継承・公開しません。closed dev-r8/dev-r9/dev-r10/dev-r11/dev-r12 keyは各Git-ignored private rootにだけ保持して再利用せず、
planned dev-r13 keyは別のfresh Git-ignored rootとtracked custodian runnerだけが扱います。marker 前の
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

formal one-shot開始前のdevelopment Visionで、各familyの20 nonzero conditionsを4つのdesign tierへ
`5 / 4 / 7 / 4` conditionsずつ配分し、corpus coverageを固定します。calibrationとholdoutはspecに記録された
split別のfrozen scheduleとpublic nonceを使います。tierはperceptual marginを広く試すための生成設計であり、
`clean`、`warning`、`reject`、severityその他のVision truthを予告・割当するものではありません。
全scheduleを一体として生成・blind reviewし、結果を見てsubsetting、top-up、key resamplingしてはいけません。

dev-r9で固定したspeck scheduleはpopulation floorを両splitで通過しました。dev-r10では
`artifact-fine-grain`のfull-support reject-tier 3条件だけを事前に変更し、calibrationのperiod `14.0`を`11.6`、
holdoutの`12.6`を`11.4`、`14.6`を`11.8`へ置き換えました。これにより全11 reject-tier grain conditionsは、
変更しないcoherence metric support `2..13`のguard-bandedな内側`3..12`へ入ります。dev-r10はgeneration中断で
Vision/analysisへ到達せず、dev-r11はprivate sentinel auditでpopulation aggregationとmetricより前に閉鎖したため、
いずれのcorpusからもscheduleを評価・調整しません。dev-r12は両private auditとwarning以外の全population endpointを
passしましたが、warning population不足で測定前に閉鎖しました。dev-r13はtier数`5/4/7/4`を維持し、
`artifact-speck`、`artifact-microblob`、`artifact-short-dash`、`artifact-parallel-bundle`の既存warning-candidateを
splitごとに各4件、計16件だけ、family invariantを保った弱いが直接知覚可能なmorphology anchorへ実パラメータ変更します。
fine-grain warning、全clean-candidate、全clear/dominant-reject morphologyは変更しません。splitごとのwarning anchor 16件に対する
development floor 13の構造上のmiss budgetは3ですが、tierはVision truthやwarning labelの保証ではありません。
metric、score reference、single-threshold rule、全endpoint count/rateは変更せず、fresh identityの全20 conditionsと各split
220 recordsを一体生成・blind reviewし、全private auditとpopulation gateをall-or-nothingで適用します。

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

closed `dev-r8` / `dev-r9` / `dev-r12` とplanned `dev-r13` の一回限りのanalysisには、formal specのendpoint最低populationを
一切変更せず、さらに厳しいdevelopment-only safety floorを上乗せします。dev-r10はanalysis前、dev-r11はprivate
sentinel auditでpopulation aggregation前に閉鎖したため、このgateの結果を持ちません。label bytesを両splitともsealし、private identityを
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
`measurement_started=false`のまま閉鎖しました。calibration warningはformal minimum 10を満たしましたが、holdout
warningはformal minimum 10も満たしませんでした。他の全endpointはformal minimumとdevelopment floorをpassしました。
planned dev-r13でもprivate auditに失敗するかpopulationが一つでも不足すれば`measurement_started=false`で消費・閉鎖し、
測定、threshold探索、ラベル修正、top-up、別keyでの再生成へ進みません。population通過後も全endpointを同時に
満たせなければthresholdを作らず閉鎖します。このmargin gateとgrain support scheduleはdevelopment専用であり、
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
で拡大されます。dev-r13の判定ではnative 512×384 full-200 cropを無補正・contrast強調なしで先に確認し、400%は
同位置の再同定だけに使います。各512×384 panelの直前には30pxのcode headerがあり、codeをpanel下へ置くこと、headerとpanelを
重ねることは禁止します。Root は生成された exact path の label stub に、`disposition`、5種の visible flag、
severity、200%確認、全400% quadrant確認、notes を記入します。全185 view-pages相当を確認する前に one-shot
evaluation を開始してはいけません。

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
明示的なnon-formal development keysでfreezeします。closed `dev-r6`～`dev-r12` corporaは正式判断に使いません。
dev-r10はgeneration中断、dev-r11はprivate sentinel audit失敗によりmetric evidenceを持たず、dev-r12もpopulation
gate失敗によりmetric evidenceを持ちません。planned `dev-r13` の
`dev-r13-warning-acceptance-anchor-schedule-v1`全scheduleをsubsettingなしで一回だけ確認します。morphology変更は
4 sparse familiesの既存warning-candidate計16件/splitだけで、fine-grain warningと全clean/reject morphologyは不変です。
formal labels、threshold、resultsは
未確定であり予告しません。既存のmetric、half-scale、absolute floor、endpoint minima/rate、blind、one-shot、
failed-r3/r4/r5およびclosed development境界は不変です。

各 branch は固定half-scale referenceに対する
`unit_soft(x,ref)=0 (x<=0), otherwise (2/pi)*atan(x/ref)` で正規化します。有限の正の証拠に対して厳密単調で
`0..1`未満に有界、`x=ref`はexact `0.5`です。観測値を分母に使わず、warning/rejectの強度差を有限値で
同一ceilingへ潰しません。grain coherenceは0..1のraw係数をRMS soft-unit scoreへ乗じます。唯一の hard scalar は

r7の閉鎖済みaggregate診断から変更するhalf-scaleは3件だけです。`grain_rms_l: 0.7 -> 0.875`、
`tiny_mass_l: 20 -> 15`、`finite_line_top4_mean_l: 4.5 -> 2.25` とし、他6件、raw metrics、branch構成、
単一threshold、全endpoint count/rateは不変です。単一reference変更は全候補不合格、2-reference変更で唯一通った組へ、
判定境界を広げるgrain 1件を加えたrevisionです。dev-r8はpopulation gateでmeasurement前に閉鎖し、dev-r9は
同じmetricを一度だけ実行したもののthresholdを選べず閉鎖しました。dev-r10はmetricを呼ぶ前のgeneration中断で
閉鎖しました。dev-r11もprivate sentinel audit、dev-r12もpopulation auditでmetric前に閉鎖しました。planned dev-r13は
metricを変更せず継承し、closed editionのthreshold、diagnostic、measurement、generation/review outputをformalへ使用しません。

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

## Development closure and planned dev-r13 operator order

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

dev-r13はformal r6ではなく、formal前の新しい一回限りdevelopment probeとしてのみ計画されています。このREADMEの
記述だけでは実行権限になりません。`dev-r13-warning-acceptance-anchor-schedule-v1`、新しいroot/key、全nonce/domain、
parameter schedule、bindings、code、tests、tracked custodian runnerを規範JSONへfreezeし、authority commitをpushして
branch upstream HEADと一致させ、Ubuntu/Windows CIを両方passさせるまでgenerateしてはいけません。
generate時に記録したmachine/exact runtime fingerprintはpreflight/analyze完了まで完全一致を必須とし、途中で変化した
場合は継続・再生成せずfail-closedに停止します。

freeze後の順序は、fresh rootの不存在確認 → fresh 32-byte key作成 → public byteより前のexclusive
`generation-start.dev.json` → 両split各220 recordsの一回限り生成 → generation summary → summaryをbindするseal →
sealをbindするexclusive completionです。start後のcatchableな例外はexclusive failureへ記録し、failureとcompletionの
共存、summary / seal / completionの欠落、hard killを含む中断はdev-r13を消費・閉鎖します。その後に限り、
Root/独立Visionによる全37
review boardsと各220 decisionsの独立確認 → exact Root decision reconciliation → code/printed-code binding、生成時SHA、
全件logical agreementのpreflight → exclusive label seal → key read後の全185 contact sheets / 37 review boardsの
secret-derived exact byte・code-order再生成照合 → private audit → all-or-nothing population gateです。全floorがpassした場合に限り最初のmetric callへ進み、calibrationで1 thresholdを
選び、その値をholdoutへ変更せず適用します。一つでも失敗すればdev-r13を消費・閉鎖し、rerun、resume、relabel、
別key、subsetting、top-upをしません。成功時もdev-r13 thresholdはformal authorityではなく、success auditをGitへ
固定してdev-r13を閉じた後にのみ、formal r6 authorityを別commitで最終freezeできます。

## Formal operator order

dev-r13が上記の全population gate、metric、calibration、holdout endpointsを一回でpassし、hash-bound success auditを
commit/pushして両CIを通すまで、以下のformal stageを一つも開始してはいけません。その成功はformal authorityではなく、
formal authorityはその後の別commitでfreezeします。順序を入れ替えたり、失敗後にやり直したりしてはいけません。

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
