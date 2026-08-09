#!/usr/bin/env bash
# Launch the public Kitea demo: an ephemeral Hetzner VM behind a Cloudflare
# tunnel at https://kitea.bitn.co.nz — the same pattern as the event build's
# impact-lab.bitn.cloud (ephemeral box + remotely-managed tunnel).
#
# Prereqs (all already true on Jason's WSL box):
#   ~/.config/cloudflare/token-tunnel   CF token: Account:Cloudflare Tunnel Edit
#                                       + Zone:DNS Edit on bitn.co.nz
#   hcloud CLI authenticated            (~/.config/hcloud/cli.toml)
#   Hetzner SSH keys "jason" + "claude-deploy" registered
#
# Everything it creates is labelled project=impact-lab-wlg ephemeral=true.
# Teardown: hcloud server delete kitea-demo
#           + delete the kitea-demo tunnel and kitea CNAME in Cloudflare.

set -euo pipefail

CF_TOKEN=$(cat ~/.config/cloudflare/token-tunnel)
ACCT=3b107115fd480728e43ee7dd1ffcf742          # Belton Internal
ZONE=7049d4aeddb4ada95ede13c4493af822          # bitn.co.nz
HOSTNAME_FQDN=kitea.bitn.co.nz
REPO=https://github.com/claudecommunity-nz/impact.lab.wlg.team-6.2026-08-08
API=https://api.cloudflare.com/client/v4

say() { printf '\n== %s\n' "$*"; }

say "1/5 create (or reuse) the tunnel"
TUN_ID=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "$API/accounts/$ACCT/cfd_tunnel?name=kitea-demo&is_deleted=false" |
  python3 -c 'import json,sys;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
if [ -z "$TUN_ID" ]; then
  TUN_ID=$(curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" \
    -H "Content-Type: application/json" "$API/accounts/$ACCT/cfd_tunnel" \
    --data '{"name":"kitea-demo","config_src":"cloudflare"}' |
    python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["id"])')
fi
echo "tunnel id: $TUN_ID"

say "2/5 ingress: $HOSTNAME_FQDN -> localhost:8146"
curl -s -X PUT -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  "$API/accounts/$ACCT/cfd_tunnel/$TUN_ID/configurations" \
  --data "{\"config\":{\"ingress\":[
    {\"hostname\":\"$HOSTNAME_FQDN\",\"service\":\"http://localhost:8146\"},
    {\"service\":\"http_status:404\"}]}}" |
  python3 -c 'import json,sys;print("ingress ok:", json.load(sys.stdin)["success"])'

say "3/5 DNS CNAME kitea -> tunnel (proxied)"
EXISTING=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "$API/zones/$ZONE/dns_records?name=$HOSTNAME_FQDN" |
  python3 -c 'import json,sys;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
if [ -z "$EXISTING" ]; then
  curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
    "$API/zones/$ZONE/dns_records" \
    --data "{\"type\":\"CNAME\",\"name\":\"kitea\",\"content\":\"$TUN_ID.cfargotunnel.com\",\"proxied\":true,\"ttl\":1}" |
    python3 -c 'import json,sys;print("dns ok:", json.load(sys.stdin)["success"])'
else
  echo "dns record already present"
fi

say "4/5 boot the ephemeral box (cloud-init does the rest)"
RUN_TOKEN=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "$API/accounts/$ACCT/cfd_tunnel/$TUN_ID/token" |
  python3 -c 'import json,sys;print(json.load(sys.stdin)["result"])')

USERDATA=$(mktemp)
trap 'rm -f "$USERDATA"' EXIT
cat > "$USERDATA" <<EOF
#cloud-config
package_update: true
packages: [git, python3, curl, openssl]
runcmd:
  - curl -fsSL -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  - dpkg -i /tmp/cloudflared.deb
  - git clone $REPO /opt/kitea
  - openssl rand -hex 12 > /root/kitea-ops-key
  - chmod 600 /root/kitea-ops-key
  - |
    cat > /etc/systemd/system/kitea.service <<'UNIT'
    [Unit]
    Description=Kitea two-way community-council channel
    After=network-online.target
    Wants=network-online.target
    [Service]
    WorkingDirectory=/opt/kitea
    ExecStart=/bin/sh -c 'KITEA_OPS_KEY=\$(cat /root/kitea-ops-key) exec /usr/bin/python3 -m kitea --host 127.0.0.1 --port 8146'
    Restart=always
    RestartSec=3
    [Install]
    WantedBy=multi-user.target
    UNIT
  - systemctl daemon-reload
  - systemctl enable --now kitea
  - cloudflared service install $RUN_TOKEN
  - sleep 8
  - KITEA_OPS_KEY=\$(cat /root/kitea-ops-key) /usr/bin/python3 /opt/kitea/scripts/seed_demo.py http://127.0.0.1:8146 || true
EOF

# cpx11 is no longer orderable in sin (verified 2026-08-10); cpx22 matches
# the event box.
hcloud server create --name kitea-demo --type cpx22 --image debian-12 \
  --location sin --ssh-key jason --ssh-key claude-deploy \
  --label project=impact-lab-wlg --label ephemeral=true \
  --user-data-from-file "$USERDATA"

say "5/5 wait for the public path (cloud-init takes a few minutes)"
for i in $(seq 1 60); do
  if curl -fsS -m 10 "https://$HOSTNAME_FQDN/api/meta" >/dev/null 2>&1; then
    echo "LIVE: https://$HOSTNAME_FQDN/   (ops: /ops, key in /root/kitea-ops-key on the box)"
    exit 0
  fi
  sleep 10
done
echo "Not answering yet — check: hcloud server ssh kitea-demo 'journalctl -u kitea -u cloudflared --no-pager | tail -30'"
exit 1
