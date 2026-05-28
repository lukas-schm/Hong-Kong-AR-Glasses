# Response to reviewer — point-by-point

Target venue: *npj Digital Medicine* (Nature Portfolio).
Revision posture: full pivot from "stewardship effect claim" to "methodological pipeline paper that operationalises causal guardrails in EHR studies", with the mortality result demoted to an illustrative case study.

Below, every numbered concern is acknowledged and addressed. For concerns we cannot fully resolve (notably #1 — unmeasured clinician-intent confounding is fundamentally outside any retrospective EHR study), we say so explicitly and identify the reframing as our principal response. Bibliography numbers refer to the revised manuscript.

---

## Overall reframing

We accept the reviewer's verdict that the manuscript was overstated as a stewardship claim and is substantially stronger as a methodological-pipeline paper. The revised manuscript reframes accordingly:

- **Title**: "A guarded causal-inference pipeline for EHR-derived treatment-policy questions: operationalising causal guardrails, with a worked example in ICU antibiotic continuation."
- **Abstract**: leads with the integrative-pipeline contribution. The mortality result is presented as the worked output of the framework, not as evidence for stewardship.
- **Introduction**: rewritten to motivate the pipeline contribution rather than the stewardship question.
- **Discussion**: organised around what the framework taught us in this case; the cessation effect is presented exploratory-only with the framework's own E-value caveat.
- **Rhetoric**: "survives every probe" is removed throughout; replaced with "internally stable under the evaluated specifications" or "the framework's diagnostic verdicts do not fail."
- The reviewer's exact recommendation phrase ("how to operationalise causal guardrails in EHR studies") is adopted as a recurring motif.

Workstreams that drove the revision are summarised in `paper/CHANGELOG.md`. The locked pre-specification is at `paper/preregistration.yaml`.

---

# Major concerns

## #1. Unmeasured confounding by clinician intent

**Reviewer point.** The cessation decision is entangled with clinician-certainty variables that are not coded in MIMIC-IV (frailty gestalt, palliative trajectory, undocumented improvement, code-status discussions, ID-consult input). The E-value of 1.55 is modest and the result is fragile.

**Response.** We agree. Three structural changes:

1. **Reframing.** The manuscript no longer presents the cessation effect as a stewardship recommendation. It is presented as the worked output of the pipeline, accompanied by the pipeline's own E-value verdict (Discussion: *"What the worked example shows"*).
2. **Additional confounders extracted from MIMIC-IV (WS4).** Four reviewer-flagged variables are now part of the adjustment set: code status at $T_0$ (chartevents itemid 223758), palliative-care consult before $T_0$ (POE), infectious-disease consult before $T_0$ (POE), and source-control procedures before $T_0$ (procedureevents). Code is in `variables/clinical_intent.py`. Patients in comfort-measures-only status at $T_0$ are *excluded* from the cohort rather than adjusted for (they are not eligible for the treatment policy of interest). The full agent-by-agent and itemid-by-itemid documentation is in the supplementary appendix.
3. **Explicit residual-unmeasured register.** The remaining clinician-intent layer (bedside frailty gestalt, undocumented improvement, full goals-of-care reasoning, microbiology certainty) is enumerated in the `unmeasured_confounders` register in `causal_graph.yaml` and feeds the E-value interpretation in the paper.

**Honest residual.** Even with the four additions, the residual unmeasured layer remains material. We do not claim to have solved unmeasured confounding; the manuscript's principal posture is that the framework is designed to render this fragility visible, not to remove it.

## #2. The "stop antibiotics" arm is a different clinical population

**Reviewer point.** Severity-adjusted ATEs of ~3 pp do not rule out residual confounding when the raw mortality gap is ~14 pp and the "stop" arm is often selected by undocumented diagnostic certainty.

**Response.** Three changes:

1. The treatment-arm contrast is reframed (following the reviewer's exact language) as an *"observational contrast of treatment states at 72h"* rather than a *"treatment-policy effect"* (target-trial protocol table, Step 1).
2. The infection-certainty eligibility layer is added (positive culture, infection-source documentation, or qSOFA $\geq 2$ at $T_0$) so that patients later found to have viral / noninfectious disease are not in the cohort by default.
3. CMO-at-$T_0$ patients are excluded (WS4), removing the largest source of "patient no longer believed infected" bias.

**Honest residual.** The Discussion's *"Limitations of the worked example"* section says explicitly that bedside-gestalt frailty and undocumented improvement remain unobserved by design.

## #3. Target trial is incompletely specified

**Reviewer point.** Eligibility refinement, grace period, deviations, censoring, competing risks, sustained-treatment, and time-varying confounding are missing or under-specified.

**Response (WS2).** A full Hernán-style target-trial protocol table is added (Step 1, Table 1) with:

- Infection-certainty eligibility refinement.
- 24h grace period after $T_0$ for arm classification (no-grace and 48h sensitivities reported alongside).
- Sustained-treatment ($\geq 48$h post-$T_0$) re-classification sensitivity.
- Censoring strategy (min($T_0 + 28$d, death, end-of-record)).
- Competing-risk sensitivity: Fine--Gray subdistribution-hazards treating ICU discharge alive as a competing event.
- Time-varying confounding caveat: the static-classification simplification is acknowledged as such; sequential dynamic-regime extension is identified as future work.
- Treatment-state framing per the reviewer's recommendation.

Code hooks: `framing/antibiotic_continuation_sepsis.py` (grace-period and sustained-treatment knobs in the cohort config); `experiments/anchor_sweep.py` (T0-anchor sensitivity at 48h, 72h, 96h, and culture-finalisation time).

## #4. Pairwise propensity decomposition is incoherent

**Reviewer point.** Three separate binary propensities give non-transitive estimates, different covariate supports, and unstable estimands in the sparse de-escalate arm.

**Response (WS5).** A single multinomial Generalized Propensity Score (random-forest classifier on $T \in \{0,1,2\}$) is fit once and used for all three pairwise contrasts, so they are coherent and on the same covariate support. The estimator-benchmark grid (DML, DRLearner, AIPW, IPTW, overlap-weighted IPTW, TMLE, g-computation, propensity matching) is run under that single GPS. Code: `experiments/benchmarks.py`. Manuscript section: *Estimator benchmarking* (new subsection in Application, with a benchmark-forest-plot figure).

## #5. Positivity diagnostic is inadequately conceptualized

**Reviewer point.** A scalar "fraction in [0.05, 0.95]" with an arbitrary clipping threshold is not enough.

**Response (WS6).** Replaced with a multi-diagnostic panel in `experiments/balance_diagnostics.py`:

- Per-arm propensity histograms (parquet for plotting).
- Standardised mean differences (SMD) before and after weighting for every confounder, per contrast (Austin 2009 threshold |SMD| < 0.1).
- Effective sample size (ESS) of the weights.
- Tail-weight diagnostics: max weight and top-5% share.
- Density-overlap plots in covariate space.
- Sensitivity over clipping thresholds {0.01, 0.05, 0.10}.
- Overlap-weighted estimand (ATO; Li, Morgan, Zaslavsky 2018) reported as the *clipping-free* alternative.

Manuscript section: rewritten *Positivity (overlap)* subsection.

## #6. Calibration is not causally informative

**Reviewer point.** Per-arm calibration validates predictive reliability, not identification.

**Response.** Conceded and structurally addressed. The Step-5 section now separates **identification-layer probes** (overlap, E-value, specification-stability null, simulation-based coverage) from **deployment-layer probes** (per-arm calibration, Mahalanobis OOD). The text explicitly states: *"Per-arm calibration validates predictive reliability of risk displays; it does not bear on identification assumptions."* The calibration subsection is retitled *"Per-arm calibration (deployment-layer probe)"*.

## #7. Permutation-label placebo is overinterpreted

**Reviewer point.** Label-shuffle nulls do not test exchangeability or omitted-variable bias.

**Response.** The probe is renamed *"specification-stability null (label-shuffle)"* and the description now reads: *"We do not interpret this probe as a test of exchangeability or of omitted-variable bias; it tests whether the estimator can distinguish structured association in the data from label noise under the chosen specification."*

## #8. No benchmarking against conventional estimators

**Reviewer point.** Why trust DML over IPTW, TMLE, overlap weighting, g-computation, matching, etc.?

**Response (WS5).** Eight estimators are now benchmarked side-by-side under the same multinomial GPS: DML, DRLearner, AIPW, IPTW (stabilised), Overlap-weighted (ATO), TMLE, g-computation, propensity matching (ATT). Implementations are in `experiments/benchmarks.py`. The benchmark forest plot is the new headline figure of the *Estimator benchmarking* subsection. The Discussion now states explicitly that no single estimator dominates and that DML's tighter CIs reflect robustness to nuisance-estimation error, not statistical power (concern #21).

## #9. Lack of external validation

**Reviewer point.** Stewardship is institution-specific; MIMIC-IV results need external replication.

**Response (WS7).** Full eICU-CRD external-validation pipeline added:

- `framing/eicu_framing.py` — parallel cohort builder mapping the eICU schema to the same target-trial protocol.
- `variables/eicu_selection.py` — confounder extraction.
- `run_eicu_pipeline.py` — end-to-end runner.

The eICU replication runs the primary continue-vs-cease analysis and reports a **per-hospital subgroup forest plot** within eICU's 200+ US hospitals — directly addressing the institution-specific stewardship-pattern concern. Measurement-error caveats (orders, not administrations, in `medication`) are documented in the eICU subsection. AmsterdamUMCdb, HiRID, and SICdb are identified as future work.

## #10. The CDSS framing is premature

**Reviewer point.** Presenting individualised counterfactual mortality estimates risks false precision.

**Response (WS9).** The CDSS section is heavily toned down:

- A dedicated Discussion paragraph titled *"The CDSS prototype is not a deployment"* states explicitly that the frontend is a reference implementation, not validated for clinical use, has not undergone prospective evaluation, and should not be interpreted as a stewardship tool.
- The de-escalate arm is suppressed in the rendered CDSS output (calibration probe gates it).
- The continue-vs-cease arm carries the E-value fragility caveat next to every per-patient risk display.

---

# Statistical/methodological concerns

## #11. CI construction insufficiently specified

**Response (WS8).** A dedicated *Statistical pre-specification* subsection now lists per estimator: asymptotic vs bootstrap CI, bootstrap replicates (500), cluster handling (not required after one-stay-per-subject dedup), cross-fit aggregation (median-of-folds), and finite-sample considerations for small arms. See also `preregistration.yaml`.

## #12. "K-fold empirical CI coverage = 100%" is uninterpretable

**Response (WS6).** Conceded. The previous metric is removed and replaced with a *simulation-based coverage* analysis (`experiments/simulation_coverage.py`): a parametric simulation calibrated on the cohort marginals, with a known ground-truth ATE, on which empirical coverage of each estimator's nominal-95% CI is read off. Coverage values are 93–95% across the principal estimators for the primary contrast. Methods description is included.

## #13. Pre-registration absent

**Response (WS8).** A retrospective pre-specification document (`paper/preregistration.yaml`) is now released alongside the manuscript: single primary analysis (continue-vs-cease, 28-day mortality, DML), all other estimators / feature sets / windows / outcomes / contrasts as secondary or sensitivity. Multiple-testing adjustment: Benjamini–Hochberg within the secondary-outcomes family; Bonferroni across the three pairwise contrasts. Acknowledged explicitly as retrospective for this manuscript; future runs of the pipeline use the same locked spec.

## #14. Treatment windows are clinically arbitrary

**Response (WS2).** A dedicated paragraph *"Why $T_0 = 72$h?"* now justifies the choice on Surviving Sepsis Campaign re-evaluation, median time to culture finalisation, and antibiotic-day count. T0-anchor sensitivity is reported at 48h, 72h, 96h, and culture-finalisation time (data-driven). Code: `experiments/anchor_sweep.py`.

## #15. Treatment taxonomy is underspecified

**Response (WS3).** A formal taxonomy YAML (`definitions/treatment_taxonomy.yaml`) is now the single source of truth, versioned with the manuscript. Decisions made explicit: IV vancomycin = broad; oral vanco/metro = C. difficile therapy (excluded from arm classification); antifungals/antivirals flagged but excluded from arm classification; mixed regimens classified as continue with `dual_gram_negative` flag; route changes flagged but do not change arm; short-course peri-operative prophylaxis (≤24h) excluded from arm classification. A supplementary appendix lists every agent observed in the cohort with its taxonomy and prevalence.

---

# Presentation and framing concerns

## #16. Manuscript overstates methodological novelty

**Response.** Conceded. A new Discussion paragraph *"The framework is the contribution"* states explicitly: *"The components in this pipeline are not new — target-trial emulation, DML and benchmark estimators, E-values, balance diagnostics, label-shuffle nulls, and simulation-based coverage all exist in the literature. The contribution is their integration into a single diagnostic-gated workflow..."*

## #17. "Survives every probe" rhetoric

**Response.** Removed throughout. Replaced with "internally stable under the evaluated specifications" or descriptions of which probes the estimate did not fail. Manuscript lint: `grep -nE 'survives every probe' paper/paper.tex` returns nothing.

## #18. "Worked replication template" framing is stronger than the stewardship claim

**Response.** Conceded — and adopted as the principal posture. The reviewer's recommended phrase *"how to operationalise causal guardrails in EHR studies"* is the subtitle / motif of the revised paper.

---

# Minor

## #19. Figure / estimand labelling

**Response.** Every forest-plot row, table cell, and figure caption now carries an estimand annotation: ATE (marginal risk difference), ATT (matched), ATO (overlap-weighted), or CATE (heterogeneous). A methods footnote defines each.

## #20. Missingness indicators may induce collider bias

**Response.** Conceded. A dedicated Methods paragraph (cf. revised *"Informative missingness (F5) and collider caveat"*) acknowledges the bias path and reports a sensitivity analysis in which the same ATE is re-estimated without missingness indicators. Indicators are also explicitly excluded from the de-escalate calibration probe.

## #21. "Orthogonalisation gives statistical power" is imprecise

**Response.** Sentence rewritten: *"...the difference is a function of nuisance-estimation error rather than statistical power per se — orthogonalisation makes the estimator more robust to misspecification of the nuisance models, which on the same data manifests as tighter CIs."*

## #22. Continuous outcome clipping may distort estimands

**Response.** Justification added: bounds are physical (VFD-28 $\in [0, 28]$ by construction). A clipped-vs-unclipped ATE sensitivity is reported per estimator as a footnote; if clipping changes the ATE materially the method (not the data) is the issue.

For the **mortality** outcome family, the post-revision pipeline replaces the single 28-day endpoint with a 4-horizon trajectory (`mortality_7d`/`14d`/`21d`/`28d`; WS11). Multi-horizon binary mortality is the discrete-time analog of a survival outcome and sidesteps the clipping question entirely. The reviewer's `#10` concern (CDSS false precision via formula-interpolated trajectories) is directly addressed: per-horizon causal estimates replace formula-based interpolation; the displayed trajectory is a piecewise-linear connector of 4 discrete estimates with per-horizon CI bars, gated per (arm × horizon) by the calibration probe.

---

# Summary

| Concern | Status |
| --- | --- |
| Reframing (1, 17, 18) | Full pivot to methods paper |
| New confounders (1, 2) | Code status, palliative consult, ID consult, source control (WS4) |
| Target trial spec (3, 14) | Hernán-style protocol table + grace period + sustained-treatment + competing risk + T0 anchors (WS2) |
| Treatment taxonomy (15) | Formal YAML, versioned (WS3) |
| Multinomial GPS + 8 benchmarks (4, 5, 8) | `experiments/benchmarks.py` + new forest plot (WS5) |
| Overlap diagnostic panel (5, 11) | SMD, ESS, tail-weight, density overlap, clipping sweep (WS6) |
| Calibration as deployment probe (6) | Reclassified; section retitled |
| Specification-stability null (7) | Renamed and reframed |
| External validation (9) | eICU-CRD pipeline + per-hospital subgroup (WS7) |
| Pre-registration (13) | Retrospective `preregistration.yaml` (WS8) |
| Simulation-based coverage (12) | `experiments/simulation_coverage.py` (WS6) |
| CDSS tone-down (10) | Dedicated non-deployment paragraph + gating in prototype (WS9) |
| Estimand labelling (19) | On every row / table / caption |
| Missingness collider (20) | Paragraph + sensitivity |
| Orthogonalisation language (21) | Sentence rewritten |
| Outcome clipping (22) | Justified + sensitivity |

Pre-spec, response letter, taxonomy YAML, and updated causal-graph YAML are released alongside the code.
