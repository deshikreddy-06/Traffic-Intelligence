from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class PredictionRecord(Base):
    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True, index=True)
    prediction_id = Column(String, unique=True, index=True, nullable=False)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)
    road_segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=True)
    prediction_target = Column(String, nullable=False)  # travel_time, speed, congestion
    predicted_value = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=True)
    prediction_timestamp = Column(DateTime, server_default=func.now())
    prediction_horizon = Column(DateTime, nullable=False)
    model_version = Column(String, nullable=False)
    features_used = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    area = relationship("Area")
    road_segment = relationship("RoadSegment")
