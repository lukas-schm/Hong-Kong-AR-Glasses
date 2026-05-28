"""FastAPI server for the Antibiotic CDSS."""
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.feature_map import payload_to_features
from api.inference import ModelStore

store = ModelStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load_or_fit()
    yield


app = FastAPI(title="Antibiotic CDSS API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PatientPayload(BaseModel):
    sofa: float
    sapsii: float
    lactate: float
    vaso: bool
    ventilation: bool
    aki: int = 0
    dialysis: bool = False
    pct: Optional[float] = None          # received but not used by model
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
    return {"status": "ok", "models_ready": store.ready}


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
    return {"patients": []}  # static data lives in frontend


@app.post("/api/v1/survey")
def survey(data: Dict[str, Any] = {}):  # noqa: B006
    return {}
