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

fresh `dev-r10` は次の一回限りdevelopment probeです。exact rootは
`tmp/map-production/microtexture-v2-r6-dev-r10`、public noncesは`r6-calibration-v5` / `r6-holdout-v5`、HMAC
cluster/render/code domainsはv5、public commitment domainはv6です。parameter nonce basesはcalibrationがartifact
`273000`、protocol-zero `251000`、duplicate-audit `291000..291002`、holdoutがartifact `283000`、protocol-zero
`261000`、duplicate-audit `301000..301002`です。schedule revisionは
`dev-r10-grain-coherence-support-schedule-v1`です。規範JSON、bindings、code、tests、tracked runnerを別commitへ
freezeし、push後にUbuntu/Windows CIを両方通すまでgenerateしてはいけません。development keyはfresh Git-ignored
private rootだけへ保持し、値のlog・Git追跡・Vision processでの読取り・formal/後続editionへの再利用を禁止します。

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

正式実行前のdevelopment Visionで、各familyの20 nonzero conditionsを4つのdesign tierへ
`5 / 4 / 7 / 4` conditionsずつ割り当て、corpus coverageとしてfreezeします。calibrationとholdoutはspecに
記録されたsplit別のfrozen scheduleとpublic nonceを使います。このtierは幅広いperceptual marginを作るための
design-only区分であり、`clean`、`warning`、`reject`、severity、visible flagのtruthを指定・予告しません。
全scheduleを一体としてblind reviewし、結果を見たsubsetting、top-up、key resamplingを禁止します。

dev-r9のspeck scheduleは両splitでtiny-speck population floorを通過したため、dev-r10でも同じmorphology coverageを
fresh controlsとして生成します。dev-r10が変更するmorphologyは`artifact-fine-grain`のfull-support reject-tier
3条件だけです。calibrationのperiod `14.0`を`11.6`、holdoutの`12.6`を`11.4`、`14.6`を`11.8`へ置換し、
全11 reject-tier grain conditionsを、変更しないcoherence support `2..13`のguard-bandedな内側`3..12`へ固定します。
metric、score references、単一threshold、tier数`5/4/7/4`、全endpoint count/rate、他4 familyは変更しません。
このscheduleはgeneration coverageであってVision truth、endpoint membership、label expectation、既存corpusへのtop-up
ではありません。全20 conditionsと両split各220 recordsをfreshに一体生成・blind reviewします。

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

closed `dev-r8` / `dev-r9` とplanned `dev-r10` のanalysisには、formal common endpoint minimaを変更しないdevelopment-only
safety gateを加えます。両splitのlabel bytesをsealし、private revealとsemantic auditを終えた後、最初のmetric call
より前に集約済みcondition-cluster truthで、splitごとにclean 19、warning 13、reject 38、severity 3が6、
grain-visible reject 10、tiny-speck-visible reject 6、microblob-visible reject 6、spot-visible reject 10、
short-line-visible reject 10、parallel-bundle-visible reject 8以上を要求します。

dev-r8ではtiny-speck-visible rejectだけがcalibration 3、holdout 1で不足し、他の全endpointはpassしました。
gateはall-or-nothingなので`measurement_started=false`のまま消費・閉鎖し、metric、threshold探索、holdout endpoint
evaluationへ進みませんでした。dev-r9は全floorを通過しましたが、warning acceptanceとseverity-3 detectionを
同時に満たすcalibration thresholdがなく、測定後に閉鎖しました。planned dev-r10でも一つでも不足すれば消費・閉鎖し、
測定、threshold探索、ラベル変更、top-up、別keyでの再生成をしません。population通過後も全endpointを同時に
満たせなければthresholdを作りません。このsafety marginとgrain support scheduleはdevelopment専用でVision truthではなく、
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
各 view は37 pages、合計185 contact-sheet view-pagesです。development helperは同じpage indexの5 viewを
横並びにした37 review boardsも作ります。5 viewの ID、順序、integer scale/crop、nearest-neighbor resize、
page ごとの code 順序が一致しない場合は fail-closed です。各512×384 panelの直前に30px code headerを置き、
codeをpanel下へ置くことやheader/panel overlapを禁止します。

Root label schema は `clean|warning|reject`、grain/tiny-speck/microblob/short-line/parallel-bundle の visible
flags、severity 0..3、200% review、全400% quadrant review、notes を要求します。label file は generator が
出した exact split path の regular non-link file でなければなりません。one-shot marker の直後、新規 decode/
reveal/measurement より前に exact sealed path へ exclusive copy し、以後の report と authority reload は
その immutable bytes を使います。

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
同じmetricを一度だけ実行したもののthresholdを選べず閉鎖しました。planned dev-r10はmetricを変更せずblindに検証し、
dev-r7/dev-r9のthreshold、diagnostic、measurementをformal判断へ移しません。

- `grain_score`: `max(min(unit occupancy, unit RMS), coherence * unit RMS)`
- `spot_score`: tiny component mass、tiny component count、multiscale blob strength のunit score最大
- `finite_line_score`: finite-line peak と top-4 mean の最大
- `parallel_bundle_score`: raw deltaへのcore-only responseから得る、同一angle/length filter内の
  weaker-pair peak とmatched-pair countの最小。matched pairsが2未満なら両raw evidenceをcanonical zeroにする

spot component floor、finite-line response floor、parallel-pair response floorはいずれもabsolute `4.5 L`です。
coherent fine patternはdirectional coherenceを含むgrain branchが担当し、spot/line branchへ役割を移しません。
split-specific schedulesとこれらのfloorは、fresh formal key、controls、labelsが存在する前に、明示的な
non-formal development keysでfreezeします。closed `dev-r6`～`dev-r9` corporaはdevelopment-onlyのfailure
evidenceに限定し、planned `dev-r10` の`dev-r10-grain-coherence-support-schedule-v1`全scheduleだけをsubsettingなしで
一回確認します。dev-r10で変更するmorphologyは前述のgrain period 3件だけです。formal labels、threshold、
resultsは未確定であり予告しません。既存のmetric、half-scale、absolute floor、endpoint minima/rate、blind、
one-shot、failed-r3/r4/r5およびclosed development境界は変更しません。

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

## Formal stage order

planned dev-r10が全population gate、metric、calibration、holdout endpointsを一回でpassし、hash-bound success auditを
別commitでpushしてUbuntu/Windows CIを両方通すまで、formal stageを一つも開始してはいけません。dev-r10 successは
formal authorityではなく、formal authorityはその後の別commitでfreezeします。

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
