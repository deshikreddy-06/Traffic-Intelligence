"""Areas endpoint for nationwide India location search support."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models.area import Area
from app.schemas.area import Area as AreaSchema
from pydantic import BaseModel, Field

router = APIRouter()


class LocationSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=250)
    limit: int = Field(default=10, ge=1, le=20)


class LocationSearchResult(BaseModel):
    place_id: str
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    types: List[str] = []


@router.get("/areas", response_model=List[AreaSchema])
def get_areas(db: Session = Depends(get_db)):
    """Return all supported areas (legacy Hyderabad areas for backward compatibility)."""
    areas = db.query(Area).filter(Area.is_active == True).all()
    return areas


@router.get("/areas/{area_id}")
def get_area(area_id: int, db: Session = Depends(get_db)):
    """Return details for a specific area."""
    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    return area


@router.get("/areas/{area_id}/traffic")
def get_area_traffic(area_id: int, db: Session = Depends(get_db)):
    """Return available traffic observations for an area."""
    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    
    from app.models.traffic_observation import TrafficObservation
    observations = db.query(TrafficObservation).filter(
        TrafficObservation.area_id == area_id
    ).order_by(TrafficObservation.timestamp.desc()).limit(100).all()
    statuses = {row.data_quality for row in observations if row.data_quality in {"actual", "historical"}}
    data_status = "mixed" if len(statuses) > 1 else next(iter(statuses), "unavailable")
    
    return {
        "area": area.display_name,
        "data_status": data_status,
        "message": None if observations else "Insufficient traffic data",
        "observation_count": len(observations),
        "observations": observations
    }


@router.get("/areas/{area_id}/history")
def get_area_history(area_id: int, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """Return historical analytics for a supported area."""
    area = db.query(Area).filter(Area.id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    
    from app.models.historical_stats import HistoricalStats
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    stats = db.query(HistoricalStats).filter(
        HistoricalStats.area_id == area_id,
        HistoricalStats.observation_period_end >= cutoff,
    ).all()
    
    return {
        "area": area.display_name,
        "period_days": days,
        "data_status": "historical" if stats else "unavailable",
        "message": None if stats else "Insufficient traffic data",
        "stats": stats
    }


@router.post("/areas/search")
async def search_locations(request: LocationSearchRequest):
    """Search for locations anywhere in India using Google Places API (New)."""
    from app.api.routes import geocode_google_places, get_place_details
    import httpx
    
    query = request.query.strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
    
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            geocode_result = await geocode_google_places(client, query)
            
            place_id = geocode_result.get("place_id")
            if place_id:
                place_details = await get_place_details(client, place_id)
                if place_details:
                    return {
                        "results": [{
                            "place_id": place_id,
                            "name": place_details.get("displayName") or geocode_result["name"],
                            "formatted_address": place_details.get("formattedAddress") or geocode_result["name"],
                            "latitude": place_details.get("latitude", geocode_result["lat"]),
                            "longitude": place_details.get("longitude", geocode_result["lon"]),
                            "types": [],
                        }]
                    }
            
            return {
                "results": [{
                    "place_id": "",
                    "name": geocode_result["name"],
                    "formatted_address": geocode_result["name"],
                    "latitude": geocode_result["lat"],
                    "longitude": geocode_result["lon"],
                    "types": [],
                }]
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Location search failed: {str(e)}")


@router.get("/areas/states")
def get_indian_states():
    """Return list of Indian states and union territories for reference."""
    states = [
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
        "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
        "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal",
        "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
        "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"
    ]
    return {"states": sorted(states)}