from pathlib import Path
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "India Traffic Intelligence"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api"
    CORS_ORIGINS: str = "http://localhost:5173"
    DATABASE_URL: str = f"sqlite:///{(Path(__file__).resolve().parents[2] / 'hti_dev.db').as_posix()}"
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    GEOAPIFY_API_KEY: Optional[str] = None
    ML_MODEL_PATH: str = "./ml/artifacts"
    PREDICTION_CONFIDENCE_THRESHOLD: float = 0.7
    INGESTION_ENABLED: bool = False
    INGESTION_SCHEDULE: str = "0 0 * * *"
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_label(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"development", "dev"}:
                return True
        return value

settings = Settings()
