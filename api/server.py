"""FastAPI server for the CDARS CDSS.

Hosts three surfaces over one backend:
  · the legacy single-patient prediction API (/api/v1/predict …)
  · the CDARS warehouse REST API (/api/v1/cdars/…)
  · the agent command endpoint (/api/v1/agent/command)
and a realtime WebSocket bus (/api/v1/ws) that keeps the AR glasses, the
model monitor and the CDARS workbench mirror-synced and streams plain-language
activity events.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from api.agent.router import router as agent_router
from api.bus import RELAY_TYPES, bus
from api.cdars import service as cdars_service
from api.cdars.router import router as cdars_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind_loop(asyncio.get_running_loop())
    summary = cdars_service.ensure_seeded()
    logger.info(f"CDARS warehouse ready: {summary}")
    # No live ML model in the AR build: three-arm predictions are served from the
    # cached values in the CDARS warehouse (cdars.service.predict_arms) and the
    # frontend's cachedArmValues fallback. The legacy /predict API was removed.
    yield


app = FastAPI(title="CDARS CDSS API", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cdars_router)
app.include_router(agent_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "models_ready": False, "clients": bus.roles()}


@app.get("/api/v1/exemplar-patients")
def exemplar_patients():
    return {"patients": []}


@app.post("/api/v1/survey")
def survey(data: Dict[str, Any] = {}):  # noqa: B006
    return {}


# ── Realtime bus ─────────────────────────────────────────────────────────────
@app.websocket("/api/v1/ws")
async def ws_endpoint(ws: WebSocket):
    role = ws.query_params.get("role", "client")
    await bus.connect(ws, role)
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype in RELAY_TYPES:
                msg["origin"] = role
                await bus.broadcast(msg, exclude=ws)
            elif mtype == "activity":
                await bus.broadcast(msg)
    except WebSocketDisconnect:
        bus.disconnect(ws)
        await bus.broadcast_presence()
    except Exception:
        bus.disconnect(ws)
        await bus.broadcast_presence()
