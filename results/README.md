# ML results — intervention → mortality (target-trial causal ML)

Preserved **aggregate** outputs of the final pipeline run (the per-patient cohorts
are intentionally **not** committed — they are MIMIC-IV-derived patient-level data
under the PhysioNet DUA). The pipeline code lives in `mortality_pipeline/` on the
`main` branch.

## Files
| File | What it is |
|---|---|
| `trial_scoreboard.csv` / `.parquet` | Tidy results: intervention × outcome × cohort (full/equipoise) × method (unadjusted/IPTW/AIPW/ATT/ATO), with CIs, diagnostics (overlap, SMD, ESS), risk ratio, E-value |
| `sequential.json` | Time-varying **sequential target-trial** estimates (initiate-now-vs-defer with time-updated confounders) vs the static estimate and the RCT benchmark |
| `credibility.json` | Falsification suite: placebo/refuters, negative-control outcome, RCT-benchmark concordance, per-intervention verdict |
| `p5_estimator_robustness.json` | AIPW vs TMLE vs TMLE×5 vs TMLE-SuperLearner agreement (estimator robustness) |
| `trajectory.parquet` | Weekly counterfactual survival RD(t) + S₁/S₀ curves (7–84 d) |
| `monitor_trials_scoreboard.json`, `monitor_trajectory.json` | Plain-language HUD/monitor cards (headline, direction, confidence, caveats) |
| `../RESULTS_INTERVENTION_TRIALS.md` | Full human-readable report (every number + method + caveats) |

## Headline findings (in-hospital mortality, deaths per 100; equipoise cohort)
| Intervention | Static AIPW | Sequential (time-updated) | RCT | Identification |
|---|---:|---:|---:|:--:|
| Vasopressors | +13.6 | +6.0 | — (no RCT) | high |
| Ventilation | +14.8 | +5.0 | — (no RCT) | low |
| RRT | +24.2 | **+3.0** | ≈0 | low |
| Corticosteroids | +7.0 | +3.0 | ≈0/−2 | low |
| Antibiotics | +2.7 | **−1.0** | — (no RCT) | high (full cohort) |

**Story:** naive associations are dominated by confounding by indication. The
estimator is valid (placebo ≈0, refuters pass) but the static effects are
RCT-discordant (RRT, steroids) → residual time-varying confounding. The
**sequential design with time-updated confounders removes 48–84 %** of each
effect and moves the RCT-benchmarkable ones toward their trial value (RRT
+19→+3 ≈ trial null; antibiotics flips to protective). Internal validity is
achieved; causal magnitude for the severity-marker treatments is not, absent a
randomised trial. See `RESULTS_INTERVENTION_TRIALS.md` for the full account and
`mortality_pipeline/IMPROVEMENT_PLAN.md` (on `main`) for the methodology roadmap.
