# Microtexture v2-r4 preregistration summary

The normative authority is `preregistered-spec.json`; this file is a readable
summary bound by `implementation-bindings.json`.

r4 replaces, rather than retunes, failed r3. The decision-critical unit is the
exact center `[128,96,256,192]` crop of each 512×384 control. That crop is the
entire source shown on every 200% panel; four non-overlapping 128×96 quadrant
views cover all of it at 400%.
The executable validator requires the exact five-view ID/order/type/scale/crop
contract, proves the four quadrants have neither overlap nor gaps, and requires
identical ordered item-code bundles across views for every page index.
All filters run after the exact crop with reflect boundaries.

The sole hard value is the density of pixels whose sigma-4 high-pass residual
has absolute magnitude at least 3.0 L. Calibration selects one scalar threshold
from finite outward sentinels and adjacent-value midpoints. A candidate threshold
is admissible only if complete-gate clean cluster acceptance is at least 0.95
and warning cluster acceptance at least 0.75. The deterministic objective then
maximizes the minimum of grain, tiny-speck, microblob, short-line, and
parallel-bundle detection, then combined-spot and overall reject detection, severity-3
detection, clean acceptance, warning acceptance, and finally stricter threshold.

Performance is cluster-macro, not record-micro. A private cluster contains one
family/variant/parameter condition and excludes polarity and replicate. Within
an eligible cluster, record booleans are averaged; unique clusters then receive
equal weight. Cluster IDs remain secret until the one-shot marker has been
durably written.

Calibration and holdout both require the preregistered minimum unique-cluster
counts and rates for clean, warning, reject, severity-3, grain, tiny-speck,
microblob, combined spot, short-line, and parallel-bundle populations. No missing
or empty population passes. Blob,
finite-line, and parallel-pair scores are diagnostic only.

Each sparse family uses exact integer counts 0..9, never a rounded density or a
forced-center item. Count is deliberately crossed with size and amplitude
rather than forming one monotone diagonal. Dark/light polarity partners use the same reference and
unsigned render realization and differ only by final sign.

Calibration writes its marker before identity reveal or measurement. Any
catchable post-marker exception attempts a separate exact-schema failure report;
an ordinary endpoint failure writes the normal report, no threshold file, and a
final completion with `passed:false`. A normal stage becomes eligible for authority reload only
when its exact-schema completion is written as the last operation; exception
paths have no completion, and completion/failure coexistence is rejected.
Success binds marker,
manifest, report, runtime, implementation hashes, key commitment, hard gate,
threshold, and endpoint definitions into `thresholds-frozen.json`.
If failure-report persistence also fails, the marker plus missing completion
remains closure evidence;
the original throwable is preserved even if adding a diagnostic note fails.
The reviewed-label input must be a regular non-link file at its exact split
path. Immediately after the marker and before new decode/reveal/measurement,
its validated bytes are exclusively sealed at a second exact authority path.
Normal report validators recompute metrics-to-result booleans, diagnostics,
every candidate audit entry, the selected objective, endpoint counts/rates, and
the final status from the persisted manifest, sealed labels, measurements, and
revealed clusters. Later authority loads repeat that recomputation for
calibration. The terminal holdout report is independently read back and rebound
to its actual files, marker, freeze, receipt, runtime/HEAD, sealed labels, and
secret-derived exact identity before success is returned.
If no candidate is admissible, the normal failed report stores a null hard
threshold and binds its endpoint/results snapshot to the final increasing
candidate (the upper sentinel); no frozen-threshold file is written.

The fresh ImageGen v7 locked clean reference is hash-bound in the normative
spec. It was Vision-qualified without numeric metrics and can be evaluated only
after freeze, exactly once, on its exact central 256×192 window. Holdout remains
impossible until that report passes and a preregistered reviewer commits a
hash-bound authority receipt. Receipt assurance is procedural trusted-agent
assurance, not a cryptographic signature or proof of human identity.
At both holdout-control generation and holdout evaluation before its marker, the
current receipt HEAD must still contain byte-identical, spec-hash-matching copies
of the v7 image and all four provenance files. This is provenance I/O only and
does not repeat the locked numeric measurement.

All formal stages run on the same machine and exact runtime fingerprint, which
includes zlib and hashes of the loaded NumPy, SciPy ndimage, and Pillow native
modules. Frozen thresholds bind the calibration Git HEAD; locked validation must
use that exact HEAD, and the later tracked receipt names both captured HEADs.
Preflight may parse and recompute already-consumed authority before the next
stage marker. It never remeasures a prior source image; the new marker still
precedes every new target decode, measurement, reveal, selection, and endpoint
evaluation for its stage.

r4 is a residual-window detector. Direct unmasked evaluation of semantic map
pixels is forbidden; production use needs a new preregistered derivation and an
eligible-background mask.
