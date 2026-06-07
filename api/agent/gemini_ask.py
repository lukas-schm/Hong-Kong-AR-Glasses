"""
Voice Q&A about the open patient, powered by Gemini.

The G2 glasses capture a spoken question (16 kHz mono PCM → WAV) and POST it to
/api/v1/agent/ask?patient=<key>. We send that audio straight to Gemini
(gemini-3.5-flash, generateContent) with:

  • a system instruction carrying THIS patient's CDARS data, and
  • Google Search grounding enabled (current guidelines / drug info),

so a single call does transcription *and* reasoning and returns a short text
answer for the glasses to show in a text window. Key lives in GEMINI_API_KEY.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from loguru import logger

MODEL = os.environ.get("CDARS_GEMINI_MODEL", "gemini-3.5-flash")


def available() -> bool:
    """True if the SDK is importable and an API key is set."""
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return False
    try:
        import google.genai  # noqa: F401
        return True
    except ImportError:
        return False


def _patient_brief(record: Optional[Dict[str, Any]]) -> str:
    """Compact, model-friendly summary of the open patient (or a note if none)."""
    if not record:
        return "No patient is currently open; answer only general clinical questions."
    keep = {
        k: record.get(k)
        for k in ("referenceKey", "nameEn", "age", "sex", "ward", "subtitle",
                  "profile", "outcomes", "redFlags")
        if record.get(k) is not None
    }
    return json.dumps(keep, ensure_ascii=False, default=str)


def _system_instruction(record: Optional[Dict[str, Any]], lang: str) -> str:
    reply_lang = "Traditional Chinese (Cantonese-appropriate)" if lang.startswith("zh") else "English"
    return (
        "You are a clinical decision-support assistant embedded in ICU smart glasses "
        "(Even Realities G2). A clinician asks a spoken question about the patient below. "
        f"Answer in {reply_lang}, in at most 2 short sentences — the display is a tiny "
        "576x288 heads-up screen, so be concise and plain. Ground time-sensitive facts "
        "(drug dosing, guidelines, interactions) with Google Search when useful. Use only "
        "the patient values provided; do not invent labs or vitals. This is a "
        "decision-support aid, not a directive; flag uncertainty briefly.\n\n"
        "PATIENT (CDARS record, JSON):\n" + _patient_brief(record)
        + _graph_context(record)
    )


def _graph_context(record: Optional[Dict[str, Any]]) -> str:
    """GraphRAG: ground the answer in the patient's knowledge-graph neighborhood
    (diagnoses, cultures, labs, and same-arm cohort mortality). Best-effort —
    returns '' if the KG hasn't been built, so voice never depends on it."""
    try:
        from kg import query as kg
        rk = (record or {}).get("referenceKey")
        if rk and kg.available():
            ctx = kg.patient_context(str(rk))
            if ctx:
                return "\n\n" + ctx
    except Exception as e:  # noqa: BLE001
        logger.warning(f"KG context unavailable: {e}")
    return ""


def ask(wav_bytes: bytes, record: Optional[Dict[str, Any]], lang: str = "en") -> Dict[str, Any]:
    """Send the spoken question + patient context to Gemini; return {answer, sources, engine}."""
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(record, lang),
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            "This audio is the clinician's question about the patient. Answer it.",
        ],
        config=config,
    )

    answer = (getattr(resp, "text", None) or "").strip()
    sources = _grounding_sources(resp)
    if not answer:
        answer = "No answer produced."
    logger.info(f"Gemini Q&A ({MODEL}): {len(wav_bytes)}B audio → {len(answer)} chars, "
                f"{len(sources)} sources")
    return {"answer": answer, "sources": sources, "engine": MODEL}


def _grounding_sources(resp: Any) -> list[Dict[str, str]]:
    """Best-effort extraction of grounding citations (title + uri)."""
    out: list[Dict[str, str]] = []
    try:
        meta = resp.candidates[0].grounding_metadata
        for chunk in (getattr(meta, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None):
                out.append({"title": getattr(web, "title", "") or web.uri, "uri": web.uri})
    except (AttributeError, IndexError, TypeError):
        pass
    return out[:3]
