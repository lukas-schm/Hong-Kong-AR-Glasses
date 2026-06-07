# Intervention → Mortality: Holistic Causal-ML Scoreboard

Doubly-robust (cross-fit AIPW / double machine learning) estimates of the effect of each major ICU intervention on mortality, on a single MIMIC-IV adult ICU cohort with a shared baseline-severity adjustment set.

- **Cohort**: 85,242 adult first ICU stays
- **In-hospital mortality**: 11.1% · **28-day**: 14.3% · **90-day**: 19.7%
- **Primary outcome**: In-hospital mortality
- **Adjustment set**: SOFA, SAPS-II, OASIS, APACHE-III, first-day vitals & labs, Charlson comorbidity, age, sex, admission type

Effects are reported as a **risk difference in deaths per 100 patients** (positive = more deaths). The naive→IPTW→AIPW progression shows how much of the crude association is confounding by indication. The **E-value** is the minimum strength (risk-ratio scale) an unmeasured confounder would need with both treatment and death to explain the result away.

## Primary outcome (in-hospital mortality)

| Intervention | Naive | IPTW | **AIPW** | 95% CI | RR | E-value (CI) | Confidence | n treat/ctrl |
|---|---:|---:|---:|---|---:|---:|:--:|---:|
| Renal-replacement therapy | +20.67 | +27.79 | **+10.80** | [+9.65, +11.94] | 1.99 | 3.39 (3.17) | low | 4,960/80,282 |
| Invasive mechanical ventilation | +11.99 | +10.03 | **+8.06** | [+7.09, +9.03] | 1.88 | 3.16 (2.94) | low | 31,224/54,018 |
| Vasopressors | +14.11 | +8.09 | **+5.88** | [+5.14, +6.62] | 1.58 | 2.53 (2.38) | moderate | 23,936/61,306 |
| Systemic corticosteroids | +7.30 | +3.36 | **+2.52** | [+2.02, +3.02] | 1.24 | 1.78 (1.67) | moderate | 17,473/67,769 |
| Antibiotics | +6.84 | -1.83 | **-1.00** | [-1.53, -0.46] | 0.92 | 1.4 (1.24) | moderate | 53,504/31,738 |

## Plain-language summary

### Renal-replacement therapy  ·  _low confidence_

After adjusting for how sick patients were, starting dialysis for the kidneys is linked to 10.8 more deaths per 100 similar patients (95% CI 9.7–11.9). The naive comparison suggested +20.7; severity adjustment moved it to +10.8.

> ⚠️ reserved for the most severe acute kidney injury.

### Invasive mechanical ventilation  ·  _low confidence_

After adjusting for how sick patients were, putting the patient on a breathing machine is linked to 8.1 more deaths per 100 similar patients (95% CI 7.1–9.0). The naive comparison suggested +12.0; severity adjustment moved it to +8.1.

> ⚠️ strong confounding by indication — ventilated patients are far sicker.

### Vasopressors  ·  _moderate confidence_

After adjusting for how sick patients were, giving blood-pressure-supporting drugs is linked to 5.9 more deaths per 100 similar patients (95% CI 5.1–6.6). The naive comparison suggested +14.1; severity adjustment moved it to +5.9.

> ⚠️ markers of shock severity drive both treatment and death.

### Systemic corticosteroids  ·  _moderate confidence_

After adjusting for how sick patients were, giving steroid medication is linked to 2.5 more deaths per 100 similar patients (95% CI 2.0–3.0). The naive comparison suggested +7.3; severity adjustment moved it to +2.5.

> ⚠️ prescribed for refractory shock and specific indications.

### Antibiotics  ·  _moderate confidence_

After adjusting for how sick patients were, giving antibiotics is linked to 1.0 fewer deaths per 100 similar patients (95% CI 0.5–1.5). The naive comparison suggested +6.8; severity adjustment moved it to -1.0.

> ⚠️ given to patients with (suspected) infection.

## All horizons (AIPW, deaths per 100)

| Intervention | In-hospital | 28-day | 90-day |
|---|---:|---:|---:|
| Renal-replacement therapy | +10.80 [+9.7,+11.9] | +7.83 [+6.7,+9.0] | +12.30 [+11.2,+13.4] |
| Invasive mechanical ventilation | +8.06 [+7.1,+9.0] | +5.43 [+4.5,+6.4] | +5.77 [+4.7,+6.8] |
| Vasopressors | +5.88 [+5.1,+6.6] | +4.37 [+3.6,+5.1] | +4.83 [+4.0,+5.7] |
| Systemic corticosteroids | +2.52 [+2.0,+3.0] | +2.40 [+1.8,+3.0] | +3.63 [+3.0,+4.3] |
| Antibiotics | -1.00 [-1.5,-0.5] | -1.45 [-2.0,-0.9] | -0.39 [-1.0,+0.2] |

## Method

- **Estimator**: cross-fit AIPW (augmented IPW), the doubly-robust / double-ML estimator of the average treatment effect. Consistent if *either* the propensity model or the outcome model is correct.
- **Nuisance models**: gradient-boosted trees (`HistGradientBoosting`), 5-fold cross-fitting; missing labs handled natively.
- **Inference**: influence-function standard errors → 95% CIs.
- **Diagnostics**: propensity overlap, effective sample size, standardised mean differences before/after weighting, propensity trimming at 2%.
- **Sensitivity**: VanderWeele–Ding E-value per estimate.

### Caveats

These are observational estimates. Baseline confounders are summarised over the first 24 h, which can overlap the start of an intervention; residual and unmeasured confounding (especially confounding by indication for ventilation, vasopressors and RRT) is expected. Treat the scoreboard as a hypothesis-generating comparison, not as evidence of causal harm/benefit on its own — read each effect alongside its E-value and overlap diagnostics.
