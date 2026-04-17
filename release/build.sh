#!/bin/bash
# ============================================================================
# KVMind kdkvm — Release Build
# Packages the kdkvm source tree into a versioned zip for distribution.
#
# Usage:
#   ./build.sh              # Build using version from version.json
#   ./build.sh 0.2.2-beta   # Override version string
#
# Output:  release/dist/kdkvm-v{version}.zip + .sha256 + SHA256SUMS + latest.txt
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[build]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KDKVM_DIR="$SCRIPT_DIR/.."
DIST_DIR="$SCRIPT_DIR/dist"
VERSION_FILE="$KDKVM_DIR/app/web/version.json"

# ── Read version ─────────────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    VERSION="$1"
else
    if [[ ! -f "$VERSION_FILE" ]]; then
        err "Version file not found: $VERSION_FILE"
    fi
    VERSION=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])")
fi

RELEASE_NAME="kdkvm-v${VERSION}"
ZIP_NAME="${RELEASE_NAME}.zip"

info "Building ${BOLD}$ZIP_NAME${NC}"

# ── Staging ──────────────────────────────────────────────────────────────
STAGING=$(mktemp -d /tmp/kvmind-build-XXXXXXXX)
trap 'rm -rf "$STAGING"' EXIT

DEST="$STAGING/$RELEASE_NAME"
mkdir -p "$DEST"/{app/lib/kvm,app/lib/handlers,app/lib/innerclaw/adapters,app/bin,app/web/static,systemd,nginx,prompts/intents}

# ── Copy application code ────────────────────────────────────────────────
info "Staging application code..."

# install.sh (entry point) — inject version string so the device-side script
# never needs to parse JSON or call python3 just to display the version.
cp -f "$KDKVM_DIR/install.sh" "$DEST/"
LC_ALL=C sed -i '' "s/__KDKVM_VERSION__/${VERSION}/g" "$DEST/install.sh"

# Python modules
cp -f "$KDKVM_DIR"/app/lib/*.py "$DEST/app/lib/"
cp -f "$KDKVM_DIR"/app/lib/kvm/*.py "$DEST/app/lib/kvm/"
cp -f "$KDKVM_DIR"/app/lib/handlers/*.py "$DEST/app/lib/handlers/"
cp -f "$KDKVM_DIR"/app/lib/innerclaw/*.py "$DEST/app/lib/innerclaw/"
cp -f "$KDKVM_DIR"/app/lib/innerclaw/adapters/*.py "$DEST/app/lib/innerclaw/adapters/"

# Shell scripts
cp -f "$KDKVM_DIR"/app/bin/* "$DEST/app/bin/"
chmod +x "$DEST/app/bin/"*

# Frontend (html, js, css, json)
for ext in html js css json; do
    cp -f "$KDKVM_DIR"/app/web/*.$ext "$DEST/app/web/" 2>/dev/null || true
done
if [[ -d "$KDKVM_DIR/app/web/static" ]]; then
    cp -rf "$KDKVM_DIR"/app/web/static/* "$DEST/app/web/static/" 2>/dev/null || true
fi

# Systemd services
cp -f "$KDKVM_DIR"/systemd/*.service "$DEST/systemd/" 2>/dev/null || true
cp -f "$KDKVM_DIR"/systemd/*.timer "$DEST/systemd/" 2>/dev/null || true

# Nginx config
cp -f "$KDKVM_DIR"/nginx/kvmd.ctx-server.conf "$DEST/nginx/"

# Prompts
cp -f "$KDKVM_DIR"/prompts/*.md "$DEST/prompts/" 2>/dev/null || true
cp -f "$KDKVM_DIR"/prompts/intents/*.md "$DEST/prompts/intents/" 2>/dev/null || true

# ── Clean unwanted files ─────────────────────────────────────────────────
find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name ".DS_Store" -delete 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true

FILE_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
ok "Staged $FILE_COUNT files"

# ── Create zip ───────────────────────────────────────────────────────────
info "Creating zip..."
mkdir -p "$DIST_DIR"
rm -f "$DIST_DIR/$ZIP_NAME"

(cd "$STAGING" && zip -rq "$DIST_DIR/$ZIP_NAME" "$RELEASE_NAME")
ok "Created $ZIP_NAME"

# ── Generate latest.txt ──────────────────────────────────────────────────
echo "$ZIP_NAME" > "$DIST_DIR/latest.txt"
ok "Updated latest.txt → $ZIP_NAME"

# ── Summary ──────────────────────────────────────────────────────────────
ZIP_SIZE=$(du -h "$DIST_DIR/$ZIP_NAME" | cut -f1)
SHA256=$(shasum -a 256 "$DIST_DIR/$ZIP_NAME" | cut -d' ' -f1)

# ── Publish checksum files ───────────────────────────────────────────────
CHECKSUMS="$DIST_DIR/SHA256SUMS"
: > "$CHECKSUMS"
for pkg in "$DIST_DIR"/kdkvm-v*.zip; do
    [[ -e "$pkg" ]] || continue
    pkg_name=$(basename "$pkg")
    pkg_sha=$(shasum -a 256 "$pkg" | cut -d' ' -f1)
    echo "$pkg_sha  $pkg_name" > "$DIST_DIR/$pkg_name.sha256"
    echo "$pkg_sha  $pkg_name" >> "$CHECKSUMS"
done
ok "Checksums generated"

echo ""
echo -e "${BOLD}${GREEN}  Build complete!${NC}"
echo ""
echo -e "  ${BOLD}Package:${NC}  $ZIP_NAME"
echo -e "  ${BOLD}Size:${NC}     $ZIP_SIZE"
echo -e "  ${BOLD}Files:${NC}    $FILE_COUNT"
echo -e "  ${BOLD}SHA256:${NC}   $SHA256"
echo -e "  ${BOLD}Output:${NC}   $DIST_DIR/"
echo ""
