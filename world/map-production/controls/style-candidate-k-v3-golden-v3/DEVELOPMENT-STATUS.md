---
type: "analysis"
category: "analysis"
title: "Golden v3 development status"
version: "1.0.0"
created: "2026-08-30"
last_updated: "2026-08-30"
author: "Codex"
tags: ["maps", "image-generation", "vision-qa"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "Golden v3 v21 development attempts, numeric gates, and fail-closed replay tooling"
base_files: ["world/map-production/spec/phase-plan.md", "scripts/map-production/render_style_candidate_k3_overhead_relief_v21.py"]
methodology: "Bounded candidate generation, native and enlarged Vision inspection, SHA-bound pixel audits, and independent read-only review"
---

# Golden v3 development status

Status: **development checkpoint only; no Golden candidate is designated**.

This file records rejected experiments and the fail-closed state of the v21
tooling. It is not acceptance, promotion, blind-review, or production
authority. No candidate from this work may be promoted from this document.

## Invariants proved across the v21 work

- Canvas is 1536 x 1024 RGB.
- The selected highland control contains exactly eight 8-connected,
  non-touching systems with 96,128 pixels.
- The replacement system has 11,302 pixels at bbox `[1030,49,1131,203]`;
  the detached 1,777-pixel v19 pill is absent.
- The selected-body union SHA-256 over contiguous uint8 bytes is
  `ffbb51bcf750c7f68aa3b8cc7a262746b82e956c0d95d5b34e926529162aa2bc`.
- Every emitted or in-memory experiment reported below preserved zero
  outside-permission, protected-feature, and road-calm-18px deltas unless a
  failure is stated explicitly. No such identity failure occurred.

## Visual development attempts dev03-dev20

All files below are TEMP development evidence under
`tmp/map-production/k3-golden-v3-v21-attempt-v2/`. They are rejected and must
not be staged as product assets.

| Attempt | PNG SHA-256 | Rejection summary |
|---|---|---|
| dev03 | `176684ff6c41d33aed66d70be4c0dc32244416d0edeed81ba406d6ea7a4f516d` | Thick angular center paths and near-perpendicular branches read as a route/root/river-vein diagram. |
| dev04 | `074e1e827ed4053b87286574c73370a31537054c6a1ad8b9f003e1faab8d69c5` | Curved geometry improved, but orange crests and cyan valleys read as annotation markup; bodies stayed flat. |
| dev05 | `a4ab32bbe1cece8089b36915dbc40d5aaa9b8ccd273e795529c5c9d291be9a2a` | Near-monochrome sepia became coherent, but relief remained too faint at 200% and 400%. |
| dev06 | `61d699d54affdb329d405e74bd6f8b7a5042bb908fbc388b4686825d40c9179d` | Separately composited opposing shoulders cancelled and did not create readable volume. |
| dev07 | `a35736dc51b3cdecef402cbf35d8bbe2397f1adc7eeebde5827c6f1c48b02cc9` | Signed line-field relief read as a satin/crease treatment instead of terrain. |
| dev08 | `976ad7fbc3d3b688236c26e7d339a8ec950d34c71162748531d672a063e5eaba` | Band artifacts receded, but the systems collapsed back to flat bodies with negligible 200-to-400 gain. |
| dev09 | `f6153dc8af86f0643ac278d1c265a00d29ab265dfea471e6bcd6d45b107a2721` | Gaussian lobes produced airbrushed highlights; hard fills still dominated and terrain information did not resolve. |
| dev10 | `35b90262b943ebdfeb760e040d7f2ab731ed75861506ae4b6d357f0b5e7a71a7` | Stronger crest-aligned volume retained synthetic satin/linear grammar and weak landform hierarchy. |
| dev11 | `bf1172d4e49de7c4d52d0d94289570e2b234852436dc5e6cfd14d65792de4abd` | Lighter base integrated better, but several systems remained flat and diagonal crease bands dominated. |
| dev12 | `36517c933376fe23685aaf6c6262a99965d8ce48980b667ad38a378031de2429` | First non-path terrain field did not yet produce legible multi-scale uplands. |
| dev13 | `ec0d95dc749ba857b0cfede894d5528c4a9ce9ca550293aa1c14fd5ce748b070` | Revised field remained too flat/common in grammar for a visual pass. |
| dev14 | `7b57286d5751ff3f6ff975781517c06e886bb6742f5386f544323eb0470173d6` | Soft integration improved, but large interior discs read as diffuse stains/central pillows shared by all bodies. |
| dev15 | `596c2bf0a6ec49fc127f9d4daf7364278dbb06bae4e4acd709a4d2f7b9a111dc` | Reduced tint still read as cloud shadow/wet stain rather than eroded overhead upland. |
| dev16 | `5f6d21b7d29868d6e664f7d44258340556ec97a96837962cc78aabac99706d7d` | Materially improved and borderline, but native remained pale and several bodies stayed smudgy/cloud-like; not frozen. |
| dev17 | `10177aad916067ef722a787e73119c5cf7c88d9709a92213b553810a7b577934` | Stronger Lambert relief created closed/near-closed dark perimeter arcs, crater hollows, and a vertical bar. |
| dev18 | `8d5d4300b4a23aff31aba5b21d8bd5cc352cb3fcc060dc2b61ccde71e64c544c` | Attempt to break rings produced visible tiger-stripe/parallel-field grammar. |
| dev19 | `5e536a3e84795467b04233843afff2d65466655d83388b2333081f985866acea` | Residual dark arcs and elongated bars remained. |
| dev20 | `29bc29d8f743442fab5fd263e3aad7094e56f69852cab6bd09deeb3fef92ad22` | Provisional visual pass only: distinct soft-edged systems without dominant rings/stripes/bars, but several remained pale/smudgy and strict texture/coverage failed. |

dev20 exact metrics were coverage 330/301 at 50%/25%, quiet `0.960109`,
dash pairs `0`, orientation `0.126138`, and texture sigma-4/sigma-8
`0.362733/0.469864`. It is not a Golden candidate.

## Fixed numeric sweeps dev21-dev31

All candidate sets were frozen before evaluation, evaluated completely, and
stopped without expansion.

| Attempt | PNG SHA-256 | coverage 50/25 | quiet | dash | orientation | texture 4/8 | Result |
|---|---|---:|---:|---:|---:|---:|---|
| dev21 base 3x | `c8f4af83ff080a21d96bdc22d1079090991ca0d004e2d6033f951f575a29ccc9` | 361/330 | .912318 | 2 | .019323 | .402839/.588783 | reject |
| dev22 base 4x | `7b1fad28a4b86ee7d2079a97ef09d477eeaa0cc6fcf87f8a3ee90d34085a9b89` | 367/339 | .895947 | 6 | .009056 | .432295/.667860 | reject |
| dev23 base 5x | `aa43b8a3fdc00f94e844df2664ac2f77670563eebfab2653d81adf97f08551a9` | 372/342 | .889501 | 5 | .016844 | .462793/.749231 | reject |
| dev24 micro 1.25 | `1fc1d079745f1127c99476af8d217371374eca1ea7699d17e76e9edf4ecd02a7` | 330/302 | .950239 | 1 | .108424 | .379445/.506042 | reject |
| dev25 micro 1.50 | `b328313455b70246359a8b4164c0a4f28f8a980939ef1c0c173e0e60e28cdd8b` | 330/302 | .946861 | 0 | .104591 | .385540/.520475 | reject |
| dev26 micro 1.75 | `eb8c574bd1675c88e046cc67d85bed2ac15793051d1cdec7f8dedbe2e0192111` | 330/302 | .942126 | 0 | .098728 | .391993/.536096 | reject |
| dev27 micro 2.00 | `6b223cdef8317b9f0a343d77f6ce6eebab8a0a2f29421507ff687adb81c7e053` | 330/302 | .937017 | 0 | .092922 | .400096/.555100 | reject |
| dev28 gain 1.06 / DoG 5.5 | `2cdfcb9d591cb5f5e0bd1398296886559c4b6d920b5c62dfa8a485121875736b` | 375/342 | .722054 | 1 | .032343 | .575282/.967599 | reject |
| dev29 gain 1.06 / DoG 6.0 | `c6fc4291e0b8c8cb051ff09e993914f0e2d5a6b577e25c69793abf83b68a0561` | 380/348 | .677431 | 0 | .025929 | .607897/1.034321 | reject |
| dev30 gain 1.10 / DoG 5.5 | `6071bb19081a506b4909a756d8163f469f7d308a0e445114e2f3b0164d0da337` | 375/342 | .720331 | 1 | .034050 | .576595/.970592 | reject |
| dev31 gain 1.10 / DoG 6.0 | `9b6bcb70b0513df470f09d007a0176507b2a6a1baadd92c63ae3da9265d00f7b` | 380/348 | .676064 | 0 | .027631 | .609190/1.037148 | reject |

The dev28-dev31 quiet failure was image-gradient-driven: dev28 had 24,920
`gradient >= 26` seeds and 64,854 dilated active measurement pixels, versus
3,033 and 9,308 for dev20. High-pass seeds stayed only 67-80. Native visual
inspection also rejected the full-measurement DoG as uniform mottled-plaster
wallpaper that suppressed the eight systems.

## Paper and non-emitted procedural families

These were bounded, read-only/in-memory evaluations. No candidate PNG was
emitted.

- v19 native parchment component at multipliers 2/3/4/5: all strict-fail.
  Multiplier 2 already reduced quiet to `.8827`; multiplier 5 reached only
  texture-8 `.9141` and coverage 334/302. Multipliers 4/5 produced 5/38 dash
  pairs.
- Sparse organic slope reinforcement, fixed 2x2: maximum coverage 335/306
  and texture `.3676/.4859`; stronger variants failed coherence and produced
  a severe vertical residual.
- v19-neighborhood plus direction-neutral ground scalar at amplitudes
  2/4/6/8: all strict-fail. A2 reached texture-8 `.9929` but had one dash
  pair and three arcs. A8 reached texture-8 `1.1054` only with quiet `.8421`,
  texture-4 `.6688`, six dash pairs, and topology counts 3/11/1/1.

## ImageGen donor evaluations

No ImageGen output was accepted as a candidate or copied into the repository.

- First donor binding: RGB 1305 x 1206, 2,911,400 bytes, SHA-256
  `7900d9adf979db18f4ca8d3902606ecdee59cac0a8b65e939407a0f305a5fda5`.
- A direct `source L - base L` four-point plan was superseded before any
  evaluation because it would transfer absolute luminance and a shared
  projected shadow. Evaluated candidates: zero; emitted candidates: zero.
- A replacement body-local normalized mid-frequency plan was frozen at
  blends .20/.30/.40/.50 and evaluated entirely in memory. All four kept
  exact eight components and zero three-lock deltas, but all failed primary
  metrics and topology:

| blend | in-memory canonical PNG SHA-256 | coverage 50/25 | quiet | dash | orientation | texture 4/8 | forbidden topology count |
|---:|---|---:|---:|---:|---:|---:|---:|
| .20 | `b6a49b9ade0f408655c3da478b5ba04b2d41b69aeb784f69fe68771b7bc552aa` | 334/306 | .931664 | 0 | .184415 | .381350/.506927 | 2 |
| .30 | `3dcd41659f35256bf6a28f35fe3cfab29dd1fb825d3059fd7c115cef9d4eca6c` | 336/307 | .911894 | 0 | .210642 | .393413/.530034 | 8 |
| .40 | `feb8090d3059466b2829b49b36bdadb900a6d27f59a7755c53de3c217be2789e` | 340/310 | .888957 | 0 | .228033 | .406967/.555393 | 8 |
| .50 | `816dddae700b774c0195b12a413b3043d53399f9a1e1a3b36b37450567309fb3` | 345/315 | .866590 | 4 | .242244 | .422044/.582785 | 13 |

- A second generated variant was rejected before numeric evaluation because
  repeated web/line-bundle relief and embossed edges were field-wide.
- A direction-neutral generated ground donor was evaluated in a fixed
  G4-G18 amplitude 4/6/8/10 sweep and stopped. A4 already had two dash pairs
  and crater/arc diagnostics; A10 reached only coverage 355/323 and texture
  `.454/.687`, with quiet `.847` and 50 dash pairs.

The two ImageGen sweep plans and their evaluator contain an absolute external
development input path. They are diagnostic-only and are explicitly excluded
from any production-ready checkpoint/staging set.

## Audit authority gap

The existing independent pixel auditor implements only coverage, quiet,
dash-pair, global orientation, sigma-4/sigma-8 texture, exact-eight geometry,
and the three permission/protected/road locks. The stricter phase-plan line
also names the following thresholds, but the current repository tree and repository
history contain no authoritative formula or mask binding for them:

- `sub8_energy_fraction <= .42`
- A/unit repetition `<= .05`
- total repetition `<= .07`
- per-body unit sigma-4 energy `>= 29`
- per-body unit sigma-8 energy `>= 34`
- white crest particle count zero

No experiment in this checkpoint claims those undefined gates passed.
Closed-loop checking is represented only by the renderer's pre-encode
crater/partial-arc proxies. A generic `alpha_zero` lock is also absent from
the v3 audit control; it would have to be derived from v19
`derive_controls()["alpha"] == 0` and bound explicitly before it could become
an auditable v3 gate.

## v21 tooling checkpoint

The following development tooling is fail-closed, but not production-ready:

- `render_style_candidate_k3_overhead_relief_v21.py` pins Python 3.12,
  OpenCV 4.13.0, NumPy 2.3.5, Pillow 12.3.0, little-endian execution, and uses
  a single OpenCV thread and fixed OpenCV RNG seed. It uses a manual filter-0
  PNG encoder with explicit stored DEFLATE blocks.
- The Golden-v3 control and five-view emitters now import v21 rather than the
  absent v20 renderer module.
- The Golden-v3 read-closed wrapper now preloads the v21 runtime surface.
- `tests/golden_v3_v21_canonical_png_test.py` has five passing tests covering
  exact manual bytes for all six masks, the indexed body control, the RGB
  foundation, runtime pins, and exact replay of the rejected dev20
  intermediate.

Fail-closed blockers intentionally remain:

- `renderer-config-v21.json` does not exist.
- v21 config SHA, expected output SHA/pixel SHA/byte count, and ordered
  donor/control inventories are zero/empty placeholders.
- `audit-control.json` still binds the rejected historical v20 candidate
  `9b75d1d651b9cda0070c331a53215c5612ee82d7a34b94b19f20a2067a65e050`
  and retains Golden-v2 audit identifiers.
- Default v21 replay still reconstructs rejected dev20 SHA
  `29bc29d8f743442fab5fd263e3aad7094e56f69852cab6bd09deeb3fef92ad22`.
- The relief search summary reproduces the selected eight systems, but its
  `input_marks_sha256` is format-checked only; the originating input-marks
  artifact is not part of the replay graph.
- The five checkpoint tests do not claim to validate a final config, sealed
  output constants, fixed CLI closure, or the missing strict-v3 audit.
- Therefore final control generation, fixed view emission, and read-closed
  Golden replay cannot succeed for any unapproved candidate.

## Checkpoint exclusions

Do not stage as production-ready authority:

- any file under `tmp/`;
- the two absolute-path ImageGen plans and their evaluator;
- a zero-output or rejected-output renderer config;
- blind packets, reviews, acceptance receipts, promotion records, or a Golden
  candidate (none were created);
- external generated images.

No promotion, acceptance, blind-review approval, or Golden designation is
recorded by this status file.
