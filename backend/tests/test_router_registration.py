from fastapi.testclient import TestClient

from app.main import API_ROUTERS, app


def test_all_feature_routers_are_registered_once_in_openapi():
    expected_router_names = {
        "areas",
        "routes",
        "predictions",
        "analytics",
        "traffic_data",
        "gps_collection",
        "location_search",
    }
    assert {name for name, _, _ in API_ROUTERS} == expected_router_names
    assert len(API_ROUTERS) == len(expected_router_names)

    paths = app.openapi()["paths"]
    expected_paths = {
        "/api/areas",
        "/api/areas/search",
        "/api/areas/states",
        "/api/areas/{area_id}",
        "/api/areas/{area_id}/history",
        "/api/areas/{area_id}/traffic",
        "/api/routes/compare",
        "/api/routes/directions",
        "/api/routes/validate-point",
        "/api/predictions/traffic",
        "/api/predictions/{prediction_id}",
        "/api/analytics/hourly",
        "/api/analytics/areas",
        "/api/traffic/import",
        "/api/traffic/observations",
        "/api/traffic/observations/by-time",
        "/api/traffic/areas/{area_name}/observations",
        "/api/traffic/sources",
        "/api/traffic/stats",
        "/api/traffic/gps-sessions/{session_id}/start",
        "/api/traffic/gps-sessions/{session_id}/readings",
        "/api/traffic/gps-sessions/{session_id}/stop",
        "/api/traffic/gps-sessions/{session_id}/observations",
        "/api/traffic/gps-observations/stats",
        "/api/locations/autocomplete",
        "/api/health",
    }
    assert set(paths) == expected_paths

    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "healthy"
