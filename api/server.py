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
from api.feature_map import payload_to_features
from api.inference import ModelStore

store = ModelStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind_loop(asyncio.get_running_loop())
    # Seed the warehouse first so endpoints work even if the model is slow.
    summary = cdars_service.ensure_seeded()
    logger.info(f"CDARS warehouse ready: {summary}")
    store.load_or_fit()
    cdars_service.set_model_store(store)
    logger.info("Model store wired into CDARS service.")
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


# ── Legacy single-patient prediction API (kept for the dashboard) ───────────
class PatientPayload(BaseModel):
    sofa: float
    sapsii: float
    lactate: float
    vaso: bool
    ventilation: bool
    aki: int = 0
    dialysis: bool = False
    pct: Optional[float] = None
    crp: Optional[float] = None
    wbc: Optional[float] = None
    temperature: Optional[float] = None
    culture_result: str = "pending"
    source_identified: bool = False
    pathogen_identified: bool = False
    antibiotic_days: float = 3.0
    age: float = 65.0
    female: bool = False
    comorbidity: float = 2.0
    immunocompromised: bool = False
    heart_rate: Optional[float] = None
    resp_rate: Optional[float] = None
    spo2: Optional[float] = None
    map: Optional[float] = None
    urine_output: Optional[float] = None
    weight: Optional[float] = None
    treatment_id: str = "continue"


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "models_ready": store.ready, "clients": bus.roles()}


@app.post("/api/v1/predict")
def predict(req: PatientPayload):
    features = payload_to_features(req.model_dump())
    return store.predict(features, req.treatment_id)


@app.post("/api/v1/similar-patients")
def similar_patients(req: PatientPayload):
    features = payload_to_features(req.model_dump())
    return {"patients": store.similar_patients(features)}


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
