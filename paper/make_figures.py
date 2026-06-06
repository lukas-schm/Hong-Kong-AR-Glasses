"""Generate all paper figures from the diagnostic artifacts produced by
the antibiotic_pipeline. Output: paper/figures/*.pdf
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "data" / "diagnostics"
EXP = ROOT / "data" / "experiences" / "antibiotic_continuation_sepsis"
OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# ── Style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.6,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
})
COLOR_BENEFIT = "#1f7a5a"  # green
COLOR_HARM = "#c0392b"     # red
COLOR_NULL = "#6c757d"     # grey
COLOR_ACCENT = "#2e6fb3"   # blue
PAIR_LABELS = {
    (0, 1): "Continue vs De-escalate",
    (0, 2): "Continue vs Stop",
    (1, 2): "De-escalate vs Stop",
}


def _color_for_ci(lb: float, ub: float) -> str:
    if ub < 0:
        return COLOR_BENEFIT
    if lb > 0:
        return COLOR_HARM
    return COLOR_NULL


# ── Figure 1: cohort flowchart ────────────────────────────────────────────────
def fig_cohort_flowchart():
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    steps = [
        ("Sepsis-3, age ≥18,\nICU LOS ≥72 h", 20804),
        ("First broad-spectrum\nantibiotic within 48 h", 11213),
        ("Alive in ICU at 72 h\n(immortal-time removed)", 10206),
        ("One earliest stay\nper subject (F4)", 9331),
    ]
    y_positions = [8.6, 6.7, 4.8, 2.9]
    for (text, n), y in zip(steps, y_positions):
        ax.add_patch(plt.Rectangle((1.4, y - 0.55), 7.2, 1.1,
                                    facecolor="#eef3f8", edgecolor=COLOR_ACCENT, lw=0.8))
        ax.text(2.0, y, text, fontsize=9, va="center")
        ax.text(7.9, y, f"n = {n:,}", fontsize=9.5, va="center", ha="right",
                fontweight="bold", color=COLOR_ACCENT)
    for y1, y2 in zip(y_positions[:-1], y_positions[1:]):
        ax.annotate("", xy=(5, y2 + 0.55), xytext=(5, y1 - 0.55),
                    arrowprops=dict(arrowstyle="->", lw=0.8, color="#444"))
    ax.text(8.5, 1.4, "Final cohort\nn = 9,331", ha="center", fontsize=10,
            fontweight="bold", color=COLOR_ACCENT)
    fig.suptitle("Figure 1.  Cohort selection flow", x=0.5, y=0.995,
                 fontsize=10, fontweight="bold")
    fig.savefig(OUT / "fig1_cohort.pdf")
    plt.close(fig)


# ── Figure 2: framework diagram ───────────────────────────────────────────────
def fig_framework():
    fig, ax = plt.subplots(figsize=(9.5, 2.8))
    ax.set_xlim(0, 55)
    ax.set_ylim(0, 14)
    ax.axis("off")
    boxes = [
        ("Framing", "Step 1",
         "PICO(T):\nSepsis-3, T₀=72 h\n3-arm Tx\n28-day mortality"),
        ("Identification", "Step 2",
         "Confounders\nfrom DAG\n+ missing\nindicators"),
        ("Estimation", "Step 3",
         "DML / DRLearner\nCausalForestDML\nT-Learner\nLogistic y · RF t"),
        ("Vibration", "Step 4",
         "Window sweep\nFeature sweep\nPermutation null\nE-values"),
        ("Validity", "Step 5",
         "Overlap · F7\nCalibration · F12\nOOD · F23\nUI guardrails"),
    ]
    colors = ["#dbe9f6", "#d8f1e3", "#fff2cf", "#fce6cf", "#e5ddee"]
    w = 9.0
    gap = 2.4
    x0 = 0.8
    for i, ((title, kicker, body), c) in enumerate(zip(boxes, colors)):
        x = x0 + i * (w + gap)
        ax.add_patch(plt.Rectangle((x, 1.5), w, 11, facecolor=c, edgecolor="#444", lw=0.7))
        ax.text(x + w / 2, 11.5, kicker, ha="center", fontsize=8.5, color="#666",
                fontstyle="italic")
        ax.text(x + w / 2, 10.0, title, ha="center", fontsize=11, fontweight="bold")
        ax.text(x + w / 2, 5.4, body, ha="center", fontsize=9, va="center")
        if i < len(boxes) - 1:
            ax.annotate("", xy=(x + w + gap - 0.2, 7.0), xytext=(x + w + 0.2, 7.0),
                        arrowprops=dict(arrowstyle="->", lw=1.0))
    fig.suptitle("Figure 2.  Step-by-step framework applied to the antibiotic-continuation question",
                 x=0.5, y=0.99, fontsize=10, fontweight="bold")
    fig.savefig(OUT / "fig2_framework.pdf", bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)


FS_ABBR = {
    "all_confounders": "all",
    "no_infection_markers": "no-infect",
    "no_trajectory": "no-traj",
    "no_treatment_history": "no-tx-hist",
    "severity_and_demographics": "sev+demo",
}
TM_ABBR = {"Random Forest": "RF", "Logistic regression": "LR"}


# ── Figure 3: forest plot of the sensitivity grid ─────────────────────────────
def fig_sensitivity_forest():
    df = pd.read_parquet(EXP / "sensitivity_results.parquet")
    df["ATE_pp"] = df["ATE"] * 100
    df["lb_pp"] = df["ATE lower bound"] * 100
    df["ub_pp"] = df["ATE upper bound"] * 100

    fig, axes = plt.subplots(3, 1, figsize=(7.0, 8.5), sharex=True)
    for ax, (a, b) in zip(axes, [(0, 1), (0, 2), (1, 2)]):
        sub = df[(df["arm_a"] == a) & (df["arm_b"] == b)].copy()
        sub = sub[(sub["lb_pp"] > -25) & (sub["ub_pp"] < 25)]
        sub["label"] = (
            sub["method"]
            + "  ·  " + sub["feature_set"].map(lambda x: FS_ABBR.get(x, x))
            + "  ·  " + sub["treatment_model"].map(lambda x: TM_ABBR.get(x, x))
        )
        sub = sub.sort_values("ATE_pp").reset_index(drop=True)
        y = np.arange(len(sub))
        for i, row in sub.iterrows():
            c = _color_for_ci(row["lb_pp"], row["ub_pp"])
            ax.plot([row["lb_pp"], row["ub_pp"]], [i, i], color=c, lw=1.2)
            ax.plot(row["ATE_pp"], i, "D", color=c, markersize=4)
        ax.axvline(0, color="black", lw=0.5, linestyle="--")
        ax.set_yticks(y)
        ax.set_yticklabels(sub["label"], fontsize=7)
        ax.set_title(f"{PAIR_LABELS[(a, b)]}    (n={len(sub)} fits, "
                     f"CI excludes 0 in {int(((sub['lb_pp']*sub['ub_pp'])>0).sum())})",
                     fontsize=9, fontweight="bold", loc="left")
        ax.set_xlim(-15, 15)
        ax.invert_yaxis()
    axes[-1].set_xlabel("ATE on 28-day mortality (percentage points)")
    fig.suptitle("Figure 3.  Vibration analysis – sensitivity of the ATE to estimator × feature-set × nuisance choice",
                 fontsize=10, fontweight="bold", y=1.00)
    fig.tight_layout()
    fig.savefig(OUT / "fig3_sensitivity_forest.pdf")
    plt.close(fig)


# ── Figure 4: window sweep ────────────────────────────────────────────────────
def fig_window_sweep():
    df = pd.read_parquet(DIAG / "window_sweep.parquet")
    fig, ax = plt.subplots(figsize=(5.6, 2.4))
    rows = []
    for _, r in df.iterrows():
        rows.append((f"w={int(r['window_h'])} h · {PAIR_LABELS[(int(r['arm_a']), int(r['arm_b']))]}",
                     r["ATE_pp"], r["CI_lb_pp"], r["CI_ub_pp"]))
    rows.sort(key=lambda x: (PAIR_LABELS_INV[x[0].split('·')[1].strip()], int(x[0].split('w=')[1].split(' ')[0])))
    y = np.arange(len(rows))
    for i, (lab, ate, lb, ub) in enumerate(rows):
        c = _color_for_ci(lb, ub)
        ax.plot([lb, ub], [i, i], color=c, lw=1.3)
        ax.plot(ate, i, "D", color=c, markersize=4)
    ax.axvline(0, color="black", lw=0.5, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("ATE on 28-day mortality (percentage points)")
    fig.suptitle("Figure 4.  Treatment-classification window sweep (±6 / ±12 / ±24 h)",
                 fontsize=10, fontweight="bold", y=1.00)
    fig.tight_layout()
    fig.savefig(OUT / "fig4_window_sweep.pdf")
    plt.close(fig)


PAIR_LABELS_INV = {v: i for i, (k, v) in enumerate(PAIR_LABELS.items())}


# ── Figure 5: overlap (propensity histograms) ────────────────────────────────
def fig_overlap():
    pairs = [(0, 1), (0, 2), (1, 2)]
    fig, axes = plt.subplots(1, 3, figsize=(7.5, 2.5), sharey=False)
    for ax, (a, b) in zip(axes, pairs):
        summary = json.load(open(DIAG / "overlap" / f"{a}v{b}" / "summary.json"))
        edges = np.array(summary["histogram_edges"])
        bin_centres = (edges[:-1] + edges[1:]) / 2
        width = edges[1] - edges[0]
        ax.bar(bin_centres, summary["histogram_arm_a"], width=width * 0.45, color=COLOR_ACCENT,
               label=f"arm {a} (n={summary['n_a']})", alpha=0.75, align="edge")
        ax.bar(bin_centres + width * 0.45, summary["histogram_arm_b"], width=width * 0.45,
               color="#e57b34", label=f"arm {b} (n={summary['n_b']})", alpha=0.85, align="edge")
        ax.axvspan(0.0, 0.05, color="grey", alpha=0.13)
        ax.axvspan(0.95, 1.0, color="grey", alpha=0.13)
        ax.set_title(f"{PAIR_LABELS[(a, b)]}\noverlap = {summary['overlap_pct']:.1f} %",
                     fontsize=8.5)
        ax.set_xlabel("Estimated propensity (arm b)")
        ax.legend(fontsize=6, frameon=False)
        ax.set_xlim(0, 1)
    axes[0].set_ylabel("Patients per bin")
    fig.suptitle("Figure 5.  Common-support diagnostic – propensity score distributions per arm",
                 fontsize=10, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig5_overlap.pdf")
    plt.close(fig)


# ── Figure 6: calibration per arm ─────────────────────────────────────────────
def fig_calibration():
    fig, axes = plt.subplots(1, 3, figsize=(7.5, 2.5), sharex=True, sharey=True)
    for ax, arm in zip(axes, [0, 1, 2]):
        path = DIAG / "calibration" / f"arm_{arm}" / "summary.json"
        if not path.exists():
            ax.text(0.5, 0.5, "n/a", ha="center", va="center", fontsize=12)
            ax.set_axis_off()
            continue
        summary = json.load(open(path))
        rel = pd.DataFrame(summary["reliability"]).dropna()
        ax.plot([0, 1], [0, 1], "--", color="grey", lw=0.7)
        ax.plot(rel["p_mean"], rel["y_mean"], "o-", color=COLOR_ACCENT, markersize=4, lw=1)
        v = summary["interpretation"]
        verdict_short = "good" if v == "good" else ("moderate" if v == "moderate" else "poor")
        ax.set_title(
            f"Arm {arm}  ({['Continue','De-escalate','Stop'][arm]})\n"
            f"Brier {summary['brier']:.3f}  ·  slope {summary['calibration_slope']:.2f}  ({verdict_short})",
            fontsize=8)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel("Predicted P(death)")
    axes[0].set_ylabel("Observed mortality rate")
    fig.suptitle("Figure 6.  Per-arm calibration of the 28-day mortality model",
                 fontsize=10, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig6_calibration.pdf")
    plt.close(fig)


# ── Figure 7: permutation placebo null distribution ───────────────────────────
def fig_permutation():
    df = pd.read_parquet(DIAG / "nco" / "permutation_placebo.parquet")
    pairs = [(0, 1), (0, 2), (1, 2)]
    fig, axes = plt.subplots(1, 3, figsize=(7.5, 2.5))
    for ax, (a, b) in zip(axes, pairs):
        sub = df[(df["arm_a"] == a) & (df["arm_b"] == b)]
        real = sub[sub["kind"] == "real"].iloc[0]
        perm = sub[sub["kind"] == "permutation"]
        ax.hist(perm["ATE_pp"], bins=8, color="lightgrey", edgecolor="#666")
        ax.axvline(real["ATE_pp"], color=COLOR_HARM, lw=1.5,
                   label=f"Observed  ATE = {real['ATE_pp']:+.2f} pp")
        ax.axvline(0, color="black", lw=0.4, linestyle="--")
        ax.set_title(PAIR_LABELS[(a, b)], fontsize=9)
        ax.set_xlabel("ATE (pp)")
        ax.legend(fontsize=6, frameon=False, loc="upper left")
    axes[0].set_ylabel("Permutations")
    n_perm = int(len(df[df["kind"] == "permutation"]) // 3)
    fig.suptitle(f"Figure 7.  Permutation-label placebo null distribution ({n_perm} shuffles per pair)",
                 fontsize=10, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig7_permutation.pdf")
    plt.close(fig)


# ── Figure 8: E-value summary ─────────────────────────────────────────────────
def fig_evalues():
    df = pd.read_parquet(DIAG / "evalues.parquet")
    df = df[df["method"] == "DML"].copy().reset_index(drop=True)
    df["label"] = df.apply(lambda r: PAIR_LABELS[(int(r["arm_a"]), int(r["arm_b"]))], axis=1)
    fig, ax = plt.subplots(figsize=(6.4, 2.2))
    y = np.arange(len(df))
    h = 0.36
    ax.barh(y + h / 2, df["E_value"], height=h, color=COLOR_ACCENT, alpha=0.85,
            label="E-value (point estimate)")
    ax.barh(y - h / 2, df["E_value_CI"], height=h, color="#e57b34", alpha=0.85,
            label="E-value (CI bound nearest null)")
    ax.set_yticks(y)
    ax.set_yticklabels(df["label"], fontsize=8)
    for i, (ep, ec) in enumerate(zip(df["E_value"], df["E_value_CI"])):
        ax.text(ep + 0.025, i + h / 2, f"{ep:.2f}", va="center", fontsize=7.5)
        ax.text(ec + 0.025, i - h / 2, f"{ec:.2f}", va="center", fontsize=7.5)
    ax.axvline(1.0, color="black", lw=0.6, linestyle="--")
    ax.set_xlabel("E-value (relative-risk scale)")
    ax.set_xlim(0, 1.9)
    ax.legend(fontsize=7, frameon=False, loc="lower right", bbox_to_anchor=(1.0, -0.05))
    fig.suptitle("Figure 8.  E-value sensitivity to unmeasured confounding",
                 fontsize=10, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig8_evalues.pdf")
    plt.close(fig)


def main():
    fig_cohort_flowchart()
    fig_framework()
    fig_sensitivity_forest()
    fig_window_sweep()
    fig_overlap()
    fig_calibration()
    fig_permutation()
    fig_evalues()
    print("Wrote figures to", OUT)


if __name__ == "__main__":
    main()
