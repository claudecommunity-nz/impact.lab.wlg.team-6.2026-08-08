# Impact Lab Wellington — Team 6

Context for Claude Code working in this repo.

## The event

A one-day build with Wellington City Council Emergency Management, Saturday
8 August 2026, at the Waimanga Room, Wellington City Council. Ten teams, five
problem statements, two teams per statement. Each team ships one working
prototype and demos it for four minutes.

## Timeline for the day

| Time | What |
|---|---|
| 08:00 | Arrival and mingle |
| 09:00 | Opening address & problem briefing |
| 09:30 | Build begins |
| 12:30 | Lunch + lightning talks |
| 16:00 | Submissions close |
| 16:30 | Demos + judging |
| 17:45 | Awards + next steps |

Build time is roughly six and a half hours, minus lunch. Scope accordingly:
a narrow thing that works beats a broad thing that doesn't demo.

## This team's problem — 02: Create a two-way information channel between communities and WCC

> How might communities provide WCC with timely, structured information about local conditions, impacts and needs — before and during an emergency — and see that their information has been received?

The current flow is inconsistent and largely one-way. WCC sends information out, while reports from communities arrive through several unrelated channels and may not reach the people who can use them.

A prototype could allow residents, community groups or Community Emergency Hubs to report an issue using a simple form or message. Reports could include location, time, issue type, description and an image. WCC could group similar reports, acknowledge receipt and show whether an issue is being checked or acted on.

**Desired outcome:** WCC gains better local awareness, while communities have a clearer and more dependable route into Council.

All five statements sit inside one frame: the common theme is improving the flow and use of information between communities and Council before and during an event.

## What success looks like

Each prototype is a module in a shared **common operating picture**: a live map
of emergency signals. Prefer outputs that compose — GeoJSON, a feed, an
endpoint — over a self-contained UI that nothing else can read.

Judging is on a four-minute demo. Something running and pointed at real
Wellington data will land better than architecture that isn't finished.

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

## Constraints that matter here

- **Hazard-planning data, not live emergency information.** Nothing built today
  should be presented as an operational emergency source. In an emergency, 111.
- **Show reliability, don't hide it.** Several of these problem statements are
  explicitly about making limitations visible. If the prototype infers or
  aggregates, say so in the interface. Never present an unverified public post
  as confirmed fact.
- **This repo is public and must stay free of personal information** — no
  participant names, contact details, or anything from the application process.
- **Attribution.** Data belongs to its publishers and licences vary per dataset.
  Check before publishing anything derived.

## Conventions

- Keep the README's problem statement in sync if the scope shifts during the day.
- Commit early and often — the repo is the submission.
