# Kitea privacy review (NZ Privacy Act 2020)

Status: **drafted 2026-08-10, awaiting accountable sign-off.** This is a
working privacy review of the Kitea prototype against the thirteen
Information Privacy Principles, written to be handed to a council privacy
officer for a formal PIA at pilot. It documents what the system actually
does, verified against the code and its tests, not aspirations.

## What personal information exists

| Data | Collected when | Stored | Who can see it |
|---|---|---|---|
| Contact detail (phone/email) | Optional field on a report or an offer | Plain text, SQLite, on the council-controlled host | Ops roles only. Never echoed to the reporter, never public, never on the event stream (tested) |
| Free-text description / offer text | Report or offer submission | Same | Ops + the reporter (via their code); offers also to the report's owner |
| Photos | Optional on a report | File on host, unguessable name | Ops + the reporter; never on public surfaces |
| Location | Map pin or place text | Same | Public at the precision the reporter chose (pin or suburb text); the privacy note states this at submission |
| Reporter identity | **Not collected.** No accounts, no names, no IP retention beyond in-memory rate windows | — | — |
| Ops user names | Access tab, entered by an admin | Name + role + hashed key | Ops; names appear in the audit trail |

## Principle-by-principle

- **IPP1 (purpose/necessity):** only fields the response needs; contact is
  optional and labelled with who sees it. No account or identity demanded
  — the reference code stands in for authentication by design.
- **IPP2/3 (source/transparency):** collected directly from the individual,
  with on-form notice of exactly what becomes public ("category, general
  location and status") versus council-only (description, photo, contact).
- **IPP4 (fair means):** no dark patterns; every optional field says so.
- **IPP5 (storage security):** data stays on the council-controlled host
  (no third-party processors; agency feeds are inbound only). TLS at the
  edge, zero public origin ports, ops access role-gated with hashed keys,
  encrypted offsite backups. Gap for pilot: SQLite file itself is not
  encrypted at rest on the host.
- **IPP6/7 (access/correction):** the reporter sees their own record via
  their reference code. Correction/deletion is manual (ops) in the
  prototype; a pilot needs a stated process.
- **IPP8 (accuracy):** provenance is explicit everywhere: community
  reports are labelled "shared as received, not yet council-verified";
  verification is a recorded act with a named actor.
- **IPP9 (retention):** **gap — no retention schedule.** The append-only
  design is deliberate for the audit record, but a pilot must define how
  long reports, photos, contacts and backups live, and implement disposal.
  Proposed for sign-off: contacts purged 90 days after resolution; photos
  12 months; anonymised report rows retained for planning.
- **IPP10/11 (use/disclosure):** used only for the response loop; the
  public sees the sanitised subset; contact details are never disclosed
  (offer contacts visible to ops only, tested).
- **IPP12 (cross-border):** hosting is currently Hetzner Singapore for the
  demo — **flagged: a council pilot should host in NZ or under an
  agreement satisfying IPP12.** Cloudflare edge terms apply to transit.
- **IPP13 (unique identifiers):** reference codes are random per report,
  not reused, and carry no meaning; public ids are a separate namespace
  with no access rights.

## Residual risks for sign-off

1. Free-text fields can carry third-party personal information (a
   neighbour's name); ops guidance + a redaction affordance are the pilot
   mitigations.
2. Photos may capture people/property; public surfaces never show them,
   but retention (IPP9) and a takedown path need the formal process.
3. No encryption at rest on the host disk (mitigated by host control and
   encrypted backups; fix at pilot with disk encryption).
4. Demo host is offshore (IPP12, above).

Sign-off: ______________________ (accountable owner, date)
