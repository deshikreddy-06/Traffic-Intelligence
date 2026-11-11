"""Persisted owner/consent state for one opt-in GPS collection session."""

from sqlalchemy import Boolean, Column, DateTime, Float, String
from sqlalchemy.sql import func

from app.core.database import Base


class GpsCollectionSession(Base):
    __tablename__ = "gps_collection_sessions"

    session_id = Column(String, primary_key=True)
    token_hash = Column(String, nullable=False)
    consent_version = Column(String, nullable=False)
    consented_at = Column(DateTime, nullable=False)
    active = Column(Boolean, nullable=False, default=True, index=True)
    last_timestamp = Column(DateTime, nullable=True)
    last_latitude = Column(Float, nullable=True)
    last_longitude = Column(Float, nullable=True)
    last_accuracy_meters = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    stopped_at = Column(DateTime, nullable=True)
