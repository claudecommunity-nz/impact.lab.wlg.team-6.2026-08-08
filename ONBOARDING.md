# Kitea developer onboarding

One sitting gets you productive; the codebase is deliberately small.

## Run it

```bash
git clone https://github.com/jasonagnewnz/wcc-two-way-channel && cd wcc-two-way-channel
python3 -m kitea          # http://127.0.0.1:8146 (ops key printed)
KITEA_OPS_KEY=<key> python3 scripts/seed_demo.py http://127.0.0.1:8146
python3 -m unittest discover tests    # 180 tests, ~7s, no dependencies
```

Zero runtime dependencies is a hard rule: stdlib + vendored `wcc_gis.py`
+ vendored MapLibre/fonts. CI tooling (ruff, mypy, bandit, coverage,
playwright) never ships.

## The mental model

- `kitea/store.py`: SQLite, append-only events. The reference code
  (WGN-) is the reporter's CREDENTIAL and never appears on public
  surfaces; the public id (K-) carries no access. Never blur these.
- `kitea/server.py`: stdlib HTTP + roles (duty/comms/admin) + the SSE
  hub. Hub delivery rules are the credential boundary; the SQLite bus
  carries events across worker processes.
- `kitea/feeds.py`: agency data, proxied+cached, freshness-checked. The
  landmine catalogue lives in the docstrings; believe them.
- `kitea/web/`: two pages, no framework, textContent-only rendering.
- Design record: `docs/V2-DESIGN.md`. Ops: `docs/RUNBOOK.md`. Privacy:
  `docs/PRIVACY-REVIEW.md`. Commercial: `COMMERCIAL.md`.

## Non-negotiables (from CLAUDE.md, enforced by tests)

Append-only log; never present inference as fact; enrichment never
blocks a report; server decides permissions; 111 disclaimer stays;
escape everything rendered; card secrets are never signals.

## Deploy

`scripts/deploy_demo.sh` builds the whole demo stack from nothing.
Update = `git pull` + restart on the box; rollback = `scripts/rollback.sh <sha>`;
backups are automatic with restore drills (see RUNBOOK).
