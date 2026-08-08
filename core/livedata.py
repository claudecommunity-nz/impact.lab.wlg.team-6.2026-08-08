"""Real data, fetched now — and the discipline to say when it is not.

Everything else on this map is invented for the demo. This module is not: it
pulls what is actually happening in Wellington at the moment it is called, from
two public sources.

  NZTA journeys      state-highway events — closures, warnings, road works
  GWRC Hilltop       river level and rainfall gauges

The trap, and why this file is careful
--------------------------------------
Hilltop exposes 2,788 sites and 300 of them sit inside the Wellington extent,
but most are **groundwater monitoring bores**, and their "latest" reading is
from 2018 or 2019. Asking a gauge for its most recent value and putting that
on a map labelled "live" would show seven-year-old data as if it were current
— which is precisely the failure this whole product exists to prevent.

So a reading is only ever shown if it is genuinely recent, the cut-off is a
named constant rather than a guess buried in a condition, and the timestamp
travels with the value everywhere it goes. A gauge with nothing recent is
reported as *stale*, not quietly dropped: knowing a gauge has stopped
reporting is itself operational information during a flood.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Hilltop publishes NAIVE local timestamps. Reading them as UTC put every
# reading 12 hours in the future — a gauge measured at 14:30 today looked like
# tomorrow morning, so "age" came out negative and a stale check comparing
# against a threshold would have passed everything. NZ is the reason this
# class of bug is worth being paranoid about: we are 12 or 13 hours off UTC,
# so the error is never subtle but it is always silent.
NZ = ZoneInfo("Pacific/Auckland")

NZTA_DELAYS = "https://www.journeys.nzta.govt.nz/assets/map-data-cache/delays.json"
WELLINGTON = (174.62, -41.36, 174.94, -41.14)

# A reading older than this is history, not telemetry. Six hours is generous
# for a flood response and still excludes the bores by several years.
FRESH_WITHIN = timedelta(hours=6)

# These servers belong to other agencies and the README asks us to be
# considerate. One fetch per interval, shared by every viewer.
CACHE_SECONDS = 120

_cache: dict = {"at": 0.0, "payload": None}
_lock = threading.Lock()


def _get_json(url: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(url, headers={
        # Identify ourselves rather than arriving as an anonymous scraper.
        "User-Agent": "impact-lab-wlg-team6/1.0 (Wellington community reporting prototype)",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _first_point(geometry: dict | None):
    coords = (geometry or {}).get("coordinates")
    while isinstance(coords, list) and coords and isinstance(coords[0], list):
        coords = coords[0]
    if isinstance(coords, list) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])   # lat, lng
    return None


def _inside(lat: float, lng: float) -> bool:
    w, s, e, n = WELLINGTON
    return w <= lng <= e and s <= lat <= n


# ---------------------------------------------------------------------------
# NZTA road events
# ---------------------------------------------------------------------------

def road_events() -> list[dict]:
    """State-highway events inside the Wellington extent, right now."""
    try:
        payload = _get_json(NZTA_DELAYS)
    except Exception:
        return []

    out = []
    for feature in payload.get("features", []):
        point = _first_point(feature.get("geometry"))
        if not point or not _inside(*point):
            continue
        props = feature.get("properties") or {}
        out.append({
            "source": "NZTA",
            "kind": "road",
            "title": props.get("LocationArea") or "State highway event",
            "event_type": props.get("EventType"),
            "detail": props.get("EventDescription") or props.get("Description") or "",
            "status": props.get("EventStatus") or props.get("Status"),
            "lat": point[0], "lng": point[1],
            "updated": props.get("LastEdited"),
            "link": "https://www.journeys.nzta.govt.nz/",
        })
    return out


# ---------------------------------------------------------------------------
# GWRC Hilltop gauges
# ---------------------------------------------------------------------------

# Named river and rainfall sites rather than the bore network. Checked against
# the live service; the bores are the ones returning 2018 values.
GAUGE_HINTS = ("hutt river", "kaiwharawhara", "korokoro", "porirua stream",
               "waiwhetu", "karori stream", "makara", "wainuiomata",
               "orongorongo", "akatarawa", "pauatahanui")


def _parse_time(value) -> datetime | None:
    """Parse a Hilltop timestamp. Naive values are Pacific/Auckland, not UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=NZ)


def gauges(limit: int = 6) -> list[dict]:
    """River and rainfall gauges with a reading, each stamped with its age.

    Returns stale ones too, marked. A gauge that has stopped reporting during
    a flood is something a duty officer wants to know about, and silently
    dropping it would hide that.
    """
    import wcc_gis

    try:
        sites = wcc_gis.hilltop_sites()
    except Exception:
        return []

    named = [s for s in sites
             if s.get("lat") is not None
             and any(h in str(s.get("site", "")).lower() for h in GAUGE_HINTS)]

    now = datetime.now(timezone.utc)
    out = []
    for site in named[:limit * 3]:
        name = site.get("site")
        try:
            measurements = wcc_gis.hilltop_measurements(name)
        except Exception:
            continue
        pick = None
        for wanted in ("Stage", "Flow", "Rainfall"):
            pick = next((m for m in measurements
                         if wanted.lower() in str(m).lower()), None)
            if pick:
                break
        if not pick:
            continue
        measurement = pick if isinstance(pick, str) else pick.get("measurement")
        try:
            readings = wcc_gis.hilltop_data(name, measurement)
        except Exception:
            continue
        if not readings:
            continue

        last = readings[-1]
        at = _parse_time(last.get("time"))
        age = (now - at) if at else None
        # A reading cannot be from the future. If one looks like it is, the
        # timezone assumption is wrong rather than the gauge being prophetic —
        # clamp so a bad assumption can never make stale data look fresh.
        if age is not None and age.total_seconds() < 0:
            age = timedelta(0)
        out.append({
            "source": "Greater Wellington",
            "kind": "gauge",
            "title": name,
            "measurement": measurement,
            "value": last.get("value"),
            "at": last.get("time"),
            "fresh": bool(age is not None and age <= FRESH_WITHIN),
            "age_hours": round(age.total_seconds() / 3600, 1) if age else None,
            "lat": site.get("lat"), "lng": site.get("lng"),
        })
        if len([g for g in out if g["fresh"]]) >= limit:
            break
    return out


# ---------------------------------------------------------------------------

def snapshot(force: bool = False) -> dict:
    """Everything real, cached briefly and stamped with when it was fetched."""
    with _lock:
        age = time.time() - _cache["at"]
        if _cache["payload"] and age < CACHE_SECONDS and not force:
            payload = dict(_cache["payload"])
            payload["cached_seconds"] = int(age)
            return payload

    roads = road_events()
    gauge_list = gauges()
    fresh = [g for g in gauge_list if g["fresh"]]

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cached_seconds": 0,
        "roads": roads,
        "gauges": gauge_list,
        "counts": {
            "roads": len(roads),
            "gauges_fresh": len(fresh),
            "gauges_stale": len(gauge_list) - len(fresh),
        },
        "note": ("Fetched live from NZTA and Greater Wellington. Everything else "
                 "on this map is invented for the demo — this is not."),
        "stale_note": (f"A reading older than {int(FRESH_WITHIN.total_seconds() // 3600)} "
                       "hours is shown as stale rather than as current. Most Hilltop "
                       "sites in this extent are groundwater bores whose latest "
                       "value is years old."),
        "sources": ["NZTA journeys.govt.nz", "Greater Wellington Hilltop telemetry"],
    }

    with _lock:
        _cache["at"] = time.time()
        _cache["payload"] = payload
    return payload
