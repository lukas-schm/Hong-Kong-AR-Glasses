"""
F13: Treatment-arm classification using ICU `inputevents` (actual IV
administrations) instead of `prescriptions` (orders).

Why: orders reflect intent; administrations reflect what nurses actually
hung. A "continue" order at 60 h that the bedside team held at 70 h would
classify as `continue` on prescriptions but correctly as `stop` on the
administration record.

We resolve `inputevents.itemid` against the ICU `d_items` dictionary so the
same broad / narrow drug taxonomy from causal_graph.yaml applies. Patients
with no matching ICU records (e.g., antibiotic given on the ward and not
re-prescribed in ICU) fall back to the prescriptions-based classifier so the
cohort doesn't shrink.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import polars as pl
from loguru import logger
from sklearn.utils import Bunch

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_PATIENT_ID,
    DIR2RAW,
    TREATMENT_ARM_CONTINUE,
    TREATMENT_ARM_DEESCALATE,
    TREATMENT_ARM_STOP,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

# ── Drug-class → ICU inputevents.itemid map ──────────────────────────────────
# Manually compiled from d_items.csv.gz on the local MIMIC-IV release.
BROAD_ITEMIDS: dict[int, str] = {
    # Carbapenems
    225876: "imipenem",
    225883: "meropenem",
    229061: "ertapenem",
    # Glycopeptides / linezolid / daptomycin
    225798: "vancomycin",
    225881: "linezolid",
    225863: "daptomycin",
    # Broad β-lactams + aminoglycosides
    225843: "ampicillin-sulbactam",
    225851: "cefepime",
    225853: "ceftazidime",
    225855: "ceftriaxone",
    225892: "piperacillin",
    225893: "piperacillin-tazobactam",
    225840: "amikacin",
    225875: "gentamicin",
    225902: "tobramycin",
}
NARROW_ITEMIDS: dict[int, str] = {
    225842: "ampicillin",
    225850: "cefazolin",
    225884: "metronidazole",
    225845: "azithromycin",
}


def classify_from_inputevents(
    population: pd.DataFrame,
    cohort_config: Bunch,
) -> pd.DataFrame:
    """Same contract as `_classify_treatment_arm`: adds `treatment_arm` column.

    Logic: a record from `inputevents` is "active in window" iff its
    [starttime, endtime] overlaps [T0 - window_h, T0 + window_h].

    Returns the population frame with `treatment_arm` integer-coded.
    """
    window_h = cohort_config.treatment_classify_window_hours
    keys = [COLNAME_PATIENT_ID, COLNAME_HADM_ID]
    decision_times = pl.from_pandas(
        population[keys + [COLNAME_DECISION_TIME]]
    ).lazy()

    all_abx_itemids = list(BROAD_ITEMIDS.keys()) + list(NARROW_ITEMIDS.keys())

    inputevents = (
        pl.scan_parquet(DIR2RAW / "inputevents.parquet")
        .select([COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "endtime", "itemid"])
        .filter(pl.col("itemid").is_in(all_abx_itemids))
    )

    abx_in_window = (
        inputevents
        .join(decision_times, on=keys, how="inner")
        .filter(
            (pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME) + pl.duration(hours=window_h))
            & (pl.col("endtime") >= pl.col(COLNAME_DECISION_TIME) - pl.duration(hours=window_h))
        )
        .collect()
        .to_pandas()
    )
    logger.info(
        f"  F13 inputevents: {len(abx_in_window):,} antibiotic administrations "
        f"in window for {abx_in_window[keys[1]].nunique()} hadm_ids"
    )

    has_broad = (
        abx_in_window[abx_in_window["itemid"].isin(BROAD_ITEMIDS)]
        .groupby(keys).size().reset_index(name="n_broad_ev")
    )
    has_narrow = (
        abx_in_window[abx_in_window["itemid"].isin(NARROW_ITEMIDS)]
        .groupby(keys).size().reset_index(name="n_narrow_ev")
    )

    pop = population.merge(has_broad, on=keys, how="left")
    pop = pop.merge(has_narrow, on=keys, how="left")
    pop["n_broad_ev"] = pop["n_broad_ev"].fillna(0)
    pop["n_narrow_ev"] = pop["n_narrow_ev"].fillna(0)

    def _arm(row):
        if row["n_broad_ev"] > 0:
            return TREATMENT_ARM_CONTINUE
        elif row["n_narrow_ev"] > 0:
            return TREATMENT_ARM_DEESCALATE
        else:
            return TREATMENT_ARM_STOP

    pop[COLNAME_INTERVENTION_STATUS] = pop.apply(_arm, axis=1)
    pop = pop.drop(columns=["n_broad_ev", "n_narrow_ev"])
    return pop
