from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class PredictionRequest(BaseModel):
    area: str
    day_of_week: int  # 0-6
    time: str  # HH:MM format
    prediction_horizon: str  # e.g., "1h", "2h", "6h"
    target: str = "travel_time"  # travel_time, speed, congestion

class PredictionResponse(BaseModel):
    prediction_id: str
    area: str
    predicted_value: float
    confidence_score: Optional[float] = None
    prediction_timestamp: datetime
    prediction_horizon: datetime
    model_version: str
    units: str
    target: str
    notes: Optional[str] = None

class TrafficStatsRequest(BaseModel):
    area: str
    stat_type: str = "hourly"  # hourly, daily, weekly
    days: int = 30

class TrafficStatsResponse(BaseModel):
    area: str
    stat_type: str
    period_days: int
    avg_travel_time: Optional[float] = None
    avg_speed: Optional[float] = None
    sample_count: int = 0
    data_source: str
    last_updated: datetime
    hourly_data: Optional[Dict[str, float]] = None
    daily_data: Optional[Dict[str, float]] = None
