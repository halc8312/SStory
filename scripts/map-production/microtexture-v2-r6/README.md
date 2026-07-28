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

fresh `dev-r8` は、追跡済み`development_probe.py`、revision-3 public/HMAC/parameter nonce domain、新しいroot、
新しいkey、新規controls/identities/labels/measurementsを使う独立した一回限りのdevelopment probeです。r7の
key、controls、labels、pixels、identities、measurements、diagnostic threshold、parameter nonce、artifact rootを
再利用せず、subsetting、合格例だけの採用、top-up、key resampling、relabel、rerunを禁止します。
development keyはtracked runnerが`secrets.token_bytes(32)`で生成し、生成・一回限りのanalysis・閉鎖後監査を
結ぶため`tmp/map-production/microtexture-v2-r6-dev-r8/private/development-key.bin`だけに保持します。このpathは
Git-ignoredで、値のlog・Git追跡・Vision processでの読取り・formalまたは後続editionへの再利用を禁止します。
key生成前に`.gitignore`がcaptured HEADとbyte-identicalであること、exact key pathがHEAD/indexに存在せず、
root `.gitignore`のexact `/tmp*/` patternで実際にignoreされることをrunnerが検証します。閉鎖rootはforensic
reproducibilityのため不変のまま保持します。formal keyの非永続化契約は変更しません。

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
継承・公開しません。dev-r8 keyは前述のGit-ignored private rootとtracked custodian runnerだけが扱います。marker 前の
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

`dev-r8` の一回限りの analysis には、formal spec の endpoint最低populationを一切変更せず、さらに厳しい
development-only safety floorを上乗せします。label bytesを両splitともsealし、private identityをrevealして
semantic auditを終えた後、最初のmetric callより前にcondition-cluster truthで次を検査します。

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

一つでも不足すれば`measurement_started=false`で`dev-r8`を消費・閉鎖し、測定、threshold探索、ラベル修正、
top-up、別keyでの再生成へ進みません。このmargin gateはdevelopment scheduleのfeasibility確認専用であり、
formal common endpoint minima、rate、candidate selection、one-shot契約を変更しません。

## Root Vision review

Root は各 split の全220 codesを、次の5 viewで漏れなく確認します。

- `full-200`: metric window 全体を 200% 表示
- `northwest-400`、`northeast-400`、`southwest-400`、`southeast-400`: metric window を隙間・重複なく4分割し 400% 表示

1 view は37 pages、合計は split あたり 185 contact-sheet view-pagesです。development helperは同じpage indexの
5 viewを横並びにした37 review boardsも作ります。全 view は同じ code 順序を持ち、nearest-neighbor
で拡大されます。各512×384 panelの直前には30pxのcode headerがあり、codeをpanel下へ置くこと、headerとpanelを
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
明示的なnon-formal development keysでfreezeします。closed `dev-r6`/`dev-r7` corporaは正式判断に使わず、fresh
`dev-r8` のrevision-3全scheduleをsubsettingなしで一回だけ確認します。formal labels、threshold、resultsは未確定であり
予告しません。既存のblind、one-shot、endpoint、failed-r3/r4/r5およびclosed development境界は不変です。

各 branch は固定half-scale referenceに対する
`unit_soft(x,ref)=0 (x<=0), otherwise (2/pi)*atan(x/ref)` で正規化します。有限の正の証拠に対して厳密単調で
`0..1`未満に有界、`x=ref`はexact `0.5`です。観測値を分母に使わず、warning/rejectの強度差を有限値で
同一ceilingへ潰しません。grain coherenceは0..1のraw係数をRMS soft-unit scoreへ乗じます。唯一の hard scalar は

r7の閉鎖済みaggregate診断から変更するhalf-scaleは3件だけです。`grain_rms_l: 0.7 -> 0.875`、
`tiny_mass_l: 20 -> 15`、`finite_line_top4_mean_l: 4.5 -> 2.25` とし、他6件、raw metrics、branch構成、
単一threshold、全endpoint count/rateは不変です。単一reference変更は全候補不合格、2-reference変更で唯一通った組へ、
判定境界を広げるgrain 1件を加えたrevisionです。r7のthreshold/measurement自体はformalへ使用しません。

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

## Dev-r8 operator order

このsectionはformal r6ではなく、formal前の一回限りdevelopment probeです。dev-r8入力authorityをcommit/pushし、
branch upstream HEADと一致しUbuntu/Windows CIが成功するまで実行しません。formal root/environmentと
`tmp/map-production/microtexture-v2-r6-dev-r8`が存在しないことを確認した後、次を一度だけ実行します。

```powershell
python scripts/map-production/microtexture-v2-r6/development_probe.py generate
```

Rootと独立Visionは両splitの全37 review boards（各boardは同pageの5 view）を別々に確認し、各220 decisionsを
`decisions-root.dev.txt`と`decisions-independent.dev.txt`へ記録します。Rootが画像へ戻って差分をreconcileしたexact
Root decisionsを`vision-decisions.dev.txt`として固定します。preflightは3ファイルの全code/printed-code bindingを
検証し、Root/独立decisionが全220件でexact logical agreementになっていなければ停止します。labelやkeyは書きません。

```powershell
python scripts/map-production/microtexture-v2-r6/development_probe.py preflight
```

全件確認とpreflight合格後だけ、次を一度だけ実行します。これはlabelsをexclusive sealし、private auditとpopulation
gate後にだけmetricを呼び、calibrationで1 thresholdを選び、その値をholdoutへ変更せず適用します。

```powershell
python scripts/map-production/microtexture-v2-r6/development_probe.py analyze
```

失敗・例外後のgenerate/analyze再実行、decision変更、別key、top-upは禁止です。成功時もdev-r8 thresholdは
formal authorityではなく、success auditをGitへ固定してdev-r8を閉じた後、formal r6 authorityを別commitで
最終freezeします。

## Formal operator order

順序を入れ替えたり、失敗後にやり直したりしてはいけません。

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
