from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class RouteRequest(BaseModel):
    origin: str
    destination: str
    departure_time: Optional[datetime] = None
    travel_mode: str = "driving"
    route_preference: str = "traffic_aware"  # shortest, fastest, traffic_aware

class RouteStep(BaseModel):
    instruction: str
    distance: Optional[float] = None
    duration: Optional[float] = None
    road_name: Optional[str] = None

class RouteAlternative(BaseModel):
    route_id: str
    distance: float
    duration: float
    duration_in_traffic: Optional[float] = None
    delay: Optional[float] = None
    is_shortest: bool = False
    is_fastest: bool = False
    steps: List[RouteStep] = []
    overview_polyline: Optional[str] = None

class RouteResponse(BaseModel):
    origin: str
    destination: str
    routes: List[RouteAlternative]
    retrieved_at: datetime
    data_source: str = "google_maps"

class DirectionsRequest(BaseModel):
    origin: str
    destination: str
    route_id: Optional[str] = None

class DirectionsResponse(BaseModel):
    origin: str
    destination: str
    total_distance: float
    total_duration: float
    total_duration_in_traffic: Optional[float] = None
    steps: List[RouteStep]
    overview_polyline: Optional[str] = None
