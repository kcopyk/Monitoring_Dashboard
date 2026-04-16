from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field
from typing import Literal

from fastapi.middleware.cors import CORSMiddleware
from app.monitoring_api import router as monitoring_router
from app.web.inference_service import log_prediction
from src.monitoring.orchestrator import run_orchestrator_from_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],  # allow both localhost and 127.0.0.1 for Vite dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(monitoring_router)


class PredictRequest(BaseModel):
    predicted_class: Literal["beverages", "snacks"]
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: float | None = None
    image_base64: str | None = None


@app.post("/predict")
def predict(payload: PredictRequest, background_tasks: BackgroundTasks):
    prediction_id = log_prediction(
        image=None,
        predicted_class=payload.predicted_class,
        confidence=payload.confidence,
        latency_ms=payload.latency_ms,
    )
    background_tasks.add_task(run_orchestrator_from_db)
    return {
        "status": "ok",
        "prediction_id": prediction_id,
        "orchestrator_queued": True,
    }

@app.get("/")
def root():
    return {"message": "ML Monitoring API is running"}