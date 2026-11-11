from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import settings
from app.core.database import engine, Base, get_db, run_sqlite_migrations
from app.models.area import Area
from app.models.road_segment import RoadSegment
from app.models.traffic_observation import TrafficObservation
from app.models.historical_stats import HistoricalStats
from app.models.prediction_record import PredictionRecord
from app.models.model_evaluation import ModelEvaluation
from app.models.data_source_metadata import DataSourceMetadata
from app.models.gps_speed_observation import GpsSpeedObservation
from app.models.gps_collection_session import GpsCollectionSession
from app.api import areas, routes, predictions, analytics, traffic_data, gps_collection, location_search

# Create database tables
Base.metadata.create_all(bind=engine)
run_sqlite_migrations()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database with default areas if empty
    from sqlalchemy.orm import Session
    db = next(get_db())
    try:
        if db.query(Area).count() == 0:
            default_areas = [
                Area(name="hitech-city", display_name="Hitech City", latitude=17.4435, longitude=78.3772),
                Area(name="madhapur", display_name="Madhapur", latitude=17.4489, longitude=78.3918),
                Area(name="gachibowli", display_name="Gachibowli", latitude=17.4401, longitude=78.3489),
                Area(name="kondapur", display_name="Kondapur", latitude=17.4633, longitude=78.3738),
                Area(name="kukatpally", display_name="Kukatpally", latitude=17.4941, longitude=78.4036),
                Area(name="ameerpet", display_name="Ameerpet", latitude=17.4378, longitude=78.4482),
                Area(name="begumpet", display_name="Begumpet", latitude=17.4449, longitude=78.4687),
                Area(name="secunderabad", display_name="Secunderabad", latitude=17.4399, longitude=78.4983),
                Area(name="lb-nagar", display_name="LB Nagar", latitude=17.3667, longitude=78.5506),
                Area(name="uppal", display_name="Uppal", latitude=17.4056, longitude=78.5596),
                Area(name="mehdipatnam", display_name="Mehdipatnam", latitude=17.3956, longitude=78.4364),
                Area(name="financial-district", display_name="Financial District", latitude=17.4245, longitude=78.3522),
                Area(name="miyapur", display_name="Miyapur", latitude=17.5041, longitude=78.3730),
                Area(name="jubilee-hills", display_name="Jubilee Hills", latitude=17.4239, longitude=78.4099),
                Area(name="banjara-hills", display_name="Banjara Hills", latitude=17.4136, longitude=78.4290),
                Area(name="raidurg", display_name="Raidurg", latitude=17.4136, longitude=78.3366),
                Area(name="koti", display_name="Koti", latitude=17.3894, longitude=78.4866),
                Area(name="abids", display_name="Abids", latitude=17.3974, longitude=78.4739),
                Area(name="dilsukhnagar", display_name="Dilsukhnagar", latitude=17.3678, longitude=78.5299),
                Area(name="nanakramguda", display_name="Nanakramguda", latitude=17.4072, longitude=78.3634),
            ]
            db.add_all(default_areas)
            db.commit()
        known_sources = {
            "CHETNA-Road emissions grids": {
                "source_url": "https://doi.org/10.6084/m9.figshare.28330067.v2",
                "data_type": "emissions_grid",
                "geographic_coverage": "15 Indian cities, including Hyderabad",
                "observation_period": "1 January–31 December 2021; daily grids",
                "available_fields": "CO2 and ten pollutant emissions on 500 m grids; this downloaded artifact is CO2 only",
                "license": "CC BY 4.0",
                "permitted_use": "Attribution required; emissions-only research dataset.",
                "retention_allowed": True,
                "training_use_allowed": False,
                "notes": "Not a raw speed/count observation dataset. Hyderabad is uncertainty class C in the authors' classification. Never imported into traffic_observations.",
            },
            "JICA Hyderabad Traffic Volume Survey (2011)": {
                "source_url": "https://openjicareport.jica.go.jp/pdf/12150363_04.pdf",
                "data_type": "restricted_historical_traffic_survey_report",
                "geographic_coverage": "Hyderabad metropolitan area; survey sites require GHMC polygon validation",
                "observation_period": "31 October–4 November 2011; weekday survey periods",
                "available_fields": "Classified vehicle counts and turning movement summaries; no speed observations",
                "license": "JICA site policy; reuse/reproduction beyond personal use prohibited",
                "permitted_use": "Source discovery only; obtain permission before extracting/importing report data.",
                "retention_allowed": False,
                "training_use_allowed": False,
                "notes": "The report describes 15-minute counting methods and summary tables, but bulk reuse is not authorized by its site policy.",
            },
        }
        from app.models.data_source_metadata import DataSourceMetadata
        for source_name, values in known_sources.items():
            metadata = db.query(DataSourceMetadata).filter(DataSourceMetadata.source_name == source_name).first()
            if metadata is None:
                metadata = DataSourceMetadata(source_name=source_name, source_type="dataset")
                db.add(metadata)
            for key, value in values.items():
                setattr(metadata, key, value)
            metadata.data_type = values["data_type"]
            metadata.city_coverage = values["geographic_coverage"]
            if source_name == "CHETNA-Road emissions grids":
                artifact = Path(__file__).resolve().parents[2] / "data" / "datasets" / "chetnaroad_co2" / "52545989.nc"
                if artifact.exists() and artifact.stat().st_size == 11_050_923 and metadata.imported_at is None:
                    metadata.imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    finally:
        db.close()
    yield
    # Shutdown logic here if needed

app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Based Smart Traffic Prediction and Route Optimization System for India",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep the API router registry in one place so each feature router is mounted
# once. Use app.openapi() to inspect the public schema: recent FastAPI versions
# keep included routers as internal _IncludedRouter objects in app.routes.
API_ROUTERS = (
    ("areas", areas.router, "areas"),
    ("routes", routes.router, "routes"),
    ("predictions", predictions.router, "predictions"),
    ("analytics", analytics.router, "analytics"),
    ("traffic_data", traffic_data.router, "traffic data"),
    ("gps_collection", gps_collection.router, "consented GPS collection"),
    ("location_search", location_search.router, "India-wide location search"),
)

if len({name for name, _, _ in API_ROUTERS}) != len(API_ROUTERS):
    raise RuntimeError("Each API router must be registered exactly once.")

for _, api_router, tag in API_ROUTERS:
    app.include_router(api_router, prefix=settings.API_PREFIX, tags=[tag])

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "app": settings.APP_NAME, "environment": settings.APP_ENV}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
