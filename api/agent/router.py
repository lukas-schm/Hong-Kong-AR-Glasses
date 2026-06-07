"""Agent command endpoint (mounted at /api/v1/agent)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..cdars import service as svc
from ..cdars.db import get_db
from . import asr, gemini_ask, llm, planner

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class Command(BaseModel):
    text: str
    referenceKey: Optional[str] = None
    source: str = "voice"          # voice | chat | glasses
    actor: str = "clinician"
    lang: str = "en"               # 'en' | 'zh-HK' (hint; CJK auto-detected too)
    engine: Optional[str] = None   # force 'planner' or 'llm'


@router.get("/engine")
def engine() -> Dict[str, Any]:
    return {
        "llmAvailable": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "model": os.environ.get("CDARS_AGENT_MODEL", "claude-sonnet-4-6"),
        "default": "llm" if os.environ.get("ANTHROPIC_API_KEY") else "planner",
    }


@router.post("/voice")
async def voice(request: Request, lang: str = "en") -> Dict[str, Any]:
    """Transcribe a WAV utterance from the G2 glasses (16 kHz mono PCM).

    The glasses-plugin POSTs raw audio/wav and feeds the transcript back
    through /command — this endpoint only does speech-to-text.
    """
    if not asr.available():
        raise HTTPException(503, "ASR unavailable: pip install faster-whisper")
    wav = await request.body()
    if len(wav) < 1024:
        raise HTTPException(400, "empty or truncated audio payload")
    try:
        return await run_in_threadpool(asr.transcribe, wav, lang)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/ask")
async def ask(request: Request, patient: str = "", lang: str = "en") -> Dict[str, Any]:
    """Voice Q&A about the open patient (transcription + reasoning in one Gemini call).

    The glasses POST raw audio/wav of a spoken question plus ?patient=<key>. We
    load that patient's CDARS record, hand it + the audio to Gemini with Google
    Search grounding, and return {answer, sources} for the glasses text window.
    """
    if not gemini_ask.available():
        raise HTTPException(503, "Gemini unavailable: set GEMINI_API_KEY and `pip install google-genai`")
    wav = await request.body()
    if len(wav) < 1024:
        raise HTTPException(400, "empty or truncated audio payload")
    db = get_db()
    rk = svc.resolve_key(db, patient) if patient else None
    record = svc.patient_record(db, rk) if rk else None
    try:
        return await run_in_threadpool(gemini_ask.ask, wav, record, lang)
    except Exception as e:  # noqa: BLE001 — surface any SDK/network error to the glasses
        raise HTTPException(502, f"Gemini error: {e}") from e


@router.post("/command")
def command(cmd: Command) -> Dict[str, Any]:
    db = get_db()
    rk = svc.resolve_key(db, cmd.referenceKey) if cmd.referenceKey else None

    use_llm = cmd.engine != "planner" and bool(os.environ.get("ANTHROPIC_API_KEY"))
    result: Optional[Dict[str, Any]] = None
    if use_llm:
        result = llm.run_llm(db, cmd.text, rk, source=cmd.source, actor=cmd.actor, lang_hint=cmd.lang)
    if result is None:
        result = planner.run_planner(db, cmd.text, rk, source=cmd.source, actor=cmd.actor, lang_hint=cmd.lang)
        result["engine"] = "planner"
    else:
        result["engine"] = "llm"
    return result
