#!/usr/bin/env bash
# Roll the live Kitea box back to a known-good revision and prove health.
#   scripts/rollback.sh <sha-or-tag>
# Note: revisions before v0.3 predate /api/health, so the check reports
# failure against them (drilled 2026-08-10); use a v0.3+ sha, or verify
# /api/meta by hand for anything older.
set -euo pipefail

REV="${1:?usage: rollback.sh <sha-or-tag>}"
BOX=root@5.223.61.6

echo "== pinning /opt/kitea to $REV"
ssh -o BatchMode=yes "$BOX" "cd /opt/kitea && git fetch origin && git checkout --detach $REV && systemctl restart kitea && sleep 2 && systemctl is-active kitea"

echo "== public health check"
for i in $(seq 1 10); do
  if curl -fsS -m 10 https://kitea.bitn.co.nz/api/health | grep -q '"ok": true'; then
    echo "ROLLBACK OK: live on $REV"
    exit 0
  fi
  sleep 3
done
echo "ROLLBACK FAILED: health not answering; investigate via runbook"
exit 1
