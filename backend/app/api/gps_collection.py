"""Opt-in, foreground-only collection of individual GPS-derived speeds.

Samples describe one consenting device's movement, not vehicle counts,
road-wide speeds, or representative traffic measurements.
"""

import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.routes import is_inside_india
from app.core.database import get_db
from app.models.gps_collection_session import GpsCollectionSession
from app.models.gps_speed_observation import GpsSpeedObservation

router = APIRouter()
CONSENT_VERSION = "gps-foreground-consent-v1"
SOURCE = "consented_foreground_browser_gps"
MAX_ACCURACY_METERS = 25.0
MAX_SPEED_KMH = 120.0
MIN_INTERVAL_SECONDS = 3.0
MAX_INTERVAL_SECONDS = 120.0
ACTIVE_SESSION_TTL = timedelta(hours=1)


class StartRequest(BaseModel):
    consent_confirmed: bool
    consent_version: str = Field(default=CONSENT_VERSION, max_length=50)


class ReadingRequest(BaseModel):
    observation_id: UUID
    timestamp: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(gt=0, le=1000)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="GPS timestamp must include a timezone.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    term = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(term), math.sqrt(max(0.0, 1 - term)))


def _authorized_session(session_id: UUID, authorization: str | None, db: Session, *, active: bool) -> GpsCollectionSession:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="A valid GPS session bearer token is required.")
    session = db.query(GpsCollectionSession).filter(GpsCollectionSession.session_id == str(session_id)).first()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if session is None or not hmac.compare_digest(session.token_hash, token_hash):
        raise HTTPException(status_code=403, detail="GPS session does not belong to this bearer token.")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session.active and session.updated_at and now - session.updated_at > ACTIVE_SESSION_TTL:
        session.active = False
        session.stopped_at = now
        session.last_timestamp = session.last_latitude = session.last_longitude = session.last_accuracy_meters = None
        db.commit()
    if active and not session.active:
        raise HTTPException(status_code=409, detail="GPS collection session is not active. Start a new session with consent.")
    return session


def _clear_baseline(session: GpsCollectionSession) -> None:
    session.last_timestamp = None
    session.last_latitude = None
    session.last_longitude = None
    session.last_accuracy_meters = None


@router.post("/traffic/gps-sessions/{session_id}/start")
def start_gps_session(session_id: UUID, request: StartRequest, db: Session = Depends(get_db)):
    if not request.consent_confirmed:
        raise HTTPException(status_code=422, detail="Explicit consent is required before GPS collection can start.")
    if request.consent_version != CONSENT_VERSION:
        raise HTTPException(status_code=422, detail="Consent text version is out of date. Refresh the page and review the current consent.")
    key = str(session_id)
    if db.query(GpsCollectionSession).filter(GpsCollectionSession.session_id == key).first():
        raise HTTPException(status_code=409, detail="This GPS session identifier has already been used. Start a new session.")
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(GpsCollectionSession(
        session_id=key,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        consent_version=CONSENT_VERSION,
        consented_at=now,
        active=True,
        updated_at=now,
    ))
    db.commit()
    return {"session_id": key, "session_token": token, "active": True, "source": SOURCE, "message": "Consent recorded for this foreground session."}


@router.post("/traffic/gps-sessions/{session_id}/readings")
def submit_gps_reading(session_id: UUID, request: ReadingRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    session = _authorized_session(session_id, authorization, db, active=True)
    timestamp = _utc(request.timestamp)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if timestamp < now - timedelta(minutes=5) or timestamp > now + timedelta(minutes=1):
        _clear_baseline(session)
        db.commit()
        raise HTTPException(status_code=422, detail="GPS timestamp is stale or in the future. Check device time and retry.")
    try:
        inside = is_inside_india(request.latitude, request.longitude)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="India boundary data is unavailable; GPS readings cannot be accepted.") from exc
    if not inside:
        _clear_baseline(session)
        db.commit()
        raise HTTPException(status_code=422, detail="This GPS position is outside India. No reading was stored.")
    if request.accuracy_meters > MAX_ACCURACY_METERS:
        _clear_baseline(session)
        db.commit()
        raise HTTPException(status_code=422, detail="GPS accuracy is too low (must be 25 m or better). No reading was stored.")

    previous = None
    if session.last_timestamp and session.last_latitude is not None and session.last_longitude is not None:
        previous = {
            "timestamp": session.last_timestamp,
            "lat": session.last_latitude,
            "lon": session.last_longitude,
            "accuracy": session.last_accuracy_meters or MAX_ACCURACY_METERS,
        }
    session.last_timestamp = timestamp
    session.last_latitude = request.latitude
    session.last_longitude = request.longitude
    session.last_accuracy_meters = request.accuracy_meters
    session.updated_at = now

    if previous is None:
        db.commit()
        return {"stored": False, "baseline_set": True, "message": "First valid fix received; another fix is needed to calculate segment speed."}
    seconds = (timestamp - previous["timestamp"]).total_seconds()
    if seconds < MIN_INTERVAL_SECONDS or seconds > MAX_INTERVAL_SECONDS:
        db.commit()
        return {"stored": False, "baseline_set": True, "message": "Fix interval was outside the accepted 3–120 second range; baseline reset."}
    distance = _haversine_meters((previous["lat"], previous["lon"]), (request.latitude, request.longitude))
    uncertainty = max(5.0, (previous["accuracy"] + request.accuracy_meters) * 0.5)
    if distance <= uncertainty:
        db.commit()
        return {"stored": False, "baseline_set": True, "message": "Movement was below GPS measurement resolution; no speed sample stored."}
    speed = (distance / seconds) * 3.6
    if speed > MAX_SPEED_KMH:
        db.commit()
        return {"stored": False, "baseline_set": True, "message": "GPS jump exceeded 120 km/h and was rejected; baseline reset."}
    observation_id = str(request.observation_id)
    if db.query(GpsSpeedObservation.id).filter(GpsSpeedObservation.observation_id == observation_id).first():
        db.commit()
        return {"stored": False, "duplicate": True, "message": "This GPS fix was already processed."}
    observation = GpsSpeedObservation(
        observation_id=observation_id,
        timestamp=timestamp,
        latitude=request.latitude,
        longitude=request.longitude,
        average_speed_kmh=round(speed, 2),
        distance_meters=round(distance, 2),
        interval_seconds=round(seconds, 2),
        accuracy_meters=request.accuracy_meters,
        session_hash=hashlib.sha256(str(session_id).encode()).hexdigest(),
        data_source=SOURCE,
        data_quality="observed_individual_gps_speed",
        consent_version=session.consent_version,
        consented_at=session.consented_at,
    )
    db.add(observation)
    db.commit()
    return {"stored": True, "source": SOURCE, "data_quality": "observed_individual_gps_speed", "average_speed_kmh": observation.average_speed_kmh, "message": "Individual GPS segment speed stored; this is not a road-wide traffic speed or vehicle count."}


@router.post("/traffic/gps-sessions/{session_id}/stop")
def stop_gps_session(session_id: UUID, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    session = _authorized_session(session_id, authorization, db, active=False)
    session.active = False
    session.stopped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _clear_baseline(session)
    db.commit()
    return {"session_id": str(session_id), "active": False, "message": "Collection stopped. Previously stored samples remain available in aggregate statistics."}


@router.delete("/traffic/gps-sessions/{session_id}/observations")
def delete_session_observations(session_id: UUID, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Explicitly delete samples and consent metadata for the authorized session."""
    session = _authorized_session(session_id, authorization, db, active=False)
    if session.active:
        raise HTTPException(status_code=409, detail="Stop GPS collection before deleting this session's samples.")
    digest = hashlib.sha256(str(session_id).encode()).hexdigest()
    deleted = db.query(GpsSpeedObservation).filter(GpsSpeedObservation.session_hash == digest).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"deleted_samples": deleted, "message": "GPS samples for this session were deleted."}


@router.get("/traffic/gps-observations/stats")
def gps_observation_stats(db: Session = Depends(get_db)):
    row = db.query(
        func.count(GpsSpeedObservation.id),
        func.min(GpsSpeedObservation.timestamp),
        func.max(GpsSpeedObservation.timestamp),
        func.avg(GpsSpeedObservation.average_speed_kmh),
    ).one()
    count = int(row[0] or 0)
    return {
        "sample_count": count,
        "date_range": {"start": row[1].isoformat() if row[1] else None, "end": row[2].isoformat() if row[2] else None},
        "average_individual_gps_speed_kmh": round(float(row[3]), 2) if row[3] is not None else None,
        "data_type": "observed_individual_gps_speed",
        "source": SOURCE,
        "message": "These are opt-in individual GPS segment speeds. They are not vehicle counts, aggregate road traffic speeds, historical survey measurements, or predictions." if count else "No consented GPS speed observations available.",
    }
