# configs/plants/

Declared configuration of the three virtual plants (proposal §6.1). What an operator or
a workflow may know is here; what is hidden (true active volume, true mixing structure,
true per-feed fractionation) is *drawn* from the priors declared here by
`sim.plants.sample_truth(declared, seed)` and lives only in `runs/<id>/truth/` once a run
harness writes it (never in this directory, never in `sim/plants`).

| File | Plant | Anchoring | Reported |
|---|---|---|---|
| `plant_a.yaml` | agricultural co-digestion (cattle slurry + grass silage), 41 °C, 650 m³ | statistics-anchored to Tisocco et al. 2024 / 2026 | outside the factorial; Levels 2–5 at Tier A |
| `plant_b.yaml` | food waste + industrial organic waste + FOG, high nitrogen, 36 °C, 1,836 m³ | dataset-anchored to Muscatine WRRF (with stated caveats) | factorial |
| `plant_c.yaml` | sewage sludge (primary + TWAS), 35 °C, BSM2 3,400 m³ | dataset-anchored to Muscatine WRRF; BSM2 geometry and fractionation | factorial |
| `plant_a_statistics.yaml` | the Plant-A anchor tables and envelopes, with citations | — | — |

Conventions: `ts` is kg TS per kg wet feed (fresh-matter basis), `vs_of_ts` kg VS per kg
TS (dry basis); dissolved species per m³ of wet feed; COD equivalents 1.19 / 1.42 / 2.90
kg COD per kg carbohydrate / protein / lipid (VDI 4630). Gas volumes are reported by the
simulator with their convention. Every design parameter is marked `# DESIGN` with its
source or "assumed" and a reason; the Pydantic contract is `sim/plants/schema.py`.
