"""Fixture-driven tests for the feed builders (no network: fetchers are
monkeypatched), the SSE hub's delivery rules (the credential boundary),
and static file serving.
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

os.environ.setdefault("KITEA_OPS_KEY", "test-ops-key")
os.environ.setdefault("KITEA_RATE_LIMIT", "1000")
os.environ.setdefault("KITEA_DATA_DIR", tempfile.mkdtemp(prefix="kitea-units-"))

import wcc_gis  # noqa: E402
from kitea import feeds, server, store  # noqa: E402


def _fresh(feed_id):
    feeds._cache.pop(feed_id, None)
    feeds._cache_expiry.pop(feed_id, None)


class TestFeedBuilders(unittest.TestCase):
    def setUp(self):
        self._get_json = feeds._get_json
        self._get_text = feeds._get_text
        self._sites = feeds.wcc_gis.hilltop_sites
        self._data = feeds.wcc_gis.hilltop_data
        self._features = feeds.wcc_gis.features

    def tearDown(self):
        feeds._get_json = self._get_json
        feeds._get_text = self._get_text
        feeds.wcc_gis.hilltop_sites = self._sites
        feeds.wcc_gis.hilltop_data = self._data
        feeds.wcc_gis.features = self._features

    def test_delays_filters_by_geometry_not_region_codes(self):
        _fresh("delays")
        feeds._get_json = lambda url: {"features": [
            {"geometry": {"type": "MultiLineString",
                          "coordinates": [[[175.15, -41.10], [175.2, -41.08]]]},
             "properties": {"EventType": "Road Closure", "EventDescription": "Wind",
                            "LocationArea": "SH2 Remutaka", "Impact": "Road closed",
                            "Status": "Active", "IsPlanned": 0,
                            "LastEdited": "2026-08-10", "regions": [16]}},
            {"geometry": {"type": "MultiLineString",
                          "coordinates": [[[172.5, -43.5], [172.6, -43.6]]]},
             "properties": {"EventType": "Road Work", "regions": [9]}},
        ]}
        out = feeds.delays()
        feats = out["geojson"]["features"]
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["properties"]["eventType"], "Road Closure")

    def test_quakes_window_and_links(self):
        _fresh("quakes")
        now = datetime.now(timezone.utc)
        feeds._get_json = lambda url: {"features": [
            {"geometry": {"coordinates": [174.8, -41.3]},
             "properties": {"publicID": "q1", "time": now.isoformat().replace("+00:00", "Z"),
                            "magnitude": 4.62, "depth": 22.4, "locality": "near Wellington", "mmi": 4}},
            {"geometry": {"coordinates": [174.8, -41.3]},
             "properties": {"publicID": "q2",
                            "time": (now - timedelta(days=8)).isoformat().replace("+00:00", "Z"),
                            "magnitude": 3.0, "depth": 10, "locality": "old", "mmi": 3}},
        ]}
        out = feeds.quakes()
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["magnitude"], 4.6)
        self.assertIn("geonet.org.nz/earthquake/q1", out["items"][0]["link"])

    def test_cameras_bbox_and_offline_flag(self):
        _fresh("cameras")
        feeds._get_json = lambda url: {"features": [
            {"geometry": {"coordinates": [174.78, -41.29]},
             "properties": {"Name": "CBD cam", "ImageUrl": "http://x/1.jpg",
                            "ThumbUrl": "t", "Offline": 0, "UnderMaintenance": 0}},
            {"geometry": {"coordinates": [174.79, -41.30]},
             "properties": {"Name": "Broken cam", "Offline": 1}},
            {"geometry": {"coordinates": [172.5, -43.5]},
             "properties": {"Name": "Chch cam", "Offline": 0}},
        ]}
        out = feeds.cameras()
        names = [i["name"] for i in out["items"]]
        self.assertEqual(names, ["CBD cam", "Broken cam"])
        self.assertTrue(out["items"][1]["offline"])

    def test_weather_uses_cap_xml_for_region_and_polygon(self):
        _fresh("weather")
        rss = """<rss><channel>
          <item><title>Heavy Rain Warning - Orange</title>
                <link>http://cap/wgtn</link><pubDate>today</pubDate></item>
          <item><title>Strong Wind Watch</title>
                <link>http://cap/bop</link><pubDate>today</pubDate></item>
        </channel></rss>"""
        cap = {"http://cap/wgtn": """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
            <info><event>rain</event><severity>Severe</severity><urgency>Immediate</urgency>
            <onset>2026-08-10T20:00:00+12:00</onset><expires>2026-08-11T04:00:00+12:00</expires>
            <area><areaDesc>Wellington</areaDesc>
            <polygon>-41.2,174.7 -41.3,174.8 -41.4,174.9 -41.2,174.7</polygon></area>
            </info></alert>""",
               "http://cap/bop": """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
            <info><event>wind</event><severity>Moderate</severity><urgency>Expected</urgency>
            <area><areaDesc>Bay of Plenty</areaDesc>
            <polygon>-37.9,176.9 -38.0,177.0 -38.1,177.1 -37.9,176.9</polygon></area>
            </info></alert>"""}

        def fake_text(url):
            if "alerts.metservice" in url:
                return rss
            return cap[url]

        feeds._get_text = fake_text
        out = feeds.weather()
        self.assertEqual(out["national_count"], 2)
        self.assertEqual(len(out["items"]), 1)
        item = out["items"][0]
        self.assertEqual(item["severity"], "severe")
        self.assertEqual(item["area"], "Wellington")
        self.assertEqual(item["polygon"][0][0], [174.7, -41.2])

    def test_hubs_reads_uppercase_fields(self):
        _fresh("hubs")
        feeds.wcc_gis.features = lambda *a, **k: [
            {"NAME": "Aro Valley Community Centre", "ADDRESS": "48 Aro St",
             "SUBURB": "Aro Valley", "TOWN": "Wellington",
             "lat": -41.296, "lng": 174.766}]
        out = feeds.hubs()
        self.assertEqual(out["items"][0]["name"], "Aro Valley Community Centre")
        self.assertIn("Aro Valley", out["items"][0]["address"])

    def test_gauges_freshness_trend_and_per_site_errors(self):
        _fresh("gauges")
        now_local = datetime.now(timezone.utc) + timedelta(hours=12)
        fresh_t = now_local.replace(tzinfo=None).isoformat(timespec="seconds")
        feeds.wcc_gis.hilltop_sites = lambda: [
            {"site": s, "lat": -41.2, "lng": 174.9} for s, _, _ in feeds.GAUGES]

        def fake_data(site, measurement, interval="PT6H"):
            if "Birchville" in site:
                raise wcc_gis.GisError("gauge offline")
            if measurement == "Rainfall":
                return [{"time": fresh_t, "value": 1.0, "units": "mm"},
                        {"time": fresh_t, "value": 2.5, "units": "mm"}]
            return [{"time": fresh_t, "value": 10.0, "units": "m³/sec"},
                    {"time": fresh_t, "value": 14.0, "units": "m³/sec"}]

        feeds.wcc_gis.hilltop_data = fake_data
        out = feeds.gauges()
        by_site = {i["site"]: i for i in out["items"]}
        taita = by_site["Hutt River at Taita Gorge"]
        self.assertTrue(taita["fresh"])
        self.assertEqual(taita["trend"], "rising")
        self.assertIn("error", by_site["Hutt River at Birchville"])
        rain = by_site["Kaiwharawhara Stream at Karori Reservoir"]
        self.assertEqual(rain["recent_total"], 3.5)


class TestHubDeliveryRules(unittest.TestCase):
    """The SSE hub is the credential boundary: reporter-targeted payloads
    must never reach the public broadcast and vice versa.
    """

    def collect(self, q):
        got = []
        try:
            while True:
                got.append(q.get_nowait())
        except queue.Empty:
            return got

    def test_targeting(self):
        hub = server.Hub()
        q_public = hub.subscribe(None, ops=False)
        q_reporter = hub.subscribe("WGN-AAAA2222", ops=False)
        q_other = hub.subscribe("WGN-BBBB3333", ops=False)
        q_ops = hub.subscribe(None, ops=True)

        hub.publish("status", {"ref": "WGN-AAAA2222", "note": "private"},
                    ref="WGN-AAAA2222")
        hub.publish("status", {"ref": "WGN-AAAA2222", "note": "private"},
                    ops_only=True)
        hub.publish("item-updated", {"public_id": "K123456"})

        self.assertEqual([e for e, _ in self.collect(q_public)], ["item-updated"])
        self.assertEqual([e for e, _ in self.collect(q_reporter)], ["status"])
        self.assertEqual(self.collect(q_other), [])
        self.assertEqual([e for e, _ in self.collect(q_ops)],
                         ["status", "item-updated"])

        hub.unsubscribe(q_public)
        hub.publish("item-updated", {"public_id": "K999999"})
        self.assertEqual(self.collect(q_public), [])


class TestCrossProcessBus(unittest.TestCase):
    """The independent review found SSE deliveries split across worker
    processes; the SQLite bus is the fix. Simulate two workers: hub A
    publishes, hub B drains the bus and its subscriber receives."""

    def test_bus_carries_events_between_hubs(self):
        store.init(server.DATA_DIR / "kitea.db")
        hub_a, hub_b = server.Hub(), server.Hub()
        q_public = hub_b.subscribe(None, ops=False)
        q_reporter = hub_b.subscribe("WGN-CROSSPROC", ops=False)
        cursor = store.bus_cursor()

        hub_a.publish("item-updated", {"public_id": "K777777"})
        hub_a.publish("status", {"ref": "WGN-CROSSPROC", "note": "x"},
                      ref="WGN-CROSSPROC")

        # the poller runs in another pid; simulate by draining with pid=-1
        real_pid = server.os.getpid
        server.os.getpid = lambda: -1
        try:
            new_cursor = server._drain_bus(hub_b, cursor)
        finally:
            server.os.getpid = real_pid
        self.assertGreater(new_cursor, cursor)

        import queue as q
        def collect(qq):
            out = []
            try:
                while True:
                    out.append(qq.get_nowait())
            except q.Empty:
                return out
        self.assertEqual([e for e, _ in collect(q_public)], ["item-updated"])
        self.assertEqual([e for e, _ in collect(q_reporter)], ["status"])


class TestStaticServing(unittest.TestCase):
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

    def fetch(self, path):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, "", b""

    def test_pages_and_assets(self):
        for path, ctype, marker in (
            ("/", "text/html", b"Kitea"),
            ("/ops", "text/html", b"Kitea Ops"),
            ("/static/kitea.css", "text/css", b"Fira Sans"),
            ("/static/app.js", "javascript", b"provenance"),
        ):
            status, got_type, body = self.fetch(path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, got_type, path)
            self.assertIn(marker, body, path)

    def test_missing_and_health(self):
        self.assertEqual(self.fetch("/static/nope.css")[0], 404)
        self.assertEqual(self.fetch("/nowhere")[0], 404)
        status, _, body = self.fetch("/api/health")
        self.assertEqual(status, 200)
        self.assertIn(b'"ok": true', body)


import urllib.error  # noqa: E402  (used in fetch)


class TestStreamAndPhotos(unittest.TestCase):
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

    def _post(self, path, payload, key=None):
        import json as _json
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     **({"X-Kitea-Key": key} if key else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, _json.load(r)
        except urllib.error.HTTPError as exc:
            import json as _json2
            return exc.code, _json2.loads(exc.read() or b"{}")

    def test_sse_stream_receives_targeted_event(self):
        _, rep = self._post("/api/reports",
                            {"category": "other", "description": "sse target"})
        ref = rep["ref"]
        got = {}

        def listen():
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/stream?ref={ref}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                lines = []
                for raw in resp:
                    line = raw.decode().strip()
                    lines.append(line)
                    if line.startswith("data:"):
                        got["lines"] = lines
                        return

        th = threading.Thread(target=listen, daemon=True)
        th.start()
        import time as _t
        _t.sleep(0.4)
        status, _ = self._post(f"/api/reports/{ref}/status",
                               {"status": "reviewing", "note": "sse check"},
                               key=os.environ["KITEA_OPS_KEY"])
        self.assertEqual(status, 201)
        th.join(timeout=8)
        self.assertIn("event: status", got.get("lines", []))

    def test_stream_rejects_malformed_ref(self):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/stream?ref=;drop", timeout=10)
            code = 200
        except urllib.error.HTTPError as exc:
            code = exc.code
        self.assertEqual(code, 400)

    def test_photo_variants(self):
        import base64
        webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBPVP8 fake").decode()
        status, rep = self._post("/api/reports", {
            "category": "other", "description": "webp photo", "photo_b64": webp})
        self.assertEqual(status, 201)
        self.assertTrue(rep["photo"].endswith(".webp"))
        # served back with containment
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/uploads/{rep['photo']}", timeout=10) as r:
            self.assertEqual(r.status, 200)

        status, body = self._post("/api/reports", {
            "category": "other", "description": "bad b64", "photo_b64": "!!not-base64!!"})
        self.assertEqual(status, 400)
        self.assertIn("base64", body["error"])

        riff_not_webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVEdata").decode()
        status, body = self._post("/api/reports", {
            "category": "other", "description": "wav not webp",
            "photo_b64": riff_not_webp})
        self.assertEqual(status, 400)

    def test_group_photos_stack(self):
        import base64
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
            "h6FO1AAAAABJRU5ErkJggg==")
        b64 = base64.b64encode(png).decode()
        refs = []
        for i in range(2):
            _, rep = self._post("/api/reports", {
                "category": "flooding", "description": f"stack {i}",
                "lat": -41.2000 + i * 0.0005, "lng": 174.9000,
                "photo_b64": b64})
            refs.append(rep["ref"])
        key = os.environ["KITEA_OPS_KEY"]
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/ops/reports/{refs[0]}",
            headers={"X-Kitea-Key": key})
        import json as _json
        with urllib.request.urlopen(req, timeout=10) as r:
            detail = _json.load(r)
        self.assertEqual(len(detail["group_photos"]), 2)


if __name__ == "__main__":
    unittest.main()
