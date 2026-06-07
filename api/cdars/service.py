"""Service layer over the CDARS warehouse.

Assembles JSON-ready records (bilingual displays resolved from the
catalogues), runs cohort extracts/aggregates, scores treatment arms against
the trained causal model, computes territory-wide stratified outcomes, and
applies voice/agent write-back — all with audit logging.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import catalog as cat
from .db import Database, get_db

# The trained causal model is injected by the API on startup (shared instance).
_store: Any = None


def set_model_store(store: Any) -> None:
    global _store
    _store = store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
# Catalogues / warehouse stats
# ─────────────────────────────────────────────────────────────────────────────
def catalog() -> Dict[str, Any]:
    return {
        "clusters": [{"code": c, "name": cat.CLUSTERS[c]} for c in cat.CLUSTERS],
        "hospitals": cat.HOSPITALS,
        "episodeTypes": [{"code": k, "name": v} for k, v in cat.EPISODE_TYPES.items()],
        "specialties": [{"code": k, "name": v} for k, v in cat.SPECIALTIES.items()],
        "icd9": [{"code": d["code"], "desc": d["desc"], "sepsis": d["sepsis"]} for d in cat.ICD9],
        "bnf": [{"code": k, "desc": v} for k, v in cat.BNF_SECTIONS.items()],
        "drugs": cat.DRUGS,
        "labs": cat.LAB_DEFS,
    }


def stats(db: Database) -> Dict[str, Any]:
    span = db.query_one("SELECT MIN(admission_date) lo, MAX(admission_date) hi FROM episode")
    by_cluster = db.query(
        "SELECT cluster, COUNT(*) n FROM episode GROUP BY cluster ORDER BY n DESC")
    by_type = db.query(
        "SELECT episode_type, COUNT(*) n FROM episode GROUP BY episode_type ORDER BY n DESC")
    return {
        "patients": db.count("patient"),
        "active": db.count("patient", "active = 1"),
        "episodes": db.count("episode"),
        "diagnoses": db.count("diagnosis"),
        "prescriptions": db.count("prescription"),
        "labs": db.count("lab_result"),
        "deaths": db.count("patient", "dod IS NOT NULL"),
        "sepsisEpisodes": db.count(
            "diagnosis", "code IN (%s)" % ",".join("?" * len(cat.SEPSIS_CODES)),
            cat.SEPSIS_CODES),
        "clusters": len(cat.CLUSTERS),
        "hospitals": len(cat.HOSPITALS),
        "span": {"from": (span or {}).get("lo"), "to": (span or {}).get("hi")},
        "byCluster": by_cluster,
        "byType": by_type,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Active admissions (re-identifiable demo cohort)
# ─────────────────────────────────────────────────────────────────────────────
def active_patients(db: Database) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT v.reference_key, v.hkid, v.name_en, v.name_zh, v.hospital, v.ward_en, v.ward_zh, "
        "p.sex, p.age, c.arm "
        "FROM identity_vault v JOIN patient p ON p.reference_key = v.reference_key "
        "LEFT JOIN abx_course c ON c.reference_key = v.reference_key "
        "WHERE p.active = 1 ORDER BY v.reference_key")
    out = []
    for r in rows:
        meta = _meta(db, r["reference_key"])
        out.append({
            "referenceKey": r["reference_key"],
            "hkid": r["hkid"],
            "nameEn": r["name_en"],
            "nameZh": r["name_zh"],
            "sex": r["sex"],
            "age": r["age"],
            "hospitalCode": r["hospital"],
            "cluster": cat.cluster_of(r["hospital"]),
            "ward": {"en": r["ward_en"], "zh": r["ward_zh"]},
            "arm": r["arm"],
            "subtitle": meta.get("subtitle", {"en": "", "zh": ""}),
            "tags": meta.get("tags", []),
        })
    return out


def _meta(db: Database, reference_key: str) -> Dict[str, Any]:
    row = db.query_one("SELECT meta FROM active_meta WHERE reference_key = ?", (reference_key,))
    return json.loads(row["meta"]) if row else {}


def resolve_key(db: Database, ident: str) -> Optional[str]:
    """Accept a reference key or an HKID and return the reference key."""
    ident = (ident or "").strip()
    if not ident:
        return None
    if db.query_one("SELECT 1 FROM patient WHERE reference_key = ?", (ident,)):
        return ident
    norm = "".join(ch for ch in ident.upper() if ch.isalnum())
    for r in db.query("SELECT reference_key, hkid FROM identity_vault"):
        if "".join(ch for ch in r["hkid"].upper() if ch.isalnum()).startswith(norm):
            return r["reference_key"]
    return None


# ── state-row ↔ camelCase profile / model payload ───────────────────────────
def _yn(v: Any) -> str:
    return "YES" if int(v or 0) else "NO"


def state_to_profile(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sofa": s["sofa"], "sapsii": s["sapsii"], "lactate": s["lactate"],
        "vaso": _yn(s["vaso"]), "ventilation": _yn(s["ventilation"]),
        "aki": int(s["aki"] or 0), "dialysis": _yn(s["dialysis"]),
        "pct": s["pct"], "crp": s["crp"], "wbc": s["wbc"], "temperature": s["temperature"],
        "cultureResult": s["culture_result"],
        "sourceIdentified": _yn(s["source_identified"]),
        "pathogenIdentified": _yn(s["pathogen_identified"]),
        "antibioticDays": s["antibiotic_days"],
        "age": s["age"], "female": _yn(s["female"]), "comorbidity": s["comorbidity"],
        "immunocompromised": _yn(s["immunocompromised"]),
        "heartRate": s["heart_rate"], "respRate": s["resp_rate"], "spo2": s["spo2"],
        "map": s["map"], "urineOutput": s["urine_output"], "weight": s["weight"],
        "activeTreatmentId": s["active_treatment_id"],
        "treatmentInGraph": True, "chartVisible": True,
    }


def _payload(s: Dict[str, Any], arm: str) -> Dict[str, Any]:
    return {
        "sofa": s["sofa"], "sapsii": s["sapsii"], "lactate": s["lactate"],
        "vaso": bool(s["vaso"]), "ventilation": bool(s["ventilation"]),
        "aki": int(s["aki"] or 0), "dialysis": bool(s["dialysis"]),
        "crp": s["crp"], "wbc": s["wbc"], "temperature": s["temperature"],
        "culture_result": s["culture_result"],
        "source_identified": bool(s["source_identified"]),
        "pathogen_identified": bool(s["pathogen_identified"]),
        "antibiotic_days": s["antibiotic_days"], "age": s["age"],
        "female": bool(s["female"]), "comorbidity": s["comorbidity"],
        "immunocompromised": bool(s["immunocompromised"]),
        "heart_rate": s["heart_rate"], "resp_rate": s["resp_rate"], "spo2": s["spo2"],
        "map": s["map"], "urine_output": s["urine_output"], "weight": s["weight"],
        "treatment_id": arm,
    }


def predict_arms(db: Database, reference_key: str,
                 override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score all three arms against the trained model; cached fallback offline."""
    s = db.query_one("SELECT * FROM patient_state WHERE reference_key = ?", (reference_key,))
    if not s:
        return {"values": {}, "live": False}
    s = dict(s)
    if override:
        s.update(override)
    if _store is not None and getattr(_store, "ready", False):
        try:
            from ..feature_map import payload_to_features
            vals = {}
            for arm in ("continue", "deescalate", "cease"):
                feats = payload_to_features(_payload(s, arm))
                res = _store.predict(feats, arm)
                vals[arm] = round(float(res["withTreatment"]))
            return {"values": vals, "live": True}
        except Exception:
            pass
    meta = _meta(db, reference_key).get("cached", {})
    vals = {k: meta.get(k) for k in ("continue", "deescalate", "cease") if meta.get(k) is not None}
    return {"values": vals, "live": False}


# ─────────────────────────────────────────────────────────────────────────────
# Full patient record assembly
# ─────────────────────────────────────────────────────────────────────────────
def patient_record(db: Database, ident: str, *, channel: str = "portal",
                   actor: str = "clinician", audit: bool = True) -> Optional[Dict[str, Any]]:
    rk = resolve_key(db, ident)
    if not rk:
        return None
    p = db.query_one("SELECT * FROM patient WHERE reference_key = ?", (rk,))
    vault = db.query_one("SELECT * FROM identity_vault WHERE reference_key = ?", (rk,))
    state = db.query_one("SELECT * FROM patient_state WHERE reference_key = ?", (rk,))
    meta = _meta(db, rk)

    diagnoses = [
        {"system": "ICD-9-CM", "code": d["code"], "rank": d["rank"],
         "display": cat.ICD9_BY_CODE.get(d["code"], {}).get("desc", {"en": d["code"], "zh": d["code"]})}
        for d in db.query(
            "SELECT DISTINCT code, rank FROM diagnosis WHERE reference_key = ? ORDER BY rank", (rk,))
    ]
    medications = [
        {"system": "BNF", "bnf": m["bnf"], "code": m["drug_code"], "status": m["status"],
         "display": cat.DRUG_BY_CODE.get(m["drug_code"], {}).get("name", {"en": m["drug_code"], "zh": m["drug_code"]}),
         "detail": {"en": f"{m['dose'] or ''} {m['route'] or ''} {m['frequency'] or ''}".strip(),
                    "zh": f"{m['dose'] or ''} {m['route'] or ''} {m['frequency'] or ''}".strip()}}
        for m in db.query(
            "SELECT * FROM prescription WHERE reference_key = ? ORDER BY start_date DESC, id", (rk,))
    ]
    # Latest value per lab test.
    labs = [
        {"code": l["test_code"],
         "name": cat.LAB_BY_CODE.get(l["test_code"], {}).get("name", {"en": l["test_code"], "zh": l["test_code"]}),
         "value": l["value"], "unit": l["unit"], "flag": l["flag"], "collected": l["collected"]}
        for l in db.query(
            "SELECT test_code, value, unit, flag, MAX(collected) collected FROM lab_result "
            "WHERE reference_key = ? GROUP BY test_code ORDER BY test_code", (rk,))
    ]
    micro = [
        {"specimen": m["specimen"], "result": m["result"],
         "organism": cat.ORGANISMS.get(m["organism"], {"en": m["organism"], "zh": m["organism"]}),
         "collected": m["collected"], "resulted": m["resulted"]}
        for m in db.query(
            "SELECT * FROM micro_result WHERE reference_key = ? ORDER BY collected", (rk,))
    ]
    allergies = [
        {"code": a["code"], "display": {"en": f"{a['substance_en']} — {a['reaction_en']}",
                                        "zh": f"{a['substance_zh']} — {a['reaction_zh']}"}}
        for a in db.query("SELECT * FROM allergy WHERE reference_key = ?", (rk,))
    ]
    encounters = [
        {"date": e["admission_date"], "discharge": e["discharge_date"],
         "facility": f"{e['cluster']}/{e['hospital']}",
         "type": {"en": f"{cat.EPISODE_TYPES.get(e['episode_type'], {}).get('en', e['episode_type'])} · {cat.SPECIALTIES.get(e['specialty'], {}).get('en', e['specialty'])}",
                  "zh": f"{cat.EPISODE_TYPES.get(e['episode_type'], {}).get('zh', e['episode_type'])} · {cat.SPECIALTIES.get(e['specialty'], {}).get('zh', e['specialty'])}"}}
        for e in db.query(
            "SELECT * FROM episode WHERE reference_key = ? ORDER BY admission_date DESC", (rk,))
    ]
    vitals = db.query(
        "SELECT taken, hr, rr, sbp, map, spo2, temp FROM vital_sign "
        "WHERE reference_key = ? ORDER BY taken", (rk,))
    notes = db.query(
        "SELECT author, note_time, lang, text, source FROM clinical_note "
        "WHERE reference_key = ? ORDER BY note_time DESC LIMIT 20", (rk,))

    cached = meta.get("cached", {})
    record = {
        "referenceKey": rk,
        "hkid": vault["hkid"] if vault else None,
        "nameEn": vault["name_en"] if vault else None,
        "nameZh": vault["name_zh"] if vault else None,
        "ccc": vault["ccc"] if vault else None,
        "dob": vault["dob"] if vault else None,
        "sex": p["sex"],
        "age": p["age"],
        "active": bool(p["active"]),
        "hospitalCode": vault["hospital"] if vault else None,
        "cluster": cat.cluster_of(vault["hospital"]) if vault else None,
        "ward": {"en": vault["ward_en"], "zh": vault["ward_zh"]} if vault else None,
        "sourceSystem": "HA-CMS",
        "subtitle": meta.get("subtitle", {"en": "", "zh": ""}),
        "tags": meta.get("tags", []),
        "diagnoses": diagnoses,
        "medications": medications,
        "labs": labs,
        "micro": micro,
        "allergies": allergies,
        "encounters": encounters,
        "vitals": vitals,
        "notes": notes,
        "outcomes": {
            "continue": cached.get("continue"),
            "deescalate": cached.get("deescalate"),
            "cease": cached.get("cease"),
            "recommendedAction": cached.get("rec", "continue"),
            "recommendation": meta.get("recommendation", {"en": "", "zh": ""}),
        },
        "profile": state_to_profile(dict(state)) if state else {},
    }
    if audit:
        db.audit(actor, "read", reference_key=rk, channel=channel,
                 detail=f"opened record {rk}")
    return record


# ─────────────────────────────────────────────────────────────────────────────
# Territory-wide stratified outcomes (real numbers behind "similar patients")
# ─────────────────────────────────────────────────────────────────────────────
def cohort_outcomes(db: Database, reference_key: str) -> Dict[str, Any]:
    s = db.query_one("SELECT sofa, lactate, culture_result FROM patient_state WHERE reference_key = ?",
                     (reference_key,))
    if not s:
        return {"band": "unknown", "arms": [], "n": 0}
    sofa, lact, cult = s["sofa"], s["lactate"], s["culture_result"]
    shock = (lact or 0) >= 4 or (sofa or 0) >= 12
    if shock:
        band, where, params = "high", "sofa >= 10", ()
    elif (sofa or 0) <= 6 and (lact or 0) < 3:
        band, where, params = "low", "sofa <= 7 AND lactate < 3.5 AND culture = ?", (cult if cult != "pending" else "positive",)
    else:
        band, where, params = "moderate", "sofa BETWEEN 6 AND 11", ()
    rows = db.query(
        f"SELECT arm, COUNT(*) n, SUM(mortality_28d) deaths FROM abx_course "
        f"WHERE mortality_28d IS NOT NULL AND {where} GROUP BY arm", params)
    arms = []
    total = 0
    for r in rows:
        n, deaths = int(r["n"]), int(r["deaths"] or 0)
        total += n
        arms.append({
            "arm": r["arm"], "n": n, "deaths": deaths, "survived": n - deaths,
            "mortality": round(100.0 * deaths / n, 1) if n else 0.0,
        })
    arms.sort(key=lambda a: a["mortality"])
    return {"band": band, "arms": arms, "n": total}


# ─────────────────────────────────────────────────────────────────────────────
# Cohort extract (de-identified line listing + aggregates)
# ─────────────────────────────────────────────────────────────────────────────
_DRUG_FOR_ARM = {"continue": "MER1G", "deescalate": "CRO2G", "cease": "AMC12"}
SAMPLE_CAP = 250


def query_cohort(db: Database, c: Dict[str, Any], *, actor: str = "researcher") -> Dict[str, Any]:
    where: List[str] = ["d.rank = 1"]
    params: List[Any] = []
    if c.get("dxCode"):
        where.append("d.code = ?"); params.append(c["dxCode"])
    if c.get("episodeType"):
        where.append("e.episode_type = ?"); params.append(c["episodeType"])
    if c.get("cluster"):
        where.append("e.cluster = ?"); params.append(c["cluster"])
    if c.get("sex"):
        where.append("p.sex = ?"); params.append(c["sex"])
    if c.get("ageMin") is not None:
        where.append("p.age >= ?"); params.append(c["ageMin"])
    if c.get("ageMax") is not None:
        where.append("p.age <= ?"); params.append(c["ageMax"])
    if c.get("admittedFrom"):
        where.append("e.admission_date >= ?"); params.append(c["admittedFrom"])
    if c.get("admittedTo"):
        where.append("e.admission_date <= ?"); params.append(c["admittedTo"])
    if c.get("deathsOnly"):
        where.append("p.dod IS NOT NULL")
    clause = " AND ".join(where)

    base = (
        "FROM episode e "
        "JOIN patient p ON p.reference_key = e.reference_key "
        "JOIN diagnosis d ON d.episode_id = e.episode_id "
        "LEFT JOIN abx_course ac ON ac.reference_key = e.reference_key "
        f"WHERE {clause}"
    )
    agg = db.query_one(
        f"SELECT COUNT(*) episodes, COUNT(DISTINCT e.reference_key) patients, "
        f"SUM(CASE WHEN p.dod IS NOT NULL THEN 1 ELSE 0 END) deaths {base}", params)

    rows = db.query(
        "SELECT e.reference_key, p.sex, p.age, e.episode_type, e.admission_date, e.cluster, "
        "e.hospital, e.specialty, d.code dx, ac.arm, p.dod, p.active, "
        "(SELECT test_code FROM lab_result WHERE episode_id = e.episode_id LIMIT 1) lab_code, "
        "(SELECT value FROM lab_result WHERE episode_id = e.episode_id LIMIT 1) lab_val, "
        "(SELECT unit FROM lab_result WHERE episode_id = e.episode_id LIMIT 1) lab_unit, "
        "(SELECT hkid FROM identity_vault WHERE reference_key = e.reference_key) hkid "
        f"{base} ORDER BY e.admission_date DESC LIMIT {SAMPLE_CAP}", params)

    listing = []
    for r in rows:
        drug_code = _DRUG_FOR_ARM.get(r["arm"] or "continue", "MER1G")
        drug = cat.DRUG_BY_CODE.get(drug_code, {})
        dx = cat.ICD9_BY_CODE.get(r["dx"], {})
        listing.append({
            "referenceKey": r["reference_key"], "sex": r["sex"], "age": r["age"],
            "episodeType": r["episode_type"], "admissionDate": r["admission_date"],
            "cluster": r["cluster"], "hospital": r["hospital"], "specialty": r["specialty"],
            "dxCode": r["dx"], "dxDesc": dx.get("desc", {"en": r["dx"], "zh": r["dx"]}),
            "arm": r["arm"], "bnf": drug.get("bnf", ""),
            "drug": drug.get("name", {"en": "", "zh": ""}),
            "labTest": r["lab_code"], "labValue": (f"{r['lab_val']} {r['lab_unit']}" if r["lab_val"] is not None else ""),
            "death": r["dod"] is not None, "deathDate": r["dod"],
            "active": bool(r["active"]),
            "linkedHkid": r["hkid"],
        })

    n_ep = int(agg["episodes"]) if agg else 0
    db.audit(actor, "query", channel="portal",
             detail=f"cohort extract: {n_ep} episodes, criteria={json.dumps(c, ensure_ascii=False)}")
    return {
        "counts": {
            "episodes": n_ep,
            "patients": int(agg["patients"]) if agg else 0,
            "deaths": int(agg["deaths"] or 0) if agg else 0,
        },
        "listing": listing,
        "truncated": n_ep > SAMPLE_CAP,
        "cap": SAMPLE_CAP,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Write-back (voice / agent charting and prescription changes)
# ─────────────────────────────────────────────────────────────────────────────
_STATE_FIELDS = {
    "sofa", "sapsii", "lactate", "vaso", "ventilation", "aki", "dialysis",
    "pct", "crp", "wbc", "temperature", "culture_result", "source_identified",
    "pathogen_identified", "antibiotic_days", "age", "female", "comorbidity",
    "immunocompromised", "heart_rate", "resp_rate", "spo2", "map",
    "urine_output", "weight", "active_treatment_id",
}


def feed_write(
    db: Database,
    reference_key: str,
    *,
    writes: Optional[List[Dict[str, Any]]] = None,
    prescription: Optional[Dict[str, Any]] = None,
    note: Optional[Dict[str, Any]] = None,
    source: str = "voice",
    actor: str = "clinician",
) -> Dict[str, Any]:
    """Apply dictated changes to the record and audit them. Returns the
    applied changes (for plain-language echo) plus a refreshed lab snapshot."""
    rk = reference_key
    applied: List[Dict[str, Any]] = []
    ep = db.query_one(
        "SELECT episode_id FROM episode WHERE reference_key = ? AND discharge_date IS NULL "
        "ORDER BY admission_date DESC LIMIT 1", (rk,))
    episode_id = ep["episode_id"] if ep else None

    for w in (writes or []):
        field = w.get("key")
        if field not in _STATE_FIELDS:
            continue
        prev = db.query_one(f"SELECT {field} AS v FROM patient_state WHERE reference_key = ?", (rk,))
        from_val = prev["v"] if prev else None
        db.execute(
            f"UPDATE patient_state SET {field} = ?, updated_at = ? WHERE reference_key = ?",
            (w.get("value"), _now(), rk))
        # Mirror numeric vitals/labs into their longitudinal tables.
        lab_map = {"lactate": "LACT", "crp": "CRP", "wbc": "WBC", "pct": "PCT"}
        if field in lab_map:
            code = lab_map[field]
            db.execute(
                "INSERT INTO lab_result (episode_id, reference_key, test_code, value, unit, flag, collected) "
                "VALUES (?,?,?,?,?,?,?)",
                (episode_id, rk, code, w.get("value"), cat.LAB_BY_CODE[code]["unit"],
                 cat.lab_flag(code, float(w.get("value", 0))), _now()))
        applied.append({"kind": "state", "key": field, "label": w.get("label", field),
                        "from": from_val, "to": w.get("value"), "unit": w.get("unit", "")})
        db.audit(actor, "write", reference_key=rk, channel=source,
                 detail=f"{field}: {from_val} → {w.get('value')}")

    if prescription:
        act = prescription.get("action")  # 'start' | 'stop' | 'switch'
        drug_code = prescription.get("drug")
        drug = cat.DRUG_BY_CODE.get(drug_code, {"bnf": "", "name": {"en": drug_code, "zh": drug_code}})
        if act == "stop" and drug_code:
            db.execute(
                "UPDATE prescription SET status = 'stopped', end_date = ? "
                "WHERE reference_key = ? AND drug_code = ? AND status = 'active'",
                (_now()[:10], rk, drug_code))
            applied.append({"kind": "rx", "action": "stop", "drug": drug["name"]})
        elif act in ("start", "switch") and drug_code:
            if act == "switch":
                # stop current broad-spectrum, then start the new drug.
                db.execute(
                    "UPDATE prescription SET status = 'stopped', end_date = ? "
                    "WHERE reference_key = ? AND status = 'active' AND drug_code IN (%s)"
                    % ",".join("?" * len(cat.BROAD_DRUGS)),
                    (_now()[:10], rk, *cat.BROAD_DRUGS))
            db.execute(
                "INSERT INTO prescription (episode_id, reference_key, bnf, drug_code, dose, route, "
                "frequency, start_date, status) VALUES (?,?,?,?,?,?,?,?,'active')",
                (episode_id, rk, drug["bnf"], drug_code, prescription.get("dose"),
                 prescription.get("route", "IV"), prescription.get("frequency"), _now()[:10]))
            applied.append({"kind": "rx", "action": act, "drug": drug["name"]})
        db.audit(actor, "write", reference_key=rk, channel=source,
                 detail=f"prescription {act} {drug_code}")

    if note and note.get("text"):
        db.execute(
            "INSERT INTO clinical_note (episode_id, reference_key, author, note_time, lang, text, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (episode_id, rk, note.get("author", "Clinician"), _now(),
             note.get("lang", "en"), note["text"], source))
        applied.append({"kind": "note", "text": note["text"]})
        db.audit(actor, "write", reference_key=rk, channel=source, detail="clinical note added")

    return {"referenceKey": rk, "applied": applied}


def audit_tail(db: Database, n: int = 40) -> List[Dict[str, Any]]:
    return db.query(
        "SELECT ts, actor, action, reference_key, channel, detail FROM audit_log "
        "ORDER BY id DESC LIMIT ?", (n,))


def ensure_seeded() -> Dict[str, int]:
    from .seed import seed
    return seed(get_db())
