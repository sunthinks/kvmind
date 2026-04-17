#!/bin/bash
# ============================================================================
# KVMind One-Click Installer
# Supports: PiKVM V3/V4, BliKVM v4 (running PiKVM OS), NanoKVM (planned)
#
# This script performs a CLEAN deployment:
#   1. Detects hardware platform
#   2. Stops all services
#   3. Removes old code entirely
#   4. Deploys fresh from source
#   5. Preserves config (/etc/kdkvm/) and venv
#
# Usage:
#   ./install.sh <device-ip> [password]
#
# Or on-device:
#   scp -r kdkvm/ root@<device-ip>:/run/kvmind_src
#   ssh root@<device-ip> 'bash /run/kvmind_src/install.sh'
#
# For incremental code updates after initial install:
#   ./deploy/deploy.sh [device-ip] [password]
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info()  { echo    "[KVMind] $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo    "  ⚠ $*"; }
err()   { echo -e "${RED}  ✗ $*${NC}"; }
step()  { echo -e "\n${GREEN}[$1/8] $2${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
DEVICE_IP=""
DEVICE_PASS="root"
for arg in "$@"; do
    case "$arg" in
        -*) ;;
        *)
            if [[ -z "$DEVICE_IP" ]]; then
                DEVICE_IP="$arg"
            else
                DEVICE_PASS="$arg"
            fi
            ;;
    esac
done

# ── Remote mode: upload + run on device ────────────────────────────────
if [[ -n "$DEVICE_IP" ]]; then
    info "Remote install mode: $DEVICE_IP"

    if ! command -v sshpass &>/dev/null; then
        err "sshpass is required for remote install"
        err "Install: brew install sshpass / apt install sshpass"
        exit 1
    fi

    SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
    SSH_CMD="sshpass -p $DEVICE_PASS ssh $SSH_OPTS root@$DEVICE_IP"
    SCP_CMD="sshpass -p $DEVICE_PASS scp $SSH_OPTS -r"

    # Test connectivity
    if ! $SSH_CMD "echo ok" &>/dev/null; then
        err "Cannot connect to root@$DEVICE_IP"
        exit 1
    fi
    ok "SSH connectivity verified"

    # Remount rw for upload
    $SSH_CMD "mount -o remount,rw / 2>/dev/null || true"

    # Clean staging area
    $SSH_CMD "rm -rf /run/kvmind_src"

    info "Uploading source to device..."
    $SCP_CMD "$SCRIPT_DIR" root@$DEVICE_IP:/run/kvmind_src
    ok "Source uploaded"

    info "Running installer on device..."
    $SSH_CMD "bash /run/kvmind_src/install.sh"
    EXIT_CODE=$?

    # Clean up staging
    $SSH_CMD "rm -rf /run/kvmind_src" 2>/dev/null || true

    exit $EXIT_CODE
fi

# ── Local install (running on device) ────────────────────────────────

# ── Detect hardware platform ──
PLATFORM="unknown"
if [[ -f /usr/bin/kvmd ]] || command -v kvmd &>/dev/null; then
    # PiKVM OS detected (used by PiKVM V3/V4 and BliKVM with PiKVM OS)
    if grep -qi "blikvm" /etc/hostname 2>/dev/null; then
        PLATFORM="blikvm"
    else
        PLATFORM="pikvm"
    fi
elif [[ -f /etc/kvm/config ]] || [[ -d /opt/nanokvm ]]; then
    PLATFORM="nanokvm"
fi

if [[ "$PLATFORM" == "nanokvm" ]]; then
    err "NanoKVM support is planned but not yet implemented."
    err "Currently supported: PiKVM V3/V4, BliKVM"
    exit 1
fi

if [[ "$PLATFORM" == "unknown" ]]; then
    err "Unsupported hardware platform. KVMind supports:"
    err "  - PiKVM V3/V4 (Arch Linux ARM + kvmd)"
    err "  - BliKVM v4 (running PiKVM OS)"
    err "  - NanoKVM (planned, not yet supported)"
    err "Run this script on a supported KVM device or use: ./install.sh <device-ip>"
    exit 1
fi

info "KVMind Installer starting on $(hostname)"
info "Detected platform: $PLATFORM"
echo ""

# Enable read-write filesystem
mount -o remount,rw / 2>/dev/null || true

# Ensure filesystem is restored to read-only on exit (normal or error)
trap 'mount -o remount,ro / 2>/dev/null || true' EXIT

# ========================================================================
step 1 "Stopping services & cleaning old deployment"
# ========================================================================

# Stop services
systemctl stop kvmind 2>/dev/null && ok "kvmind stopped" || true
systemctl stop zeroclaw 2>/dev/null && ok "zeroclaw stopped" || true

# Remove old application code (preserve venv and config)
if [[ -d /opt/kvmind/kdkvm ]]; then
    # Preserve venv (expensive to rebuild)
    if [[ -d /opt/kvmind/kdkvm/venv ]]; then
        mv /opt/kvmind/kdkvm/venv /run/_kvmind_venv_backup
    fi
    # Preserve device config (auth.json)
    if [[ -d /opt/kvmind/kdkvm/config ]]; then
        mv /opt/kvmind/kdkvm/config /run/_kvmind_config_backup
    fi

    # Wipe old code
    rm -rf /opt/kvmind/kdkvm/lib
    rm -rf /opt/kvmind/kdkvm/bin
    rm -rf /opt/kvmind/kdkvm/web
    rm -f /opt/kvmind/kdkvm/*.py
    ok "Old application code removed"

    # Restore preserved items
    if [[ -d /run/_kvmind_venv_backup ]]; then
        mkdir -p /opt/kvmind/kdkvm
        mv /run/_kvmind_venv_backup /opt/kvmind/kdkvm/venv
    fi
    if [[ -d /run/_kvmind_config_backup ]]; then
        mkdir -p /opt/kvmind/kdkvm
        mv /run/_kvmind_config_backup /opt/kvmind/kdkvm/config
    fi
fi

# Remove legacy ZeroClaw service
if [[ -f /etc/systemd/system/zeroclaw.service ]]; then
    systemctl disable zeroclaw 2>/dev/null || true
    rm -f /etc/systemd/system/zeroclaw.service
    ok "Legacy ZeroClaw service removed"
fi

# Remove legacy ZeroClaw binary
rm -f /root/.cargo/bin/zeroclaw 2>/dev/null || true

ok "Clean slate ready"

# ========================================================================
step 2 "Installing system dependencies"
# ========================================================================

# Initialize pacman keyring if needed
if ! pacman-key --list-keys &>/dev/null 2>&1; then
    info "Initializing pacman keyring..."
    pacman-key --init
    pacman-key --populate archlinuxarm
fi

PACKAGES=(python python-pip python-virtualenv git curl)
MISSING=()
for pkg in "${PACKAGES[@]}"; do
    if ! pacman -Qi "$pkg" &>/dev/null 2>&1; then
        MISSING+=("$pkg")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    info "Installing: ${MISSING[*]}"
    pacman -Sy --noconfirm "${MISSING[@]}" 2>/dev/null || warn "Some packages may have failed"
fi
ok "System dependencies ready"

# ========================================================================
step 3 "Deploying application code"
# ========================================================================

# Create directory structure
mkdir -p /opt/kvmind/kdkvm/{bin,lib,web,config}
mkdir -p /etc/kdkvm
mkdir -p /var/log/kdkvm
mkdir -p /var/log/nginx

# Ensure directories survive reboot (PiKVM overlayfs)
mkdir -p /etc/tmpfiles.d
cat > /etc/tmpfiles.d/kvmind.conf << 'TMPFILES'
d /var/log/kdkvm 0755 root root -
d /var/log/nginx 0755 root root -
TMPFILES

# ── Backend: lib/ ──
cp -f "$SCRIPT_DIR/app/lib/"*.py /opt/kvmind/kdkvm/lib/

# ── Backend: lib/handlers/ (HTTP handler modules) ──
if [[ -d "$SCRIPT_DIR/app/lib/handlers" ]]; then
    mkdir -p /opt/kvmind/kdkvm/lib/handlers
    cp -f "$SCRIPT_DIR/app/lib/handlers/"*.py /opt/kvmind/kdkvm/lib/handlers/
    ok "Handler modules deployed"
fi

# ── Backend: lib/innerclaw/ (AI harness) ──
if [[ -d "$SCRIPT_DIR/app/lib/innerclaw" ]]; then
    mkdir -p /opt/kvmind/kdkvm/lib/innerclaw/adapters
    cp -f "$SCRIPT_DIR/app/lib/innerclaw/"*.py /opt/kvmind/kdkvm/lib/innerclaw/
    if [[ -d "$SCRIPT_DIR/app/lib/innerclaw/adapters" ]]; then
        cp -f "$SCRIPT_DIR/app/lib/innerclaw/adapters/"*.py /opt/kvmind/kdkvm/lib/innerclaw/adapters/
    fi
    ok "InnerClaw harness deployed"
fi

# ── Backend: lib/kvm/ (hardware abstraction) ──
if [[ -d "$SCRIPT_DIR/app/lib/kvm" ]]; then
    mkdir -p /opt/kvmind/kdkvm/lib/kvm
    cp -f "$SCRIPT_DIR/app/lib/kvm/"*.py /opt/kvmind/kdkvm/lib/kvm/
    ok "KVM backend abstraction deployed"
fi

# ── Backend: bin/ (shell scripts) ──
cp -f "$SCRIPT_DIR/app/bin/"* /opt/kvmind/kdkvm/bin/
chmod +x /opt/kvmind/kdkvm/bin/*

# ── Frontend: web/ ──
cp -f "$SCRIPT_DIR/app/web/"*.html /opt/kvmind/kdkvm/web/
cp -f "$SCRIPT_DIR/app/web/"*.js /opt/kvmind/kdkvm/web/
cp -f "$SCRIPT_DIR/app/web/"*.css /opt/kvmind/kdkvm/web/
cp -f "$SCRIPT_DIR/app/web/"*.json /opt/kvmind/kdkvm/web/
if [[ -d "$SCRIPT_DIR/app/web/static" ]]; then
    mkdir -p /opt/kvmind/kdkvm/web/static
    cp -rf "$SCRIPT_DIR/app/web/static/"* /opt/kvmind/kdkvm/web/static/
fi

# Deploy prompt files
if [[ -d "$SCRIPT_DIR/prompts" ]]; then
    mkdir -p /etc/kdkvm/prompts/intents
    cp -rf "$SCRIPT_DIR/prompts/"*.md /etc/kdkvm/prompts/ 2>/dev/null || true
    cp -rf "$SCRIPT_DIR/prompts/intents/"*.md /etc/kdkvm/prompts/intents/ 2>/dev/null || true
    ok "Prompt files deployed to /etc/kdkvm/prompts/"
fi

# SQLite database lives on MSD partition (p4, hidden dir to avoid kvmd MSD scanner)
mount -o remount,rw /var/lib/kvmd/msd 2>/dev/null || true
mkdir -p /var/lib/kvmd/msd/.kdkvm
# Migrate from old visible directory if exists
if [[ -d "/var/lib/kvmd/msd/kdkvm" ]]; then
    cp -an /var/lib/kvmd/msd/kdkvm/* /var/lib/kvmd/msd/.kdkvm/ 2>/dev/null || true
    rm -rf /var/lib/kvmd/msd/kdkvm
    ok "Migrated data from kdkvm/ to .kdkvm/ (hidden from kvmd MSD scanner)"
fi
mount -o remount,ro /var/lib/kvmd/msd 2>/dev/null || true
ok "SQLite DB path: /var/lib/kvmd/msd/.kdkvm/memory.db (MSD partition, persistent)"

ok "All application code deployed"

# ── Python virtualenv ──
if [[ ! -d /opt/kvmind/kdkvm/venv ]]; then
    info "Creating Python virtualenv..."
    python3 -m venv /opt/kvmind/kdkvm/venv
fi

/opt/kvmind/kdkvm/venv/bin/pip install --quiet aiohttp aiofiles PyYAML pydantic 2>/dev/null || \
    warn "Some pip packages may have failed (non-critical if kvmd provides them)"
ok "Python environment ready"

# ========================================================================
step 4 "Configuring KVMind"
# ========================================================================

# Config file (create only if missing — never overwrite user config)
if [[ ! -f /etc/kdkvm/config.yaml ]]; then
    cat > /etc/kdkvm/config.yaml << YAML
kvm:
  backend: "$PLATFORM"  # pikvm, blikvm, nanokvm
  transport: unix
  unix_socket: /run/kvmd/kvmd.sock
  host: localhost
  username: admin
  password: admin

ai:
  gemini_key: ""        # Gemini API Key (get from https://aistudio.google.com)
  # claude_key: ""      # Claude API Key (optional)

bridge:
  host: "127.0.0.1"
  port: 8765
  mode: suggest
  backend_url: "https://kvmind.com"
YAML
    ok "Config created: /etc/kdkvm/config.yaml (platform: $PLATFORM)"
else
    ok "Config preserved: /etc/kdkvm/config.yaml"
fi

# AI environment file (create only if missing)
# Keys can also be set here as env vars (takes priority over config.yaml)
if [[ ! -f /etc/kdkvm/ai.env ]]; then
    cat > /etc/kdkvm/ai.env << 'ENV'
# KVMind AI Keys — set here or in /etc/kdkvm/config.yaml
# Env vars take priority over config.yaml
GEMINI_API_KEY=
# ANTHROPIC_API_KEY=
ENV
    warn "AI key not set — edit /etc/kdkvm/ai.env or config.yaml"
else
    ok "AI env preserved: /etc/kdkvm/ai.env"
fi

# Device UID — preserve existing UID on re-install so the device keeps its identity
# across upgrades, migrations, and accidental install.sh re-runs. Only generate a fresh
# UID when none exists yet (first install) or the existing file is empty/unreadable.
# P1-NEW: previous version always regenerated the UID, which broke an already-registered
# device's binding to its customer account every time the user re-ran install.sh.
# Shape validation (KVM-AAAA-AAAA-AAAA): 4 × 4 uppercase-alphanumeric groups separated by '-'.
EXISTING_UID=""
if [[ -s /etc/kdkvm/device.uid ]]; then
    EXISTING_UID=$(tr -d '[:space:]' < /etc/kdkvm/device.uid)
fi
if [[ "$EXISTING_UID" =~ ^KVM(-[A-Z0-9]{4}){3}$ ]]; then
    UID_STR="$EXISTING_UID"
    ok "Device UID preserved: $UID_STR"
else
    if [[ -n "$EXISTING_UID" ]]; then
        warn "Existing device.uid is malformed ('$EXISTING_UID'), regenerating"
    fi
    UID_STR="KVM-$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Z0-9' | head -c 12 | sed 's/.\{4\}/&-/g;s/-$//')"
    echo "$UID_STR" > /etc/kdkvm/device.uid
    # Fresh UID ⇒ clear registration marker so the device re-registers with the new identity.
    rm -f /etc/kdkvm/.registered
    ok "Device UID: $UID_STR"
fi

# Registration secret — proves device ownership when binding to user account.
# Preserve on re-install so a device that's already bound doesn't lose its secret;
# only generate if missing or empty.
if [[ ! -s /etc/kdkvm/registration.secret ]]; then
    REG_SECRET=$(openssl rand -hex 32)
    echo "$REG_SECRET" > /etc/kdkvm/registration.secret
    chmod 600 /etc/kdkvm/registration.secret
    ok "Registration secret generated (needed for device binding)"
else
    # Ensure mode is tight even if the file was created by an older install.
    chmod 600 /etc/kdkvm/registration.secret 2>/dev/null || true
    ok "Registration secret preserved"
fi

# PiKVM streamer: always-on mode + quality settings
OVERRIDE_FILE="/etc/kvmd/override.yaml"
if ! grep -q 'forever: true' "$OVERRIDE_FILE" 2>/dev/null; then
    cat >> "$OVERRIDE_FILE" << 'YAML'

kvmd:
    streamer:
        forever: true
        quality: 95
        h264_bitrate:
            default: 20000
        h264_gop:
            default: 0
YAML
    ok "PiKVM streamer set to always-on mode with quality settings"
elif ! grep -q 'h264_bitrate' "$OVERRIDE_FILE" 2>/dev/null; then
    # Migration: already has forever: true but missing quality params
    cat >> "$OVERRIDE_FILE" << 'YAML'

kvmd:
    streamer:
        quality: 95
        h264_bitrate:
            default: 20000
        h264_gop:
            default: 0
YAML
    ok "PiKVM streamer quality settings updated (quality=95, 5000 kbps)"
else
    ok "PiKVM streamer already configured"
fi

# ========================================================================
step 5 "Initializing device authentication"
# ========================================================================

AUTH_FILE="/var/lib/kvmd/msd/.kdkvm/auth.json"
mount -o remount,rw /var/lib/kvmd/msd 2>/dev/null || true
# Migrate from legacy path if needed
if [[ ! -f "$AUTH_FILE" && -f "/opt/kvmind/kdkvm/config/auth.json" ]]; then
    cp /opt/kvmind/kdkvm/config/auth.json "$AUTH_FILE"
    chmod 600 "$AUTH_FILE"
    ok "auth.json migrated to MSD partition"
fi
if [[ ! -f "$AUTH_FILE" ]]; then
    INIT_PASSWORD=$(/opt/kvmind/kdkvm/venv/bin/python -c "
import sys, os
sys.path.insert(0, '/opt/kvmind/kdkvm')
from lib.auth_manager import init_auth
password = init_auth()
if password:
    print(password)
else:
    sys.exit(1)
" 2>&1) && {
        ok "Device password generated: $INIT_PASSWORD"
        echo ""
        echo    "  Please save this password securely."
        echo    "  You will be asked to change it on first login."
        echo ""
    } || warn "Auth init failed (non-critical, can run manually later)"
else
    ok "auth.json already exists, skipping"
fi
mount -o remount,ro /var/lib/kvmd/msd 2>/dev/null || true

# ========================================================================
step 6 "Installing systemd services"
# ========================================================================

cp -f "$SCRIPT_DIR/systemd/kvmind.service" /etc/systemd/system/

# Copy optional services if present
for svc in kvmind-register.service kvmind-register.timer kvmind-tunnel.service kvmind-updater.service kvmind-updater.timer kvmind-heartbeat.service kvmind-heartbeat.timer; do
    if [[ -f "$SCRIPT_DIR/systemd/$svc" ]]; then
        cp -f "$SCRIPT_DIR/systemd/$svc" /etc/systemd/system/
    fi
done

systemctl daemon-reload
systemctl enable kvmind 2>/dev/null

# Install cloudflared if not present
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared..."
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
    ok "cloudflared $(cloudflared --version 2>&1 | head -1)"
else
    ok "cloudflared already installed"
fi

# Enable tunnel service if token exists
if [[ -f /etc/kdkvm/tunnel.token ]]; then
    systemctl enable kvmind-tunnel 2>/dev/null
    ok "Tunnel service enabled"
else
    warn "No tunnel token found — tunnel will start after device provisioning"
fi

# Enable OTA updater timer
if [[ -f /etc/systemd/system/kvmind-updater.timer ]]; then
    systemctl enable kvmind-updater.timer 2>/dev/null
    systemctl start kvmind-updater.timer 2>/dev/null || true
    ok "OTA update timer enabled (every 6h)"
fi

# Enable heartbeat timer
if [[ -f /etc/systemd/system/kvmind-heartbeat.timer ]]; then
    systemctl enable kvmind-heartbeat.timer 2>/dev/null
    systemctl start kvmind-heartbeat.timer 2>/dev/null || true
    ok "Heartbeat timer enabled (every 60s)"
fi

# Enable registration timer (retries on boot if first attempt failed)
if [[ -f /etc/systemd/system/kvmind-register.timer ]]; then
    systemctl enable kvmind-register.timer 2>/dev/null
    ok "Registration timer enabled (on boot + every 6h)"
fi

ok "Services installed and enabled"

# ========================================================================
step 7 "Configuring nginx"
# ========================================================================

NGINX_CONF="/etc/kvmd/nginx/kvmd.ctx-server.conf"
if [[ -f "$NGINX_CONF" ]]; then
    # Backup original PiKVM config (only on first install)
    cp -n "$NGINX_CONF" "${NGINX_CONF}.pre-kvmind"

    # Always deploy latest nginx config
    cp -f "$SCRIPT_DIR/nginx/kvmd.ctx-server.conf" "$NGINX_CONF"

    # Inject KVM credentials from config.yaml into nginx config
    KVM_USER=$(python3 -c "import yaml; print(yaml.safe_load(open('/etc/kdkvm/config.yaml'))['kvm']['username'])" 2>/dev/null || echo admin)
    KVM_PASS=$(python3 -c "import yaml; print(yaml.safe_load(open('/etc/kdkvm/config.yaml'))['kvm']['password'])" 2>/dev/null || echo admin)
    KVM_AUTH_B64=$(echo -n "${KVM_USER}:${KVM_PASS}" | base64)
    sed -i "s|Basic YWRtaW46YWRtaW4=|Basic ${KVM_AUTH_B64}|" "$NGINX_CONF"
    ok "nginx config deployed (credentials injected)"
else
    warn "nginx config not found at $NGINX_CONF — PiKVM may not be fully set up"
fi

# ========================================================================
step 8 "Starting services"
# ========================================================================

systemctl restart kvmind && ok "kvmind started" || warn "kvmind failed to start"
systemctl restart kvmd 2>/dev/null && ok "kvmd restarted (streamer config applied)" || warn "kvmd restart failed"
systemctl restart kvmd-nginx 2>/dev/null && ok "kvmd-nginx restarted" || warn "kvmd-nginx restart failed"

if [[ -f /etc/kdkvm/tunnel.token ]]; then
    systemctl restart kvmind-tunnel && ok "kvmind-tunnel started" || warn "kvmind-tunnel failed to start"
fi

# Register device with cloud (first attempt — timer retries on failure)
info "Registering device with KVMind cloud..."
if bash /opt/kvmind/kdkvm/bin/kvmind-register.sh --force 2>&1; then
    ok "Device registered with cloud"
else
    warn "Cloud registration failed (will retry on next boot via timer)"
fi

# Wait and verify
sleep 2
# `systemctl is-active` exits non-zero for inactive/failed/unknown states
# while still printing the state string to stdout. Using `|| true` instead
# of `|| echo "..."` prevents the fallback string from being appended and
# producing double-line values (e.g. "inactive\ninactive").
KVMIND_STATUS=$(systemctl is-active kvmind 2>/dev/null || true)
NGINX_STATUS=$(systemctl is-active kvmd-nginx 2>/dev/null || true)
TUNNEL_STATUS=$(systemctl is-active kvmind-tunnel 2>/dev/null || true)

# ========================================================================
# Summary
# ========================================================================

echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  KVMind installation complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""

IP=$(ip -4 addr show | grep -oP '(?<=inet\s)[\d.]+' | grep -v 127.0.0.1 | head -1)
DEVICE_UID=$(cat /etc/kdkvm/device.uid 2>/dev/null || echo 'N/A')

echo    "  Dashboard:  https://${IP:-<pikvm-ip>}/kvm/"
echo    "  MyClaw AI:  Panel on the right side of the dashboard"
echo ""
echo    "  Services:"
echo    "    kvmind         ${KVMIND_STATUS}"
echo    "    kvmd-nginx     ${NGINX_STATUS}"
echo    "    kvmind-tunnel  ${TUNNEL_STATUS}"
echo ""

if [[ "$KVMIND_STATUS" != "active" ]]; then
    echo -e "${RED}  ⚠ kvmind is not running! Check:${NC}"
    echo    "    journalctl -u kvmind -n 20 --no-pager"
    echo ""
fi

# Check for any AI key configured
HAS_KEY=false
grep -q 'GEMINI_API_KEY=AIza' /etc/kdkvm/ai.env 2>/dev/null && HAS_KEY=true
grep -q 'ANTHROPIC_API_KEY=sk-ant-' /etc/kdkvm/ai.env 2>/dev/null && HAS_KEY=true
grep -q 'gemini_key:.*AIza' /etc/kdkvm/config.yaml 2>/dev/null && HAS_KEY=true
grep -q 'claude_key:.*sk-ant-' /etc/kdkvm/config.yaml 2>/dev/null && HAS_KEY=true
if [[ "$HAS_KEY" != "true" ]]; then
    echo    "  ⚠ Set your AI API key:"
    echo    "    nano /etc/kdkvm/config.yaml  (set ai.gemini_key)"
    echo    "    Or: nano /etc/kdkvm/ai.env  (set GEMINI_API_KEY)"
    echo    "    Then: systemctl restart kvmind"
    echo ""
fi

echo    "  Logs:"
echo    "    journalctl -u kvmind -f"
echo ""

# Verify deployment
echo    "  Deployed files:"
echo    "    lib/  $(ls /opt/kvmind/kdkvm/lib/*.py 2>/dev/null | wc -l || echo 0) modules"
echo    "    web/  $(ls /opt/kvmind/kdkvm/web/*.{js,html,css} 2>/dev/null | wc -l || echo 0) files"
if [[ -d /opt/kvmind/kdkvm/lib/innerclaw ]]; then
    echo "    innerclaw/  $(ls /opt/kvmind/kdkvm/lib/innerclaw/*.py 2>/dev/null | wc -l || echo 0) modules + $(ls /opt/kvmind/kdkvm/lib/innerclaw/adapters/*.py 2>/dev/null | wc -l || echo 0) adapters"
fi
echo ""

# ── Bind credentials — printed last so they are the final thing on screen ──
KDKVM_VERSION="__KDKVM_VERSION__"  # replaced by release/build.sh at package time
if [[ -f /etc/kdkvm/registration.secret ]]; then
    BIND_SECRET=$(cat /etc/kdkvm/registration.secret)
    echo -e "${GREEN}┌─ IMPORTANT — Save these credentials ────────────────────────────────┐${NC}"
    echo -e "${GREEN}│${NC}"
    echo    "│  KVMind Web Login (https://<device-ip>/kvm/)"
    if [[ -n "${INIT_PASSWORD:-}" ]]; then
        echo    "│    Password:   ${INIT_PASSWORD}"
    else
        echo    "│    Password:   (unchanged — existing password preserved)"
    fi
    echo -e "${GREEN}│${NC}"
    echo    "│  Device UID:   ${DEVICE_UID}"
    echo    "│  Bind Secret:  ${BIND_SECRET}"
    echo    "│  Version:      kdkvm-v${KDKVM_VERSION}"
    echo -e "${GREEN}│${NC}"
    echo    "│  Next step:  Go to kvmind.com → Dashboard → Add Device"
    echo    "│  Enter the Device UID and Bind Secret to link this KVM"
    echo    "│  to your account and enable remote access."
    echo -e "${GREEN}│${NC}"
    echo -e "${GREEN}│  ${RED}⚠  Screenshot or copy these now.${NC}"
    echo    "│  Reinstalling kdkvm generates a new Bind Secret — the old one"
    echo    "│  will stop working and you will need to re-bind on kvmind.com."
    echo -e "${GREEN}│${NC}"
    echo -e "${GREEN}└──────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
else
    if [[ -n "${INIT_PASSWORD:-}" ]]; then
        echo    "  Web login password: ${INIT_PASSWORD}"
    fi
    echo    "  Device UID:   ${DEVICE_UID}"
    echo    "  Version:      kdkvm-v${KDKVM_VERSION}"
    echo ""
fi

# Note: trap EXIT handles remount ro automatically
