from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class TrafficObservation(Base):
    __tablename__ = "traffic_observations"

    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(String, unique=True, index=True, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)
    area_name = Column(String, nullable=True, index=True)
    road_segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=True)
    road_name = Column(String, nullable=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    traffic_volume = Column(Float, nullable=True)
    vehicle_count = Column(Float, nullable=True)
    traffic_density = Column(Float, nullable=True)
    average_speed = Column(Float, nullable=True)
    travel_time = Column(Float, nullable=True)
    congestion_level = Column(String, nullable=True)
    data_source = Column(String, nullable=False)
    data_quality = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    area = relationship("Area", back_populates="observations")
    road_segment = relationship("RoadSegment", back_populates="observations")

