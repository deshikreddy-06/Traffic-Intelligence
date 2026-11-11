from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base

class DataSourceMetadata(Base):
    __tablename__ = "data_source_metadata"

    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, unique=True, nullable=False)
    source_type = Column(String, nullable=False)  # api, dataset, manual
    data_type = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    geographic_coverage = Column(String, nullable=True)
    city_coverage = Column(String, nullable=True)
    observation_period = Column(String, nullable=True)
    available_fields = Column(Text, nullable=True)
    sampling_frequency = Column(String, nullable=True)
    license = Column(String, nullable=True)
    permitted_use = Column(Text, nullable=True)
    retention_allowed = Column(Boolean, default=False)
    training_use_allowed = Column(Boolean, default=False)
    last_ingested_at = Column(DateTime, nullable=True)
    imported_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
