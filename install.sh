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
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo    "[KVMind] $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo    "  ⚠ $*"; }
err()   { echo -e "${RED}  ✗ $*${NC}"; }
step()  { echo -e "\n${GREEN}[$1/9] $2${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
DEVICE_IP=""
DEVICE_PASS="root"
RESET=0
# --keep-root-pw: skip step 9 (OS root password rotation). Use only when the
# operator has pre-provisioned a non-default root password externally — stock
# PiKVM/BliKVM images ship with root:root, which install.sh rotates by default.
KEEP_ROOT_PW=0
for arg in "$@"; do
    case "$arg" in
        # INTENTIONAL: accept both --reset and reset (back-compat + user habit).
        # Do NOT "normalize" to a single form — README and historical commands use reset.
        --reset|reset)
            RESET=1
            ;;
        --keep-root-pw)
            KEEP_ROOT_PW=1
            ;;
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

# P2 (2026-04-19) — version drift check. Runs only when executed from the
# developer workstation (i.e. the deploy/ sibling directory exists). On the
# device itself this path is absent, so the block is a no-op there.
if [[ -x "$SCRIPT_DIR/deploy/sync-version.sh" ]]; then
    if ! "$SCRIPT_DIR/deploy/sync-version.sh" --check >/dev/null 2>&1; then
        warn "Version references drifted from app/web/version.json; syncing"
        "$SCRIPT_DIR/deploy/sync-version.sh"
    fi
fi

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
    REMOTE_FLAGS=""
    [[ "$RESET" == "1" ]] && REMOTE_FLAGS="$REMOTE_FLAGS --reset"
    [[ "$KEEP_ROOT_PW" == "1" ]] && REMOTE_FLAGS="$REMOTE_FLAGS --keep-root-pw"
    $SSH_CMD "bash /run/kvmind_src/install.sh${REMOTE_FLAGS}"
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
    err "NanoKVM support is on the v0.4.x roadmap and not yet implemented."
    err "Currently supported: PiKVM V3/V4, BliKVM v4 (PiKVM OS)."
    err "Follow https://kvmind.com for NanoKVM release notes."
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

# 0.5.24: 不再吞 remount 失败——之前 `2>/dev/null || true` 让 PiKVM v3 上
# 偶发的 remount 失败被静默吞掉，脚本以为 / 是 rw 继续写文件，结果 chpasswd /
# rm /etc/kdkvm/* 全部失败但被 `|| true` 兜成"成功"。失败立刻报错才是正解。
# PiKVM v3 的 `rw` 命令包了 `mount -o remount,rw / && mount -o remount,rw /boot`
# 我们只需 / 即可（state.db 等都不在 /boot 上）。
if ! mount -o remount,rw / 2>/dev/null; then
    echo "[install.sh] FATAL: cannot remount / read-write." >&2
    echo "  On PiKVM v3, try: rw" >&2
    echo "  Then re-run this installer." >&2
    exit 1
fi

# Ensure filesystem is restored to read-only on exit (normal or error)
trap 'mount -o remount,ro / 2>/dev/null || true' EXIT

# ========================================================================
# RESET: wipe all device state so the next install is a true first-boot.
# Invoked by `install.sh --reset` or `install.sh reset`. Destroys:
# UID, state.db (OAuth tokens + AI keys + tunnel token), auth.json, AI
# memory DB, config.yaml, and Python venv. Legacy files from pre-M3.4
# installs (registration.secret / device.token / ai.env / tunnel.token)
# are cleaned up too. Cloud bindings become invalid — the user must
# re-activate on kvmind.com after reset.
# ========================================================================
if [[ "$RESET" == "1" ]]; then
    echo ""
    echo -e "${RED}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  RESET MODE — DESTRUCTIVE${NC}"
    echo -e "${RED}══════════════════════════════════════════════════════════════${NC}"
    echo    "  This will wipe all device state:"
    echo    "    - Device UID"
    echo    "    - state.json (AI keys, tunnel token, binding state)"
    echo    "    - Admin password (auth.json) and AI memory database"
    echo    "    - Local config (config.yaml)"
    echo    "    - Python virtualenv"
    echo    "  Existing cloud bindings will need to be re-done on kvmind.com."
    echo ""
    echo    "  Starting in 5 seconds — press Ctrl+C to abort."
    sleep 5

    # Stop services before wiping (they hold auth.json and memory.db open)
    systemctl stop kdkvm 2>/dev/null || true
    systemctl stop kdkvm-cloudflared 2>/dev/null || true
    systemctl stop kdkvm-updater.timer 2>/dev/null || true
    # Legacy unit names (pre-M3.4) — noop if absent
    systemctl stop kvmind 2>/dev/null || true
    systemctl stop kvmind-tunnel 2>/dev/null || true
    systemctl stop kvmind-heartbeat.timer 2>/dev/null || true
    systemctl stop kvmind-updater.timer 2>/dev/null || true
    systemctl stop kvmind-register.timer 2>/dev/null || true

    # M3.5 — state now lives in state.db. device.uid kept as a file since
    # it's the one stable identifier we want to survive reboot/reinstall.
    rm -f /etc/kdkvm/device.uid
    rm -f /etc/kdkvm/config.yaml

    # 0.5.25: state moved from SQLite (state.db + WAL/SHM sidecars) to atomic
    # JSON (state.json + transient .tmp). Wipe both so reset is clean whether
    # the device upgraded from <0.5.25 (legacy db) or installed fresh (json).
    rm -f /var/lib/kdkvm/state.json
    rm -f /var/lib/kdkvm/state.json.tmp
    # Legacy SQLite remnants (pre-0.5.25)
    rm -f /var/lib/kdkvm/state.db
    rm -f /var/lib/kdkvm/state.db-wal
    rm -f /var/lib/kdkvm/state.db-shm

    # Legacy file wipes (pre-M3.4) — no-ops on fresh devices but clean up
    # upgraded ones. Tokens / AI keys / bind secret / tunnel token all
    # moved into state.db.
    rm -f /etc/kdkvm/device.token
    rm -f /etc/kdkvm/registration.secret
    rm -f /etc/kdkvm/.registered
    rm -f /etc/kdkvm/ai.env
    rm -f /etc/kdkvm/tunnel.token

    # Wipe MSD-side state (auth.json, memory DB + its WAL/SHM sidecars)
    mount -o remount,rw /var/lib/kvmd/msd 2>/dev/null || true
    rm -f /var/lib/kvmd/msd/.kdkvm/auth.json
    rm -f /var/lib/kvmd/msd/.kdkvm/memory.db
    rm -f /var/lib/kvmd/msd/.kdkvm/memory.db-wal
    rm -f /var/lib/kvmd/msd/.kdkvm/memory.db-shm
    mount -o remount,ro /var/lib/kvmd/msd 2>/dev/null || true

    # Wipe Python venv — forces fresh pip install during deployment
    rm -rf /opt/kvmind/kdkvm/venv

    ok "Reset complete — continuing as first-boot install"
    echo ""
fi

# ========================================================================
# Pre-flight notice: OS root password rotation (step 9)
# ========================================================================
# Stock PiKVM / BliKVM ships with the well-known root:root credentials. Any
# device on the LAN can SSH in with that pair, so step 9 rotates root to a
# random 24-char passphrase on first boot. The new password is printed ONCE
# at the end of the install and not persisted on the device — losing it
# means re-flashing or HDMI/keyboard console reset.
#
# This pre-flight notice exists because `curl … | bash` users have no chance
# to read step 9's behaviour before it executes. Skip the notice when:
#   • --keep-root-pw is set (the operator already chose to retain root pw)
#   • the marker exists (rotation already happened on a previous install)
ROOT_PW_MARKER="/etc/kdkvm/.root-rotated"
if [[ "$KEEP_ROOT_PW" != "1" ]] && [[ ! -f "$ROOT_PW_MARKER" ]]; then
    echo ""
    echo -e "${YELLOW}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  NOTICE — OS root password will be rotated${NC}"
    echo -e "${YELLOW}══════════════════════════════════════════════════════════════${NC}"
    echo    "  This installer will replace the device's root password with a"
    echo    "  random 24-character passphrase (printed once at the end)."
    echo    "  Stock PiKVM / BliKVM ships with the public root:root default;"
    echo    "  first-boot rotation is the secure default."
    echo ""
    echo    "  Want to keep your existing root password? Press Ctrl+C now and"
    echo    "  rerun with --keep-root-pw:"
    echo    "    curl -sSL https://kvmind.com/install.sh | bash -s -- --keep-root-pw"
    echo ""
    echo    "  Continuing in 5 seconds..."
    sleep 5
    echo ""
fi

# ========================================================================
step 1 "Stopping services & cleaning old deployment"
# ========================================================================

# Stop services
systemctl stop kdkvm 2>/dev/null && ok "kdkvm stopped" || true
systemctl stop kdkvm-cloudflared 2>/dev/null || true
systemctl stop kdkvm-updater.timer 2>/dev/null || true
# Legacy names (pre-M3.4)
systemctl stop kvmind 2>/dev/null || true
systemctl stop kvmind-tunnel 2>/dev/null || true
systemctl stop kvmind-heartbeat.timer 2>/dev/null || true
systemctl stop kvmind-updater.timer 2>/dev/null || true
systemctl stop kvmind-register.timer 2>/dev/null || true
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
mkdir -p /etc/kdkvm/update.pub.d
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

# ── MyClaw Ed25519 verification key ──
# P0-14 v0.3.2: kdcms signs MyClaw actions with an Ed25519 private key and the
# device verifies with this public key. Without the pub key on disk, the
# device's gateway silently downgrades to "skip signature verification" — any
# LAN attacker who can reach /kdkvm/api/... could then inject HID actions.
#
# Packaging: release/build.sh embeds the current production pub key into
# app/keys/myclaw_verify.pub at tar time; a freshly-cloned dev tree may not
# have it, so we warn rather than fail when the file is absent in dev mode.
#
# Production: the pub key is rotated via OTA: a new release embeds the new
# key under a distinct key_id filename in update.pub.d/ + legacy update.pub
# stays as rollback fallback. See app/bin/kvmind-updater.sh for the rotation
# logic.
if [[ -f "$SCRIPT_DIR/app/keys/myclaw_verify.pub" ]]; then
    cp -f "$SCRIPT_DIR/app/keys/myclaw_verify.pub" /etc/kdkvm/myclaw_verify.pub
    chmod 644 /etc/kdkvm/myclaw_verify.pub
    ok "MyClaw verify key deployed: /etc/kdkvm/myclaw_verify.pub"
elif [[ -f /etc/kdkvm/myclaw_verify.pub ]]; then
    ok "MyClaw verify key preserved (from prior install): /etc/kdkvm/myclaw_verify.pub"
else
    warn "MyClaw verify key missing — signature verification will fail-closed in server.py"
    warn "  Dev tree: put the current pub key at \$REPO/dev/kdkvm/app/keys/myclaw_verify.pub"
    warn "  Prod: ensure release/build.sh embedded it, or copy from 1Password to /etc/kdkvm/myclaw_verify.pub"
fi

# ── Heartbeat Ed25519 verification key (R5-HB-01, 2026-04-26) ──
# 心跳响应权威字段（features/tunnelToken/customerCleared 等）由 kdcms 用独立
# Ed25519 私钥签名，设备端使用此公钥在落地 feature_flags.json 前验签。
# 缺失公钥时 device_keys.verify_heartbeat_response 返回 False，heartbeat.py
# 拒绝接受签名响应（保留旧 features），强制运维补齐。
if [[ -f "$SCRIPT_DIR/app/keys/heartbeat_verify.pub" ]]; then
    cp -f "$SCRIPT_DIR/app/keys/heartbeat_verify.pub" /etc/kdkvm/heartbeat_verify.pub
    chmod 644 /etc/kdkvm/heartbeat_verify.pub
    ok "Heartbeat verify key deployed: /etc/kdkvm/heartbeat_verify.pub"
elif [[ -f /etc/kdkvm/heartbeat_verify.pub ]]; then
    ok "Heartbeat verify key preserved (from prior install): /etc/kdkvm/heartbeat_verify.pub"
else
    warn "Heartbeat verify key missing — kdkvm will reject signed heartbeat responses"
    warn "  Dev tree: 在 kdcms deploy.sh 首次跑后，把 dev/kdcms/keys/heartbeat_verify.pub"
    warn "    复制到 dev/kdkvm/app/keys/heartbeat_verify.pub 并 commit + 重打 OTA 包"
    warn "  兼容期：kdcms 旧版本不签的响应会被设备端 warn-and-accept，迁移完成后必须修复"
fi

# ── OTA update-trust public keys ──
# P0-14 v0.3.2: kvmind-updater.sh fails closed when no trust root exists
# (app/bin/kvmind-updater.sh:228-240). Fan every update-trust-*.pub in the
# release package into /etc/kdkvm/update.pub.d/ so the updater can verify
# manifest.key_id → pub. Legacy /etc/kdkvm/update.pub is left untouched so
# existing installs keep their rollback fallback.
_update_pub_count=0
if ls "$SCRIPT_DIR"/app/keys/update-trust-*.pub >/dev/null 2>&1; then
    for _pub in "$SCRIPT_DIR"/app/keys/update-trust-*.pub; do
        _name=$(basename "$_pub")
        cp -f "$_pub" "/etc/kdkvm/update.pub.d/$_name"
        chmod 644 "/etc/kdkvm/update.pub.d/$_name"
        ok "OTA trust root deployed: /etc/kdkvm/update.pub.d/$_name"
        _update_pub_count=$((_update_pub_count + 1))
    done
fi
# Fail closed: if the package carried no trust root AND the device has none
# from a prior install, future OTA updates would brick with "pubkey missing".
# Catch that here while the user is still at the shell, not 3 AM during a
# hotfix rollout.
if (( _update_pub_count == 0 )); then
    if ! ls /etc/kdkvm/update.pub.d/*.pub >/dev/null 2>&1 && [[ ! -f /etc/kdkvm/update.pub ]]; then
        err "No OTA trust root deployed. Package missing app/keys/update-trust-*.pub and device has no prior keys. kvmind-updater would fail closed on every upgrade. Rebuild the package on a machine that has release/keys/ populated."
    else
        ok "OTA trust root preserved (from prior install): /etc/kdkvm/update.pub.d/"
    fi
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

# P0-10 v0.3.2: pip failure must NOT be silently swallowed. aiohttp / PyYAML /
# cryptography are hard runtime deps; without them kdkvm.service crashes with
# ImportError on first start and the user has no clue why (journalctl shows
# only "exit 1"). Previously `2>/dev/null || warn` hid network/TLS errors.
if ! /opt/kvmind/kdkvm/venv/bin/pip install --quiet aiohttp aiofiles PyYAML pydantic cryptography; then
    err "pip install FAILED — kdkvm cannot start without aiohttp/PyYAML/pydantic/cryptography."
    err "Common causes:"
    err "  - No network (PiKVM overlay fs may lose DNS mid-install; try 'mount -o remount,rw /' + 'systemctl restart systemd-resolved')"
    err "  - PyPI TLS cert fetch failed (check 'pip config get global.index-url')"
    err "  - /opt/kvmind/kdkvm/venv lacks ensurepip (rerun with 'rm -rf /opt/kvmind/kdkvm/venv' to recreate)"
    err "Re-run 'pip install -v aiohttp aiofiles PyYAML pydantic cryptography' to see the underlying error."
    exit 1
fi
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

# M3.5 — AI keys, device UID, bind secret have all moved out of bash:
#   - AI keys           → /var/lib/kdkvm/state.db (via setup page or kvmind.com)
#   - Device UID        → auto-created on first get_uid() call (Python, lib/uid.py)
#   - Registration secret → deleted (Device Code Flow replaces the bind secret)
# Any lingering legacy files are cleaned up below so a re-install on an
# older device doesn't leave confusing artifacts.
rm -f /etc/kdkvm/ai.env /etc/kdkvm/registration.secret /etc/kdkvm/.registered \
      /etc/kdkvm/device.token /etc/kdkvm/tunnel.token 2>/dev/null || true

# state.db lives on a writable ext4 partition that survives OTA — create
# it with the right perms before kdkvm.service opens it.
mkdir -p /var/lib/kdkvm
chmod 700 /var/lib/kdkvm

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

# M3.4 — remove legacy units (pre-M3.4) that were renamed or absorbed
for legacy in kvmind.service kvmind-register.service kvmind-register.timer \
              kvmind-tunnel.service kvmind-updater.service kvmind-updater.timer \
              kvmind-heartbeat.service kvmind-heartbeat.timer; do
    if [[ -f "/etc/systemd/system/$legacy" ]]; then
        systemctl disable "$legacy" 2>/dev/null || true
        rm -f "/etc/systemd/system/$legacy"
    fi
done

# Core unit + ancillary units
cp -f "$SCRIPT_DIR/systemd/kdkvm.service" /etc/systemd/system/
for svc in kdkvm-cloudflared.service kdkvm-updater.service kdkvm-updater.timer; do
    if [[ -f "$SCRIPT_DIR/systemd/$svc" ]]; then
        cp -f "$SCRIPT_DIR/systemd/$svc" /etc/systemd/system/
    fi
done

systemctl daemon-reload
systemctl enable kdkvm 2>/dev/null

# Install cloudflared if not present
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared..."
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
    ok "cloudflared $(cloudflared --version 2>&1 | head -1)"
else
    ok "cloudflared already installed"
fi

# Tunnel service — token lives in state.db (M3.4). kdkvm.service heartbeat
# loop writes tunnel_token on subscription sync and nudges cloudflared via
# `systemctl restart kdkvm-cloudflared`. Enable unconditionally; the service
# itself exits early if no token is present.
systemctl enable kdkvm-cloudflared 2>/dev/null || true
ok "kdkvm-cloudflared enabled (starts once kdkvm provides a tunnel token)"

# OTA updater timer (every 6h)
if [[ -f /etc/systemd/system/kdkvm-updater.timer ]]; then
    systemctl enable kdkvm-updater.timer 2>/dev/null
    systemctl start kdkvm-updater.timer 2>/dev/null || true
    ok "OTA update timer enabled (every 6h)"
fi

# M3.4 — heartbeat is an asyncio task inside kdkvm.service (no separate
# timer). Registration is user-driven via Device Code Flow (no timer).

# Enable PiKVM OLED (ships with PiKVM OS but preset: disabled — shows IP on front panel)
if systemctl cat kvmd-oled &>/dev/null; then
    systemctl enable kvmd-oled 2>/dev/null || true
    if systemctl start kvmd-oled 2>/dev/null; then
        ok "kvmd-oled enabled (front-panel OLED IP display)"
    else
        warn "kvmd-oled enabled but failed to start (OLED hardware missing?)"
    fi
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

# Patch mako template to disable HTTP/2 — nginx OSS 主线不支持 RFC 8441
# (WebSocket over HTTP/2)，开 http2 后浏览器 WS 升级会被 400 拒绝。同一 server
# block 不能重复 http2 directive，所以必须在 mako 源头改而不是 include 内覆盖。
# 幂等：如果已经是 off 或已 patch 过，sed 不重复修改。
NGINX_MAKO="/etc/kvmd/nginx/nginx.conf.mako"
if [[ -f "$NGINX_MAKO" ]]; then
    if grep -q '^[[:space:]]*http2 on;' "$NGINX_MAKO"; then
        cp -n "$NGINX_MAKO" "${NGINX_MAKO}.pre-kvmind"
        sed -i 's|^\([[:space:]]*\)http2 on;|\1http2 off;  # kdkvm: nginx OSS 不支持 WS over HTTP/2|' "$NGINX_MAKO"
        ok "nginx mako template: http2 on → http2 off (RFC 8441 不被 nginx OSS 支持)"
    else
        ok "nginx mako template: http2 already off (no patch needed)"
    fi
else
    warn "nginx mako template not found at $NGINX_MAKO — skipping http2 patch"
fi

# ========================================================================
step 8 "Starting services"
# ========================================================================

systemctl restart kdkvm && ok "kdkvm started" || warn "kdkvm failed to start"
systemctl restart kvmd 2>/dev/null && ok "kvmd restarted (streamer config applied)" || warn "kvmd restart failed"
systemctl restart kvmd-nginx 2>/dev/null && ok "kvmd-nginx restarted" || warn "kvmd-nginx restart failed"

# M3.4 — cloudflared needs a token in state.db. kdkvm's heartbeat loop
# writes it on subscription sync once the user activates via
# kvmind.com/activate. Probe via the kdkvm CLI; non-empty output == ready.
if /opt/kvmind/kdkvm/venv/bin/python -m lib.cli tunnel-token 2>/dev/null | grep -q .; then
    systemctl restart kdkvm-cloudflared && ok "kdkvm-cloudflared started" \
        || warn "kdkvm-cloudflared failed to start"
else
    info "kdkvm-cloudflared: waiting for paid seat — see kvmind.com/activate (claim this device first)"
fi

# V1 Seat model: registration no longer blocks install. kdkvm boots in
# unclaimed + local_free state. To bind to an account, click "Link device to
# account" on the Setup page to get a claim_code, then enter it at
# kvmind.com/activate. If a free Standard/Pro seat is available it auto-
# assigns; otherwise the device stays in claimed_free.

# Wait and verify
sleep 2
# `systemctl is-active` exits non-zero for inactive/failed/unknown states
# while still printing the state string to stdout. Using `|| true` instead
# of `|| echo "..."` prevents the fallback string from being appended and
# producing double-line values (e.g. "inactive\ninactive").
KDKVM_STATUS=$(systemctl is-active kdkvm 2>/dev/null || true)
NGINX_STATUS=$(systemctl is-active kvmd-nginx 2>/dev/null || true)
TUNNEL_STATUS=$(systemctl is-active kdkvm-cloudflared 2>/dev/null || true)

# ========================================================================
step 9 "Rotating OS root password (first-boot only)"
# ========================================================================
# Stock PiKVM / BliKVM images ship with root:root — anyone on the same LAN
# can SSH in and pivot. On the first successful install we swap the OS root
# password for a random 24-char passphrase and print it once in the summary.
# A marker at $ROOT_PW_MARKER prevents rotation on re-runs (that would break
# the password the operator has already recorded) and `--keep-root-pw`
# skips the whole step for provisioning pipelines that manage root out of
# band. This step intentionally runs AFTER services start so a failure
# earlier in the install doesn't leave the device locked behind an unknown
# password while also broken.

# ROOT_PW_MARKER is defined earlier (pre-flight notice block) so both checks
# read the same path.
INIT_ROOT_PASSWORD=""
if [[ "$KEEP_ROOT_PW" == "1" ]]; then
    info "Skipped (--keep-root-pw)"
elif [[ -f "$ROOT_PW_MARKER" ]]; then
    ok "Already rotated previously (marker: $ROOT_PW_MARKER)"
elif [[ "$KDKVM_STATUS" != "active" ]]; then
    warn "kdkvm is not active — deferring root password rotation to next install"
else
    # 24 chars from [A-Za-z0-9] ≈ 143 bits of entropy; no shell-metacharacter
    # chars so we never have to quote-escape this anywhere downstream.
    INIT_ROOT_PASSWORD=$(/opt/kvmind/kdkvm/venv/bin/python -c "
import secrets, string
alpha = string.ascii_letters + string.digits
print(''.join(secrets.choice(alpha) for _ in range(24)))
" 2>/dev/null || true)
    if [[ -z "$INIT_ROOT_PASSWORD" ]]; then
        warn "Failed to generate a password — root unchanged"
    elif echo "root:$INIT_ROOT_PASSWORD" | chpasswd 2>/dev/null; then
        touch "$ROOT_PW_MARKER"
        chmod 600 "$ROOT_PW_MARKER"
        ok "Root password rotated (recorded in summary below)"
    else
        warn "chpasswd failed — root password unchanged"
        INIT_ROOT_PASSWORD=""
    fi
fi

# ========================================================================
# Summary
# ========================================================================

echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  KVMind installation complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""

IP=$(ip -4 addr show | grep -oP '(?<=inet\s)[\d.]+' | grep -v 127.0.0.1 | head -1)
# device_uid lives in state.db (M3.3). CLI prints it via `status`.
DEVICE_UID=$(/opt/kvmind/kdkvm/venv/bin/python -m lib.cli status 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('device_uid') or 'N/A')" 2>/dev/null || echo 'N/A')

echo    "  Dashboard:  https://${IP:-<pikvm-ip>}/kvm/"
echo    "  MyClaw AI:  Panel on the right side of the dashboard"
echo ""
echo    "  Services:"
echo    "    kdkvm              ${KDKVM_STATUS}"
echo    "    kvmd-nginx         ${NGINX_STATUS}"
echo    "    kdkvm-cloudflared  ${TUNNEL_STATUS}"
echo ""

if [[ "$KDKVM_STATUS" != "active" ]]; then
    echo -e "${RED}  ⚠ kdkvm is not running! Check:${NC}"
    echo    "    journalctl -u kdkvm -n 20 --no-pager"
    echo ""
fi

# M3.5 — AI keys are entered through the setup panel (stored in state.db,
# encrypted at rest, never written to /etc/kdkvm/*). Nothing to check
# from bash; the setup panel signals status to the user directly.

echo    "  Logs:"
echo    "    journalctl -u kdkvm -f"
echo ""

# Verify deployment
echo    "  Deployed files:"
echo    "    lib/  $(ls /opt/kvmind/kdkvm/lib/*.py 2>/dev/null | wc -l || echo 0) modules"
echo    "    web/  $(ls /opt/kvmind/kdkvm/web/*.{js,html,css} 2>/dev/null | wc -l || echo 0) files"
if [[ -d /opt/kvmind/kdkvm/lib/innerclaw ]]; then
    echo "    innerclaw/  $(ls /opt/kvmind/kdkvm/lib/innerclaw/*.py 2>/dev/null | wc -l || echo 0) modules + $(ls /opt/kvmind/kdkvm/lib/innerclaw/adapters/*.py 2>/dev/null | wc -l || echo 0) adapters"
fi
echo ""

# M3.5 — Next steps panel. OAuth Device Code Flow replaces the old
# bind-secret UX: kdkvm.service boots, prints a user_code, and the user
# approves it at https://kvmind.com/activate. The setup page at
# https://<device-ip>/kvm/setup exposes the code visually too.
KDKVM_VERSION="__KDKVM_VERSION__"  # replaced by release/build.sh at package time

echo -e "${GREEN}┌─ Next step — activate this device ──────────────────────────────────┐${NC}"
echo -e "${GREEN}│${NC}"
echo    "│  KVMind Web Login (https://<device-ip>/kvm/)"
if [[ -n "${INIT_PASSWORD:-}" ]]; then
    echo    "│    Password:   ${INIT_PASSWORD}"
else
    echo    "│    Password:   (unchanged — existing password preserved)"
fi
echo -e "${GREEN}│${NC}"
echo    "│  Device UID:   ${DEVICE_UID}"
echo    "│  Version:      kdkvm-v${KDKVM_VERSION}"
echo -e "${GREEN}│${NC}"
echo    "│  1. Open  https://<device-ip>/setup.html  in a LAN browser."
echo    "│  2. Choose 'Start with Free' to use Free immediately, OR"
echo    "│     'Link device to account' to fetch a claim_code."
echo    "│  3. Visit  https://kvmind.com/activate  in any browser, sign in,"
echo    "│     and enter the claim_code to link this KVM to your account."
echo    "│     A paid Standard / Pro seat (if any) is auto-assigned."
echo -e "${GREEN}│${NC}"
echo    "│  The claim_code is short-lived (~10 min). If it expires,"
echo    "│  click 'Refresh claim code' on the setup page."
echo -e "${GREEN}│${NC}"
echo -e "${GREEN}└──────────────────────────────────────────────────────────────────────┘${NC}"
echo ""

# Loudly print the rotated OS root password once — this is the only place
# it appears. We don't persist it anywhere on the device; losing it means
# re-flashing or a physical console reset.
if [[ -n "${INIT_ROOT_PASSWORD:-}" ]]; then
    echo -e "${RED}┌─ IMPORTANT — new OS root password ───────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}"
    echo    "│  The default root:root credentials were just rotated. All future"
    echo    "│  SSH / scp / deploy.sh invocations against this device must use:"
    echo -e "${RED}│${NC}"
    echo    "│      root@${IP:-<device>}  ${INIT_ROOT_PASSWORD}"
    echo -e "${RED}│${NC}"
    echo    "│  This password is NOT stored on the device. Save it in your"
    echo    "│  password manager now — if lost you must re-flash the SD card or"
    echo    "│  reset via HDMI/keyboard console."
    echo -e "${RED}│${NC}"
    echo -e "${RED}└──────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
fi

# Note: trap EXIT handles remount ro automatically
