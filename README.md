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

## What we're building

One working prototype, demoed in four minutes at 16:30.

Each team's module is meant to slot into a shared **common operating picture** —
a live map of emergency signals that the ten prototypes feed together. Aim for
something that can be pointed at a map, a feed or an API, rather than a
closed-off demo.

Two teams work each problem statement independently. That's deliberate: two
honest attempts at the same problem tell WCC more than one.

## The prototype — run it

```bash
python3 run.py --seed
```

Then open <http://127.0.0.1:8080>. **No `pip install`, no build step, no API
key, no database.** Python 3.9+ and the standard library, so it runs on any
laptop in the room.

Live: **https://impact-lab.bitn.cloud**

### The loop, in three clicks

1. **Report an issue** — pick a type, write a line, tap the map, send. You get
   a reference code like `WLG-K7M2Q`. No account, no login.
2. **WCC view** — the report is on the map. Tap **Being checked**.
3. **My reports** — the status has already changed. Nothing was refreshed and
   nobody was rung.

That is the graded wording of Problem 02 — communities "see that their
information has been received" — as a working thing rather than a diagram.

### What it does

- **Reference code instead of auth.** No accounts. During an emergency a login
  screen is a barrier between someone and the information you need from them.
  Possession of the code is the claim; it is kept on the reporter's device and
  can be typed in on any other.
- **Nothing is ever edited.** A status change publishes a *new* signal chained
  to the original report, and current status is derived by replaying the chain.
  The reporter's view and the council's view cannot disagree, and afterwards
  there is a complete timestamped record of who knew what and when. This falls
  out of the platform's own shape: `publish_signal` exists, `update_signal`
  does not.
- **Similar reports group.** Same issue type, within 250 m, inside six hours.
  Deliberately arithmetic rather than a language model, so it is explainable to
  a duty officer and works with no API key.
- **Hazard context, labelled as inferred.** When a report lands, the WCC hazard
  layers are asked what is true of that location — tsunami evacuation zone,
  nearest Community Emergency Hub. Shown as context, never as confirmed fact.
- **It composes.** `/api/geojson` and `/api/signals` are CORS-open and need no
  key, so any other team's map can read this module directly.

### The message board

The reporting loop is one-to-one. The board is the other half — everyone
talking to everyone, with officials clearly identifiable. Three surfaces, all
on the same append-only log:

- **Agency wall** — eight real agencies (WCC Emergency Management, WREMO,
  Wellington Water, FENZ, Police, Greater Wellington, Free Ambulance, Red
  Cross), each its own channel, all on one screen. Officials coordinating with
  each other. **The public are not in these** — a public request for an agency
  channel is a 403, and agency channels are absent from the public channel
  list entirely rather than filtered out of it.
- **Public boards** — city-wide plus one per suburb. Anyone posts; officials
  are badged with their agency, everyone else is a neighbour.
- **Important comms banner** — officials publish one line and it appears at
  the top of every public screen at once, at four escalating levels.

The author picks **Everyone can see this** or **Only officials** per message —
the second for anything about a named person, like a welfare concern about a
neighbour. Officials can flag a message, which takes it out of the public feed
and leaves a visible marker in its place.

That last detail matters. Because the log is append-only, a flag is a *new*
signal chaining to the message, never an edit or a delete, so **moderation on
a public emergency board cannot silently erase what somebody said**. Clearing
the banner works the same way — another entry, not a deletion, so afterwards
you can say exactly what was displayed and for how long.

No new storage and no new dependency: a message is a `chat-message` signal, a
flag is a `chat-flag` chaining to it, the banner is a `comms-banner`. The
existing `?since=` cursor already makes it live.

**Identity is deliberately absent**, matching the reference-code model — a
random per-browser `author_id` in `localStorage` that proves nothing and only
lets the board show you your own private messages after a reload. Officials
are marked by a client-set role, so on a public deployment anyone can claim
one. That is the first thing this needs before it is more than a demo.

**The demo content is invented.** `demo_data.py` fills the board with one
coherent scenario matching the seeded reports. The agencies are real so a WCC
judge sees their own operating picture, but none of them wrote any of it and
it describes no real incident — the agency wall says so on screen.

### The map has no dependencies

Plain SVG: real WCC GeoJSON projected into a viewBox, about eighty lines in
`web/app.js`. No MapLibre, no Leaflet, no CDN — a `<script src>` to someone
else's server is a single point of failure that fails exactly when the venue
wifi does. `tools/fetch_basemap.py` bakes the geometry to
`web/data/basemap.json`, so a fresh clone renders fully offline. Layers: the
19 tsunami evacuation zones and all 60 Community Emergency Hubs.

### Tests

```bash
python3 -m unittest discover tests -v      # 46 tests, ~0.6s
```

Standard library `unittest`, no pytest. They cover the things that would break
the demo or mislead the council, plus every message-board visibility rule —
who can read an agency channel, whether a private message leaks, and that
flagging never deletes: acknowledgement fires without a human, status
is derived rather than stored, the log survives a restart including a torn
final line, grouping does what the interface claims, and GeoJSON comes out
lng/lat the right way round.

### It still drops onto the platform

`loader.py` implements the platform contract — `main()`, `tick()`, `sample()`
— and is the working implementation of the design in
`reference/report-status-design.md`. It binds to `wcc_impact` if that is
importable and to a local append-only log if it is not, through the same
`ReportService`: the same code path in both cases, only the store differs. So
nothing here was blocked waiting for the SDK, and nothing needs rewriting when
it arrives.

It also settles one of that design's open questions — whether
`publish_signal()` returns the created signal, which the reference code was
assumed to need. `PlatformStore` mints the reference itself and carries it in
`raw.reference`, so it works either way.

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

Two further traps, found in `enrichment/hazard_context.py` and fixed here.
Both were verified live against the WCC services on 2026-08-08, and both fail
*quietly* — worth knowing if you use that module.

- **Hubs came back `name: None`.** The code read `Name` / `HubName` /
  `FACILITY`; the live layer publishes `NAME` / `ADDRESS` / `SUBURB` in upper
  case. All 60 hubs were anonymous.
- **"Nearest" hub was not the nearest.** A `near=` query is a spatial *filter*,
  not a sort — it returns whatever is inside the radius in arbitrary order, so
  `limit=1` gave an arbitrary hub within 5 km. A Newtown report was told its
  nearest hub was Aro Valley, about 2 km further than the right answer. Now all
  candidates are fetched and sorted by haversine. Telling someone the wrong
  place to walk to during an emergency is not a cosmetic bug.

There is a third, unrelated one: `enrichment/signal_helpers.py` does
`from wcc_impact import ...` at module scope, so it cannot be imported at all
without the SDK. `core/signals.py` is a standalone equivalent with the same
field names and limits.

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
