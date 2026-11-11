"""Road routing with Google Places API (New) and Google Routes API for nationwide India coverage."""

import asyncio
import json
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from app.api.location_search import autocomplete_locations

router = APIRouter()

GOOGLE_MAPS_API_KEY = None  # Will be loaded from settings
PLACES_API_BASE = "https://places.googleapis.com/v1/places:autocomplete"
ROUTES_API_BASE = "https://routes.googleapis.com/directions/v2:computeRoutes"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://router.project-osrm.org/route/v1/driving"
INDIA_VIEWBOX = "68.1,37.6,97.4,6.5"
NOMINATIM_USER_AGENT = "IndiaTrafficIntelligence/1.0 (academic project)"
GEOCODE_CACHE_TTL = 30 * 24 * 60 * 60
ROUTE_CACHE_TTL = 5 * 60
NOMINATIM_MIN_INTERVAL = 1.05
MAX_ROUTES = 4

_cache_lock = RLock()
_geocode_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_route_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_last_nominatim_start = 0.0
_google_api_key: Optional[str] = None


def get_google_api_key() -> str:
    global _google_api_key
    if _google_api_key is not None:
        return _google_api_key
    from app.core.config import settings
    _google_api_key = settings.GOOGLE_MAPS_API_KEY
    if not _google_api_key:
        raise HTTPException(status_code=500, detail="Google Maps API key not configured. Set GOOGLE_MAPS_API_KEY in backend/.env")
    return _google_api_key


class RouteCompareRequest(BaseModel):
    origin: Optional[str] = Field(default=None, max_length=250)
    destination: Optional[str] = Field(default=None, max_length=250)
    origin_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    origin_lon: Optional[float] = Field(default=None, ge=-180, le=180)
    destination_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    destination_lon: Optional[float] = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinate_pairs_are_complete(self):
        if (self.origin_lat is None) != (self.origin_lon is None):
            raise ValueError("Provide both latitude and longitude for the starting point.")
        if (self.destination_lat is None) != (self.destination_lon is None):
            raise ValueError("Provide both latitude and longitude for the destination.")
        return self


class PointValidationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@lru_cache(maxsize=1)
def get_india_boundary():
    """Return a simple bounding box for India as a fallback."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [68.1, 37.6],
            [97.4, 37.6],
            [97.4, 6.5],
            [68.1, 6.5],
            [68.1, 37.6]
        ]]
    }


def is_inside_india(lat: float, lon: float) -> bool:
    """Check if coordinates are within India's approximate bounding box."""
    return 6.5 <= lat <= 37.6 and 68.1 <= lon <= 97.4


def _validate_point(lat: float, lon: float, label: str) -> None:
    if not is_inside_india(lat, lon):
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be inside India. Choose a valid Indian location.",
        )


@router.post("/routes/validate-point")
def validate_route_point(request: PointValidationRequest):
    """Validate a browser GPS point against India boundary."""
    _validate_point(request.latitude, request.longitude, "GPS starting point")
    return {"valid": True, "latitude": request.latitude, "longitude": request.longitude, "boundary": "India"}


def _coordinate_query(text: str) -> Optional[dict[str, Any]]:
    import re
    match = re.fullmatch(r"\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*", text)
    if not match:
        return None
    lat, lon = (float(value) for value in match.groups())
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Enter coordinates as latitude, longitude using valid values.")
    return {"lat": lat, "lon": lon, "name": f"{lat:.6f}, {lon:.6f}"}


async def _wait_for_nominatim_slot() -> None:
    """Throttle requests across concurrent calls in this API process."""
    global _last_nominatim_start
    with _cache_lock:
        now = time.monotonic()
        scheduled_start = max(now, _last_nominatim_start + NOMINATIM_MIN_INTERVAL)
        _last_nominatim_start = scheduled_start
    delay = scheduled_start - now
    if delay > 0:
        await asyncio.sleep(delay)


async def geocode_google_places(client: httpx.AsyncClient, text: str) -> dict[str, Any]:
    """Geocode using Google Places API (New) Autocomplete."""
    api_key = get_google_api_key()
    
    coordinate = _coordinate_query(text)
    if coordinate:
        return coordinate

    normalized = " ".join(text.casefold().split())
    now = time.monotonic()
    with _cache_lock:
        cached = _geocode_cache.get(normalized)
        if cached and now - cached[0] < GEOCODE_CACHE_TTL:
            return dict(cached[1])
        if cached:
            _geocode_cache.pop(normalized, None)

    try:
        response = await client.post(
            PLACES_API_BASE,
            params={"key": api_key},
            headers={
                "Content-Type": "application/json",
                "X-Goog-FieldMask": "suggestions.placePrediction.placeId,suggestions.placePrediction.text,suggestions.placePrediction.structuredFormat",
            },
            json={
                "input": text,
                "includedRegionCodes": ["in"],
                "languageCode": "en",
                "regionCode": "IN",
                "origin": {"latitude": 20.5937, "longitude": 78.9629},
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Google Places search timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            message = "Google Places API is rate limited. Wait a moment and retry."
        elif status == 403:
            message = "Google Places API access denied. Check API key and billing."
        else:
            message = "Google Places API is temporarily unavailable. Please try again."
        raise HTTPException(status_code=502, detail=message) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Google Places API is temporarily unavailable.") from exc

    suggestions = data.get("suggestions", [])
    if not suggestions:
        raise HTTPException(status_code=404, detail=f"Could not find '{text}' in India. Try a nearby landmark.")

    for suggestion in suggestions:
        prediction = suggestion.get("placePrediction")
        if not prediction:
            continue
        place_id = prediction.get("placeId")
        if not place_id:
            continue
        
        place_details = await get_place_details(client, place_id)
        if place_details:
            result = {
                "lat": place_details["latitude"],
                "lon": place_details["longitude"],
                "name": place_details["formattedAddress"] or place_details["displayName"],
                "place_id": place_id,
            }
            with _cache_lock:
                _geocode_cache[normalized] = (time.monotonic(), result)
            return result

    raise HTTPException(status_code=404, detail=f"Could not resolve location for '{text}'. Try a more specific search.")


async def geocode_location_search(text: str) -> dict[str, Any]:
    """Resolve manually entered route endpoints with the same Geoapify provider as autocomplete."""
    coordinate = _coordinate_query(text)
    if coordinate:
        return coordinate

    normalized = " ".join(text.casefold().split())
    now = time.monotonic()
    with _cache_lock:
        cached = _geocode_cache.get(normalized)
        if cached and now - cached[0] < GEOCODE_CACHE_TTL:
            return dict(cached[1])

    try:
        response = await autocomplete_locations(text)
        results = response.get("results", [])
        if not results:
            raise HTTPException(status_code=404, detail=f"Could not find '{text}' in India. Try a nearby landmark.")
    except HTTPException as exc:
        if exc.status_code not in {404, 502, 503, 504}:
            raise
        # If Geoapify is temporarily unavailable, preserve manual route entry
        # with the existing India-filtered OpenStreetMap fallback.
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            result = await geocode_nominatim_fallback(client, text)
        with _cache_lock:
            _geocode_cache[normalized] = (time.monotonic(), result)
        return result
    match = results[0]
    result = {
        "lat": match["latitude"],
        "lon": match["longitude"],
        "name": match["formatted_address"],
        "place_id": match["place_id"],
    }
    _validate_point(result["lat"], result["lon"], "Location")
    with _cache_lock:
        _geocode_cache[normalized] = (time.monotonic(), result)
    return result


async def get_place_details(client: httpx.AsyncClient, place_id: str) -> Optional[dict[str, Any]]:
    """Fetch place details including coordinates from Google Places API."""
    api_key = get_google_api_key()
    try:
        response = await client.get(
            f"https://places.googleapis.com/v1/places/{place_id}",
            params={"key": api_key},
            headers={
                "Content-Type": "application/json",
                "X-Goog-FieldMask": "location,displayName,formattedAddress",
            },
        )
        response.raise_for_status()
        data = response.json()
        location = data.get("location")
        if not location:
            return None
        return {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "displayName": data.get("displayName", {}).get("text"),
            "formattedAddress": data.get("formattedAddress"),
        }
    except httpx.HTTPError:
        return None


async def geocode_nominatim_fallback(client: httpx.AsyncClient, text: str) -> dict[str, Any]:
    """Fallback geocoding using Nominatim (OpenStreetMap) for India-wide search."""
    coordinate = _coordinate_query(text)
    if coordinate:
        return coordinate

    normalized = " ".join(text.casefold().split())
    now = time.monotonic()
    with _cache_lock:
        cached = _geocode_cache.get(normalized)
        if cached and now - cached[0] < GEOCODE_CACHE_TTL:
            return dict(cached[1])
        if cached:
            _geocode_cache.pop(normalized, None)

    await _wait_for_nominatim_slot()
    try:
        response = await client.get(
            NOMINATIM,
            params={
                "q": f"{text}, India",
                "format": "jsonv2",
                "limit": 5,
                "viewbox": INDIA_VIEWBOX,
                "bounded": 1,
                "countrycodes": "in",
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
        )
        response.raise_for_status()
        candidates = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Location search timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            message = "Location search is rate limited. Wait a moment and retry."
        else:
            message = "Location search is temporarily unavailable. Please try again."
        raise HTTPException(status_code=502, detail=message) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Location search is temporarily unavailable.") from exc

    if not candidates:
        raise HTTPException(status_code=404, detail=f"Could not find '{text}' in India. Try a nearby landmark.")

    for candidate in candidates:
        try:
            point = {"lat": float(candidate["lat"]), "lon": float(candidate["lon"])}
        except (KeyError, TypeError, ValueError):
            continue
        if is_inside_india(point["lat"], point["lon"]):
            result = {**point, "name": candidate.get("display_name") or text}
            with _cache_lock:
                _geocode_cache[normalized] = (time.monotonic(), result)
            return result

    raise HTTPException(
        status_code=400,
        detail=f"'{text}' resolved outside India. Choose a location within India.",
    )


def _route_cache_key(origin: dict[str, Any], destination: dict[str, Any]) -> str:
    return f"{origin['lon']:.6f},{origin['lat']:.6f};{destination['lon']:.6f},{destination['lat']:.6f}"


def _format_step(step: dict[str, Any]) -> dict[str, Any]:
    maneuver = step.get("maneuver") or {}
    kind = (maneuver.get("type") or "continue").replace("_", " ")
    modifier = maneuver.get("modifier")
    road_name = (step.get("name") or "").strip() or None
    if kind == "arrive":
        instruction = "Arrive at your destination"
    elif kind == "depart":
        instruction = f"Head {modifier}" if modifier else "Start route"
    else:
        instruction = " ".join(part for part in (kind, modifier, f"onto {road_name}" if road_name else None) if part)
    distance_km = round(float(step.get("distance", 0)) / 1000, 2)
    duration_minutes = round(float(step.get("duration", 0)) / 60, 1)
    maneuver_location = maneuver.get("location") or []
    return {
        "instruction": instruction,
        "road_name": road_name,
        "turn_direction": modifier,
        "location": [float(maneuver_location[1]), float(maneuver_location[0])] if len(maneuver_location) >= 2 else None,
        "distance": distance_km,
        "distance_km": distance_km,
        "duration": duration_minutes,
        "duration_minutes": duration_minutes,
    }


def _normalize_routes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for osrm_route in payload.get("routes", []):
        coordinates = (osrm_route.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        geometry = [[float(lat), float(lon)] for lon, lat, *_ in coordinates]
        distance_meters = float(osrm_route.get("distance") or 0)
        duration_seconds = float(osrm_route.get("duration") or 0)
        if distance_meters <= 0 or duration_seconds <= 0:
            continue

        legs = osrm_route.get("legs") or []
        steps = [_format_step(step) for leg in legs for step in leg.get("steps", [])]
        candidate = {
            "distance_meters": distance_meters,
            "distance": round(distance_meters / 1000, 2),
            "duration": round(duration_seconds / 60, 1),
            "geometry": geometry,
            "steps": steps,
        }
        if any(_nearly_same_route(candidate, prior) for prior in candidates):
            continue
        candidates.append(candidate)
        if len(candidates) == MAX_ROUTES:
            break

    if not candidates:
        raise HTTPException(status_code=404, detail="The routing service returned no usable road routes.")

    shortest = min(candidates, key=lambda route: route["distance_meters"])
    fastest = min(candidates, key=lambda route: route["duration"])
    for index, route in enumerate(candidates, start=1):
        route["route_id"] = f"route-{index}"
        route["route_number"] = index
        route["is_shortest"] = route is shortest
        route["is_fastest"] = route is fastest
        if route is shortest and route is fastest:
            route["route_type"] = "shortest and fastest"
        elif route is shortest:
            route["route_type"] = "shortest"
        elif route is fastest:
            route["route_type"] = "fastest estimated"
        else:
            route["route_type"] = "alternative"
        route.pop("distance_meters")
    return candidates


def _nearly_same_route(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if not first["geometry"] or not second["geometry"]:
        return False
    if max(first["distance"], second["distance"]) / min(first["distance"], second["distance"]) > 1.08:
        return False
    
    def project_line(geometry: list[list[float]], reference_lat: float) -> list[tuple[float, float]]:
        import math
        x_scale = 111_320 * math.cos(math.radians(reference_lat))
        y_scale = 111_320
        return [(lon * x_scale, lat * y_scale) for lat, lon in geometry]
    
    def point_to_line_distance(point: tuple[float, float], line: list[tuple[float, float]]) -> float:
        import math
        if len(line) == 1:
            return math.dist(point, line[0])
        minimum = math.inf
        for start, end in zip(line, line[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_squared = dx * dx + dy * dy
            if length_squared == 0:
                distance = math.dist(point, start)
            else:
                fraction = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
                projection = (start[0] + fraction * dx, start[1] + fraction * dy)
                distance = math.dist(point, projection)
            minimum = min(minimum, distance)
        return minimum
    
    def sample_line(line: list[tuple[float, float]], count: int = 21) -> list[tuple[float, float]]:
        import math
        lengths = [math.dist(start, end) for start, end in zip(line, line[1:])]
        total_length = sum(lengths)
        if total_length == 0:
            return [line[0]] * count
        samples = []
        for index in range(count):
            remaining = total_length * index / (count - 1)
            for segment_index, length in enumerate(lengths):
                if remaining <= length or segment_index == len(lengths) - 1:
                    ratio = remaining / length if length else 0
                    start, end = line[segment_index], line[segment_index + 1]
                    samples.append((start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1])))
                    break
                remaining -= length
        return samples

    reference_lat = (first["geometry"][0][0] + second["geometry"][0][0]) / 2
    first_line = project_line(first["geometry"], reference_lat)
    second_line = project_line(second["geometry"], reference_lat)
    first_samples, second_samples = sample_line(first_line), sample_line(second_line)
    hausdorff = max(
        max(point_to_line_distance(point, second_line) for point in first_samples),
        max(point_to_line_distance(point, first_line) for point in second_samples),
    )
    if hausdorff <= 125:
        return True

    return (
        sum(point_to_line_distance(point, second_line) <= 80 for point in first_samples) / len(first_samples) >= 0.88
        and sum(point_to_line_distance(point, first_line) <= 80 for point in second_samples) / len(second_samples) >= 0.88
    )


async def _get_osrm_routes(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    params = {"overview": "full", "geometries": "geojson", "steps": "true", "alternatives": "3"}
    try:
        response = await client.get(url, params=params, headers={"User-Agent": NOMINATIM_USER_AGENT})
        response.raise_for_status()
        payload = response.json()
        error_message = str(payload.get("message") or "").lower()
        if payload.get("code") == "Ok" or "alternative" not in error_message:
            return payload
        fallback = await client.get(url, params={**params, "alternatives": "false"}, headers={"User-Agent": NOMINATIM_USER_AGENT})
        fallback.raise_for_status()
        return fallback.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Road routing timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="The free OSRM routing service is temporarily unavailable.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="The free OSRM routing service is temporarily unavailable.") from exc


async def _get_google_routes(client: httpx.AsyncClient, origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    """Get routes using Google Routes API with traffic awareness."""
    api_key = get_google_api_key()
    
    intermediates = []
    if "geometry" in origin and origin["geometry"]:
        geometry = origin["geometry"]
        max_intermediates = 23
        stride = max(1, (len(geometry) - 2) // max_intermediates)
        for index in range(stride, len(geometry) - 1, stride):
            if len(intermediates) >= max_intermediates:
                break
            lat, lng = geometry[index]
            intermediates.append({"location": {"latLng": {"latitude": lat, "longitude": lng}}, "via": True})
    
    request_body = {
        "origin": {"location": {"latLng": {"latitude": origin["lat"], "longitude": origin["lon"]}}},
        "destination": {"location": {"latLng": {"latitude": destination["lat"], "longitude": destination["lon"]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": True,
        "extraComputations": ["TRAFFIC_ON_POLYLINE"],
        "routeModifiers": {"avoidTolls": False, "avoidHighways": False, "avoidFerries": False},
        "languageCode": "en-IN",
        "units": "METRIC",
    }
    
    if intermediates:
        request_body["intermediates"] = intermediates
    
    try:
        response = await client.post(
            ROUTES_API_BASE,
            params={"key": api_key},
            headers={
                "Content-Type": "application/json",
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.staticDuration,routes.polyline.encodedPolyline,routes.legs.steps.navigationInstruction,routes.legs.steps.distanceMeters,routes.legs.steps.staticDuration,routes.legs.steps.startLocation,routes.legs.distanceMeters,routes.legs.duration,routes.travelAdvisory,routes.routeLabels",
            },
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get("routes"):
            raise HTTPException(status_code=404, detail="No route found between these locations.")
        
        return data
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Traffic-aware route calculation timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            message = "Traffic-aware route calculation is rate limited. Wait a moment and retry."
        elif status == 403:
            message = "Traffic-aware route calculation is unavailable. Check map-service access and billing."
        else:
            message = "Traffic-aware route calculation is temporarily unavailable. Please try again."
        raise HTTPException(status_code=502, detail=message) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Traffic-aware route calculation is temporarily unavailable.") from exc


def _decode_polyline(encoded: str) -> list[list[float]]:
    """Decode Google encoded polyline to lat/lng coordinates."""
    index = 0
    lat = 0
    lng = 0
    coordinates = []
    while index < len(encoded):
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng
        
        coordinates.append([lat / 1e5, lng / 1e5])
    return coordinates


def _normalize_google_routes(data: dict[str, Any], origin: dict[str, Any], destination: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Google Routes API response to our internal format."""
    candidates: list[dict[str, Any]] = []
    
    for route in data.get("routes", []):
        encoded_polyline = route.get("polyline", {}).get("encodedPolyline")
        if not encoded_polyline:
            continue
        
        geometry = _decode_polyline(encoded_polyline)
        if len(geometry) < 2:
            continue
        
        distance_meters = float(route.get("distanceMeters", 0))
        duration_seconds = float(route.get("duration", "0s").rstrip("s"))
        static_duration_seconds = (
            float(route["staticDuration"].rstrip("s"))
            if route.get("staticDuration") is not None
            else None
        )
        
        if distance_meters <= 0 or duration_seconds <= 0:
            continue
        
        steps = []
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                maneuver = step.get("navigationInstruction", {})
                instruction = maneuver.get("instructions") or maneuver.get("maneuver", "continue")
                road_name = step.get("roadName", "")
                distance_km = round(float(step.get("distanceMeters", 0)) / 1000, 2)
                step_duration = step.get("staticDuration", step.get("duration", "0s"))
                duration_minutes = round(float(step_duration.rstrip("s")) / 60, 1)
                start_location = step.get("startLocation", {}).get("latLng", {})
                steps.append({
                    "instruction": instruction,
                    "road_name": road_name or None,
                    "turn_direction": None,
                    "location": [start_location.get("latitude"), start_location.get("longitude")] if start_location else None,
                    "distance": distance_km,
                    "distance_km": distance_km,
                    "duration": duration_minutes,
                    "duration_minutes": duration_minutes,
                })
        
        route_label = route.get("routeLabels", ["ALTERNATIVE"])[0]
        route_type = "alternative"
        if route_label == "DEFAULT_ROUTE":
            route_type = "fastest estimated"
        elif route_label == "SHORTEST":
            route_type = "shortest"
        
        candidates.append({
            "distance": round(distance_meters / 1000, 2),
            "duration": round(duration_seconds / 60, 1),
            "static_duration": round(static_duration_seconds / 60, 1) if static_duration_seconds is not None else None,
            "geometry": geometry,
            "steps": steps,
            "route_type": route_type,
            "route_label": route_label,
        })
    
    if not candidates:
        raise HTTPException(status_code=404, detail="No usable traffic-aware routes were returned.")
    
    shortest = min(candidates, key=lambda r: r["distance"])
    fastest = min(candidates, key=lambda r: r["duration"])
    
    for index, route in enumerate(candidates, start=1):
        route["route_id"] = f"route-{index}"
        route["route_number"] = index
        route["is_shortest"] = route is shortest
        route["is_fastest"] = route is fastest
        if route is shortest and route is fastest:
            route["route_type"] = "shortest and fastest"
        elif route is shortest:
            route["route_type"] = "shortest"
        elif route is fastest:
            route["route_type"] = "fastest estimated"
    
    return candidates


@router.post("/routes/compare")
async def compare_routes(req: RouteCompareRequest):
    if req.origin_lat is not None and req.origin_lon is not None:
        origin = {"lat": req.origin_lat, "lon": req.origin_lon, "name": req.origin or "Current location"}
        if "geometry" not in origin:
            origin["geometry"] = None
    elif req.origin and req.origin.strip():
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            origin = await geocode_location_search(req.origin.strip())
            if "geometry" not in origin:
                origin["geometry"] = None
    else:
        raise HTTPException(status_code=400, detail="Enter a starting point or allow location access.")

    if req.destination_lat is not None and req.destination_lon is not None:
        destination = {"lat": req.destination_lat, "lon": req.destination_lon, "name": req.destination or "Destination"}
    elif req.destination and req.destination.strip():
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            destination = await geocode_location_search(req.destination.strip())
    else:
        raise HTTPException(status_code=400, detail="Enter a destination.")

    _validate_point(origin["lat"], origin["lon"], "Starting point")
    _validate_point(destination["lat"], destination["lon"], "Destination")

    cache_key = _route_cache_key(origin, destination)
    with _cache_lock:
        cached = _route_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < ROUTE_CACHE_TTL:
            result = json.loads(json.dumps(cached[1]))
            result["origin"] = origin["name"]
            result["destination"] = destination["name"]
            result["retrieved_at"] = datetime.now(timezone.utc).isoformat()
            return result
        if cached:
            _route_cache.pop(cache_key, None)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
        try:
            google_data = await _get_google_routes(client, origin, destination)
            routes = _normalize_google_routes(google_data, origin, destination)
            data_source = "Traffic-aware route estimate"
            traffic_note = "Estimated travel time uses current traffic conditions where available. Typical travel time is also shown for comparison."
        except Exception:
            url = f"{OSRM}/{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}"
            payload = await _get_osrm_routes(client, url)
            if payload.get("code") != "Ok" or not payload.get("routes"):
                if payload.get("code") in {"NoRoute", "NoSegment"}:
                    raise HTTPException(status_code=404, detail="No drivable road route was found between these locations.")
                raise HTTPException(status_code=502, detail="The routing service could not calculate a road route. Please retry.")
            routes = _normalize_routes(payload)
            data_source = "Road-network estimate"
            traffic_note = "Live traffic-aware routing is unavailable for this request; travel time is a road-network estimate."

    same_best = next(route for route in routes if route["is_shortest"])["route_id"] == next(route for route in routes if route["is_fastest"])["route_id"]
    alternatives_note = (
        "Only one distinct road route was returned; alternatives are unavailable for this trip."
        if len(routes) == 1
        else f"{len(routes)} distinct road routes returned."
    )
    result = {
        "origin": origin["name"],
        "destination": destination["name"],
        "origin_point": [origin["lat"], origin["lon"]],
        "destination_point": [destination["lat"], destination["lon"]],
        "routes": routes,
        "route_count": len(routes),
        "alternatives_available": len(routes) > 1,
        "alternatives_note": alternatives_note,
        "shortest_fastest_same": same_best,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "data_source": data_source,
        "traffic_note": traffic_note,
    }
    with _cache_lock:
        _route_cache[cache_key] = (time.monotonic(), json.loads(json.dumps(result)))
    return result


@router.post("/routes/directions")
async def get_directions(request: RouteCompareRequest):
    result = await compare_routes(request)
    fastest = next((route for route in result["routes"] if route["is_fastest"]), result["routes"][0])
    return {
        "origin": result["origin"],
        "destination": result["destination"],
        "total_distance": fastest["distance"],
        "total_duration": fastest["duration"],
        "total_duration_in_traffic": None,
        "steps": fastest["steps"],
        "geometry": fastest["geometry"],
        "data_source": result["data_source"],
        "traffic_note": result["traffic_note"],
    }
