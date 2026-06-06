"""OSRM route resolver — fetches real road geometry for supply chain routes.

Calls the OSRM Route API to get actual road-following polylines instead of
straight-line arrows. Returns GeoJSON LineString coordinates that Leaflet
renders as real road routes on the map.

API: https://project-osrm.org/docs/v5.5.1/api/#route-service

Usage:
    coords = resolve_route_geometry(40.04, -76.08, 40.04, -76.31)
    # → [[lon, lat], [lon, lat], ...] (400+ points along actual road)
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)

# OSRM public demo server — for production, use self-hosted OSRM
OSRM_BASE_URL = "https://router.project-osrm.org"
OSRM_TIMEOUT = 10  # seconds per request
OSRM_PROFILE = "driving"


def resolve_route_geometry(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> list[list[float]] | None:
    """Fetch real road geometry from OSRM for a single route.

    Returns a list of [lon, lat] coordinates (GeoJSON order) representing
    the actual road path, or None if the API call fails.

    Falls back gracefully — callers should use straight-line if None returned.
    """
    # OSRM expects lon,lat order in the URL
    coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    url = (
        f"{OSRM_BASE_URL}/route/v1/{OSRM_PROFILE}/{coords}"
        f"?overview=full&geometries=geojson"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GRASS/2.0"})
        with urllib.request.urlopen(req, timeout=OSRM_TIMEOUT) as resp:
            data = json.loads(resp.read())

        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning("OSRM returned non-Ok: %s", data.get("code"))
            return None

        route = data["routes"][0]
        geometry = route.get("geometry", {})
        coordinates = geometry.get("coordinates", [])

        if len(coordinates) < 2:
            return None

        logger.debug(
            "OSRM route: %.1f miles, %d points",
            route.get("distance", 0) / 1609.34,
            len(coordinates),
        )
        return coordinates

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.warning("OSRM API call failed: %s", exc)
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("OSRM response parse error: %s", exc)
        return None


def resolve_routes_batch(
    routes: list[dict[str, Any]],
    max_routes: int = 20,
) -> list[dict[str, Any]]:
    """Resolve road geometry for a batch of optimization routes.

    Each route dict must have origin_lat, origin_lon, dest_lat, dest_lon.
    Returns the same routes with an added 'road_geometry' field containing
    the GeoJSON coordinates, or None if resolution failed.

    Limits to max_routes to avoid hammering the public OSRM server.
    """
    resolved = []
    count = 0

    for route in routes:
        r = dict(route)  # shallow copy

        if count < max_routes and all(
            k in route for k in ("origin_lat", "origin_lon", "dest_lat", "dest_lon")
        ):
            geometry = resolve_route_geometry(
                route["origin_lat"], route["origin_lon"],
                route["dest_lat"], route["dest_lon"],
            )
            if geometry:
                r["road_geometry"] = geometry
                count += 1
            else:
                r["road_geometry"] = None
        else:
            r["road_geometry"] = None

        resolved.append(r)

    logger.info("Resolved %d/%d routes with OSRM road geometry", count, len(routes))
    return resolved
