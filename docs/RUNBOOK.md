# Kitea runbook: operating the demo deployment

Deployment: ephemeral Hetzner box `kitea-demo` (5.223.61.6, Debian 12)
running `kitea.service` (systemd) on 127.0.0.1:8146, exposed only via the
Cloudflare tunnel `kitea-demo` as https://kitea.bitn.co.nz. Zero public
ports on the origin.

## Service level objectives (pilot scale)

Defined against the measured envelope (load smoke in CI, 2026-08-10:
~125 req/s at 20-concurrent, p50 ~60 ms, p95 ~615 ms, zero errors).

| SLO | Target | Measured by |
|---|---|---|
| Availability | 99% monthly (demo), 99.5% for a pilot | `.github/workflows/uptime.yml` probes `/api/health` every 30 min; a failed run notifies watchers |
| Read latency | p95 under 800 ms at 20-concurrent | `scripts/load_smoke.py`, enforced in CI on every push |
| Error rate | 0 5xx under normal load | load smoke fails on any non-200 |
| Acknowledgment | `received` status is synchronous with submission | by construction (same transaction), covered by tests |
| Data loss window | 24 h max (daily backups) | `kitea-backup.timer`; restore drill on every backup run |

Scaling: `--workers N` runs N processes sharing the port via
SO_REUSEPORT. Measured 2026-08-10: 1 worker ~125 req/s (p95 ~600 ms at
20-concurrent); 2 workers 477 req/s with p95 13.7 ms at 100-concurrent,
zero errors (the stress tier in CI re-proves this every push). Prod runs
`--workers 2`. `/api/metrics` (ops key) exposes uptime, request count,
SSE clients and feed cache ages. Retention (privacy review IPP9) runs
daily in-process; counts appear in journald when anything is purged.

## Common operations

```bash
ssh root@5.223.61.6                                  # jason + claude-deploy keys
systemctl status kitea                               # service state
journalctl -u kitea --since -1h                      # request logs
curl -s localhost:8146/api/health                    # local health
cat /root/kitea-ops-key                              # bootstrap admin key
```

Deploy an update: `cd /opt/kitea && git pull --ff-only && systemctl restart kitea`,
then check `https://kitea.bitn.co.nz/api/health` from outside.

Roll back: `scripts/rollback.sh <good-sha>` from any machine with the SSH
key. It pins the box to that revision, restarts, and health-checks; the
box stays pinned until the next explicit deploy.

## Incidents

- **Site down, box up**: `systemctl status kitea`; if active, check the
  tunnel: `systemctl status cloudflared`, and the tunnel's health in the
  Cloudflare dashboard (Networking → Tunnels → kitea-demo).
- **Site down, box unreachable**: Hetzner console (`hcloud server list`,
  `hcloud server reboot kitea-demo`). The box is stateless apart from
  `/opt/kitea/data`; worst case, rebuild via `scripts/deploy_demo.sh`
  and restore the latest backup.
- **Restore from backup**: decrypt and verify first, then swap in:
  ```bash
  openssl enc -d -aes-256-cbc -pbkdf2 -in <archive>.enc \
      -out /tmp/restore.tar.gz -pass file:/root/kitea-backup-key
  python3 /opt/kitea/scripts/kitea_backup.py verify --archive /tmp/restore.tar.gz
  systemctl stop kitea
  tar -xzf /tmp/restore.tar.gz -C /opt/kitea/data.new && \
      mv /opt/kitea/data /opt/kitea/data.old && mv /opt/kitea/data.new /opt/kitea/data
  systemctl start kitea
  ```
  Offsite copies live on Jason's workstation under `~/backups/kitea/`
  (key in `.backup-key` there); the offsite decrypt+restore path was
  drilled 2026-08-10.
- **Compromised ops key**: revoke named keys in the Access tab (immediate).
  For the bootstrap key: `openssl rand -hex 12 > /root/kitea-ops-key` is not
  enough — it is read at service start from the systemd unit's env; edit
  `/etc/systemd/system/kitea.service`'s key file read, `daemon-reload`,
  restart. Named keys survive restarts (hashed in the DB).
- **Abuse/spam**: rate buckets throttle per IP (reports, offers, code
  guessing). For a determined flood, enable Cloudflare WAF/managed
  challenge on kitea.bitn.co.nz: the origin only sees tunnel traffic.

## Teardown

```bash
hcloud server delete kitea-demo
# then delete tunnel kitea-demo + the kitea CNAME in Cloudflare (bitn.co.nz)
```
