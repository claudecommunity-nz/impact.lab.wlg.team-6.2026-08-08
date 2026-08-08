#!/usr/bin/env python3
"""End-to-end smoke test against a running instance.

    python3 tests/smoke.py                          # local, default port
    python3 tests/smoke.py https://impact-lab.bitn.cloud

The unit tests prove the pieces work. This proves the PRODUCT works: it walks
every journey a real person takes, in order, against a real server over real
HTTP — the resident who reports something, the resident who asks for help, the
duty officer who answers, the moderator who approves a photo, the coordinator
who issues a card.

It also asserts the things that must NOT happen, because a smoke test that
only checks the happy path will happily certify a system that leaks.

Exit code is the number of failures, so it can gate a deploy.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
COORDINATOR = "WCC-JYCE-VWQE-U3PX-S2DY"
MODERATOR = "WCC-U69C-USPV-J6TP-CRG6"
HUB_LEAD = "WCC-NYUX-HEAH-SFXT-9XD9"

passed, failed, notes = 0, [], []


def check(label: str, got, want=True):
    global passed
    ok = (got == want) if not callable(want) else want(got)
    if ok:
        passed += 1
        print(f"  ok    {label}")
    else:
        failed.append(label)
        print(f"  FAIL  {label}  (got {got!r}, wanted {want!r})")
    return ok


def call(path: str, method="GET", body=None, token=None, timeout=45):
    """Returns (status, parsed_json_or_text)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Identify ourselves. Cloudflare's browser-integrity check returns a 1010
    # for the bare `Python-urllib/x.y` default User-Agent, so a smoke test
    # that did not set one would report the whole site as 403 and be wrong
    # about it. Every other client — curl, requests, a browser — is fine.
    headers["User-Agent"] = "impact-lab-team6-smoke/1.0"
    request = urllib.request.Request(BASE + path, data=data,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw.decode("utf-8", "replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def section(title: str):
    print(f"\n\033[1m{title}\033[0m")


# ---------------------------------------------------------------------------

section("The pages a person actually opens")
for path in ("/", "/app.js", "/styles.css"):
    check(f"{path} serves", call(path)[0], 200)

section("Data every page depends on")
for path in ("/api/health", "/api/meta", "/api/live", "/api/news",
             "/api/basemap", "/api/geojson", "/api/community",
             "/api/adaptation", "/api/realtime", "/api/auth/demo-cards"):
    status, payload = call(path)
    check(f"{path}", status, 200)

status, meta = call("/api/meta")
check("five response stages", len(meta.get("statuses", [])), 5)
check("every stage has a plain meaning",
      all(meta.get("status_meanings", {}).get(s) for s in meta.get("statuses", [])))

status, basemap = call("/api/basemap")
check("gazetteer shipped for offline address lookup",
      len(basemap.get("places", [])) > 2000)
check("hazard layers shipped", len(basemap.get("features", [])) > 50)

section("A resident reports something and is answered")
status, created = call("/api/reports", "POST", {
    "title": "Smoke test — water over the road",
    "description": "Filed by the automated smoke test.",
    "issue_type": "flooding", "lat": -41.2432, "lng": 174.8100,
    "place_name": "Ngauranga", "severity": "moderate", "author_id": "smoke"})
check("report accepted", status, 201)
ref = created.get("reference", "")
check("reference code is speakable", bool(ref) and ref.startswith("WLG-"))
check("acknowledged with no human involved", created.get("status"), "received")

status, view = call(f"/api/reports/{ref}")
check("reporter can read their own report", status, 200)
check("timeline starts immediately", len(view.get("timeline", [])) >= 1)

section("The reporter can speak again — the loop is two-way")
check("follow-up accepted without a card",
      call(f"/api/reports/{ref}/followup", "POST",
           {"kind": "worse", "note": "Now over the footpath.",
            "author_id": "smoke"})[0], 201)
status, view = call(f"/api/reports/{ref}")
voices = {c["who"] for c in view.get("conversation", [])}
check("conversation carries both voices", voices, {"wcc", "reporter"})
check("invented follow-up refused",
      call(f"/api/reports/{ref}/followup", "POST", {"kind": "nonsense"})[0], 400)

section("Nobody without a card can act as the council")
for label, path, body in (
        ("set a report status", f"/api/reports/{ref}/status", {"status": "resolved"}),
        ("publish the banner", "/api/banner", {"text": "hijacked"}),
        ("publish an issue", "/api/live/issue", {"title": "hijacked"}),
        ("post agency news", "/api/news", {"title": "x", "agency": "wcc-em"}),
        ("open the moderation queue", "/api/community/queue", None),
        ("approve content", "/api/community/moderate",
         {"item_id": "x", "state": "approved"})):
    method = "GET" if body is None else "POST"
    check(f"refused: {label}", call(path, method, body)[0], 401)

check("refused: post into an agency channel",
      call("/api/chat/messages", "POST",
           {"channel_id": "fenz", "author_id": "smoke",
            "body": "I am the fire service and this is long enough to pass"})[0], 403)

section("A duty officer signs in with a printed card")
status, session = call("/api/auth/redeem", "POST", {"code": COORDINATOR})
check("card redeems", status, 200)
token = session.get("token", "")
check("card carries a role", (session.get("session") or {}).get("role"), "coordinator")
check("a mistyped card is refused as a typo",
      call("/api/auth/redeem", "POST", {"code": COORDINATOR[:-1] + "Z"})[0], 401)

section("...and drives the report through every stage")
for stage in ("reviewing", "enroute", "onsite", "resolved"):
    check(f"status: {stage}",
          call(f"/api/reports/{ref}/status", "POST",
               {"status": stage}, token)[0], 201)
status, view = call(f"/api/reports/{ref}")
labels = [t["label"] for t in view.get("timeline", [])]
check("all five stages recorded", len(labels), 5)
check("stages read in plain English",
      labels[-3:], ["On the way", "Crew on site", "Fixed"])
check("invented status refused",
      call(f"/api/reports/{ref}/status", "POST", {"status": "nearly"}, token)[0], 400)

section("Asking for help, and getting an honest answer")
status, request = call("/api/live/request", "POST", {
    "need": "welfare", "detail": "Smoke test — neighbour has not answered.",
    "urgency": "today", "author_id": "smoke", "author_name": "Smoke",
    "visibility": "officials", "contact": "021 000 0000"})
check("help request accepted", status, 201)
rid = request.get("id", "")
check("officials answer likelihood and timeframe separately",
      call("/api/live/update", "POST",
           {"target_id": rid, "likelihood": "unable", "timeframe": "no-eta",
            "note": "Smoke test."}, token)[0], 201)
check("an invented likelihood is refused",
      call("/api/live/update", "POST",
           {"target_id": rid, "likelihood": "maybe", "timeframe": "today"},
           token)[0], 400)

section("A private request stays private")
status, public = call("/api/live")
ids = [r["id"] for r in public.get("requests", [])]
check("officials-only request hidden from the public", rid not in ids)
status, official = call("/api/live", token=token)
check("...and visible to an official",
      rid in [r["id"] for r in official.get("requests", [])])

section("The public log leaks nothing")
status, log = call("/api/signals")
signals = log.get("signals", [])
check("no officials-only content",
      sum(1 for s in signals if (s.get("raw") or {}).get("visibility") == "officials"), 0)
check("no contact details",
      sum(1 for s in signals if "contact" in (s.get("raw") or {})), 0)
check("no agency traffic",
      sum(1 for s in signals if (s.get("raw") or {}).get("channel_kind") == "agency"), 0)
check("no unapproved community content",
      sum(1 for s in signals if (s.get("raw") or {}).get("state") in ("pending", "rejected")), 0)
check("no card events", sum(1 for s in signals if s.get("signal_type") == "card-event"), 0)
check("reports still compose for other teams",
      len(call("/api/geojson")[1].get("features", [])) > 0)

section("The board keeps itself readable")
check("a one-word cry for help is challenged, not dropped",
      call("/api/chat/messages", "POST",
           {"channel_id": "wellington", "body": "help", "author_id": "smoke2"})[0], 422)
check("a useful message is accepted",
      call("/api/chat/messages", "POST",
           {"channel_id": "wellington", "author_id": "smoke2",
            "body": "Smoke test: water over the road near the Ngauranga onramp."})[0], 201)
check("the same message twice is refused",
      call("/api/chat/messages", "POST",
           {"channel_id": "wellington", "author_id": "smoke2",
            "body": "Smoke test: water over the road near the Ngauranga onramp."})[0], 422)

section("Links can never carry a script")
for scheme in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
               "vbscript:msgbox", "//evil.example"):
    check(f"refused: {scheme[:28]}",
          call("/api/news", "POST",
               {"title": "probe", "agency": "wcc-em", "category": "general",
                "link": scheme}, token)[0], 400)
check("a real link is accepted",
      call("/api/news", "POST",
           {"title": "Smoke test update", "agency": "wcc-em",
            "category": "general", "link": "https://wellington.govt.nz"},
           token)[0], 201)

section("Uploads cannot be talked into being something else")
# Assert the SECURITY PROPERTY, not one status code. Behind Cloudflare the
# percent-encoded variants are rejected at the edge with a 400 before they
# reach us, which is stricter than our own 404 — an assertion pinned to 404
# would have called that a regression. What matters is that every variant is
# refused and none of them ever returns file content.
for attempt in ("/uploads/../../etc/passwd",
                "/uploads/..%2f..%2fetc%2fpasswd",
                "/uploads/....//etc/passwd",
                "/../../etc/passwd",
                "/uploads/%2e%2e%2f%2e%2e%2fetc%2fpasswd"):
    status, body = call(attempt)
    refused = 400 <= status < 500
    leaked = "root:" in str(body)
    check(f"refused, nothing leaked: {attempt[:40]}", refused and not leaked)
check("unknown upload refused",
      call("/uploads/deadbeefdeadbeef.jpg")[0], lambda s: 400 <= s < 500)

section("Delegation always loses privilege")
status, issued = call("/api/auth/issue", "POST",
                      {"role": "official", "holder": "Smoke Test Official"}, token)
check("a coordinator can issue an official", status, 201)
check("a coordinator cannot clone itself",
      call("/api/auth/issue", "POST",
           {"role": "coordinator", "holder": "Clone"}, token)[0], 403)
status, lead = call("/api/auth/redeem", "POST", {"code": HUB_LEAD})
lead_token = lead.get("token", "")
check("a hub lead cannot issue an official",
      call("/api/auth/issue", "POST",
           {"role": "official", "holder": "Nope"}, lead_token)[0], 403)
# Reading the agency channels is open for this demo
# (AGENCY_CHANNELS_PUBLIC_READ). What a hub lead still cannot do is POST into
# one, which is the control that matters.
check("a hub lead can read the agency channels (demo setting)",
      call("/api/chat/messages?channel=fenz", token=lead_token)[0], 200)
check("...but still cannot post into one",
      call("/api/chat/messages", "POST",
           {"channel_id": "fenz", "author_id": "lead",
            "body": "Posting as the fire service, which should be refused"},
           lead_token)[0], 403)

section("Moderation is visible, never silent")
status, moderator = call("/api/auth/redeem", "POST", {"code": MODERATOR})
mod_token = moderator.get("token", "")
check("a moderator can open the queue",
      call("/api/community/queue", token=mod_token)[0], 200)
check("a moderator cannot issue cards",
      call("/api/auth/issue", "POST", {"role": "verified", "holder": "x"}, mod_token)[0], 403)

section("Real data says how old it is")
status, real = call("/api/realtime")
check("live sources answered", status, 200)
gauges = real.get("gauges", [])
check("every gauge is stamped fresh or stale",
      all("fresh" in g and "at" in g for g in gauges))
stale = [g for g in gauges if not g["fresh"]]
if stale:
    notes.append(f"{len(stale)} gauge(s) correctly marked stale "
                 f"(oldest: {min(g['at'] for g in stale)[:10]})")
check("no stale reading is presented as current",
      all(g["fresh"] is False or (g.get("age_hours") or 0) <= 6 for g in gauges))

# ---------------------------------------------------------------------------

print("\n" + "=" * 62)
for note in notes:
    print(f"  note: {note}")
print(f"  {passed} passed, {len(failed)} failed   against {BASE}")
for f in failed:
    print(f"    FAILED: {f}")
print("=" * 62)
sys.exit(len(failed))
