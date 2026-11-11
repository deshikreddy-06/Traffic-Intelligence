"""Parse and validate externally sourced India traffic observations."""

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routes import is_inside_india
from app.models.area import Area
from app.models.traffic_observation import TrafficObservation

ALIASES = {
    "id": ("observation_id", "record_id", "id"),
    "timestamp": ("observation_timestamp", "timestamp", "datetime", "date_time", "date", "time"),
    "area": ("area_name", "area", "neighbourhood", "neighborhood", "location_name"),
    "road": ("road_name", "road", "street", "street_name"),
    "lat": ("latitude", "lat"),
    "lon": ("longitude", "lon", "lng", "long"),
    "speed": ("average_speed", "avg_speed", "speed", "speed_kmh", "speed_kmph", "speed_kph"),
    "count": ("vehicle_count", "traffic_volume", "vehicle_volume", "count"),
    "density": ("traffic_density", "density", "density_vehicles_per_km"),
}


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().casefold()).strip("_")


def _value(record: dict[str, Any], name: str) -> Any:
    normalized = {_normalize_key(key): value for key, value in record.items()}
    return next((normalized[alias] for alias in ALIASES[name] if alias in normalized), None)


def _parse_records(content: bytes, filename: str) -> list[dict[str, Any]]:
    suffix = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    try:
        if suffix == "csv":
            text = content.decode("utf-8-sig")
            records = list(csv.DictReader(io.StringIO(text)))
            if not records or not records[0]:
                raise ValueError("CSV must contain a header row and at least one record.")
            _validate_headers(records)
            return records
        if suffix in {"json", "geojson"}:
            payload = json.loads(content.decode("utf-8-sig"))
            if isinstance(payload, list):
                _validate_headers(payload)
                return payload
            if not isinstance(payload, dict):
                raise ValueError("JSON must contain an array of observation objects.")
            if payload.get("type") == "FeatureCollection":
                records = []
                for feature in payload.get("features", []):
                    if not isinstance(feature, dict):
                        continue
                    record = dict(feature.get("properties") or {})
                    geometry = feature.get("geometry") or {}
                    if geometry.get("type") == "Point":
                        coordinates = geometry.get("coordinates") or []
                        if len(coordinates) >= 2:
                            record.setdefault("longitude", coordinates[0])
                            record.setdefault("latitude", coordinates[1])
                    records.append(record)
                _validate_headers(records)
                return records
            if isinstance(payload.get("observations"), list):
                _validate_headers(payload["observations"])
                return payload["observations"]
            raise ValueError("JSON must be an observation array or GeoJSON FeatureCollection.")
        raise ValueError("Upload a .csv, .json, or .geojson file.")
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not read traffic dataset: {exc}") from exc


def _validate_headers(records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError("Dataset contains no observation records.")
    keys = {_normalize_key(key) for record in records[:1] if isinstance(record, dict) for key in record}
    required = ("timestamp", "area", "lat", "lon")
    missing = [name for name in required if not any(alias in keys for alias in ALIASES[name])]
    if not any(alias in keys for field in ("speed", "count", "density") for alias in ALIASES[field]):
        missing.append("average_speed, vehicle_count, or traffic_density")
    if missing:
        raise ValueError("Required columns are missing: " + ", ".join(missing))


def _number(value: Any, label: str, minimum: float = 0) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"{label} must be a finite value greater than or equal to {minimum}")
    return parsed


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _source_id(record: dict[str, Any], values: dict[str, Any]) -> str:
    supplied = _value(record, "id")
    if supplied is not None and str(supplied).strip():
        return (str(supplied).strip() + "-" + hashlib.sha256(values.get("source", "").encode()).hexdigest()[:12])[:200]
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    return f"import-{digest}"


def _area_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:80]
    return slug or "dataset-area"


def ingest_records(
    db: Session,
    records: list[dict[str, Any]],
    *,
    source_name: str,
    data_status: str,
) -> dict[str, Any]:
    if data_status not in {"actual", "historical"}:
        raise HTTPException(status_code=422, detail="Data status must be actual or historical; predicted/simulated records cannot be imported.")
    if not records:
        raise HTTPException(status_code=422, detail="Dataset contains no observation records.")
    if len(records) > 100_000:
        raise HTTPException(status_code=413, detail="A dataset may contain at most 100,000 records per import.")

    inserted = duplicates = rejected = 0
    reasons: dict[str, int] = {}
    seen_ids: set[str] = set()
    for row_number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            rejected += 1
            reasons["record is not an object"] = reasons.get("record is not an object", 0) + 1
            continue
        try:
            area_name = str(_value(record, "area") or "").strip()
            road_name = str(_value(record, "road") or "").strip() or None
            if not area_name:
                raise ValueError("area name is missing")
            timestamp = _timestamp(_value(record, "timestamp"))
            latitude = _number(_value(record, "lat"), "latitude", -90)
            longitude = _number(_value(record, "lon"), "longitude", -180)
            if latitude is None or longitude is None or latitude > 90 or longitude > 180:
                raise ValueError("valid latitude and longitude are required")
            if not is_inside_india(latitude, longitude):
                raise ValueError("coordinates are outside India")
            speed = _number(_value(record, "speed"), "average speed")
            vehicle_count = _number(_value(record, "count"), "vehicle count")
            density = _number(_value(record, "density"), "traffic density")
            if speed is None and vehicle_count is None and density is None:
                raise ValueError("at least one measured speed, vehicle count, or density field is required")
            if speed is not None and speed > 250:
                raise ValueError("average speed exceeds 250 km/h")

            clean = {
                "timestamp": timestamp.isoformat(), "area": area_name.casefold(), "road": road_name,
                "lat": round(latitude, 7), "lon": round(longitude, 7),
                "speed": speed, "count": vehicle_count, "density": density,
                "source": source_name.casefold(),
            }
            observation_id = _source_id(record, clean)
            if observation_id in seen_ids or db.query(TrafficObservation.id).filter(TrafficObservation.observation_id == observation_id).first():
                duplicates += 1
                continue
            seen_ids.add(observation_id)

            slug = _area_slug(area_name)
            area = db.query(Area).filter(Area.name == slug).first()
            if area is None:
                # The source gives an area label and observation point, not a centroid.
                # Record the point for the required legacy FK; keep source label separately.
                area = Area(name=slug, display_name=area_name, latitude=latitude, longitude=longitude)
                db.add(area)
                db.flush()
            observation = TrafficObservation(
                observation_id=observation_id,
                timestamp=timestamp,
                area_id=area.id,
                area_name=area_name,
                road_name=road_name,
                latitude=latitude,
                longitude=longitude,
                traffic_volume=vehicle_count,
                vehicle_count=vehicle_count,
                traffic_density=density,
                average_speed=speed,
                data_source=source_name,
                data_quality=data_status,
                notes=f"Imported from source dataset; record {row_number}.",
            )
            db.add(observation)
            inserted += 1
        except (TypeError, ValueError, OverflowError) as exc:
            rejected += 1
            reason = str(exc)
            reasons[reason] = reasons.get(reason, 0) + 1

    db.flush()
    return {
        "received_count": len(records), "imported_count": inserted,
        "duplicate_count": duplicates, "rejected_count": rejected,
        "rejection_reasons": reasons,
    }


def parse_traffic_file(content: bytes, filename: str) -> list[dict[str, Any]]:
    return _parse_records(content, filename)
