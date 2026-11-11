from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class HistoricalStats(Base):
    __tablename__ = "historical_stats"

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)
    road_segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=True)
    stat_type = Column(String, nullable=False)  # hourly_avg, daily_avg, weekly_avg
    time_period = Column(String, nullable=False)  # e.g., "hour_17", "weekday", "weekend"
    avg_travel_time = Column(Float, nullable=True)
    avg_speed = Column(Float, nullable=True)
    avg_traffic_volume = Column(Float, nullable=True)
    sample_count = Column(Integer, nullable=True)
    observation_period_start = Column(DateTime, nullable=True)
    observation_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    area = relationship("Area")
    road_segment = relationship("RoadSegment")
