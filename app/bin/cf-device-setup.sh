#!/bin/bash
# KVMind Device Cloudflare Tunnel Setup (optional)
# Creates a tunnel for a specific device and configures DNS on your own Cloudflare zone.
#
# Usage:
#   export CF_API_TOKEN=...
#   export CF_ACCOUNT_ID=...
#   export CF_ZONE_ID=...
#   export CF_ROOT_DOMAIN=example.com   # your own domain managed by Cloudflare
#   ./cf-device-setup.sh <DEVICE_UID>
set -euo pipefail

# Read from environment or config — NEVER hardcode credentials here
CF_TOKEN="${CF_API_TOKEN:?ERROR: CF_API_TOKEN not set. Export it or add to /etc/kdkvm/config.yaml}"
ACCOUNT_ID="${CF_ACCOUNT_ID:?ERROR: CF_ACCOUNT_ID not set}"
ZONE_ID="${CF_ZONE_ID:?ERROR: CF_ZONE_ID not set}"
ROOT_DOMAIN="${CF_ROOT_DOMAIN:?ERROR: CF_ROOT_DOMAIN not set (e.g. example.com)}"
DEVICE_UID="${1:?ERROR: pass device UID as first argument}"
# Cloudflare hostnames are lowercase
HOSTNAME="$(echo "$DEVICE_UID" | tr '[:upper:]' '[:lower:]').${ROOT_DOMAIN}"

echo "Setting up tunnel for $DEVICE_UID → $HOSTNAME"

# 1. Create tunnel
echo "Creating tunnel..."
TUNNEL_RESULT=$(curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$DEVICE_UID\",\"tunnel_secret\":\"$(openssl rand -base64 32)\"}")

TUNNEL_ID=$(echo "$TUNNEL_RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['id'])" 2>/dev/null)
TUNNEL_TOKEN=$(echo "$TUNNEL_RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['token'])" 2>/dev/null)

if [[ -z "$TUNNEL_ID" || "$TUNNEL_ID" == "None" ]]; then
    echo "ERROR: Failed to create tunnel"
    echo "$TUNNEL_RESULT" | python3 -m json.tool 2>/dev/null || echo "$TUNNEL_RESULT"
    exit 1
fi

echo "Tunnel created: $TUNNEL_ID"

# 2. Configure tunnel ingress (route hostname to local HTTPS)
echo "Configuring tunnel ingress..."
curl -s -X PUT \
  "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"config\":{\"ingress\":[{\"hostname\":\"$HOSTNAME\",\"service\":\"https://localhost:443\",\"originRequest\":{\"noTLSVerify\":true}},{\"service\":\"http_status:404\"}]}}" | python3 -c "import sys,json;d=json.load(sys.stdin);print('Ingress:', 'OK' if d.get('success') else d)"

# 3. Add DNS CNAME record for this device
echo "Adding DNS record: $HOSTNAME → tunnel..."
DNS_RESULT=$(curl -s -X POST \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"CNAME\",\"name\":\"$HOSTNAME\",\"content\":\"${TUNNEL_ID}.cfargotunnel.com\",\"proxied\":true}")
echo "$DNS_RESULT" | python3 -c "import sys,json;d=json.load(sys.stdin);print('DNS:', 'OK' if d.get('success') else d.get('errors','?'))"

# Output
echo ""
echo "=== Results ==="
echo "Tunnel ID: $TUNNEL_ID"
echo "Tunnel Token: $TUNNEL_TOKEN"
echo "Hostname: $HOSTNAME"
echo ""
echo "Run on device:"
echo "  cloudflared --no-autoupdate tunnel run --token $TUNNEL_TOKEN"
