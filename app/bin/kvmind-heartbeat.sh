#!/bin/bash
# ============================================================================
# KVMind Device Heartbeat
# Sends periodic heartbeat to KVMind backend, receives subscription + features.
# Manages tunnel token, messaging, and OTA based on server response.
# ============================================================================

set -euo pipefail

UID_FILE="/etc/kdkvm/device.uid"
CONFIG_FILE="/etc/kdkvm/config.yaml"
TOKEN_FILE="/etc/kdkvm/device.token"
TUNNEL_TOKEN_FILE="/etc/kdkvm/tunnel.token"
LOG_TAG="kvmind-heartbeat"

log() { logger -t "$LOG_TAG" "$*"; }

# Read device UID
if [[ ! -f "$UID_FILE" ]]; then
    log "No device UID file found, skipping heartbeat"
    exit 0
fi
DEVICE_UID=$(cat "$UID_FILE" | tr -d '[:space:]')
if [[ -z "$DEVICE_UID" ]]; then
    log "Empty device UID, skipping heartbeat"
    exit 0
fi

# Gather device info
get_mac() {
    for iface in eth0 end0 enp0s3 wlan0; do
        if [[ -f "/sys/class/net/$iface/address" ]]; then
            cat "/sys/class/net/$iface/address"
            return
        fi
    done
    echo "unknown"
}

MAC=$(get_mac)
IP=$(ip -4 addr show | grep -oP '(?<=inet\s)[\d.]+' | grep -v 127.0.0.1 | head -1 || echo "")
HOSTNAME=$(hostname 2>/dev/null || echo "unknown")
FW_VERSION=$(cat /etc/kdkvm/version 2>/dev/null || echo "0.2.2-beta")

# Read config values from YAML (lightweight grep-based, no python needed)
yaml_val() {
    grep -m1 "^[[:space:]]*$1:" "$CONFIG_FILE" 2>/dev/null | sed 's/^[^:]*:[[:space:]]*//' | tr -d '"' | tr -d "'" || true
}
CONFIGURED_BACKEND=$(yaml_val "backend_url")

# Backend URL: use configured URL (empty = no cloud, skip heartbeat)
if [[ -z "$CONFIGURED_BACKEND" ]]; then
    log "No backend_url configured — running in local/air-gapped mode, skipping heartbeat."
    exit 0
fi
BACKEND_URL="$CONFIGURED_BACKEND"

# Send heartbeat
PAYLOAD=$(cat <<EOF
{
    "uid": "$DEVICE_UID",
    "macAddress": "$MAC",
    "ipAddress": "$IP",
    "hostname": "$HOSTNAME",
    "firmwareVersion": "$FW_VERSION"
}
EOF
)

DEVICE_TOKEN=""
if [[ -f "$TOKEN_FILE" ]]; then
    DEVICE_TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")
fi
if [[ -z "$DEVICE_TOKEN" ]]; then
    log "No device token found (not registered yet), skipping heartbeat"
    exit 0
fi

RESPONSE=$(curl -s --max-time 10 \
    -X POST \
    -H "Content-Type: application/json" \
    -H "X-Device-Token: $DEVICE_TOKEN" \
    -d "$PAYLOAD" \
    "$BACKEND_URL/api/devices/heartbeat" 2>/dev/null) || {
    log "Heartbeat failed (network error)"
    exit 0
}

# Parse response
CODE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code',0))" 2>/dev/null || echo "0")
if [[ "$CODE" != "200" ]]; then
    log "Heartbeat rejected: $RESPONSE"
    exit 0
fi

# Extract response data
# R4-C2: 新增 customerCleared + deletionRequestId 两行，老版本服务器返回
# 没有这些字段时默认 false/空，保持向后兼容。
RESP_DATA=$(echo "$RESPONSE" | python3 -c "
import sys,json
d=json.load(sys.stdin).get('data',{})
plan=d.get('planType','community')
feat=d.get('features',{})
is_paid=plan in ('standard','pro')
is_pro=plan == 'pro'
tunnel_token=d.get('tunnelToken') or ''
# 用统一词汇：community/standard/pro
print(plan)
print('true' if feat.get('tunnel', is_paid) else 'false')
print('true' if feat.get('messaging', is_paid) else 'false')
print('true' if feat.get('ota', is_paid) else 'false')
print('true' if feat.get('scheduled_tasks', is_pro) else 'false')
print(feat.get('myclaw_limit', -1 if is_paid else 5))
print(feat.get('myclaw_daily_limit', -1 if is_paid else 20))
print(feat.get('myclaw_max_action_level', 3 if is_pro else 2 if is_paid else 1))
print(tunnel_token)
# R4-C2: GDPR chat wipe pull signal
print('true' if d.get('customerCleared') else 'false')
print(d.get('deletionRequestId') or '')
" 2>/dev/null || echo "community
false
false
false
false
5
20
1

false
")

PLAN_TYPE=$(echo "$RESP_DATA" | sed -n '1p')
FEAT_TUNNEL=$(echo "$RESP_DATA" | sed -n '2p')
FEAT_MESSAGING=$(echo "$RESP_DATA" | sed -n '3p')
FEAT_OTA=$(echo "$RESP_DATA" | sed -n '4p')
FEAT_SCHEDULED_TASKS=$(echo "$RESP_DATA" | sed -n '5p')
MYCLAW_LIMIT=$(echo "$RESP_DATA" | sed -n '6p')
MYCLAW_DAILY_LIMIT=$(echo "$RESP_DATA" | sed -n '7p')
MYCLAW_MAX_ACTION_LEVEL=$(echo "$RESP_DATA" | sed -n '8p')
TUNNEL_TOKEN=$(echo "$RESP_DATA" | sed -n '9p')
CUSTOMER_CLEARED=$(echo "$RESP_DATA" | sed -n '10p')
DELETION_REQUEST_ID=$(echo "$RESP_DATA" | sed -n '11p')
SYNCED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log "Heartbeat OK: plan=$PLAN_TYPE tunnel=$FEAT_TUNNEL messaging=$FEAT_MESSAGING ota=$FEAT_OTA scheduled_tasks=$FEAT_SCHEDULED_TASKS"

# Sync subscription to local server (updates in-memory config + config.yaml)
curl -s --max-time 5 -X POST "http://127.0.0.1:8765/api/subscription/sync" \
    -H "Content-Type: application/json" \
    -d "{
      \"plan\": \"$PLAN_TYPE\",
	      \"tunnel\": $FEAT_TUNNEL,
	      \"messaging\": $FEAT_MESSAGING,
	      \"ota\": $FEAT_OTA,
	      \"scheduled_tasks\": $FEAT_SCHEDULED_TASKS,
	      \"myclaw_limit\": $MYCLAW_LIMIT,
	      \"myclaw_daily_limit\": $MYCLAW_DAILY_LIMIT,
	      \"myclaw_max_action_level\": $MYCLAW_MAX_ACTION_LEVEL,
	      \"synced_at\": \"$SYNCED_AT\"
	    }" >/dev/null 2>&1 || log "Failed to sync subscription to local server"

# OTA updater timer: enable/disable based on subscription
if [[ "$FEAT_OTA" == "true" ]]; then
    systemctl enable kvmind-updater.timer 2>/dev/null || true
    systemctl start kvmind-updater.timer 2>/dev/null || true
else
    systemctl stop kvmind-updater.timer 2>/dev/null || true
    systemctl disable kvmind-updater.timer 2>/dev/null || true
fi

# Update tunnel token if changed
if [[ -n "$TUNNEL_TOKEN" ]]; then
    CURRENT_TOKEN=$(cat "$TUNNEL_TOKEN_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")
    if [[ "$CURRENT_TOKEN" != "$TUNNEL_TOKEN" ]]; then
        mount -o remount,rw / 2>/dev/null || true
        mkdir -p "$(dirname "$TUNNEL_TOKEN_FILE")"
        # P1-NEW: tunnel token is a Cloudflare bearer secret — restrict to root-only (0600)
        # so any other local user or compromised service can't exfiltrate it and pivot into the
        # tunnel. umask alone isn't reliable: redirection inherits whatever mode existed on the
        # replaced file, so chmod explicitly after write.
        echo "$TUNNEL_TOKEN" > "$TUNNEL_TOKEN_FILE"
        chmod 600 "$TUNNEL_TOKEN_FILE" 2>/dev/null || true
        mount -o remount,ro / 2>/dev/null || true
        log "Tunnel token updated, restarting cloudflared"
        # Enable and restart tunnel service
        systemctl enable kvmind-tunnel 2>/dev/null || true
        systemctl restart kvmind-tunnel 2>/dev/null || true
    fi
elif [[ -f "$TUNNEL_TOKEN_FILE" ]]; then
    # Server returned no tunnel token — remove local tunnel
    mount -o remount,rw / 2>/dev/null || true
    rm -f "$TUNNEL_TOKEN_FILE"
    mount -o remount,ro / 2>/dev/null || true
    systemctl stop kvmind-tunnel 2>/dev/null || true
    systemctl disable kvmind-tunnel 2>/dev/null || true
    log "Plan expired, tunnel removed"
fi

# ============================================================================
# R4-C2: GDPR chat wipe pull 模型
#
# 当服务器通过心跳告知 customerCleared=true 时：
#   1. 调用本地 bridge /api/internal/chat-wipe 触发 chat_store.wipe_for_uid()
#   2. 将结果 (成功/失败) 回调到云端 /api/subscription/wipe-chat/ack
# 任一步失败都只 log 不 exit — 下次心跳仍会再次触发，天然幂等。
# ============================================================================
if [[ "$CUSTOMER_CLEARED" == "true" ]] && [[ -n "$DELETION_REQUEST_ID" ]]; then
    log "Chat wipe requested (deletion_request_id=$DELETION_REQUEST_ID)"

    WIPE_SUCCESS="false"
    WIPE_ERROR=""

    # 1) 本地 bridge 触发擦除
    WIPE_RESPONSE=$(curl -s --max-time 15 -X POST \
        "http://127.0.0.1:8765/api/internal/chat-wipe" \
        -H "Content-Type: application/json" \
        -d "{\"deletionRequestId\": $DELETION_REQUEST_ID}" 2>/dev/null) || WIPE_RESPONSE=""

    WIPE_OK=$(echo "$WIPE_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('true' if d.get('ok') else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

    if [[ "$WIPE_OK" == "true" ]]; then
        WIPE_SUCCESS="true"
        log "Chat wipe local OK (deletion_request_id=$DELETION_REQUEST_ID)"
    else
        WIPE_ERROR=$(echo "$WIPE_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print((d.get('error') or d.get('message') or 'bridge returned unexpected payload')[:300])
except Exception:
    print('bridge unreachable or invalid JSON')
" 2>/dev/null || echo "bridge unreachable")
        log "Chat wipe local FAILED: $WIPE_ERROR"
    fi

    # 2) 回 ACK 到云端 (无论成功/失败都要报告，让云端 attempt_count 正确累加)
    ERROR_JSON=$(python3 -c "
import json, sys
print(json.dumps(sys.argv[1]))
" "$WIPE_ERROR" 2>/dev/null || echo '""')

    ACK_PAYLOAD="{\"deletionRequestId\": $DELETION_REQUEST_ID, \"success\": $WIPE_SUCCESS, \"errorMessage\": $ERROR_JSON}"

    ACK_RESPONSE=$(curl -s --max-time 10 -X POST \
        -H "Content-Type: application/json" \
        -H "X-Device-Token: $DEVICE_TOKEN" \
        -d "$ACK_PAYLOAD" \
        "$BACKEND_URL/api/subscription/wipe-chat/ack" 2>/dev/null) || {
        log "Chat wipe ACK network error (will retry next heartbeat)"
    }
    if [[ -n "${ACK_RESPONSE:-}" ]]; then
        ACK_CODE=$(echo "$ACK_RESPONSE" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('code', 0))
except Exception:
    print(0)
" 2>/dev/null || echo "0")
        if [[ "$ACK_CODE" == "200" ]]; then
            log "Chat wipe ACK accepted by server"
        else
            log "Chat wipe ACK rejected: $ACK_RESPONSE"
        fi
    fi
fi
