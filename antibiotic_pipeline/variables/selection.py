"""
Confounder extraction at time zero (72 h decision point) for the antibiotic
continuation cohort.

All features are measured in a window ending at time zero (COLNAME_DECISION_TIME).
Feature type classification is driven by causal_graph.yaml via CAUSAL_GRAPH.

Feature groups
--------------
1. illness_severity   : SOFA, SAPSII, lactate, vasopressors, MAP
2. infection_certainty: CRP, WBC, temperature, culture results, source
3. organ_dysfunction  : AKI stage, PF ratio, ventilation, creatinine, bilirubin
4. treatment_history  : days on antibiotics, prior antibiotic classes
5. trajectory (0→72h) : delta SOFA, WBC, lactate, temperature, creatinine
6. demographics       : age, sex, immunosuppression, Charlson CCI

Source tables (all parquet, built by data/build_derived.py):
  derived/ : sofa, sapsii, bg, vitalsign, vasoactive_agent, ventilation,
             kdigo_stages, charlson, chemistry, complete_blood_count, enzyme,
             inflammation, antibiotic
  raw/     : patients, admissions, icustays, microbiologyevents, prescriptions
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import pandas as pd
import polars as pl
from joblib import Memory

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_INCLUSION_START,
    COLNAME_PATIENT_ID,
    DIR2DERIVED,
    DIR2RAW,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

_cache = Memory("./cachedir", verbose=0)


@dataclass
class FeatureTypes:
    binary_features: List[str] = field(default_factory=list)
    categorical_features: List[str] = field(default_factory=list)
    numerical_features: List[str] = field(default_factory=list)


# ── Public entry point ────────────────────────────────────────────────────────

@_cache.cache()
def get_confounders_at_decision_time(
    target_population: pd.DataFrame,
) -> Tuple[pd.DataFrame, FeatureTypes]:
    """Extract all confounders measured at or before time zero (72 h).

    Parameters
    ----------
    target_population : pd.DataFrame
        Output of framing.antibiotic_continuation_sepsis.get_population().

    Returns
    -------
    features_df : pd.DataFrame
        One row per stay_id with all confounders as columns.
    feature_types : FeatureTypes
        Classification of each feature for downstream preprocessing.
    """
    pop_pl = pl.from_pandas(target_population)
    stays = pop_pl.select([
        COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID,
        COLNAME_INCLUSION_START, COLNAME_DECISION_TIME,
    ])

    from antibiotic_pipeline.variables.clinical_intent import (
        get_clinical_intent_confounders,
    )

    frames = [
        _get_severity_features(stays),
        _get_infection_markers(stays),
        _get_organ_function(stays),
        _get_treatment_history(stays),
        _get_trajectory_features(stays),
        _get_demographics(stays, pop_pl),
        # WS4: code-status, palliative consult, ID consult, source-control
        get_clinical_intent_confounders(target_population),
    ]

    features_df = target_population[[
        COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID
    ]].copy()
    for frame in frames:
        if frame is not None:
            features_df = features_df.merge(frame, on=COLNAME_ICUSTAY_ID, how="left")

    # F5: missing-indicator columns for every numeric confounder.
    # Clinical missingness is informative ("PCT not measured" ≈ low clinical
    # suspicion); median-imputed values erase that signal. We keep the imputed
    # value *and* an indicator so downstream models can use both.
    numeric_cols = [c for c in CAUSAL_GRAPH.numerical_confounders if c in features_df.columns]
    indicator_cols = []
    for col in numeric_cols:
        ind_name = f"{col}__missing"
        features_df[ind_name] = features_df[col].isna().astype("int8")
        indicator_cols.append(ind_name)

    # Coerce object-typed numerics (e.g. Decimal from polars) to float so the
    # downstream median imputer can consume them.
    for col in numeric_cols:
        if features_df[col].dtype == object:
            features_df[col] = pd.to_numeric(features_df[col], errors="coerce")

    feature_types = FeatureTypes(
        binary_features=CAUSAL_GRAPH.binary_confounders + indicator_cols,
        categorical_features=CAUSAL_GRAPH.categorical_confounders,
        numerical_features=CAUSAL_GRAPH.numerical_confounders,
    )
    return features_df, feature_types


# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_stay(lf: pl.LazyFrame, stays_lf: pl.LazyFrame, val_col: str,
               time_col: str = "charttime") -> pd.DataFrame:
    """Latest value per stay_id at or before decision_time."""
    return (
        lf.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
                on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
        .sort([COLNAME_ICUSTAY_ID, time_col])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.last(val_col))
        .collect()
        .to_pandas()
    )


def _last_hadm(lf: pl.LazyFrame, stays_lf: pl.LazyFrame, val_col: str,
               time_col: str = "charttime") -> pd.DataFrame:
    """Latest value per hadm_id at or before decision_time, returned with stay_id."""
    return (
        lf.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_HADM_ID, COLNAME_DECISION_TIME]),
                on=COLNAME_HADM_ID, how="inner")
        .filter(pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
        .sort([COLNAME_ICUSTAY_ID, time_col])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.last(val_col))
        .collect()
        .to_pandas()
    )


# ── Feature group extractors ──────────────────────────────────────────────────

def _get_severity_features(stays: pl.DataFrame) -> pd.DataFrame:
    """SOFA at 72h, SAPSII, lactate, MAP, vasopressor status."""
    stays_lf = stays.lazy()

    sofa = pl.scan_parquet(DIR2DERIVED / "sofa.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "sofa_24hours"]
    )
    sapsii = pl.scan_parquet(DIR2DERIVED / "sapsii.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "sapsii"]
    )
    # bg has hadm_id; lactate measured in blood gas
    bg = pl.scan_parquet(DIR2DERIVED / "bg.parquet").select(
        [COLNAME_HADM_ID, "charttime", "lactate"]
    )
    vitals = pl.scan_parquet(DIR2DERIVED / "vitalsign.parquet").select(
        [COLNAME_ICUSTAY_ID, "charttime", "mbp"]
    )
    vasopressors = pl.scan_parquet(DIR2DERIVED / "vasoactive_agent.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "endtime",
         "norepinephrine", "epinephrine", "dopamine", "vasopressin"]
    )

    sofa_df = _last_stay(sofa, stays_lf, "sofa_24hours", "starttime").rename(
        columns={"sofa_24hours": "SOFA_at_decision"}
    )
    sapsii_df = _last_stay(sapsii, stays_lf, "sapsii", "starttime").rename(
        columns={"sapsii": "SAPSII"}
    )
    lactate_df = _last_hadm(bg, stays_lf, "lactate").rename(
        columns={"lactate": "lactate_at_decision"}
    )
    map_df = _last_stay(vitals, stays_lf, "mbp").rename(
        columns={"mbp": "MAP_at_decision"}
    )

    # Vasopressors: any active at decision_time (interval overlap)
    vaso_df = (
        vasopressors.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
                          on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME))
            & (pl.col("endtime") >= pl.col(COLNAME_DECISION_TIME))
        )
        .filter(
            (pl.col("norepinephrine").is_not_null() & (pl.col("norepinephrine") > 0))
            | (pl.col("epinephrine").is_not_null() & (pl.col("epinephrine") > 0))
            | (pl.col("dopamine").is_not_null() & (pl.col("dopamine") > 0))
            | (pl.col("vasopressin").is_not_null() & (pl.col("vasopressin") > 0))
        )
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).alias("vasopressors_at_decision"))
        .collect()
        .to_pandas()
    )

    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas()
    for df in [sofa_df, sapsii_df, lactate_df, map_df]:
        result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    result = result.merge(vaso_df, on=COLNAME_ICUSTAY_ID, how="left")
    result["vasopressors_at_decision"] = result["vasopressors_at_decision"].fillna(0).astype(int)
    return result


def _get_infection_markers(stays: pl.DataFrame) -> pd.DataFrame:
    """CRP (proxy for PCT), WBC, temperature, culture results, infection source."""
    stays_lf = stays.lazy()

    # All measurement tables join via hadm_id
    cbc = pl.scan_parquet(DIR2DERIVED / "complete_blood_count.parquet").select(
        [COLNAME_HADM_ID, "charttime", "wbc"]
    )
    vitals = pl.scan_parquet(DIR2DERIVED / "vitalsign.parquet").select(
        [COLNAME_ICUSTAY_ID, "charttime", "temperature"]
    )
    inflammation = pl.scan_parquet(DIR2DERIVED / "inflammation.parquet").select(
        [COLNAME_HADM_ID, "charttime", "crp"]
    )

    wbc_df = _last_hadm(cbc, stays_lf, "wbc").rename(
        columns={"wbc": "WBC_at_decision"}
    )
    temp_df = _last_stay(vitals, stays_lf, "temperature").rename(
        columns={"temperature": "temperature_at_decision"}
    )
    crp_df = _last_hadm(inflammation, stays_lf, "crp").rename(
        columns={"crp": "CRP_at_decision"}
    )

    # Blood culture positivity
    micro = pl.scan_parquet(DIR2RAW / "microbiologyevents.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "chartdate", "spec_type_desc", "org_name"]
    )
    cultures = (
        micro.join(
            stays_lf.select([COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID,
                              COLNAME_INCLUSION_START, COLNAME_DECISION_TIME]),
            on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner"
        )
        .filter(
            (pl.col("chartdate").cast(pl.Utf8)
             .str.to_datetime(format="%Y-%m-%d", strict=False)
             >= pl.col(COLNAME_INCLUSION_START))
            & (pl.col("chartdate").cast(pl.Utf8)
               .str.to_datetime(format="%Y-%m-%d", strict=False)
               <= pl.col(COLNAME_DECISION_TIME))
        )
        .collect()
        .to_pandas()
    )

    blood = cultures[cultures["spec_type_desc"].str.lower().str.contains("blood", na=False)]
    positive_blood = (
        blood[blood["org_name"].notnull()]
        .groupby(COLNAME_ICUSTAY_ID).size().reset_index(name="_n")
        .assign(positive_blood_culture=1)[[COLNAME_ICUSTAY_ID, "positive_blood_culture"]]
    )
    gram_pos = (
        blood[blood["org_name"].str.lower().str.contains(
            "staphylococcus|streptococcus|enterococcus", na=False)]
        .groupby(COLNAME_ICUSTAY_ID).size().reset_index(name="_n")
        .assign(culture_gram_positive=1)[[COLNAME_ICUSTAY_ID, "culture_gram_positive"]]
    )
    gram_neg = (
        blood[blood["org_name"].str.lower().str.contains(
            "escherichia|klebsiella|pseudomonas|acinetobacter|enterobacter", na=False)]
        .groupby(COLNAME_ICUSTAY_ID).size().reset_index(name="_n")
        .assign(culture_gram_negative=1)[[COLNAME_ICUSTAY_ID, "culture_gram_negative"]]
    )

    def _source_flag(spec_pattern: str, col_name: str):
        return (
            cultures[cultures["spec_type_desc"].str.lower().str.contains(spec_pattern, na=False)]
            .groupby(COLNAME_ICUSTAY_ID).size().reset_index(name="_n")
            .assign(**{col_name: 1})[[COLNAME_ICUSTAY_ID, col_name]]
        )

    pulm = _source_flag("sputum|bronch|bal|tracheal", "infection_source_pulmonary")
    uri = _source_flag("urine", "infection_source_urinary")
    abdo = _source_flag("peritoneal|bile|wound|abscess", "infection_source_abdominal")

    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas()
    for df in [wbc_df, temp_df, crp_df, positive_blood, gram_pos, gram_neg, pulm, uri, abdo]:
        if df is not None and len(df):
            result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")

    binary_cols = [
        "positive_blood_culture", "culture_gram_positive", "culture_gram_negative",
        "infection_source_pulmonary", "infection_source_urinary", "infection_source_abdominal",
    ]
    for c in binary_cols:
        if c in result.columns:
            result[c] = result[c].fillna(0).astype(int)
    return result


def _get_organ_function(stays: pl.DataFrame) -> pd.DataFrame:
    """AKI stage, PF ratio, ventilation, creatinine, bilirubin."""
    stays_lf = stays.lazy()

    kdigo = pl.scan_parquet(DIR2DERIVED / "kdigo_stages.parquet").select(
        [COLNAME_ICUSTAY_ID, "charttime", "aki_stage"]
    )
    bg = pl.scan_parquet(DIR2DERIVED / "bg.parquet").select(
        [COLNAME_HADM_ID, "charttime", "pao2fio2ratio"]
    )
    ventilation = pl.scan_parquet(DIR2DERIVED / "ventilation.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "endtime"]
    )
    chemistry = pl.scan_parquet(DIR2DERIVED / "chemistry.parquet").select(
        [COLNAME_HADM_ID, "charttime", "creatinine"]
    )
    enzyme = pl.scan_parquet(DIR2DERIVED / "enzyme.parquet").select(
        [COLNAME_HADM_ID, "charttime", "bilirubin_total"]
    )

    aki_df = _last_stay(kdigo, stays_lf, "aki_stage").rename(
        columns={"aki_stage": "AKI_stage_at_decision"}
    )
    pf_df = _last_hadm(bg, stays_lf, "pao2fio2ratio").rename(
        columns={"pao2fio2ratio": "pf_ratio_at_decision"}
    )
    creat_df = _last_hadm(chemistry, stays_lf, "creatinine").rename(
        columns={"creatinine": "creatinine_at_decision"}
    )
    bili_df = _last_hadm(enzyme, stays_lf, "bilirubin_total").rename(
        columns={"bilirubin_total": "bilirubin_at_decision"}
    )

    vent_df = (
        ventilation.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
                         on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME))
            & (pl.col("endtime") >= pl.col(COLNAME_DECISION_TIME))
        )
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).alias("ventilation_at_decision"))
        .collect()
        .to_pandas()
    )

    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas()
    for df in [aki_df, pf_df, vent_df, creat_df, bili_df]:
        result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    result["ventilation_at_decision"] = result["ventilation_at_decision"].fillna(0).astype(int)
    return result


def _get_treatment_history(stays: pl.DataFrame) -> pd.DataFrame:
    """Days on antibiotics and prior antibiotic class flags at time zero."""
    stays_lf = stays.lazy()

    from antibiotic_pipeline.framing.antibiotic_continuation_sepsis import (
        BROAD_SPECTRUM_DRUGS,
        CARBAPENEM_DRUGS,
        GLYCOPEPTIDE_DRUGS,
        BETALACTAM_BROAD_DRUGS,
        AMINOGLYCOSIDE_DRUGS,
    )

    prescriptions = pl.scan_parquet(DIR2RAW / "prescriptions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "stoptime", "drug"]
    )

    abx_before_decision = (
        prescriptions.filter(
            pl.col("drug").str.to_lowercase().str.contains("|".join(BROAD_SPECTRUM_DRUGS))
        )
        .join(stays_lf.select([COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID,
                                COLNAME_INCLUSION_START, COLNAME_DECISION_TIME]),
              on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")
        .filter(
            (pl.col("starttime") >= pl.col(COLNAME_INCLUSION_START))
            & (pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME))
        )
        .with_columns(pl.col("drug").str.to_lowercase().alias("drug_lower"))
        .collect()
        .to_pandas()
    )

    stays_pd = stays.select([COLNAME_ICUSTAY_ID, COLNAME_INCLUSION_START,
                              COLNAME_DECISION_TIME]).to_pandas()
    days_df = stays_pd.copy()
    days_df["days_on_abx"] = (
        pd.to_datetime(days_df[COLNAME_DECISION_TIME]) -
        pd.to_datetime(days_df[COLNAME_INCLUSION_START])
    ).dt.total_seconds() / 86400

    def _flag_class(drug_list, col_name):
        pattern = "|".join(drug_list)
        return (
            abx_before_decision[abx_before_decision["drug_lower"].str.contains(pattern)]
            .groupby(COLNAME_ICUSTAY_ID).size().reset_index(name="_n")
            .assign(**{col_name: 1})[[COLNAME_ICUSTAY_ID, col_name]]
        )

    result = days_df[[COLNAME_ICUSTAY_ID, "days_on_abx"]]
    for df in [
        _flag_class(CARBAPENEM_DRUGS, "prior_carbapenem"),
        _flag_class(GLYCOPEPTIDE_DRUGS, "prior_glycopeptide"),
        _flag_class(BETALACTAM_BROAD_DRUGS, "prior_betalactam"),
        _flag_class(AMINOGLYCOSIDE_DRUGS, "prior_aminoglycoside"),
    ]:
        result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")

    for c in ["prior_carbapenem", "prior_glycopeptide", "prior_betalactam", "prior_aminoglycoside"]:
        result[c] = result[c].fillna(0).astype(int)
    return result


def _get_trajectory_features(stays: pl.DataFrame) -> pd.DataFrame:
    """Delta features: value at 72h minus value at 0h for key markers."""
    stays_lf = stays.lazy()

    sofa = pl.scan_parquet(DIR2DERIVED / "sofa.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "sofa_24hours"]
    )
    bg = pl.scan_parquet(DIR2DERIVED / "bg.parquet").select(
        [COLNAME_HADM_ID, "charttime", "lactate"]
    )
    chemistry = pl.scan_parquet(DIR2DERIVED / "chemistry.parquet").select(
        [COLNAME_HADM_ID, "charttime", "creatinine"]
    )
    vitals = pl.scan_parquet(DIR2DERIVED / "vitalsign.parquet").select(
        [COLNAME_ICUSTAY_ID, "charttime", "temperature"]
    )
    cbc = pl.scan_parquet(DIR2DERIVED / "complete_blood_count.parquet").select(
        [COLNAME_HADM_ID, "charttime", "wbc"]
    )

    def _delta_stay(lf, val_col, out_col, time_col="starttime"):
        return (
            lf.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_INCLUSION_START,
                                     COLNAME_DECISION_TIME]),
                    on=COLNAME_ICUSTAY_ID, how="inner")
            .filter(
                (pl.col(time_col) >= pl.col(COLNAME_INCLUSION_START))
                & (pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
            )
            .sort([COLNAME_ICUSTAY_ID, time_col])
            .group_by(COLNAME_ICUSTAY_ID)
            .agg([
                pl.first(val_col).alias("_first"),
                pl.last(val_col).alias("_last"),
            ])
            .with_columns((pl.col("_last") - pl.col("_first")).alias(out_col))
            .select([COLNAME_ICUSTAY_ID, out_col])
            .collect()
            .to_pandas()
        )

    def _delta_hadm(lf, val_col, out_col, time_col="charttime"):
        return (
            lf.join(stays_lf.select([COLNAME_ICUSTAY_ID, COLNAME_HADM_ID,
                                     COLNAME_INCLUSION_START, COLNAME_DECISION_TIME]),
                    on=COLNAME_HADM_ID, how="inner")
            .filter(
                (pl.col(time_col) >= pl.col(COLNAME_INCLUSION_START))
                & (pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
            )
            .sort([COLNAME_ICUSTAY_ID, time_col])
            .group_by(COLNAME_ICUSTAY_ID)
            .agg([
                pl.first(val_col).alias("_first"),
                pl.last(val_col).alias("_last"),
            ])
            .with_columns((pl.col("_last") - pl.col("_first")).alias(out_col))
            .select([COLNAME_ICUSTAY_ID, out_col])
            .collect()
            .to_pandas()
        )

    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas()
    for df in [
        _delta_stay(sofa, "sofa_24hours", "delta_SOFA_0_72h", "starttime"),
        _delta_hadm(bg, "lactate", "delta_lactate_0_72h"),
        _delta_stay(vitals, "temperature", "delta_temperature_0_72h", "charttime"),
        _delta_hadm(cbc, "wbc", "delta_WBC_0_72h"),
        _delta_hadm(chemistry, "creatinine", "delta_creatinine_0_72h"),
    ]:
        result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    return result


def _get_demographics(stays: pl.DataFrame, pop_pl: pl.DataFrame) -> pd.DataFrame:
    """Age, sex, immunosuppression, Charlson CCI, emergency admission."""
    patients = pl.scan_parquet(DIR2RAW / "patients.parquet").select(
        [COLNAME_PATIENT_ID, "anchor_age", "gender"]
    )
    admissions = pl.scan_parquet(DIR2RAW / "admissions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "admission_type"]
    )
    charlson = pl.scan_parquet(DIR2DERIVED / "charlson.parquet").select(
        [COLNAME_HADM_ID, "charlson_comorbidity_index",
         "malignant_cancer", "metastatic_solid_tumor", "aids"]
    )

    demo = (
        pop_pl.lazy()
        .select([COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID])
        .join(patients, on=COLNAME_PATIENT_ID, how="inner")
        .join(admissions, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")
        .join(charlson, on=COLNAME_HADM_ID, how="left")
        .with_columns([
            pl.col("anchor_age").alias("admission_age"),
            (pl.col("gender") == "F").cast(pl.Int8).alias("Female"),
            pl.col("admission_type").str.to_lowercase().str.contains("emergency")
            .cast(pl.Int8).alias("emergency_admission"),
            (
                (pl.col("malignant_cancer").fill_null(0) > 0)
                | (pl.col("metastatic_solid_tumor").fill_null(0) > 0)
                | (pl.col("aids").fill_null(0) > 0)
            ).cast(pl.Int8).alias("immunosuppressed"),
        ])
        .select([
            COLNAME_ICUSTAY_ID,
            "admission_age", "Female", "emergency_admission",
            "immunosuppressed", "charlson_comorbidity_index",
        ])
        .collect()
        .to_pandas()
    )
    return demo


# ── Ventilator-free and vasopressor-free day computation ─────────────────────

def compute_vfd28(population: pd.DataFrame) -> pd.DataFrame:
    """Add VFD-28 and VaPFD-28 columns to the population dataframe.

    VFD-28 = 0 if patient dies within 28 days; otherwise 28 minus days
    on mechanical ventilation after time zero.
    """
    from antibiotic_pipeline.constants import COLNAME_MORTALITY_28D, COLNAME_VFD28, COLNAME_VAPFD28
    from antibiotic_pipeline.variables.aggregation import compute_free_days

    pop = population.copy()

    ventilation = pl.scan_parquet(DIR2DERIVED / "ventilation.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "endtime"]
    )
    vasopressors = pl.scan_parquet(DIR2DERIVED / "vasoactive_agent.parquet").select(
        [COLNAME_ICUSTAY_ID, "starttime", "endtime"]
    )

    pop = compute_free_days(pop, ventilation, COLNAME_VFD28, COLNAME_MORTALITY_28D,
                            follow_days=28, start_col="starttime", end_col="endtime")
    pop = compute_free_days(pop, vasopressors, COLNAME_VAPFD28, COLNAME_MORTALITY_28D,
                            follow_days=28, start_col="starttime", end_col="endtime")
    return pop
