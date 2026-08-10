"""Real-time agency feeds, proxied once and cached.

Every feed returns the same envelope so the UI can render trust uniformly:

    {
        "id": "gauges",
        "name": "River & rain gauges",
        "attribution": "...",           # the publisher, always shown
        "fetched_at": "...Z",           # when WE last got fresh data
        "from_cache": bool,              # served stale after an upstream error
        "items": [...] | "geojson": {...},
        "error": "..."                  # present only when upstream failed
    }

Proxying server-side keeps each upstream seeing exactly one polite client
regardless of how many browsers are open (the prep-kit README notes at
least one council host throttles under concurrent load), and lets the
dashboard keep working through upstream flakiness by serving the last
good payload marked from_cache.

Readings carry their own freshness verdict: probing found gauges that
answer happily with data from 2013 (Wallaceville) and 2020 (Melling), so
an HTTP 200 is never treated as "current".
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET  # nosec B405 - all parses go through _safe_xml, which refuses DTDs
from datetime import datetime, timezone

import wcc_gis

_UA = "Kitea/0.1 (community-council two-way channel prototype)"
_TIMEOUT = 20

# Greater Wellington region, generous enough to include the Remutakas
# and Kāpiti approaches that carry Wellington's supply lines.
BBOX = (174.5, -41.7, 175.7, -40.6)  # w, s, e, n

WELLINGTON = (-41.2865, 174.7762)

# Curated live telemetry, verified answering with current readings on
# 2026-08-10. Coordinates resolved at runtime from hilltop_sites() so a
# renamed site degrades gracefully instead of pinning the wrong spot.
GAUGES = (
    ("Hutt River at Taita Gorge", "Flow", "river"),
    ("Hutt River at Birchville", "Flow", "river"),
    ("Waiwhetu Stream at Whites Line East", "Stage", "river"),
    ("Porirua Stream at Town Centre", "Stage", "river"),
    ("Wainuiomata River at Manuka Track", "Flow", "river"),
    ("Kaiwharawhara Stream at Karori Reservoir", "Rainfall", "rain"),
    ("Horokiri Stream at Battle Hill", "Rainfall", "rain"),
)

_FRESH_MAX_AGE_S = 6 * 3600  # a reading older than this is flagged stale

_WGTN_KEYWORDS = ("wellington", "wairarapa", "kapiti", "kāpiti", "hutt",
                  "porirua", "remutaka", "rimutaka", "tararua")

_SEVERITY_WORDS = (("red", "extreme"), ("orange", "severe"),
                   ("warning", "severe"), ("yellow", "moderate"),
                   ("watch", "moderate"))


# ---------------------------------------------------------------------------
# cache plumbing
# ---------------------------------------------------------------------------

_cache: dict[str, dict] = {}          # feed id -> last good envelope
_cache_expiry: dict[str, float] = {}  # feed id -> monotonic expiry
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(feed_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(feed_id, threading.Lock())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cached(feed_id: str, ttl: int, build) -> dict:
    """Serve from cache inside TTL; otherwise rebuild. On upstream failure,
    fall back to the last good payload marked from_cache rather than a hole
    in the dashboard.
    """
    with _lock_for(feed_id):
        if feed_id in _cache and time.monotonic() < _cache_expiry.get(feed_id, 0):
            return _cache[feed_id]
        try:
            envelope = build()
            envelope["fetched_at"] = _now_iso()
            envelope["from_cache"] = False
            _cache[feed_id] = envelope
            _cache_expiry[feed_id] = time.monotonic() + ttl
            return envelope
        except Exception as exc:  # upstream down; degrade visibly
            if feed_id in _cache:
                stale = dict(_cache[feed_id])
                stale["from_cache"] = True
                stale["error"] = f"upstream refresh failed: {exc}"
                _cache_expiry[feed_id] = time.monotonic() + 60
                return stale
            return {"id": feed_id, "error": str(exc), "items": [],
                    "fetched_at": _now_iso(), "from_cache": False}


def _check_scheme(url: str) -> str:
    # CAP item links arrive from a feed; never follow file:/ or exotic
    # schemes even if the upstream is compromised.
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"refusing non-http(s) url: {url[:60]}")
    return url


def _get_json(url: str) -> dict:
    req = urllib.request.Request(_check_scheme(url), headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310 - scheme checked above
        data = json.load(resp)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object from {url[:60]}")
    return data


def _get_text(url: str) -> str:
    req = urllib.request.Request(_check_scheme(url), headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310 - scheme checked above
        return resp.read().decode("utf-8", "replace")


def _in_bbox(lng: float | None, lat: float | None) -> bool:
    if lng is None or lat is None:
        return False
    w, s, e, n = BBOX
    return w <= lng <= e and s <= lat <= n


def _geometry_touches_bbox(geometry: dict | None) -> bool:
    """True when any coordinate of a GeoJSON geometry falls in BBOX."""
    if not geometry:
        return False

    def walk(node):
        if (isinstance(node, (list, tuple)) and len(node) >= 2
                and all(isinstance(v, (int, float)) for v in node[:2])):
            yield node[0], node[1]
        elif isinstance(node, (list, tuple)):
            for child in node:
                yield from walk(child)

    return any(_in_bbox(lng, lat)
               for lng, lat in walk(geometry.get("coordinates")))


def _reading_age_s(iso_time: str) -> float | None:
    """Age of a gauge reading, robust to the timestamp's timezone.

    Hilltop timestamps arrive naive. Observed live they align with UTC
    (reading 23:40, probed 23:53 UTC), but Hilltop deployments commonly
    publish NZ local time — so treat as UTC first, and when that puts the
    reading in the future, assume it was NZ local and shift 12 hours.
    """
    try:
        t = datetime.fromisoformat(iso_time)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - t).total_seconds()
    if age < -600:
        age += 12 * 3600
    return age


# ---------------------------------------------------------------------------
# the feeds
# ---------------------------------------------------------------------------


def gauges() -> dict:
    def build() -> dict:
        try:
            site_coords = {s["site"]: (s.get("lat"), s.get("lng"))
                           for s in wcc_gis.hilltop_sites()}
        except Exception:
            site_coords = {}
        items = []
        for site, measurement, kind in GAUGES:
            item: dict = {"site": site, "measurement": measurement, "kind": kind}
            lat, lng = site_coords.get(site, (None, None))
            item["lat"], item["lng"] = lat, lng
            try:
                series = wcc_gis.hilltop_data(site, measurement, interval="PT6H")
            except wcc_gis.GisError as exc:
                item["error"] = str(exc)[:120]
                items.append(item)
                continue
            if not series:
                item["error"] = "no readings returned"
                items.append(item)
                continue
            last = series[-1]
            item["value"] = last["value"]
            item["units"] = last["units"]
            item["time"] = last["time"]
            age = _reading_age_s(last["time"])
            item["fresh"] = age is not None and age < _FRESH_MAX_AGE_S
            if kind == "rain":
                # PT6H = last 6 records; for rainfall these are hourly buckets
                item["recent_total"] = round(
                    sum(r["value"] for r in series
                        if isinstance(r["value"], (int, float))), 1)
            else:
                first = series[0]
                if isinstance(last["value"], (int, float)) and \
                        isinstance(first["value"], (int, float)):
                    delta = last["value"] - first["value"]
                    eps = 10 if last["units"] == "mm" else max(0.02 * abs(first["value"]), 0.05)
                    item["trend"] = ("rising" if delta > eps
                                     else "falling" if delta < -eps else "steady")
                item["series"] = [
                    {"t": r["time"], "v": r["value"]} for r in series[-24:]
                ]
            items.append(item)
        return {"id": "gauges", "name": "River & rain gauges",
                "attribution": "Greater Wellington Regional Council (Hilltop telemetry)",
                "items": items}
    return _cached("gauges", ttl=120, build=build)


def delays() -> dict:
    def build() -> dict:
        data = _get_json("https://www.journeys.nzta.govt.nz/assets/map-data-cache/delays.json")
        feats = []
        for f in data.get("features", []):
            p = f.get("properties", {})
            # The regions property is bare numeric codes with no published
            # mapping (observed live: the Remutaka Hill event is [16]), so
            # filter by geometry against the Wellington bbox instead.
            if not _geometry_touches_bbox(f.get("geometry")):
                continue
            feats.append({
                "type": "Feature",
                "geometry": f.get("geometry"),
                "properties": {
                    "eventType": p.get("EventType"),
                    "description": p.get("EventDescription"),
                    "location": p.get("LocationArea"),
                    "impact": p.get("Impact"),
                    "status": p.get("Status"),
                    "planned": bool(p.get("IsPlanned")),
                    "updated": p.get("LastEdited"),
                },
            })
        return {"id": "delays", "name": "State highway delays & closures",
                "attribution": "NZ Transport Agency Waka Kotahi (Journeys)",
                "geojson": {"type": "FeatureCollection", "features": feats}}
    return _cached("delays", ttl=120, build=build)


def cameras() -> dict:
    def build() -> dict:
        data = _get_json("https://www.journeys.nzta.govt.nz/assets/map-data-cache/cameras.json")
        items = []
        for f in data.get("features", []):
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            lng, lat = (coords + [None, None])[:2]
            if not _in_bbox(lng, lat):
                continue
            p = f.get("properties", {})
            items.append({
                "name": p.get("Name"),
                "description": p.get("Description"),
                "image": p.get("ImageUrl"),
                "thumb": p.get("ThumbUrl"),
                "offline": bool(p.get("Offline")) or bool(p.get("UnderMaintenance")),
                "lat": lat, "lng": lng,
            })
        return {"id": "cameras", "name": "Traffic cameras",
                "attribution": "NZ Transport Agency Waka Kotahi (Journeys)",
                "items": items}
    return _cached("cameras", ttl=300, build=build)


def quakes() -> dict:
    def build() -> dict:
        data = _get_json("https://api.geonet.org.nz/quake?MMI=3")
        items = []
        now = datetime.now(timezone.utc)
        for f in data.get("features", []):
            p = f.get("properties", {})
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            lng, lat = (coords + [None, None])[:2]
            try:
                t = datetime.fromisoformat(p["time"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            age_h = (now - t).total_seconds() / 3600
            if age_h > 7 * 24:
                continue
            items.append({
                "publicID": p.get("publicID"),
                "time": p.get("time"),
                "magnitude": round(p.get("magnitude", 0), 1),
                "depth_km": round(p.get("depth", 0)),
                "locality": p.get("locality"),
                "mmi": p.get("mmi"),
                "lat": lat, "lng": lng,
                "link": f"https://www.geonet.org.nz/earthquake/{p.get('publicID')}",
            })
        return {"id": "quakes", "name": "Earthquakes (felt, last 7 days)",
                "attribution": "GeoNet (GNS Science / Toka Tū Ake EQC)",
                "items": items}
    return _cached("quakes", ttl=120, build=build)


def outages() -> dict:
    def build() -> dict:
        w, s, e, n = BBOX
        params = urllib.parse.urlencode({
            "where": "1=1",
            "geometry": f"{w},{s},{e},{n}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "startdate,enddate,locationname,numaffected,details,status",
            "outSR": "4326",
            "f": "geojson",
        })
        data = _get_json(
            "https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/"
            f"electricity_outages_read_only/FeatureServer/0/query?{params}")
        items = []
        for f in data.get("features", []):
            p = f.get("properties", {})
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            lng, lat = (coords + [None, None])[:2]
            items.append({
                "location": p.get("locationname"),
                "affected": p.get("numaffected"),
                "status": p.get("status"),
                "details": p.get("details"),
                "start": p.get("startdate"),
                "lat": lat, "lng": lng,
            })
        return {"id": "outages", "name": "Electricity outages",
                "attribution": "National Emergency Management Agency (NEMA)",
                "items": items}
    return _cached("outages", ttl=180, build=build)


_CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


def _safe_xml(text: str) -> ET.Element:
    """Entity-expansion attacks (billion laughs, XXE) all require a DTD;
    a legitimate RSS/CAP document never carries one. Refusing outright
    keeps stdlib ElementTree safe without a defusedxml dependency.
    """
    lowered = text[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("feed contained a DTD; refusing to parse")
    return ET.fromstring(text)  # nosec B314 - DTD refused above; ElementTree does not resolve external entities


def _cap_polygon_geojson(polygon_text: str) -> list | None:
    """CAP polygons are 'lat,lon lat,lon ...'; GeoJSON wants [lng, lat]."""
    ring = []
    for pair in polygon_text.split():
        try:
            lat_s, lng_s = pair.split(",")
            ring.append([float(lng_s), float(lat_s)])
        except ValueError:
            return None
    return [ring] if len(ring) >= 4 else None


def _touches_region(area_desc: str, rings: list | None) -> bool:
    blob = area_desc.lower()
    if any(k in blob for k in _WGTN_KEYWORDS):
        return True
    if rings:
        return any(_in_bbox(lng, lat) for lng, lat in rings[0])
    return False


def weather() -> dict:
    def build() -> dict:
        root = _safe_xml(_get_text("https://alerts.metservice.com/cap/rss"))
        items = []
        national = 0
        for it in root.iter("item"):
            national += 1
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            item: dict[str, object] = {"title": title, "link": link,
                    "published": (it.findtext("pubDate") or "").strip()}
            # Region and geometry live in the per-alert CAP XML, not the
            # RSS item (verified live: RSS titles carry no placenames).
            try:
                info = _safe_xml(_get_text(link)).find("cap:info", _CAP_NS)
                if info is None:
                    raise ValueError("CAP alert has no info block")
                area = info.find("cap:area", _CAP_NS)
                if area is None:
                    raise ValueError("CAP alert has no area block")
                area_desc = area.findtext("cap:areaDesc", "", _CAP_NS)
                rings = _cap_polygon_geojson(
                    area.findtext("cap:polygon", "", _CAP_NS))
                if not _touches_region(area_desc, rings):
                    continue
                item.update({
                    "event": info.findtext("cap:event", None, _CAP_NS),
                    "severity": (info.findtext("cap:severity", "", _CAP_NS) or "unknown").lower(),
                    "urgency": info.findtext("cap:urgency", None, _CAP_NS),
                    "onset": info.findtext("cap:onset", None, _CAP_NS),
                    "expires": info.findtext("cap:expires", None, _CAP_NS),
                    "area": area_desc,
                    "polygon": rings,
                })
            except Exception:
                # CAP detail unavailable: fall back to a keyword match on
                # the title alone, marked unlocated rather than dropped.
                if not any(k in title.lower() for k in _WGTN_KEYWORDS):
                    continue
                sev = "unknown"
                for word, s in _SEVERITY_WORDS:
                    if word in title.lower():
                        sev = s
                        break
                item.update({"severity": sev, "unlocated": True})
            items.append(item)
        return {"id": "weather", "name": "Weather watches & warnings",
                "attribution": "MetService Te Ratonga Tirorangi (CC BY 4.0)",
                "national_count": national,
                "items": items}
    return _cached("weather", ttl=300, build=build)


def hubs() -> dict:
    """Community Emergency Hubs — not real-time, but the layer every
    community-facing view should carry: where people go when systems fail.
    """
    def build() -> dict:
        rows = wcc_gis.features("community-emergency-hubs",
                                bbox=(BBOX[0], BBOX[1], BBOX[2], BBOX[3]),
                                limit=300)
        items = [{
            "name": r.get("NAME"),
            "address": ", ".join(p for p in (r.get("ADDRESS"), r.get("SUBURB"),
                                             r.get("TOWN")) if p),
            "lat": r.get("lat"), "lng": r.get("lng"),
        } for r in rows]
        return {"id": "hubs", "name": "Community Emergency Hubs",
                "attribution": "Wellington Region Emergency Management Office (WREMO)",
                "items": items}
    return _cached("hubs", ttl=3600, build=build)


FEEDS = {
    "gauges": gauges,
    "hubs": hubs,
    "delays": delays,
    "cameras": cameras,
    "quakes": quakes,
    "outages": outages,
    "weather": weather,
}


def get(feed_id: str) -> dict | None:
    fn = FEEDS.get(feed_id)
    return fn() if fn else None
