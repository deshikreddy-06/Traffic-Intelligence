"""Consent-based individual GPS segment-speed samples (not traffic counts)."""

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class GpsSpeedObservation(Base):
    __tablename__ = "gps_speed_observations"

    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(String, nullable=False, unique=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    average_speed_kmh = Column(Float, nullable=False)
    distance_meters = Column(Float, nullable=False)
    interval_seconds = Column(Float, nullable=False)
    accuracy_meters = Column(Float, nullable=False)
    session_hash = Column(String, nullable=False, index=True)
    data_source = Column(String, nullable=False, default="consented_foreground_browser_gps")
    data_quality = Column(String, nullable=False, default="observed_individual_gps_speed")
    consent_version = Column(String, nullable=False)
    consented_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
