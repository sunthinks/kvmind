#!/bin/bash
# ============================================================================
# KVMind KVM (kdkvm) — Quick Deploy
# Pushes code, config, and services to a PiKVM device. No first-time setup.
# For initial installation use: ../install.sh <pikvm-ip>
#
# Usage:
#   ./deploy.sh <device-ip> [device-password]
#
# Password defaults to "root" (PiKVM/BliKVM default). IP is required — no default,
# so the script can't accidentally hit a stale lab device if a past one was hardcoded.
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[kdkvm]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KDKVM_DIR="$SCRIPT_DIR/.."
PIKVM_IP="${1:-}"
PIKVM_PASS="${2:-root}"

if [[ -z "$PIKVM_IP" ]]; then
    err "Usage: $0 <device-ip> [device-password]"
fi

# P2 (2026-04-19) — before touching the device, ensure the repo's cross-file
# version references are in sync with the canonical app/web/version.json.
# Hard-fail on drift (no silent auto-fix) so the developer must commit the
# synced state before deploying; otherwise HTML ?v= tags can diverge from
# version.json and the browser cache-bust mechanism silently breaks.
if ! "$SCRIPT_DIR/sync-version.sh" --check; then
    err "Version references are out of sync — run 'dev/kdkvm/deploy/sync-version.sh' locally, commit, then re-run deploy.sh"
fi

# i18n lint: fail fast if any page references a missing key or a dict has
# duplicate keys (JS silently drops dupes — validator is the only safety net).
if command -v python3 &>/dev/null && [[ -f "$SCRIPT_DIR/../scripts/check-i18n.py" ]]; then
    if ! python3 "$SCRIPT_DIR/../scripts/check-i18n.py"; then
        err "i18n validation failed — see errors above"
    fi
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# SSH authentication: prefer sshpass, fall back to SSH_ASKPASS
if command -v sshpass &>/dev/null; then
    SSH_CMD="sshpass -p '$PIKVM_PASS' ssh $SSH_OPTS root@$PIKVM_IP"
    SCP_CMD="sshpass -p '$PIKVM_PASS' scp $SSH_OPTS -r"
    RSYNC_CMD="sshpass -p '$PIKVM_PASS' rsync -az --delete -e 'ssh $SSH_OPTS'"
else
    # Use SSH_ASKPASS for non-interactive password auth
    _ASKPASS_SCRIPT=$(mktemp)
    printf '#!/bin/sh\necho "%s"\n' "$PIKVM_PASS" > "$_ASKPASS_SCRIPT"
    chmod +x "$_ASKPASS_SCRIPT"
    export SSH_ASKPASS="$_ASKPASS_SCRIPT"
    export SSH_ASKPASS_REQUIRE=force
    export DISPLAY="${DISPLAY:-:0}"
    SSH_CMD="ssh $SSH_OPTS root@$PIKVM_IP"
    SCP_CMD="scp $SSH_OPTS -r"
    RSYNC_CMD="rsync -az --delete -e 'ssh $SSH_OPTS'"
    warn "sshpass not found, using SSH_ASKPASS fallback"
fi

STAGING="/tmp/kdkvm-deploy-$$"
# Cleanup local temp + ensure remote device is remounted ro on exit
cleanup() {
    rm -rf "$STAGING" "${_ASKPASS_SCRIPT:-}"
    eval $SSH_CMD "mount -o remount,ro / 2>/dev/null || true" 2>/dev/null || true
}
trap cleanup EXIT

# ── Step 1: Preflight ─────────────────────────────────────────────────────
info "Deploying kdkvm to $PIKVM_IP"

if ! eval $SSH_CMD "echo ok" &>/dev/null; then
    err "Cannot connect to root@$PIKVM_IP"
fi
ok "SSH connected"

# ── Step 2: Remount read-write ────────────────────────────────────────────
eval $SSH_CMD "mount -o remount,rw / 2>/dev/null || true"
ok "Filesystem remounted rw"

# ── Step 2.5: Ensure dependencies ────────────────────────────────────────
info "Ensuring Python dependencies..."
eval $SSH_CMD "'pacman -Qq python-cryptography &>/dev/null || pacman -Sy --noconfirm python-cryptography'" && ok "python-cryptography ok" || warn "python-cryptography install failed"
# Inline `if [[ ]]; then ... fi` via `eval ssh ...` gets mangled by the
# double-parsing pass (host quotes, then shell quotes).  Use POSIX `test`
# + `&&`/`||` which survives both passes.
eval $SSH_CMD "'test -x /opt/kvmind/kdkvm/venv/bin/pip && /opt/kvmind/kdkvm/venv/bin/pip install --quiet cryptography || echo venv-missing-install-sh-will-create'" \
    && ok "venv cryptography ok" || warn "venv cryptography install failed"

# ── Step 3: Build staging tree and push ───────────────────────────────────
info "Staging files..."

mkdir -p "$STAGING"/{opt/kvmind/kdkvm/{lib/kvm,lib/innerclaw/adapters,lib/handlers,bin,web/static},etc/kdkvm/prompts/intents,etc/systemd/system,etc/kvmd/nginx}

# Application code
cp -f "$KDKVM_DIR"/app/lib/*.py            "$STAGING/opt/kvmind/kdkvm/lib/"
cp -f "$KDKVM_DIR"/app/lib/kvm/*.py       "$STAGING/opt/kvmind/kdkvm/lib/kvm/"
cp -f "$KDKVM_DIR"/app/lib/handlers/*.py  "$STAGING/opt/kvmind/kdkvm/lib/handlers/"
cp -f "$KDKVM_DIR"/app/lib/innerclaw/*.py  "$STAGING/opt/kvmind/kdkvm/lib/innerclaw/"
cp -f "$KDKVM_DIR"/app/lib/innerclaw/adapters/*.py "$STAGING/opt/kvmind/kdkvm/lib/innerclaw/adapters/"
cp -f "$KDKVM_DIR"/app/bin/*               "$STAGING/opt/kvmind/kdkvm/bin/"
chmod +x "$STAGING/opt/kvmind/kdkvm/bin/"*

# Frontend
for ext in html js css json; do
    cp -f "$KDKVM_DIR"/app/web/*.$ext "$STAGING/opt/kvmind/kdkvm/web/" 2>/dev/null || true
done
if [[ -d "$KDKVM_DIR/app/web/static" ]]; then
    cp -rf "$KDKVM_DIR"/app/web/static/* "$STAGING/opt/kvmind/kdkvm/web/static/"
fi

# Prompts
cp -f "$KDKVM_DIR"/prompts/*.md              "$STAGING/etc/kdkvm/prompts/" 2>/dev/null || true
cp -f "$KDKVM_DIR"/prompts/intents/*.md      "$STAGING/etc/kdkvm/prompts/intents/" 2>/dev/null || true

# MyClaw verify key (public key from kdcms, for signature verification)
MYCLAW_PUB="$KDKVM_DIR/../kdcms/keys/myclaw_verify.pub"
if [[ -f "$MYCLAW_PUB" ]]; then
    cp -f "$MYCLAW_PUB" "$STAGING/etc/kdkvm/"
    ok "MyClaw verify key included"
else
    warn "MyClaw verify key not found (run kdcms deploy first to generate)"
fi

# Systemd services
cp -f "$KDKVM_DIR"/systemd/*.service "$STAGING/etc/systemd/system/" 2>/dev/null || true
cp -f "$KDKVM_DIR"/systemd/*.timer   "$STAGING/etc/systemd/system/" 2>/dev/null || true

# Nginx config
cp -f "$KDKVM_DIR"/nginx/kvmd.ctx-server.conf "$STAGING/etc/kvmd/nginx/"

# Count files
FILE_COUNT=$(find "$STAGING" -type f | wc -l | tr -d ' ')
ok "Staged $FILE_COUNT files"

# Push to device
info "Pushing to device..."
HAS_RSYNC=$(eval $SSH_CMD "command -v rsync" 2>/dev/null || true)

if [[ -n "$HAS_RSYNC" ]]; then
    eval $RSYNC_CMD "$STAGING/opt/" "root@$PIKVM_IP:/opt/"
    eval $RSYNC_CMD "$STAGING/etc/" "root@$PIKVM_IP:/etc/"
    ok "Synced via rsync (incremental)"
else
    eval $SCP_CMD "$STAGING/opt/kvmind" "root@$PIKVM_IP:/opt/"
    eval $SCP_CMD "$STAGING/etc/kdkvm"  "root@$PIKVM_IP:/etc/"
    # M3.4 rename: systemd units were renamed kvmind* → kdkvm*.  Match the
    # current naming scheme so the new unit files actually land on devices.
    eval $SCP_CMD "$STAGING/etc/systemd/system/"kdkvm* "root@$PIKVM_IP:/etc/systemd/system/"
    eval $SCP_CMD "$STAGING/etc/kvmd/nginx/kvmd.ctx-server.conf" "root@$PIKVM_IP:/etc/kvmd/nginx/"
    ok "Copied via scp"
fi

# ── Step 3.5c: Retire legacy kvmind-* systemd units (M3.4 rename cleanup) ──
# Old boxes may still carry kvmind.service / kvmind-{register,heartbeat,
# updater,tunnel}.{service,timer}, whose ExecStart points at bash scripts
# that have since been deleted (kvmind-register.sh / kvmind-heartbeat.sh).
# Stop + disable + remove them so systemd quits retrying dead units.
info "Retiring legacy kvmind-* systemd units + legacy state files..."
eval $SSH_CMD "'bash -s'" <<'LEGACY_CLEANUP'
set -u
LEGACY_UNITS="kvmind.service kvmind-register.service kvmind-register.timer \
              kvmind-heartbeat.service kvmind-heartbeat.timer \
              kvmind-updater.service kvmind-updater.timer \
              kvmind-tunnel.service"
for u in $LEGACY_UNITS; do
    if [ -f /etc/systemd/system/$u ]; then
        systemctl stop    "$u" 2>/dev/null || true
        systemctl disable "$u" 2>/dev/null || true
        rm -f "/etc/systemd/system/$u"
        echo "  retired $u"
    fi
done
# M5 §16 delete list — `/etc/kdkvm/*.token` and the old registration
# secret file are supplanted by state.db (plan §13). Leaving them on
# disk makes deploy.sh's TUNNEL_EXISTS probe lie, and the files are
# otherwise dead weight. Safe to remove: if state.db has the real
# tunnel_token, cloudflared reads it from there; if not, there is no
# token anywhere — same end state as before.
mount -o remount,rw / 2>/dev/null || true
for f in /etc/kdkvm/tunnel.token /etc/kdkvm/device.token \
         /etc/kdkvm/registration.secret /etc/kdkvm/bind.secret; do
    if [ -f "$f" ]; then
        rm -f "$f"
        echo "  retired $f"
    fi
done
systemctl daemon-reload
LEGACY_CLEANUP
ok "Legacy units + state files retired"

# ── Step 3.5a: Security fix — bind bridge to 127.0.0.1 only ─────────────
info "Applying bridge bind security fix..."
BRIDGE_FIX=$(eval $SSH_CMD "sed -i 's/host: 0\.0\.0\.0/host: 127.0.0.1/g' /etc/kdkvm/config.yaml 2>/dev/null && grep -c 'host: 127.0.0.1' /etc/kdkvm/config.yaml || echo 0")
if [[ "$BRIDGE_FIX" -ge 1 ]]; then
    ok "Bridge host → 127.0.0.1"
else
    warn "Bridge host migration skipped (already set or config missing)"
fi

# ── Step 3.5b: Migrate MSD data from kdkvm/ to .kdkvm/ ────────────────────
info "Migrating MSD data to hidden directory..."
eval $SSH_CMD "test -d /var/lib/kvmd/msd/kdkvm && { mount -o remount,rw /var/lib/kvmd/msd 2>/dev/null; mkdir -p /var/lib/kvmd/msd/.kdkvm; cp -an /var/lib/kvmd/msd/kdkvm/* /var/lib/kvmd/msd/.kdkvm/ 2>/dev/null; rm -rf /var/lib/kvmd/msd/kdkvm; mount -o remount,ro /var/lib/kvmd/msd 2>/dev/null; echo migrated; } || true" && ok "MSD data migrated" || warn "Migration skipped"

# ── Step 4: Reload and restart services ───────────────────────────────────
info "Restarting services..."

eval $SSH_CMD "systemctl daemon-reload"
# ── NOTE on quoting ─────────────────────────────────────────────────────
# Wrap EVERY remote command containing `||`, `&&`, `|`, `;`, `>` in single
# quotes (`"'cmd a || cmd b'"`). `eval $SSH_CMD "cmd a || cmd b"`
# re-parses after expansion, so the `||` becomes a LOCAL shell operator —
# ssh only sends `cmd a`, and `cmd b` gets executed on the dev machine
# (which, on macOS, promptly fails with `systemctl: command not found`).
# Single quotes keep the control chars opaque until they reach the remote.
# ─────────────────────────────────────────────────────────────────────────

# M3.4 rename: enable the new kdkvm-* units so they survive reboots.
# `enable` is idempotent and harmless when units are already enabled; we
# pipe `2>/dev/null || true` so missing units on older images don't abort
# the deploy.
eval $SSH_CMD "'systemctl enable kdkvm.service kdkvm-updater.timer kdkvm-cloudflared.service 2>/dev/null || true'" \
    && ok "kdkvm units enabled" || warn "kdkvm unit enable failed"
# M3.4: kvmind.service → kdkvm.service rename. Try the new name first so
# deploys to already-migrated devices behave normally; fall through to
# the old name for machines still on pre-M3.4 installs that haven't been
# re-flashed yet.
eval $SSH_CMD "'systemctl restart kdkvm 2>/dev/null || systemctl restart kvmind'" \
    && ok "kdkvm restarted" || warn "kdkvm/kvmind restart failed"
eval $SSH_CMD "systemctl restart kvmd"       && ok "kvmd restarted"       || warn "kvmd restart failed"

# Patch nginx mako template to disable HTTP/2 — nginx OSS 主线不支持 RFC 8441
# (WebSocket over HTTP/2)，开 http2 后浏览器 WS 升级会被 400 拒绝。同一 server
# block 不能重复 http2 directive，所以必须在 mako 源头改而不是 include 内覆盖。
# 幂等：sed 仅在 `http2 on;` 出现时改，已 patch 过的不重复。
# 需先 remount rw（PiKVM 根分区默认 ro）。
eval $SSH_CMD "'kvmd-helper-pst-remount 2>/dev/null; mount -o remount,rw / 2>/dev/null; \
    if grep -q \"^[[:space:]]*http2 on;\" /etc/kvmd/nginx/nginx.conf.mako 2>/dev/null; then \
        cp -n /etc/kvmd/nginx/nginx.conf.mako /etc/kvmd/nginx/nginx.conf.mako.pre-kvmind 2>/dev/null; \
        sed -i \"s|^\\([[:space:]]*\\)http2 on;|\\1http2 off;  # kdkvm: nginx OSS 不支持 WS over HTTP/2|\" /etc/kvmd/nginx/nginx.conf.mako; \
        echo PATCHED; \
    else echo \"already off / not needed\"; fi'" \
    | grep -qE "PATCHED|off" && ok "nginx mako http2 patch verified" || warn "nginx mako http2 patch may have failed"

eval $SSH_CMD "systemctl restart kvmd-nginx"  && ok "kvmd-nginx restarted" || warn "kvmd-nginx restart failed"

# cloudflared restart is best-effort and intentionally silent on failure:
#
#   · State.db is now the authoritative tunnel_token source (plan §13);
#     kdkvm.service's heartbeat loop re-issues the restart when a token
#     actually lands. No need to pre-check from deploy.sh.
#   · On a fresh/unactivated device there is no token — kdkvm-cloudflared
#     exits 1 (fail-fast), and RestartPreventExitStatus=1 in the unit
#     stops systemd from burning CPU on respawns. This is the expected
#     quiet state, not an error.
#   · We still trigger one restart so that an UPGRADE of a device that
#     already has a valid token picks up new kdkvm-cloudflared.service
#     changes immediately instead of waiting for the next heartbeat.
eval $SSH_CMD "'systemctl restart kdkvm-cloudflared 2>/dev/null || true'" >/dev/null 2>&1
ok "cloudflared restart triggered (fail-quiet on no-token devices)"

# Enable PiKVM OLED (ships with PiKVM OS but preset: disabled — shows IP on front panel)
OLED_EXISTS=$(eval $SSH_CMD "systemctl cat kvmd-oled &>/dev/null && echo yes || echo no")
if [[ "$OLED_EXISTS" == "yes" ]]; then
    eval $SSH_CMD "systemctl enable kvmd-oled 2>/dev/null || true"
    if eval $SSH_CMD "systemctl start kvmd-oled 2>/dev/null"; then
        ok "kvmd-oled enabled (front-panel OLED IP display)"
    else
        warn "kvmd-oled enabled but failed to start (OLED hardware missing?)"
    fi
fi

# ── Step 5: Remount ro and summary ────────────────────────────────────────
# Note: trap EXIT also ensures remount ro on any exit path
eval $SSH_CMD "mount -o remount,ro / 2>/dev/null || true"

sleep 2
# M3.4: check kdkvm first, fall back to kvmind for pre-migration devices.
KDKVM_STATUS=$(eval $SSH_CMD "systemctl is-active kdkvm 2>/dev/null || systemctl is-active kvmind 2>/dev/null" || echo "unknown")
NGINX_STATUS=$(eval $SSH_CMD "systemctl is-active kvmd-nginx 2>/dev/null" || echo "unknown")
TUNNEL_STATUS=$(eval $SSH_CMD "systemctl is-active kdkvm-cloudflared 2>/dev/null || systemctl is-active kvmind-tunnel 2>/dev/null" || echo "inactive")

echo ""
echo -e "${BOLD}${GREEN}  kdkvm deployed successfully!${NC}"
echo ""
echo -e "  ${BOLD}Target:${NC}     root@$PIKVM_IP"
echo -e "  ${BOLD}Files:${NC}      $FILE_COUNT"
echo -e "  ${BOLD}Services:${NC}"
echo -e "    kdkvm             $KDKVM_STATUS"
echo -e "    kvmd-nginx        $NGINX_STATUS"
echo -e "    kdkvm-cloudflared $TUNNEL_STATUS"
echo -e "  ${BOLD}Dashboard:${NC}  https://$PIKVM_IP/kvm/"
echo ""

if [[ "$KDKVM_STATUS" != "active" ]]; then
    warn "kdkvm is not running! Check: ssh root@$PIKVM_IP journalctl -u kdkvm -n 20"
fi
