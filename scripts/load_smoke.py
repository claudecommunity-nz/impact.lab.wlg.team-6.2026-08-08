"""Load smoke: pin the server's PILOT-SCALE envelope and trip on
regression. 300 requests at 20-concurrent must complete with zero errors,
p95 under 800 ms and throughput over 60 req/s.

Context for those numbers: the stdlib threaded server is GIL-bound, so a
20-concurrent burst tails around ~600 ms p95 at ~120 req/s on modest
hardware while sequential latency is ~2 ms. A suburb-scale pilot peaks at
single-digit requests/second, so this is 25-100x headroom; the documented
scaling path beyond pilot is multiple processes behind the tunnel or a
WSGI server, not a rewrite.

The server runs in a SEPARATE process: generator and server sharing one
interpreter measures GIL contention in the harness, not the server (the
first version of this script did exactly that: sequential p50 was 1.8 ms
while in-process "load" showed a 700 ms p95 that vanished across a
process boundary).

    python3 scripts/load_smoke.py
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TOTAL = 300
CONCURRENCY = 20
P95_BUDGET_MS = 800
MIN_THROUGHPUT_RPS = 60
PORT = 8199


def main() -> int:
    # --stress: 1000 requests at 100-concurrent against 2 workers
    # (SO_REUSEPORT), the measured scaling step past one interpreter.
    stress = "--stress" in sys.argv
    global TOTAL, CONCURRENCY, P95_BUDGET_MS, MIN_THROUGHPUT_RPS
    workers = "1"
    if stress:
        TOTAL, CONCURRENCY = 1000, 100
        P95_BUDGET_MS, MIN_THROUGHPUT_RPS = 2000, 100
        workers = "2"
    env = dict(os.environ,
               KITEA_OPS_KEY="load-smoke-key",
               KITEA_RATE_LIMIT="10000",
               KITEA_DATA_DIR=tempfile.mkdtemp(prefix="kitea-load-"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "kitea", "--port", str(PORT), "--workers", workers],
        cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=2).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise SystemExit("server never came up")

        # seed rows so the list endpoint does real work
        for i in range(25):
            req = urllib.request.Request(
                f"{base}/api/reports",
                data=json.dumps({"category": "other",
                                 "description": f"load row {i}"}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()

        # Generate load with curl PROCESSES: a threaded Python client shares
        # one GIL and measures its own contention (observed: server p50
        # 1.8 ms sequential, but a 20-thread urllib pool reported p95 870 ms).
        paths = ["/api/reports?limit=100", "/api/meta", "/api/health"]
        urls = "\n".join(f"{base}{paths[i % len(paths)]}" for i in range(TOTAL))
        t_start = time.perf_counter()
        out = subprocess.run(
            ["xargs", "-P", str(CONCURRENCY), "-n", "1",
             "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code} %{time_total}\n"],
            input=urls, capture_output=True, text=True, timeout=120)
        wall = time.perf_counter() - t_start
        times, errors = [], 0
        for line in out.stdout.splitlines():
            code, secs = line.split()
            if code != "200":
                errors += 1
            times.append(float(secs) * 1000)
        if errors or len(times) != TOTAL:
            print(f"FAIL: errors={errors} completed={len(times)}/{TOTAL}")
            return 1
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times) * 0.95)]
    print(f"requests={TOTAL} concurrency={CONCURRENCY} errors=0 "
          f"p50={p50:.1f}ms p95={p95:.1f}ms throughput={TOTAL / wall:.0f} req/s")
    if p95 > P95_BUDGET_MS:
        print(f"FAIL: p95 {p95:.1f}ms over budget {P95_BUDGET_MS}ms")
        return 1
    if TOTAL / wall < MIN_THROUGHPUT_RPS:
        print(f"FAIL: throughput under {MIN_THROUGHPUT_RPS} req/s")
        return 1
    print("LOAD SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
