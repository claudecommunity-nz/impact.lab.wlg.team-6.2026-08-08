# Kitea v2 design: one canvas, provenance-first

Agreed direction (2026-08-10): stop making people choose between pages that
imply categories (Live map / Community map / Report / My reports). v2 has
exactly two surfaces.

## Surface 1: the public canvas (`/`)

One full-viewport map. Everything a resident does happens on or over it.

### Lenses (segmented control, one active)

The lens answers the sentence the visitor is asking:

| Lens | Shows | The question it answers |
|---|---|---|
| Everything | all of the below | "what's going on?" |
| Official | agency feeds + council-verified reports | "what's confirmed?" |
| Community | reports not yet verified (incl. mine) | "what are people saying?" |
| Mine | reports whose reference codes are on this device | "where are my reports?" |

### Type chips (additive filters, cut across lenses)

Flooding & drains · Slips · Roads · Power · Rivers & rain · Weather ·
Quakes · Help & hubs · Other. One vocabulary across community reports and
agency feeds: an NZTA closure and a verified road-damage report are both
"Roads".

### Provenance is the visual language

One encoding per channel, never mixed:

- **Shape/ring = provenance.** Community report: round dot. Council-verified:
  the same dot earns a pine ring. Mine: kōwhai halo. Agency items keep their
  distinctive marks (gauge pills, warning polygons, hub glyphs).
- **Colour = status** (received/reviewing/responding/resolved, the validated
  status palette). Severity colours are reserved for weather polygons.
- Every pin's tap card states provenance in words as well ("Official ·
  verified by the council", "Community report · shared as received"), so
  the encoding is never colour-alone.

### Interaction rules

- **Tap first, hover is sugar.** The panel (right on desktop, bottom sheet
  on mobile) shows the same card either way; nothing exists only on hover.
- **The list twin.** The panel's default content is the list form of exactly
  what the current lens+chips show, newest first. Map-only UIs exclude
  screen readers and tiny data plans; the list is the same state, always on.
- **Report is an action, not a page.** A floating "Report something" button
  enters placing mode ("tap the map where it is"); the tap opens the drawer
  with the pin set and the hazard hint already fetched. The drawer also
  opens without a pin (place can be described in words).
- Deep links: `/?item=<public_id>` opens the canvas with that item selected;
  `/?ref=<code>` remains the private tracking page.

## Identity model (the fix v2 forced)

The reference code (`WGN-…`) is the reporter's **credential**: it unlocks
the private view and must never appear on public surfaces. The map speaks
**public ids** (`K…`), which carry no access. v1 used the ref for both and
the public list leaked credentials; v2 splits them at the store level and
the SSE hub only broadcasts sanitized payloads (public_id, status,
verified) to the public stream. Reporter-targeted events (with notes) go
only to the holder of the code; full payloads only to ops.

## Verification (the event that moves a pin between lenses)

`verified` is an explicit append-only event, not a vibe: who (ops actor),
when, optional note. It is orthogonal to the response lifecycle (a report
can be verified and still `reviewing`). One tap in the ops console:

1. inserts the event and flags the report,
2. tells the reporter ("Council verified your report") on their stream,
3. broadcasts the sanitized flag so the public pin earns its official ring
   live: the demo moment.

`verified` is rejected as a lifecycle status by validation; the two
vocabularies cannot bleed into each other.

## Surface 2: the council console (`/ops`)

Same map component and data, plus the private layers, in three tabs:

- **Queue** (built): triage, situation grouping, one-tap statuses, one-tap
  Verify, hazard context per report, feed-health strip, offers of help per
  report, and the photo stack: every photo from a grouped situation shown
  together on any report in the group.
- **Comms** (built): council posts an update (typed, optionally geotagged,
  optional expiry); it lands on the public canvas as an official item
  immediately, withdrawable but never deleted. One publishing surface,
  replacing the event build's separate message-board world. No open public
  board: a moderation liability councils will veto, and removing it is a
  selling point.
- **Access** (built): named keys, one per person, in three roles: duty
  (statuses + verify), comms (public updates), admin (both + people +
  emergency mode). Keys are shown once and stored hashed; revocation is
  immediate; every status/verify event carries the actor's name in the
  audit trail. Only a human admin can issue keys: no automated promotion
  path exists, by design. Council SSO replaces keys at pilot; the event
  build's printed access cards remain the offline/field fallback story.

## Community participation (built with v2.1)

- **Ask for help** is a first-class action beside "Report something":
  same drawer, welfare-need preselected, urgent treatment in the queue.
- **Offers of help** attach to items: a neighbour taps an item and offers
  hands, equipment, transport, shelter, food/water, a check-in, or a
  skill, with optional contact. Deliberately council-mediated: the public
  sees only the count, the reporter sees the offers (no contact details),
  ops sees everything and can connect people. Participation without an
  open wall.
- **Emergency mode**: an admin declares it and the whole platform states
  it: the public banner switches to "the council is coordinating the
  response". Standing down is the same single control. In normal times the
  platform runs exactly the same loop for everyday reports: the emergency
  posture is a switch, not a separate product.

## Live demo affordances (built with v3)

- **Simulate WCC staff** on a community item lets a public visitor feel the
  council side — acknowledge, set a status, post an update — entirely
  SANDBOXED: it writes only to an ephemeral `demo_actions` table (30-min
  auto-expiry), never touches the report's real status/verification/audit,
  and is always labelled "simulated, not a real council action".
- **Abuse filter** (`kitea/moderation.py`, stdlib): every public free-text
  input (reports, offers, demo notes) is checked and abusive text rejected.
  Demo-grade wordlist matcher with leetspeak + boundary handling; a pilot
  uses a maintained moderation service.
- **Council broadcast alerts + resident sign-up**: an ops alert fires a
  priority banner to every open page and a browser Notification to opted-in
  residents; the subscriber count is shown to the council. Delivery is via
  the open SSE stream + the Notifications API (page must be open). PILOT
  needs Web Push (service worker, background delivery) + an SMS gateway so
  no-data phones are reached — already on the roadmap below.
- **First-visit tour**: a one-time click-through (localStorage) explaining
  the map, lenses, reporting, help and alerts.

## The horizon: working as one

Where this goes next, agreed 2026-08-10 (designed, not yet built):

- **Notification tiers**: official notifications (council/agency, pushed
  prominently) vs community notifications (nearby reports, opt-in), on Web
  Push and an SMS gateway so no-data phones stay included.
- **Agency collaboration**: agencies as first-class actors: an agency role
  posting into Comms under its own name (Wellington Water, NZTA, WREMO),
  and the outbound GeoJSON/CAP feed so Kitea items appear in the CDEM
  common operating picture and vice versa. The council can ask FOR help,
  not just receive it: a council "request for resources" item type that
  agencies and community both see and answer with the same offer mechanic.
- **Standing skills register**: residents register capabilities out of
  event time (chainsaw, 4WD, first aid, languages, ham radio) so the offer
  pool exists before it is needed: recruitment happens on the calm days.

## What v2 deliberately drops

The event build's public message board, offers/asks wall and separate
help-request queue fold into this model: help requests are the
`welfare-need` category with urgent treatment in the queue; announcements
are Comms items; the open board goes away entirely.
