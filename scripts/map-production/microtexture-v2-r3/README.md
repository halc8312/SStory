# microtexture-v2-r3 authority

r1 and r2 remain immutable evidence. r3 may execute only from the exact tracked `scripts/map-production/microtexture-v2-r3` location after its authority bytes are committed and equal to the current branch upstream. Copies at any other location fail preflight before mutation.

## Required production order

1. Finalize the authority files at the required `scripts/map-production/microtexture-v2-r3/` location.
2. Rebuild `implementation-bindings.json`, commit, and push every authority file; local HEAD must equal the current branch upstream.
3. Set `MICROTEXTURE_V2_R3_ARTIFACT_ROOT` to the absolute repository path `tmp/map-production/microtexture-v2-r3-artifacts`. Generate 32 cryptographically random bytes, encode them as exactly 64 hexadecimal characters, and provide that same `MICROTEXTURE_V2_R3_BLIND_KEY` for every stage. Never print or persist it. Git subprocesses receive an environment with this variable removed.
4. Generate calibration controls.
5. Root reviews every listed 200% and 400% contact-sheet page and completes every calibration label using `clean`, `warning`, or `reject`.
6. Calibrate and freeze thresholds.
7. Run the locked-positive validation exactly once; it must pass every hard threshold. It is never used to select thresholds and may not be used as production art.
8. An eligible independent reviewer—exactly `Cicero the 2nd` or `Descartes the 2nd` after normalization—fills `threshold-authority.template.json`, including `blind-independent-authority` review mode, a UTC review timestamp after freeze and locked-positive evaluation, and the actual hash bindings. Write it to `world/map-production/qa/microtexture-v2-r3-threshold-authority.json`, commit it, and push it. This is procedural trusted-agent assurance, not a cryptographic signature or proof of identity.
9. From that unchanged captured HEAD, generate holdout controls. Generation rejects any untracked, dirty, unapproved, or mismatched receipt.
10. Root reviews every holdout 200% and 400% sheet and completes every holdout label.
11. Run holdout evaluation exactly once. Hard composite, warning-disposition acceptance of at least 0.75, and every hard per-metric minimum must pass; warning-adoption thresholds remain nonblocking and appear only in `warnings_by_code`. If Root assigns zero warning dispositions, warning acceptance is not applicable, reported as vacuous 1.0 with `warning_acceptance_applicable: false`, and no warning-label quota is imposed.

The preflight rejects any wrong CODE_ROOT, untracked or dirty authority, unpushed HEAD, invalid reviewer receipt, or mismatched hash before an artifact directory, image, marker, manifest, or report can be created.
