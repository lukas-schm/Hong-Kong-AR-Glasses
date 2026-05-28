# Model Improvement Plan — Antibiotic Continuation CDSS

Audit of the causal-ML stack in `antibiotic_pipeline/` and `api/inference.py`. Each item lists the **risk**, the **fix**, and the **priority**. Implementation tracker at the bottom.

---

## P1 — Causal-validity (must fix before reporting any ATE)

### F1. Propensity-score clipping is too aggressive
- **Where:** `antibiotic_pipeline/constants.py:172` (`MIN_PS_SCORE = 0.001`); used by `DRLearner` in `experiments/utils.py:193`. API DML in `api/inference.py:253` uses econml default but no clipping at all.
- **Risk:** PS=0.001 means a single "stop antibiotics" patient with a near-zero estimated probability of stopping gets a weight of ~1000, dominating the ATE. With the stop-arm typically <5% of the cohort, this is a near-guarantee of unstable estimates.
- **Fix:** raise `MIN_PS_SCORE` to **0.05**, document the choice, and log `% of rows trimmed` per fit. Reject estimates where >10% are clipped.

### F2. DML outcome model is a linear regressor on a binary outcome
- **Where:** `experiments/utils.py:175,189` and `api/inference.py:242,248` use `RidgeCV` as `model_y` for `mortality_28days ∈ {0,1}`.
- **Risk:** Residuals from a linear fit on a Bernoulli outcome are not well-behaved at the boundary; DML asymptotics assume `model_y` is a reasonable conditional-mean estimator. Logistic regression (or any classifier with `predict_proba` wrapped to return probabilities) is the standard.
- **Fix:** For binary outcomes, route `model_y` through a `LogisticRegression`/`HistGradientBoostingClassifier` adapter (econml accepts regression-style estimators that return probabilities via `predict_proba`). Switch on `outcome_name in BINARY_OUTCOMES`.

### F3. Imputation leaks across cross-fitting folds
- **Where:** `experiments/sensitivity_antibiotic.py:161-163`, `experiments/cate_exploration_antibiotic.py:77-78`, `api/inference.py:179-184` — `SimpleImputer.fit_transform(...)` runs once on the full training set, *then* DML cross-fits.
- **Risk:** Each CV fold's imputer has already seen the held-out fold's medians. Leakage is small in volume but invalidates the orthogonality argument that makes DML doubly-robust.
- **Fix:** Move the imputer **inside** each pipeline (`make_pipeline(SimpleImputer(median), StandardScaler(), estimator)`) so it refits per fold.

### F4. One subject can appear in multiple stays (and arms)
- **Where:** Cohort built in `framing/antibiotic_continuation_sepsis.py` on `(subject_id, hadm_id, stay_id)` — no deduplication.
- **Risk:** Within-subject correlation inflates effective sample size and biases CIs narrow. Also, a patient who was "continue" in stay 1 and "stop" in stay 2 violates SUTVA.
- **Fix:** Keep the **first qualifying stay per `subject_id`** (or implement clustered standard errors via `cluster_groups=subject_id` if econml exposes it; currently does not, so deduplicate). Log how many stays are dropped.

### F5. Median imputation discards clinically informative missingness
- **Where:** All imputation in pipeline + API.
- **Risk:** "PCT not measured" is informative about clinician suspicion; "lactate missing at 72h" suggests clinical stability. Replacing with median erases the signal *and* introduces bias if missingness depends on treatment assignment (MAR-on-A).
- **Fix:** Add missing-indicator columns (`<feature>__missing ∈ {0,1}`) for every numeric feature; document in the causal graph YAML. Audit which indicators have non-trivial coefficients downstream.

### F6. Bootstrap CIs use only 50 replicates
- **Where:** `experiments/utils.py:40`, `experiments/sensitivity_antibiotic.py:173` (`bootstrap_num_samples=20`).
- **Risk:** 20–50 bootstraps give wide Monte Carlo error on the CI endpoints themselves; reproducibility suffers (different seeds yield visibly different "ATE [LB, UB]").
- **Fix:** Default to **500**, with `--quick` flag dropping to 100 for development. Seed RNG explicitly.

---

## P2 — Identification & robustness diagnostics

### F7. No positivity / overlap diagnostics are saved
- **Risk:** Without examining the propensity distribution per arm, we cannot tell whether the "stop" arm even has a comparable population to "continue". This is the **most common cause of bogus ATEs** in observational antibiotic studies.
- **Fix:** Save a `positivity.parquet` per fit with `propensity, treatment_arm, mortality_28d` rows; render a histogram + report `% overlap` (rows in [0.05, 0.95]) per pairwise comparison. Refuse to display ATEs in the UI when overlap < 70%.

### F8. Feature contributions come from a *different* model than the prediction
- **Where:** `api/inference.py:301-339` — UI shows `Ridge` coefficients for "patient feature importance" but the predicted mortality comes from `LogisticRegression`. The two disagree by design.
- **Risk:** Clinicians see "SOFA = +3 pp" attribution that does not actually correspond to the displayed risk. Trust-damaging.
- **Fix:** Compute contributions on the *same* logistic T-Learner (logit decomposition, or `shap.LinearExplainer` after refactoring the pipeline to expose the linear model). Verify `sum(contributions) ≈ logit(predicted) - logit(reference)`.

### F9. Continuous outcomes are unbounded linear regressions
- **Where:** `api/inference.py:223-229` (`RidgeCV` for VFD-28, VaPFD-28, ICU-LOS).
- **Risk:** Predictions can be negative or > 28 days. Currently masked by `max(0, …)` and `max(1, …)` clips in `_predict_continuous`, which silently hides miscalibration.
- **Fix:** Use a Tweedie GLM (`TweedieRegressor(power=1.5)`) or a quantile regressor for VFD/VaPFD; use a Cox PH or right-censored regression for ICU-LOS. Verify predictions are inside clinical bounds without clipping.

### F10. No E-value (sensitivity to unmeasured confounding)
- **Risk:** With only EHR-observed confounders, the question "how strong would an unmeasured confounder need to be to flip the conclusion?" is the single most useful sanity check for an observational causal estimate.
- **Fix:** Compute an E-value (VanderWeele & Ding 2017) for every reported ATE and CI, display alongside the estimate in the UI footnote.

### F11. No negative-control outcome (NCO)
- **Risk:** Treatment-arm classification depends on EHR prescribing patterns. If sicker patients get more aggressive antibiotics *and* more aggressive everything-else, the model attributes outcomes to antibiotics that are caused by the other interventions.
- **Fix:** Pick an outcome that is *not* causally affected by antibiotic strategy at 72h (e.g., 28-day in-hospital fall events). Estimate ATE; expect 0. A non-zero NCO signals residual confounding.

### F12. No calibration evaluation per arm
- **Risk:** A T-Learner can have very different calibration in the rare "stop" arm vs the abundant "continue" arm. Without per-arm Brier/intercept-slope, we cannot trust per-arm absolute risk displays.
- **Fix:** After fitting, compute Brier score, intercept-slope, and a calibration plot per arm; save under `data/diagnostics/calibration/`.

---

## P3 — Data-pipeline correctness

### F13. Treatment-arm classification uses `prescriptions` (orders), not administrations
- **Where:** `framing/antibiotic_continuation_sepsis.py:234` — joins on `prescriptions.parquet`.
- **Risk:** A "continue" order at 60h with a manual stop at 70h would still classify as continue because `stoptime` reflects the *order's* intended end, not actual administration. MIMIC-IV has `emar` (electronic Medication Administration Record) which is the right source.
- **Fix:** Reclassify on `emar` (or `inputevents` for IV antibiotics), keeping `prescriptions` only as a fallback.

### F14. VFD-28, AKI-worsening, secondary-infection are placeholders
- **Where:** `framing/antibiotic_continuation_sepsis.py:311-316`.
- **Risk:** These columns are filled "downstream" — but if the downstream step fails or is skipped, the sensitivity grid silently drops the outcome (it checks `data[outcome].isnull().all()`). User sees "no ATE for VFD-28" without knowing why.
- **Fix:** Move outcome computation entirely into `framing/`; emit explicit error if any required derived table is missing.

### F15. PCT (procalcitonin) is asked for in UI but not used in model
- **Where:** Frontend `types.ts:17` includes `pct`, API `feature_map.py` and `inference.py` do not.
- **Risk:** Clinician adjusts PCT → sees outcomes update (because outcomes are recomputed) → wrongly believes PCT influenced the estimate. Trust hazard.
- **Fix:** Either (a) add PCT to the model if available in MIMIC-IV (`derived/inflammation`, sparse), with missing-indicator from F5; or (b) **remove** PCT from the input UI and document why.

### F16. 28-day mortality loss-to-follow-up
- **Where:** `framing/antibiotic_continuation_sepsis.py:297-301` — uses `patients.dod` only.
- **Risk:** MIMIC-IV `dod` is populated for in-hospital deaths and state death-registry matches; patients lost to follow-up after discharge get coded "alive". Survivorship bias.
- **Fix:** Restrict 28-day mortality denominator to patients whose `discharge_date + 28d` is before the data-extraction cut-off, OR explicitly drop patients discharged <28d before cutoff. Document the censoring rule.

### F17. Decision-window classification is 12h symmetric
- **Where:** `framing/antibiotic_continuation_sepsis.py:228` — `[T0-12h, T0+12h]`.
- **Risk:** A "stop" patient is one with no covered window — but a brief dose-window gap (e.g., 13h between orders) misclassifies them as "stop" when clinically they were continued. Sensitivity to this is unknown.
- **Fix:** Add a sensitivity sweep over `window_h ∈ {6, 12, 24}` and report ATE stability.

---

## P4 — Methodology enrichment (after P1–P3 land)

- **F18:** Add `CausalForest` calibration via honest splitting + per-arm cross-fit (currently fits without orthogonalization in `experiments/utils.py:206-211`).
- **F19:** External validation on **eICU-CRD** (UCSD/Philips ICU database). Re-fit the same pipeline; compare ATEs. Substantial drift signals MIMIC-specific bias.
- **F20:** Add an antibiotic-stewardship secondary outcome: **C. difficile incidence** within 28 days. Currently only `cdiffRisk` is in the UI as a hardcoded placeholder.
- **F21:** Replace the current confidence-band heuristic (`abs_ate > 0.06 and ci_width < 0.06 → high`) with **post-hoc CI calibration** against a held-out fold's empirical coverage.
- **F22:** Implement **dynamic treatment regimes** (Q-learning over the 72h ⇒ Day-5 ⇒ Day-7 decision points) rather than the current single-shot 72h decision.

---

## P5 — UX / safety guardrails

- **F23:** Refuse to render a CATE estimate for a patient whose covariates fall outside the convex hull of training data (compute Mahalanobis distance to the cohort centroid, flag > p99).
- **F24:** Show the **propensity score** of the displayed patient alongside the ATE so clinicians know whether the estimate is interpolation or extrapolation.
- **F25:** Add a "this decision conflicts with guideline X" annotation (Sepsis Surviving Campaign 2021) — purely informational.

---

## Implementation order (this session)

1. **F1** — clip MIN_PS_SCORE to 0.05 (5-line change, big effect). ✅
2. **F2** — Logistic outcome model for mortality in DML (correct ML choice). ✅
3. **F3** — Imputer inside pipeline (prevents leakage, low risk). ✅
4. **F4** — Deduplicate to one stay per subject. ✅
5. **F5** — Missing-indicator columns. ✅
6. **F6** — Bump bootstrap default to 500. ✅
7. **F8** — Use logistic-based contributions to match displayed risk. ✅
8. **F9** — Bound continuous-outcome predictions clinically. ✅
9. **F23** — Out-of-distribution detection in the API (Mahalanobis check). ✅

## Day-3 fixes

16. **F13** — Treatment-arm classification now uses ICU `inputevents`
    (actual administrations) as the primary source, with `prescriptions`
    as a fallback for hadm_ids with no IV record. EMAR-based variant
    was attempted but the local `emar.csv.gz` is corrupted on disk; the
    inputevents approach is medically equivalent for IV antibiotics
    and arguably better-coded (uses `d_items.itemid` rather than
    free-text drug names). ✅
17. **F14** — VFD-28, VaPFD-28, AKI worsening, and secondary infection
    are now filled directly inside framing from `derived/ventilation`,
    `derived/vasoactive_agent`, `derived/kdigo_stages`, and
    `raw/microbiologyevents`. No more silent NaN columns. ✅
18. **F17** — `experiments/window_sweep.py` re-classifies and re-estimates
    for `window_h ∈ {6, 12, 24}`. ✅
19. **F18** — CausalForest now routed through econml's `CausalForestDML`
    with cross-fit nuisances + honest splits, yielding valid inference
    comparable to the DML family. ✅
20. **F20** — `cdiff_28d` outcome added: new oral vancomycin or oral
    metronidazole order in [T0+3d, T0+28d], excluding patients already
    on CDI therapy at T0. Pharma-epi proxy (Bagdasarian et al. 2015). ✅
21. **F21** — `experiments/ci_calibration.py` runs K-fold DML and
    reports empirical 95% CI coverage against the full-sample ATE.
    Produces a calibration deficit factor that can widen displayed CIs. ✅
22. **F24/F25** — UI guardrails: KPI panel renders a red OOD banner
    when the API returns `ood.outOfDistribution=true`, and a yellow
    overlap banner for known low-overlap comparisons
    (Continue↔De-escalate, where empirical overlap is only 17 %). ✅

## Out of scope this session

- **F19** — External validation on eICU-CRD. Requires (a) provisioning
  and de-identifying the eICU dataset, (b) writing a parallel framing
  module that maps eICU's schema to MIMIC-IV's confounder set, and
  (c) refitting/transferring the pipeline. Estimated >1 week of work
  per the original plan; not attempted.
- **F22** — Dynamic treatment regimes (Q-learning over the 72 h → Day 5 →
  Day 7 decision points). This is a fundamental shift from single-shot
  estimation to sequential decision-making; needs a different data
  representation (per-day feature snapshots), a different identification
  argument (sequential ignorability), and a different estimator
  (econml's `DynamicDML` or hand-rolled Q-learning). Substantial method
  redesign, out of scope here.

## Day-2 fixes

10. **F7** — Positivity / overlap diagnostics module. ✅
    → `data/diagnostics/overlap/{0v1,0v2,1v2}/`. Surfaced the
    Continue-vs-De-escalate 17% overlap problem.
11. **F12** — Per-arm calibration evaluation. ✅
    → `data/diagnostics/calibration/arm_{0,1,2}/`. Surfaced the de-escalate
    arm calibration collapse (slope 0.08).
12. **F10** — E-value sensitivity to unmeasured confounding. ✅
    → `data/diagnostics/evalues.parquet`. Continue-vs-Stop E_value 1.55,
    CI-bound 1.3 — modest robustness, easily defeated by a moderate
    unmeasured severity confounder.
13. **F11** — Negative-control / permutation-placebo scaffold. ✅
    → `data/diagnostics/nco/permutation_placebo.parquet`. The `run_nco`
    function is parameterised so a real NCO column can be plugged in
    once derived from MIMIC.
14. **F15** — PCT removed from the editable UI; API payload no longer
    includes it. PCT remains as static clinical context in patient cards
    because clinicians want to see it; it just no longer pretends to
    influence the estimate. ✅
15. **F16** — 28-day mortality follow-up censoring. ✅ Patients whose
    decision time + 28 d exceeds the global `dod_max` are now coded NaN
    rather than "alive" (eliminates survivorship-bias false negatives).

Everything else stays as documented future work for the deadline-day push.
