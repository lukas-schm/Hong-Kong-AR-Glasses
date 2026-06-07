"""Agent tools: thin wrappers over the CDARS service that also emit live,
plain-language activity events (and HUD-sync side-effects) onto the bus.

Both the deterministic planner and the optional Claude loop call these, so
the monitor shows the same step-by-step progress regardless of engine.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..bus import bus
from ..cdars import service as svc
from ..cdars.db import Database


def _norm_hkid(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


class AgentTools:
    def __init__(self, db: Database, *, source: str = "agent", actor: str = "clinician",
                 lang: str = "en", emit: bool = True):
        self.db = db
        self.source = source
        self.actor = actor
        self.lang = lang
        self.emit = emit
        self._active: Optional[List[Dict[str, Any]]] = None

    def _act(self, kind: str, en: str, zh: str = "", *, detail: str = "",
             rk: Optional[str] = None, ok: Optional[bool] = None) -> None:
        if self.emit:
            bus.activity(kind, en, text_zh=zh or None, detail=detail,
                         reference_key=rk, ok=ok, source=self.source)

    # ── patient lookup against the active worklist ───────────────────────────
    def active(self) -> List[Dict[str, Any]]:
        if self._active is None:
            self._active = svc.active_patients(self.db)
        return self._active

    def find_patient(self, text: str) -> Optional[Dict[str, Any]]:
        self._act("tool", f"Searching CDARS for “{text.strip()}”",
                  f"喺 CDARS 搜尋「{text.strip()}」")
        lower = text.lower()
        hkid_tok = _norm_hkid(re.search(r"[a-z]{1,2}\s?\d{6}", lower).group(0)) if re.search(
            r"[a-z]{1,2}\s?\d{6}", lower) else ""
        best, best_score = None, 0
        for p in self.active():
            score = 0
            if p["nameZh"] and p["nameZh"] in text:
                score += 4
            tokens = p["nameEn"].lower().replace(",", "").split()
            matched = [tk for tk in tokens if re.search(rf"\b{re.escape(tk)}\b", lower)]
            if tokens and tokens[0] in matched:
                score += 1 + len(matched)
            if hkid_tok and len(hkid_tok) >= 4 and _norm_hkid(p["hkid"]).startswith(hkid_tok):
                score += 5
            if score > best_score:
                best, best_score = p, score
        if best:
            self._act("patient", f"Matched {best['nameEn']} ({best['hkid']})",
                      f"配對到 {best['nameZh']}（{best['hkid']}）", rk=best["referenceKey"], ok=True)
        return best

    def open_patient(self, reference_key: str, *, broadcast: bool = True) -> Optional[Dict[str, Any]]:
        rec = svc.patient_record(self.db, reference_key, channel=self.source, actor=self.actor)
        if not rec:
            return None
        self._act("tool", f"Opened CDARS record · {rec['nameEn']} · {rec['hospitalCode']} {rec['ward']['en']}",
                  f"開啟 CDARS 紀錄 · {rec['nameZh']} · {rec['hospitalCode']} {rec['ward']['zh']}",
                  rk=reference_key)
        if broadcast and self.emit:
            # Tell every connected client (glasses + monitor) to open this patient.
            bus.publish({"type": "select", "referenceKey": reference_key, "origin": self.source})
        return rec

    # ── model scoring ────────────────────────────────────────────────────────
    def predict(self, reference_key: str, override: Optional[Dict[str, Any]] = None,
                *, label: str = "") -> Dict[str, Any]:
        self._act("model", f"Scoring treatment arms against the causal model{(' · ' + label) if label else ''}",
                  f"以因果模型評估治療方案{(' · ' + label) if label else ''}", rk=reference_key)
        res = svc.predict_arms(self.db, reference_key, override)
        vals = res.get("values", {})
        if vals:
            tag = "LIVE" if res.get("live") else "cached"
            summary = " · ".join(f"{k}={v}%" for k, v in vals.items())
            self._act("model", f"28-day mortality ({tag}): {summary}",
                      f"28日死亡率（{tag}）：{summary}", rk=reference_key, ok=res.get("live"))
        return res

    def cohort(self, reference_key: str) -> Dict[str, Any]:
        res = svc.cohort_outcomes(self.db, reference_key)
        if res.get("arms"):
            best = res["arms"][0]
            self._act("tool",
                      f"Territory-wide ({res['band']} severity, n={res['n']}): "
                      f"{best['arm']} lowest mortality {best['mortality']}%",
                      f"全港（{res['band']}嚴重程度，n={res['n']}）：{best['arm']} 死亡率最低 {best['mortality']}%",
                      rk=reference_key)
        return res

    def query(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        res = svc.query_cohort(self.db, criteria, actor=self.actor)
        c = res["counts"]
        self._act("tool", f"CDARS extract — {c['episodes']} episodes, {c['patients']} patients, {c['deaths']} deaths",
                  f"CDARS 提取 — {c['episodes']} 次就診、{c['patients']} 名病人、{c['deaths']} 宗死亡")
        return res

    # ── write-back ───────────────────────────────────────────────────────────
    def feed(self, reference_key: str, *, writes: Optional[List[Dict[str, Any]]] = None,
             prescription: Optional[Dict[str, Any]] = None,
             note: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        res = svc.feed_write(self.db, reference_key, writes=writes, prescription=prescription,
                             note=note, source=self.source, actor=self.actor)
        for a in res["applied"]:
            if a["kind"] == "state":
                self._act("db-write", f"Charted to CDARS — {a['label']}: {a['from']} → {a['to']} {a['unit']}".strip(),
                          f"已寫入 CDARS — {a['label']}：{a['from']} → {a['to']} {a['unit']}".strip(),
                          rk=reference_key, ok=True)
            elif a["kind"] == "rx":
                self._act("db-write", f"Prescription {a['action']} — {a['drug']['en']}",
                          f"處方{a['action']} — {a['drug']['zh']}", rk=reference_key, ok=True)
            elif a["kind"] == "note":
                self._act("db-write", f"Clinical note added — “{a['text']}”",
                          f"已加臨床記錄 — 「{a['text']}」", rk=reference_key, ok=True)
        if self.emit:
            bus.data_change(reference_key, fields=[a.get("key") for a in res["applied"] if a.get("key")])
        return res
