"""
Holistic causal-ML pipeline: the effect of major ICU interventions on mortality.

Where ``antibiotic_pipeline`` answers one narrow target-trial question
(continue / de-escalate / stop antibiotics in sepsis), this package answers a
*broad* one that fits the CDARS retrieval story:

    "Across the whole ICU population, what is the causal effect of each major
     life-support intervention on mortality, once we adjust for how sick the
     patient was?"

It builds a single adult ICU cohort with a shared baseline confounder set, then
estimates the average treatment effect on mortality for a *panel* of binary
interventions (mechanical ventilation, vasopressors, renal-replacement therapy,
corticosteroids, antibiotics) with doubly-robust causal machine learning. The
result is an "intervention scoreboard" that the model monitor and the glasses
HUD can render in plain language.
"""

from mortality_pipeline.constants import (
    INTERVENTIONS,
    MORTALITY_OUTCOMES,
    CONFOUNDERS,
)

__all__ = ["INTERVENTIONS", "MORTALITY_OUTCOMES", "CONFOUNDERS"]
