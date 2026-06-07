"""Server-side speech-to-text for the Even G2 glasses.

The G2 has no on-device/WebView speech recognition — the glasses-plugin
captures the 4-mic array as 16 kHz mono PCM, wraps it into a WAV and POSTs
it to /api/v1/agent/voice. We transcribe with faster-whisper (lazy-loaded
singleton; CDARS_ASR_MODEL picks the checkpoint, default "base").

Cantonese: whisper large-v3 knows "yue"; smaller checkpoints only "zh".
We try the requested code and degrade gracefully.
"""
from __future__ import annotations

import io
import os
import threading
from typing import Any, Optional

from loguru import logger

_lock = threading.Lock()
_model: Optional[Any] = None
_load_error: Optional[str] = None

#: UI language hint → whisper language code candidates (first that works wins).
LANG_CANDIDATES = {
    "en": ["en"],
    "zh-HK": ["yue", "zh"],
    "zh": ["zh"],
}


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model() -> Any:
    """Lazy singleton — the first transcription pays the model load."""
    global _model, _load_error
    with _lock:
        if _model is not None:
            return _model
        if _load_error:
            raise RuntimeError(_load_error)
        try:
            from faster_whisper import WhisperModel
            name = os.environ.get("CDARS_ASR_MODEL", "base")
            logger.info(f"Loading ASR model '{name}' (faster-whisper) …")
            _model = WhisperModel(name, device="auto", compute_type="auto")
            logger.info("ASR model ready.")
            return _model
        except Exception as e:  # noqa: BLE001
            _load_error = f"ASR model load failed: {e}"
            raise RuntimeError(_load_error) from e


def transcribe(wav_bytes: bytes, lang_hint: str = "en") -> dict:
    """Transcribe a WAV payload. Returns {text, language, engine}."""
    model = _get_model()
    last_err: Optional[Exception] = None
    for code in LANG_CANDIDATES.get(lang_hint, [None]):
        try:
            segments, info = model.transcribe(
                io.BytesIO(wav_bytes), language=code, vad_filter=True, beam_size=5,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return {"text": text, "language": info.language, "engine": "faster-whisper"}
        except ValueError as e:  # unsupported language code on this checkpoint
            last_err = e
            continue
    raise RuntimeError(f"ASR failed for lang '{lang_hint}': {last_err}")
