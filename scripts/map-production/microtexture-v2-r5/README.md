# Microtexture v2-r5 authority

`preregistered-spec.json` が規範的 authority であり、この README は正式運用のための要約です。
r5 は fresh one-shot edition です。r3 と r4 は failed-and-closed の開発資料に限定され、
その control、key、label、threshold、foundation、locked source、holdout は r5 に再利用できません。
r4 の revealed corpus は、r5 の固定 morphology channel と reference constant を設計するためにのみ
使用されました。r5 の正式判断へ r4 の pixel または数値を混入させてはいけません。

## ImageGen authority

正式な fresh foundation corpus は、Vision-qualified 済みの ImageGen `v10`、`v11`、`v12`
だけです。各画像は 1536×1024 で、control/reference の基礎として使える範囲は中央
`[512,320,512,384]` crop に限定されます。その内部の detector/Vision 対象は
`[128,96,256,192]`、すなわち元画像上の `[640,416,256,192]` です。

foundation は secret HMAC で `v10`～`v12` に割り当てますが、各 record の reference はさらに full private
record identity（polarity と replicate を含む）を入力とする full-output HMAC-SHA-256 counter-mode PRF から
個別生成します。7×9 coefficient grid を滑らかに補間し、最大 1.75 px の warp と最大 0.75 L の tone shift
だけを加えます。各 split の140 reference SHA、140 control SHA、および5 viewそれぞれの140 panel SHAは
すべて一意でなければなりません。

この blind は、honest reviewer が割り当てられた review surface だけを見るための**運用上の blind**です。
technical / cryptographic blind や、同じ OS principal で悪意ある reviewer に対する secrecy は主張しません。
fresh key は専用の長寿命 custodian process だけが保持し、Vision process へ継承・公開しません。marker 前の
review surface は120 contact-sheet pagesとcode-only label formだけです。manifest schema
`microtexture-v2-r5-control-manifest/3` が公開する record 情報は opaque code と code別の
`control` / `reference` / `delta` HMAC commitment 3件だけで、個別control/referenceのpath、file、raw bytes、
raw SHAは公開しません。Vision process はlabel sealまでsource、authority code、raw extraction、hash/diff、
filesystem比較、identity regenerationを使用してはいけません。

次の候補は正式 authority から除外します。

- `v8`、`v9`: foundation 候補として Vision 不採用。reference、control、duplicate audit に使用禁止。
- `v13`: locked-clean predecessor として Root Vision 不採用。正式な locked-clean、reference、control に使用禁止。

`v14` は foundation corpus とは別の、Vision-qualified 済み locked-clean reference です。
その固定 path は
`world/map-production/style-assets/microtexture-v2-locked-clean-reference-imagegen-v14.png`
です。calibration と threshold selection から完全に除外し、threshold freeze 前の decode、測定、
数値参照を禁止します。freeze 後に一度だけ検証し、hard composite が accept しなければ r5 は閉じます。

`v10`～`v12` と `v14` はいずれも validation-only です。production art、Golden input、texture donor、
final pixel として使ったり、そこへ pixel を転送したりしてはいけません。正式 calibration/holdout 中に
production candidate、Golden candidate、または未登録画像を読むことも禁止です。

## Control population

calibration と holdout はそれぞれ 140 records、78 unique private clusters です。

| private role | records | clusters | 契約 |
|---|---:|---:|---|
| artifact | 120 | 60 | 5 morphology families × 12 nonzero conditions × dark/light pair |
| protocol-zero | 16 | 16 | control bytes が reference bytes と完全一致する exact-zero sentinel |
| duplicate-audit | 4 | 2 | clean 1組と obvious-artifact 1組、各2 distinct-reference semantic replicates |

artifact の5 family は、compact `control_families` schema の次の ID だけです。

- `artifact-fine-grain`
- `artifact-speck`
- `artifact-microblob`
- `artifact-short-dash`
- `artifact-parallel-bundle`

formal one-shot開始前のdevelopment Visionで、各familyの12 nonzero conditionsを低・中・高強度へ再配分し、
corpus coverageを固定します。calibrationとholdoutはsplit別のfrozen scheduleを使います。fine-grainは
fine-band / halftoneの各patternにつき最低強度の1 conditionだけをmetric window内のdeterministic nonzero
sparse support（`support_fraction=0.001`）とし、残り10 conditionsはfull supportです。これは正式labelの
事前指定ではなく、endpoint最低population/rate、blind、one-shot契約を変更しません。

各 artifact family は `private_role=artifact`、`polarities=[-1,1]`、12 clusters、24 records です。
全60 artifact cluster は nonzero requested delta を持ち、control は reference と異なります。
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

calibration と holdout は nonce、parameter range、HMAC identity、opaque code、control ID、delta hash が
分離されています。polarity と replicate は独立 cluster と数えません。正式 endpoint は eligible な
artifact records を cluster 内平均し、その後 unique cluster を等重みで集計します。

## Root Vision review

Root は各 split の全140 codesを、次の5 viewで漏れなく確認します。

- `full-200`: metric window 全体を 200% 表示
- `northwest-400`、`northeast-400`、`southwest-400`、`southeast-400`: metric window を隙間・重複なく4分割し 400% 表示

1 view は24 pages、合計は split あたり 120 pages です。全 view は同じ code 順序を持ち、nearest-neighbor
で拡大されます。Root は生成された exact path の label stub に、`disposition`、5種の visible flag、
severity、200%確認、全400% quadrant確認、notes を記入します。全120 pagesを確認する前に one-shot
evaluation を開始してはいけません。

## Hard detector

detector は中央 256×192 luminance-residual window に対し、固定 raw metrics から4 branch scoreを作ります。

1. `grain_score`
2. `spot_score`
3. `finite_line_score`
4. `parallel_bundle_score`

spot component floor、finite-line response floor、parallel-pair response floor はすべてabsolute `4.5 L`です。
coherent fine patternはspot/line branchではなく、directional coherenceを含むgrain branchが担当します。
split-specific morphology schedulesとこれらのabsolute floorは、fresh formal key、controls、labelsより前に
明示的なnon-formal development keysでfreezeしました。そのdevelopment corpusは正式判断に使わず、formal
labels、threshold、resultsは未確定であり予告しません。既存のblind、one-shot、endpoint、failed-r3/r4契約は
不変です。

各 branch は固定 reference constant による飽和正規化です。唯一の hard scalar は

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
cluster acceptance 0.95以上、warning cluster acceptance 0.75以上を満たす候補から、規範specの固定
objective order と全 endpoint minima により1値を選びます。candidate set は exact domain floor `0` を必ず
含み、minimum-epsilon、adjacent midpoint、upper outward sentinel を加えます。selection と全endpointに
eligibleなのは `private_role=artifact` だけです。holdout はその値を変更せず使用します。

## Formal operator order

順序を入れ替えたり、失敗後にやり直したりしてはいけません。

1. authority files、implementation bindings、foundation/locked provenance、Vision reviews を Git で freeze し、
   working tree の対象 bytes、captured upstream HEAD、tracked SHA を preflight します。Ubuntu/Windows CI は
   static/unit/golden-vector preflight として両方 pass させます。formal stages は同一 machine・同一 runtime
   fingerprint で実行します。
2. 暗号学的に安全な fresh 32-byte key を専用の長寿命custodian process内で作り、formal generation/evaluation
   にだけ渡します。Vision processへ環境を継承させず、keyの永続化・ログ出力・公開は禁止です。
   `MICROTEXTURE_V2_R5_ARTIFACT_ROOT` は
   `tmp/map-production/microtexture-v2-r5-artifacts` に固定します。
3. calibration controls を一度だけ生成します。

   ```powershell
   python scripts/map-production/microtexture-v2-r5/generate_controls.py --split calibration
   ```

4. Root が calibration の全120 pagesを確認し、生成された
   `controls/calibration/labels-calibration.json` を完成させます。
5. calibration を一度だけ実行します。marker、label sealing、secret regeneration、private audits、identity
   reveal、測定、候補選択の順は
   harness が fail-closed で固定します。

   ```powershell
   python scripts/map-production/microtexture-v2-r5/calibration_harness.py calibrate --labels tmp/map-production/microtexture-v2-r5-artifacts/controls/calibration/labels-calibration.json
   ```

6. calibration が pass し threshold が freeze された場合に限り、`v14` を一度だけ数値検証します。

   ```powershell
   python scripts/map-production/microtexture-v2-r5/calibration_harness.py locked-clean-reference
   ```

7. eligible external authority (`Cicero the 2nd` または `Descartes the 2nd`) が frozen calibration と
   locked-clean report を blind-independent mode で審査し、tracked receipt
   `world/map-production/qa/microtexture-v2-r5-threshold-authority.json` を作成します。
8. receipt を commit/push し、その receipt HEAD で Ubuntu/Windows CI を pass させます。
9. receipt が有効な場合に限り、fresh holdout controls を一度だけ生成します。生成 preflight は `v14` と
   provenance/review bytes を再検証しますが、`v14` を再測定しません。

   ```powershell
   python scripts/map-production/microtexture-v2-r5/generate_controls.py --split holdout
   ```

10. Root が holdout の全120 pagesを確認し、`controls/holdout/labels-holdout.json` を完成させます。
11. frozen threshold を変更せず、holdout を一度だけ評価します。

   ```powershell
   python scripts/map-production/microtexture-v2-r5/calibration_harness.py holdout --labels tmp/map-production/microtexture-v2-r5-artifacts/controls/holdout/labels-holdout.json
   ```

各 one-shot stage はmarker write自体をpost-marker failure guardの`try`内で行い、durable markerを新しいidentity
reveal、target decode、numeric measurement、selection、endpoint evaluationより先に書きます。terminal
completionを書いた直後は必ず`require_completion=True`でauthorityをreloadします。catchableなpost-marker
exception、通常のendpoint failure、欠落・不整合completionはeditionを消費してr5を閉じます。regeneration、
relabel、再測定、rerun、threshold変更は禁止です。

## Production scope

r5 が検証するのは、別途 preregister された background reference から得る 256×192 float32 luminance
residual window です。semantic map pixels を直接・無maskで評価してはいけません。production への昇格には、
source/reference、protected-feature mask と erosion、filter support、tile halo/overlap/seam、color/alpha/
resampling、zoom/tile coverage、deterministic hashes、window/master aggregation、および untouched production
holdout を別途 preregister する必要があります。roads、rivers、coasts、labels、symbols、settlements などの
canonical geometry は eligible background から除外します。r5 synthetic holdout の pass だけでは production
derivation や Golden pixel を承認しません。
