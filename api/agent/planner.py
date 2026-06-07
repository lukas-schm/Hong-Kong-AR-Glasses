"""Deterministic intent planner — the default agent engine.

Parses an English / Cantonese utterance into one intent, calls the CDARS
tools (emitting live activity), and returns a bilingual reply. Works with no
API key; the optional Claude loop in llm.py wraps the same tools.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..bus import bus
from ..cdars import service as svc
from ..cdars.db import Database
from . import lexicon as lex
from .tools import AgentTools

ARM_LABEL = {
    "continue": {"en": "Continue broad-spectrum", "zh": "繼續廣譜抗生素"},
    "deescalate": {"en": "De-escalate", "zh": "降階治療"},
    "cease": {"en": "Cease antibiotics", "zh": "停用抗生素"},
}


def run_planner(db: Database, text: str, reference_key: Optional[str], *,
                source: str = "voice", actor: str = "clinician",
                lang_hint: str = "en") -> Dict[str, Any]:
    zh = lex.has_cjk(text) or lang_hint == "zh-HK"
    lang = "zh-HK" if zh else "en"
    lower = text.lower()
    tools = AgentTools(db, source=source, actor=actor, lang=lang)

    def L(en: str, zh_t: str) -> str:
        return zh_t if zh else en

    bus.activity("voice", text, source=source)

    def done(intent: str, reply: str, *, rk: Optional[str] = None,
             reply_zh: Optional[str] = None, extra: Optional[Dict] = None) -> Dict[str, Any]:
        bus.activity("intent", intent, source=source)
        bus.activity("reply", reply, text_zh=reply_zh, reference_key=rk or reference_key, source=source)
        out = {"intent": intent, "reply": reply, "referenceKey": rk or reference_key, "lang": lang}
        if extra:
            out.update(extra)
        return out

    cur = reference_key

    # 1 ── open a patient (name / HKID) ──────────────────────────────────────
    found = tools.find_patient(text)
    if found and found["referenceKey"] != cur:
        rec = tools.open_patient(found["referenceKey"])
        sub = found["subtitle"]["zh"] if zh else found["subtitle"]["en"]
        return done(
            "open-patient",
            L(f"Opening {found['nameEn']} {found['nameZh']} ({found['hkid']}) — {sub}",
              f"開啟 {found['nameZh']}（{found['hkid']}）— {sub}"),
            rk=found["referenceKey"],
            extra={"select": found["referenceKey"], "patient": rec},
        )

    # 2 ── show worklist ─────────────────────────────────────────────────────
    if lex.includes_any(text, lower, lex.SHOW_ALL):
        pts = tools.active()
        lines = [f"• {(p['nameZh'] if zh else p['nameEn'])} · {(p['subtitle']['zh'] if zh else p['subtitle']['en'])}"
                 for p in pts]
        return done("show-all",
                    L("Current ICU admissions:\n" + "\n".join(lines),
                      "現時深切治療部住院病人：\n" + "\n".join(lines)),
                    extra={"patients": pts})

    # Territory-wide cohort question — patient-independent, so handle it before
    # requiring a current patient (the per-patient "similar" variant is below).
    wants_similar = lex.includes_any(text, lower, lex.SIMILAR_Q)
    if lex.includes_any(text, lower, lex.COHORT_Q) and not (wants_similar and cur):
        crit = _cohort_criteria(text, lower)
        res = tools.query(crit)
        c = res["counts"]
        dx_desc = svc.cat.ICD9_BY_CODE.get(crit["dxCode"], {}).get("desc", {"en": "matching", "zh": "符合條件"})
        return done("cohort-query",
                    L(f"CDARS territory-wide extract — {c['episodes']} {dx_desc['en']} episodes across "
                      f"{c['patients']} patients, {c['deaths']} deaths.",
                      f"CDARS 全港提取 — {dx_desc['zh']}就診 {c['episodes']} 次、{c['patients']} 名病人、"
                      f"{c['deaths']} 宗死亡。"),
                    extra={"query": res})

    # Everything below needs a current patient.
    if not cur:
        names = ", ".join((p["nameZh"] if zh else p["nameEn"].split(",")[0]) for p in tools.active())
        return done("help",
                    L(f"Say a patient name or HKID to open a record, e.g. {names}. "
                      f"You can also say “show all patients”.",
                      f"講出病人姓名或身份證號碼開啟紀錄，例如：{names}。亦可講「所有病人」。"))

    state = db.query_one("SELECT * FROM patient_state WHERE reference_key = ?", (cur,))
    state = dict(state) if state else {}
    name = _name(db, cur, zh)

    # 3 ── voice charting (write a value) ────────────────────────────────────
    write = lex.parse_write(text, lower)
    if write:
        before = tools.predict(cur, label="baseline")
        tools.feed(cur, writes=[write])
        after = tools.predict(cur, label="after update")
        msg = L(
            f"Recorded {write['label']} = {write['value']} {write['unit']} to {name}'s CDARS record. "
            + _risk_phrase(before, after, zh),
            f"已將 {write['label']} = {write['value']} {write['unit']} 寫入 {name} 嘅 CDARS 紀錄。"
            + _risk_phrase(before, after, zh))
        return done("write-record", msg, extra={"changed": True, "predictions": after})

    # 4 ── antibiotic action (de-escalate / cease / continue) ────────────────
    abx = next((a for a in lex.ABX_ACTIONS if lex.includes_any(text, lower, a["match"])), None)
    if abx:
        before = tools.predict(cur, label="baseline")
        if abx["prescription"]:
            presc = dict(abx["prescription"])
            if presc.get("drug") == "*":      # stop every active antibiotic
                for code in svc.cat.BROAD_DRUGS + svc.cat.NARROW_DRUGS:
                    tools.feed(cur, prescription={"action": "stop", "drug": code})
            else:
                tools.feed(cur, prescription=presc)
        tools.feed(cur, writes=[{"key": "active_treatment_id", "label": "Antibiotic plan",
                                 "unit": "", "value": abx["arm"]}])
        after = tools.predict(cur, label="after change")
        desc = abx["describe"]["zh"] if zh else abx["describe"]["en"]
        return done("abx-change",
                    L(f"{desc} for {name}. " + _risk_phrase(before, after, zh),
                      f"{desc}（{name}）。" + _risk_phrase(before, after, zh)),
                    extra={"changed": True, "predictions": after})

    # 5 ── named drug start ──────────────────────────────────────────────────
    drug = lex.parse_drug_start(text, lower)
    if drug:
        tools.feed(cur, prescription=drug)
        dn = svc.cat.DRUG_BY_CODE.get(drug["drug"], {}).get("name", {"en": drug["drug"], "zh": drug["drug"]})
        return done("rx-start",
                    L(f"Started {dn['en']} for {name} — written to CDARS.",
                      f"已為 {name} 開始 {dn['zh']} — 已寫入 CDARS。"),
                    extra={"changed": True})

    # 6 ── simulated intervention (scored, not written) ──────────────────────
    iv = next((i for i in lex.INTERVENTIONS if lex.includes_any(text, lower, i["match"])), None)
    if iv:
        override = _apply_delta(state, iv["delta"])
        base = tools.predict(cur, label="baseline")
        sim = tools.predict(cur, override=override, label=iv["id"])
        desc = iv["describe"]["zh"] if zh else iv["describe"]["en"]
        lines = [desc + ("。" if zh else ".")]
        bv = _best(base); sv = _best(sim)
        if bv is not None and sv is not None:
            delta = sv[1] - bv[1]
            lines.append(L(f"Model 28-day mortality {sv[1]}% (baseline {bv[1]}%, {_signed(delta)} pp).",
                           f"模型28日死亡率 {sv[1]}%（基線 {bv[1]}%，{_signed(delta)} 個百分點）。"))
            lines.append(_verdict(delta, zh))
        if iv.get("caveat"):
            lines.append((("註：" + iv["caveat"]["zh"]) if zh else ("Note: " + iv["caveat"]["en"])))
        return done("intervention", "\n".join(lines), extra={"predictions": sim, "simulated": True})

    # 7 ── vital / data query ────────────────────────────────────────────────
    vq = next((v for v in lex.VITAL_QUERIES if lex.includes_any(text, lower, v["match"])), None)
    if vq and state:
        val = state.get(vq["field"])
        label = vq["label"]["zh"] if zh else vq["label"]["en"]
        unit = vq["unit"]["zh"] if zh else vq["unit"]["en"]
        return done("vital-query", f"{label}: {val} {unit}".strip())

    # 8 ── mortality / recommendation ────────────────────────────────────────
    if lex.includes_any(text, lower, lex.MORTALITY_Q + lex.RECOMMEND_Q):
        preds = tools.predict(cur, label="current")
        coh = tools.cohort(cur)
        vals = preds.get("values", {})
        if vals:
            best = min(vals, key=vals.get)
            lines = [
                L(f"Current model 28-day mortality for {name}:", f"{name} 而家嘅模型28日死亡率："),
                *[f"• {ARM_LABEL[a]['zh' if zh else 'en']}: {vals[a]}%" for a in ("continue", "deescalate", "cease") if a in vals],
                L(f"Recommended: {ARM_LABEL[best]['en']} (lowest predicted risk).",
                  f"建議：{ARM_LABEL[best]['zh']}（預測風險最低）。"),
            ]
            if coh.get("arms"):
                cb = coh["arms"][0]
                lines.append(L(
                    f"Territory-wide, {cb['arm']} had the lowest mortality "
                    f"({cb['mortality']}%, {cb['survived']}/{cb['n']} survived) in {coh['band']}-severity patients.",
                    f"全港數據中，{coh['band']}嚴重程度病人以 {cb['arm']} 死亡率最低"
                    f"（{cb['mortality']}%，{cb['survived']}/{cb['n']} 存活）。"))
            return done("mortality", "\n".join(lines), extra={"predictions": preds, "cohort": coh})

    # 9 ── similar territory-wide patients (current patient's severity band) ──
    if wants_similar or lex.includes_any(text, lower, lex.COHORT_Q):
        coh = tools.cohort(cur)
        if coh.get("arms"):
            cb = coh["arms"][0]; cw = coh["arms"][-1]
            return done("cohort-similar",
                        L(f"Among {coh['n']} territory-wide {coh['band']}-severity patients, "
                          f"{cb['arm']} had the lowest 28-day mortality ({cb['mortality']}%, "
                          f"{cb['survived']}/{cb['n']} survived) and {cw['arm']} the highest "
                          f"({cw['mortality']}%).",
                          f"全港 {coh['n']} 名 {coh['band']}嚴重程度病人中，"
                          f"{cb['arm']} 28日死亡率最低（{cb['mortality']}%，{cb['survived']}/{cb['n']} 存活），"
                          f"{cw['arm']} 最高（{cw['mortality']}%）。"),
                        extra={"cohort": coh})

    # 10 ── help ──────────────────────────────────────────────────────────────
    return done("help",
                L("I can query vitals (“SOFA score”), chart a value (“set lactate to 3.2”), "
                  "change antibiotics (“de-escalate”, “stop antibiotics”), simulate interventions "
                  "(“give albumin”), report mortality, answer cohort questions, or open another patient.",
                  "我可以查詢數據（「SOFA評分」）、記錄數值（「乳酸記低 3.2」）、更改抗生素"
                  "（「降階」「停抗生素」）、模擬介入（「俾白蛋白」）、報告死亡率、回答隊列問題，"
                  "或者開啟另一位病人。"))


# ── helpers ──────────────────────────────────────────────────────────────────
def _name(db: Database, rk: str, zh: bool) -> str:
    v = db.query_one("SELECT name_en, name_zh FROM identity_vault WHERE reference_key = ?", (rk,))
    if not v:
        return rk
    return v["name_zh"] if zh else v["name_en"].split(",")[0]


def _apply_delta(state: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, dv in delta.items():
        if k in ("vaso", "ventilation", "dialysis"):
            out[k] = 1
        else:
            out[k] = round((state.get(k) or 0) + dv, 2)
    return out


def _best(preds: Dict[str, Any]):
    vals = preds.get("values", {})
    if not vals:
        return None
    arm = min(vals, key=vals.get)
    return arm, vals[arm]


def _signed(x: float) -> str:
    return f"+{x}" if x > 0 else str(x)


def _risk_phrase(before: Dict[str, Any], after: Dict[str, Any], zh: bool) -> str:
    b, a = _best(before), _best(after)
    if not a:
        return ""
    if not b or b[1] == a[1]:
        return (f"模型重新計算後建議 {ARM_LABEL[a[0]]['zh']}，預測死亡率 {a[1]}%。" if zh
                else f"The model now favours {ARM_LABEL[a[0]]['en']} at {a[1]}% predicted mortality.")
    delta = a[1] - b[1]
    arrow = "↓" if delta < 0 else "↑"
    return (f"模型重新計算：建議方案風險由 {b[1]}% {arrow} {a[1]}%。" if zh
            else f"Model re-ran: recommended risk {b[1]}% {arrow} {a[1]}%.")


def _verdict(delta: float, zh: bool) -> str:
    if delta < 0:
        return "✓ 模型顯示有改善。" if zh else "✓ The model suggests this improves the outlook."
    if delta == 0:
        return "— 無明顯變化。" if zh else "— No meaningful change predicted."
    return "⚠ 風險上升，建議重新考慮。" if zh else "⚠ The model predicts increased risk — reconsider."


def _cohort_criteria(text: str, lower: str) -> Dict[str, Any]:
    crit: Dict[str, Any] = {"dxCode": "", "episodeType": "", "cluster": "", "sex": "",
                            "ageMin": None, "ageMax": None, "admittedFrom": "", "admittedTo": "",
                            "deathsOnly": False}
    if "septic shock" in lower or "休克" in text:
        crit["dxCode"] = "785.52"
    elif "severe sepsis" in lower or "嚴重敗血" in text:
        crit["dxCode"] = "995.92"
    elif "sepsis" in lower or "敗血" in text:
        crit["dxCode"] = "995.91"
    elif "pneumonia" in lower or "肺炎" in text:
        crit["dxCode"] = "486"
    if "death" in lower or "died" in lower or "死" in text:
        crit["deathsOnly"] = True
    return crit
