"""Unit tests for the feeds layer's pure logic: the timestamp, geometry and
CAP parsing helpers that encode this repo's hard-won data landmines, and the
cache's serve-stale-on-error behaviour. No network: builders are fakes.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from kitea import feeds


class TestReadingAge(unittest.TestCase):
    def test_fresh_utc_timestamp(self):
        t = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None)
        age = feeds._reading_age_s(t.isoformat(timespec="seconds"))
        self.assertAlmostEqual(age, 600, delta=60)

    def test_nz_local_timestamp_corrected(self):
        # Hilltop publishes naive NZ local time: a fresh reading looks ~12h
        # in the future when read as UTC and must come back as recent.
        t = (datetime.now(timezone.utc) + timedelta(hours=12)).replace(tzinfo=None)
        age = feeds._reading_age_s(t.isoformat(timespec="seconds"))
        self.assertLess(abs(age), 3600)

    def test_decommissioned_gauge_reads_old(self):
        # Wallaceville answered with 2013 data; it must never look fresh.
        age = feeds._reading_age_s("2013-05-29T15:00:00")
        self.assertGreater(age, 365 * 24 * 3600)

    def test_garbage_returns_none(self):
        self.assertIsNone(feeds._reading_age_s("not-a-time"))


class TestGeometry(unittest.TestCase):
    def test_point_in_bbox(self):
        self.assertTrue(feeds._in_bbox(174.78, -41.29))     # Wellington CBD
        self.assertFalse(feeds._in_bbox(172.64, -43.53))    # Christchurch
        self.assertFalse(feeds._in_bbox(None, -41.0))

    def test_multiline_geometry_touches(self):
        remutaka = {"type": "MultiLineString",
                    "coordinates": [[[175.15, -41.10], [175.20, -41.08]]]}
        chch = {"type": "MultiLineString",
                "coordinates": [[[172.5, -43.5], [172.6, -43.6]]]}
        self.assertTrue(feeds._geometry_touches_bbox(remutaka))
        self.assertFalse(feeds._geometry_touches_bbox(chch))
        self.assertFalse(feeds._geometry_touches_bbox(None))
        self.assertFalse(feeds._geometry_touches_bbox({"type": "Point"}))


class TestCapParsing(unittest.TestCase):
    def test_polygon_converts_latlon_to_geojson(self):
        rings = feeds._cap_polygon_geojson("-41.2,174.7 -41.3,174.8 -41.4,174.9 -41.2,174.7")
        self.assertEqual(rings[0][0], [174.7, -41.2])   # lng,lat order
        self.assertEqual(len(rings[0]), 4)

    def test_short_or_malformed_polygon_rejected(self):
        self.assertIsNone(feeds._cap_polygon_geojson("-41.2,174.7 -41.3,174.8"))
        self.assertIsNone(feeds._cap_polygon_geojson("-41.2,174.7 rubbish -41.4,174.9 -41.2,174.7"))

    def test_region_match_by_keyword_and_polygon(self):
        # RSS titles carry no placenames; region comes from areaDesc keywords
        # or the polygon touching the Wellington bbox.
        self.assertTrue(feeds._touches_region("Heavy rain for the Tararua Range", None))
        self.assertFalse(feeds._touches_region("The ranges of eastern Bay of Plenty", None))
        wellington_ring = [[[174.78, -41.29], [174.80, -41.30], [174.82, -41.28], [174.78, -41.29]]]
        self.assertTrue(feeds._touches_region("somewhere unnamed", wellington_ring))

    def test_dtd_refused(self):
        with self.assertRaises(ValueError):
            feeds._safe_xml('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "b">]><r>&a;</r>')
        root = feeds._safe_xml("<rss><item><title>ok</title></item></rss>")
        self.assertEqual(root.findtext("item/title"), "ok")


class TestCache(unittest.TestCase):
    def setUp(self):
        feeds._cache.pop("t-cache", None)
        feeds._cache_expiry.pop("t-cache", None)

    def test_serves_fresh_then_stale_on_upstream_error(self):
        calls = {"n": 0}

        def good():
            calls["n"] += 1
            return {"id": "t-cache", "items": [calls["n"]]}

        first = feeds._cached("t-cache", ttl=0, build=good)
        self.assertEqual(first["items"], [1])
        self.assertFalse(first["from_cache"])

        def broken():
            raise RuntimeError("upstream down")

        stale = feeds._cached("t-cache", ttl=0, build=broken)
        self.assertEqual(stale["items"], [1])       # last good payload survives
        self.assertTrue(stale["from_cache"])
        self.assertIn("upstream refresh failed", stale["error"])

    def test_error_with_no_cache_degrades_visibly(self):
        feeds._cache.pop("t-none", None)

        def broken():
            raise RuntimeError("no luck")

        out = feeds._cached("t-none", ttl=0, build=broken)
        self.assertEqual(out["items"], [])
        self.assertIn("no luck", out["error"])


if __name__ == "__main__":
    unittest.main()
