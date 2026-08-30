# Microtexture v2-r5 preregistration summary

規範的 authority は `preregistered-spec.json` です。この文書は
`implementation-bindings.json` に hash-bind される readable summary であり、矛盾時は JSON が優先します。

## Edition boundary and image inputs

r5 は r3/r4 の retune ではなく fresh one-shot edition です。r3 と r4 は failed-and-closed、development-only
であり、過去の controls、keys、labels、thresholds、foundations、locked sources、holdouts は再利用しません。
r4 の revealed failed corpus を参照したのは、r5 key/control/label/measurement の生成前に morphology channels、
fixed filters、score reference constants を定義した開発段階だけです。

fresh foundation corpus は、非数値の Vision review を通過し SHA-bind された ImageGen `v10`、`v11`、`v12`
のみです。source は 1536×1024、許可される foundation crop は `[512,320,512,384]`、その中の metric window は
`[128,96,256,192]` です。foundation は secret HMAC で割り当てますが、各recordはfull private record identity
（polarityとreplicateを含む）を入力とするfull-output HMAC-SHA-256 counter-mode PRFで固有のprivate
referenceを生成します。7×9 coefficient gridを滑らかに補間し、最大1.75 pxのwarpと最大0.75 Lのtone shift
だけを加えます。`v8` と `v9` は foundation 候補として却下され、
formal reference/control/audit への流入を禁止します。

locked-clean reference は別系統の ImageGen `v14` です。`v13` はその生成チェーンで Root Vision が却下した
predecessor であり authority ではありません。`v14` は calibration population と threshold selection に
含めず、threshold freeze 前の decode・測定・数値参照を禁止し、freeze 後に一度だけ hard composite で
accept を確認します。foundation と locked-clean の全 pixel は validation-only であり、production art、
Golden input、texture donor、final pixels への利用・転送を禁止します。

## Blinded control design

各 split は 140 records、78 unique condition clusters です。規範的 `control_families` は compact schema で、
artifact family entry は `id`、`private_role`、`polarities`、`expected_clusters_per_split`、
`expected_records_per_split` だけを持ちます。

- `artifact-fine-grain`: 12 clusters、24 paired records
- `artifact-speck`: 12 clusters、24 paired records
- `artifact-microblob`: 12 clusters、24 paired records
- `artifact-short-dash`: 12 clusters、24 paired records
- `artifact-parallel-bundle`: 12 clusters、24 paired records

正式実行前のdevelopment Visionで、各familyの12 nonzero conditionsを低・中・高強度へ再配分し、corpus
coverageとしてfreezeします。calibrationとholdoutはsplit別のfrozen schedulesを持ちます。fine-grainは
fine-band / halftoneの各patternにつき最低強度の1 conditionだけをmetric-window内のdeterministic nonzero
sparse support（`support_fraction=0.001`）とし、他の10 conditionsはfull supportです。このcoverage設計は
formal labelの期待値や事前指定ではなく、endpoint最低population/rate、blind、one-shot契約を変えません。

この5 familyで60 artifact clusters、120 artifact recordsです。各 cluster は dark/light
`polarities=[-1,1]` を持ち、両recordは異なるprivate referenceを使います。同じ位置、角度、unsigned geometry
からrequested deltaをexact sign inverseとして作り、decoded `control-reference` int16 residualもexact inverse、
対応metricsもexact equalityでなければなりません。60 clusters はすべて nonzero injection で、各record内の
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

以上で `60 + 16 + 2 = 78` clusters、`120 + 16 + 4 = 140` records です。protocol-zero と
duplicate-audit は foundation/label protocol の検査専用で、threshold candidates、objective、artifact
endpoints から除外します。

private cluster identity は split、nonce、role、family、variant、parameters、duplicate group、foundation を
HMAC-SHA-256 に bind し、polarity と replicate を除外します。公開 manifest、record、contact sheet、label
には family/role/polarity/parameter/cluster/foundation/duplicate identity を出しません。validated labels と
durable one-shot marker の後だけ reveal できます。calibration と holdout は nonce、parameters、identity、
opaque code、control ID、requested-delta hash が互いに独立です。

公開manifest schemaは`microtexture-v2-r5-control-manifest/3`です。各recordが持つのはopaque codeと、secret
key・code・lane (`control|reference|delta`)・raw SHAをdomain-separateしたHMAC-SHA-256 commitment 3件だけ
です。420 commitmentsは全件一意で、個別control/referenceのpath、file、raw bytes、raw SHAをmarker前に
作成・公開しません。各splitの140 reference SHA、140 control SHA、および5 viewそれぞれの140 panel SHAも
全件一意でなければなりません。raw SHAはmarkerとlabel seal後のprivate revealだけへ出します。

ここでのblindはhonest reviewerに対する運用上のblindであり、technical / cryptographic blindでも、同じOS
principalで悪意あるreviewerに対するsecrecyでもありません。fresh keyは専用の長寿命custodian processだけが
保持し、Vision processへ継承・公開しません。marker前のreview surfaceは120 contact-sheet pagesとcode-only
label formだけです。Vision processはlabel sealまでsource、authority code、個別control/reference、raw
extraction、filesystem、hash/diff、identity regenerationを使用してはいけません。

## Vision observation contract

decision-critical unit は 512×384 control の中央 `[128,96,256,192]` crop です。Root は各 split について、
この全体を示す `full-200` と、隙間・重複なく分割する NW/NE/SW/SE の4つの 400% view を確認します。
各 view は24 pages、合計120 pagesです。5 viewの ID、順序、integer scale/crop、nearest-neighbor resize、
page ごとの code 順序が一致しない場合は fail-closed です。

Root label schema は `clean|warning|reject`、grain/tiny-speck/microblob/short-line/parallel-bundle の visible
flags、severity 0..3、200% review、全400% quadrant review、notes を要求します。label file は generator が
出した exact split path の regular non-link file でなければなりません。one-shot marker の直後、新規 decode/
reveal/measurement より前に exact sealed path へ exclusive copy し、以後の report と authority reload は
その immutable bytes を使います。

marker 前に検証できるのはschema、authority、code coverage、review completenessと各record内のsemantic
整合だけです。raw hash equalityやprivate sentinel membershipを使ったlabel修正は禁止します。semantic
sentinel/replicate auditの順序は marker → label seal → 全control/referenceのin-memory regeneration → exact
contact-sheet byte binding → private audit → measurement
です。16 protocol-zeroとclean duplicateはclean必須、obvious-artifact duplicateは同一semantic label、
severity 2/3 reject、`short_line_visible=true` 必須です。違反はpost-marker failureとしてeditionを閉じます。

## Four branches and one hard scalar

metric window は 192×256 float32 luminance residual です。固定 raw metrics を artifact-derived denominator なしで
正規化し、次の4 branch scoreを得ます。

- `grain_score`: occupancy/RMS と directional coherence/RMS の固定組合せ
- `spot_score`: tiny component mass と multiscale blob strength の最大
- `finite_line_score`: finite-line peak と top-4 mean の最大
- `parallel_bundle_score`: raw deltaへのcore-only responseから得る、同一angle/length filter内の
  weaker-pair peak とmatched-pair countの最小。matched pairsが2未満なら両raw evidenceをcanonical zeroにする

spot component floor、finite-line response floor、parallel-pair response floorはいずれもabsolute `4.5 L`です。
coherent fine patternはdirectional coherenceを含むgrain branchが担当し、spot/line branchへ役割を移しません。
split-specific schedulesとこれらのfloorは、fresh formal key、controls、labelsが存在する前に、明示的な
non-formal development keysでfreezeしました。pre-freeze corpusはdevelopment-onlyで、formal labels、threshold、
resultsは未確定であり予告しません。blind、one-shot、endpoint、failed-r3/r4境界は変更しません。

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
合成しません。clean-cluster acceptance 0.95以上、warning-cluster acceptance 0.75以上のみ admissible とし、
次の順で決定論的に最適化します。

1. grain、tiny-speck、microblob、short-line、parallel-bundle reject-cluster detection の最小値
2. combined spot reject-cluster detection
3. overall reject-cluster detection
4. severity-3 cluster detection
5. clean-cluster acceptance
6. warning-cluster acceptance
7. より厳しい lower threshold

全 endpoint は preregistered minimum unique-cluster count と calibration/holdout rate を満たさなければなりません。
threshold candidates、selection、全endpointのeligible roleはartifactだけで、protocol-zeroとduplicate-auditは
完全に除外します。集計は eligible artifact records の cluster 内平均後、unique clusters を等重みにします。missing/empty
population、admissible candidate 不在、または endpoint failure は freeze を禁止して edition を閉じます。
holdout は frozen single threshold を変更せず評価します。

## Formal stage order

1. authority、bindings、ImageGen provenance、Vision reviews を tracked SHA/captured upstream HEAD に freeze し、
   working bytes と HEAD を preflightする。Ubuntu/Windows CI は formal run を生成せず、static/unit/golden-vector
   preflight のみを担当する。
2. 同一 machine/runtime fingerprint を全 formal stages に固定し、安全な fresh 32-byte blind key を専用の
   長寿命custodian processだけに置く。Vision processへkeyまたは環境を継承しない。
3. calibration controls を一度だけ生成する。
4. Root が calibration の全120 pagesを確認し、exact label artifact を完成する。
5. calibration を一度だけ実行する。marker → label seal → secret regeneration → private audits → identity reveal → measurement → candidate selection →
   endpoint evaluation → report → completion の順を変えない。
6. calibration pass と threshold freeze 後に限り、locked-clean `v14` を一度だけ評価する。
7. allow-list の external authority が frozen calibration と locked-clean report を審査し、hash-bound tracked
   receipt を書く。
8. receipt を commit/push し、その HEAD で両CIを通す。
9. receipt と `v14` provenance/reviews を preflightして fresh holdout controls を一度だけ生成する。
   この preflight は stored authority の再検証であり `v14` の再測定ではない。
10. Root が holdout の全120 pagesを確認し、exact label artifact を完成する。
11. holdout marker 後、frozen threshold を変えず一度だけ評価し、terminal report を actual files、sealed labels、
    marker、threshold、receipt、HEAD/runtime、secret-derived identity に再bindしてから completion を書く。

各stage markerのwrite自体をpost-marker failure guardの`try`内で行い、current-stage private identity reveal、
target decode、新規numeric measurement、selection、endpoint evaluationより前にdurableに書きます。terminal
completionを書いた直後は必ず`require_completion=True`でauthorityをreloadします。prior authority の stored decisions を marker 前に再計算して
整合確認することはできますが、source image の再測定ではありません。post-marker exception は failure report
を試み、通常 endpoint failure は `passed:false` completion を書きます。completion 欠落または failure coexistence
も fail-closed です。いずれの失敗も edition を消費し、regeneration、relabel、rerun、threshold change を禁止します。

## Production boundary

r5 detector は、別途 preregister された background reference から得た完全な 256×192 eligible-background
residual window のみを対象にします。roads、rivers、coasts、labels、symbols、settlements、その他 canonical
geometry を mask と filter-support erosion で除外し、partial window や denominator renormalization を禁止します。

r5 synthetic holdout pass は production derivation を直接承認しません。production source/reference、mask、
filter support、tile overlap/halo/seam、boundary、color/alpha/quantization/resampling、zoom/tile coverage、deterministic
outputs、window-to-master aggregation、untouched production holdout を候補測定前に別途 preregister しなければ
なりません。promotion には、実装と frozen threshold を変えず synthetic holdout と production holdout の両方を
通過することが必要です。
