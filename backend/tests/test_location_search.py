from fastapi.testclient import TestClient

from app.api import location_search
from app.main import API_ROUTERS, app


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {"results": []}

    def json(self):
        return self.payload


class FakeAsyncClient:
    response = FakeResponse()
    requests = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None):
        self.requests.append((url, params))
        return self.response


def test_location_autocomplete_uses_private_key_and_returns_india_place(monkeypatch):
    secret = "geoapify-test-secret"
    monkeypatch.setattr(location_search.settings, "GEOAPIFY_API_KEY", secret)
    monkeypatch.setattr(location_search.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.requests = []
    FakeAsyncClient.response = FakeResponse(payload={"results": [{
        "place_id": "test-place-id",
        "name": "Gachibowli",
        "formatted": "Gachibowli, Hyderabad, Telangana, India",
        "lat": 17.4401,
        "lon": 78.3489,
        "result_type": "suburb",
        "categories": ["administrative.suburb"],
        "city": "Hyderabad",
        "county": "Rangareddy",
        "state": "Telangana",
    }]})

    with TestClient(app) as client:
        response = client.get("/api/locations/autocomplete", params={"text": "Gachibowli"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0] == {
        "place_id": "test-place-id",
        "name": "Gachibowli",
        "formatted_address": "Gachibowli, Hyderabad, Telangana, India",
        "latitude": 17.4401,
        "longitude": 78.3489,
        "place_type": "suburb",
        "categories": ["administrative.suburb"],
        "city": "Hyderabad",
        "district": "Rangareddy",
        "state": "Telangana",
    }
    assert secret not in response.text
    request_url, params = FakeAsyncClient.requests[0]
    assert request_url == location_search.GEOAPIFY_AUTOCOMPLETE_URL
    assert params == {
        "text": "Gachibowli",
        "filter": "countrycode:in",
        "format": "json",
        "limit": 8,
        "apiKey": secret,
    }


def test_location_autocomplete_requires_three_characters_and_handles_empty_results(monkeypatch):
    monkeypatch.setattr(location_search.settings, "GEOAPIFY_API_KEY", "test-secret")
    monkeypatch.setattr(location_search.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.requests = []
    FakeAsyncClient.response = FakeResponse(payload={"results": []})

    with TestClient(app) as client:
        too_short = client.get("/api/locations/autocomplete", params={"text": "IN"})
        empty = client.get("/api/locations/autocomplete", params={"text": "No such village"})

    assert too_short.status_code == 422
    assert not FakeAsyncClient.requests or FakeAsyncClient.requests[0][1]["text"] == "No such village"
    assert empty.status_code == 200
    assert empty.json()["results"] == []
    assert "No matching" in empty.json()["message"]


def test_location_autocomplete_sanitizes_provider_credential_and_quota_errors(monkeypatch):
    monkeypatch.setattr(location_search.settings, "GEOAPIFY_API_KEY", "test-secret")
    monkeypatch.setattr(location_search.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(app) as client:
        FakeAsyncClient.response = FakeResponse(status_code=401)
        invalid_key = client.get("/api/locations/autocomplete", params={"text": "Delhi"})
        FakeAsyncClient.response = FakeResponse(status_code=429)
        quota = client.get("/api/locations/autocomplete", params={"text": "Mumbai"})

    assert invalid_key.status_code == 502
    assert "credentials" in invalid_key.json()["detail"]
    assert "test-secret" not in invalid_key.text
    assert quota.status_code == 503
    assert "quota" in quota.json()["detail"]
