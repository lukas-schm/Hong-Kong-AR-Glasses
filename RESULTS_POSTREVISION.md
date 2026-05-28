# Post-revision results — first execution pass

Date: 2026-05-21. Run on the post-WS4 cohort (n=9,314 after CMO-at-T₀ exclusion).

## Cohort

| Step | n |
| --- | --- |
| Sepsis-3, adult, ICU LOS ≥ 72h | 17,407 |
| First broad-spectrum abx ≤ 48h of ICU admission | 10,216 |
| Alive in ICU at T₀ (immortal-time bias removed) | 9,331 |
| One stay per subject | 9,331 |
| **NOT in CMO at T₀ (WS4)** | **9,314** |
| Treatment arms (continue / de-esc / stop) | 7,368 / 429 / 1,517 |

28-day mortality overall = 27.4%.

## New clinical-intent confounders

| Variable | Prevalence | Continue | De-escalate | Cease | Interpretation |
| --- | --- | --- | --- | --- | --- |
| `id_consult_pre_T0` | 10.4% | 11.1% | 15.6% | 5.2% | ID consult drives continuation / de-escalation, not cessation. |
| `source_control_pre_T0` | 4.4% | 4.8% | 6.1% | 1.7% | Documented source control → continuation. |
| `palliative_transition_pre_T0` | 3.9% | – | – | – | Modest baseline rate. |
| `code_status_*` (one-hot) | 47.9% documented | – | – | – | DNR/DNI variants 5.2% overall. |

All four signals point in clinically sensible directions; the directional confounding is strongest for ID-consult and source-control.

## Headline DML estimate (sensitivity grid, partial)

Three DML fits completed before the runner was killed (the full 420-fit grid is impractical at ~8 min/fit; the manuscript narrative does not need the full grid). All on `feature_set=all_confounders`, `outcome=mortality_28d`, bootstrap CIs:

| Contrast | ATE (pp) | 95% CI | CI excludes 0? |
| --- | --- | --- | --- |
| Continue vs De-escalate (0v1) | −0.50 | [−4.52, +3.51] | No |
| **Continue vs Cease (0v2)** | **−4.46** | **[−6.60, −2.31]** | **Yes** |
| De-escalate vs Cease (1v2) | −4.41 | [−8.64, −0.18] | Just |

The cease-vs-continue effect *strengthened* slightly with the new clinical-intent confounders (was −3.86pp pre-WS4) — the adjustments did not eliminate the signal.

## Eight-estimator benchmark grid (WS5) — `data/diagnostics/benchmark_grid.parquet`

200 bootstrap reps, multinomial GPS, single propensity model across all three contrasts.

### Continue vs Cease (0v2) — the headline contrast

| Estimator | Estimand | ATE (pp) | 95% CI | n_a / n_b |
| --- | --- | --- | --- | --- |
| IPTW (stabilised) | ATE | **−8.45** | [−10.75, −6.21] | 7368 / 1517 |
| Overlap-weighted | ATO | **−6.39** | [−8.60, −4.45] | 7368 / 1517 |
| AIPW | ATE | **−4.02** | [−5.27, −2.59] | 7368 / 1517 |
| G-computation | ATE | **−4.27** | [−4.51, −4.04] | 7368 / 1517 |
| TMLE | ATE | **−3.63** | [−6.92, +0.43] | 7368 / 1517 |
| PS matching | ATT | **+1.45** | [−2.29, +3.89] | 7368 / 1517 |

**The estimators do not agree.** Doubly-robust methods (AIPW, G-computation, TMLE, DML) cluster around −4pp; pure weighting (IPTW, Overlap) overshoots to −6 to −8pp; **the matched ATT is essentially zero**. This is exactly the kind of cross-estimator divergence the reviewer wanted to see — the headline "−3 to −4pp" claim is *not* estimator-invariant, and the matching ATT in particular suggests the effect is being driven by a non-overlap region.

### Continue vs De-escalate (0v1) — gated

Estimators disagree on **sign**: IPTW/Overlap negative, AIPW/G-comp/TMLE positive (+3.4 to +3.6pp), matching ATT +10pp. The pipeline's pre-existing decision to suppress this contrast is fully validated by the benchmark grid.

### De-escalate vs Cease (1v2) — gated

Most estimators agree at ~−5pp; matching ATT is +9pp. Same pattern.

## Balance diagnostics (WS5/WS6) — `data/diagnostics/balance/`

% of confounders with |SMD| < 0.1 *after* IPTW weighting (Austin 2009 threshold):

| Contrast | % balanced | ESS / n | Max weight | Top-5% weight share |
| --- | --- | --- | --- | --- |
| 0v1 | 44.4% | 7685 / 7797 (99%) | 1.17 | 5.5% |
| **0v2** | **33.3%** | **8341 / 8885 (94%)** | **3.11** | **8.2%** |
| 1v2 | 50.0% | 1876 / 1946 (96%) | 1.82 | 7.0% |

Substantial residual imbalance even after weighting on the headline contrast (only 1/3 of confounders pass the Austin threshold), reinforcing the framework's E-value verdict that the cessation point estimate should be treated as exploratory.

## Simulation-based coverage (WS6) — `data/diagnostics/simulation_coverage.parquet`

Parametric simulation: N=2000, 100 sims, known true ATE τ=−4pp. Bootstrap CIs (150 reps):

| Estimator | Coverage of nominal 95% CI | Mean point (pp) | Mean CI width (pp) |
| --- | --- | --- | --- |
| **TMLE** | **100%** | **−3.86** | 17.4 (wide) |
| **Overlap-weighted** | **91%** | **−5.56** | 10.7 |
| **AIPW** | **84%** | **−3.91** | 8.1 |
| IPTW | 74% | −7.14 | 11.1 |
| G-computation | 10% (under-covers) | −3.95 | 0.7 (too narrow) |

- AIPW and TMLE recover the true effect (−4pp) most accurately.
- IPTW/Overlap point estimates are biased away from the truth (the headline IPTW result of −8.45pp on the real cohort is likely partly this bias).
- G-computation's bootstrap CI is too narrow because it doesn't capture nuisance-estimation variance.

This is a useful pre-emptive answer to reviewer concern #11/#12 (CI methodology + empirical coverage interpretation): the manuscript can now report which estimators are well-calibrated and which are not, on data that matches the cohort's scale.

## Files produced

```
data/diagnostics/benchmark_grid.parquet           # WS5 — 8 estimators × 3 contrasts
data/diagnostics/balance/
  propensity_panel.parquet                        # per-row e_hat per contrast
  smd_table.parquet                               # SMD before/after weighting × clip
  ess_tail.parquet                                # ESS, max_w, top-5% share × clip
  summary.parquet                                 # % balanced per contrast
data/diagnostics/simulation_coverage.parquet      # WS6 — coverage by estimator
data/diagnostics/simulation_coverage.summary.parquet
data/experiences/antibiotic_continuation_sepsis/  # partial DML fits resumeable
```

## Pending

- **Resume the sensitivity grid** for the four remaining feature sets × 5 estimators × 3 contrasts on the mortality outcome. At ~8 min/fit this is ~8 hours; can be left to run overnight via `python -m antibiotic_pipeline.run_pipeline --steps 5` (auto-resume picks up the 3 completed fits).
- Re-run window sweep (`experiments/window_sweep.py`) and anchor sweep (`experiments/anchor_sweep.py`) on the new cohort.
- Run `experiments/nco.py` (negative-control outcome) and `experiments/evalues.py` to refresh those diagnostics.
- Re-render manuscript figures from the new diagnostics.
- Eight-estimator benchmark on eICU once the data is mounted.

## Update for the manuscript

The benchmark grid is the most important new finding for the revision: **the matched-ATT estimate (+1.45pp) materially disagrees with the DML/AIPW/IPTW estimates (−4 to −8pp)**. The manuscript's Discussion paragraph *"What the pipeline taught us in this case"* should be updated:

- Previous claim: *"DML, AIPW, TMLE, and overlap-weighted IPTW agree on the continue-vs-cease point estimate within ∼0.5 pp; the matching ATT (a different estimand) is roughly 1 pp larger, in the expected direction."*
- Honest revision: *"Doubly-robust estimators (DML, AIPW, TMLE, g-computation) cluster around −4 pp on the continue-vs-cease contrast. Pure-weighting estimators (IPTW, overlap-weighted ATO) report a larger effect (−6 to −8 pp). The propensity-matched ATT, by contrast, is essentially zero (+1.45 pp [−2.29, +3.89]) — the effect, on the matched subpopulation that achieves adequate overlap, does not survive. This estimator-to-estimator divergence is itself a robustness diagnostic and a substantively important caveat: the doubly-robust ATEs and the matched ATT are estimating different estimands on different subpopulations, and the gap is large enough to argue that the headline number does not generalise straightforwardly across the cohort."*
