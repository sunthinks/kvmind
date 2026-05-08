#!/usr/bin/env bash
#
# sync-version.sh — propagate the canonical version from
#   dev/kdkvm/app/web/version.json
# to every other file that mentions it.
#
# Canonical source: app/web/version.json (.version key).
# Synced targets:
#   - dev/kdkvm/README.md:        the two kdkvm-v<ver>-beta.zip references
#
# NOT synced (by design):
#   - README.md / PROJECT_INDEX.md / docs/**:
#       quote version.json directly via link, no embedded version string.
#   - dev/kdkvm/pyproject.toml:   reads version dynamically via _version.py
#
# Usage:
#   ./deploy/sync-version.sh           # run from dev/kdkvm or anywhere
#   ./deploy/sync-version.sh --check   # dry-run; exits 1 if anything differs
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
KDKVM_DIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$KDKVM_DIR/../.." && pwd)"

VERSION_JSON="$KDKVM_DIR/app/web/version.json"
if [[ ! -f "$VERSION_JSON" ]]; then
    echo "ERROR: $VERSION_JSON not found" >&2
    exit 2
fi

# Extract version without jq (not guaranteed on every build machine).
VERSION="$(python3 -c "import json,sys; print(json.load(open('$VERSION_JSON'))['version'])")"
if [[ -z "$VERSION" ]]; then
    echo "ERROR: version.json has no .version key" >&2
    exit 2
fi

CHECK_MODE=0
if [[ "${1:-}" == "--check" ]]; then
    CHECK_MODE=1
fi

echo "[sync-version] canonical version: $VERSION"

replace_in_file() {
    local file="$1" pattern="$2" replacement="$3"
    if [[ ! -f "$file" ]]; then
        echo "  SKIP  $file (missing)" >&2
        return 0
    fi
    if grep -qE "$pattern" "$file"; then
        if [[ $CHECK_MODE -eq 1 ]]; then
            # Check whether the replacement would be a no-op.
            local before after
            before="$(cat "$file")"
            after="$(sed -E "s|$pattern|$replacement|g" "$file")"
            if [[ "$before" != "$after" ]]; then
                echo "  DIFF  $file" >&2
                return 1
            fi
            echo "  OK    $file"
        else
            # Portable in-place edit (works on BSD + GNU sed).
            local tmp
            tmp="$(mktemp)"
            sed -E "s|$pattern|$replacement|g" "$file" > "$tmp"
            mv "$tmp" "$file"
            echo "  WROTE $file"
        fi
    else
        echo "  MISS  $file (pattern not found — did the file format change?)" >&2
        return 1
    fi
}

failed=0

# Regex note: `(-[A-Za-z]+)?` makes the pre-release suffix optional so this
# script keeps working after 0.3.1 GA drops the `-beta` tag. Before this
# change the pattern hard-coded `-beta` and MISSed every time the anchor
# file was already at a GA version, defeating the sync.

# dev/kdkvm/README.md: kdkvm-v<ver>.zip references (install command examples)
replace_in_file "$KDKVM_DIR/README.md" \
    "kdkvm-v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z]+)?\.zip" \
    "kdkvm-v$VERSION.zip" || failed=1

if [[ $CHECK_MODE -eq 1 ]]; then
    if [[ $failed -eq 1 ]]; then
        echo "[sync-version] CHECK FAILED — run without --check to fix" >&2
        exit 1
    fi
    echo "[sync-version] CHECK OK"
fi

echo "[sync-version] done."
