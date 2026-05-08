#!/bin/bash
# ============================================================================
# KVMind KVM — One-time Cleanup
# Removes legacy artifacts that are no longer needed.
# Run once after upgrading from old kdkvm layout to new kvmind layout.
#
# Usage:
#   ./clear.sh [pikvm-ip] [pikvm-password]
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
info() { echo -e "  ${BOLD}→${NC} $*"; }

PIKVM_IP="${1:-}"
if [[ -z "$PIKVM_IP" ]]; then
    echo "Usage: $0 <pikvm-ip> [pikvm-password]" >&2
    exit 1
fi
PIKVM_PASS="${2:-root}"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

if command -v sshpass &>/dev/null; then
    SSH_CMD="sshpass -p '$PIKVM_PASS' ssh $SSH_OPTS root@$PIKVM_IP"
else
    _ASKPASS_SCRIPT=$(mktemp)
    printf '#!/bin/sh\necho "%s"\n' "$PIKVM_PASS" > "$_ASKPASS_SCRIPT"
    chmod +x "$_ASKPASS_SCRIPT"
    export SSH_ASKPASS="$_ASKPASS_SCRIPT"
    export SSH_ASKPASS_REQUIRE=force
    export DISPLAY="${DISPLAY:-:0}"
    SSH_CMD="ssh $SSH_OPTS root@$PIKVM_IP"
    trap 'rm -f "$_ASKPASS_SCRIPT" 2>/dev/null' EXIT
fi

run_remote() {
    eval $SSH_CMD "$1"
}

echo ""
echo -e "${BOLD}  KVMind — One-time Cleanup${NC}"
echo -e "  Target: root@${PIKVM_IP}"
echo ""

# ── 1. Remove legacy kdkvm.service (replaced by kvmind.service) ─────────
info "Checking for legacy kdkvm.service..."
if run_remote "systemctl is-enabled kdkvm.service 2>/dev/null" | grep -q enabled; then
    run_remote "systemctl stop kdkvm.service 2>/dev/null; systemctl disable kdkvm.service 2>/dev/null; rm -f /etc/systemd/system/kdkvm.service; systemctl daemon-reload" || true
    ok "Legacy kdkvm.service stopped, disabled, and removed"
else
    ok "No legacy kdkvm.service found (or already disabled)"
fi

# ── 2. Remove old /opt/kdkvm directory (code moved to /opt/kvmind/kdkvm) ─
info "Checking for legacy /opt/kdkvm..."
if run_remote "test -d /opt/kdkvm && echo yes" | grep -q yes; then
    run_remote "rm -rf /opt/kdkvm"
    ok "Legacy /opt/kdkvm directory removed"
else
    ok "No legacy /opt/kdkvm directory found"
fi

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}  Cleanup complete!${NC}"
echo ""
