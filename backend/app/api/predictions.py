from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.area import Area
from app.models.prediction_record import PredictionRecord

router = APIRouter()


class PredictionRequest(BaseModel):
    area: str = Field(min_length=1)
    day_of_week: int = Field(ge=0, le=6)
    time: str
    prediction_horizon: str
    target: str = "travel_time"


@router.post("/predictions/traffic")
def predict_traffic(request: PredictionRequest, db: Session = Depends(get_db)):
    """Return an explicit unavailable status until a validated model exists."""
    area = db.query(Area).filter(
        (Area.name == request.area.strip().lower().replace(" ", "-"))
        | (Area.display_name.ilike(request.area.strip()))
    ).first()
    if not area:
        raise HTTPException(status_code=400, detail=f"Area '{request.area}' is not supported.")
    return {
        "status": "unavailable",
        "message": "Insufficient traffic data",
        "area": area.display_name,
        "target": request.target,
        "prediction_timestamp": datetime.utcnow().isoformat() + "Z",
        "predicted_value": None,
        "confidence_score": None,
        "model_version": None,
    }


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, db: Session = Depends(get_db)):
    record = db.query(PredictionRecord).filter(
        PredictionRecord.prediction_id == prediction_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return {
        "prediction_id": record.prediction_id,
        "area": record.area.display_name if record.area else None,
        "predicted_value": record.predicted_value,
        "confidence_score": record.confidence_score,
        "prediction_timestamp": record.prediction_timestamp,
        "prediction_horizon": record.prediction_horizon,
        "model_version": record.model_version,
        "target": record.prediction_target,
        "data_status": "predicted",
        "notes": record.notes,
    }
