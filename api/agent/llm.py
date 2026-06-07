"""Optional Claude tool-use loop.

When ANTHROPIC_API_KEY is set, Claude orchestrates the CDARS tools to answer
the clinician — the same tools the deterministic planner uses, so the monitor
shows identical step-by-step activity. Any failure returns None and the
router falls back to the planner, so the demo never hard-depends on the API.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ..bus import bus
from ..cdars import service as svc
from ..cdars.db import Database
from . import lexicon as lex
from .tools import AgentTools

MODEL = os.environ.get("CDARS_AGENT_MODEL", "claude-sonnet-4-6")
MAX_ROUNDS = 6

TOOL_DEFS = [
    {"name": "open_patient",
     "description": "Find a current ICU patient by name or HKID and open their CDARS record on the glasses. Returns the record summary and makes them the active patient.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_record",
     "description": "Get the active patient's current vitals, labs, diagnoses, medications and treatment plan from CDARS.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "predict_arms",
     "description": "Score the three antibiotic arms (continue/deescalate/cease) for the active patient against the trained causal model, returning predicted 28-day mortality. Optionally pass an intervention id (albumin|fluids|vasopressor|ventilation) to simulate it without writing to the record.",
     "input_schema": {"type": "object", "properties": {"intervention": {"type": "string"}}}},
    {"name": "chart_value",
     "description": "Write a dictated vital or lab value into the active patient's CDARS record (e.g. lactate, map, sofa, crp, wbc, spo2, temperature).",
     "input_schema": {"type": "object",
                      "properties": {"field": {"type": "string"}, "value": {"type": "number"}},
                      "required": ["field", "value"]}},
    {"name": "change_antibiotics",
     "description": "Change the active patient's antibiotic plan in CDARS. action is one of: deescalate (narrow spectrum), cease (stop antibiotics), continue (keep broad-spectrum).",
     "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["deescalate", "cease", "continue"]}}, "required": ["action"]}},
    {"name": "cohort_query",
     "description": "Run a territory-wide CDARS cohort extract and return aggregate counts. Optional ICD-9-CM dx code and deaths_only filter.",
     "input_schema": {"type": "object", "properties": {"dx_code": {"type": "string"}, "deaths_only": {"type": "boolean"}}}},
    {"name": "similar_outcomes",
     "description": "Return territory-wide 28-day mortality by antibiotic arm for patients of similar severity to the active patient.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _system(db: Database, rk: Optional[str], zh: bool) -> str:
    worklist = "; ".join(f"{p['nameEn']} ({p['hkid']}, {p['subtitle']['en']})"
                         for p in svc.active_patients(db))
    cur = ""
    if rk:
        v = db.query_one("SELECT name_en, hkid FROM identity_vault WHERE reference_key = ?", (rk,))
        if v:
            cur = f"\nActive patient: {v['name_en']} ({v['hkid']}, ref {rk})."
    lang_note = ("Reply in Traditional Chinese (Cantonese, zh-Hant-HK)."
                 if zh else "Reply in English.")
    return (
        "You are the CDARS voice agent for a Hospital Authority intensivist wearing Even Realities "
        "G2 AR glasses. CDARS is the territory-wide HA clinical data warehouse. Use the tools to "
        "retrieve from and write to CDARS and to score the causal antibiotic-continuation model. "
        "Be concise and clinical — your reply is read aloud on a heads-up display, so keep it to a "
        "few short sentences. Always ground numbers in tool results; never invent values. "
        f"{lang_note}\n"
        f"Current ICU worklist: {worklist}.{cur}"
    )


def run_llm(db: Database, text: str, reference_key: Optional[str], *,
            source: str = "voice", actor: str = "clinician",
            lang_hint: str = "en") -> Optional[Dict[str, Any]]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:
        return None

    zh = lex.has_cjk(text) or lang_hint == "zh-HK"
    lang = "zh-HK" if zh else "en"
    tools = AgentTools(db, source=source, actor=actor, lang=lang)
    ctx = {"rk": reference_key}

    bus.activity("voice", text, source=source)

    def run_tool(name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        rk = ctx["rk"]
        if name == "open_patient":
            found = tools.find_patient(inp.get("query", ""))
            if not found:
                return {"found": False}
            rec = tools.open_patient(found["referenceKey"])
            ctx["rk"] = found["referenceKey"]
            return {"found": True, "referenceKey": found["referenceKey"], "name": found["nameEn"],
                    "subtitle": found["subtitle"]["en"], "plan": rec["outcomes"]["recommendedAction"],
                    "profile": rec["profile"]}
        if not rk:
            return {"error": "no active patient — call open_patient first"}
        if name == "get_record":
            rec = svc.patient_record(db, rk, audit=False)
            return {"name": rec["nameEn"], "diagnoses": [d["display"]["en"] for d in rec["diagnoses"]],
                    "medications": [m["display"]["en"] for m in rec["medications"] if m["status"] == "active"],
                    "labs": {l["code"]: f"{l['value']} {l['unit']}{(' ' + l['flag']) if l['flag'] else ''}" for l in rec["labs"]},
                    "profile": rec["profile"]}
        if name == "predict_arms":
            iv_id = inp.get("intervention")
            override = None
            if iv_id:
                iv = next((i for i in lex.INTERVENTIONS if i["id"] == iv_id), None)
                if iv:
                    s = dict(db.query_one("SELECT * FROM patient_state WHERE reference_key = ?", (rk,)))
                    override = {k: (1 if k in ("vaso", "ventilation", "dialysis") else round((s.get(k) or 0) + dv, 2))
                               for k, dv in iv["delta"].items()}
            res = tools.predict(rk, override=override, label=iv_id or "current")
            return {"mortality_by_arm": res.get("values", {}), "live": res.get("live"),
                    "simulated_intervention": iv_id}
        if name == "chart_value":
            field = inp.get("field", "").lower().replace(" ", "_")
            fdef = next((f for f in lex.FIELD_LEXICON if f["key"] == field
                         or field in [m.lower() for m in f["match"]]), None)
            if not fdef:
                return {"error": f"unknown field {field}"}
            tools.feed(rk, writes=[{"key": fdef["key"], "label": fdef["label"],
                                    "unit": fdef["unit"], "value": inp.get("value")}])
            res = tools.predict(rk, label="after update")
            return {"charted": fdef["label"], "value": inp.get("value"), "new_mortality": res.get("values", {})}
        if name == "change_antibiotics":
            act = next((a for a in lex.ABX_ACTIONS if a["arm"] == inp.get("action")), None)
            if not act:
                return {"error": "unknown action"}
            if act["prescription"]:
                presc = dict(act["prescription"])
                if presc.get("drug") == "*":
                    for code in svc.cat.BROAD_DRUGS + svc.cat.NARROW_DRUGS:
                        tools.feed(rk, prescription={"action": "stop", "drug": code})
                else:
                    tools.feed(rk, prescription=presc)
            tools.feed(rk, writes=[{"key": "active_treatment_id", "label": "Antibiotic plan",
                                    "unit": "", "value": act["arm"]}])
            res = tools.predict(rk, label="after change")
            return {"new_plan": act["arm"], "new_mortality": res.get("values", {})}
        if name == "cohort_query":
            crit = {"dxCode": inp.get("dx_code", ""), "deathsOnly": bool(inp.get("deaths_only"))}
            res = tools.query(crit)
            return res["counts"]
        if name == "similar_outcomes":
            return tools.cohort(rk)
        return {"error": f"unknown tool {name}"}

    client = anthropic.Anthropic()
    messages: List[Dict[str, Any]] = [{"role": "user", "content": text}]
    final_text = ""
    try:
        for _ in range(MAX_ROUNDS):
            resp = client.messages.create(
                model=MODEL, max_tokens=700,
                system=_system(db, ctx["rk"], zh), tools=TOOL_DEFS, messages=messages)
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            if text_blocks:
                final_text = "\n".join(t for t in text_blocks if t).strip()
            if resp.stop_reason != "tool_use" or not tool_uses:
                break
            messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            results = []
            for tu in tool_uses:
                try:
                    out = run_tool(tu.name, tu.input or {})
                except Exception as exc:  # surface tool errors to the model
                    out = {"error": str(exc)}
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(out, ensure_ascii=False)})
            messages.append({"role": "user", "content": results})
    except Exception:
        return None

    if not final_text:
        return None
    bus.activity("intent", "claude-agent", source=source)
    bus.activity("reply", final_text, reference_key=ctx["rk"], source=source)
    return {"intent": "claude-agent", "reply": final_text, "referenceKey": ctx["rk"],
            "lang": lang, "select": ctx["rk"] if ctx["rk"] != reference_key else None}
