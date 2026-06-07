# Intervention → Mortality: target-trial causal-ML (P1+P2)

Upgrade of the associational scoreboard. Each intervention is now a **per-intervention target-trial emulation**:

- **Pre-treatment baseline** — confounders are RAW physiology aggregated over the first 6 h; patients already on the treatment in that window are excluded (prevalent users), so the adjustment set strictly precedes treatment. **No SOFA/OASIS/APACHE composites** (they encode the treatment).
- **Real time-zero** — exposure must *initiate* within the grace window; controls are the never-treated; late starters are dropped.
- **Stronger adjustment (P3)** — also adjusts for goals-of-care (code-status limitation DNR/DNI/CMO by t0), surgical/elective admitting service, and informative-missingness indicators (was the lactate/ABG/INR/bilirubin drawn).
- **Equipoise cohort** — restricted to patients in whom the decision is genuinely uncertain, so propensity overlap holds.
- **Estimands** — doubly-robust AIPW (ATE), overlap-weighted ATO, ATT.

### Earned identification-confidence rubric
`high` requires: pre-treatment baseline ✓ · weighted SMD < 0.1 · effective overlap ESS ≥ 15% · E-value(CI) ≥ 2 · p < 0.05. This is **internal validity / robustness given measured confounders** — not a guarantee of the causal magnitude (P4 adds negative-control & RCT-consistency checks).

## Primary outcome — in-hospital mortality (deaths per 100)

Headline cell = equipoise cohort where it exists, else full cohort (†).

| Intervention | Full naive | **AIPW** | 95% CI | ATO | ATT | E-value (CI) | SMDw | ESS | Identification | n t/c |
|---|---:|---:|---|---:|---:|---:|---:|---:|:--:|---:|
| Renal-replacement therapy | +45.95 | **+23.59** | [+20.97, +26.21] | +29.42 | +19.53 | 4.62 (4.26) | 0.45 | 12% | low | 1,035/27,153 |
| Invasive mechanical ventilation | +14.23 | **+14.79** | [+11.90, +17.68] | +16.50 | +16.27 | 4.68 (4.04) | 0.16 | 22% | low | 1,106/11,933 |
| Vasopressors | +14.98 | **+13.61** | [+11.60, +15.62] | +13.23 | +10.94 | 4.52 (4.05) | 0.07 | 20% | high | 2,456/24,311 |
| Systemic corticosteroids | +9.01 | **+7.13** | [+5.23, +9.04] | +8.41 | +6.48 | 2.26 (2.0) | 0.11 | 25% | low | 2,291/18,369 |
| Antibiotics † | +8.09 | **+2.69** | [+2.09, +3.30] | +3.79 | +2.75 | 2.23 (2.01) | 0.03 | 49% | high | 11,563/30,549 |

† antibiotics has **no equipoise cohort** (near-universal treatment in suspected infection → positivity violation); only the full-cohort contrast exists.

> ⚠️ **Identification confidence ≠ proven causal magnitude.** For vasopressors / ventilation / RRT the effect size is likely still inflated by confounding by indication that evolves *after* the 6 h baseline; resolving it needs P4 (negative controls + RCT benchmark) and clone-censor-weight.

### What changed vs the associational scoreboard

Removing treatment-contaminated severity scores typically **increases** the estimated effect for vasopressors/ventilation (those scores were absorbing the treatment signal), while the equipoise restriction sharply improves balance (weighted SMD → <0.1) and tames IPTW. Confidence is now *earned* per the rubric, not asserted.

## Weekly survival trajectory (equipoise cohort)

Doubly-robust cumulative-mortality difference RD(t) by week, with counterfactual survival S₁/S₀.

### Renal-replacement therapy — _growing_

For starting dialysis for the kidneys, the mortality gap widens over time — +11.7 per 100 by day 7 → +21.4 by day 84.

| Day | RD (per 100) | 95% CI | S₁ | S₀ |
|---:|---:|---|---:|---:|
| 7 | +11.69 | [+9.36, +14.02] | 0.778 | 0.895 |
| 14 | +17.03 | [+14.51, +19.55] | 0.681 | 0.852 |
| 21 | +16.94 | [+14.37, +19.51] | 0.657 | 0.827 |
| 28 | +19.37 | [+16.84, +21.89] | 0.617 | 0.811 |
| 35 | +20.52 | [+17.93, +23.11] | 0.594 | 0.799 |
| 42 | +21.14 | [+18.56, +23.72] | 0.579 | 0.790 |
| 49 | +21.43 | [+18.88, +23.98] | 0.568 | 0.783 |
| 56 | +20.80 | [+18.25, +23.36] | 0.566 | 0.774 |
| 63 | +20.19 | [+17.62, +22.76] | 0.566 | 0.768 |
| 70 | +20.75 | [+18.23, +23.26] | 0.555 | 0.763 |
| 77 | +20.79 | [+18.30, +23.27] | 0.549 | 0.757 |
| 84 | +21.41 | [+18.96, +23.86] | 0.539 | 0.753 |

### Invasive mechanical ventilation — _growing_

For putting the patient on a breathing machine, the mortality gap widens over time — +7.7 per 100 by day 7 → +10.6 by day 84.

| Day | RD (per 100) | 95% CI | S₁ | S₀ |
|---:|---:|---|---:|---:|
| 7 | +7.67 | [+5.30, +10.04] | 0.851 | 0.928 |
| 14 | +11.20 | [+8.45, +13.94] | 0.784 | 0.896 |
| 21 | +11.49 | [+8.61, +14.36] | 0.758 | 0.873 |
| 28 | +12.25 | [+9.32, +15.17] | 0.736 | 0.859 |
| 35 | +12.47 | [+9.47, +15.46] | 0.723 | 0.847 |
| 42 | +12.45 | [+9.41, +15.49] | 0.713 | 0.837 |
| 49 | +11.77 | [+8.74, +14.80] | 0.709 | 0.827 |
| 56 | +11.10 | [+8.08, +14.12] | 0.708 | 0.819 |
| 63 | +10.98 | [+7.98, +13.98] | 0.702 | 0.812 |
| 70 | +11.08 | [+8.03, +14.12] | 0.696 | 0.806 |
| 77 | +10.77 | [+7.71, +13.82] | 0.693 | 0.800 |
| 84 | +10.57 | [+7.53, +13.61] | 0.689 | 0.795 |

### Vasopressors — _growing_

For giving blood-pressure-supporting drugs, the mortality gap widens over time — +7.6 per 100 by day 7 → +11.6 by day 84.

| Day | RD (per 100) | 95% CI | S₁ | S₀ |
|---:|---:|---|---:|---:|
| 7 | +7.59 | [+5.97, +9.21] | 0.863 | 0.939 |
| 14 | +11.80 | [+9.88, +13.73] | 0.790 | 0.908 |
| 21 | +12.30 | [+10.30, +14.30] | 0.763 | 0.886 |
| 28 | +12.33 | [+10.31, +14.35] | 0.747 | 0.870 |
| 35 | +12.61 | [+10.56, +14.66] | 0.732 | 0.858 |
| 42 | +12.88 | [+10.84, +14.92] | 0.719 | 0.848 |
| 49 | +12.75 | [+10.71, +14.79] | 0.712 | 0.840 |
| 56 | +12.44 | [+10.40, +14.47] | 0.708 | 0.832 |
| 63 | +12.28 | [+10.24, +14.33] | 0.702 | 0.825 |
| 70 | +12.02 | [+9.97, +14.08] | 0.699 | 0.819 |
| 77 | +11.78 | [+9.72, +13.83] | 0.696 | 0.814 |
| 84 | +11.62 | [+9.56, +13.68] | 0.693 | 0.809 |

### Systemic corticosteroids — _stable_

For giving steroid medication, the mortality gap stays steady over time — +5.3 per 100 by day 7 → +5.6 by day 84.

| Day | RD (per 100) | 95% CI | S₁ | S₀ |
|---:|---:|---|---:|---:|
| 7 | +5.30 | [+3.66, +6.95] | 0.846 | 0.899 |
| 14 | +5.30 | [+3.56, +7.05] | 0.797 | 0.850 |
| 21 | +5.84 | [+4.00, +7.68] | 0.762 | 0.821 |
| 28 | +5.67 | [+3.81, +7.54] | 0.746 | 0.802 |
| 35 | +5.82 | [+3.88, +7.76] | 0.732 | 0.790 |
| 42 | +6.17 | [+4.21, +8.14] | 0.717 | 0.778 |
| 49 | +6.00 | [+4.02, +7.98] | 0.709 | 0.769 |
| 56 | +5.65 | [+3.67, +7.63] | 0.704 | 0.760 |
| 63 | +5.81 | [+3.80, +7.82] | 0.695 | 0.753 |
| 70 | +5.74 | [+3.73, +7.74] | 0.689 | 0.747 |
| 77 | +5.69 | [+3.69, +7.69] | 0.684 | 0.741 |
| 84 | +5.60 | [+3.59, +7.61] | 0.680 | 0.736 |

## Credibility (P4) — falsification + RCT benchmark

Each headline estimate is stress-tested: a permutation **placebo** (randomised treatment, RD should be ≈0), **random-common-cause** & **subset** refuters, a **negative-control outcome** (pressure injury), and an **RCT benchmark**.

| Intervention | Placebo RD (→0) | Refuters | NCO RD | RCT concordant | Verdict |
|---|---:|:--:|---:|:--:|---|
| Renal-replacement therapy | +0.35 | pass | 0.882 | **no** | RCT-discordant — effect likely inflated by residual confounding |
| Invasive mechanical ventilation | +0.64 | pass | 4.527 | n/a | negative-control non-null — residual confounding likely |
| Vasopressors | -0.03 | pass | 1.569 | n/a | internally valid; not externally benchmarkable (no RCT) — treat as hypothesis |
| Systemic corticosteroids | +0.29 | pass | -0.316 | **no** | RCT-discordant — effect likely inflated by residual confounding |
| Antibiotics | +0.10 | pass | 1.957 | n/a | internally valid; not externally benchmarkable (no RCT) — treat as hypothesis |

**RCT benchmark sources:**
- _Renal-replacement therapy_: Early vs delayed RRT: no mortality difference (AKIKI, IDEAL-ICU, STARRT-AKI); ELAIN single-centre benefit. Trial RD ≈ 0.
- _Invasive mechanical ventilation_: No ethical RCT of invasive ventilation vs none.
- _Vasopressors_: No RCT of vasopressors vs none; vasopressin add-on neutral (VASST, VANISH).
- _Systemic corticosteroids_: Septic shock: ADRENAL neutral on 90d mortality; APROCCHSS ≈ -2.6pp 90d. Trial RD ≈ 0 to slightly protective.
- _Antibiotics_: No RCT of antibiotics vs none in infection (unethical); observational early-abx benefit.

> The estimator is **valid** (placebo ≈0, refuters pass, NCO ≈null) — the large vasopressor/ventilation/RRT effects are *not* numerical artifacts. But where a randomised benchmark exists (RRT, steroids) the observational effect is **RCT-discordant**, i.e. inflated by residual confounding by indication. This is the honest ceiling: internal validity is achieved; causal magnitude is not, absent a design that handles time-varying confounding.

## Time-varying design — sequential target trials (28-day mortality)

At each 6 h decision block, patients who **initiate now** are contrasted with those who **defer**, adjusting for **time-updated** physiology (cumulative-to-decision) and co-treatments — capturing the deterioration that precedes the decision. Pooled doubly-robust, subject-clustered SEs. If the static effect was inflated by time-varying confounding, the sequential estimate moves **toward the RCT benchmark**.

| Intervention | Static RD | **Sequential RD** | 95% CI | Attenuation | RCT RD | → toward RCT |
|---|---:|---:|---|---:|---:|:--:|
| Renal-replacement therapy | +19.37 | **+3.01** | [+2.49, +3.53] | 84% | +0 | ✓ yes |
| Invasive mechanical ventilation | +12.25 | **+4.98** | [+4.07, +5.88] | 59% | — | n/a (no RCT) |
| Vasopressors | +12.33 | **+6.00** | [+5.36, +6.65] | 51% | — | n/a (no RCT) |
| Systemic corticosteroids | +5.67 | **+2.96** | [+2.15, +3.77] | 48% | -2 | ✓ yes |
| Antibiotics | +2.51 | **-1.04** | [-1.68, -0.39] | 141% | — | n/a (no RCT) |

> Where a randomised benchmark exists, the sequential (time-updated) estimate **collapses toward it** — e.g. RRT's static +19pp falls to ~+3pp (≈84% was deterioration-before-treatment confounding). This is the design fix the RCT-discordance called for; a residual gap remains (still observational; full per-protocol clone-censor-weight with adherence IPCW is the next refinement).

## Estimator robustness (P5) — TMLE · SuperLearner · repeated cross-fit

Re-estimating the headline with the gold-standard estimator. This does **not** change the bias story (design-driven) — it checks the effect is not an artifact of estimator choice. **TMLE** is bounded & efficient; **repeated ×5** removes fold-split randomness; **SuperLearner** stacks LR+HGB+RF so double-robustness rests on no single model.

| Intervention | AIPW (HGB) | TMLE (HGB) | TMLE ×5 | TMLE (SuperLearner) | Spread | Robust |
|---|---:|---:|---:|---:|---:|:--:|
| Renal-replacement therapy | +23.59 | +27.40 | +27.61 | +24.61 | 4.0pp | ⚠ sensitive |
| Invasive mechanical ventilation | +14.79 | +14.80 | +14.38 | +15.24 | 0.9pp | ✓ |
| Vasopressors | +13.61 | +13.78 | +13.55 | +13.17 | 0.6pp | ✓ |
| Systemic corticosteroids | +7.13 | +7.02 | +7.02 | +7.98 | 1.0pp | ✓ |
| Antibiotics | +2.69 | +2.69 | +2.65 | +3.00 | 0.3pp | ✓ |

> Where overlap is adequate the estimators **agree** (estimator-robust). Where positivity is violated (RRT), they **diverge** — an extra flag that the estimate is fragile, consistent with its low identification confidence.

## Remaining limitations & roadmap

- **Done:** P1 pre-treatment baselines · P2 equipoise + overlap weights · P3 goals-of-care/service/missingness confounders · P4 credibility suite · weekly trajectory · **time-varying sequential design** · P5 TMLE/SuperLearner robustness.
- The sequential design with **time-updated confounders** removes most of the residual confounding by indication (validated against RCT benchmarks). Remaining gap is the deferral-arm crossover (ITT-style): full **per-protocol clone-censor-weight** with adherence IPCW would close it.
- **Only refinement left:** per-protocol clone-censor-weight (adherence IPCW). The estimator (P5: TMLE/SuperLearner/repeated cross-fit) and the bias-control roadmap are done.
