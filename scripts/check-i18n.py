#!/usr/bin/env python3
"""Validate kvmind-i18n.js dictionaries and HTML data-i18n references.

Checks:
  1. Duplicate keys within any DICTS[namespace][lang] object (JS silently last-wins
     but we catch it here).
  2. Key-set parity across zh/ja/en within each namespace (warn if any lang is
     missing keys the others have).
  3. Every data-i18n / data-kv-i18n attribute in HTML files resolves to an
     actual key in the appropriate namespace (host page's init() namespace for
     data-i18n; 'widget' for data-kv-i18n).

Exits non-zero on any hard failure. Run from repo root or wire into deploy.sh
pre-flight alongside sync-version.sh --check.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"
I18N_JS = WEB / "kvmind-i18n.js"

# page file name → namespace passed to KVMindI18n.init(...)
PAGE_NAMESPACE = {
    "setup.html": "setup",
    "activate.html": "activate",
    "login.html": "login",
    "change-password.html": "change_password",
    "dashboard.html": "dashboard",
    "index.html": "kvm",
}

errors: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# ---------------------------------------------------------------------------
# 1. Parse kvmind-i18n.js dictionaries (naive but sufficient — we control the
# file format so we can rely on the literal structure it uses).
# ---------------------------------------------------------------------------

def load_i18n_source() -> str:
    if not I18N_JS.exists():
        fail(f"kvmind-i18n.js not found at {I18N_JS}")
        sys.exit(1)
    return I18N_JS.read_text(encoding="utf-8")


NAMESPACE_RE = re.compile(r"^\s{4}(\w+):\s*\{\s*$", re.MULTILINE)
LANG_RE = re.compile(r"^\s{6}(zh|ja|en):\s*\{\s*$", re.MULTILINE)
KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def extract_keys(block: str) -> list[str]:
    """Extract top-level object keys, skipping contents of string literals and
    nested braces so we do not pick up `IP:` from inside value strings or keys
    of nested sub-objects (we treat the lang block as flat — it is)."""
    keys: list[str] = []
    i = 0
    n = len(block)
    depth = 0
    expecting_key = True  # after `{`, `,` or at start; False while inside a value
    while i < n:
        c = block[i]
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n and block[i] != quote:
                if block[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            i += 1
            continue
        if c == "{":
            depth += 1
            expecting_key = True
            i += 1
            continue
        if c == "}":
            depth -= 1
            i += 1
            continue
        if c == ",":
            if depth == 0:
                expecting_key = True
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if expecting_key and depth == 0:
            m = KEY_PATTERN.match(block, i)
            if m:
                kname = m.group(0)
                j = m.end()
                # skip spaces; must be followed by `:`
                while j < n and block[j].isspace():
                    j += 1
                if j < n and block[j] == ":":
                    keys.append(kname)
                    expecting_key = False
                    i = j + 1
                    continue
            expecting_key = False
        i += 1
    return keys


def collect_dicts(src: str) -> dict[str, dict[str, list[str]]]:
    """Return {namespace: {lang: [key, key, ...]}} — duplicates preserved."""
    # Narrow to inside the DICTS object: from `var DICTS = {` up to `};\n  //`
    m = re.search(r"var DICTS\s*=\s*\{", src)
    if not m:
        fail("Could not locate `var DICTS = {` in kvmind-i18n.js")
        return {}
    start = m.end()
    # Find end of DICTS object by scanning braces
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    dicts_src = src[start:i - 1]

    out: dict[str, dict[str, list[str]]] = {}
    # Split into namespace blocks
    ns_matches = list(re.finditer(r"^\s{4}(\w+):\s*\{\s*$", dicts_src, re.MULTILINE))
    for idx, nm in enumerate(ns_matches):
        ns = nm.group(1)
        block_start = nm.end()
        block_end = ns_matches[idx + 1].start() if idx + 1 < len(ns_matches) else len(dicts_src)
        block = dicts_src[block_start:block_end]
        out[ns] = {}
        lang_matches = list(LANG_RE.finditer(block))
        for lidx, lm in enumerate(lang_matches):
            lang = lm.group(1)
            lstart = lm.end()
            lend = lang_matches[lidx + 1].start() if lidx + 1 < len(lang_matches) else len(block)
            lang_block = block[lstart:lend]
            keys = extract_keys(lang_block)
            out[ns][lang] = keys
    return out


def check_duplicates(dicts: dict[str, dict[str, list[str]]]) -> None:
    for ns, langs in dicts.items():
        for lang, keys in langs.items():
            seen: dict[str, int] = {}
            for k in keys:
                seen[k] = seen.get(k, 0) + 1
            dups = [k for k, n in seen.items() if n > 1]
            if dups:
                fail(f"[duplicate] {ns}.{lang}: {', '.join(dups)}")


def check_parity(dicts: dict[str, dict[str, list[str]]]) -> None:
    for ns, langs in dicts.items():
        if not langs:
            continue
        key_sets = {lang: set(keys) for lang, keys in langs.items()}
        # union of all keys
        union: set[str] = set()
        for s in key_sets.values():
            union |= s
        for lang, keys in key_sets.items():
            missing = union - keys
            if missing:
                warn(f"[parity] {ns}.{lang} missing: {', '.join(sorted(missing))}")


# ---------------------------------------------------------------------------
# 2. Scan HTML for data-i18n / data-kv-i18n attributes and verify they resolve.
# ---------------------------------------------------------------------------

ATTR_RE = re.compile(r'data-(i18n|kv-i18n)(?:-ph)?="([^"]+)"')


def check_html_refs(dicts: dict[str, dict[str, list[str]]]) -> None:
    for html_name, ns in PAGE_NAMESPACE.items():
        path = WEB / html_name
        if not path.exists():
            warn(f"[html] page not found: {html_name}")
            continue
        content = path.read_text(encoding="utf-8")
        for m in ATTR_RE.finditer(content):
            attr_kind, key = m.group(1), m.group(2)
            target_ns = "widget" if attr_kind == "kv-i18n" else ns
            # Any language has the key is fine (we warn about parity above).
            ns_dict = dicts.get(target_ns, {})
            has = any(key in ns_dict.get(lang, []) for lang in ("zh", "ja", "en"))
            if not has:
                fail(f"[html:{html_name}] data-{attr_kind}=\"{key}\" missing from {target_ns}.*")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    src = load_i18n_source()
    dicts = collect_dicts(src)
    if not dicts:
        fail("No namespaces parsed from DICTS")
        print_result()
        return 1
    check_duplicates(dicts)
    check_parity(dicts)
    check_html_refs(dicts)
    print_summary(dicts)
    print_result()
    return 1 if errors else 0


def print_summary(dicts: dict[str, dict[str, list[str]]]) -> None:
    print(f"[check-i18n] parsed {len(dicts)} namespace(s):")
    for ns, langs in sorted(dicts.items()):
        sizes = ", ".join(f"{lang}={len(keys)}" for lang, keys in sorted(langs.items()))
        print(f"  - {ns}: {sizes}")


def print_result() -> None:
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    if errors:
        print(f"[check-i18n] {len(errors)} error(s), {len(warnings)} warning(s)")
    else:
        print(f"[check-i18n] OK ({len(warnings)} warning(s))")


if __name__ == "__main__":
    sys.exit(main())
