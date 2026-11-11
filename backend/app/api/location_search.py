"""India-wide place autocomplete backed by Geoapify."""

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

router = APIRouter()
GEOAPIFY_AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"


@router.get("/locations/autocomplete")
async def autocomplete_locations(text: str = Query(..., min_length=3, max_length=200)):
    query = text.strip()
    if len(query) < 3:
        raise HTTPException(status_code=422, detail="Enter at least 3 characters to search.")
    api_key = settings.GEOAPIFY_API_KEY
    if not api_key:
        raise HTTPException(status_code=503, detail="Location search is not configured on the server.")

    params = {
        "text": query,
        "filter": "countrycode:in",
        "format": "json",
        "limit": 8,
        "apiKey": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=4)) as client:
            response = await client.get(GEOAPIFY_AUTOCOMPLETE_URL, params=params)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Location search timed out. Please try again.") from None
    except httpx.HTTPError:
        # Do not include the exception text: request URLs contain the private API key.
        raise HTTPException(status_code=502, detail="Location search is temporarily unavailable.") from None

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=502, detail="Location search credentials were rejected by the provider.")
    if response.status_code == 429:
        raise HTTPException(status_code=503, detail="Location search quota is temporarily exhausted. Please try again later.")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="Location search provider is temporarily unavailable.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Location search provider rejected the request.")

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Location search provider returned an invalid response.") from None

    raw_results = payload.get("results", []) if isinstance(payload, dict) else []
    results = []
    for item in raw_results[:8] if isinstance(raw_results, list) else []:
        if not isinstance(item, dict):
            continue
        latitude, longitude = item.get("lat"), item.get("lon")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            continue
        name = item.get("name") or item.get("address_line1") or item.get("formatted")
        formatted_address = item.get("formatted") or item.get("address_line2") or name
        if not isinstance(name, str) or not isinstance(formatted_address, str):
            continue
        categories = item.get("categories")
        results.append({
            "place_id": str(item.get("place_id") or f"{latitude},{longitude}"),
            "name": name,
            "formatted_address": formatted_address,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "place_type": item.get("result_type") or item.get("category") or "place",
            "categories": categories if isinstance(categories, list) else [],
            "city": item.get("city") or item.get("town") or item.get("village") or item.get("municipality"),
            "district": item.get("county") or item.get("district"),
            "state": item.get("state"),
        })

    return {"results": results, "message": None if results else "No matching locations were found in India."}
