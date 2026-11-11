from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    evaluation_timestamp = Column(DateTime, server_default=func.now())
    training_period_start = Column(DateTime, nullable=False)
    training_period_end = Column(DateTime, nullable=False)
    test_period_start = Column(DateTime, nullable=False)
    test_period_end = Column(DateTime, nullable=False)
    metric_mae = Column(Float, nullable=True)
    metric_rmse = Column(Float, nullable=True)
    metric_r2 = Column(Float, nullable=True)
    metric_f1 = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    sample_count_train = Column(Integer, nullable=True)
    sample_count_test = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
