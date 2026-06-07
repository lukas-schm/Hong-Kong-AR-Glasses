"""
Turn the scoreboard into human- and machine-readable outputs:

  * a console table (grouped by intervention),
  * a markdown report (``RESULTS_INTERVENTION_MORTALITY.md``),
  * a plain-language JSON (``monitor_scoreboard.json``) designed to be rendered
    verbatim in the **model monitor** and mirrored on the **glasses HUD** — one
    card per intervention, each with a one-sentence headline a clinician can read.

The language is deliberately associational-under-assumptions ("after adjusting
for baseline severity, X is linked to N more/fewer deaths per 100 similar
patients"), because these are observational estimates with residual
confounding-by-indication — surfaced via the E-value and overlap diagnostics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from mortality_pipeline.constants import (
    DIR2RESULTS_MORTALITY,
    INTERVENTIONS,
    INTERVENTION_KEYS,
    MIN_PS_SCORE,
    MORTALITY_OUTCOMES,
    PRIMARY_OUTCOME,
)

_INTV = {i.key: i for i in INTERVENTIONS}
_OUT = {o.key: o for o in MORTALITY_OUTCOMES}

MONITOR_JSON = DIR2RESULTS_MORTALITY / "monitor_scoreboard.json"
REPORT_MD = Path(__file__).resolve().parents[1] / "RESULTS_INTERVENTION_MORTALITY.md"


# ── classification of an AIPW result ────────────────────────────────────────
def classify_direction(row: pd.Series) -> str:
    if row["ci_low"] > 0:
        return "harm"          # more deaths
    if row["ci_high"] < 0:
        return "benefit"       # fewer deaths
    return "inconclusive"


def classify_confidence(row: pd.Series) -> str:
    """Robustness of the *adjusted* estimate (internal validity), not effect size."""
    clipped = row.get("diag_frac_clipped", 0.0)
    ess = row.get("diag_ess_frac", 1.0)
    smd_w = row.get("diag_max_smd_weighted", 0.0)
    evci = row.get("e_value_ci", 1.0)
    p = row.get("p_value", 1.0)
    if clipped > 0.10 or ess < 0.10 or smd_w > 0.25:
        return "low"           # positivity / residual-imbalance concern
    if evci >= 2.0 and p < 0.05 and smd_w <= 0.15:
        return "high"
    return "moderate"


def _headline(intv_key: str, aipw: pd.Series, naive: pd.Series) -> str:
    plain = _INTV[intv_key].plain
    ate, lo, hi = aipw["ate_pct"], aipw["ci_low"] * 100, aipw["ci_high"] * 100
    direction = classify_direction(aipw)
    if direction == "harm":
        msg = (f"After adjusting for how sick patients were, {plain} is linked to "
               f"{ate:.1f} more deaths per 100 similar patients "
               f"(95% CI {lo:.1f}–{hi:.1f}).")
    elif direction == "benefit":
        msg = (f"After adjusting for how sick patients were, {plain} is linked to "
               f"{abs(ate):.1f} fewer deaths per 100 similar patients "
               f"(95% CI {abs(hi):.1f}–{abs(lo):.1f}).")
    else:
        msg = (f"After adjusting for how sick patients were, {plain} shows no clear "
               f"effect on mortality (95% CI {lo:.1f} to {hi:.1f} per 100).")
    nv = naive["ate_pct"]
    msg += f" The naive comparison suggested {nv:+.1f}; severity adjustment moved it to {ate:+.1f}."
    return msg


# ── cohort summary ──────────────────────────────────────────────────────────
def cohort_summary(cohort: pd.DataFrame) -> Dict:
    out = {"n": int(len(cohort))}
    for o in MORTALITY_OUTCOMES:
        out[o.key + "_pct"] = round(float(np.nanmean(cohort[o.key])) * 100, 1)
    out["exposure_prevalence_pct"] = {
        k: round(float(cohort[k].mean()) * 100, 1) for k in INTERVENTION_KEYS if k in cohort
    }
    return out


# ── JSON for the monitor / glasses HUD ──────────────────────────────────────
def build_monitor_json(board: pd.DataFrame, cohort: pd.DataFrame) -> Dict:
    aipw = board[board["method"] == "aipw"]
    naive = board[board["method"] == "unadjusted"]
    cards: List[Dict] = []

    for key in INTERVENTION_KEYS:
        prim = aipw[(aipw["intervention"] == key) & (aipw["outcome"] == PRIMARY_OUTCOME)]
        if prim.empty:
            continue
        a = prim.iloc[0]
        nv = naive[(naive["intervention"] == key) & (naive["outcome"] == PRIMARY_OUTCOME)].iloc[0]
        direction = classify_direction(a)
        confidence = classify_confidence(a)
        naive_ate, aipw_ate = nv["ate_pct"], a["ate_pct"]
        removed = (1 - abs(aipw_ate) / abs(naive_ate)) * 100 if naive_ate else np.nan

        outcomes = {}
        for o in MORTALITY_OUTCOMES:
            r = aipw[(aipw["intervention"] == key) & (aipw["outcome"] == o.key)]
            if not r.empty:
                rr = r.iloc[0]
                outcomes[o.key] = {
                    "label": o.label,
                    "ate_pp": round(float(rr["ate_pct"]), 2),
                    "ci": [round(float(rr["ci_low"] * 100), 2), round(float(rr["ci_high"] * 100), 2)],
                    "p_value": float(rr["p_value"]),
                    "e_value": _f(rr.get("e_value")),
                    "direction": classify_direction(rr),
                }

        cards.append({
            "key": key,
            "label": _INTV[key].label,
            "plain": _INTV[key].plain,
            "decision": _INTV[key].decision,
            "headline": _headline(key, a, nv),
            "direction": direction,
            "confidence": confidence,
            "ate_pp": round(float(aipw_ate), 2),
            "ci": [round(float(a["ci_low"] * 100), 2), round(float(a["ci_high"] * 100), 2)],
            "risk_ratio": _f(a.get("risk_ratio")),
            "e_value": _f(a.get("e_value")),
            "e_value_ci": _f(a.get("e_value_ci")),
            "naive_ate_pp": round(float(naive_ate), 2),
            "confounding_removed_pct": None if not np.isfinite(removed) else round(float(removed), 0),
            "n_treated": int(a["n_treated"]),
            "n_control": int(a["n_control"]),
            "overlap_frac": round(float(a.get("diag_ps_overlap_frac", np.nan)), 2),
            "balance_smd_weighted": round(float(a.get("diag_max_smd_weighted", np.nan)), 2),
            "caveat": _INTV[key].caveat,
            "outcomes": outcomes,
        })

    # rank by absolute adjusted effect on the primary outcome
    cards.sort(key=lambda c: abs(c["ate_pp"]), reverse=True)
    return {
        "artifact": "intervention_mortality_scoreboard",
        "primary_outcome": PRIMARY_OUTCOME,
        "primary_outcome_label": _OUT[PRIMARY_OUTCOME].label,
        "method": "cross-fit doubly-robust AIPW (double machine learning)",
        "cohort": cohort_summary(cohort),
        "interventions": cards,
        "interpretation_note": (
            "Estimates are observational and adjusted for baseline severity "
            "(SOFA/SAPS-II/OASIS/APACHE-III, vitals, labs, comorbidity, demographics). "
            "They are causal only under no-unmeasured-confounding; the E-value states "
            "how strong an unmeasured confounder would need to be to overturn each result."
        ),
    }


def _f(v):
    try:
        v = float(v)
        return None if not np.isfinite(v) else round(v, 2)
    except (TypeError, ValueError):
        return None


# ── console + markdown ──────────────────────────────────────────────────────
def print_console(board: pd.DataFrame) -> None:
    aipw = board[board["method"] == "aipw"]
    naive = board[board["method"] == "unadjusted"]
    iptw = board[board["method"] == "iptw"]
    print("\n" + "=" * 92)
    print("  INTERVENTION → MORTALITY SCOREBOARD   (risk difference in deaths per 100 patients)")
    print("=" * 92)
    for key in INTERVENTION_KEYS:
        p = aipw[(aipw.intervention == key) & (aipw.outcome == PRIMARY_OUTCOME)]
        if p.empty:
            continue
        a = p.iloc[0]
        nv = naive[(naive.intervention == key) & (naive.outcome == PRIMARY_OUTCOME)].iloc[0]
        iw = iptw[(iptw.intervention == key) & (iptw.outcome == PRIMARY_OUTCOME)].iloc[0]
        arrow = {"harm": "↑", "benefit": "↓", "inconclusive": "≈"}[classify_direction(a)]
        print(f"\n  {_INTV[key].label}  [{classify_confidence(a)} confidence]")
        print(f"    naive {nv['ate_pct']:+6.2f}  →  IPTW {iw['ate_pct']:+6.2f}  →  "
              f"AIPW {arrow} {a['ate_pct']:+6.2f}pp "
              f"[{a['ci_low']*100:+.2f},{a['ci_high']*100:+.2f}]")
        print(f"    RR={_f(a.get('risk_ratio'))}  E-value={_f(a.get('e_value'))} "
              f"(CI {_f(a.get('e_value_ci'))})  |  overlap={a.get('diag_ps_overlap_frac', float('nan')):.0%}"
              f"  weighted-SMD={a.get('diag_max_smd_weighted', float('nan')):.2f}"
              f"  n={int(a['n_treated']):,}/{int(a['n_control']):,}")
    print("\n" + "=" * 92)


def write_markdown(board: pd.DataFrame, cohort: pd.DataFrame, path: Path = REPORT_MD) -> Path:
    aipw = board[board["method"] == "aipw"]
    naive = board[board["method"] == "unadjusted"]
    iptw = board[board["method"] == "iptw"]
    cs = cohort_summary(cohort)

    lines = [
        "# Intervention → Mortality: Holistic Causal-ML Scoreboard",
        "",
        "Doubly-robust (cross-fit AIPW / double machine learning) estimates of the "
        "effect of each major ICU intervention on mortality, on a single MIMIC-IV "
        "adult ICU cohort with a shared baseline-severity adjustment set.",
        "",
        f"- **Cohort**: {cs['n']:,} adult first ICU stays",
        f"- **In-hospital mortality**: {cs['mortality_in_hospital_pct']}% · "
        f"**28-day**: {cs['mortality_28d_pct']}% · **90-day**: {cs['mortality_90d_pct']}%",
        f"- **Primary outcome**: {_OUT[PRIMARY_OUTCOME].label}",
        "- **Adjustment set**: SOFA, SAPS-II, OASIS, APACHE-III, first-day vitals & labs, "
        "Charlson comorbidity, age, sex, admission type",
        "",
        "Effects are reported as a **risk difference in deaths per 100 patients** "
        "(positive = more deaths). The naive→IPTW→AIPW progression shows how much of "
        "the crude association is confounding by indication. The **E-value** is the "
        "minimum strength (risk-ratio scale) an unmeasured confounder would need with "
        "both treatment and death to explain the result away.",
        "",
        "## Primary outcome (in-hospital mortality)",
        "",
        "| Intervention | Naive | IPTW | **AIPW** | 95% CI | RR | E-value (CI) | Confidence | n treat/ctrl |",
        "|---|---:|---:|---:|---|---:|---:|:--:|---:|",
    ]
    ranked = sorted(
        INTERVENTION_KEYS,
        key=lambda k: abs(aipw[(aipw.intervention == k) & (aipw.outcome == PRIMARY_OUTCOME)]["ate_pct"].iloc[0])
        if not aipw[(aipw.intervention == k) & (aipw.outcome == PRIMARY_OUTCOME)].empty else 0,
        reverse=True,
    )
    for key in ranked:
        p = aipw[(aipw.intervention == key) & (aipw.outcome == PRIMARY_OUTCOME)]
        if p.empty:
            continue
        a = p.iloc[0]
        nv = naive[(naive.intervention == key) & (naive.outcome == PRIMARY_OUTCOME)].iloc[0]
        iw = iptw[(iptw.intervention == key) & (iptw.outcome == PRIMARY_OUTCOME)].iloc[0]
        lines.append(
            f"| {_INTV[key].label} | {nv['ate_pct']:+.2f} | {iw['ate_pct']:+.2f} | "
            f"**{a['ate_pct']:+.2f}** | [{a['ci_low']*100:+.2f}, {a['ci_high']*100:+.2f}] | "
            f"{_f(a.get('risk_ratio'))} | {_f(a.get('e_value'))} ({_f(a.get('e_value_ci'))}) | "
            f"{classify_confidence(a)} | {int(a['n_treated']):,}/{int(a['n_control']):,} |"
        )

    lines += ["", "## Plain-language summary", ""]
    cards = build_monitor_json(board, cohort)["interventions"]
    for c in cards:
        lines.append(f"### {c['label']}  ·  _{c['confidence']} confidence_")
        lines.append("")
        lines.append(c["headline"])
        lines.append("")
        if c["caveat"]:
            lines.append(f"> ⚠️ {c['caveat']}.")
            lines.append("")

    lines += [
        "## All horizons (AIPW, deaths per 100)",
        "",
        "| Intervention | In-hospital | 28-day | 90-day |",
        "|---|---:|---:|---:|",
    ]
    for key in ranked:
        cells = []
        for o in MORTALITY_OUTCOMES:
            r = aipw[(aipw.intervention == key) & (aipw.outcome == o.key)]
            if r.empty:
                cells.append("–")
            else:
                rr = r.iloc[0]
                cells.append(f"{rr['ate_pct']:+.2f} [{rr['ci_low']*100:+.1f},{rr['ci_high']*100:+.1f}]")
        lines.append(f"| {_INTV[key].label} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Method",
        "",
        "- **Estimator**: cross-fit AIPW (augmented IPW), the doubly-robust / double-ML "
        "estimator of the average treatment effect. Consistent if *either* the propensity "
        "model or the outcome model is correct.",
        "- **Nuisance models**: gradient-boosted trees (`HistGradientBoosting`), 5-fold "
        "cross-fitting; missing labs handled natively.",
        "- **Inference**: influence-function standard errors → 95% CIs.",
        "- **Diagnostics**: propensity overlap, effective sample size, standardised mean "
        f"differences before/after weighting, propensity trimming at {MIN_PS_SCORE*100:.0f}%.",
        "- **Sensitivity**: VanderWeele–Ding E-value per estimate.",
        "",
        "### Caveats",
        "",
        "These are observational estimates. Baseline confounders are summarised over the "
        "first 24 h, which can overlap the start of an intervention; residual and "
        "unmeasured confounding (especially confounding by indication for ventilation, "
        "vasopressors and RRT) is expected. Treat the scoreboard as a hypothesis-generating "
        "comparison, not as evidence of causal harm/benefit on its own — read each effect "
        "alongside its E-value and overlap diagnostics.",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def save_all(board: pd.DataFrame, cohort: pd.DataFrame) -> Dict[str, Path]:
    DIR2RESULTS_MORTALITY.mkdir(parents=True, exist_ok=True)
    monitor = build_monitor_json(board, cohort)
    MONITOR_JSON.write_text(json.dumps(monitor, indent=2))
    md = write_markdown(board, cohort)
    return {"monitor_json": MONITOR_JSON, "report_md": md}
