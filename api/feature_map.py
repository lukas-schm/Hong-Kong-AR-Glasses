"""Maps the frontend API payload dict to pipeline feature names."""
from typing import Any, Dict, Optional


def payload_to_features(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Convert frontend PatientState payload to pipeline feature dict.

    Keys match pipeline confounder variable names from causal_graph.yaml.
    Missing fields are left as None — imputed with training median by ModelStore.
    """
    crp = payload.get("crp")
    culture = payload.get("culture_result", "pending")

    return {
        # Illness severity
        "SOFA_at_decision":         float(payload["sofa"]) if payload.get("sofa") is not None else None,
        "SAPSII":                   float(payload["sapsii"]) if payload.get("sapsii") is not None else None,
        "lactate_at_decision":      float(payload["lactate"]) if payload.get("lactate") is not None else None,
        "vasopressors_at_decision": 1.0 if payload.get("vaso") else 0.0,
        "MAP_at_decision":          float(payload["map"]) if payload.get("map") is not None else None,

        # Infection certainty (model uses CRP; pct is not used)
        "CRP_at_decision":          float(crp) if crp is not None else None,
        "WBC_at_decision":          float(payload["wbc"]) if payload.get("wbc") is not None else None,
        "temperature_at_decision":  float(payload["temperature"]) if payload.get("temperature") is not None else None,
        "positive_blood_culture":   1.0 if culture == "positive" else 0.0,
        "culture_gram_positive":    None,  # not in frontend — imputed
        "culture_gram_negative":    None,
        "infection_source_pulmonary":  None,
        "infection_source_urinary":    None,
        "infection_source_abdominal":  None,

        # Organ dysfunction
        "AKI_stage_at_decision":    float(payload.get("aki", 0)),
        "pf_ratio_at_decision":     None,
        "ventilation_at_decision":  1.0 if payload.get("ventilation") else 0.0,
        "creatinine_at_decision":   None,
        "bilirubin_at_decision":    None,

        # Treatment history
        "days_on_abx":              float(payload.get("antibiotic_days", 3)),
        "prior_carbapenem":         None,
        "prior_glycopeptide":       None,
        "prior_betalactam":         None,
        "prior_aminoglycoside":     None,

        # Trajectory — not available from single snapshot; all imputed
        "delta_SOFA_0_72h":         None,
        "delta_WBC_0_72h":          None,
        "delta_lactate_0_72h":      None,
        "delta_temperature_0_72h":  None,
        "delta_creatinine_0_72h":   None,

        # Demographics
        "admission_age":            float(payload.get("age", 65)),
        "Female":                   1.0 if payload.get("female") else 0.0,
        "immunosuppressed":         1.0 if payload.get("immunocompromised") else 0.0,
        "charlson_comorbidity_index": float(payload.get("comorbidity", 2)),
        "emergency_admission":      None,
    }
