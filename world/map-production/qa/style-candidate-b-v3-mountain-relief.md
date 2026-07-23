---
type: "analysis"
category: "analysis"
title: "Map Vision QA: style-candidate-b-v3-mountain-relief"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Independent Codex Vision QA"
tags: ["maps", "vision-qa", "image-generation", "quality"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "Candidate B v3 mountain-relief style board"
methodology: "Original-resolution comparison with B v2, immediate-failure gates, and weighted scoring"
findings: []
metrics: {}
ratings: {}
recommendations: []
---

# Map Vision QA: candidate B v3 mountain relief

- Image: `world/map-production/candidates/style-candidate-b-v3-mountain-relief.png`
- Score: **81/100**
- Decision: `rejected`
- Golden threshold: **94/100**

## Result

The concentric mountain targets were removed, but they were replaced by repeated triangular, fan-shaped peaks with dark side hatching. This reintroduces a bird's-eye perspective and fails both the perspective and repetition gates.

The delta channels, island shapes, forests, city details, and field hatching also changed across the image. The next attempt must therefore return to B v2 and use a local binary mountain mask so every pixel outside the intended edit area is reused exactly.
