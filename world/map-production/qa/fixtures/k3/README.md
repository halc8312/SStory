---
type: "asset"
category: "assets"
title: "K3 Rejected Regression Fixtures"
version: "1.0.0"
created: "2026-07-22"
last_updated: "2026-07-22"
author: "halc8312"
tags: ["map-production", "qa", "fixtures", "regression"]
status: "draft"
document_kind: "readme"
summary: "不採用K3系統の失敗特性を再現する、テスト専用の固定画像一覧です。"
---

# K3 rejected-regression fixtures

The PNG files in this directory are hash-locked, rejected K3 lineage snapshots kept only for deterministic regression tests and fail-closed audit calibration.

They are not approved donors, Golden references, candidate outputs, or promotion authority. Production and ImageGen work must not use them as visual source material.

| Fixture | SHA-256 | Regression role |
| --- | --- | --- |
| `style-candidate-k-v3-semantic-cleanup-proof-v3.png` | `808922469b8e0fd9dafec0c71053867daf60498b60d53b5262c1acbbde2c5fe3` | rejected forest-lineage behavior |
| `style-candidate-k-v3-semantic-cleanup-proof-v10.png` | `d1c835e62ec7e9c2f7f42709aa1600ee42c0ddcc98f02d41daf3a1f1449feb24` | rejected low-frequency field blotch calibration |
| `style-candidate-k-v3-semantic-cleanup-proof-v17.png` | `9e11125b30f4849ee23c3cb4c0a69ab070ff53401b419bc5699529ace8cd573c` | frozen pre-v18 identity regression |
