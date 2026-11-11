from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Use SQLite for development, PostgreSQL for production
database_url = settings.DATABASE_URL
if database_url.startswith("sqlite"):
    # Keep legacy relative SQLite URLs anchored to the backend directory, regardless
    # of whether Uvicorn is launched from the repository root or backend folder.
    sqlite_path = database_url.removeprefix("sqlite:///")
    if sqlite_path != ":memory:" and not Path(sqlite_path).is_absolute():
        sqlite_path = str((Path(__file__).resolve().parents[2] / sqlite_path).resolve())
        database_url = f"sqlite:///{Path(sqlite_path).as_posix()}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(settings.DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_sqlite_migrations() -> None:
    """Add Phase 3A nullable columns in-place, preserving all existing records."""
    if not database_url.startswith("sqlite"):
        return
    additions = {
        "traffic_observations": {
            "area_name": "VARCHAR", "road_name": "VARCHAR",
            "vehicle_count": "FLOAT", "traffic_density": "FLOAT",
        },
        "data_source_metadata": {
            "data_type": "VARCHAR", "city_coverage": "VARCHAR", "imported_at": "DATETIME",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, column_type in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_traffic_observations_area_name "
            "ON traffic_observations(area_name)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_traffic_observations_road_name "
            "ON traffic_observations(road_name)"
        )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
