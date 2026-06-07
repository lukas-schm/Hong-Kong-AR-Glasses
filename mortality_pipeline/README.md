# `mortality_pipeline` — holistic causal ML: interventions vs. mortality

A **broad** counterpart to `antibiotic_pipeline`. Where that package emulates one
narrow target trial (continue / de-escalate / stop antibiotics in sepsis), this
one answers a *territory-wide-CDARS-style* question across the whole ICU:

> For each major life-support intervention, what is its **causal effect on
> mortality** once we adjust for how sick the patient was at baseline?

It builds **one** adult-ICU cohort with **one** shared baseline-severity
adjustment set, then estimates a doubly-robust average treatment effect for a
**panel** of interventions — so they sit on a single, comparable scoreboard.

## What it compares

| Intervention (binary, vs. not received) | Source |
|---|---|
| Invasive mechanical ventilation | `mimiciv_derived.ventilation` |
| Vasopressors | `mimiciv_derived.vasoactive_agent` |
| Renal-replacement therapy (RRT/CRRT) | `mimiciv_derived.rrt`, `crrt` |
| Systemic corticosteroids | `mimiciv_hosp.prescriptions` |
| Antibiotics | `mimiciv_derived.antibiotic` |

**Outcomes:** in-hospital, 28-day, 90-day mortality (right-censored at registry coverage).

**Shared confounders (first 24 h):** SOFA, SAPS-II, OASIS, APACHE-III, Charlson,
age, sex, admission type, first-day vitals (HR, MAP, RR, temp, SpO₂) and labs
(lactate, creatinine, BUN, WBC, platelets, bilirubin, Hb, INR, Na, K, glucose,
P/F ratio, pH).

## Method (causal, not just predictive)

- **Headline estimator — cross-fit AIPW** (augmented IPW / double machine
  learning). Doubly robust: consistent if *either* the propensity or the outcome
  model is right. Nuisances are gradient-boosted trees (`HistGradientBoosting`,
  NaN-native), 5-fold cross-fitted; CIs from the influence function.
- **Contrast estimators** — naive risk difference and stabilised IPTW (Hájek), so
  every card shows `naive → IPTW → AIPW`: how much crude association was
  confounding by indication.
- **Diagnostics** — propensity overlap, effective sample size, standardised mean
  differences before/after weighting, propensity trimming.
- **Sensitivity** — VanderWeele–Ding **E-value** per estimate (reused from
  `antibiotic_pipeline.experiments.evalues`).
- **Heterogeneity (optional)** — econml `CausalForestDML` CATE: who benefits most.

## Run

```bash
# full run (~few minutes); builds the cohort on first use
python -m mortality_pipeline.run_pipeline

# fast demo on a 20% sample
python -m mortality_pipeline.run_pipeline --fraction 0.2

# rebuild cohort + add a causal-forest CATE for vasopressors
python -m mortality_pipeline.run_pipeline --rebuild-cohort --heterogeneity intv_vasopressors
```

## Outputs

```
data/cohort/intervention_mortality/icu_intervention_cohort.parquet   analysis table
data/results/intervention_mortality/scoreboard.parquet | .csv        tidy results
data/results/intervention_mortality/monitor_scoreboard.json          HUD / monitor cards
data/results/intervention_mortality/cate_<intv>_<outcome>.parquet     (with --heterogeneity)
RESULTS_INTERVENTION_MORTALITY.md                                     human report
```

`monitor_scoreboard.json` is the integration surface for the agentic stack: each
intervention is a card with a one-sentence plain-language `headline`, the adjusted
effect + CI, an `e_value`, a `direction` (harm/benefit/inconclusive) and a
`confidence` (robustness of the adjusted estimate). The **model monitor** renders
these directly and the **glasses HUD** mirrors the same cards — so "every activity
is displayed in easy language" and the two HUDs stay in sync.

## Files

| File | Role |
|---|---|
| `constants.py` | confounder / intervention / outcome definitions, paths |
| `cohort.py` | DuckDB → analysis cohort (confounders, interventions, outcomes) |
| `estimators.py` | cross-fit AIPW, IPTW, unadjusted, diagnostics, E-value |
| `scoreboard.py` | run the panel × outcomes → tidy scoreboard |
| `report.py` | console table, markdown report, monitor/HUD JSON |
| `heterogeneity.py` | optional causal-forest CATE |
| `run_pipeline.py` | CLI orchestration |

## v2 — target-trial design (P1 + P2 + weekly trajectory)

The associational scoreboard above adjusts for *contaminated* severity scores
(SOFA-cardiovascular ≈ vasopressor dose, OASIS-mechvent ≈ ventilation) over a
24 h window that straddles treatment. The **target-trial** path fixes this:

- **Pre-treatment baselines** (`trials.py`) — RAW physiology over the first
  `BASELINE_WINDOW_HOURS` (6 h); prevalent users (treated in that window) excluded
  so confounders strictly precede treatment; **no composite scores**.
- **Real time-zero** — exposure must *initiate* in the grace window; controls are
  never-treated; late starters dropped. Removes immortal-time bias.
- **Equipoise cohorts** (`equipoise.py`) — shock / resp-failure / AKI-2-3 /
  septic-shock / suspected-infection, so propensity overlap holds.
- **Estimands** (`estimators.py`) — doubly-robust AIPW (ATE) + overlap-weighted
  **ATO** + ATT + truncated stabilised IPTW.
- **Weekly survival trajectory** (`trajectory.py`) — `RD(t)` and counterfactual
  survival `S₁/S₀` on a weekly grid (7…84 d) → `monitor_trajectory.json` for an
  animated HUD card.
- **Earned confidence** (`report_trials.py`) — `high` requires pre-treatment
  baseline ✓ + weighted SMD<0.1 + overlap≥25%/ESS≥15% + E-value(CI)≥2 + p<0.05.

```bash
python -m mortality_pipeline.run_trials                 # cohorts + scoreboard + trajectory + report
python -m mortality_pipeline.run_trials --rebuild       # rebuild trial cohorts from DuckDB first
python -m mortality_pipeline.run_trials --weeks 7 14 28 56 84 --interventions intv_rrt
```

Outputs under `data/results/intervention_trials/`: `trial_scoreboard.{parquet,csv}`,
`monitor_trials_scoreboard.json`, `trajectory.parquet`, `monitor_trajectory.json`;
report `RESULTS_INTERVENTION_TRIALS.md`. See `IMPROVEMENT_PLAN.md` for the full
critique and the P3–P5 roadmap (code-status/diagnosis confounders, negative
controls + RCT benchmarking, TMLE/SuperLearner).

## Honest caveats

Observational estimates. Baseline confounders are summarised over the first 24 h,
which can overlap an intervention's start; residual and unmeasured confounding by
indication (notably for ventilation, vasopressors, RRT) is expected and is
exactly why naive effects look large. Read each effect **with** its E-value and
overlap diagnostics — this is a hypothesis-generating comparison, not standalone
evidence of harm or benefit.
