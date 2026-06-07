"""REST API over the CDARS warehouse (mounted at /api/v1/cdars)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..bus import bus
from . import service as svc
from .db import get_db

router = APIRouter(prefix="/api/v1/cdars", tags=["cdars"])


class Criteria(BaseModel):
    dxCode: str = ""
    episodeType: str = ""
    cluster: str = ""
    sex: str = ""
    ageMin: Optional[int] = None
    ageMax: Optional[int] = None
    admittedFrom: str = ""
    admittedTo: str = ""
    deathsOnly: bool = False
    actor: str = "researcher"


class RecordWrite(BaseModel):
    key: str
    label: str = ""
    unit: str = ""
    value: Any


class Prescription(BaseModel):
    action: str                 # start | stop | switch
    drug: str                   # HA drug code
    dose: Optional[str] = None
    route: Optional[str] = "IV"
    frequency: Optional[str] = None


class Note(BaseModel):
    text: str
    author: str = "Clinician"
    lang: str = "en"


class FeedRequest(BaseModel):
    referenceKey: str
    writes: List[RecordWrite] = []
    prescription: Optional[Prescription] = None
    note: Optional[Note] = None
    source: str = "voice"
    actor: str = "clinician"
    silent: bool = False        # skip bus broadcast (agent handles its own)


@router.get("/stats")
def get_stats() -> Dict[str, Any]:
    return svc.stats(get_db())


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return svc.catalog()


@router.get("/active")
def get_active() -> Dict[str, Any]:
    return {"patients": svc.active_patients(get_db())}


@router.post("/query")
def post_query(c: Criteria) -> Dict[str, Any]:
    db = get_db()
    result = svc.query_cohort(db, c.model_dump(exclude={"actor"}), actor=c.actor)
    bus.activity(
        "tool",
        f"CDARS extract — {result['counts']['episodes']} episodes, "
        f"{result['counts']['patients']} patients, {result['counts']['deaths']} deaths",
        text_zh=f"CDARS 提取 — {result['counts']['episodes']} 次就診、"
                f"{result['counts']['patients']} 名病人、{result['counts']['deaths']} 宗死亡",
        detail=f"dx={c.dxCode or 'any'} cluster={c.cluster or 'all'}",
        source="portal",
    )
    return result


@router.get("/patient/{ident}")
def get_patient(ident: str, channel: str = "portal", actor: str = "clinician") -> Dict[str, Any]:
    rec = svc.patient_record(get_db(), ident, channel=channel, actor=actor)
    if not rec:
        raise HTTPException(status_code=404, detail="patient not found")
    return rec


@router.get("/patient/{ident}/predict")
def get_predict(ident: str) -> Dict[str, Any]:
    db = get_db()
    rk = svc.resolve_key(db, ident)
    if not rk:
        raise HTTPException(status_code=404, detail="patient not found")
    return svc.predict_arms(db, rk)


@router.get("/patient/{ident}/cohort")
def get_cohort(ident: str) -> Dict[str, Any]:
    db = get_db()
    rk = svc.resolve_key(db, ident)
    if not rk:
        raise HTTPException(status_code=404, detail="patient not found")
    return svc.cohort_outcomes(db, rk)


@router.post("/feed")
def post_feed(req: FeedRequest) -> Dict[str, Any]:
    db = get_db()
    rk = svc.resolve_key(db, req.referenceKey)
    if not rk:
        raise HTTPException(status_code=404, detail="patient not found")
    result = svc.feed_write(
        db, rk,
        writes=[w.model_dump() for w in req.writes],
        prescription=req.prescription.model_dump() if req.prescription else None,
        note=req.note.model_dump() if req.note else None,
        source=req.source, actor=req.actor,
    )
    if not req.silent:
        for a in result["applied"]:
            if a["kind"] == "state":
                bus.activity("db-write", f"Charted {a['label']}: {a['from']} → {a['to']} {a['unit']}".strip(),
                             reference_key=rk, source=req.source)
            elif a["kind"] == "rx":
                bus.activity("db-write", f"Prescription {a['action']}: {a['drug']['en']}",
                             text_zh=f"處方{a['action']}：{a['drug']['zh']}", reference_key=rk, source=req.source)
            elif a["kind"] == "note":
                bus.activity("db-write", f"Note added: {a['text']}", reference_key=rk, source=req.source)
        bus.data_change(rk, fields=[a.get("key") for a in result["applied"] if a.get("key")])
    return result


@router.get("/audit")
def get_audit(n: int = Query(40, ge=1, le=200)) -> Dict[str, Any]:
    return {"entries": svc.audit_tail(get_db(), n)}
