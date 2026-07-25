---
type: "overview"
category: "maps"
title: "Microtexture v2-r4 候補非依存較正契約"
version: "0.5.0"
created: "2026-07-25"
last_updated: "2026-07-25"
author: "Codex"
tags: ["maps", "quality-assurance", "microtexture", "vision-qa", "calibration"]
status: "review"
document_kind: "navigation"
summary: "r3の一回限り不合格を固定し、freshな匿名control、Root Vision、locked clean reference、未使用holdoutでr4 residual-window detectorを凍結する契約です。"
---

# Microtexture v2-r4 候補非依存較正契約

## 現在地

r3は2026-07-25に一回だけcalibrationされ、不合格のまま閉鎖しました。追跡証拠は
`world/map-production/qa/microtexture-v2-r3-calibration-failure.json`です。

| r3結果 | 実績 |
| --- | ---: |
| clean acceptance | 22 / 22 = 100% |
| warning acceptance | 15 / 19 = 78.9% |
| reject detection | 12 / 25 = 48.0% |
| severity-3 detection | 4 / 4 = 100% |
| speck / short / parallel hard detector | 0件検出 |

原因は、Rootが判定した中央256×192とmetricが測った512×384全体の不一致、tiny
speckとmicroblobを混ぜたlabel、target線へ反応せずclean背景へ反応したHessian
ridge、metricごとの独立threshold選択です。r3の再実行、再label、再調整、threshold
凍結、locked検証、holdoutは禁止します。

r4はr3のretuneではなく、新しいspec、実装、blind key、controls、labels、locked
clean reference、authority receipt、holdoutを持つ独立editionです。

## 目的と適用境界

Vision上の即時不合格である粒、点、微小塊、短線、平行線束、周期模様を、候補画像を
見ずに較正します。候補、foundation、permission mask、過去候補順位はcontrol生成、
label、formula、thresholdへ入力しません。

r4が測るのは、別途作られた256×192の背景luminance residualです。道路、河川、
海岸、文字、記号、集落、正典geometryを含む生のmap pixelへ直接使いません。holdout
合格後も、production referenceとeligible-background maskを別specで事前登録するまで
制作候補へ接続しません。

## Authority

実行可能なrootは`scripts/map-production/microtexture-v2-r4/`です。normative JSON、
実装、docs、templates、self-testは`implementation-bindings.json`でbyte固定します。
各操作は次をすべて要求します。

- HEADがcurrent branch upstreamと一致
- authority working bytesがcaptured HEADと一致
- exact code rootとexact成果物root
- spec、bindings、runtime、blind-key commitmentの一致
- 操作中のHEAD不変

Formal stageは同一machineと同一runtime fingerprintを要求します。Fingerprintはplatform、
Python executable hash、Python / NumPy / SciPy / Pillow / zlibのversionに加え、実際にloadしたNumPy core、SciPy
ndimage、Pillow imaging binaryのSHA-256を含みます。Calibration HEADをfrozen authorityへ
固定し、locked validationは同じHEADだけ、holdoutはそのHEADをancestorに持つtracked
receipt commitだけで実行できます。

UbuntuとWindows CIが同じauthority commitで成功するまでformal controlを生成しません。

## Exact Vision / metric unit

Control canvasは512×384 L-modeです。metricは中央`[128,96,256,192]`だけをcropし、
その後にreflect filterを適用します。この256×192は200% contact-sheet panelのsource
全体と完全一致します。400%は北西・北東・南西・南東の非重複128×96へ4分割し、
4 viewの和が256×192全域と完全一致します。実装は5 viewのID順、exact-int scale / crop、
nearest resize、4象限のmetric内包含、重複なし、gapなし、同一page indexのcode順一致を
runtimeでも検証し、1pxのずれやbool / floatへの型変化もfail closedにします。

sparse speck、microblob、short dash、parallel bundleは各splitでexact integer 0..9個を
1条件ずつ持ちます。0は真の無注入境界です。非zeroの位置と角度は全てsecret-derivedで、
中央固定や固定軸はありません。全geometryをmetric window内へ収め、外側canvasはmetricへ
影響しません。Countとsize / amplitude / width / spacingは単調増加させず、low-countの
大きく強い条件とhigh-countの小さく中程度の条件を交差配置します。

## Hard gate

blocking metricは1件だけです。

```text
delta = control - reference
highpass = delta - Gaussian(delta, sigma=4, reflect, truncate=4)
microartifact_occupancy_per_mp =
  count(abs(highpass) >= 3.0 L) * 1,000,000 / 49,152
reject = occupancy > frozen threshold
```

Blob、finite-line、parallel-pair scoreは原因帰属用diagnosticです。threshold選択、
reject、freeze、holdout passへ混ぜません。これによりmetricごとのfalse rejectがORで
累積する構造をなくします。

## Control corpusと独立cluster

各splitは140 recordsです。

| 区分 | Family | parameter clusters | records |
| --- | --- | ---: | ---: |
| clean | zero / lowpass / Matérn-like / broad shoulder / multiscale | 20 | 20 |
| grain | fine band / halftone | 20 | 40 |
| spot | tiny speck / microblob | 20 | 40 |
| line | short dash / parallel bundle | 20 | 40 |
| 合計 | 11 family | 80 | 140 |

異常clusterはdark/light polarityの2 recordsを持ちますが、polarityは独立標本数へ
加えません。cluster内record correctnessを平均し、その後clusterを等重みで平均します。
Dark/lightはbyte-identical referenceと同一のposition / angle / unsigned deltaを共有し、
最後の符号だけを反転します。Calibrationとholdoutはnonce、parameters、背景、配置を分離します。

anonymous code順に1頁6件、full 200%を24頁、4象限400%を各24頁、計120頁 / splitです。
私が全5 viewの全頁・全codeを見ない限りlabelは受理されません。

## Root Vision labels

visible flagは次の5件です。

- `grain_visible`
- `tiny_speck_visible`
- `microblob_visible`
- `short_line_visible`
- `parallel_bundle_visible`

Disposition整合は固定です。

- clean: severity 0、visible flagなし
- warning: severity 1、visible flagを1件以上
- reject: severity 2または3、visible flagを1件以上

full 200%と全4象限400%のreviewed flag、全exact keys、全code coverageを要求します。旧
`speck_visible` schemaはfail closedです。validated labelsとexclusive one-shot markerが
作られる前のidentity / cluster revealは禁止します。Reviewed label inputはlink / junction /
reparse pointを含まないregular fileとしてspec固定の
`controls/calibration/labels-calibration.json`または
`controls/holdout/labels-holdout.json`だけから読みます。Marker直後かつ新規decode / reveal /
measurement前に、そのvalidated bytesを`sealed-inputs/`以下のsplit別固定pathへexclusiveに
封印し、bytes SHAをreportへ結合します。Calibration authorityとterminal holdout reportの
再読込時にもsealed bytesを読み、manifest、measurements、revealed clusterから全endpoint
count / rateとselector結果を再計算します。

## Threshold selectionと合格条件

候補thresholdは`max(0, minimum-epsilon)`の非負lower boundary、隣接値midpoint、
`maximum+epsilon`のupper outward sentinelです。完全hard gateで
clean cluster acceptance `>= .95`、warning cluster acceptance `>= .75`を満たす候補だけ
を許可し、次の順で一意に選びます。

1. grain / tiny-speck / microblob / short-line / parallel-bundleの最小cluster detectionを最大化
2. combined spot cluster detectionを最大化
3. overall reject cluster detectionを最大化
4. severity-3 cluster detectionを最大化
5. clean acceptanceを最大化
6. warning acceptanceを最大化
7. より厳しい低thresholdを選択

Calibration / holdoutはそれぞれ次を要求します。

| endpoint | minimum clusters | calibration | holdout |
| --- | ---: | ---: | ---: |
| clean acceptance | 15 | .95 | .95 |
| warning acceptance | 10 | .75 | .75 |
| overall reject detection | 30 | .95 | .95 |
| severity-3 detection | 4 | 1.00 | 1.00 |
| grain reject detection | 8 | .80 | .75 |
| tiny-speck reject detection | 4 | .75 | .75 |
| microblob reject detection | 4 | .75 | .75 |
| spot reject detection | 8 | .80 | .75 |
| short-line reject detection | 8 | .80 | .75 |
| parallel-bundle reject detection | 6 | .80 | .75 |

不足population、0分母、vacuous passは禁止です。全threshold候補のadmissibility auditを
reportへ残すため、候補が1件も許可されない場合も原因を追跡できます。Calibration失敗でも
reportは残しますが、thresholds-frozenは作りません。候補が1件もadmissibleでない場合、
`hard_threshold`はnull、endpoint / per-code resultsは昇順candidateの最後であるupper
sentinelに結合し、`passed=false`とします。失敗したeditionは閉鎖します。

これはconfidence intervalや無制限母集団の推定ではなく、exact finite corpusに対する
決定論的coverage gateです。Endpoint間の独立性は主張せず、合格の意味を「同じ単一gateが
事前登録した全count/rateをcalibrationとholdoutの双方で満たした」に限定します。

## Fresh ImageGen locked clean reference

`microtexture-v2-locked-clean-reference-imagegen-v7.png`はr3 v4/v5を参照しないfresh
chainです。第1案は私が200% / 400%の細かなmottleと短いwispを見て棄却し、第2案だけを
保存しました。第2案はexact metric windowの4象限を個別に400%確認し、Root Vision 97、
独立Vision 97で、original / 200% / 全4象限400%の点、塊、短線、平行束、反復、seamなしを
確認しています。

この画像はthreshold選択から除外し、freeze前の数値計測を禁止します。Freeze後に中央
256×192だけを一回評価し、hard gateがacceptしなければr4を閉じます。Production donor、
Golden input、最終pixelには使いません。

## 技術的blindとone-shot chain

- 32 cryptographic random bytesを一時環境変数で渡し、値をartifactやlogへ保存しない
- render seed、private control ID、private cluster ID、anonymous codeをHMAC-SHA-256で導出
- public manifest / labelsへidentityとclusterを出さない
- manifestをcode、control SHA、reference SHA、requested-delta SHAへ結合
- contact-sheet bytes、SHA、code順、crop、scaleをsecret-derived corpusから再生成
- marker、control directory、report、frozen threshold、最終completionをexactなregular non-link pathへexclusive write
- marker SHAをreportとfrozen authorityへ結合
- markerへruntime、captured HEAD、started_at、one-shot consumedをexact-schemaで結合
- 次stageのmarker前には既に消費済みのreport / labels / stored metrics / receiptをauthorityとして
  再計算できますが、旧source imageを再測定せず、新stageのtarget decode / measurement / revealはmarker後だけ
- normal pass / normal endpoint failの双方で、全read-backとHEAD確認後にstage completionを最後の操作として
  書き、normal failは`passed:false`とする。Authority loaderはcompletion必須かつfailure reportとの共存を拒否
- marker後のcatch可能な例外はstage別exclusive failure reportへphase、type、sanitized messageとhashの
  記録を試み、persistenceや`add_note`自体が失敗してもoriginal throwableを置換せず、markerとcompletion欠如を閉鎖証拠とする
- normal reportは保存前にnested numeric / bool / rate、全candidate、objective、per-code result、
  endpoint、最終passを入力から再計算し、authority再読込でもcalibrationを再計算
- terminal holdout reportはfinal completion前にread-backし、actual control / reference / sheet、sealed
  labels、marker、freeze、tracked receipt、HEAD / runtime、secret-derived exact identityへ再結合し、
  completion writer自身も書込み後のexact non-link bytesを検証
- holdout前にfreeze、locked-clean report、reviewer receiptをhash結合
- holdout control生成時とholdout marker前の双方で、current receipt HEADにあるv7本体、
  generation chain / receipt、Root / independent Vision QAの5ファイルをtracked bytesとspec SHAへ再照合

## 実行順序

1. r4 authority、v7画像、prompt receipt、Root / independent Vision QA、本文書をcommit / push
2. Ubuntu / Windows CI成功を確認
3. fresh blind keyを安全に作り、calibration 140 controlsを一回生成
4. 私がcalibration 120頁・140 codeを匿名状態でlabel
5. calibrationを一回評価。失敗ならr4閉鎖
6. 合格時だけthresholdをfreezeし、v7 locked cleanを一回評価
7. eligible independent reviewerがexact hashesを監査し、tracked authority receiptを作成
8. receiptをcommit / pushし、Ubuntu / Windows CI成功を確認
9. v7と全provenanceを再検証後、未使用holdout 140 controlsを一回生成
10. 私がholdout 120頁・140 codeを同じ規則でlabel
11. v7と全provenanceを再検証後、holdoutを一回評価。失敗しても変更・再実行しない
12. 合格時だけproduction residual derivationとv246 terminal familyを別specで事前登録

Production側の別specは、reference/source hash、semantic maskとerosion、eligible pixel不足時の
無効化、tile overlap / halo / seam、zoom / DPI、color / alpha / resampling、windowからmasterへ
昇格する集約規則、地域・地形別の未使用production holdoutを全て固定します。r4の合格だけで
制作pixelへの適用は許可しません。

## Golden / Phase 5への接続

新v246はfamily、candidate数、seed、donor変換、residual reference、eligible mask、合成、
gate、停止条件を事前登録します。Golden候補は同一native PNGから
`native/full25/full50/highland200/highland400`のexact-fiveを作り、私が5枚全てを
Vision確認します。異なる二名のSHA-blind reviewerも双方94点以上でなければ昇格しません。

Golden固定後は`17 direct -> idx17 -> 5 continent -> idx22 -> world -> idx23 ->
23 masters / 1350 tiles`の順で制作し、採用する各masterを私がVision確認します。
