#!/bin/bash
# ============================================================================
# KVMind Test Setup — inject test AI keys for development/QA
#
# This script is NOT part of the install process.
# Run AFTER install.sh to set up AI providers for testing.
#
# Usage:
#   # Preferred: source a local env file (gitignored) then run
#   set -a && source .env.test.local && set +a
#   ./deploy/test-setup.sh <device-ip> [password]
#
#   # Or pass via env inline
#   GEMINI_KEY=xxx ./deploy/test-setup.sh <device-ip> [password]
#
# Required env:
#   GEMINI_KEY   — Google AI Studio API key (https://aistudio.google.com/apikey)
#
# Optional env:
#   OLLAMA_URL   — Local LLM endpoint (default: http://192.168.0.12:11434/v1)
#
# See .env.test.example for a template.
#
# What it does:
#   1. Writes GEMINI_KEY to /etc/kdkvm/ai.env on the target device
#   2. Adds Ollama (local LLM) config to /etc/kdkvm/config.yaml
#   3. Restarts kvmind service
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; exit 1; }

DEVICE_IP="${1:-}"
DEVICE_PASS="${2:-root}"

if [[ -z "$DEVICE_IP" ]]; then
    err "Usage: $0 <device-ip> [password]"
fi

# ── Required test AI configuration (from env; never hardcode secrets) ──
: "${GEMINI_KEY:?GEMINI_KEY env var required; get a key from https://aistudio.google.com/apikey and put it in dev/kdkvm/deploy/.env.test.local}"
: "${OLLAMA_URL:=http://192.168.0.12:11434/v1}"

echo -e "[KVMind] Setting up test AI on ${DEVICE_IP}"

# Check sshpass
if ! command -v sshpass &>/dev/null; then
    # Fall back to expect
    if ! command -v expect &>/dev/null; then
        err "sshpass or expect required"
    fi
    SSH_CMD="expect -c 'set timeout 15; spawn ssh -o StrictHostKeyChecking=no root@${DEVICE_IP} {*}; expect password:; send ${DEVICE_PASS}\r; expect eof'"
    _ssh() {
        expect -c "
            set timeout 15
            spawn ssh -o StrictHostKeyChecking=no root@${DEVICE_IP} \"$1\"
            expect \"password:\"
            send \"${DEVICE_PASS}\r\"
            expect eof
        " 2>&1 | grep -v "^spawn\|^root@\|password:"
    }
else
    _ssh() {
        sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no "root@${DEVICE_IP}" "$1" 2>&1
    }
fi

# 1. Write AI env
_ssh "echo -e '# KVMind Test AI Configuration\nGEMINI_API_KEY=${GEMINI_KEY}' > /etc/kdkvm/ai.env"
ok "Gemini API key set"

# 2. Add Ollama to config.yaml (if not already present)
_ssh "grep -q 'ollama_enabled' /etc/kdkvm/config.yaml 2>/dev/null || sed -i '/^ai:/a\\  ollama_enabled: true\n  ollama_url: ${OLLAMA_URL}' /etc/kdkvm/config.yaml"
ok "Ollama config added (${OLLAMA_URL})"

# 3. Restart
_ssh "systemctl restart kvmind"
sleep 3
STATUS=$(_ssh "systemctl is-active kvmind" | tail -1)

if [[ "$STATUS" == *"active"* ]]; then
    ok "kvmind restarted successfully"
    PROVIDERS=$(_ssh "journalctl -u kvmind -n 20 --no-pager | grep 'AI providers'" | tail -1)
    echo -e "  ${GREEN}${PROVIDERS}${NC}"
else
    warn "kvmind may still be starting, check: journalctl -u kvmind -f"
fi

echo ""
echo -e "  Test setup complete for ${DEVICE_IP}"
echo -e "  Dashboard: https://${DEVICE_IP}/kvm/"
