# Antibiotic Continuation CDSS — Headline Results

Single-page summary of the causal-ML estimates produced after the
F1–F16 + F23 fixes documented in `MODEL_IMPROVEMENT_PLAN.md`. All
numbers are 28-day mortality risk differences in percentage points
(negative = the second arm is *safer*).

## Cohort

- Source: MIMIC-IV, sepsis-3 admissions on broad-spectrum antibiotics.
- Target trial: 72 h after first broad-spectrum antibiotic.
- One earliest ICU stay per subject (F4): **n = 9,331**.
- Arm distribution at the 72 h decision: continue 80.7 % · de-escalate
  2.9 % · stop 16.4 %.
- Overall 28-day mortality 27.5 %.

## Robustness diagnostics (all three converge)

| Comparison | Overlap (F7) | Per-arm calibration (F12) | Permutation null (F11) |
|---|---|---|---|
| Continue vs De-escalate | **17.3 %** — POOR | de-esc. slope **0.08** — POOR | \|ATE_real\|=0.45, perm-q95=3.13 — **null** |
| Continue vs Stop | 82.8 % — OK | slopes 0.95 / 0.81 — OK / moderate | \|ATE_real\|=3.76, perm-q95=1.64 — **signal** |
| De-escalate vs Stop | 92.8 % — OK (but n=270 small) | de-esc. slope 0.08 — POOR | \|ATE_real\|=2.79, perm-q95=3.59 — **null** |

## Sensitivity grid summary (58 fits)

Methods × feature sets × pairwise comparisons, mortality_28days only:

| Comparison | n fits | CIs excluding zero | Median ATE (pp) |
|---|---|---|---|
| 0 vs 1 (Continue vs De-escalate) | 22 | **0 / 22** | −0.23 |
| **0 vs 2 (Continue vs Stop)** | **21** | **15 / 21** | **−3.86** |
| 1 vs 2 (De-escalate vs Stop) | 21 | **0 / 21** | −3.38 |

The Continue-vs-Stop result is reproduced across DML, LinearDML and
DRLearner under three feature sets (all confounders, no infection
markers, no trajectory) and under both Random-Forest and Logistic
nuisance models. CausalForest and TLearner produce wider CIs that
include zero — expected with small effective sample size for those
methods.

## E-value (F10)

For the headline Continue-vs-Stop result:

- Risk-ratio scale: **0.87**
- **E_value: 1.55** (point estimate)
- **E_value_CI: 1.30** (CI bound closest to null)

An unmeasured confounder would need to be associated with both
treatment and mortality at relative risks of ~1.3 to fully explain
this away. That's a *modest* bar — clinically plausible severity
confounders (e.g., bedside-gestalt severity, frailty) can easily
exceed it. The estimate is suggestive, not robust.

## Bottom line

1. **The only defensible causal claim from this MIMIC cohort is that
   stopping antibiotics at 72 h is associated with ~3–4 pp lower
   28-day mortality than continuing broad-spectrum, after
   confounder adjustment.** The CI is consistently strictly below
   zero across the DML family; the permutation placebo confirms the
   signal exceeds shuffled-label noise.
2. **No reliable conclusion can be drawn for the de-escalate arm.**
   The arm has only 270 patients, 17 % overlap with Continue, and
   per-arm calibration is essentially random (slope 0.08).
3. **The E_value of 1.55 is modest** — readers should treat the
   Continue-vs-Stop result as hypothesis-generating, not
   confirmatory. A randomized stewardship trial remains required.

## Files of record

```
data/cohort/antibiotic_continuation_sepsis/
  target_population.parquet     (n=9,331 with F4 dedup, F16 censoring)
  confounders.parquet           (49 cols incl. 18 __missing indicators)

data/diagnostics/
  overlap/{0v1,0v2,1v2}/        (F7)
  calibration/arm_{0,1,2}/      (F12)
  evalues.parquet, evalues.json (F10)
  nco/permutation_placebo.parquet, permutation_summary.json (F11)
  diagnostics_summary.json

data/experiences/antibiotic_continuation_sepsis/
  sensitivity_results.parquet   (58 fits, F1–F6 applied)
  _validation/validation_results.parquet  (6 fits, fast smoke test)
  <per-fit directories>/logs/   (resume-friendly per-fit parquet logs)
```
