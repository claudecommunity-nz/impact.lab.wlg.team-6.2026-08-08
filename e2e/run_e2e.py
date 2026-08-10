"""Browser end-to-end test: the whole loop through the real UI.

Drives headless Chromium (Playwright) against a freshly spawned server:
a resident dismisses the demo gate, places a pin, submits a report
through the drawer, lands on their tracking page; the public item page
takes an offer of help; the ops console unlocks, opens the report and
verifies it, and the verified badge appears.

Lives outside tests/ so unittest discovery (zero-dependency) never
imports Playwright; CI runs it as its own step:

    pip install playwright && playwright install --with-deps chromium
    python3 e2e/run_e2e.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parent.parent
PORT = 8197
BASE = f"http://127.0.0.1:{PORT}"
OPS_KEY = "e2e-ops-key"


def wait_up() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=2).read()
            return
        except OSError:
            time.sleep(0.3)
    raise SystemExit("server never came up")


def main() -> int:
    env = dict(os.environ, KITEA_OPS_KEY=OPS_KEY, KITEA_RATE_LIMIT="1000",
               KITEA_DATA_DIR=tempfile.mkdtemp(prefix="kitea-e2e-"))
    proc = subprocess.Popen([sys.executable, "-m", "kitea", "--port", str(PORT)],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        with sync_playwright() as pw:
            # PLAYWRIGHT_CHROMIUM_PATH lets a host without Playwright's
            # bundled-browser deps (e.g. WSL) use its system chromium.
            exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
            browser = pw.chromium.launch(executable_path=exe) if exe \
                else pw.chromium.launch()
            # CI runners are slow; default 5s assertion timeout flakes on
            # dynamic content. 15s is patient without hiding a real hang.
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_default_timeout(15000)

            # ── resident: gate → place pin → drawer → submit → tracking
            page.goto(BASE, wait_until="domcontentloaded")
            expect(page.locator("#demo-gate")).to_be_visible()
            page.click("#gate-ok")
            expect(page.locator("#demo-gate")).to_be_hidden()

            # first-visit tour appears after the gate; step through and skip
            expect(page.locator("#tour")).to_be_visible()
            expect(page.locator("#tour-body")).to_contain_text("Welcome to Kitea")
            page.click("#tour-next")
            page.click("#tour-skip")
            expect(page.locator("#tour")).to_be_hidden()

            page.click("#btn-report-fab")
            expect(page.locator("#placing-banner")).to_be_visible()
            page.locator("#canvas-map").click(position={"x": 450, "y": 350})
            expect(page.locator("#drawer-wrap")).to_be_visible()

            page.locator('#category-chips .chip[data-value="flooding"]').click()
            page.fill("#description", "E2E: water over the road, rising")
            page.fill("#place-name", "E2E Test Street")
            page.click("#btn-submit")
            page.wait_for_url("**/?ref=*", timeout=15000)
            expect(page.locator("#track-heading")).to_contain_text("report is in")
            ref = page.locator("#track-ref").inner_text().strip()
            assert ref.startswith("WGN-"), ref
            expect(page.locator("#track-timeline")).to_contain_text("Received")

            # ── public item page: provenance + offer of help
            with urllib.request.urlopen(f"{BASE}/api/reports?limit=1", timeout=5) as r:
                pid = json.load(r)["reports"][0]["public_id"]
            public = browser.new_page(viewport={"width": 1280, "height": 900})
            public.set_default_timeout(15000)
            public.add_init_script("try{localStorage.setItem('kitea-tour-done','1')}catch(e){}")
            public.goto(f"{BASE}/?item={pid}", wait_until="domcontentloaded")
            public.click("#gate-ok")
            expect(public.locator(".item-detail .prov")).to_contain_text("community")
            public.select_option(".offer-form select", "equipment")
            public.fill(".offer-form textarea", "E2E: I have a pump nearby")
            public.click(".offer-send")
            expect(public.locator(".offer-thanks")).to_be_visible()
            # simulate WCC staff (demo) — sandboxed, must not change real status
            public.click(".sim-toggle")
            public.locator(".sim-btn", has_text="Acknowledged").click()
            expect(public.locator(".sim-log li")).to_be_visible()
            expect(public.locator(".sim-simlabel").first).to_contain_text("simulated")

            # ── ops: unlock → open report → verify → badge appears
            ops = browser.new_page(viewport={"width": 1400, "height": 900})
            ops.set_default_timeout(15000)
            ops.goto(f"{BASE}/ops", wait_until="domcontentloaded")
            ops.fill("#lock-key", OPS_KEY)
            ops.click("#lock-form button[type=submit]")
            expect(ops.locator("#workspace")).to_be_visible()
            ops.locator(".qcard", has_text="E2E Test Street").first.click()
            expect(ops.locator("#detail-body")).to_contain_text("water over the road")
            expect(ops.locator("#detail-body")).to_contain_text("I have a pump nearby")
            ops.locator(".verify-btn").click()
            expect(ops.locator("#detail-body .vbadge")).to_be_visible(timeout=10000)

            # ── the reporter's tracking page saw the verification live (SSE)
            expect(page.locator("#track-timeline")).to_contain_text(
                "Council verified", timeout=10000)

            # ── mobile: resident flow on a phone viewport
            mob = browser.new_page(viewport={"width": 390, "height": 844},
                                   is_mobile=True, has_touch=True)
            mob.set_default_timeout(15000)
            mob.add_init_script("try{localStorage.setItem('kitea-tour-done','1')}catch(e){}")
            mob.goto(BASE, wait_until="domcontentloaded")
            mob.click("#gate-ok")
            expect(mob.locator("#btn-report-fab")).to_be_visible()
            mob.click("#sheet-handle")          # collapse: maximum map
            expect(mob.locator("#panel-scroll")).to_be_hidden()
            mob.click("#sheet-handle")
            expect(mob.locator("#panel-scroll")).to_be_visible()
            mob.click("#btn-help-fab")          # ask for help preset
            # the "describe it instead of pinning" path — deterministic on
            # touch, where synthetic map-canvas taps are unreliable
            mob.click("#placing-banner")
            expect(mob.locator("#drawer-wrap")).to_be_visible()
            pressed = mob.locator('#category-chips .chip[aria-pressed="true"]')
            expect(pressed).to_have_attribute("data-value", "welfare-need")
            mob.fill("#description", "E2E mobile: neighbour needs water")
            mob.click("#btn-submit")
            mob.wait_for_url("**/?ref=*", timeout=15000)
            expect(mob.locator("#track-timeline")).to_contain_text("Received")

            browser.close()
        print("E2E OK: report -> track -> offer -> ops verify -> live update -> mobile")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
