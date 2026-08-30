---
type: "analysis"
category: "analysis"
title: "Map Vision QA: style-candidate-b-v2-plan-view"
version: "1.0.0"
created: "2026-07-19"
last_updated: "2026-07-19"
author: "Independent Codex Vision QA"
tags: ["maps", "vision-qa", "image-generation", "quality"]
status: "draft"
analysis_type: "feature-evaluation"
scope: "Candidate B v2 plan-view style board"
methodology: "Original-resolution Vision review, immediate-failure gates, and weighted scoring"
---

# Map Vision QA: candidate B v2 plan view

- Image: `world/map-production/candidates/style-candidate-b-v2-plan-view.png`
- Score: **84/100**
- Decision: `revise`
- Golden threshold: **94/100**

## Result

The requested strict 90-degree plan-view correction succeeded: no mountain face, building facade, island underside, or oblique shadow remains. Candidate B's coastline, river, roads, palette, and quiet overlay corridors are preserved.

The image still fails the immediate repetition gate. Mountain areas repeat concentric rings, center dots, and diamonds as obvious bullseye symbols. Floating-land semantics are weaker than desired, but that is deliberately deferred so the next generation changes one variable only.

## One next change

Replace only the mountain bullseyes with irregular connected ridges, saddles, valleys, nonconcentric contours, and variable hatching. Keep the city, port, floating-island footprints, river, roads, coast, palette, paper grain, and density unchanged.
