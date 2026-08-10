"""API lifecycle tests: the acknowledgment loop, validation, and the ops
boundary. Runs the real server on an ephemeral port with a temp database —
no mocks of business behaviour, and no network beyond localhost (feeds and
hazard enrichment are simply not exercised: test reports carry no lat/lng
unless the test wants the enrichment thread, which talks to real GIS and
is out of scope here).

Run from the repo root:
    python3 -m unittest discover tests -v
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

os.environ.setdefault("KITEA_OPS_KEY", "test-ops-key")
os.environ.setdefault("KITEA_RATE_LIMIT", "1000")
os.environ["KITEA_DATA_DIR"] = tempfile.mkdtemp(prefix="kitea-test-")

from kitea import server, store  # noqa: E402

KEY = os.environ["KITEA_OPS_KEY"]

# A 1x1 valid PNG for photo-path tests.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg==")


def _request(method: str, path: str, body: dict | None = None,
             key: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{TestKitea.port}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"X-Kitea-Key": key} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


class TestKitea(unittest.TestCase):
    httpd: ThreadingHTTPServer
    port: int

    @classmethod
    def setUpClass(cls):
        store.init(server.DATA_DIR / "kitea.db")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    # -- the acknowledgment loop --------------------------------------------

    def test_report_lifecycle(self):
        status, rep = _request("POST", "/api/reports", {
            "category": "flooding",
            "description": "Water over the road, rising",
            "place_name": "Petone",
        })
        self.assertEqual(status, 201)
        ref = rep["ref"]
        self.assertRegex(ref, r"^WGN-[A-Z2-9]{8}$")
        # received fires automatically, no human involved
        self.assertEqual(rep["status"], "received")
        self.assertEqual(rep["history"][0]["status"], "received")
        self.assertEqual(rep["history"][0]["actor"], "system")

        # ops taps through the vocabulary
        status, _ = _request("POST", f"/api/reports/{ref}/status",
                             {"status": "reviewing", "note": "On it"}, key=KEY)
        self.assertEqual(status, 201)
        status, _ = _request("POST", f"/api/reports/{ref}/status",
                             {"status": "resolved", "note": "All clear"}, key=KEY)
        self.assertEqual(status, 201)

        # reporter sees the full trail through possession of the code alone
        status, view = _request("GET", f"/api/reports/{ref}")
        self.assertEqual(status, 200)
        self.assertEqual(view["status"], "resolved")
        self.assertEqual([e["status"] for e in view["history"]],
                         ["received", "reviewing", "resolved"])
        self.assertNotIn("contact", view)  # never echoed, even to the reporter

    def test_validation_rejected(self):
        for bad in (
            {"category": "volcano", "description": "made-up category"},
            {"category": "flooding", "description": ""},
            {"category": "flooding", "description": "x" * 2001},
            {"category": "flooding", "description": "ok", "lat": 95, "lng": 174},
        ):
            status, body = _request("POST", "/api/reports", bad)
            self.assertEqual(status, 400, bad)
            self.assertIn("error", body)

    def test_unknown_ref_404_and_guessing_throttled(self):
        status, _ = _request("GET", "/api/reports/WGN-ZZZZ9")
        self.assertEqual(status, 404)
        # the ref code is the credential; repeated misses must hit a wall
        last = 404
        for _ in range(35):
            last, _ = _request("GET", "/api/reports/WGN-ZZZZ9")
            if last == 429:
                break
        self.assertEqual(last, 429)

    def test_bad_status_rejected(self):
        _, rep = _request("POST", "/api/reports",
                          {"category": "other", "description": "test row"})
        status, _ = _request("POST", f"/api/reports/{rep['ref']}/status",
                             {"status": "closed"}, key=KEY)
        self.assertEqual(status, 400)

    # -- the ops boundary -----------------------------------------------------

    def test_ops_endpoints_require_key(self):
        _, rep = _request("POST", "/api/reports",
                          {"category": "other", "description": "private things",
                           "contact": "021 000 0000"})
        ref = rep["ref"]
        for method, path, body in (
            ("POST", f"/api/reports/{ref}/status", {"status": "reviewing"}),
            ("GET", "/api/ops/reports", None),
            ("GET", f"/api/ops/reports/{ref}", None),
        ):
            status, _ = _request(method, path, body)
            self.assertEqual(status, 401, path)
            status, _ = _request(method, path, body, key="wrong-key")
            self.assertEqual(status, 401, path)
            status, _ = _request(method, path, body, key=KEY)
            self.assertIn(status, (200, 201), path)

    def test_public_list_is_sanitised(self):
        _, rep = _request("POST", "/api/reports", {
            "category": "flooding",
            "description": "my phone is 021 123 456",
            "contact": "021 123 456",
        })
        status, data = _request("GET", "/api/reports")
        self.assertEqual(status, 200)
        row = next(r for r in data["reports"] if r["public_id"] == rep["public_id"])
        # the ref is the reporter's credential and must NEVER appear publicly
        for private_field in ("ref", "description", "contact", "photo", "hazard"):
            self.assertNotIn(private_field, row)

    def test_verify_flow(self):
        _, rep = _request("POST", "/api/reports",
                          {"category": "flooding", "description": "verify me",
                           "place_name": "Petone"})
        ref, pid = rep["ref"], rep["public_id"]
        self.assertFalse(rep["verified"])

        # verification is an ops act
        status, _ = _request("POST", f"/api/reports/{ref}/verify", {})
        self.assertEqual(status, 401)
        status, event = _request("POST", f"/api/reports/{ref}/verify",
                                 {"note": "Crew confirmed on site"}, key=KEY)
        self.assertEqual(status, 201)
        self.assertEqual(event["public_id"], pid)

        # the public item shows verified + a times-only timeline, no notes
        status, item = _request("GET", f"/api/items/{pid}")
        self.assertEqual(status, 200)
        self.assertTrue(item["verified"])
        self.assertNotIn("ref", item)
        self.assertIn("verified", [t["status"] for t in item["timeline"]])
        for t in item["timeline"]:
            self.assertNotIn("note", t)

        # the reporter sees the verification in their own history
        _, view = _request("GET", f"/api/reports/{ref}")
        self.assertIn("verified", [e["status"] for e in view["history"]])

    def test_verified_not_a_lifecycle_status(self):
        _, rep = _request("POST", "/api/reports",
                          {"category": "other", "description": "status guard"})
        status, _ = _request("POST", f"/api/reports/{rep['ref']}/status",
                             {"status": "verified"}, key=KEY)
        self.assertEqual(status, 400)

    # -- comms + access (roles) ----------------------------------------------

    def test_comms_lifecycle_and_roles(self):
        # an admin key issues a comms key and a duty key
        status, comms_user = _request("POST", "/api/ops/users",
                                      {"name": "Comms Casey", "role": "comms"}, key=KEY)
        self.assertEqual(status, 201)
        comms_key = comms_user["key"]
        self.assertTrue(comms_key.startswith("KOPS-"))
        _, duty_user = _request("POST", "/api/ops/users",
                                {"name": "Duty Dana", "role": "duty"}, key=KEY)
        duty_key = duty_user["key"]

        # comms role posts an update; duty role may not
        post_body = {"title": "Boil water notice: Karori", "comms_type": "other",
                     "body": "Until further notice, boil tap water in Karori.",
                     "lat": -41.2865, "lng": 174.74, "expires_in_h": 24}
        status, _ = _request("POST", "/api/ops/comms", post_body, key=duty_key)
        self.assertEqual(status, 403)
        status, post = _request("POST", "/api/ops/comms", post_body, key=comms_key)
        self.assertEqual(status, 201)
        self.assertEqual(post["author"], "Comms Casey")
        cid = post["public_id"]
        self.assertRegex(cid, r"^C[A-Z2-9]{6}$")

        # it is publicly visible while active
        _, pub = _request("GET", "/api/comms")
        self.assertIn(cid, [c["public_id"] for c in pub["comms"]])

        # comms role cannot touch reports; duty can
        _, rep = _request("POST", "/api/reports",
                          {"category": "other", "description": "role boundary"})
        status, _ = _request("POST", f"/api/reports/{rep['ref']}/status",
                             {"status": "reviewing"}, key=comms_key)
        self.assertEqual(status, 403)
        status, event = _request("POST", f"/api/reports/{rep['ref']}/status",
                                 {"status": "reviewing"}, key=duty_key)
        self.assertEqual(status, 201)
        self.assertEqual(event["actor"], "Duty Dana")  # named audit trail

        # withdraw removes it from the public list but not the record
        status, _ = _request("POST", f"/api/ops/comms/{cid}/withdraw", {}, key=comms_key)
        self.assertEqual(status, 200)
        _, pub = _request("GET", "/api/comms")
        self.assertNotIn(cid, [c["public_id"] for c in pub["comms"]])
        _, all_comms = _request("GET", "/api/ops/comms", key=KEY)
        row = next(c for c in all_comms["comms"] if c["public_id"] == cid)
        self.assertIsNotNone(row["withdrawn_at"])
        self.assertEqual(row["withdrawn_by"], "Comms Casey")

    def test_user_management_is_admin_only_and_revocable(self):
        _, made = _request("POST", "/api/ops/users",
                           {"name": "Field Frank", "role": "duty"}, key=KEY)
        frank_key = made["key"]

        # non-admin roles cannot mint keys (no automated promotion path)
        status, _ = _request("POST", "/api/ops/users",
                             {"name": "Sneaky", "role": "admin"}, key=frank_key)
        self.assertEqual(status, 403)
        status, _ = _request("GET", "/api/ops/users", key=frank_key)
        self.assertEqual(status, 403)

        # the key works until revoked, then dies
        status, _ = _request("GET", "/api/ops/reports", key=frank_key)
        self.assertEqual(status, 200)
        status, _ = _request("POST", f"/api/ops/users/{made['user']['id']}/revoke",
                             {}, key=KEY)
        self.assertEqual(status, 200)
        status, _ = _request("GET", "/api/ops/reports", key=frank_key)
        self.assertEqual(status, 401)

    def test_offers_flow_and_visibility(self):
        _, rep = _request("POST", "/api/reports",
                          {"category": "tree-down", "description": "big branch down",
                           "place_name": "Karori"})
        pid, ref = rep["public_id"], rep["ref"]

        status, out = _request("POST", f"/api/items/{pid}/offer",
                               {"kind": "equipment", "text": "I have a chainsaw, two streets away",
                                "contact": "021 555 000"})
        self.assertEqual(status, 201)
        self.assertEqual(out["offer_count"], 1)

        # rejected inputs
        status, _ = _request("POST", f"/api/items/{pid}/offer",
                             {"kind": "magic", "text": "nope"})
        self.assertEqual(status, 400)
        status, _ = _request("POST", "/api/items/KZZZZZZ/offer",
                             {"kind": "hands", "text": "hello there"})
        self.assertEqual(status, 404)

        # public sees the count only; reporter sees text but never contact;
        # ops sees everything
        _, item = _request("GET", f"/api/items/{pid}")
        self.assertEqual(item["offer_count"], 1)
        _, view = _request("GET", f"/api/reports/{ref}")
        self.assertEqual(view["offers"][0]["text"],
                         "I have a chainsaw, two streets away")
        self.assertNotIn("contact", view["offers"][0])
        _, ops_view = _request("GET", f"/api/ops/reports/{ref}", key=KEY)
        self.assertEqual(ops_view["offers"][0]["contact"], "021 555 000")

    def test_emergency_mode_is_admin_only(self):
        _, made = _request("POST", "/api/ops/users",
                           {"name": "Duty Mo", "role": "duty"}, key=KEY)
        status, _ = _request("POST", "/api/ops/mode",
                             {"mode": "emergency"}, key=made["key"])
        self.assertEqual(status, 403)
        status, out = _request("POST", "/api/ops/mode",
                               {"mode": "emergency"}, key=KEY)
        self.assertEqual(status, 200)
        _, meta = _request("GET", "/api/meta")
        self.assertEqual(meta["mode"], "emergency")
        _request("POST", "/api/ops/mode", {"mode": "normal"}, key=KEY)
        _, meta = _request("GET", "/api/meta")
        self.assertEqual(meta["mode"], "normal")

    def test_metrics_requires_ops_and_reports_counters(self):
        status, _ = _request("GET", "/api/metrics")
        self.assertEqual(status, 401)
        status, m = _request("GET", "/api/metrics", key=KEY)
        self.assertEqual(status, 200)
        self.assertGreater(m["requests_total"], 0)
        self.assertIn("reports", m)
        self.assertIn("sse_clients", m)

    def test_honeypot_rejects_form_bots(self):
        status, _ = _request("POST", "/api/reports", {
            "category": "other", "description": "I am a bot",
            "website": "http://spam.example"})
        self.assertEqual(status, 400)
        _, rep = _request("POST", "/api/reports",
                          {"category": "other", "description": "offer target"})
        status, _ = _request("POST", f"/api/items/{rep['public_id']}/offer",
                             {"kind": "hands", "text": "bot offer",
                              "website": "x"})
        self.assertEqual(status, 400)

    def test_rate_buckets_use_real_visitor_ip_behind_tunnel(self):
        # Behind the tunnel every socket peer is Cloudflare; identity must
        # come from Cf-Connecting-Ip or the buckets collapse into one.
        import urllib.request as _u
        def miss(ip):
            req = _u.Request(
                f"http://127.0.0.1:{self.port}/api/reports/WGN-GUESSNOT",
                headers={"Cf-Connecting-Ip": ip})
            try:
                _u.urlopen(req, timeout=10)
                return 200
            except _u.HTTPError as exc:  # noqa: F841
                return exc.code
        # visitor A exhausts THEIR miss budget
        last = 404
        for _ in range(35):
            last = miss("203.0.113.7")
            if last == 429:
                break
        self.assertEqual(last, 429)
        # visitor B is unaffected
        self.assertEqual(miss("203.0.113.8"), 404)

    # -- photo handling -------------------------------------------------------

    def test_photo_magic_bytes_enforced(self):
        ok = base64.b64encode(PNG_1PX).decode()
        status, rep = _request("POST", "/api/reports", {
            "category": "other", "description": "with photo", "photo_b64": ok})
        self.assertEqual(status, 201)
        self.assertTrue(rep["photo"].endswith(".png"))

        evil = base64.b64encode(b"<script>alert(1)</script>").decode()
        status, body = _request("POST", "/api/reports", {
            "category": "other", "description": "not a photo", "photo_b64": evil})
        self.assertEqual(status, 400)
        self.assertIn("JPEG, PNG or WebP", body["error"])

    def test_uploads_path_traversal_blocked(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/uploads/%2e%2e/kitea.db")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertIn(status, (403, 404))


if __name__ == "__main__":
    unittest.main()
