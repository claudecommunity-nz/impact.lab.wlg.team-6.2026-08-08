#!/usr/bin/env python3
"""Bake the map backdrop into web/data/basemap.json.

    python3 tools/fetch_basemap.py

Pulls two real WCC layers via wcc_gis and writes a trimmed GeoJSON the
browser can draw with no external map library and no network:

  - tsunami-evacuation-zones   the coloured zones people are told to leave
  - community-emergency-hubs   where communities gather and report from

Why bake rather than fetch live
-------------------------------
Three reasons, in order of how much they would hurt during a four-minute
demo. The venue wifi might not hold. Council servers throttle under
concurrent load and the README asks us to be considerate. And a raw pull of
the tsunami zones is 2.7 MB, which is a slow first paint on a phone.

Trimming: coordinates to 4 decimal places (~11 m, far finer than a city map
needs) and only the handful of properties the UI actually renders. That
turns 2.7 MB into something a phone loads instantly.

Re-run it whenever you want fresher geometry. The output is committed, so a
fresh clone works offline.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wcc_gis  # noqa: E402

OUT = ROOT / "web" / "data" / "basemap.json"
PRECISION = 4


def round_coords(node):
    """Walk a GeoJSON coordinate tree, rounding every number."""
    if isinstance(node, (int, float)):
        return round(float(node), PRECISION)
    if isinstance(node, list):
        return [round_coords(item) for item in node]
    return node


# ~11 m at Wellington's latitude. Finer than a city-scale map can show, and
# still removes most of the vertices.
#
# 0.0003 (~33 m) was tried first and made the file smaller, but six of the
# nineteen tsunami zones collapsed below a valid ring and vanished from the
# map entirely. A backdrop that silently loses a third of the evacuation
# zones is worse than a backdrop that is 40 KB larger, so this is deliberately
# conservative. The script prints a warning if any feature is still dropped.
TOLERANCE = 0.0001


def _simplify_ring(points: list, tolerance: float) -> list:
    """Douglas-Peucker. Iterative rather than recursive: a coastline ring can
    be thousands of points deep and Python's recursion limit is 1000.
    """
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue

        ax, ay = points[start][0], points[start][1]
        bx, by = points[end][0], points[end][1]
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy

        worst, worst_i = -1.0, start
        for i in range(start + 1, end):
            px, py = points[i][0], points[i][1]
            if span == 0:
                dist = (px - ax) ** 2 + (py - ay) ** 2
            else:
                # Perpendicular distance, squared, without the sqrt.
                cross = abs(dy * px - dx * py + bx * ay - by * ax)
                dist = (cross * cross) / span
            if dist > worst:
                worst, worst_i = dist, i

        if worst > tolerance * tolerance:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))

    return [p for p, k in zip(points, keep) if k]


def simplify_geometry(geom_type: str, coords, tolerance: float = TOLERANCE):
    """Simplify Polygon / MultiPolygon rings, dropping any that collapse.

    A ring needs four positions to be a valid closed polygon. Anything that
    simplifies below that was too small to see anyway.
    """
    if geom_type == "Polygon":
        rings = [_simplify_ring(r, tolerance) for r in coords]
        return [r for r in rings if len(r) >= 4]
    if geom_type == "MultiPolygon":
        polys = [simplify_geometry("Polygon", p, tolerance) for p in coords]
        return [p for p in polys if p]
    return coords


def zone_layer() -> list[dict]:
    print("  tsunami-evacuation-zones ...", end=" ", flush=True)
    started = time.time()
    collection = wcc_gis.geojson("tsunami-evacuation-zones", bbox=wcc_gis.WELLINGTON)
    features = []
    dropped = 0
    for feature in collection.get("features", []):
        props = feature.get("properties") or {}
        geom_type = feature["geometry"]["type"]
        coords = simplify_geometry(geom_type, feature["geometry"]["coordinates"])
        if not coords:
            dropped += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": geom_type,
                "coordinates": round_coords(coords),
            },
            "properties": {
                "layer": "tsunami-zone",
                # Col_Code is the colour WCC publishes the zone as; Evac_Zone
                # is the instruction that goes with it.
                "colour": (props.get("Col_Code") or "").lower(),
                "zone": props.get("Evac_Zone"),
                "location": props.get("Location"),
            },
        })
    print(f"{len(features)} zones in {time.time() - started:.1f}s")
    if dropped:
        print(f"     ⚠  {dropped} zone(s) collapsed at TOLERANCE={TOLERANCE} "
              f"and are NOT on the map. Lower the tolerance.")
    return features


def hub_layer() -> list[dict]:
    print("  community-emergency-hubs ...", end=" ", flush=True)
    started = time.time()
    collection = wcc_gis.geojson("community-emergency-hubs", bbox=wcc_gis.WELLINGTON)
    features = []
    for feature in collection.get("features", []):
        props = feature.get("properties") or {}
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": round_coords(feature["geometry"]["coordinates"]),
            },
            "properties": {
                "layer": "hub",
                # Upper case: the live layer publishes NAME/ADDRESS/SUBURB.
                # Guessing at "Name" returns None for all 60 of them.
                "name": props.get("NAME"),
                "address": props.get("ADDRESS"),
                "suburb": props.get("SUBURB"),
            },
        })
    print(f"{len(features)} hubs in {time.time() - started:.1f}s")
    return features


# OpenStreetMap, via Overpass. Baked like everything else rather than fetched
# at runtime: a tile server is the same single point of failure as a CDN font,
# and this has to work on a dead network.
#
# Weighted by class so the map reads as a map — motorways heavy, residential
# hairline. Without that hierarchy 6,500 streets is a grey smear.
OVERPASS = "https://overpass-api.de/api/interpreter"
ROAD_CLASSES = {
    "motorway": 3, "trunk": 3, "primary": 2,
    "secondary": 2, "tertiary": 1, "residential": 0, "unclassified": 0,
}
# Coarser simplification for the streets you would never trace by eye, finer
# for the ones people navigate by.
ROAD_TOLERANCE = {3: 0.00004, 2: 0.00006, 1: 0.00010, 0: 0.00016}


def _simplify_line(points, tolerance):
    """Douglas-Peucker on an open line. Iterative — a long road can be deep."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        worst, worst_i = -1.0, start
        for i in range(start + 1, end):
            px, py = points[i]
            if span == 0:
                dist = (px - ax) ** 2 + (py - ay) ** 2
            else:
                cross = abs(dy * px - dx * py + bx * ay - by * ax)
                dist = (cross * cross) / span
            if dist > worst:
                worst, worst_i = dist, i
        if worst > tolerance * tolerance:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [pt for pt, k in zip(points, keep) if k]


def streets() -> list[dict]:
    """Wellington's street network from OpenStreetMap, simplified and weighted."""
    import urllib.parse, urllib.request

    print("  openstreetmap streets ...", end=" ", flush=True)
    started = time.time()
    w, s, e, n = wcc_gis.WELLINGTON
    classes = "|".join(ROAD_CLASSES)
    query = (f'[out:json][timeout:90];(way["highway"~"^({classes})$"]'
             f'({s},{w},{n},{e}););out geom;')
    try:
        raw = urllib.request.urlopen(urllib.request.Request(
            OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
            headers={"User-Agent": "impact-lab-team6/1.0 (Wellington emergency prototype)"}),
            timeout=150).read()
        payload = json.loads(raw)
    except Exception as exc:
        print(f"unavailable ({type(exc).__name__}) — map falls back to hazard layers only")
        return []

    out, kept_points, raw_points = [], 0, 0
    for way in payload.get("elements", []):
        geom = way.get("geometry") or []
        if len(geom) < 2:
            continue
        weight = ROAD_CLASSES.get((way.get("tags") or {}).get("highway"), 0)
        line = [(pt["lon"], pt["lat"]) for pt in geom]
        raw_points += len(line)
        line = _simplify_line(line, ROAD_TOLERANCE[weight])
        kept_points += len(line)
        out.append({"w": weight,
                    "p": [[round(x, 5), round(y, 5)] for x, y in line]})

    print(f"{len(out)} streets, {kept_points} of {raw_points} points kept "
          f"in {time.time() - started:.1f}s")
    return out


# The coastline, so the harbour reads as water.
#
# This is the single biggest legibility win on the map, and the fiddliest to
# produce. OpenStreetMap does not store the sea as a polygon: it stores
# `natural=coastline` as a *directed line*, by convention with land on the
# left. So the sea cannot simply be filled. The ways have to be joined head to
# tail, clipped to the map extent, and closed along the extent boundary.
#
# Which way to walk that boundary is decided by TEST, not by argument. Whether
# SVG's flipped y-axis inverts "clockwise" is exactly the kind of reasoning
# that is wrong half the time and looks fine until someone notices the harbour
# is a hill. So: build it both ways, then ask whether Civic Square is on land
# and the middle of the harbour is not.
LAND_ORACLES = [
    ((174.7762, -41.2865), True, "Civic Square"),
    ((174.7400, -41.2830), True, "Karori"),
    ((174.8180, -41.3160), True, "Miramar peninsula"),
    ((174.8660, -41.2570), True, "Matiu / Somes Island"),
    ((174.8800, -41.2250), True, "Petone foreshore"),
    ((174.7680, -41.3200), True, "Island Bay"),
    ((174.9000, -41.2100), True, "Lower Hutt"),
    ((174.9200, -41.2600), True, "eastern harbour hills"),
    ((174.6500, -41.2000), False, "Tasman Sea, west"),
    ((174.8300, -41.2750), False, "middle of the harbour"),
    ((174.7500, -41.3550), False, "Cook Strait, south"),
    ((174.8450, -41.3000), False, "outer harbour"),
    ((174.7950, -41.3420), False, "Lyall Bay"),
]
COAST_TOLERANCE = 0.00006


def _join_chains(ways: list[list[tuple]]) -> list[list[tuple]]:
    """Join coastline ways head to tail.

    Start only from ways that nothing else feeds into. Starting anywhere
    consumes a chain from its middle, and it then stops short at the join —
    which produced eight broken fragments instead of three clean ones.
    """
    heads: dict = {}
    for i, pts in enumerate(ways):
        heads.setdefault(pts[0], []).append(i)
    tails = {pts[-1] for pts in ways}

    out, consumed = [], set()

    def grow(i: int) -> list[tuple]:
        chain = list(ways[i])
        consumed.add(i)
        while True:
            following = [j for j in heads.get(chain[-1], []) if j not in consumed]
            if not following:
                return chain
            j = following[0]
            consumed.add(j)
            chain.extend(ways[j][1:])
            if chain[-1] == chain[0]:
                return chain

    for i, pts in enumerate(ways):
        if i not in consumed and pts[0] not in tails:
            out.append(grow(i))
    for i in range(len(ways)):          # whatever is left is a closed ring
        if i not in consumed:
            out.append(grow(i))
    return out


def _clip_segment(a, b, bbox):
    """Liang-Barsky. Returns the visible span of a-b, or None."""
    w, s, e, n = bbox
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - w), (dx, e - x0), (-dy, y0 - s), (dy, n - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1: return None
            if r > t0: t0 = r
        elif r < t0: return None
        elif r < t1: t1 = r
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


def _clip_chain(chain, bbox):
    """Clip a polyline to the extent, splitting where it leaves and returns."""
    runs, current = [], []
    for i in range(len(chain) - 1):
        span = _clip_segment(chain[i], chain[i + 1], bbox)
        if span is None:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        a, b = span
        if not current:
            current = [a, b]
        elif abs(current[-1][0] - a[0]) < 1e-9 and abs(current[-1][1] - a[1]) < 1e-9:
            current.append(b)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = [a, b]
    if len(current) >= 2:
        runs.append(current)
    return runs


def _perimeter_t(pt, bbox, eps=1e-7):
    """Where a point sits on the extent boundary: 0-4 from the NW corner."""
    w, s, e, n = bbox
    x, y = pt
    if abs(y - n) < eps: return 0 + (x - w) / (e - w)
    if abs(x - e) < eps: return 1 + (n - y) / (n - s)
    if abs(y - s) < eps: return 2 + (e - x) / (e - w)
    if abs(x - w) < eps: return 3 + (y - s) / (n - s)
    return None


def _perimeter_pt(t, bbox):
    w, s, e, n = bbox
    t %= 4
    if t < 1: return (w + t * (e - w), n)
    if t < 2: return (e, n - (t - 1) * (n - s))
    if t < 3: return (e - (t - 2) * (e - w), s)
    return (w, s + (t - 3) * (n - s))


def _close_along_boundary(runs, bbox, forward: bool):
    """Turn clipped coastline runs into closed land polygons."""
    def is_ring(r):
        return abs(r[0][0] - r[-1][0]) < 1e-9 and abs(r[0][1] - r[-1][1]) < 1e-9

    polygons = [r for r in runs if is_ring(r)]           # islands, already closed
    edges = []
    for run in runs:
        if is_ring(run):
            continue
        start, end = _perimeter_t(run[0], bbox), _perimeter_t(run[-1], bbox)
        if start is not None and end is not None:
            edges.append({"pts": run, "start": start, "end": end})

    unused = set(range(len(edges)))
    while unused:
        first = min(unused)
        polygon, cursor = [], first
        while True:
            unused.discard(cursor)
            polygon.extend(edges[cursor]["pts"])
            here = edges[cursor]["end"]
            # the next coastline run reached soonest along the boundary
            best, best_gap = None, None
            for j, edge in enumerate(edges):
                gap = (edge["start"] - here) % 4 if forward else (here - edge["start"]) % 4
                if gap < 1e-9:
                    gap += 4
                if best_gap is None or gap < best_gap:
                    best, best_gap = j, gap
            if best is None:
                break
            # Insert the extent corners crossed on the way, at the INTEGER
            # values of t between here and the next run — not at here+1,
            # here+2, which is a different set of points entirely and closes
            # the polygon with a diagonal shortcut straight across the map.
            # That version passed all ten land/sea checks while drawing the
            # Hutt Valley as open water, because no check sat near the seam.
            if forward:
                t = math.floor(here) + 1
                while t < here + best_gap - 1e-9:
                    polygon.append(_perimeter_pt(t, bbox))
                    t += 1
            else:
                t = math.ceil(here) - 1
                while t > here - best_gap + 1e-9:
                    polygon.append(_perimeter_pt(t, bbox))
                    t -= 1
            if best == first or best not in unused:
                break
            cursor = best
        if len(polygon) >= 4:
            polygons.append(polygon)
    return polygons


def _contains(pt, polygons) -> bool:
    """Ray casting across every polygon at once."""
    x, y = pt
    crossings = 0
    for polygon in polygons:
        for i in range(len(polygon)):
            x0, y0 = polygon[i]
            x1, y1 = polygon[(i + 1) % len(polygon)]
            if (y0 > y) != (y1 > y) and x0 + (y - y0) / (y1 - y0) * (x1 - x0) > x:
                crossings += 1
    return crossings % 2 == 1


def coastline() -> list[list[list[float]]]:
    """Land polygons for the map extent, so everything else can be sea."""
    import urllib.parse, urllib.request

    print("  openstreetmap coastline ...", end=" ", flush=True)
    started = time.time()
    bbox = wcc_gis.WELLINGTON
    w, s, e, n = bbox
    query = (f'[out:json][timeout:120];(way["natural"="coastline"]'
             f'({s},{w},{n},{e}););out geom;')
    try:
        raw = urllib.request.urlopen(urllib.request.Request(
            OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
            headers={"User-Agent": "impact-lab-team6/1.0 (Wellington emergency prototype)"}),
            timeout=180).read()
        payload = json.loads(raw)
    except Exception as exc:
        print(f"unavailable ({type(exc).__name__}) — map falls back to a flat backdrop")
        return []

    ways = []
    for way in payload.get("elements", []):
        pts = [(round(p["lon"], 6), round(p["lat"], 6)) for p in way.get("geometry") or []]
        if len(pts) >= 2:
            ways.append(pts)

    runs = []
    for chain in _join_chains(ways):
        runs.extend(_clip_chain(chain, bbox))

    for forward in (True, False):
        polygons = _close_along_boundary(runs, bbox, forward)
        if all(_contains(pt, polygons) == want for pt, want, _ in LAND_ORACLES):
            break
    else:
        # Neither direction puts the city on land. Drawing it anyway would put
        # the harbour where the hills are, which is worse than no water at all.
        wrong = [name for pt, want, name in LAND_ORACLES
                 if _contains(pt, polygons) != want]
        print(f"failed the land/sea check ({', '.join(wrong)}) — skipping water")
        return []

    raw_points = sum(len(p) for p in polygons)
    simplified = [_simplify_line(p, COAST_TOLERANCE) for p in polygons]
    simplified = [p for p in simplified if len(p) >= 4]
    if not all(_contains(pt, simplified) == want for pt, want, _ in LAND_ORACLES):
        print("simplification broke the land/sea check — keeping full detail")
        simplified = polygons

    kept = sum(len(p) for p in simplified)
    print(f"{len(simplified)} land polygons, {kept} of {raw_points} points kept, "
          f"all {len(LAND_ORACLES)} land/sea checks pass, in {time.time() - started:.1f}s")
    return [[[round(x, 5), round(y, 5)] for x, y in p] for p in simplified]


def gazetteer() -> list[dict]:
    """Street and suburb names with a point, for offline address lookup.

    Why bother when a geocoding API exists: typing your address into a service
    to find out what is happening on your street means telling that service
    where you live. Baking the index means the lookup happens in the browser,
    the address never leaves the device, and it still works with no
    connectivity.

    Deduped to one point per (street, suburb) — 5,000 road segments collapse to
    a few thousand names, which is small enough to ship.
    """
    print("  roads (gazetteer) ...", end=" ", flush=True)
    started = time.time()
    seen: dict[tuple, dict] = {}
    for feature in wcc_gis.all_features("roads", bbox=wcc_gis.WELLINGTON,
                                        max_features=6000):
        name = (feature.get("ramm_alias") or "").strip()
        suburb = (feature.get("suburb") or "").strip()
        lat, lng = feature.get("lat"), feature.get("lng")
        if not name or lat is None or lng is None:
            continue
        key = (name.lower(), suburb.lower())
        if key in seen:
            continue
        seen[key] = {"n": name, "s": suburb,
                     "y": round(float(lat), 4), "x": round(float(lng), 4)}

    # Suburb centroids too, so "Karori" alone resolves.
    by_suburb: dict[str, list] = {}
    for entry in seen.values():
        if entry["s"]:
            by_suburb.setdefault(entry["s"], []).append(entry)
    for suburb, entries in by_suburb.items():
        key = (suburb.lower(), "")
        if key not in seen:
            seen[key] = {
                "n": suburb, "s": "",
                "y": round(sum(e["y"] for e in entries) / len(entries), 4),
                "x": round(sum(e["x"] for e in entries) / len(entries), 4),
            }

    places = sorted(seen.values(), key=lambda e: e["n"])
    print(f"{len(places)} places in {time.time() - started:.1f}s")
    return places


def labels() -> list[dict]:
    """Suburb and town names, for drawing on the map.

    A street network with no names on it makes people hunt for their own area
    by shape, which nobody can do under stress. Ranked so the renderer can
    thin them out as the map shrinks rather than overprinting itself.
    """
    import urllib.parse, urllib.request

    print("  openstreetmap place names ...", end=" ", flush=True)
    started = time.time()
    w, s, e, n = wcc_gis.WELLINGTON
    rank = {"city": 0, "town": 1, "suburb": 2, "village": 2}
    query = (f'[out:json][timeout:60];(node["place"~"^(city|town|suburb|village)$"]'
             f'({s},{w},{n},{e}););out;')
    try:
        raw = urllib.request.urlopen(urllib.request.Request(
            OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
            headers={"User-Agent": "impact-lab-team6/1.0 (Wellington emergency prototype)"}),
            timeout=120).read()
        payload = json.loads(raw)
    except Exception as exc:
        print(f"unavailable ({type(exc).__name__}) — map draws without names")
        return []

    out = []
    for node in payload.get("elements", []):
        tags = node.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        out.append({"n": name, "r": rank.get(tags.get("place"), 2),
                    "y": round(node["lat"], 4), "x": round(node["lon"], 4)})
    out.sort(key=lambda p: (p["r"], p["n"]))
    print(f"{len(out)} names in {time.time() - started:.1f}s")
    return out


def main() -> int:
    print("\nFetching WCC layers (live, from council servers):")
    features = zone_layer() + hub_layer()

    places = gazetteer()
    roads = streets()
    time.sleep(5)                      # Overpass rate-limits back to back calls
    land = coastline()
    time.sleep(45)
    names = labels()

    payload = {
        "type": "FeatureCollection",
        "places": places,
        "streets": roads,
        "land": land,
        "labels": names,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "attribution": (
            "Tsunami evacuation zones and Community Emergency Hubs: "
            "Wellington City Council / Greater Wellington Regional Council. "
            "Hazard-planning layers, not live emergency information. "
            "Coastline, streets and place names: OpenStreetMap contributors, "
            "ODbL."
        ),
        "features": features,
    }

    # Never let a failed fetch delete a layer that is already baked.
    #
    # Overpass rate-limits three heavy queries in a row, each fetch returns []
    # on failure, and the first run of this merge-less version quietly replaced
    # 6,527 streets and the whole coastline with nothing. The file still looked
    # valid; the map just lost its water. A partial refresh must degrade to
    # "keep what we had", never to "publish less".
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        for layer in ("places", "streets", "land", "labels", "features"):
            if not payload.get(layer) and existing.get(layer):
                payload[layer] = existing[layer]
                print(f"     ⚠  {layer}: fetch failed, kept the {len(existing[layer])} "
                      f"already baked. Re-run to refresh them.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"\n  wrote {OUT.relative_to(ROOT)}  ({size_kb:.0f} KB, {len(features)} features)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
