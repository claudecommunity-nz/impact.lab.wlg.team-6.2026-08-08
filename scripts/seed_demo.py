"""Seed a running Kitea with a believable Wellington demo scenario.

Usage:
    KITEA_OPS_KEY=<key> python3 scripts/seed_demo.py [http://127.0.0.1:8146]

Creates a spread of community reports around the city in different states,
so the ops dashboard and public page have something honest to show. Pure
HTTP client — exercises the same API the UI uses.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8146"
KEY = os.environ.get("KITEA_OPS_KEY", "")

REPORTS = [
    dict(category="flooding", place_name="Hutt Rd near Caltex, Petone",
         lat=-41.2270, lng=174.8712, reporter_role="resident",
         description="Water coming over the road from the stormwater drain, "
                     "about 10 cm deep and rising. Two cars have turned around."),
    dict(category="landslip", place_name="Ngaio Gorge Rd", lat=-41.2565, lng=174.7770,
         reporter_role="resident",
         description="Small slip has come down across one lane just below the "
                     "bend. Rocks still falling occasionally."),
    dict(category="tree-down", place_name="Karori Rd near the tunnel",
         lat=-41.2855, lng=174.7460, reporter_role="community-group",
         description="Large macrocarpa branch across the footpath and part of "
                     "the bus lane. Pedestrians stepping onto the road."),
    dict(category="blocked-drain", place_name="Onepu Rd, Lyall Bay",
         lat=-41.3270, lng=174.7950, reporter_role="resident",
         description="Grate fully blocked with leaves, big puddle spreading "
                     "across the intersection."),
    dict(category="power-lines", place_name="Severn St, Island Bay",
         lat=-41.3355, lng=174.7660, reporter_role="on-behalf",
         description="Reporting for my elderly neighbour: a line is hanging "
                     "low over her driveway after the wind last night."),
    dict(category="welfare-need", place_name="Newtown", lat=-41.3110, lng=174.7790,
         reporter_role="emergency-hub",
         description="Newtown hub: three households on our street have asked "
                     "about drinking water; mains pressure very low since 9am."),
    dict(category="flooding", place_name="Jackson St, Petone", lat=-41.2245, lng=174.8770,
         reporter_role="resident",
         description="Shop entrance flooding again, same as last month. "
                     "Sandbags holding for now."),
    dict(category="road-damage", place_name="Happy Valley Rd", lat=-41.3330, lng=174.7570,
         reporter_role="resident",
         description="New pothole opening up on the downhill side, deep enough "
                     "to damage a wheel."),
]

# ref index -> list of (status, note) taps to apply after creation
ADVANCE = {
    0: [("reviewing", "Duty officer has seen this; checking crew availability."),
        ("responding", "Roading crew on the way, ETA 20 minutes.")],
    1: [("reviewing", "Geotech advisor reviewing the photo now.")],
    2: [("reviewing", ""), ("responding", "Arborist crew dispatched."),
        ("resolved", "Branch cleared, footpath open again. Thanks for letting us know.")],
    3: [("reviewing", "")],
    5: [("reviewing", "Passed to Wellington Water; hub will be updated directly.")],
    6: [("reviewing", ""), ("responding", "Sandbags topped up; sucker truck booked.")],
}

# ref index -> verification note; these show as official on the public map
VERIFY = {
    0: "Roading crew on site confirmed water over both lanes.",
    2: "Arborist crew confirmed and cleared.",
    5: "Wellington Water confirmed low pressure in the area.",
}


def post(path: str, body: dict, with_key: bool = False) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"X-Kitea-Key": KEY} if with_key else {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> None:
    if not KEY:
        raise SystemExit("Set KITEA_OPS_KEY so the seed can advance statuses "
                         "(printed at server startup).")
    refs = []
    for i, r in enumerate(REPORTS):
        rep = post("/api/reports", r)
        refs.append(rep["ref"])
        print(f"created {rep['ref']}  {r['category']:15} {r['place_name']}")
        for status, note in ADVANCE.get(i, []):
            post(f"/api/reports/{rep['ref']}/status",
                 {"status": status, "note": note}, with_key=True)
            print(f"        -> {status}")
        if i in VERIFY:
            post(f"/api/reports/{rep['ref']}/verify",
                 {"note": VERIFY[i]}, with_key=True)
            print("        -> verified")
    print(f"\nSeeded {len(refs)} reports. Track the first one at {BASE}/?ref={refs[0]}")


if __name__ == "__main__":
    main()
