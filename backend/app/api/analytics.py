from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.area import Area
from app.models.traffic_observation import TrafficObservation

router = APIRouter()


def _observation_status(statuses: set[str]) -> str:
    recognized = statuses & {"actual", "historical"}
    if len(recognized) > 1:
        return "mixed"
    return next(iter(recognized), "unavailable")


def _area_by_name(db: Session, name: str) -> Area:
    area = db.query(Area).filter(
        (Area.name == name.strip().lower().replace(" ", "-"))
        | (Area.display_name.ilike(name.strip()))
    ).first()
    if not area:
        raise HTTPException(status_code=400, detail=f"Area '{name}' not supported.")
    return area


@router.get("/analytics/hourly")
def get_hourly_stats(
    area: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Aggregate actual observations by hour; missing hours remain null."""
    selected_area = _area_by_name(db, area)
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.strftime("%H", TrafficObservation.timestamp).label("hour"),
        func.avg(TrafficObservation.travel_time).label("avg_travel_time"),
        func.avg(TrafficObservation.average_speed).label("avg_speed"),
        func.count(TrafficObservation.id).label("sample_count"),
    ).filter(
        TrafficObservation.area_id == selected_area.id,
        TrafficObservation.timestamp >= cutoff,
        TrafficObservation.data_quality.in_(["actual", "historical"]),
    ).group_by("hour").all()
    statuses = {
        row[0] for row in db.query(TrafficObservation.data_quality).filter(
            TrafficObservation.area_id == selected_area.id,
            TrafficObservation.timestamp >= cutoff,
            TrafficObservation.data_quality.in_(["actual", "historical"]),
        ).distinct().all() if row[0]
    }
    by_hour = {int(row.hour): row for row in rows if row.hour is not None}
    hourly_data = {
        f"{hour:02d}:00": ({
            "avg_travel_time": round(by_hour[hour].avg_travel_time, 2)
            if by_hour[hour].avg_travel_time is not None else None,
            "avg_speed": round(by_hour[hour].avg_speed, 2)
            if by_hour[hour].avg_speed is not None else None,
            "sample_count": by_hour[hour].sample_count,
        } if hour in by_hour else None)
        for hour in range(24)
    }
    count = sum(row.sample_count for row in rows)
    return {
        "area": selected_area.display_name,
        "period_days": days,
        "stat_type": "hourly",
        "data_status": _observation_status(statuses),
        "message": None if count else "Insufficient traffic data",
        "sample_count": count,
        "data_source": "traffic_observations" if count else None,
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "hourly_data": hourly_data,
    }


@router.get("/analytics/areas")
def get_area_summaries(db: Session = Depends(get_db)):
    areas = db.query(Area).filter(Area.is_active.is_(True)).order_by(Area.display_name).all()
    summaries = []
    for area in areas:
        average_time, average_speed, count = db.query(
            func.avg(TrafficObservation.travel_time),
            func.avg(TrafficObservation.average_speed),
            func.count(TrafficObservation.id),
        ).filter(
            TrafficObservation.area_id == area.id,
            TrafficObservation.data_quality.in_(["actual", "historical"]),
        ).one()
        has_data = count > 0
        statuses = {row[0] for row in db.query(TrafficObservation.data_quality).filter(
            TrafficObservation.area_id == area.id,
            TrafficObservation.data_quality.in_(["actual", "historical"]),
        ).distinct().all() if row[0]}
        summaries.append({
            "area": area.display_name,
            "avg_travel_time": round(average_time, 2) if average_time is not None else None,
            "avg_speed": round(average_speed, 2) if average_speed is not None else None,
            "sample_count": count,
            "data_status": _observation_status(statuses) if has_data else "unavailable",
            "message": None if has_data else "Insufficient traffic data",
            "data_source": "traffic_observations" if has_data else None,
        })
    return {"areas": summaries, "count": len(summaries)}
