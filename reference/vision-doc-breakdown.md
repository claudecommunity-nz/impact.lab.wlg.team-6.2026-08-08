# Vision doc breakdown — the regenerative loop

A teammate shared a vision doc the night before the build (7 Aug 2026). It
proposes two features beyond the acknowledgment loop we'd already designed,
plus a cycle diagram offered as the pitch centrepiece. This is that doc
decomposed and checked against what's actually in this repo.

The source is a Word file on a personal university SharePoint; not linked
here, since this repo stays free of personal information.

## What the doc is

55 lines, ~1.6 KB of text, three sections. It **starts at heading "8."** — it
is the tail of a longer list, and items 1–7 are not in the file we have. If
those seven contain the intake mechanic, we're planning around a fragment.

```
8. Introduce Community Missions - Gamified
9. Make climate adaptation visible
The core regenerative model
```

## §8 — Community Missions

Monthly prompts pushed to residents before an emergency, whose completions
accumulate into "Wellington's community resilience dataset". Framed as
crowdsourced preparedness — "participatory rather than bureaucratic".

The doc gives four examples as if they were interchangeable. They aren't —
they collect four different things and carry four different risks:

| Mission | What it actually is | Collision |
|---|---|---|
| Find your nearest emergency water source | Verification of a known WCC asset | `water tanks` layer is already in the catalogue |
| Does your street have someone with first-aid skills? | Human capability census | Personal information about identifiable third parties |
| Identify a neighbourhood gathering point | Community-proposed geography | `emergency hubs` layer is already in the catalogue |
| Photograph a blocked storm drain before heavy rain | Pre-hazard condition report | None — the only genuinely new data of the four |

Two things to carry forward. The storm-drain mission is the one worth
building, because it's the only one that produces data WCC doesn't already
hold. And the first-aid mission **cannot be built as written** — it collects
capability information about neighbours who never consented, and the doc
gives it no privacy treatment at all.

The heading says *Gamified*. No mechanics are specified anywhere — no points,
badges, streaks, leaderboards or completion feedback. The word is carrying
the whole idea.

## §9 — Climate adaptation visible

Reports accumulate over years into community-generated climate adaptation
evidence. Five atoms: yearly aggregation; spatial clustering by catchment;
threshold detection that auto-flags "Emerging Climate Resilience Issue /
frequency increasing"; an intervention menu attached to the flag; and
cross-silo routing, Emergency Management → Climate Adaptation → Urban
Planning.

The intervention menu escalates from engineering to withdrawal: stormwater
upgrades, wetlands, sponge-city interventions, managed retreat investigation,
community resilience infrastructure.

The worked example — 2026: 13 flooding reports, 2027: 22, 2028: 37, all in
one catchment — is explicitly hypothetical. The doc says "For example". We
have no multi-year community report history and won't have one by 16:00.

No threshold is defined for what counts as "increasing", and no baseline is
named to measure against.

## The core regenerative model

Offered as the central diagram of the pitch:

```
COMMUNITY OBSERVATION → EMERGENCY SIGNAL → LOCAL RESPONSE → COUNCIL RESPONSE
   → RECOVERY DATA → PATTERN IDENTIFICATION → RESILIENCE INVESTMENT
   → STRONGER COMMUNITY + ECOSYSTEM ↺
```

Closing line: "That loop is probably more important than any individual
feature."

Mapped against what exists here:

| # | Stage | Who acts | Status in this repo |
|---|---|---|---|
| 1 | Community observation | Resident / hub | Intake *shape* only — `loader-sketches/track2_community.py` polls, classifies, geocodes, publishes. No real form. |
| 2 | Emergency signal | System | `publish_signal` — covered |
| 3 | **Local response** | Neighbours / hub | **No mechanism, here or in the doc** |
| 4 | Council response | WCC staff | `set_status()` — `report_status_loader.py:149` |
| 5 | **Recovery data** | Undefined | **No mechanism, here or in the doc** |
| 6 | Pattern identification | System | Primitive exists — `_find_duplicates()`, `loader-sketches/track4_triage.py:100` |
| 7 | **Resilience investment** | Council | Beyond any one-day prototype |
| 8 | Stronger community | — | An outcome, not a feature |
| ↺ | Return arc | Council → residents | This is what §8 missions are |

Two consequences.

**Stage 6 is already half-built.** `_find_duplicates()` clusters on 1 km
haversine distance and 0.6 title similarity. §9 is the same operation with
the time window stretched from minutes to years. That's the cheapest bridge
from this doc to running code.

**Stages 3, 5 and 7 have no mechanism anywhere.** The eight-stage loop is a
three-and-a-half-stage loop in practice. Say so if it goes on a slide.

## Dependencies the doc doesn't account for

- **Missions need identity; the platform has none.** `report-status-design.md`
  establishes that no auth exists anywhere in the platform docs, which is why
  acknowledgment runs off a possession-based reference code. A mission implies
  a persistent resident who receives it, completes it, and is prevented from
  completing it a hundred times. Unresolved conflict.
- **Missions need a push channel to residents.** None exists.
- **§9 needs stable geographic buckets.** It says "catchment" — check whether
  the 74-dataset catalogue actually has a catchment boundary layer, or whether
  we'd be substituting suburb.
- **§9 needs multi-year persistence.** Append-only signals suit this well;
  that part is fine.

## The structural gap

Problem 02's graded wording is that communities "see that their information
has been received". **The loop has no acknowledgment stage.** It runs
observation → signal → local response → council response, skipping receipt
entirely.

The doc is a strong account of what the channel *becomes over years*. It
drifts off what the brief asks for and what `report-status-design.md` is
built around.

## Where this leaves the build

| Piece | Cost | Call |
|---|---|---|
| The loop diagram | Free — it's a slide | Take it. Better framing for four minutes than anything else we have. |
| Missions | Medium — a mission is a signal with a known type, but needs a second UI surface and an identity story | Best stretch goal. Also seeds pins so we don't demo an empty basemap. |
| Multi-year climate trend | Data-blocked | Don't. |

If any of §9 goes in, the honest version is spatial rather than temporal:
cluster today's reports against the existing flood-hazard layer and
deprivation-by-area data, labelled as correlation, not trend. An "Emerging
Climate Resilience Issue" flag over sparse reports is an inference, and
inference has to be labelled as such in the interface.

## Open questions

- Can we get items 1–7? The missing seven are where the core mechanic
  probably sits.
- Does the catalogue have catchment boundaries, or do we substitute suburb?
- How does a mission reach a resident at all, given there's no auth and no
  push channel — and does that conflict with the reference-code model in
  `report-status-design.md`?
