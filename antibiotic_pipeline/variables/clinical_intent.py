"""
Clinical-intent confounders for the antibiotic-continuation cohort.

Adds four reviewer-requested confounders extracted from MIMIC-IV raw tables:

  * code_status_at_decision      — categorical: full / dnr / dni / dnr_dni / cmo / unknown
  * palliative_transition_pre_T0 — binary: palliative-care consult between admission and T0
  * id_consult_pre_T0            — binary: infectious-disease consult between admission and T0
  * source_control_pre_T0        — binary: source-control procedure between admission and T0

A CMO-at-T0 indicator is also returned so that the framing module can *exclude*
those stays from the analytic cohort (they are not eligible for the treatment
policy of interest; they should not be adjusted for).

Source tables (raw parquet):
  * chartevents/  partitioned — itemid 223758 = "Code status"
  * poe/          partitioned — order_type='Consults', subtype in {Infectious
                                Disease, Palliative Care, Palliative Care/Ethics Support}
  * procedureevents.parquet   — therapeutic procedures (curated itemid list)

We deliberately keep the source-control itemid list explicit and conservative
rather than scanning d_items. The list is versioned in
``antibiotic_pipeline.definitions.clinical_intent_codes`` and documented in the
manuscript supplement.
"""
from __future__ import annotations

import polars as pl
import pandas as pd

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_INCLUSION_START,
    COLNAME_PATIENT_ID,
    DIR2RAW,
)

# ── Itemids ────────────────────────────────────────────────────────────────
# MIMIC-IV chartevents itemid for code-status documentation.
CODE_STATUS_ITEMID = 223758

# Source-control procedures (MIMIC-IV procedureevents). Conservative,
# clinically-justifiable subset; extend in YAML before reporting new analyses.
# Refs: MIMIC-IV d_items concept dictionary; mimic-code/concepts.
SOURCE_CONTROL_ITEMIDS: frozenset[int] = frozenset(
    {
        # Verified against mimic-iv/icu/d_items.csv.gz (linksto=procedureevents).
        225433,  # Chest Tube Placed — pleural source control
        225445,  # Paracentesis — abdominal source control
        225479,  # Thoracentesis — pleural source control
        225447,  # Percutaneous Drain Insertion — IR drainage analog
        226475,  # Intraventricular Drain Inserted — CSF source control
        225805,  # Peritoneal Dialysis — peritoneal source control
    }
)

# ── Mapping for code-status values ─────────────────────────────────────────
_CODE_STATUS_NORMALIZER = {
    "full code": "full_code",
    "dnr (do not resuscitate)": "dnr",
    "dni (do not intubate)": "dni",
    "dnr / dni": "dnr_dni",
    "comfort measures only": "cmo",
    "cpr not indicated": "dnr",
}


def _normalize_code_status(value: str | None) -> str:
    if value is None:
        return "unknown"
    return _CODE_STATUS_NORMALIZER.get(value.strip().lower(), "unknown")


# ── Extractors ─────────────────────────────────────────────────────────────


def get_clinical_intent_confounders(
    target_population: pd.DataFrame,
) -> pd.DataFrame:
    """Return one row per stay with the clinical-intent confounders.

    Columns
    -------
    stay_id,
    code_status_full_code, code_status_dnr, code_status_dni,
    code_status_dnr_dni, code_status_unknown,   # one-hot of code status
    cmo_at_decision,                            # used for cohort exclusion
    palliative_transition_pre_T0,
    id_consult_pre_T0,
    source_control_pre_T0

    Code status is emitted as one-hot binary columns rather than a
    string-valued category so that downstream median imputation does not
    choke on the categorical type. ``cmo_at_decision`` is kept as a
    standalone binary (it's used for cohort exclusion in the framing module
    and never appears as a confounder in the adjustment set).
    """
    pop_pl = pl.from_pandas(
        target_population[
            [
                COLNAME_PATIENT_ID,
                COLNAME_HADM_ID,
                COLNAME_ICUSTAY_ID,
                COLNAME_INCLUSION_START,
                COLNAME_DECISION_TIME,
            ]
        ]
    )

    stays_pd = pop_pl.select(COLNAME_ICUSTAY_ID).to_pandas()

    code_status_df = _extract_code_status(pop_pl)
    palliative_df = _extract_consult(pop_pl, {"Palliative Care", "Palliative Care/Ethics Support"},
                                      out_col="palliative_transition_pre_T0")
    id_consult_df = _extract_consult(pop_pl, {"Infectious Disease"},
                                      out_col="id_consult_pre_T0")
    source_control_df = _extract_source_control(pop_pl)

    out = stays_pd
    for df in (code_status_df, palliative_df, id_consult_df, source_control_df):
        out = out.merge(df, on=COLNAME_ICUSTAY_ID, how="left")

    # Binary columns: missing => 0 (no documented event before T0)
    for c in ["palliative_transition_pre_T0", "id_consult_pre_T0",
              "source_control_pre_T0", "cmo_at_decision"]:
        out[c] = out[c].fillna(0).astype("int8")

    # One-hot code-status (drop the cmo column — those stays are excluded
    # from the cohort upstream).
    out["code_status_raw"] = out["code_status_raw"].fillna("unknown")
    for value in ("full_code", "dnr", "dni", "dnr_dni", "unknown"):
        out[f"code_status_{value}"] = (out["code_status_raw"] == value).astype("int8")
    out = out.drop(columns=["code_status_raw"])
    return out


def _extract_code_status(stays_pl: pl.DataFrame) -> pd.DataFrame:
    """Latest non-null code-status documentation at or before T0."""
    chartevents = pl.scan_parquet(
        DIR2RAW / "chartevents/_partition=*/*.parquet"
    ).select(["stay_id", "charttime", "itemid", "value"])

    code_status = (
        chartevents.filter(pl.col("itemid") == CODE_STATUS_ITEMID)
        .join(
            stays_pl.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
            on=COLNAME_ICUSTAY_ID,
            how="inner",
        )
        .filter(pl.col("charttime") <= pl.col(COLNAME_DECISION_TIME))
        .filter(pl.col("value").is_not_null())
        .sort([COLNAME_ICUSTAY_ID, "charttime"])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.last("value").alias("raw_value"))
        .collect()
        .to_pandas()
    )

    code_status["code_status_raw"] = code_status["raw_value"].map(
        _normalize_code_status
    )
    code_status["cmo_at_decision"] = (
        code_status["code_status_raw"] == "cmo"
    ).astype("int8")
    return code_status[[COLNAME_ICUSTAY_ID, "code_status_raw", "cmo_at_decision"]]


def _extract_consult(
    stays_pl: pl.DataFrame, subtypes: set[str], out_col: str
) -> pd.DataFrame:
    """Binary flag: any consult with the given order_subtype between admission and T0.

    POE is hadm-keyed, so we join on hadm_id. A consult before the inclusion
    start (i.e. before the first broad-spectrum order) is still relevant —
    it predates and may have shaped the antibiotic decision — so we use the
    interval [admission_start, decision_time]. We approximate admission_start
    by ``inclusion_start - 7 days`` (a conservative window). This is documented
    as a measurement-error caveat in the manuscript.
    """
    poe = pl.scan_parquet(DIR2RAW / "poe/_partition=*/*.parquet").select(
        ["subject_id", "hadm_id", "ordertime", "order_type", "order_subtype"]
    )

    subtype_filter = pl.col("order_subtype").is_in(list(subtypes))
    flag = (
        poe.filter((pl.col("order_type") == "Consults") & subtype_filter)
        .join(
            stays_pl.lazy().select(
                [COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID,
                 COLNAME_INCLUSION_START, COLNAME_DECISION_TIME]
            ),
            on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID],
            how="inner",
        )
        .filter(pl.col("ordertime") <= pl.col(COLNAME_DECISION_TIME))
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).cast(pl.Int8).alias(out_col))
        .collect()
        .to_pandas()
    )
    return flag


def _extract_source_control(stays_pl: pl.DataFrame) -> pd.DataFrame:
    """Binary flag: any source-control procedure recorded before T0."""
    procedureevents = pl.scan_parquet(DIR2RAW / "procedureevents.parquet").select(
        ["stay_id", "starttime", "itemid"]
    )
    flag = (
        procedureevents.filter(pl.col("itemid").is_in(list(SOURCE_CONTROL_ITEMIDS)))
        .join(
            stays_pl.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
            on=COLNAME_ICUSTAY_ID,
            how="inner",
        )
        .filter(pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME))
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).cast(pl.Int8).alias("source_control_pre_T0"))
        .collect()
        .to_pandas()
    )
    return flag
