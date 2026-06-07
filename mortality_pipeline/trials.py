"""
P1 — per-intervention **target-trial emulation** with pre-treatment baselines.

Fixes the two identification flaws of the associational scoreboard:

  * **No treatment-contaminated confounders.** Baseline severity is built from
    RAW physiology aggregated over a short pre-exposure window
    ``[icu_intime, icu_intime + BASELINE_WINDOW_HOURS]`` — never SOFA/OASIS/APACHE
    composites that embed organ support.
  * **A real time-zero.** Exposure must *initiate* in the window
    ``(baseline, grace]``. Patients already on the treatment during the baseline
    window are **prevalent users** and excluded, so confounders strictly precede
    treatment for everyone retained. Controls are the never-treated; ambiguous
    late starters (after the grace window) are dropped.

t0 (the analysis clock for survival/trajectory) is the end of the baseline
window. One tidy table per intervention is written under ``DIR2TRIALS``.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    BASELINE_WINDOW_HOURS,
    CODE_STATUS_ITEMID,
    CODE_STATUS_LIMITED_VALUES,
    DIR2TRIALS,
    DUCKDB_PATH,
    ELECTIVE_ADMISSION_TYPES,
    MIN_AGE,
    P3_CONFOUNDER_KEYS,
    RAW_CONFOUNDERS,
    RAW_CONFOUNDER_KEYS,
    SURGICAL_SERVICES,
    TRIALS,
    TrialConfig,
)

# Exposure-onset extractors: stay-level first initiation time of each treatment.
_START_SQL: Dict[str, str] = {
    "vasoactive": """
        SELECT stay_id, min(starttime) AS t0_treat
        FROM mimiciv_derived.vasoactive_agent
        WHERE greatest(coalesce(norepinephrine,0),coalesce(epinephrine,0),
              coalesce(dopamine,0),coalesce(phenylephrine,0),coalesce(vasopressin,0))>0
        GROUP BY 1""",
    "invasive_vent": """
        SELECT stay_id, min(starttime) AS t0_treat
        FROM mimiciv_derived.ventilation
        WHERE ventilation_status IN ('InvasiveVent','Tracheostomy')
        GROUP BY 1""",
    "rrt": """
        SELECT stay_id, min(t) AS t0_treat FROM (
            SELECT stay_id, min(charttime) t FROM mimiciv_derived.rrt
              WHERE dialysis_active=1 GROUP BY 1
            UNION ALL
            SELECT stay_id, min(charttime) t FROM mimiciv_derived.crrt GROUP BY 1
        ) GROUP BY 1""",
    "antibiotic": """
        SELECT stay_id, min(starttime) AS t0_treat
        FROM mimiciv_derived.antibiotic WHERE stay_id IS NOT NULL GROUP BY 1""",
}

_STEROID_RX = r"hydrocortisone|methylprednisolone|dexamethasone|prednisone|prednisolone|fludrocortisone"
_STEROID_EXCLUDE_RX = r"cream|ophth|rectal|suppos|oint|otic|nasal|topical|lotion|%"


def _start_times(con, source: str) -> pd.DataFrame:
    if source in _START_SQL:
        return con.execute(_START_SQL[source]).fetch_df()
    if source == "steroid":
        # prescriptions are hadm-level; assign onset to the stay whose ICU window
        # contains it (first ICU stay only, so unambiguous in practice).
        return con.execute(f"""
            SELECT d.stay_id, min(p.starttime) AS t0_treat
            FROM mimiciv_derived.icustay_detail d
            JOIN mimiciv_hosp.prescriptions p ON p.hadm_id = d.hadm_id
             AND p.starttime >= d.icu_intime AND p.starttime <= d.icu_outtime
            WHERE regexp_matches(lower(p.drug), '{_STEROID_RX}')
              AND NOT regexp_matches(lower(p.drug), '{_STEROID_EXCLUDE_RX}')
              AND d.first_icu_stay = TRUE
            GROUP BY 1""").fetch_df()
    raise ValueError(f"Unknown start source: {source}")


def _baseline_confounders_sql() -> str:
    """Build the per-source baseline-window aggregation, joined onto the cohort.

    stay-keyed sources (vitalsign, gcs) join on stay_id; hadm-keyed lab sources
    (bg, chemistry, cbc, coagulation, enzyme) join on hadm_id. Both are filtered
    to charttime within [icu_intime, cutoff].
    """
    by_source: Dict[str, List] = defaultdict(list)
    for c in RAW_CONFOUNDERS:
        if c.source:
            by_source[c.source].append(c)

    stay_keyed = {"vitalsign", "gcs"}
    ctes, joins, selects = [], [], []
    for src, confs in by_source.items():
        aggs = ", ".join(f"{c.agg}(m.{c.column}) AS {c.key}" for c in confs)
        key = "stay_id" if src in stay_keyed else "hadm_id"
        ctes.append(f"""{src}_b AS (
            SELECT w.stay_id, {aggs}
            FROM mimiciv_derived.{src} m
            JOIN win w ON m.{key} = w.{key}
             AND m.charttime >= w.icu_intime AND m.charttime <= w.cutoff
            GROUP BY w.stay_id)""")
        joins.append(f"LEFT JOIN {src}_b ON {src}_b.stay_id = b.stay_id")
        selects += [f"{src}_b.{c.key}" for c in confs]
    return ctes, joins, selects


def build_trial(cfg: TrialConfig, con=None, save: bool = True) -> pd.DataFrame:
    """Emulate the target trial for one intervention → tidy analysis table."""
    own = con is None
    if own:
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        ctes, joins, selects = _baseline_confounders_sql()
        win_cte = f"""
        win AS (
            SELECT subject_id, hadm_id, stay_id, icu_intime,
                   icu_intime + INTERVAL '{BASELINE_WINDOW_HOURS} hours' AS cutoff
            FROM mimiciv_derived.icustay_detail
            WHERE admission_age >= {MIN_AGE} AND first_icu_stay = TRUE
        )"""
        base_cte = """
        base AS (
            SELECT d.subject_id, d.hadm_id, d.stay_id, d.gender, d.admission_age,
                   d.icu_intime, d.icu_outtime, d.dod, d.hospital_expire_flag,
                   a.admission_type,
                   ch.charlson_comorbidity_index
            FROM mimiciv_derived.icustay_detail d
            LEFT JOIN mimiciv_hosp.admissions a USING (hadm_id)
            LEFT JOIN (SELECT hadm_id, max(charlson_comorbidity_index) charlson_comorbidity_index
                       FROM mimiciv_derived.charlson GROUP BY 1) ch ON ch.hadm_id = d.hadm_id
            WHERE d.admission_age >= {MIN_AGE} AND d.first_icu_stay = TRUE
        )""".format(MIN_AGE=MIN_AGE)

        sql = f"""
        WITH {win_cte},
        {base_cte},
        {','.join(ctes)}
        SELECT b.*, {', '.join(selects)}
        FROM base b
        {' '.join(joins)}
        """
        df = con.execute(sql).fetch_df()

        # auxiliary signals for equipoise (computed in the baseline window / first 48h)
        df = df.merge(_aux_signals(con), on="stay_id", how="left")
        # P3 confounders: goals-of-care (baseline window) + admitting service
        df = df.merge(_p3_code_status(con), on="stay_id", how="left")
        df = df.merge(_p3_services(con), on="hadm_id", how="left")
        # exposure onset
        starts = _start_times(con, cfg.start_source)
        df = df.merge(starts, on="stay_id", how="left")
        # exclusion source
        if cfg.exclude == "esrd":
            esrd = con.execute("""SELECT DISTINCT subject_id FROM mimiciv_hosp.diagnoses_icd
                                  WHERE icd_code IN ('5856','5855','N186','N185')""").fetch_df()
            df["_esrd"] = df["subject_id"].isin(set(esrd["subject_id"]))
        else:
            df["_esrd"] = False
    finally:
        if own:
            con.close()

    return _assemble(df, cfg, save=save)


# Cohort-wide signal tables are identical across interventions; cache within a run
# so the (chartevents) code-status scan happens once, not once per trial.
_SIGNAL_CACHE: dict = {}


def _cached(con, name: str, fn):
    if name not in _SIGNAL_CACHE:
        _SIGNAL_CACHE[name] = fn(con)
    return _SIGNAL_CACHE[name]


def _aux_signals(con) -> pd.DataFrame:
    return _cached(con, "aux", _aux_signals_q)


def _aux_signals_q(con) -> pd.DataFrame:
    sep = con.execute(
        "SELECT DISTINCT stay_id, TRUE AS sepsis3 FROM mimiciv_derived.sepsis3 WHERE sepsis3=TRUE"
    ).fetch_df()
    inf = con.execute(
        "SELECT DISTINCT stay_id, TRUE AS suspected_infection FROM mimiciv_derived.suspicion_of_infection "
        "WHERE suspected_infection=1 AND stay_id IS NOT NULL"
    ).fetch_df()
    aki = con.execute(f"""
        SELECT k.stay_id, max(k.aki_stage) AS aki_stage_max
        FROM mimiciv_derived.kdigo_stages k
        JOIN mimiciv_derived.icustay_detail d ON d.stay_id = k.stay_id
        WHERE k.charttime <= d.icu_intime + INTERVAL '48 hours'
        GROUP BY 1""").fetch_df()
    out = sep.merge(inf, on="stay_id", how="outer").merge(aki, on="stay_id", how="outer")
    return out


def _p3_code_status(con) -> pd.DataFrame:
    return _cached(con, "code_status", _p3_code_status_q)


def _p3_code_status_q(con) -> pd.DataFrame:
    """Code-status limitation (DNR/DNI/CMO) documented by the baseline landmark t0."""
    vals = ", ".join(f"'{v}'" for v in CODE_STATUS_LIMITED_VALUES)
    return con.execute(f"""
        SELECT d.stay_id,
               max(CASE WHEN ce.value IN ({vals}) THEN 1 ELSE 0 END) AS code_status_limited
        FROM mimiciv_derived.icustay_detail d
        JOIN mimiciv_icu.chartevents ce ON ce.stay_id = d.stay_id
         AND ce.charttime <= d.icu_intime + INTERVAL '{BASELINE_WINDOW_HOURS} hours'
        WHERE ce.itemid = {CODE_STATUS_ITEMID}
          AND d.first_icu_stay = TRUE AND d.admission_age >= {MIN_AGE}
        GROUP BY 1""").fetch_df()


def _p3_services(con) -> pd.DataFrame:
    return _cached(con, "services", _p3_services_q)


def _p3_services_q(con) -> pd.DataFrame:
    """First hospital service of the admission (admitting service)."""
    return con.execute("""
        SELECT hadm_id, arg_min(curr_service, transfertime) AS first_service
        FROM mimiciv_hosp.services GROUP BY 1""").fetch_df()


def _assemble(df: pd.DataFrame, cfg: TrialConfig, save: bool) -> pd.DataFrame:
    df = df.copy()
    for col in ["icu_intime", "icu_outtime", "dod", "t0_treat"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["female"] = (df["gender"] == "F").astype(int)
    df["emergency_admission"] = (
        df["admission_type"].fillna("").str.upper().str.contains("EMER|URGENT", regex=True).astype(int)
    )
    df["sepsis3"] = df["sepsis3"].eq(True)
    df["suspected_infection"] = df["suspected_infection"].eq(True)
    df["aki_stage_max"] = pd.to_numeric(df["aki_stage_max"], errors="coerce").fillna(0)

    # P3 confounders: goals-of-care, service, informative-missingness indicators
    df["code_status_limited"] = pd.to_numeric(
        df.get("code_status_limited"), errors="coerce").fillna(0).astype(int)
    first_service = df["first_service"] if "first_service" in df else pd.Series(index=df.index, dtype=object)
    df["surgical_admission"] = first_service.isin(SURGICAL_SERVICES).astype(int)
    df["elective_admission"] = (
        df["admission_type"].fillna("").str.upper().isin(ELECTIVE_ADMISSION_TYPES).astype(int))
    df["lactate_measured"] = df["lactate_max"].notna().astype(int)
    df["abg_measured"] = (df["ph_min"].notna() | df["pao2fio2_min"].notna()).astype(int)
    df["inr_measured"] = df["inr_max"].notna().astype(int)
    df["bilirubin_measured"] = df["bilirubin_max"].notna().astype(int)

    # carry time anchors as columns so they survive row filtering
    df["cutoff"] = df["icu_intime"] + pd.Timedelta(hours=BASELINE_WINDOW_HOURS)
    df["grace"] = df["icu_intime"] + pd.Timedelta(hours=cfg.grace_hours)
    df["t0"] = df["cutoff"]                     # analysis clock origin (baseline landmark)

    n0 = len(df)
    # alive in ICU at the baseline landmark t0 (baseline must exist; no immortal time before t0)
    alive_t0 = (df["icu_outtime"] > df["cutoff"]) & (df["dod"].isna() | (df["dod"] > df["cutoff"]))
    df = df[alive_t0].copy()
    # exclusion: chronic dialysis / ESRD where applicable
    df = df[~df["_esrd"]].copy()
    # prevalent users: treated within the baseline window → excluded
    prevalent = df["t0_treat"].notna() & (df["t0_treat"] < df["cutoff"])
    # exposure classification
    treated = df["t0_treat"].notna() & (df["t0_treat"] >= df["cutoff"]) & (df["t0_treat"] <= df["grace"])
    late = df["t0_treat"].notna() & (df["t0_treat"] > df["grace"])   # ambiguous → drop
    never = df["t0_treat"].isna()
    keep = (treated | never) & ~prevalent
    n_prev, n_late = int(prevalent.sum()), int((late & ~prevalent).sum())
    df = df[keep].copy()
    df["treated"] = treated[keep].astype(int)

    # equipoise membership (from baseline-window physiology / aux signals)
    from mortality_pipeline.equipoise import equipoise_mask
    df["equipoise"] = equipoise_mask(df, cfg.equipoise).astype(int)

    # outcomes measured from t0
    days_to_death = (df["dod"] - df["t0"]).dt.total_seconds() / 86400.0
    df["days_to_death"] = days_to_death
    df["died"] = df["dod"].notna().astype(int)
    # administrative censoring horizon (per-patient) from registry coverage
    dod_max = df["dod"].max()
    df["followup_days"] = np.where(
        df["dod"].notna(), days_to_death, (dod_max - df["t0"]).dt.total_seconds() / 86400.0
    )
    df["mortality_in_hospital"] = df["hospital_expire_flag"].astype(float)
    for d, col in [(28, "mortality_28d"), (90, "mortality_90d")]:
        died_by = (df["died"] == 1) & (df["days_to_death"] <= d)
        uncertain = (df["died"] == 0) & (df["followup_days"] < d)
        out = died_by.astype(float)
        out[uncertain] = np.nan
        df[col] = out

    logger.info(
        f"  {cfg.key}: kept {len(df):,}/{n0:,}  (treated={int(df['treated'].sum()):,}, "
        f"control={int((df['treated']==0).sum()):,}; excluded {n_prev:,} prevalent, {n_late:,} late)  "
        f"equipoise={int(df['equipoise'].sum()):,}")

    keep_cols = (
        ["subject_id", "hadm_id", "stay_id", "t0", "treated", "equipoise",
         "days_to_death", "died", "followup_days",
         "mortality_in_hospital", "mortality_28d", "mortality_90d",
         "sepsis3", "suspected_infection", "aki_stage_max"]
        + RAW_CONFOUNDER_KEYS + P3_CONFOUNDER_KEYS
    )
    df = df[keep_cols]

    if save:
        DIR2TRIALS.mkdir(parents=True, exist_ok=True)
        path = DIR2TRIALS / f"trial_{cfg.key}.parquet"
        df.to_parquet(path)
        logger.info(f"    saved → {path}")
    return df


def build_all_trials(save: bool = True) -> Dict[str, pd.DataFrame]:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    out = {}
    try:
        for cfg in TRIALS:
            logger.info(f"▶ Target trial: {cfg.key} (grace={cfg.grace_hours}h, equipoise={cfg.equipoise})")
            out[cfg.key] = build_trial(cfg, con=con, save=save)
    finally:
        con.close()
    return out


def load_trial(key: str, rebuild: bool = False) -> pd.DataFrame:
    path = DIR2TRIALS / f"trial_{key}.parquet"
    if path.exists() and not rebuild:
        return pd.read_parquet(path)
    from mortality_pipeline.constants import TRIAL_BY_KEY
    return build_trial(TRIAL_BY_KEY[key], save=True)


if __name__ == "__main__":
    build_all_trials()
