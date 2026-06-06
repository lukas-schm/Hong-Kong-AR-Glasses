"""
Sepsis treatment-*timing* causal pipeline ("when to treat").

Companion to ``antibiotic_pipeline`` (which answers a single 72h decision).
This package answers the *longitudinal* question: at each hour since sepsis
onset, what is the causal benefit of *treating now vs waiting*?  The core
deliverable is a **benefit-vs-time curve** per decision (antibiotics, fluids,
vasopressors) that the AR-glasses frontend renders directly.

Design goals (per hackathon scope):
  - Output must be meaningful for visual representation, with data at MULTIPLE
    time points (the landmark grid).
  - Lean by default: analytic (debiased) confidence intervals, a single primary
    estimator, cached panels -> minutes on CPU.
  - Heavy rigor (bootstrap, full estimator grid, NCO, e-values, MSM, GPU, eICU
    external validation) is opt-in via flags, run once for the paper/pitch.

Reuses ``antibiotic_pipeline`` for estimators and diagnostics; only the
timing-specific framing/exposures and the landmark loop are new here.
"""
