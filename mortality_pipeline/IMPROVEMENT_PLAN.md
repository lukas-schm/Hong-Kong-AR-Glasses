# `mortality_pipeline` — critical review & improvement plan

_Reviewed: 2026-06-07. Scope: the holistic intervention→mortality causal-ML pipeline._

> **Status (2026-06-07): P1, P2, P3 and the weekly trajectory are IMPLEMENTED** —
> see `trials.py`, `equipoise.py`, `trajectory.py`, `trial_scoreboard.py`,
> `report_trials.py`, run via `python -m mortality_pipeline.run_trials`.
> **P3 finding:** adding goals-of-care (code status), surgical/elective service and
> informative-missingness indicators (26→33 confounders) improved *overall* balance
> and bias control but did **not** raise identification confidence for
> ventilation/RRT/steroids. Diagnosed cause: their binding constraint is
> **positivity + time-varying confounding**, not missing baseline covariates — e.g.
> ventilation's max weighted-SMD is now driven by `elective_admission` (0.16,
> near-deterministic in the resp-failure cohort) and irreducible indication
> physiology (P/F, resp-rate); RAW-physiology balance was unchanged (0.136→0.136)
> and point estimates barely moved (±0.5pp). ⇒ Lifting them needs **design changes
> (clone-censor-weight / time-updated confounders)** + the credibility layer, not
> more baseline covariates.
>
> **P4 (credibility suite) IMPLEMENTED** — `credibility.py`: permutation-placebo
> (negative-control treatment), random-common-cause & subset refuters,
> negative-control outcome (pressure injury), and RCT-benchmark concordance.
> **P4 finding:** the estimator is *valid* (placebo ≈0, refuters pass, NCO ≈null)
> — the large effects are not numerical artifacts — but where a randomised
> benchmark exists, the observational effect is **RCT-discordant** (RRT +24pp vs
> trial ≈0; steroids +7pp vs trial ≈0/-2) ⇒ residual confounding by indication
> confirmed. Honest ceiling: internal validity achieved, causal magnitude not.
>
> **Time-varying design (sequential target trials) IMPLEMENTED** — `sequential.py`:
> person-time over 6 h decision blocks, **time-updated** (cumulative-to-decision)
> confounders + time-varying co-treatments, pooled doubly-robust initiate-now-vs-defer
> with subject-clustered SEs. **Result — it works:** every effect attenuates 48–84%
> and the RCT-benchmarkable ones move **toward the trial value** (RRT +19→+3 vs ≈0 —
> 84% was confounding; steroids +5.7→+3.0; vasopressors +12→+6; ventilation +12→+5;
> **antibiotics flips to −1.0pp protective**, recovering the early-abx signal). The fix
> the RCT-discordance called for. Residual gap = deferral-arm crossover (ITT); full
> **per-protocol clone-censor-weight with adherence IPCW** is the next refinement.
> **P5 (TMLE + SuperLearner) remains** (precision, not bias).

## Executive verdict

The **engineering and inference machinery are sound** — cross-fit AIPW with
influence-function CIs, IPTW/naive contrasts, overlap/SMD diagnostics, E-values,
a tidy scoreboard and a plain-language JSON. The pipeline correctly *flags* its
own weak cells (RRT, ventilation) as low-confidence.

But the **causal identification is not yet trustworthy**. Three problems mean the
current point estimates are biased by construction, not just noisy:

1. **Treatment-contaminated confounders** — we adjust for severity scores that are
   partly *defined by the treatment*. SOFA-cardiovascular ≥3 occurs in **57% of
   vasopressor patients vs 0% of untreated** (the 3–4 score *is* the pressor
   dose); OASIS-mechvent = **0.91 vs 0.00** ventilated vs not. Conditioning on
   these partials out the very effect we want, and risks collider bias.
2. **No real time-zero / immortal time** — exposure is "received any time during
   the stay" while confounders are first-24 h aggregates. **48% of RRT starts are
   >24 h after admission** (19% >72 h); meanwhile 31–43% of pressor/vent starts
   are <1 h, so "first-day" labs are a mix of pre- and post-treatment values.
3. **Positivity violations** — ATE over the whole ICU when assignment is near
   deterministic: RRT propensity overlap **12%**, weighted SMD **0.72**, IPTW
   blows up to **+27.8 pp**.

These are fixable. The plan below is ordered by **impact on confidence**.
Headline: move from "association adjusted for contaminated severity" to a set of
**per-intervention target-trial emulations** with pre-treatment baselines,
equipoise cohorts, overlap-weighted doubly-robust estimation, negative controls,
RCT benchmarking, and a **weekly counterfactual survival trajectory**.

---

## What is already good (keep)

- Doubly-robust AIPW + cross-fitting + influence-function SE.
- `naive → IPTW → AIPW` presentation that *shows* confounding being removed.
- Overlap / ESS / SMD diagnostics and per-estimate E-values.
- NaN-native gradient boosting (no forced imputation of the nuisances).
- Clean separation: cohort → estimators → scoreboard → report/JSON.
- Self-describing run logs and HUD-ready JSON.

---

## Critical issues, ranked

### SEV-1 — Identification (biases the point estimate itself)

**1A. Confounders are functions of the treatment (mediator/collider adjustment).**
- Evidence: SOFA-cardiovascular≥3 = 57% (treated) vs 0% (untreated); OASIS-mechvent
  0.91 vs 0.00; renal-SOFA/creatinine entangled with the RRT indication.
- Why: conditioning on a consequence of treatment biases the estimate (usually
  toward null) and can open collider paths. SOFA/OASIS/APACHE all embed
  organ-support signals.
- Fix: build a **treatment-decoupled baseline**. (i) Drop score *components* that
  encode organ support (SOFA-cardiovascular for pressors, OASIS/APACHE vent terms
  for ventilation, renal terms for RRT). (ii) Replace composite scores with **raw
  pre-treatment physiology** measured strictly *before the intervention starts*
  (e.g., lowest MAP and highest lactate before first pressor; worst P/F before
  intubation). (iii) Keep treatment-agnostic structure: demographics, comorbidity,
  admission diagnosis, pre-ICU labs.

**1B. Ill-defined time-zero + immortal time.**
- Evidence: RRT 48% start >24 h; pressors/vent mostly <3 h but 8–11% >24 h.
- Why: "ever treated" conditions on survival-to-treatment; first-24 h confounders
  straddle the treatment for early starters and lag it for late starters.
- Fix: **target-trial emulation per intervention** — define t0 (ICU admission or a
  short grace window), confounders strictly in `[t0−w, t0]`, exposure = *initiated
  within the grace window* `[t0, t0+g]`, exclude prevalent users and anyone who
  died/was discharged before t0+g. For interventions with genuinely time-varying
  start (RRT), use a **landmark grid** or **clone-censor-weight** so each "start
  time" is compared against concurrent not-yet-treated controls.

### SEV-2 — Positivity / overlap (the "low confidence" flags)

**2A. Whole-population ATE under near-deterministic assignment.**
- Evidence: RRT overlap 12% / SMD 0.72 / IPTW +27.8; ventilation overlap 25%.
- Fix (biggest single confidence lever for these cells):
  - **Change the estimand to ATO** (Li–Tipton overlap weights) and/or **ATT**.
    Overlap weights target the equipoise population, give *exact* balance on
    weighted means, and bound weights — no blow-ups.
  - **Restrict to clinical-equipoise subcohorts**: RRT among KDIGO stage 2–3 AKI;
    pressors among shock (hypotension/lactate); ventilation among hypoxaemic
    respiratory failure; steroids among septic shock on pressors. This both fixes
    overlap *and* makes the question clinically meaningful.
  - **Trim to common support** and report the trimmed estimand explicitly; report
    ESS and the trimmed N.

### SEV-3 — Unmeasured confounding (modest E-values 1.4–3.4)

- Missing the dominant ICU mortality confounders: **goals-of-care / code status /
  CMO**, frailty/functional status, **admission diagnosis & service**, pre-ICU
  trajectory, hospital/unit practice.
- Fix: add **code-status/CMO** (reuse `antibiotic_pipeline/variables/clinical_intent.py`,
  which already extracts `cmo_at_decision`, DNR/DNI), admission diagnosis category
  (`diagnoses_icd` Elixhauser/CCS or `services`), surgical vs medical, and unit
  fixed effects. Each strong confounder added raises the achievable E-value.

### SEV-4 — Credibility / calibration (prove the estimates, don't just assert)

- No negative controls, no refutation, no external benchmark.
- Fix:
  - **Negative-control outcomes** (reuse `experiments/nco.py`): pick outcomes the
    intervention should not cause; a non-null estimate quantifies residual bias and
    can *debias* (negative-control calibration).
  - **DoWhy refutation** (dowhy is already a dep): placebo treatment, random common
    cause, data subset, add-unobserved-common-cause.
  - **RCT benchmarking** — contextualise each effect against trial evidence:
    steroids in septic shock (ADRENAL null / APROCCHSS benefit → our +2.5 pp harm
    signals residual confounding), vasopressin (VASST/VANISH null), early-vs-late
    RRT (AKIKI/STARRT-AKI null vs ELAIN → our +10.8 pp is confounding by
    indication), early antibiotics (observational benefit → our −1.0 pp is
    directionally plausible). Agreement/with-known-direction is the strongest
    confidence signal we can give a clinician.

### SEV-5 — Estimator robustness

- Single un-tuned HGB learner; AIPW only; IPTW unstable; one cross-fit split.
- Fix: **TMLE** as the headline (bounded, respects [0,1], better finite-sample;
  pairs naturally with the survival extension); **SuperLearner** ensemble for
  nuisances (logistic + HGB + RF + spline) so DR robustness is real; **repeated
  cross-fitting** with median aggregation (kills split randomness); replace raw
  IPTW with **truncated stabilised weights**; positivity-aware weighting.

### SEV-6 — Outcomes, competing risks, multiplicity, missingness

- **In-hospital mortality** is length-biased and competing-risk confounded
  (discharge competes with death). Prefer fixed-horizon mortality; model
  **discharge-alive as a competing risk** (Aalen–Johansen / cause-specific).
- **Multiplicity**: 5×3×3 estimates with no adjustment → add simultaneous CIs or
  FDR for the scoreboard.
- **Informative missingness** (lactate 47%, P/F 61% missing — sicker patients get
  the test). Add **missingness indicators** and test MAR sensitivity; the "max/min
  over 24 h" aggregation is itself post-treatment-contaminated (see 1A/1B).

---

## Prioritized roadmap (ordered by confidence gain per unit effort)

| Phase | Work | Fixes | Confidence impact |
|---|---|---|---|
| **P1. Pre-treatment baselines + time-zero** | Per-intervention t0, confounders strictly pre-treatment, raw physiology, drop organ-support score components, grace-window exposure, exclude prevalent users / pre-t0 deaths | 1A, 1B, part of 6 | **Highest** — removes structural bias |
| **P2. Equipoise cohorts + overlap weighting** | Clinical subcohorts; ATO/ATT estimands; common-support trimming; truncated stabilised weights | 2A | **Highest** for RRT/vent/pressors (turns "low" → "moderate/high") |
| **P3. Stronger adjustment set** | Add code-status/CMO, admission diagnosis/service, unit; missingness indicators | 3, part of 6 | High — raises E-values |
| **P4. Credibility suite** | Negative-control outcomes, DoWhy refuters, RCT benchmark table | 4 | High — *demonstrates* validity |
| **P5. Robust estimation** | TMLE headline + SuperLearner + repeated cross-fit (median) | 5 | Medium — tightens & de-biases |
| **P6. Weekly survival trajectory** | Counterfactual survival curves + weekly RD(t) (see below) | new feature + 6 | **New insight axis** |
| **P7. Reporting** | Competing-risk handling, multiplicity-adjusted simultaneous CIs, trajectory cards in JSON/HUD | 6 | Medium — honesty/clarity |

A "confidence" upgrade should also make the label *earned*: tie `high` to
{pre-treatment baseline ✓, overlap after weighting SMD<0.1 ✓, E-value_CI≥2 ✓,
negative-control null ✓, direction consistent with RCT ✓}.

---

## Weekly survival trajectory (the requested feature)

**Goal:** instead of three independent horizons, estimate the **causal effect of
each intervention on mortality as a function of time**, on a weekly grid
`t ∈ {7,14,21,…,84} days` from t0, so the HUD/monitor can show whether an effect
**grows, attenuates, or reverses** over the patient's trajectory.

**Feasibility (verified):** 100% of the cohort is followable to 365 d (MIMIC dod
coverage), so administrative censoring to 90 d is ≈0 — a weekly grid is clean;
IPCW is a formality at ≤90 d and becomes necessary only if we extend to 6–12 mo.

**Estimand:** counterfactual cumulative-incidence difference and ratio
`RD(t) = P[T≤t | do(A=1)] − P[T≤t | do(A=0)]`, plus survival curves
`S_1(t), S_0(t)`, at each weekly t — with death as the event and **discharge-alive
modelled as a competing risk** (cause-specific / Aalen–Johansen) rather than
naive censoring.

**Method (two tiers):**
- *MVP (reuses current engine):* run the existing cross-fit AIPW at each weekly
  horizon as a binary "died by t" outcome, with **IPCW** for the (small) censoring.
  Yields RD(t) ± influence-function CI per week immediately. Valid here because
  censoring ≈0 to 90 d.
- *Rigorous (target):* one coherent **discrete-time doubly-robust survival**
  model — pooled-logistic weekly hazards for the outcome, propensity for treatment,
  censoring model for IPCW → **survival TMLE / one-step** giving simultaneous
  confidence bands over the whole curve, monotone and bounded.

**Outputs:**
- `trajectory.parquet` — rows: intervention × week × {RD, CI, S1, S0, RR}.
- `monitor_trajectory.json` — per-intervention weekly series for an animated HUD
  card ("week-by-week effect on survival"), synced monitor↔glasses.
- Trajectory plots + a curve panel in the markdown report.

**Insights it unlocks:** early-vs-late harm (e.g., ventilation harmful acutely
then plateauing), delayed benefit (antibiotics), divergence vs convergence of
curves, and which week the effect (if any) becomes/ceases to be significant.

**Reuse:** `antibiotic_pipeline` already has `MORTALITY_TRAJECTORY` (7/14/21/28 d)
and `run_trajectory_models.py` / `trajectory_tlearner.joblib` — extend the grid to
weekly and make it doubly-robust + competing-risk aware.

---

## Concrete module changes (proposed)

```
mortality_pipeline/
  cohort.py            # +per-intervention t0, pre-treatment confounder windows,
                       #  grace-window exposure, prevalent-user/pre-t0 exclusions,
                       #  raw pre-tx physiology, code-status/diagnosis joins, miss-indicators
  equipoise.py    NEW  # clinical subcohort definitions (shock / AKI 2-3 / resp failure / septic shock)
  estimators.py        # +overlap (ATO) & ATT weights, truncated stabilised IPTW,
                       #  TMLE, SuperLearner nuisances, repeated cross-fit (median)
  survival.py     NEW  # weekly counterfactual survival: IPCW + discrete-time DR / survival-TMLE
  trajectory.py   NEW  # run weekly grid → trajectory.parquet + monitor_trajectory.json
  credibility.py  NEW  # negative-control outcomes, DoWhy refuters, RCT benchmark table
  report.py            # +trajectory curves, competing-risk notes, simultaneous CIs,
                       #  earned-confidence rubric
  constants.py         # +WEEKLY_GRID, equipoise defs, per-intervention t0/grace, RCT priors
```

## Acceptance criteria (how we'll know confidence improved)

- Post-weighting **max SMD < 0.1** on the (decoupled) confounders for every
  reported cell; ESS ≥ 25% of N.
- No confounder that is a deterministic function of the treatment remains in the
  adjustment set (audited).
- **Negative-control outcome** estimates centred on null (|RD| within noise);
  residual bias reported and optionally calibrated out.
- **DoWhy refuters** pass (placebo/random-common-cause effects ≈ 0).
- Direction of each headline effect **consistent with RCT evidence**, or the
  discrepancy explicitly explained by remaining confounding.
- Weekly trajectory with valid simultaneous bands for ≥1 equipoise cohort.
```
