"""Traffic observation imports and database-backed statistics."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.ingestion.traffic_files import ingest_records, parse_traffic_file
from app.models.area import Area
from app.models.data_source_metadata import DataSourceMetadata
from app.models.traffic_observation import TrafficObservation
from app.api.routes import is_inside_india

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/traffic/import")
async def import_traffic_dataset(
    file: UploadFile = File(...),
    source_name: str = Form(..., min_length=2, max_length=200),
    source_url: str | None = Form(default=None, max_length=1000),
    collection_period: str = Form(..., min_length=1, max_length=200),
    license_name: str = Form(..., min_length=1, max_length=200),
    data_type: str = Form(default="traffic_observations", max_length=100),
    city_coverage: str = Form(default="India", min_length=1, max_length=200),
    data_status: str = Form(default="historical"),
    db: Session = Depends(get_db),
):
    """Import CSV/JSON/GeoJSON observations with uploader-provided provenance."""
    if data_type.strip().casefold() not in {"traffic_observations", "traffic observations", "road_traffic_observations"}:
        raise HTTPException(status_code=422, detail="Only traffic observation datasets belong in this import endpoint; emissions and other proxies must use a separate dataset registry entry.")
    if "india" not in city_coverage.casefold():
        raise HTTPException(status_code=422, detail="Dataset city coverage must explicitly include India.")
    if source_url and not source_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Source URL must be an HTTP or HTTPS URL.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 20 MB limit.")
    records = parse_traffic_file(content, file.filename or "")

    metadata = db.query(DataSourceMetadata).filter(DataSourceMetadata.source_name == source_name.strip()).first()
    if metadata and metadata.data_type and metadata.data_type not in {"traffic_observations", "traffic observations", "road_traffic_observations"}:
        raise HTTPException(status_code=409, detail="This source is already registered as a non-traffic dataset and cannot be reclassified as traffic observations.")
    if metadata is None:
        metadata = DataSourceMetadata(source_name=source_name.strip(), source_type="dataset")
        db.add(metadata)
    metadata.source_url = source_url
    metadata.data_type = "traffic_observations"
    metadata.city_coverage = city_coverage.strip()
    metadata.geographic_coverage = city_coverage.strip()
    metadata.observation_period = collection_period.strip()
    metadata.license = license_name.strip()
    metadata.available_fields = ", ".join(records[0].keys()) if records else ""
    metadata.permitted_use = "Imported by project operator; license and source provenance supplied with upload."
    metadata.retention_allowed = True
    metadata.last_ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    metadata.imported_at = metadata.last_ingested_at
    metadata.is_active = True
    try:
        summary = ingest_records(db, records, source_name=source_name.strip(), data_status=data_status)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"source_name": source_name.strip(), "data_status": data_status, **summary}


@router.get("/traffic/observations")
def list_traffic_observations(
    area: str | None = Query(default=None, max_length=200),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(TrafficObservation)
    if area:
        query = query.filter(func.lower(func.coalesce(TrafficObservation.area_name, Area.display_name)) == area.strip().casefold())
        query = query.join(Area, TrafficObservation.area_id == Area.id)
    if date_from:
        query = query.filter(TrafficObservation.timestamp >= date_from)
    if date_to:
        query = query.filter(TrafficObservation.timestamp <= date_to)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be earlier than or equal to date_to.")
    total = query.count()
    rows = query.order_by(TrafficObservation.timestamp.desc(), TrafficObservation.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "observations": [{
            "observation_id": row.observation_id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "area_name": row.area_name or row.area.display_name,
            "road_name": row.road_name,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "average_speed_kmh": row.average_speed,
            "vehicle_count": row.vehicle_count if row.vehicle_count is not None else row.traffic_volume,
            "traffic_density": row.traffic_density,
            "congestion_level": row.congestion_level,
            "data_source": row.data_source,
            "data_status": row.data_quality,
            "road_segment": ({
                "segment_id": row.road_segment.segment_id,
                "name": row.road_segment.name,
                "start": [row.road_segment.start_lat, row.road_segment.start_lon],
                "end": [row.road_segment.end_lat, row.road_segment.end_lon],
            } if row.road_segment
                and is_inside_india(row.road_segment.start_lat, row.road_segment.start_lon)
                and is_inside_india(row.road_segment.end_lat, row.road_segment.end_lon)
                and row.data_quality in {"actual", "historical"}
                else None),
        } for row in rows],
    }


@router.get("/traffic/areas/{area_name}/observations")
def observations_by_area(area_name: str, db: Session = Depends(get_db)):
    return list_traffic_observations(area=area_name, offset=0, limit=1000, db=db)


@router.get("/traffic/observations/by-time")
def observations_by_time(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return list_traffic_observations(area=None, date_from=date_from, date_to=date_to, offset=offset, limit=limit, db=db)


@router.get("/traffic/stats")
def traffic_dataset_stats(db: Session = Depends(get_db)):
    base = db.query(
        func.count(TrafficObservation.id),
        func.count(func.distinct(func.coalesce(TrafficObservation.area_name, Area.display_name))),
        func.min(TrafficObservation.timestamp),
        func.max(TrafficObservation.timestamp),
        func.avg(TrafficObservation.average_speed),
        func.avg(func.coalesce(TrafficObservation.vehicle_count, TrafficObservation.traffic_volume)),
    ).join(Area, TrafficObservation.area_id == Area.id).filter(
        TrafficObservation.data_quality.in_(["actual", "historical"]),
        TrafficObservation.data_source.isnot(None),
    ).one()
    sources = db.query(DataSourceMetadata).order_by(DataSourceMetadata.source_name).all()
    count = int(base[0] or 0)
    source_counts = dict(db.query(TrafficObservation.data_source, func.count(TrafficObservation.id)).filter(
        TrafficObservation.data_quality.in_(["actual", "historical"]),
        TrafficObservation.data_source.isnot(None),
    ).group_by(TrafficObservation.data_source).all())
    return {
        "observation_count": count,
        "covered_area_count": int(base[1] or 0),
        "date_range": {"start": base[2].isoformat() if base[2] else None, "end": base[3].isoformat() if base[3] else None},
        "average_recorded_speed_kmh": round(float(base[4]), 2) if base[4] is not None else None,
        "average_recorded_vehicle_count": round(float(base[5]), 2) if base[5] is not None else None,
        "data_status": "historical/actual observations" if count else "unavailable",
        "message": None if count else "No traffic observations available",
        "sources": [{
            "source_name": source.source_name,
            "observation_count": int(source_counts.get(source.source_name, 0)),
            "source_url": source.source_url,
            "collection_period": source.observation_period,
            "license": source.license,
            "data_type": source.data_type or source.source_type,
            "city_coverage": source.city_coverage or source.geographic_coverage,
            "imported_at": source.imported_at.isoformat() if source.imported_at else None,
            "notes": source.notes,
        } for source in sources],
    }


@router.get("/traffic/sources")
def list_dataset_sources(db: Session = Depends(get_db)):
    return traffic_dataset_stats(db)["sources"]
