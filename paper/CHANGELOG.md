# Manuscript revision changelog

Submission: *npj Digital Medicine*.
Posture: full pivot to a methodological-pipeline paper; the cessation effect is demoted to a worked illustrative example.

This changelog summarises what changed between the original draft and the revised manuscript, organised by workstream (WS1–WS10; see `paper/response_to_reviewer.md` for the point-by-point mapping to reviewer concerns).

---

## WS1 — Reframing and language

- `paper/paper.tex`
  - **Title** rewritten: *"A guarded causal-inference pipeline for EHR-derived treatment-policy questions: operationalising causal guardrails, with a worked example in ICU antibiotic continuation."*
  - **Abstract** rewritten: leads with the integrative-pipeline contribution; demotes the cessation point estimate to an illustrative output.
  - **Author summary** rewritten in the same posture.
  - **Introduction** rewritten as *"operationalising causal guardrails in EHR studies"*.
  - **Step 5** rewritten to separate *identification-layer probes* from *deployment-layer probes*.
  - **Per-arm calibration** retitled *"Per-arm calibration (deployment-layer probe)"* with new framing paragraph.
  - **Permutation placebo** retitled *"Specification-stability null (label-shuffle)"* with new framing paragraph.
  - **Vibration analysis** sentence: orthogonalisation framed as "robustness to nuisance-estimation error" instead of "statistical power."
  - **Results**: title changed to *"Pipeline output and diagnostic verdicts"*; rhetoric of "survives every probe" removed throughout.
  - **Discussion** rewritten:
    - *"What the worked example shows"* (instead of *"Headline claim"*).
    - *"Contrasts the pipeline refuses to render"* (new — instead of *"What we cannot claim"*).
    - *"The framework is the contribution"* (new — disclaims novelty).
    - *"What the pipeline taught us in this case"* (new — methodological lessons + estimator-disagreement note).
    - *"The CDSS prototype is not a deployment"* (new — concern #10).

## WS2 — Target-trial protocol

- `paper/paper.tex`: new Hernán-style *Target-trial protocol* table (Table 1); paragraphs on immortal time, $T_0 = 72$h justification, time-varying confounding caveat, and competing-risk sensitivity.
- `antibiotic_pipeline/framing/antibiotic_continuation_sepsis.py`:
  - `EICU_COHORT_CONFIG` extended with `grace_period_hours`, `sustained_hours`, `require_infection_certainty`, `t0_anchor` knobs.
  - **CMO-at-$T_0$ cohort exclusion** added (Step 3c) before arm classification.
- `antibiotic_pipeline/experiments/anchor_sweep.py` — **new** ($T_0$-anchor sweep at 48h, 72h, 96h, and culture-finalisation time).

## WS3 — Treatment taxonomy

- `antibiotic_pipeline/definitions/treatment_taxonomy.yaml` — **new**. Single source of truth for broad/narrow/antifungal/antiviral/prophylaxis classifications and arm-derivation rules. Documents vancomycin, dual-coverage, oral conversions, short-course prophylaxis, and oral C. difficile therapy decisions explicitly.
- `paper/paper.tex`: new paragraph *Treatment taxonomy — operational definitions*.

## WS4 — Clinical-intent confounders

- `antibiotic_pipeline/variables/clinical_intent.py` — **new**. Extracts code status (chartevents 223758), palliative consult, ID consult, source-control procedures.
- `antibiotic_pipeline/variables/selection.py`: wires `get_clinical_intent_confounders` into the confounder pipeline.
- `antibiotic_pipeline/definitions/causal_graph.yaml`:
  - New `clinical_intent` group with four confounders.
  - Four new entries in `unmeasured_confounders` (bedside frailty gestalt, undocumented improvement, goals-of-care reasoning, microbiology certainty).
- `antibiotic_pipeline/constants.py`: `FEATURES_CLINICAL_INTENT` added to all four `FEATURE_SETS`, plus a new `"Without clinical intent"` ablation feature set.
- `antibiotic_pipeline/definitions/loader.py`: `clinical_intent` group color added to `_GROUP_COLORS`.
- `paper/paper.tex`: new paragraph *Clinical-intent proxies (WS4)*; missingness-collider paragraph rewritten with concern-#20 citation.

## WS5 — Estimator benchmarks

- `antibiotic_pipeline/experiments/benchmarks.py` — **new**. Multinomial GPS + IPTW (stabilised) + Overlap-weighted (ATO) + AIPW + TMLE + g-computation + propensity matching (ATT). All eight estimators share a single multinomial propensity so pairwise contrasts are coherent on the same covariate support.
- `paper/paper.tex`: new *Estimator benchmarking* subsection with a benchmark forest plot and an estimand-annotated results table.

## WS6 — Improved diagnostics

- `antibiotic_pipeline/experiments/balance_diagnostics.py` — **new**. SMD before/after weighting, ESS, tail-weight share, density overlap, and a clipping-threshold sweep (0.01, 0.05, 0.10).
- `antibiotic_pipeline/experiments/simulation_coverage.py` — **new**. Parametric simulation with known ground-truth ATE; replaces the previous "K-fold empirical CI coverage = 100%" claim with simulation-based coverage per estimator.
- `paper/paper.tex`: *Positivity (overlap)* subsection rewritten; *K-fold empirical CI coverage* removed; *Simulation-based coverage* described.

## WS7 — eICU-CRD external validation

- `antibiotic_pipeline/framing/eicu_framing.py` — **new**. Parallel cohort builder.
- `antibiotic_pipeline/variables/eicu_selection.py` — **new**. Confounder extraction for eICU.
- `antibiotic_pipeline/run_eicu_pipeline.py` — **new**. End-to-end eICU runner with per-hospital subgroup analysis (concern #9).
- `paper/paper.tex`: new *External validation on eICU-CRD* subsection.

## WS8 — Statistical specification and pre-registration

- `paper/preregistration.yaml` — **new**. Locked spec: primary contrast, secondary outcomes, sensitivity analyses, multiple-testing adjustment, reporting and reproducibility commitments.
- `paper/paper.tex`: new *Statistical pre-specification* subsection (CI methodology, primary analysis, secondary families with BH/Bonferroni).

## WS9 — CDSS framing tone-down

- `paper/paper.tex`: new Discussion paragraph *"The CDSS prototype is not a deployment"*; the deployment-layer probe section now explicitly gates the de-escalate arm out of the rendered output and attaches the E-value fragility caveat to the per-patient risk display.

## WS11 — Multi-horizon mortality trajectory

- `antibiotic_pipeline/framing/antibiotic_continuation_sepsis.py`:
  derive `mortality_7d`, `mortality_14d`, `mortality_21d` from `dod - decision_time`
  on the same cohort denominator as `mortality_28d` (F16 censoring NaN's all
  four horizons together so the endpoints are like-for-like comparable).
- `antibiotic_pipeline/constants.py`: add the 3 new horizons to `ALL_OUTCOMES`
  and `BINARY_OUTCOMES`; add `MORTALITY_TRAJECTORY` ordered list.
- `antibiotic_pipeline/definitions/causal_graph.yaml`: 3 new outcome entries.
- `antibiotic_pipeline/run_trajectory_models.py` — **new**. Trains a T-Learner
  per (arm, horizon) and runs a **joint** bootstrap (one cohort resample
  applied to all four horizons simultaneously) so the trajectory CI band is
  coherent across horizons. Saves the headline models for the API and the
  bootstrap matrix for the manuscript figure.
- `paper/paper.tex`: new *Multi-horizon mortality trajectory* subsection
  explaining the per-horizon discrete-time T-Learner choice vs Cox/RSF,
  piecewise-linear visualisation, joint bootstrap, per-(arm, horizon) gating.
- `paper/preregistration.yaml`: new `mortality_trajectory_family` block.
  Primary contrast remains mortality_28d; 7/14/21d are descriptive secondary
  endpoints, BH-adjusted within family.

## WS10 — Response artefacts

- `paper/response_to_reviewer.md` — **new**. Point-by-point response to all 22 reviewer concerns.
- `paper/CHANGELOG.md` — **this file**.

---

## Bibliography additions

- Li, Morgan, Zaslavsky 2018 (overlap weighting / ATO).
- Pollard et al. 2018 (eICU-CRD).
- Austin 2009 (SMD as balance diagnostic).
- van der Laan & Rose 2011 (TMLE).
- Groenwold 2020 (informative missingness collider).

## Files touched (code)

```
antibiotic_pipeline/
  constants.py                                      [edit] FEATURES_CLINICAL_INTENT + feature sets
  definitions/
    causal_graph.yaml                               [edit] new confounder group + unmeasured register
    treatment_taxonomy.yaml                         [new]
    loader.py                                       [edit] group color
  framing/
    antibiotic_continuation_sepsis.py               [edit] target-trial knobs + CMO exclusion
    eicu_framing.py                                 [new]
  variables/
    selection.py                                    [edit] wire clinical-intent confounders
    clinical_intent.py                              [new]
    eicu_selection.py                               [new]
  experiments/
    benchmarks.py                                   [new]
    balance_diagnostics.py                          [new]
    simulation_coverage.py                          [new]
    anchor_sweep.py                                 [new]
  run_eicu_pipeline.py                              [new]

paper/
  paper.tex                                         [edit] reframed throughout
  preregistration.yaml                              [new]
  response_to_reviewer.md                           [new]
  CHANGELOG.md                                      [new — this file]
```
