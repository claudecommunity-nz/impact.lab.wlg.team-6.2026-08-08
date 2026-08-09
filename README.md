# Impact Lab Wellington — Team 6

**Wellington City Council Emergency Management × Claude Code Community NZ**
Saturday 8 August 2026 · Waimanga Room, Wellington City Council

---

## Problem 02 — Create a two-way information channel between communities and WCC

> How might communities provide WCC with timely, structured information about local conditions, impacts and needs — before and during an emergency — and see that their information has been received?

The current flow is inconsistent and largely one-way. WCC sends information out, while reports from communities arrive through several unrelated channels and may not reach the people who can use them.

A prototype could allow residents, community groups or Community Emergency Hubs to report an issue using a simple form or message. Reports could include location, time, issue type, description and an image. WCC could group similar reports, acknowledge receipt and show whether an issue is being checked or acted on.

**Desired outcome:** WCC gains better local awareness, while communities have a clearer and more dependable route into Council.

*The common theme is improving the flow and use of information between communities and Council before and during an event.*

---

## What we built — Kitea

**Kitea** ("seen") is the answer to Problem 02 as a standalone, self-hostable
product: residents report local conditions in under a minute and watch the
council act on them live; the council gets one operating picture of every
report beside the real-time feeds it already watches. The commercial case,
inclusion stance and pilot path are in [COMMERCIAL.md](COMMERCIAL.md).

- **Resident page** (`/`): category chips, map pin or GPS, optional photo,
  no login. Returns a reference code (e.g. `WGN-A4UD`) and a tracking page
  that pushes `received → reviewing → responding → resolved` live over SSE.
  The moment a pin is dropped, the page shows what the council's own hazard
  maps say about that spot, and the nearest Community Emergency Hub.
- **Ops dashboard** (`/ops`, access-key gated): live map + triage queue,
  similar reports grouped into situations, one-tap status buttons that are
  simultaneously the public acknowledgment, per-report hazard context
  (tsunami zone, ponding, liquefaction, fault, NZDep decile, nearest live
  gauge), and a feed-health strip that shows the age of every data source.
- **Live agency feeds**, proxied and cached server-side: GWRC Hilltop river
  and rain telemetry, Waka Kotahi delays/closures and cameras, GeoNet felt
  quakes, NEMA electricity outages, MetService CAP warnings (with polygons
  on the map), and WREMO Community Emergency Hubs.

### Run it

```bash
python3 -m kitea
```

Zero dependencies beyond Python 3.10+. The ops access key comes from
`KITEA_OPS_KEY` (a random one is generated and printed if unset). Residents:
`http://127.0.0.1:8146/` — ops: `http://127.0.0.1:8146/ops`.

Seed a believable demo scenario against a running server:

```bash
KITEA_OPS_KEY=<key> python3 scripts/seed_demo.py http://127.0.0.1:8146
```

Tests: `python3 -m unittest discover tests`.

### Repo layout

| Path | What |
|---|---|
| `kitea/` | the product: stdlib HTTP server, SQLite store, feed proxies, both UIs |
| `enrichment/` | hazard-context lookups over `wcc_gis` (field names verified live) |
| `wcc_gis.py`, `catalogue.json` | the event's GIS SDK, unchanged |
| `reference/`, `loader-sketches/`, `report_status_loader.py` | pre-event design kit, kept as the record of how the design evolved |
| `tests/`, `scripts/` | API lifecycle tests, demo seeder |

## The event format (for context)

Each team's module was meant to slot into a shared **common operating
picture** — a live map of emergency signals fed by all ten prototypes. Kitea
keeps that composability on its roadmap: an outbound GeoJSON/CAP feed of
reports rather than a closed-off demo.

Two teams work each problem statement independently. That's deliberate: two
honest attempts at the same problem tell WCC more than one.

## Data

The public GIS datasets Wellington City Council Emergency Management shared are
catalogued, checked and made queryable here:

- **Catalogue + SDK** — https://github.com/claudecommunity-nz/wcc-emergency-gis-data
- **Browse the datasets** — https://claudecommunity-nz.github.io/wcc-emergency-gis-data/

74 datasets: flood, landslide, earthquake, tsunami, coastal inundation and
climate layers, plus emergency hubs, post-quake road reopening order, water
tanks, deprivation by area, and live river-level and rainfall telemetry.
`wcc_gis.py` is a single file with no dependencies — copy it and
`catalogue.json` into your project.

```python
import wcc_gis

wcc_gis.ids("tsunami")                                    # find datasets
wcc_gis.features("tsunami-evacuation-zones", at=(-41.2790, 174.7804))
wcc_gis.geojson("footpaths", bbox=wcc_gis.WELLINGTON)     # straight into MapLibre
wcc_gis.hilltop_data("Hutt River at Taita Gorge", "Flow")[-1]
```

Three traps worth knowing before you lose an hour to them:

- Everything is published in **NZTM2000, not lat/lng**. Request raw and your
  pins land off the coast of Africa. Always ask for `outSR=4326`.
- **A quarter of the layers are rasters** that advertise a query capability,
  then refuse to answer. Ask them for a PNG instead.
- **One query is silently capped** (`footpaths` has 8,130 features; a request
  returns 2,000). Page properly, or check `exceededTransferLimit`.

## Schedule

| Time | What |
|---|---|
| 08:00 | Arrival and mingle |
| 09:00 | Opening address & problem briefing |
| 09:30 | Build begins |
| 12:30 | Lunch + lightning talks |
| 16:00 | Submissions close |
| 16:30 | Demos + judging |
| 17:45 | Awards + next steps |

## Ground rules

- These are **hazard-planning layers, not live emergency information**.
  In an emergency, call 111.
- **The data is not ours.** Each dataset belongs to its publisher — WCC, Greater
  Wellington, GNS Science, NIWA, Wellington Water, MBIE, NZTA, MetService.
  Licence terms vary per dataset; check the dataset's page before publishing
  anything derived from it, and credit the publisher.
- Be considerate with request rates. These are council servers, and at least one
  host throttles under concurrent load.
- **Keep personal details out of this repo.** It is public. No participant
  names, contact details or application material.
- Treat public social content as a *signal to investigate*, never as verified
  fact — surfacing something unverified as confirmed is the failure mode these
  problem statements are most wary of.

## Licence

Code here is MIT unless stated otherwise. The data is not covered by it.
