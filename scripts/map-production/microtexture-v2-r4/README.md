# Microtexture v2-r4 authority

r4 is a fresh, one-shot successor to the failed and closed r3 authority. It
measures exactly the center 256×192 luminance-residual window shown in full on
the 200% contact sheets. r3 controls, labels, key, thresholds, and locked source
are development evidence only and cannot enter an r4 decision.

## Hard gate

Only `microartifact_occupancy_per_mp` is blocking:

```text
highpass = delta - Gaussian(delta, sigma=4, reflect, truncate=4)
occupancy = count(abs(highpass) >= 3.0 L) * 1,000,000 / 49,152
reject = occupancy > frozen threshold
```

The sparse-blob, finite-line, and parallel-pair scores are deterministic cause
diagnostics. They never reject a control, influence threshold selection, or
block holdout. This leaves one complete hard composite and one jointly selected
threshold, so independent metric false-reject rates cannot accumulate through
an OR gate.

## Blinded populations

Each split has 140 controls: 20 clean records and 120 artifact records. The 60
artifact parameter conditions each have paired dark/light polarities; polarity
is not counted as an independent condition cluster. Sparse speck, microblob,
short-line, and parallel-pair families contain exact integer counts 0 through 9;
zero is a real no-injection boundary, and every nonzero position/angle is
secret-derived without a forced center. Paired polarities share the exact
reference and unsigned geometry and differ only by sign.
Count is crossed non-monotonically with size/length and amplitude, so the set
contains low-count strong/large and high-count moderate/small conditions.

Root must inspect every anonymous code on 24 full-window pages at 200% and 24
pages for each of the northwest, northeast, southwest, and southeast quadrants
at 400%: 120 pages per split. The four quadrant views partition the complete
metric window, so no sparse item can fall outside the high-magnification review.
The renderer fail-closes unless the five exact IDs, order, integer scales,
integer crops, non-overlap, gap-free union, nearest-neighbor resize, and matching
per-page code order all agree with that partition.

Vision labels separate grain, tiny speck, microblob, short line, and parallel
bundle. Clean, warning, reject, severity, and both-scale review booleans are
exact-schema fields. A missing population or insufficient unique-cluster count
closes r4; no vacuous pass is allowed.
The reviewed-label input must be a regular non-link file at the exact split path
emitted by the generator. Immediately after the marker and before new decode or
measurement, its validated bytes are exclusively sealed at a second
preregistered path. Reports and authority reloads use that immutable snapshot so
endpoint counts, rates, candidate selection, per-code results, and the final
pass remain reproducible after failed and terminal runs.

## Required order

1. Freeze this directory and its implementation bindings in Git.
2. Push the branch and require both Ubuntu and Windows CI to pass at that SHA.
3. Generate a cryptographically random 32-byte key without logging or storing
   it in any artifact. Export it only as `MICROTEXTURE_V2_R4_BLIND_KEY`.
4. Set `MICROTEXTURE_V2_R4_ARTIFACT_ROOT` to the exact repository-relative root
   `tmp/map-production/microtexture-v2-r4-artifacts`.
5. Generate calibration controls exactly once:

   ```powershell
   python scripts/map-production/microtexture-v2-r4/generate_controls.py --split calibration
   ```

6. Root inspects all 120 calibration sheets, completes the generated label stub,
   and runs calibration exactly once:

   ```powershell
   python scripts/map-production/microtexture-v2-r4/calibration_harness.py calibrate --labels tmp/map-production/microtexture-v2-r4-artifacts/controls/calibration/labels-calibration.json
   ```

7. If calibration passes, run the new ImageGen v7 locked clean reference exactly
   once. This is the first permitted numeric access to that image:

   ```powershell
   python scripts/map-production/microtexture-v2-r4/calibration_harness.py locked-clean-reference
   ```

8. An eligible independent reviewer (`Cicero the 2nd` or `Descartes the 2nd`)
   reviews the frozen calibration and locked-clean report, fills
   `threshold-authority.template.json`, and writes the tracked receipt to
   `world/map-production/qa/microtexture-v2-r4-threshold-authority.json`.
9. Commit and push the receipt; require Ubuntu and Windows CI at the new SHA.
10. Only then generate holdout controls exactly once, inspect all 120 sheets,
    complete the exact `controls/holdout/labels-holdout.json` artifact, and
    evaluate holdout exactly once. Both holdout generation and the pre-marker
    evaluation preflight revalidate the tracked v7 image, generation chain,
    generation receipt, Root Vision review, and independent Vision review at the
    current receipt HEAD without numerically measuring v7 again.

Every generation/evaluation command requires HEAD to equal its upstream ref and
requires every authority file to be byte-identical to that captured commit.
Markers, reports, frozen thresholds, final stage completions, and control
directories are exclusive regular non-link artifacts at their exact paths.
The runtime fingerprint binds platform, the Python executable,
Python/libraries, zlib, and the loaded NumPy/SciPy/Pillow native binaries. Every
normal report is exact-schema validated and all stored numeric decisions are
recomputed from its bound inputs before it is written and whenever authority is
reloaded. The terminal holdout report is read back before its final completion and rebound to
actual control/reference/sheet files, sealed labels, marker, frozen threshold,
tracked receipt, HEAD/runtime, and the secret-derived exact identity reveal.
Calibration, locked-clean validation, and holdout then write an exact-schema
completion as the final stage operation. A normal endpoint failure also writes
that completion with `passed:false`; an exception writes no completion. Every
authority loader requires the completion and rejects any coexisting failure
report.
Every catchable exception after a marker triggers an exclusive exact-schema
stage failure-report write. If report persistence itself fails, the durable
marker plus missing completion remains the fail-closed closure record and the
original throwable is re-raised. Adding a
second-fault note is best effort and cannot replace the original throwable.
Failure consumes the edition and closes r4; relabeling, threshold changes,
regeneration, or reruns are forbidden.

## Locked clean reference

`world/map-production/style-assets/microtexture-v2-locked-clean-reference-imagegen-v7.png`
is a fresh ImageGen chain independent of r3. After original/full-window review
and explicit 400% review of all four metric-window quadrants, Root and
independent Vision both approved it at 97/100. It is excluded from calibration
and threshold selection, remains numerically unread until freeze, and is never
production art, a donor, a Golden input, or final pixels.

## Scope

r4 validates a separately derived background residual, not arbitrary semantic
map pixels. A future production derivation must hash-bind its reference/source,
mask construction and erosion, overlap/halo/seam rules, zoom/tile coverage,
color/alpha/resampling rules, deterministic outputs, and a fresh production
holdout. It must exclude roads, rivers, coasts, labels, symbols, settlements,
and other canonical geometry. Passing r4 alone does not authorize that
production derivation.
