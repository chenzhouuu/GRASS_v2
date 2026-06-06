"""Deterministic GeoJSON extractor for GRASS.

Converts Cypher query results containing lat/lon columns into a GeoJSON
FeatureCollection for frontend Leaflet rendering.  No LLM needed — this
is a pure data transformation.

Supported patterns:
- **Point markers**: records with ``lat``/``lon`` columns -> Point features
- **Route lines**: records with ``origin_lat``/``origin_lon`` +
  ``dest_lat``/``dest_lon`` -> LineString features

GeoJSON coordinates use ``[longitude, latitude]`` order per RFC 7946.
Leaflet's ``L.geoJSON()`` handles the coordinate swap automatically.

Reference: https://geojson.org/ , https://leafletjs.com/examples/geojson/
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Column name patterns for coordinate detection
_LAT_NAMES = {"lat", "latitude"}
_LON_NAMES = {"lon", "lng", "longitude"}
_ORIGIN_LAT = {
    "origin_lat", "origin_latitude", "src_lat", "from_lat",
    "farm_lat", "supplier_lat", "source_lat", "start_lat",
}
_ORIGIN_LON = {
    "origin_lon", "origin_lng", "origin_longitude", "src_lon", "from_lon",
    "farm_lon", "farm_lng", "supplier_lon", "source_lon", "start_lon",
}
_DEST_LAT = {
    "dest_lat", "dest_latitude", "dst_lat", "to_lat", "destination_lat",
    "processor_lat", "proc_lat", "target_lat", "end_lat", "plant_lat",
}
_DEST_LON = {
    "dest_lon", "dest_lng", "dest_longitude", "dst_lon", "to_lon", "destination_lon",
    "processor_lon", "processor_lng", "proc_lon", "proc_lng", "target_lon", "end_lon", "plant_lon",
}
_NAME_NAMES = {"name", "label", "title", "entity_name"}


def _find_column(keys_lower: dict[str, str], candidates: set[str]) -> str | None:
    """Find the first matching column name (case-insensitive).

    Handles both exact matches (``lat``) and Cypher property-accessor
    patterns (``d.lat``, ``farm.latitude``) where the column name ends
    with a dot followed by the candidate name.
    """
    # 1. Exact match first
    for candidate in candidates:
        if candidate in keys_lower:
            return keys_lower[candidate]
    # 2. Suffix match for Cypher "alias.property" patterns (e.g. "d.lat")
    for key_low, key_orig in keys_lower.items():
        for candidate in candidates:
            if key_low.endswith("." + candidate):
                return key_orig
    return None


def _strip_alias(key: str) -> str:
    """Strip Cypher alias prefix from a column name.

    ``d.name`` -> ``name``, ``farm.herd_size`` -> ``herd_size``,
    ``name`` -> ``name`` (unchanged).
    """
    dot_pos = key.rfind(".")
    return key[dot_pos + 1 :] if dot_pos >= 0 else key


def _safe_float(value: Any) -> float | None:
    """Convert to float, returning None for non-numeric / null values.

    Also handles Neo4j spatial Point objects (WGS84Point) by attempting
    to read their coordinate attributes.
    """
    if value is None:
        return None
    # Native numeric types — fast path
    if isinstance(value, (int, float)):
        return float(value)
    # Neo4j WGS84Point — has .latitude / .longitude attrs
    # (won't match plain dicts or strings)
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return None  # caller should use _extract_point() instead
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _extract_point_coords(value: Any) -> tuple[float, float] | None:
    """Extract (lat, lon) from a Neo4j spatial Point object.

    Returns None if the value is not a Point-like object.
    """
    if value is None:
        return None
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        try:
            return (float(value.latitude), float(value.longitude))
        except (ValueError, TypeError):
            return None
    return None


def _valid_lat(v: float) -> bool:
    return -90.0 <= v <= 90.0


def _valid_lon(v: float) -> bool:
    return -180.0 <= v <= 180.0


def _valid_coords(lat: float, lon: float) -> bool:
    """Validate that coordinates are within WGS84 bounds."""
    return _valid_lat(lat) and _valid_lon(lon)


def _infer_entity_type(record: dict) -> str:
    """Infer the entity type from record columns or values.

    Uses characteristic column names from the GRASS dairy supply chain schema
    to determine what kind of entity this record represents.  Handles both
    bare column names (``herd_size``) and Cypher alias.property patterns
    (``d.herd_size``).
    """
    # Strip alias prefixes so "d.herd_size" -> "herd_size"
    keys_stripped = {_strip_alias(k).lower() for k in record.keys()}

    # Check for Neo4j _labels (e.g., ["DairyFarm"])
    labels = record.get("_labels") or record.get("labels")
    if isinstance(labels, list) and labels:
        label = str(labels[0]).lower()
        if "farm" in label:
            return "farm"
        if "processor" in label or "plant" in label:
            return "processor"
        if "distribution" in label or "warehouse" in label:
            return "distributor"
        if "retailer" in label or "store" in label:
            return "retailer"
        if "cooperative" in label or "coop" in label:
            return "cooperative"
        if "storage" in label:
            return "warehouse"
        return label

    # Infer from characteristic columns (alias-stripped)
    if any(k in keys_stripped for k in ("herd_size", "milk_grade", "annual_production_lbs")):
        return "farm"
    if any(k in keys_stripped for k in ("processing_capacity_lbs_day", "plant_type", "organic_capable")):
        return "processor"
    if any(k in keys_stripped for k in ("storage_capacity", "refrigerated")):
        return "warehouse"
    if any(k in keys_stripped for k in ("retail_type", "store_format")):
        return "retailer"

    return ""


def _build_properties(
    record: dict, exclude_keys: set[str], entity_type: str = ""
) -> dict[str, Any]:
    """Build GeoJSON properties from all non-coordinate columns.

    Strips Cypher alias prefixes (``d.name`` -> ``name``) and skips
    null values.
    """
    props: dict[str, Any] = {}
    for k, v in record.items():
        if k in exclude_keys or v is None:
            continue
        clean_key = _strip_alias(k)
        props[clean_key] = v
    if "type" not in props and "category" not in props and entity_type:
        props["type"] = entity_type
    return props


def extract_geo_data(records: list[dict]) -> dict:
    """Convert Cypher results to a GeoJSON FeatureCollection.

    Parameters
    ----------
    records : list[dict]
        Cypher query results (list of row dicts).

    Returns
    -------
    dict
        A GeoJSON FeatureCollection with Point and/or LineString features.
        Returns an empty FeatureCollection if no geographic columns found.
    """
    empty = {"type": "FeatureCollection", "features": []}
    if not records:
        return empty

    # Build case-insensitive column lookup: lowered_name -> original_name
    first = records[0]
    keys_lower = {k.lower(): k for k in first.keys()}

    # Detect route pattern (origin + destination coordinates)
    o_lat_col = _find_column(keys_lower, _ORIGIN_LAT)
    o_lon_col = _find_column(keys_lower, _ORIGIN_LON)
    d_lat_col = _find_column(keys_lower, _DEST_LAT)
    d_lon_col = _find_column(keys_lower, _DEST_LON)
    is_route = all([o_lat_col, o_lon_col, d_lat_col, d_lon_col])

    # Detect point pattern (single lat/lon)
    lat_col = _find_column(keys_lower, _LAT_NAMES)
    lon_col = _find_column(keys_lower, _LON_NAMES)
    is_point = bool(lat_col and lon_col) and not is_route

    # Detect Neo4j Point column (e.g. RETURN d.location)
    point_col: str | None = None
    if not is_route and not is_point:
        # Check if any value in the first record is a Neo4j Point object
        for key, val in first.items():
            if _extract_point_coords(val) is not None:
                point_col = key
                is_point = True
                break

    if not is_route and not is_point:
        logger.info("No geographic columns detected in %d records", len(records))
        return empty

    # Infer entity type once from the first record (all share the same schema)
    entity_type = _infer_entity_type(first)

    features: list[dict] = []
    skipped = 0

    if is_route:
        # Also exclude standalone lat/lon if present alongside route coords
        coord_keys = {o_lat_col, o_lon_col, d_lat_col, d_lon_col}
        if lat_col:
            coord_keys.add(lat_col)
        if lon_col:
            coord_keys.add(lon_col)

        # Collect valid routes first
        valid_routes: list[tuple[float, float, float, float, dict]] = []
        for record in records:
            o_lat = _safe_float(record.get(o_lat_col))
            o_lon = _safe_float(record.get(o_lon_col))
            d_lat = _safe_float(record.get(d_lat_col))
            d_lon = _safe_float(record.get(d_lon_col))

            if None in (o_lat, o_lon, d_lat, d_lon):
                continue

            if not (_valid_coords(o_lat, o_lon) and _valid_coords(d_lat, d_lon)):
                skipped += 1
                continue

            valid_routes.append((o_lat, o_lon, d_lat, d_lon, record))

        # Resolve real road geometry via OSRM (top 20 routes)
        road_geometries: list[list[list[float]] | None] = [None] * len(valid_routes)
        try:
            from ..utils.route_resolver import resolve_route_geometry
            for i, (o_lat, o_lon, d_lat, d_lon, _) in enumerate(valid_routes[:20]):
                geom = resolve_route_geometry(o_lat, o_lon, d_lat, d_lon)
                if geom:
                    road_geometries[i] = geom
        except Exception as exc:
            logger.warning("OSRM route resolution failed: %s", exc)

        for i, (o_lat, o_lon, d_lat, d_lon, record) in enumerate(valid_routes):
            road_geom = road_geometries[i] if i < len(road_geometries) else None
            coordinates = (
                road_geom if road_geom and len(road_geom) >= 2
                else [[o_lon, o_lat], [d_lon, d_lat]]
            )
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
                "properties": _build_properties(record, coord_keys, entity_type),
            })
    elif point_col:
        # Neo4j Point object column
        for record in records:
            coords = _extract_point_coords(record.get(point_col))
            if coords is None:
                continue
            lat, lon = coords
            if not _valid_coords(lat, lon):
                skipped += 1
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": _build_properties(record, {point_col}, entity_type),
            })
    else:
        coord_keys = {lat_col, lon_col}
        for record in records:
            lat = _safe_float(record.get(lat_col))
            lon = _safe_float(record.get(lon_col))

            if lat is None or lon is None:
                continue

            if not _valid_coords(lat, lon):
                skipped += 1
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],  # GeoJSON: [lon, lat]
                },
                "properties": _build_properties(record, coord_keys, entity_type),
            })

    if skipped:
        logger.warning(
            "Skipped %d record(s) with out-of-bounds coordinates", skipped,
        )

    logger.info(
        "Extracted %d %s features from %d records",
        len(features),
        "LineString" if is_route else "Point",
        len(records),
    )

    return {"type": "FeatureCollection", "features": features}
