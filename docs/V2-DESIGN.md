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
  Verify, hazard context per report, feed-health strip.
- **Comms** (designed, next): council posts an update; it lands as an
  official item on the public canvas (geotagged when relevant). One
  publishing surface, replacing the event build's separate message-board
  world. No open public board: a moderation liability councils will veto,
  and removing it is a selling point.
- **Access** (designed, next): who can verify, who can post comms,
  delegation. Council SSO lands here; the event build's printed access
  cards remain the offline/field fallback story.

## What v2 deliberately drops

The event build's public message board, offers/asks wall and separate
help-request queue fold into this model: help requests are the
`welfare-need` category with urgent treatment in the queue; announcements
are Comms items; the open board goes away entirely.
