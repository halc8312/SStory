---
type: "overview"
category: "maps"
title: "Microtexture v2-r3 候補非依存較正契約"
version: "0.3.0"
created: "2026-07-25"
last_updated: "2026-07-25"
author: "Codex"
tags: ["maps", "quality-assurance", "microtexture", "vision-qa", "calibration"]
status: "review"
document_kind: "navigation"
summary: "匿名合成control、Root Vision、未使用holdoutで粒・微小塊・短線・平行線束の検出器を候補非依存に凍結する契約です。"
---

# Microtexture v2-r3 候補非依存較正契約

## 目的と境界

Golden候補を自動検査へ合わせて弱くするのではなく、Vision上の即時不合格である粒、点、短線、平行線束、魚骨、周期模様を直接測ります。候補画像、正典foundation、permission mask、過去候補の順位や選択結果は、control生成、label、metric定義、threshold選択に使用しません。

Microtexture v2-r3のcalibration、locked positive、独立authority、未使用holdoutがすべて合格するまで、新しいv246候補を生成しません。合格後も、候補を見てthreshold、seed、family、component分類、null反復数を変えてはいけません。

## 旧rawゼロ件ゲートを置換する理由

v193–v244の重複routeを除いた316件を候補選択に使わず集計した結果は次のとおりです。

| 条件 | 合格数 |
| --- | ---: |
| `sub8_cell_component_count == 0` | 0 / 316 |
| `dash == 0` | 43 / 316 |
| `parallel_short_bundle_pair_count == 0` | 15 / 316 |
| 三条件の同時合格 | 0 / 316 |

`texture4 >= .4`の149件ではbundleゼロが0件でした。生bundle数はquietとSpearman `ρ=-.985`、texture4と`ρ=+.786`で、形態欠陥より活動量を強く測っています。

旧sub8検査は`max(p99(high4), 1.5)`を二値閾値にします。信号が1.5未満なら突然0件となり、1.5を越える自然な連続場では上位1%の局所極値を多数数えます。一方で、視覚上問題になる1–3px粒とbboxが9px以上の細い線を対象外にし、画像面積でも正規化しません。

r3合格後、旧component/dash/raw bundle件数はlegacy diagnosticとしてだけ残します。連続量である`sub8_energy_fraction`、texture帯域、quiet、orientation、repetition、body energyは別軸の固定gateとして維持します。

## 凍結済みauthority

実行可能な唯一のauthority rootは`scripts/map-production/microtexture-v2-r3/`です。

| Authority | SHA-256 | 状態 |
| --- | --- | --- |
| r1 preregistered spec | `2018d1427eb7a52ea77314ecde821b6aa63b56553cecb9ac4f9ea6d1aa316cbd` | 実行前棄却・不変 |
| r2 preregistered spec | `3d28be3ff74272cd82e247867994775c507a07afe5b3382d5e21abef3b50b96e` | 実行前棄却・不変 |
| r2 implementation bindings | `8cccf13f4d68fe2df8fc3f80e2adcd911f94bc388bd75b7846fbb974f5c62f7d` | 実行前棄却・不変 |
| r3 preregistered spec | `166eb08f8d2f9de673c29c4c24b4d1c405f0ea3800a04b50ac4124aa84bdb0a1` | 昇格済み・未実行 |
| r3 implementation bindings | `a08e20142ca6d3b797223cfbeee8659396d8f5a08431e79843d5fc7730420ddd` | 11 authority fileを固定 |

r1はraw bundle、threshold authority、manifest binding、匿名性に欠陥があり、r2は公開hashからidentityを推測できること、warningのhard扱い、小標本nullの盲点、label意味の曖昧さがありました。両版ともcontrol、metric、画像を一度も実行せず閉じています。

r3は正確なtracked path、全authority bytes、captured Git HEAD、current branch upstreamを相互に固定します。HEADとupstreamが一致しない場合、またはauthorityの作業tree bytesがcommitと異なる場合は、artifact作成前に停止します。

## ImageGen資産の役割

- `microtexture-v2-calibration-positive-imagegen-v4.png` はRoot Vision 94点の目視専用smooth anchorです。threshold選択、数値validation、holdout、制作候補、Golden、最終画素には使用しません。
- `microtexture-v2-calibration-positive-imagegen-v5.png` はSHA-256 `b9e21a0e32cf88d099f81503915c5649affc192c9ae025ce3f893dce472a88e7`のlocked positiveです。threshold凍結後に中央`[512,320,512,384]`だけを一度評価し、全hard metricの受理を要求します。threshold選択、制作候補、Golden、最終画素には使用しません。
- `k3-v246-imagegen-ground-material-donor-v5.png` はcalibration、locked validation、holdoutから完全に除外します。r3 holdout合格後に新しく事前登録するv246 production derivationでのみ、相対的な低・中周波輝度位相を条件付き利用できます。

したがって、ImageGen画像がr3 thresholdを学習させることはありません。v5は凍結後のfalse-reject検証だけであり、1–24pxの粒・線・塊を許可する根拠にはなりません。

## 技術的blind

- 32 cryptographic random bytesを64桁hexとして一時的に渡し、値をファイル、生成物、logへ保存しません。
- render seed、private control ID、24桁anonymous codeはHMAC-SHA-256で導出します。公開物へ出すのは一方向commitmentだけです。
- Git subprocessからblind key環境変数を必ず除去します。
- calibrationからholdoutまで同じcommitment、runtime、implementation bindingsを要求します。
- parallel nullは公開固定seedとridge geometry digestだけから再現し、blind keyへ依存しません。将来の候補監査も秘密鍵なしで再現可能にします。

各manifest recordは`(anonymous_code, control SHA, reference SHA, requested-delta SHA)`のexact tupleとcode由来pathでsecret-derived corpusへ結合します。contact sheetも同じcontrolから、中央crop、整数NEAREST、2×3配置、固定3×5 hex font、page順、L-mode PNGを再生成し、manifest bundle、保存PNG bytes、SHA、寸法を完全一致させます。私が見たsheetと数値評価されたcontrolを差し替えることはできません。

## Control corpus

各splitは512×384 L-modeで、clean 18件、defect probe 48件、合計66件です。全variantを2 replicateとし、calibrationとholdoutでnonceとparameterを分離します。

| 区分 | Family | 件数 / split |
| --- | --- | ---: |
| clean | zero、lowpass、Matérn-like、broad shoulder、multiscale | 18 |
| defect | speck、microblob、fine band、short dash、parallel bundle、halftone | 48 |
| 合計 | 11 family | 66 |

anonymous code順に1頁6件を配置し、200%を11頁、400%を11頁、計22頁 / splitとします。calibrationとholdoutの合計は132 controls、44頁です。

## Root Vision label

私がfamily、期待label、parameter、polarityを知らない状態で、全22頁の200%と400%を実見してから全66 codeをlabelします。

- `clean`: severity 0、visible flagなし
- `warning`: severity 1、visible flagを1つ以上
- `reject`: severity 2または3、visible flagを1つ以上

visible flagはgrain、speck、short line、parallel bundleです。両scaleを見ていないcode、未記入値、矛盾したseverityは受理しません。labelを検証し一回限りmarkerをexclusive作成するまで、identity revealは禁止です。

warningが0件ならquotaを作るためにlabelを歪めません。`warning_acceptance_applicable=false`、vacuous `1.0`として明示し、warningが1件以上ならhard-composite acceptance `>= .75`を両splitで要求します。

## Metricと合格条件

Hard metricは次の5件です。

1. `speck_density_per_mp`
2. `fine_to_broad_energy_ratio`
3. `short_ridge_density_per_mp`
4. `parallel_bundle_excess_z`
5. `parallel_neighbor_pair_fraction`

`microblob_excess_energy_per_mp`と`broad_parent_support_fraction`はwarning-onlyです。生pair数、density、opportunity、null mean/stdはdiagnostic-onlyで、hard compositeへ混ぜません。

Calibrationはclean false rejectをmetricごとに最大.05とし、hard metricのmatching reject検出を順に`.75/.75/.75/.60/.75`以上要求します。Holdoutは同じ順に`.70/.70/.70/.60/.70`以上です。両splitのhard compositeはclean acceptance `>= .95`、warning acceptance `>= .75`（applicable時）、reject detection `>= .95`、severity 3 detection `= 1.0`を要求します。

## 一回限りの実行順序

1. r3 authority、画像生成receipt、Vision QA、本文書をcommit/pushし、Ubuntu / Windows CI成功を確認します。
2. blind keyを安全に一度生成し、生成物rootを`tmp/map-production/microtexture-v2-r3-artifacts`へ固定します。
3. calibration 66 controlsだけを一度生成します。
4. 私が200% / 400%の全22頁を見て、全66 labelを確定します。
5. 一回だけcalibrationを実行します。失敗した場合はthresholdを調整せずr3を閉じます。
6. 合格時だけthresholdを凍結し、v5 locked positiveを一回だけ実行します。全hard metricが受理しなければr3を閉じます。
7. `Cicero the 2nd`または`Descartes the 2nd`だけが、凍結reportとlocked reportのexact hashを独立監査し、tracked receiptを作ります。これは事前登録allow-listとhash-bound receiptによるprocedural trusted-agent assuranceであり、暗号署名や人間本人証明ではありません。
8. receiptをcommit/pushしてから、未使用holdout 66 controlsを一度だけ生成します。
9. 私がholdoutの全22頁、全66 codeを同じ規則でlabelし、一回だけ評価します。失敗してもthresholdは変更しません。
10. 合格時だけ、固定metric、transform、thresholdをGolden auditorへ接続し、新しいv246 terminal familyを別specで事前登録します。

## GoldenとPhase 5への接続

候補監査はblind keyへ依存せず、calibration時と同じmetric bytes、runtime contract、凍結thresholdを使います。legacy raw件数はreceiptへ残しますが、r3 hard gateと混同しません。候補実行後のmorphology、component削除、pixel pruning、局所減衰、threshold変更は禁止します。

新しいv246はr3合格後にだけfamily、candidate数、seed、donor変換、合成、gate、停止条件を事前登録します。Golden候補は同一native PNGから`native/full25/full50/highland200/highland400`のexact-fiveを作り、私が5枚すべてを確認します。さらに異なる二名のSHA-blind reviewerが双方94点以上でなければGoldenへ昇格しません。

Golden固定後、`17 direct -> idx17 -> 5 continent -> idx22 -> world -> idx23 -> 23 masters / 1350 tiles`の順で制作し、採用する各masterを私がVision確認します。
