import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.area import Area
from app.models.road_segment import RoadSegment
from app.models.traffic_observation import TrafficObservation


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    db.add(Area(name="hitech-city", display_name="Hitech City", latitude=17.4435, longitude=78.3772))
    db.commit()

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _upload(client, content: str, filename: str = "traffic.csv", **form):
    data = {
        "source_name": "Local Hyderabad survey",
        "source_url": "https://example.org/hyderabad-data",
        "collection_period": "2024-01 to 2024-01",
        "license_name": "CC BY 4.0",
        "data_type": "traffic_observations",
        "city_coverage": "Hyderabad, India",
        **form,
    }
    return client.post("/api/traffic/import", files={"file": (filename, content, "text/csv")}, data=data)


def test_csv_import_duplicate_handling_retrieval_and_stats(client):
    csv_data = "observation_id,timestamp,area_name,road_name,latitude,longitude,average_speed,vehicle_count\n" \
        "obs-1,2024-01-01T08:00:00,Hitech City,Cyber Towers Road,17.4435,78.3772,24.5,32\n" \
        "obs-1,2024-01-01T08:00:00,Hitech City,Cyber Towers Road,17.4435,78.3772,24.5,32\n"
    imported = _upload(client, csv_data)
    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 1
    assert imported.json()["duplicate_count"] == 1

    observations = client.get("/api/traffic/observations?area=Hitech%20City&date_from=2024-01-01T00:00:00&date_to=2024-01-02T00:00:00")
    assert observations.status_code == 200
    assert observations.json()["total"] == 1
    row = observations.json()["observations"][0]
    assert row["average_speed_kmh"] == 24.5
    assert row["vehicle_count"] == 32
    assert row["data_status"] == "historical"
    assert client.get("/api/traffic/areas/Hitech%20City/observations").json()["total"] == 1
    assert client.get("/api/traffic/observations/by-time?date_from=2024-01-01T00:00:00&date_to=2024-01-02T00:00:00").json()["total"] == 1

    stats = client.get("/api/traffic/stats")
    assert stats.json()["observation_count"] == 1
    assert stats.json()["covered_area_count"] == 1
    assert stats.json()["average_recorded_speed_kmh"] == 24.5
    assert stats.json()["average_recorded_vehicle_count"] == 32
    sources = client.get("/api/traffic/sources").json()
    assert sources[0]["license"] == "CC BY 4.0"


def test_invalid_format_status_and_out_of_boundary_rows(client):
    invalid_csv = _upload(client, "not,a,valid,header\n1,2,3,4\n")
    assert invalid_csv.status_code == 422
    assert "Required columns are missing" in invalid_csv.json()["detail"]

    outside = "timestamp,area_name,latitude,longitude,average_speed\n2024-01-01T08:00:00,Outside,0,0,30\n"
    result = _upload(client, outside)
    assert result.status_code == 200
    assert result.json()["rejected_count"] == 1
    assert any("outside India" in reason for reason in result.json()["rejection_reasons"])

    bad_timestamp = "timestamp,area_name,latitude,longitude,average_speed\nnot-a-date,Hitech City,17.4435,78.3772,30\n"
    assert _upload(client, bad_timestamp).json()["rejected_count"] == 1

    simulated = _upload(client, "timestamp,area_name,latitude,longitude,average_speed\n2024-01-01T08:00:00,Hitech City,17.4435,78.3772,30\n", data_status="predicted")
    assert simulated.status_code == 422

    other_city = _upload(client, "timestamp,area_name,latitude,longitude,average_speed\n2024-01-01T08:00:00,Hitech City,17.4435,78.3772,30\n", city_coverage="Bengaluru")
    assert other_city.status_code == 422


def test_geojson_point_import_and_reject_emissions_registry_type(client):
    geojson = '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"timestamp":"2024-02-01T10:00:00Z","area_name":"Madhapur","road_name":"Road 1","vehicle_count":11},"geometry":{"type":"Point","coordinates":[78.3918,17.4489]}}]}'
    response = _upload(client, geojson, filename="traffic.geojson")
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1
    row = client.get("/api/traffic/observations").json()["observations"][0]
    assert row["longitude"] == pytest.approx(78.3918)
    assert row["vehicle_count"] == 11

    rejected = _upload(client, geojson, filename="traffic.geojson", data_type="emissions_grid")
    assert rejected.status_code == 422

    json_rows = '[{"timestamp":"2024-02-02T10:00:00Z","area_name":"Madhapur","road_name":"Road 2","latitude":17.4489,"longitude":78.3918,"traffic_density":18}]'
    json_response = _upload(client, json_rows, filename="traffic.json")
    assert json_response.status_code == 200
    assert json_response.json()["imported_count"] == 1
    assert client.get("/api/traffic/observations").json()["total"] == 2


def test_database_insert_does_not_create_fake_measurements(client):
    response = _upload(client, "timestamp,area_name,latitude,longitude,average_speed\n2024-03-01T10:00:00,Hitech City,17.4435,78.3772,\n")
    assert response.status_code == 200
    assert response.json()["imported_count"] == 0
    db = next(iter(app.dependency_overrides[get_db]()))
    assert db.query(TrafficObservation).count() == 0
    db.close()


def test_actual_road_segment_observation_is_exposed_with_geometry(client):
    db = next(iter(app.dependency_overrides[get_db]()))
    area = db.query(Area).filter(Area.name == "hitech-city").first()
    segment = RoadSegment(
        segment_id="test-cyber-towers-road",
        name="Cyber Towers Road",
        area_id=area.id,
        start_lat=17.4435,
        start_lon=78.3772,
        end_lat=17.4440,
        end_lon=78.3780,
    )
    db.add(segment)
    db.flush()
    db.add(TrafficObservation(
        observation_id="test-road-observation",
        timestamp=datetime(2024, 1, 1, 8, 0),
        area_id=area.id,
        area_name=area.display_name,
        road_segment_id=segment.id,
        road_name=segment.name,
        latitude=17.4437,
        longitude=78.3775,
        average_speed=22,
        vehicle_count=8,
        congestion_level="moderate",
        data_source="isolated API test fixture",
        data_quality="actual",
    ))
    db.commit()
    db.close()

    response = client.get("/api/traffic/observations")
    assert response.status_code == 200
    observation = response.json()["observations"][0]
    assert observation["data_status"] == "actual"
    assert observation["congestion_level"] == "moderate"
    assert observation["road_segment"] == {
        "segment_id": "test-cyber-towers-road",
        "name": "Cyber Towers Road",
        "start": [17.4435, 78.3772],
        "end": [17.4440, 78.3780],
    }
    area_summary = client.get("/api/analytics/areas").json()["areas"]
    hitech_summary = next(item for item in area_summary if item["area"] == "Hitech City")
    assert hitech_summary["sample_count"] == 1
    assert hitech_summary["avg_speed"] == 22


def test_analytics_excludes_non_observation_statuses(client):
    db = next(iter(app.dependency_overrides[get_db]()))
    area = db.query(Area).filter(Area.name == "hitech-city").first()
    db.add(TrafficObservation(
        observation_id="isolated-predicted-row",
        timestamp=datetime(2024, 1, 1, 8, 0),
        area_id=area.id,
        area_name=area.display_name,
        average_speed=99,
        data_source="isolated test row",
        data_quality="predicted",
    ))
    db.commit()
    db.close()

    area_summaries = client.get("/api/analytics/areas").json()["areas"]
    hitech_summary = next(item for item in area_summaries if item["area"] == "Hitech City")
    hourly = client.get("/api/analytics/hourly?area=Hitech%20City").json()
    assert hitech_summary["sample_count"] == 0
    assert hitech_summary["avg_speed"] is None
    assert hourly["sample_count"] == 0
    assert hourly["data_status"] == "unavailable"


def test_prediction_endpoint_explicitly_reports_empty_training_data(client):
    response = client.post("/api/predictions/traffic", json={
        "area": "Hitech City",
        "day_of_week": 0,
        "time": "08:30",
        "prediction_horizon": "30m",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "unavailable"
    assert result["message"] == "Insufficient traffic data"
    assert result["predicted_value"] is None
