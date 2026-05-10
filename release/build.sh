#!/bin/bash
# ============================================================================
# KVMind kdkvm — Release Build
# Packages the kdkvm source tree into a versioned tar.gz for distribution.
#
# Usage:
#   ./build.sh                         # Build from version.json, canary=100
#   ./build.sh 0.2.2-beta               # Override version string
#   ./build.sh --canary 10              # M5: restrict rollout to 10% of fleet
#   ./build.sh --changelog notes.md     # M5: attach release notes
#   ./build.sh --sign-key /path/key.pem # M5: sign latest.json with Ed25519
#   ./build.sh --sign-key k2.pem --key-id k2  # tag manifest so devices pick k2.pub
#
# Output:  release/dist/kdkvm-v{version}.tar.gz + .sha256 + SHA256SUMS
#          release/dist/latest.json (+ latest.json.sig if --sign-key given)
#          release/dist/latest.txt   (legacy pointer, kept for back-compat)
#
# 历史注：以前打 .zip + manifest 指 .zip，但设备端 kvmind-updater.sh 用
# `tar -xzf` 解压，结构性不匹配——zip 不是 gzip stream，tar 解失败。改
# 输出真 tar.gz 让两端协议一致。
#
# M5 (plan §5 M5 + §9.1 case 6): latest.json carries `canary_percent`. The
# kdkvm updater uses it to gate rollout per-device via SHA256(uid+build) mod
# 100 < canary_percent. Operator workflow: publish at canary=10 → monitor
# heartbeats/errors → re-run with canary=50 → canary=100.
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[build]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KDKVM_DIR="$SCRIPT_DIR/.."
DIST_DIR="$SCRIPT_DIR/dist"
VERSION_FILE="$KDKVM_DIR/app/web/version.json"

# ── Parse args ────────────────────────────────────────────────────────────
VERSION_OVERRIDE=""
CANARY_PERCENT="100"
CHANGELOG_FILE=""
SIGN_KEY=""
KEY_ID=""
MIN_VERSION=""
DOWNLOAD_BASE="${KDKVM_DOWNLOAD_BASE:-https://kvmind.com/release}"

while (( $# > 0 )); do
    case "$1" in
        --canary)       CANARY_PERCENT="$2"; shift 2 ;;
        --changelog)    CHANGELOG_FILE="$2"; shift 2 ;;
        --sign-key)     SIGN_KEY="$2"; shift 2 ;;
        --key-id)       KEY_ID="$2"; shift 2 ;;
        --min-version)  MIN_VERSION="$2"; shift 2 ;;
        --download-base) DOWNLOAD_BASE="$2"; shift 2 ;;
        --*)            err "unknown flag: $1" ;;
        *)              VERSION_OVERRIDE="$1"; shift ;;
    esac
done

if ! [[ "$CANARY_PERCENT" =~ ^[0-9]+$ ]] || (( CANARY_PERCENT < 0 )) || (( CANARY_PERCENT > 100 )); then
    err "--canary must be an integer 0..100 (got $CANARY_PERCENT)"
fi

# ── OTA manifest signing key (managed default) ───────────────────────────
# Private key lives under dev/keys/kdkvm-ota/ (gitignored, build-machine-only).
# Its public counterpart is committed there too so fresh installs pick up the
# trust root via build.sh staging. --sign-key overrides this default.
REPO_ROOT="$(cd "$KDKVM_DIR/../.." && pwd)"
KEYS_DIR="$REPO_ROOT/dev/keys/kdkvm-ota"
# TD-15 (2026-04-26): default key_id is the production rotation pin. Rotating
# again? Bump the suffix here AND drop the old .pub from /etc/kdkvm/update.pub.d/
# on staging first to validate.
: "${KEY_ID:=update-trust-2026-2}"

if [[ -z "$SIGN_KEY" ]]; then
    mkdir -p "$KEYS_DIR"
    chmod 700 "$KEYS_DIR"
    TRUSTED_KEY_PRIV="$KEYS_DIR/${KEY_ID}.key"
    TRUSTED_KEY_PUB="$KEYS_DIR/${KEY_ID}.pub"

    if [[ ! -f "$TRUSTED_KEY_PRIV" ]]; then
        # 2026-05-09: silent genpkey was the source of the myclaw "Invalid signature"
        # outage on .21 — a fresh checkout would generate a new keypair, push the
        # private key to production, and strand every device still carrying the
        # previous .pub. The new policy is fail-fast: an absent private key is
        # treated as an explicit operator decision needing explicit recovery.
        if [[ -f "$TRUSTED_KEY_PUB" ]]; then
            err "Private OTA signing key for key_id=$KEY_ID is missing but a public key is already committed (devices in the field carry it). This build machine cannot sign without de-trusting the fleet.

  Options:
    1. Restore $TRUSTED_KEY_PRIV from secure backup (recommended).
    2. Rotate to a new key_id (--key-id update-trust-YYYY-N+1) and run a coordinated co-trust → cutover OTA campaign. See dev/keys/README.md.
    3. If you are SURE no device is trusting the committed pub yet (fresh project / staging-only), set ALLOW_KEY_REGEN=1 and rerun to genpkey a brand-new keypair."
        fi
        if [[ "${ALLOW_KEY_REGEN:-0}" != "1" ]]; then
            err "No private OTA signing key for key_id=$KEY_ID. Set ALLOW_KEY_REGEN=1 only if no devices in the field are trusting this key_id yet."
        fi
        info "Generating Ed25519 release signing key (ALLOW_KEY_REGEN=1): $KEY_ID"
        openssl genpkey -algorithm Ed25519 -out "$TRUSTED_KEY_PRIV" 2>/dev/null
        chmod 600 "$TRUSTED_KEY_PRIV"
        openssl pkey -in "$TRUSTED_KEY_PRIV" -pubout -out "$TRUSTED_KEY_PUB"
        chmod 644 "$TRUSTED_KEY_PUB"
        ok "New keypair written to $KEYS_DIR — commit $TRUSTED_KEY_PUB to git (private key stays gitignored)."
    else
        # Re-derive public from private to detect drift/corruption.
        DERIVED_PUB=$(mktemp)
        openssl pkey -in "$TRUSTED_KEY_PRIV" -pubout -out "$DERIVED_PUB" 2>/dev/null
        if [[ -f "$TRUSTED_KEY_PUB" ]] && ! diff -q "$DERIVED_PUB" "$TRUSTED_KEY_PUB" >/dev/null; then
            rm -f "$DERIVED_PUB"
            err "Committed public key drifted from $TRUSTED_KEY_PRIV's derived public counterpart. Investigate: $TRUSTED_KEY_PUB vs derived. Do NOT silently overwrite — devices may already trust the committed pub."
        fi
        rm -f "$DERIVED_PUB"
    fi

    SIGN_KEY="$TRUSTED_KEY_PRIV"
fi

# ── Read version ─────────────────────────────────────────────────────────
if [[ -n "$VERSION_OVERRIDE" ]]; then
    VERSION="$VERSION_OVERRIDE"
    BUILD_NUMBER=$(python3 -c "import json; print(json.load(open('$VERSION_FILE')).get('build', '0'))" 2>/dev/null || echo "0")
else
    if [[ ! -f "$VERSION_FILE" ]]; then
        err "Version file not found: $VERSION_FILE"
    fi
    VERSION=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])")
    BUILD_NUMBER=$(python3 -c "import json; print(json.load(open('$VERSION_FILE')).get('build', '0'))")
fi

RELEASE_NAME="kdkvm-v${VERSION}"
PKG_NAME="${RELEASE_NAME}.tar.gz"
# Legacy alias —— 旧代码内可能还有 ZIP_NAME 引用，保持向后兼容地指向 PKG_NAME
ZIP_NAME="$PKG_NAME"

info "Building ${BOLD}$PKG_NAME${NC}"

# ── Staging ──────────────────────────────────────────────────────────────
STAGING=$(mktemp -d /tmp/kvmind-build-XXXXXXXX)
trap 'rm -rf "$STAGING"' EXIT

DEST="$STAGING/$RELEASE_NAME"
mkdir -p "$DEST"/{app/lib/kvm,app/lib/handlers,app/lib/innerclaw/adapters,app/bin,app/web/static,app/keys,systemd,nginx,prompts/intents}

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

# ── Trust roots: stage from dev/keys/ into OTA tar ──────────────────────
# install.sh reads $SCRIPT_DIR/app/keys/*.pub from the unpacked tar, so the
# tar internal layout (staging $DEST/app/keys/) is fixed. Source of truth is
# the unified dev/keys/ tree.
UNIFIED_KEYS="$REPO_ROOT/dev/keys"

stage_pub() {
    local name="$1" src="$2"
    if [[ -f "$src" ]]; then
        cp -f "$src" "$DEST/app/keys/$name"
        ok "$name staged from $src"
    else
        warn "$name missing at $src — devices receiving this OTA will fail-closed for the corresponding signature path"
    fi
}

stage_pub "myclaw_verify.pub"    "$UNIFIED_KEYS/kdcms/myclaw_verify.pub"
stage_pub "heartbeat_verify.pub" "$UNIFIED_KEYS/kdcms/heartbeat_verify.pub"

# OTA update-trust public keys — every *.pub in dev/keys/kdkvm-ota/ is staged;
# install.sh fans them out to /etc/kdkvm/update.pub.d/ for kvmind-updater.sh
# multi-key_id verification.
shopt -s nullglob
for pub in "$UNIFIED_KEYS"/kdkvm-ota/update-trust-*.pub; do
    base="$(basename "$pub")"
    cp -f "$pub" "$DEST/app/keys/$base"
    ok "OTA trust root staged → app/keys/$base"
done
shopt -u nullglob

# ── Clean unwanted files ─────────────────────────────────────────────────
find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name ".DS_Store" -delete 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true

# macOS Sonoma+ launch services 给每个新文件自动打 com.apple.provenance xattr。
# BSD tar 默认会把所有 xattr 写成 PAX 扩展头 LIBARCHIVE.xattr.com.apple.*，
# 设备端 PiKVM 上的 GNU tar 不认这种 keyword，每个文件解压时各打一行 warning，
# OTA / curl install 日志被几百行噪音淹没（虽然文件本身解压正确）。
# 在打 tar 前把 staging 树的所有 xattr 剥光，让 tar 没 xattr 可嵌。
# Linux 上 xattr 命令不存在 / 也不会自动写 macOS xattr，直接跳过。
if [[ "$(uname)" == "Darwin" ]] && command -v xattr >/dev/null 2>&1; then
    xattr -cr "$DEST" 2>/dev/null || true
fi

FILE_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
ok "Staged $FILE_COUNT files"

# ── Create tar.gz ────────────────────────────────────────────────────────
info "Creating tar.gz..."
mkdir -p "$DIST_DIR"
rm -f "$DIST_DIR/$PKG_NAME"

# --no-xattrs: belt-and-suspenders — 即使 staging 目录残留 xattr（比如 xattr 命令
# 不可用 fallback），bsdtar/GNU tar 也强制不嵌入扩展属性。BSD tar (macOS, libarchive)
# 与 GNU tar 1.27+ 都支持 --no-xattrs。
#
# 顶层结构契约（与 kvmind-updater.sh 协议）：tar 解压后第一层目录是 app/、
# prompts/、nginx/ 等业务子树，**不**是 kdkvm-v{ver}/ 版本目录。updater 用
# `cp -f $DOWNLOAD_DIR/app/lib/*.py ...` 这种平铺路径直接消费，加版本目录
# 包一层会让所有 cp 静默 no-match（updater 用 `2>/dev/null || true` 吞错），
# 表面 status=updated 实际什么都没换。曾经的事故：0.5.41 OTA 之前打过带
# 版本目录的包，所有设备点升级 → 服务重启 → version.json 仍是旧的。
# 改用 -C $RELEASE_NAME + 写 . 让 tar 内层就是 app/ 等。
(cd "$STAGING/$RELEASE_NAME" && tar --no-xattrs -czf "$DIST_DIR/$PKG_NAME" .)
ok "Created $PKG_NAME"

# 包内成员路径硬性校验：绝对路径 / 上跳路径会让设备端解压时落到 /etc 等
# 关键目录之外。即便 kvmind-updater.sh 已经做运行时拒绝，这里在打包侧
# 同样卡死，可以阻断"误打包了恶意 staging" + "签名密钥被攻陷后伪造包"
# 两类场景，是与 OTA 验签独立的另一条防线。
info "Validating archive member paths..."
BAD_PATHS=$(tar -tzf "$DIST_DIR/$PKG_NAME" | grep -E '^/|(^|/)\.\./|(^|/)\.\.($|/)' || true)
if [[ -n "$BAD_PATHS" ]]; then
    echo -e "${RED}  ✗ Archive contains unsafe paths:${NC}" >&2
    echo "$BAD_PATHS" | sed 's/^/    /' >&2
    err "refusing to ship $PKG_NAME — unsafe member paths"
fi
ok "Archive member paths are safe (no absolute / .. entries)"

# ── Generate latest.txt ──────────────────────────────────────────────────
echo "$ZIP_NAME" > "$DIST_DIR/latest.txt"
ok "Updated latest.txt → $ZIP_NAME"

# ── Summary ──────────────────────────────────────────────────────────────
ZIP_SIZE=$(du -h "$DIST_DIR/$ZIP_NAME" | cut -f1)
SHA256=$(shasum -a 256 "$DIST_DIR/$ZIP_NAME" | cut -d' ' -f1)

# ── Publish checksum files ───────────────────────────────────────────────
CHECKSUMS="$DIST_DIR/SHA256SUMS"
: > "$CHECKSUMS"
for pkg in "$DIST_DIR"/kdkvm-v*.tar.gz; do
    [[ -e "$pkg" ]] || continue
    pkg_name=$(basename "$pkg")
    pkg_sha=$(shasum -a 256 "$pkg" | cut -d' ' -f1)
    echo "$pkg_sha  $pkg_name" > "$DIST_DIR/$pkg_name.sha256"
    echo "$pkg_sha  $pkg_name" >> "$CHECKSUMS"
done
ok "Checksums generated"

# ── Generate latest.json (OTA manifest, M5) ──────────────────────────────
CHANGELOG_TEXT=""
if [[ -n "$CHANGELOG_FILE" ]]; then
    if [[ ! -f "$CHANGELOG_FILE" ]]; then
        err "Changelog file not found: $CHANGELOG_FILE"
    fi
    CHANGELOG_TEXT=$(cat "$CHANGELOG_FILE")
fi

MANIFEST_FILE="$DIST_DIR/latest.json"
KDKVM_VERSION="$VERSION" \
KDKVM_BUILD="$BUILD_NUMBER" \
KDKVM_URL="$DOWNLOAD_BASE/$ZIP_NAME" \
KDKVM_SHA256="$SHA256" \
KDKVM_CANARY="$CANARY_PERCENT" \
KDKVM_CHANGELOG="$CHANGELOG_TEXT" \
KDKVM_MIN_VERSION="$MIN_VERSION" \
KDKVM_KEY_ID="$KEY_ID" \
python3 - "$MANIFEST_FILE" <<'PY'
import json, os, sys
out = {
    "version":        os.environ["KDKVM_VERSION"],
    "build":          int(os.environ["KDKVM_BUILD"]),
    "url":            os.environ["KDKVM_URL"],
    "sha256":         os.environ["KDKVM_SHA256"],
    "canary_percent": int(os.environ["KDKVM_CANARY"]),
    "changelog":      os.environ.get("KDKVM_CHANGELOG", ""),
    "min_version":    os.environ.get("KDKVM_MIN_VERSION", ""),
    # Manifest schema versioning — bump when adding required fields the
    # updater must understand. kdkvm updater ignores unknown fields.
    "manifest_schema": "1.0",
}
# Optional key_id tags which pubkey signed this manifest. Devices prefer
# update.pub.d/<key_id>.pub first, then fall through to the rest of the
# directory and the legacy update.pub. Omit for legacy single-key mode.
_key_id = os.environ.get("KDKVM_KEY_ID", "").strip()
if _key_id:
    out["key_id"] = _key_id
with open(sys.argv[1], "w") as f:
    # Canonical ordering + no trailing whitespace so the Ed25519 signature
    # is reproducible. Do NOT add indent= here — signature is over the
    # exact bytes we write.
    json.dump(out, f, separators=(",", ":"), sort_keys=True)
PY
ok "Manifest: $MANIFEST_FILE (canary=${CANARY_PERCENT}%)"

# ── Sign manifest (optional, M5) ──────────────────────────────────────────
if [[ -n "$SIGN_KEY" ]]; then
    if [[ ! -f "$SIGN_KEY" ]]; then
        err "Signing key not found: $SIGN_KEY"
    fi
    SIG_FILE="$MANIFEST_FILE.sig"
    KDKVM_KEY="$SIGN_KEY" python3 - "$MANIFEST_FILE" "$SIG_FILE" <<'PY'
import base64, os, sys
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
manifest_path, sig_path = sys.argv[1], sys.argv[2]
with open(os.environ["KDKVM_KEY"], "rb") as f:
    key = load_pem_private_key(f.read(), password=None)
if not isinstance(key, Ed25519PrivateKey):
    sys.exit("signing key must be Ed25519 PEM")
with open(manifest_path, "rb") as f:
    payload = f.read()
sig = key.sign(payload)
with open(sig_path, "w") as f:
    f.write(base64.b64encode(sig).decode() + "\n")
PY
    ok "Signature: $SIG_FILE"
else
    warn "No --sign-key given — latest.json.sig NOT generated (device-side will refuse update if /etc/kdkvm/update.pub is present)"
fi

# ── Sanity: manifest must match version.json + real zip sha256 ───────────
# If latest.json drifts (e.g., someone hand-edited it or the last build.sh
# run was on an older checkout), uploading it would silently ship the wrong
# version to the fleet. Fail fast instead.
MANIFEST_VER=$(python3 -c "import json; print(json.load(open('$MANIFEST_FILE'))['version'])")
MANIFEST_SHA=$(python3 -c "import json; print(json.load(open('$MANIFEST_FILE'))['sha256'])")
if [[ -z "$VERSION_OVERRIDE" ]]; then
    SOURCE_VER=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])")
    if [[ "$MANIFEST_VER" != "$SOURCE_VER" ]]; then
        err "Manifest/source version mismatch: latest.json=$MANIFEST_VER vs version.json=$SOURCE_VER"
    fi
fi
if [[ "$MANIFEST_SHA" != "$SHA256" ]]; then
    err "Manifest sha256 does not match zip: manifest=$MANIFEST_SHA zip=$SHA256"
fi
ok "Manifest cross-check passed (version=$MANIFEST_VER, sha=${MANIFEST_SHA:0:12}…)"

echo ""
echo -e "${BOLD}${GREEN}  Build complete!${NC}"
echo ""
echo -e "  ${BOLD}Package:${NC}  $ZIP_NAME"
echo -e "  ${BOLD}Size:${NC}     $ZIP_SIZE"
echo -e "  ${BOLD}Files:${NC}    $FILE_COUNT"
echo -e "  ${BOLD}SHA256:${NC}   $SHA256"
echo -e "  ${BOLD}Canary:${NC}   ${CANARY_PERCENT}%"
echo -e "  ${BOLD}Output:${NC}   $DIST_DIR/"
echo ""
