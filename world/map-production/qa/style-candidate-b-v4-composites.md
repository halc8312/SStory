---
type: "analysis"
category: "analysis"
title: "Map Vision QA: candidate B v4 masked composites"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Independent Codex Vision QA"
tags: ["maps", "vision-qa", "image-generation", "masking"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "Candidate B attempt-4 masked topography and mask refinement"
methodology: "Original-resolution comparison, immediate-failure gates, and deterministic composite evidence"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# Candidate B v4 masked-composite QA

| Composite | Score | Decision | Main result |
| --- | ---: | --- | --- |
| v4 mask v1 | 76 | rejected | Plan view and geometry exact; hard seams and fingerprint repetition fail |
| v4b mask v2 | 83 | rejected | Seam passes after 64px feather; fingerprint repetition still fails |

The mask refinement changed no ImageGen content. It reduced road protection to 8px and increased inward feathering to 64px. The next generation attempt keeps this mask fixed and changes only the internal relief-line vocabulary.
