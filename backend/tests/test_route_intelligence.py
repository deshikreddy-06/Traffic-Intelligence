import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import routes as route_api
from app.main import app

REAL_VALHALLA_PROVIDER = route_api._get_valhalla_routes


ORIGIN = {"origin_lat": 17.4435, "origin_lon": 78.3772}
DESTINATION = {"destination_lat": 17.4401, "destination_lon": 78.3489}


def osrm_route(distance, duration, coordinates, steps=None):
    return {
        "distance": distance,
        "duration": duration,
        "geometry": {"coordinates": coordinates, "type": "LineString"},
        "legs": [{"steps": steps or []}],
    }


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeAsyncClient:
    payload = {"code": "Ok", "routes": []}
    requests = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None, headers=None):
        self.requests.append((url, params, headers))
        return FakeResponse(self.payload)


@pytest.fixture(autouse=True)
def use_osrm_fallback(monkeypatch):
    async def google_routes_unavailable(*args, **kwargs):
        raise RuntimeError("Use the mocked OSRM response.")

    async def valhalla_unavailable(*args, **kwargs):
        raise RuntimeError("Use the mocked OSRM response.")

    monkeypatch.setattr(route_api, "_get_google_routes", google_routes_unavailable)
    monkeypatch.setattr(route_api, "_get_valhalla_routes", valhalla_unavailable)


def setup_function():
    FakeAsyncClient.requests = []
    route_api._route_cache.clear()
    route_api._geocode_cache.clear()


def test_one_osrm_route_is_not_manufactured_and_is_explained(monkeypatch):
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [osrm_route(10_000, 900, [[78.3772, 17.4435], [78.36, 17.44], [78.3489, 17.4401]])],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={**ORIGIN, **DESTINATION})

    assert response.status_code == 200
    result = response.json()
    assert result["route_count"] == 1
    assert result["alternatives_available"] is False
    assert "Only one distinct" in result["alternatives_note"]
    assert len(result["routes"]) == 1
    assert FakeAsyncClient.requests[0][1]["alternatives"] == "true"


def test_candidates_are_deduplicated_classified_and_converted(monkeypatch):
    shared = [[78.3772, 17.4435], [78.365, 17.442], [78.3489, 17.4401]]
    alternate_fast = [[78.3772, 17.4435], [78.37, 17.435], [78.3489, 17.4401]]
    alternate = [[78.3772, 17.4435], [78.36, 17.45], [78.3489, 17.4401]]
    turn_steps = [{
        "name": "Madhapur Road",
        "distance": 1_250,
        "duration": 120,
        "maneuver": {"type": "turn", "modifier": "left"},
    }]
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [
            osrm_route(10_000, 1_000, shared, turn_steps),
            osrm_route(12_000, 900, alternate_fast),
            osrm_route(20_000, 1_010, shared),  # same geometry with a conflicting distance
            osrm_route(14_000, 1_100, alternate),
        ],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={**ORIGIN, **DESTINATION})

    assert response.status_code == 200
    data = response.json()
    assert len(data["routes"]) == 3
    assert all(route["distance"] != 20 for route in data["routes"])
    shortest = next(route for route in data["routes"] if route["is_shortest"])
    fastest = next(route for route in data["routes"] if route["is_fastest"])
    assert shortest["distance"] == 10.0
    assert fastest["duration"] == 15.0
    assert shortest["route_id"] != fastest["route_id"]
    assert shortest["route_type"] == "shortest"
    assert fastest["route_type"] == "fastest estimated"
    assert shortest["geometry"][0] == [17.4435, 78.3772]
    assert shortest["steps"][0]["road_name"] == "Madhapur Road"
    assert shortest["steps"][0]["distance_km"] == 1.25
    assert shortest["steps"][0]["duration_minutes"] == 2.0


def test_valhalla_alternatives_are_normalized_ranked_and_returned(monkeypatch):
    paths = [
        osrm_route(5_000, 600, [[78.3772, 17.4435], [78.363, 17.440], [78.3489, 17.4401]]),
        osrm_route(5_800, 520, [[78.3772, 17.4435], [78.363, 17.446], [78.3489, 17.4401]]),
        osrm_route(7_000, 700, [[78.3772, 17.4435], [78.363, 17.435], [78.3489, 17.4401]]),
    ]

    async def valhalla_routes(*args, **kwargs):
        return {"code": "Ok", "routes": paths}

    monkeypatch.setattr(route_api, "_get_valhalla_routes", valhalla_routes)
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={**ORIGIN, **DESTINATION})

    assert response.status_code == 200
    data = response.json()
    assert data["route_count"] == 3
    assert data["data_source"] == "Valhalla OpenStreetMap road-network estimate"
    fastest = next(route for route in data["routes"] if route["is_fastest"])
    shortest = next(route for route in data["routes"] if route["is_shortest"])
    assert fastest["duration"] == pytest.approx(520 / 60)
    assert shortest["distance"] == 5.0
    assert all(route["route_source"] == "Valhalla" for route in data["routes"])
    assert len({tuple(tuple(point) for point in route["geometry"]) for route in data["routes"]}) == 3
    assert all("distance_vs_shortest_km" in route and "time_vs_fastest_minutes" in route for route in data["routes"])


def test_valhalla_request_asks_for_two_alternates_for_three_total_routes(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(route_api, "_get_valhalla_routes", REAL_VALHALLA_PROVIDER)

    class ValhallaClient:
        request = None

        async def post(self, url, json=None, headers=None):
            self.request = (url, json, headers)
            return FakeResponse({"code": "Ok", "routes": []})

    monkeypatch.setattr(settings, "VALHALLA_URL", "https://valhalla.example/route")
    client = ValhallaClient()
    response = asyncio.run(route_api._get_valhalla_routes(
        client,
        {"lat": 17.4435, "lon": 78.3772},
        {"lat": 17.4401, "lon": 78.3489},
    ))

    assert response["code"] == "Ok"
    url, payload, headers = client.request
    assert url == "https://valhalla.example/route"
    assert payload["alternates"] == 2
    assert payload["costing"] == "auto"
    assert payload["format"] == "osrm"
    assert payload["shape_format"] == "geojson"
    assert len(payload["locations"]) == 2
    assert headers["User-Agent"].startswith("IndiaTrafficIntelligence/")


def test_route_can_use_coordinates_across_india(monkeypatch):
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [osrm_route(4_000, 400, [[78.3772, 17.4435], [78.3489, 17.4401]])],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(app) as client:
        good = client.post("/api/routes/compare", json={**ORIGIN, "destination": "17.4401, 78.3489"})
        across_india = client.post("/api/routes/compare", json={
            "origin": "Chennai",
            "origin_lat": 13.0827,
            "origin_lon": 80.2707,
            "destination": "Delhi",
            "destination_lat": 28.6139,
            "destination_lon": 77.2090,
        })

    assert good.status_code == 200
    assert across_india.status_code == 200
    assert across_india.json()["origin_point"] == [13.0827, 80.2707]
    assert across_india.json()["destination_point"] == [28.6139, 77.209]


def test_gps_button_validation_endpoint_accepts_points_across_india():
    with TestClient(app) as client:
        inside = client.post("/api/routes/validate-point", json={"latitude": 17.4435, "longitude": 78.3772})
        outside_hyderabad = client.post("/api/routes/validate-point", json={"latitude": 28.6139, "longitude": 77.2090})
        outside = client.post("/api/routes/validate-point", json={"latitude": 0, "longitude": 0})
    assert inside.status_code == 200
    assert inside.json()["valid"] is True
    assert outside_hyderabad.status_code == 200
    assert outside_hyderabad.json()["boundary"] == "India"
    assert outside.status_code == 400
    assert "India" in outside.json()["detail"]


def test_geoapify_geocoder_and_road_router_support_locations_across_india(monkeypatch):
    class GeoapifyAndOsrmClient(FakeAsyncClient):
        async def get(self, url, params=None, headers=None):
            self.requests.append((url, params, headers))
            if url == "https://api.geoapify.com/v1/geocode/autocomplete":
                place = params["text"].casefold()
                if "chennai" in place:
                    return FakeResponse({"results": [{
                        "place_id": "chennai-id", "name": "Chennai", "formatted": "Chennai, Tamil Nadu, India",
                        "lat": 13.0827, "lon": 80.2707, "result_type": "city",
                    }]})
                return FakeResponse({"results": [{
                    "place_id": "delhi-id", "name": "Delhi", "formatted": "Delhi, India",
                    "lat": 28.6139, "lon": 77.2090, "result_type": "city",
                }]})
            return FakeResponse({
                "code": "Ok",
                "routes": [osrm_route(2_200_000, 28_800, [[80.2707, 13.0827], [77.2090, 28.6139]])],
            })

    monkeypatch.setattr(route_api.httpx, "AsyncClient", GeoapifyAndOsrmClient)
    route_api._route_cache.clear()
    route_api._geocode_cache.clear()
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={"origin": "Chennai", "destination": "Delhi"})
    assert response.status_code == 200
    assert response.json()["origin"] == "Chennai, Tamil Nadu, India"
    assert response.json()["destination"] == "Delhi, India"
    assert response.json()["origin_point"] == [13.0827, 80.2707]
    assert response.json()["destination_point"] == [28.6139, 77.209]
    autocomplete_requests = [
        request for request in GeoapifyAndOsrmClient.requests
        if request[0] == "https://api.geoapify.com/v1/geocode/autocomplete"
    ]
    assert len(autocomplete_requests) == 2
    assert all(request[1]["filter"] == "countrycode:in" for request in autocomplete_requests)


def test_coordinate_origin_from_gps_is_used_directly_with_manual_destination(monkeypatch):
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [osrm_route(4_000, 400, [[78.3772, 17.4435], [78.3489, 17.4401]])],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    route_api._route_cache.clear()
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={
            "origin": "17.443500, 78.377200",
            "destination": "17.4401, 78.3489",
        })
    assert response.status_code == 200
    assert response.json()["origin_point"] == [17.4435, 78.3772]
    assert response.json()["destination_point"] == [17.4401, 78.3489]
    assert all(request[0] != route_api.NOMINATIM for request in FakeAsyncClient.requests)


def test_nominatim_geocoder_discards_candidates_outside_india(monkeypatch):
    class GeocoderClient(FakeAsyncClient):
        async def get(self, url, params=None, headers=None):
            return FakeResponse([{"lat": "0", "lon": "0", "display_name": "Outside"}])

    async def no_wait():
        return None

    monkeypatch.setattr(route_api, "_wait_for_nominatim_slot", no_wait)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(route_api.geocode_nominatim_fallback(GeocoderClient(), "Somewhere"))
    assert "outside India" in failure.value.detail


def test_shortest_and_fastest_same_is_explicit(monkeypatch):
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [osrm_route(10_000, 900, [[78.3772, 17.4435], [78.3489, 17.4401]])],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(app) as client:
        response = client.post("/api/routes/compare", json={**ORIGIN, **DESTINATION})
    assert response.json()["shortest_fastest_same"] is True
    assert response.json()["routes"][0]["route_type"] == "shortest and fastest"


def test_directions_endpoint_uses_real_osrm_steps(monkeypatch):
    FakeAsyncClient.payload = {
        "code": "Ok",
        "routes": [osrm_route(8_200, 840, [[78.3772, 17.4435], [78.3489, 17.4401]], [{
            "name": "Gachibowli Road", "distance": 8_200, "duration": 840,
            "maneuver": {"type": "depart", "modifier": "south", "location": [78.3772, 17.4435]},
        }])],
    }
    monkeypatch.setattr(route_api.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(app) as client:
        response = client.post("/api/routes/directions", json={**ORIGIN, **DESTINATION})
    assert response.status_code == 200
    directions = response.json()
    assert directions["total_distance"] == 8.2
    assert directions["total_duration"] == 14.0
    assert directions["steps"][0]["road_name"] == "Gachibowli Road"
    assert directions["steps"][0]["turn_direction"] == "south"
    assert directions["steps"][0]["location"] == [17.4435, 78.3772]


def test_nominatim_cache_avoids_repeating_same_search():
    class GeocoderClient:
        calls = 0

        async def get(self, url, params=None, headers=None):
            self.calls += 1
            assert headers["User-Agent"].startswith("IndiaTrafficIntelligence/")
            return FakeResponse([{"lat": "17.4435", "lon": "78.3772", "display_name": "Hitech City"}])

    geocoder = GeocoderClient()
    async def lookup_twice():
        first = await route_api.geocode_nominatim_fallback(geocoder, "Hitech City")
        second = await route_api.geocode_nominatim_fallback(geocoder, "  Hitech   City ")
        return first, second

    first, second = asyncio.run(lookup_twice())
    assert first == second
    assert geocoder.calls == 1
