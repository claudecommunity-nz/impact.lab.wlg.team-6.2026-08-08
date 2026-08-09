# Kitea — the commercial case

*Working name: "kitea" is te reo Māori for "seen / found" (passive of kite).
The name states the product promise: your report has been seen. Before any
real launch the name and all te reo usage must be reviewed with mana whenua
and a te reo advisor; treat it as a placeholder with intent.*

## The problem, in one sentence

Councils spend an event's worst hours answering "did you get my report?"
phone calls, while the people who could tell them what is actually happening
on the ground have no reliable way in and no evidence they were heard.

The design insight this product is built on: **roughly a third of council
call-centre volume is status checks**. Nobody wants to make that call, and
nobody wants to answer it. Every one of them is a failure of acknowledgment,
not of information.

## What Kitea is

A two-way information channel between a community and its council, modelled
on delivery tracking rather than a support ticket:

- **Residents, community groups and Community Emergency Hubs** report local
  conditions in under a minute: category, pin on a map, description, photo.
  No account, no app store, no login. They get a short reference code and a
  page that updates itself the moment the council acts:
  `received → reviewing → responding → resolved`.
- **The council duty team** gets one operating picture: every report pinned
  on a live map beside the real-time feeds they already watch separately
  (river and rain telemetry, road closures, power outages, weather warnings,
  earthquakes), with similar reports grouped into situations. Acting is one
  tap, and that tap *is* the public acknowledgment. Every report is
  automatically enriched with the council's own hazard context: tsunami
  zone, mapped ponding, liquefaction class, nearest Community Emergency Hub,
  nearest live river gauge, NZDep deprivation decile.

One tap on the council side replaces one inbound phone call on the other.
That is the entire economics of the product.

## Why a council would adopt it

1. **It reduces work rather than adding it.** The acknowledgment loop is
   cheaper than the phone call it replaces. Nothing about it requires a new
   team or a social-media monitoring desk.
2. **It runs on anything.** Python standard library, one SQLite file, no
   external services and no per-seat licences. A council can run it on the
   hardware it already owns, inside its own network boundary. Procurement
   has almost nothing to assess.
3. **Data sovereignty by construction.** Reports never leave the council.
   Contact details and photos are ops-only by default; the public view is
   category, locality and status. That maps cleanly onto NZ Privacy Act 2020
   principles (minimisation, purpose limitation, access control).
4. **An audit trail for free.** Status changes are append-only events, never
   edits. After the event, the council has a defensible record of what was
   reported, when it was seen, and what was done, ready for the post-event
   review and the coroner's counsel alike.
5. **It composes with what exists.** Feeds in are the agencies' own public
   APIs (GWRC Hilltop, Waka Kotahi, GeoNet, NEMA, MetService CAP). The
   roadmap output is a GeoJSON/CAP feed so reports slot into any common
   operating picture (ArcGIS, D4H, whatever the CDEM group runs), rather
   than competing with it.
6. **Inclusion is structural, not a checkbox.**
   - No account or email needed; possession of a code is the only credential.
   - Works in any browser on any phone; heavy assets (map library, fonts)
     are served locally, not from CDNs that may be unreachable in an event.
   - Body typeface is Atkinson Hyperlegible, designed by the Braille
     Institute for low-vision readers.
   - "Reporting as" explicitly includes community groups, hubs and
     *on behalf of someone else*: the librarian, the marae, the neighbour
     with the working phone are all first-class reporters.
   - The NZDep decile on every report lets the duty officer see when a
     cluster of need is coming from a community with the fewest private
     resources.

## Market and model

- **Primary market:** New Zealand's 67 territorial authorities and 16 CDEM
  groups. The pain is universal; the current tooling is a mix of phone,
  email, social media monitoring and paper.
- **Beachhead:** one council (Wellington City, whose problem statement this
  answers), one suburb-scale pilot, one scheduled exercise with a Community
  Emergency Hub network. Success metric agreed up front: status-check call
  deflection and time-to-first-acknowledgment.
- **Model sketch** (to be validated, not a promise):
  - Pilot engagement, fixed-fee, one event exercise included.
  - Annual per-council licence with hosting either self-hosted (support
    contract) or managed single-tenant. Small councils should pay less than
    the cost of one week of after-hours call-centre overflow.
  - CDEM-group tier: shared operating picture across member councils.
- **What is defensible:** not the code (a form and a map are replicable) but
  the loop design (acknowledgment-first), the hazard-context enrichment
  wired to each region's own data, and event-tested trust with hubs and
  community networks. Those compound per deployment.

## Honest limitations (what this prototype is not)

- Not an emergency channel and never marketed as one. 111 messaging is
  baked into the UI and stays.
- Ops access is a single shared key: fine for a demo, replaced by council
  SSO (Entra/RealMe) before any pilot.
- No HTTPS termination, moderation queue, CAPTCHA/abuse hardening, backups,
  or monitoring in the prototype; all are pilot-blockers and all are
  well-understood work.
- Accessibility is designed-in but not yet audited to WCAG 2.2; te reo
  content not yet reviewed; both required before public launch.
- Basemap tiles come from OpenStreetMap's public servers; a pilot needs
  self-hosted or LINZ tiles for load and for offline resilience.

## Roadmap after pilot

1. Outbound feed (GeoJSON + CAP) so reports appear in the CDEM common
   operating picture, fulfilling the "module, not silo" brief.
2. SMS in/out gateway so a reporter with no data connection can still
   report and still get the acknowledgment loop.
3. Offline-first PWA and self-hosted tiles for degraded-network operation.
4. Duplicate-merge and bulk-status for the ops queue at real event volumes.
5. Multilingual UI (te reo, Samoan, Tongan, Hindi, Mandarin: Wellington's
   actual languages), each reviewed by speakers, not machine-translated.

## Provenance

Kitea is the commercialisation track of Team 6's Impact Lab Wellington 2026
submission (Problem 02, with Wellington City Council Emergency Management).
The event build itself lives in this repo (`run.py`, `core/`, `web/`), stays
runnable offline, and is demoed at https://impact-lab.bitn.cloud. All live data belongs to its
publishers and is credited in the product footer. Code is MIT. The repo is
public and contains no personal information.
