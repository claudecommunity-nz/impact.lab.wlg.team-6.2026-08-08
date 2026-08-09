"""Spatial hazard context for any point in Wellington.

Wraps wcc_gis spatial queries into a single hazard_context(lat, lng) call
returning tsunami zone, liquefaction risk, flood hazard, fault proximity,
deprivation decile, nearby earthquake-prone buildings, nearest community
emergency hub, and nearest live gauge reading.

Usage:
    from enrichment.hazard_context import hazard_context, hazard_summary

    ctx = hazard_context(-41.2865, 174.7762)
    print(ctx["tsunami_zone"])       # e.g. "Orange" or None
    print(ctx["liquefaction_risk"])   # e.g. "Moderate damage is possible"
    print(hazard_summary(-41.2865, 174.7762))
"""

from __future__ import annotations

import wcc_gis


# ---------------------------------------------------------------------------
# point-in-polygon lookups (wcc_gis at= queries)
# ---------------------------------------------------------------------------

def _first_attr(dataset: str, lat: float, lng: float, field: str) -> str | None:
    """Return the value of `field` from the first feature containing (lat, lng)."""
    try:
        rows = wcc_gis.features(dataset, at=(lat, lng), limit=1)
        return rows[0][field] if rows else None
    except wcc_gis.GisError:
        return None


def _tsunami_zone(lat: float, lng: float) -> str | None:
    """Tsunami evacuation zone at this point.

    Live layer fields (verified 2026-08-10): Col_Code is the zone colour
    ("red"/"orange"/"yellow"), Evac_Zone the human description. The
    pre-event guess of Zone_Class turned out to be a bare integer.
    """
    try:
        rows = wcc_gis.features("tsunami-evacuation-zones", at=(lat, lng), limit=1)
    except wcc_gis.GisError:
        return None
    if not rows:
        return None
    r = rows[0]
    colour, zone = r.get("Col_Code"), r.get("Evac_Zone")
    if colour and zone:
        return f"{colour} ({zone})"
    return colour or zone or (str(r["Zone_Class"]) if r.get("Zone_Class") is not None else None)


def _liquefaction_risk(lat: float, lng: float) -> str | None:
    """Liquefaction vulnerability at this point.

    The dataset id is liquefaction-regional with field "Liquefaction"
    (verified live 2026-08-10; the pre-event id didn't exist).
    """
    return (_first_attr("liquefaction-regional", lat, lng, "Liquefaction")
            or _first_attr("liquefaction-overlay", lat, lng, "Category"))


def _flood_hazard(lat: float, lng: float) -> str | None:
    """Flood/ponding hazard at this point.

    flood-hazard-areas is a whole ArcGIS service, not a queryable layer
    (verified 2026-08-10), so this asks the ponding-areas layer instead;
    presence of a mapped ponding polygon is the signal.
    """
    try:
        rows = wcc_gis.features("ponding-areas", at=(lat, lng), limit=1)
    except wcc_gis.GisError:
        return None
    if not rows:
        return None
    r = rows[0]
    for field in ("Hazard_Class", "Type", "Category", "Description"):
        if r.get(field):
            return str(r[field])
    return "mapped ponding area"


def _fault_zone(lat: float, lng: float, radius_m: int = 500) -> dict | None:
    """Nearest active fault within radius_m, if any."""
    try:
        rows = wcc_gis.features("active-faults", near=(lat, lng, radius_m), limit=1)
        if not rows:
            return None
        r = rows[0]
        return {
            # live layer publishes lowercase field names (verified 2026-08-10)
            "name": r.get("name") or r.get("Name") or r.get("FaultName"),
            "distance_m": radius_m,  # upper bound — actual may be closer
            "slip_rate": r.get("slip_rate") or r.get("Slip_Rate") or r.get("SlipRate"),
        }
    except wcc_gis.GisError:
        return None


def _deprivation_decile(lat: float, lng: float) -> int | None:
    """NZDep2023 deprivation decile (1 = least deprived, 10 = most)."""
    try:
        # NZDep2023 feature server — SA1-level polygons
        rows = wcc_gis.features("deprivation-2023", at=(lat, lng), limit=1)
        if not rows:
            return None
        # The field name varies; try common variants
        for field in ("NZDep2023", "Decile", "NZDep2023_Decile", "SA12023_V1"):
            val = rows[0].get(field)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
        return None
    except wcc_gis.GisError:
        return None


# ---------------------------------------------------------------------------
# radius queries (wcc_gis near= queries)
# ---------------------------------------------------------------------------

def _nearby_eq_prone_buildings(lat: float, lng: float, radius_m: int = 500) -> list[dict]:
    """Earthquake-prone buildings within radius_m."""
    try:
        rows = wcc_gis.features(
            "earthquake-prone-buildings",
            near=(lat, lng, radius_m),
            limit=10,
        )
        return [
            {
                "address": r.get("Address") or r.get("STREET_ADDRESS"),
                "rating": r.get("EQ_Rating") or r.get("Building_Status"),
                "lat": r.get("lat"),
                "lng": r.get("lng"),
            }
            for r in rows
        ]
    except wcc_gis.GisError:
        return []


def _nearest_emergency_hub(lat: float, lng: float, radius_m: int = 5000) -> dict | None:
    """Nearest community emergency hub within radius_m."""
    try:
        rows = wcc_gis.features(
            "community-emergency-hubs",
            near=(lat, lng, radius_m),
            limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        # live layer publishes uppercase field names (verified 2026-08-10)
        address = ", ".join(p for p in (r.get("ADDRESS") or r.get("Address"),
                                        r.get("SUBURB"), r.get("TOWN")) if p)
        return {
            "name": r.get("NAME") or r.get("Name") or r.get("HubName") or r.get("FACILITY"),
            "address": address or r.get("LOCATION"),
            "lat": r.get("lat"),
            "lng": r.get("lng"),
        }
    except wcc_gis.GisError:
        return None


# ---------------------------------------------------------------------------
# live telemetry — nearest gauge reading
# ---------------------------------------------------------------------------

def _nearest_gauge_reading(lat: float, lng: float) -> dict | None:
    """Nearest Hilltop gauge with its most recent reading.

    Scans cached gauge locations for the closest by naive Euclidean distance
    (adequate within Wellington's extent). Returns the latest Stage reading.
    """
    try:
        sites = wcc_gis.hilltop_sites()
    except wcc_gis.GisError:
        return None

    if not sites:
        return None

    best = None
    best_dist = float("inf")
    for s in sites:
        if s.get("lat") is None or s.get("lng") is None:
            continue
        d = (s["lat"] - lat) ** 2 + (s["lng"] - lng) ** 2
        if d < best_dist:
            best_dist = d
            best = s

    if best is None:
        return None

    result = {
        "site": best["site"],
        "lat": best["lat"],
        "lng": best["lng"],
    }

    # Try to get the latest reading — Stage first, then Flow
    for measurement in ("Stage", "Flow", "Rainfall"):
        try:
            readings = wcc_gis.hilltop_data(best["site"], measurement, interval="PT1H")
            if readings:
                r = readings[-1]
                result["measurement"] = measurement
                result["value"] = r["value"]
                result["units"] = r["units"]
                result["time"] = r["time"]
                break
        except wcc_gis.GisError:
            continue

    return result


# ---------------------------------------------------------------------------
# composite function
# ---------------------------------------------------------------------------

def hazard_context(lat: float, lng: float) -> dict:
    """Full hazard context for a point. Returns a dict with all available layers.

    Every value is None when the layer doesn't cover the point or the query
    fails — callers should handle missing data gracefully.
    """
    fault = _fault_zone(lat, lng)
    eq_buildings = _nearby_eq_prone_buildings(lat, lng)
    hub = _nearest_emergency_hub(lat, lng)
    gauge = _nearest_gauge_reading(lat, lng)

    return {
        "lat": lat,
        "lng": lng,
        "tsunami_zone": _tsunami_zone(lat, lng),
        "liquefaction_risk": _liquefaction_risk(lat, lng),
        "flood_hazard": _flood_hazard(lat, lng),
        "fault_zone": fault,
        "deprivation_decile": _deprivation_decile(lat, lng),
        "eq_prone_buildings_nearby": eq_buildings,
        "eq_prone_building_count": len(eq_buildings),
        "nearest_emergency_hub": hub,
        "nearest_gauge": gauge,
    }


def hazard_summary(lat: float, lng: float) -> str:
    """One-line human-readable hazard summary for a location."""
    ctx = hazard_context(lat, lng)
    parts = []

    if ctx["tsunami_zone"]:
        parts.append(f"tsunami:{ctx['tsunami_zone']}")
    if ctx["liquefaction_risk"]:
        parts.append(f"liquefaction:{ctx['liquefaction_risk']}")
    if ctx["flood_hazard"]:
        parts.append(f"flood:{ctx['flood_hazard']}")
    if ctx["fault_zone"]:
        parts.append(f"fault:<{ctx['fault_zone']['distance_m']}m")
    if ctx["deprivation_decile"]:
        parts.append(f"deprivation:D{ctx['deprivation_decile']}")
    if ctx["eq_prone_building_count"]:
        parts.append(f"EQP-buildings:{ctx['eq_prone_building_count']}")
    if ctx["nearest_emergency_hub"]:
        parts.append(f"hub:{ctx['nearest_emergency_hub']['name']}")
    if ctx["nearest_gauge"] and ctx["nearest_gauge"].get("value") is not None:
        g = ctx["nearest_gauge"]
        parts.append(f"gauge:{g['site']}={g['value']}{g.get('units','')}")

    return " | ".join(parts) if parts else "no hazard data at this location"
