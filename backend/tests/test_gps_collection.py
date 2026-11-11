from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import gps_collection
from app.core.database import Base, get_db
from app.main import app
from app.models.gps_speed_observation import GpsSpeedObservation
from app.models.gps_collection_session import GpsCollectionSession
from app.models.traffic_observation import TrafficObservation


@pytest.fixture()
def gps_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    # Do not enter TestClient as a context manager: startup intentionally runs
    # against the application engine, while this fixture uses a private DB.
    client = TestClient(app)
    yield client, TestingSession
    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def start_session(client, *, consent=True):
    session_id = str(uuid4())
    response = client.post(
        f"/api/traffic/gps-sessions/{session_id}/start",
        json={"consent_confirmed": consent, "consent_version": gps_collection.CONSENT_VERSION},
    )
    return session_id, response


def headers(start_response):
    return {"Authorization": f"Bearer {start_response.json()['session_token']}"}


def reading(session_id, token_headers, *, seconds=0, lat=17.4435, lon=78.3772, accuracy=5, fix=None):
    timestamp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return {
        "observation_id": str(fix or uuid4()),
        "timestamp": timestamp.isoformat(),
        "latitude": lat,
        "longitude": lon,
        "accuracy_meters": accuracy,
    }


def send_fix(client, session_id, auth, **kwargs):
    return client.post(
        f"/api/traffic/gps-sessions/{session_id}/readings",
        headers=auth,
        json=reading(session_id, auth, **kwargs),
    )


def test_consent_required_and_session_token_is_private(gps_client, caplog):
    client, _ = gps_client
    session_id, denied = start_session(client, consent=False)
    assert denied.status_code == 422
    assert "consent" in denied.json()["detail"].lower()

    session_id, started = start_session(client)
    assert started.status_code == 200
    assert started.json()["active"] is True
    assert len(started.json()["session_token"]) >= 40
    db = next(iter(app.dependency_overrides[get_db]()))
    try:
        stored_session = db.query(GpsCollectionSession).filter_by(session_id=session_id).one()
        assert stored_session.token_hash != started.json()["session_token"]
        assert stored_session.consent_version == gps_collection.CONSENT_VERSION
    finally:
        db.close()

    unauthenticated = send_fix(client, session_id, {})
    assert unauthenticated.status_code == 401
    invalid_token = "invalid-token-canary"
    other_owner = send_fix(client, session_id, {"Authorization": f"Bearer {invalid_token}"})
    assert other_owner.status_code == 403
    assert invalid_token not in other_owner.text
    assert invalid_token not in str(other_owner.request.url)
    assert started.json()["session_token"] not in str(other_owner.request.url)
    assert invalid_token not in caplog.text
    assert started.json()["session_token"] not in caplog.text


def test_two_accurate_fixes_store_one_individual_gps_speed(gps_client):
    client, session_factory = gps_client
    session_id, started = start_session(client)
    auth = headers(started)
    baseline = send_fix(client, session_id, auth, seconds=0)
    assert baseline.status_code == 200
    assert baseline.json()["stored"] is False

    moved = send_fix(client, session_id, auth, seconds=10, lat=17.4437)
    assert moved.status_code == 200
    result = moved.json()
    assert result["stored"] is True
    assert result["data_quality"] == "observed_individual_gps_speed"
    assert result["average_speed_kmh"] == pytest.approx(7.99, abs=0.1)

    db = session_factory()
    try:
        sample = db.query(GpsSpeedObservation).one()
        assert sample.data_source == gps_collection.SOURCE
        assert sample.average_speed_kmh == result["average_speed_kmh"]
        assert sample.session_hash != session_id
        assert db.query(TrafficObservation).count() == 0
    finally:
        db.close()

    gps_stats = client.get("/api/traffic/gps-observations/stats").json()
    traffic_stats = client.get("/api/traffic/stats").json()
    assert gps_stats["sample_count"] == 1
    assert gps_stats["average_individual_gps_speed_kmh"] is not None
    assert traffic_stats["observation_count"] == 0
    assert traffic_stats["average_recorded_speed_kmh"] is None
    assert traffic_stats["average_recorded_vehicle_count"] is None


def test_gps_summary_returns_real_zero_when_no_samples_exist(gps_client):
    client, _ = gps_client
    response = client.get("/api/traffic/gps-observations/stats")
    assert response.status_code == 200
    summary = response.json()
    assert summary["sample_count"] == 0
    assert summary["average_individual_gps_speed_kmh"] is None
    assert summary["date_range"] == {"start": None, "end": None}
    assert "No consented GPS speed observations" in summary["message"]


def test_invalid_accuracy_and_outside_boundary_are_not_stored(gps_client):
    client, session_factory = gps_client
    session_id, started = start_session(client)
    auth = headers(started)
    invalid_accuracy = send_fix(client, session_id, auth, accuracy=26)
    assert invalid_accuracy.status_code == 422
    assert "accuracy" in invalid_accuracy.json()["detail"].lower()

    outside = send_fix(client, session_id, auth, lat=0, lon=0)
    assert outside.status_code == 422
    assert "outside India" in outside.json()["detail"]
    db = session_factory()
    try:
        assert db.query(GpsSpeedObservation).count() == 0
    finally:
        db.close()


def test_invalid_or_timezone_free_timestamp_is_rejected(gps_client):
    client, session_factory = gps_client
    session_id, started = start_session(client)
    auth = headers(started)
    naive = reading(session_id, auth)
    naive["timestamp"] = "2026-11-03T12:00:00"
    response = client.post(f"/api/traffic/gps-sessions/{session_id}/readings", headers=auth, json=naive)
    assert response.status_code == 422
    future = reading(session_id, auth, seconds=180)
    response = client.post(f"/api/traffic/gps-sessions/{session_id}/readings", headers=auth, json=future)
    assert response.status_code == 422
    db = session_factory()
    try:
        assert db.query(GpsSpeedObservation).count() == 0
    finally:
        db.close()


def test_impossible_jump_resets_baseline_and_is_rejected(gps_client):
    client, session_factory = gps_client
    session_id, started = start_session(client)
    auth = headers(started)
    assert send_fix(client, session_id, auth, seconds=0).status_code == 200
    jump = send_fix(client, session_id, auth, seconds=3, lat=17.4535)
    assert jump.status_code == 200
    assert jump.json()["stored"] is False
    assert "jump" in jump.json()["message"].lower()

    valid_after_jump = send_fix(client, session_id, auth, seconds=13, lat=17.4540)
    assert valid_after_jump.status_code == 200
    assert valid_after_jump.json()["stored"] is True
    db = session_factory()
    try:
        assert db.query(GpsSpeedObservation).count() == 1
    finally:
        db.close()


def test_stop_blocks_new_fixes_and_delete_requires_owner(gps_client):
    client, session_factory = gps_client
    session_id, started = start_session(client)
    auth = headers(started)
    assert send_fix(client, session_id, auth, seconds=0).status_code == 200
    assert send_fix(client, session_id, auth, seconds=10, lat=17.4437).json()["stored"] is True

    premature_delete = client.delete(f"/api/traffic/gps-sessions/{session_id}/observations", headers=auth)
    assert premature_delete.status_code == 409
    stolen_stop = client.post(f"/api/traffic/gps-sessions/{session_id}/stop", headers={"Authorization": "Bearer stolen"})
    assert stolen_stop.status_code == 403
    stopped = client.post(f"/api/traffic/gps-sessions/{session_id}/stop", headers=auth)
    assert stopped.status_code == 200
    rejected = send_fix(client, session_id, auth, seconds=20, lat=17.4439)
    assert rejected.status_code == 409

    stolen_delete = client.delete(f"/api/traffic/gps-sessions/{session_id}/observations", headers={"Authorization": "Bearer stolen"})
    assert stolen_delete.status_code == 403
    deleted = client.delete(f"/api/traffic/gps-sessions/{session_id}/observations", headers=auth)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_samples"] == 1
    db = session_factory()
    try:
        assert db.query(GpsSpeedObservation).count() == 0
        assert db.query(TrafficObservation).count() == 0
        assert db.query(GpsCollectionSession).count() == 0
    finally:
        db.close()
