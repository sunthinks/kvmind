"""
M3.4 (plan §16): ``kdkvm`` CLI entrypoint.

Small surface on purpose — the CLI only exists so systemd units can
read/write state.db without shelling through Python boilerplate. All
real business logic lives in the main ``kdkvm.service`` process; this
module is glue.

Subcommands:

  kdkvm tunnel-token
      Print the Cloudflare tunnel token from ``state.db`` (key
      ``tunnel_token``) to stdout, then exit. Invoked by
      ``kdkvm-cloudflared.service`` as its ExecStart token source so we
      don't have to write the secret to a file on disk.

  kdkvm reset
      Wipe activation + AI keys + tunnel token from ``state.db``. Used
      by the operator's "factory reset" flow; the service unit still
      needs a separate ``systemctl stop kdkvm.service`` around this.

  kdkvm status
      Print a human-readable dump of ``state.db`` and current activation
      state. Diagnostic only.

The module deliberately avoids any aiohttp / network I/O — anything
that requires the backend must go through the running service.
"""
from __future__ import annotations

import argparse
import json
import sys

from .state_db import get_state_db
from .state_store import read_raw as _read_state_raw


def _cmd_tunnel_token(_args) -> int:
    # 0.5.25: read state.json directly so the CLI invocation (called every
    # time kdkvm-cloudflared.service starts) doesn't trigger StateStore init
    # side effects (writing an empty schema if missing, migration). The main
    # kdkvm.service owns init; this CLI is a pure reader.
    data = _read_state_raw()
    token = data.get("kv", {}).get("tunnel_token", "") or ""
    # Print with no trailing newline — systemd $(...) substitution does
    # NOT strip stdin, and cloudflared rejects tokens with whitespace.
    sys.stdout.write(token)
    sys.stdout.flush()
    return 0


def _cmd_reset(args) -> int:
    """Factory reset — wipe activation, keypair, and bootstrap state.

    V6: the device's identity is now the Ed25519 private key at
    ``/etc/kdkvm/device_ed25519.key``. A reset has to unlink it too, or the
    user ends up with a device that kdcms still knows the old pubkey for
    and a clean activation flow that never completes because the cached
    ``bootstrap_done`` flag short-circuits re-registration.

    Order matters:
      1. Clear activation (customer binding + needs_reactivation banner).
      2. Delete the keypair (so the next boot generates a fresh one).
      3. Clear ``bootstrap_done`` + ``bound_customer_id`` (so the next boot
         re-registers the *new* pubkey with kdcms instead of thinking it's
         already done).
      4. Wipe tunnel_token (it was scoped to the old identity).
    """
    from .device_keys import delete_keypair

    delete_keypair()
    db = get_state_db()
    for kv_key in ("bootstrap_done", "bound_customer_id", "bound_customer_email",
                   "needs_reactivation", "tunnel_token"):
        db.kv_delete(kv_key)
    if args.wipe_ai_keys:
        for row in db.list_ai_keys():
            db.delete_ai_key(row["provider"])
    sys.stderr.write(
        "kdkvm state reset (activation + keypair + bootstrap + tunnel cleared)\n"
    )
    return 0


def _cmd_status(_args) -> int:
    # 0.5.25: read-only path — direct JSON load, no StateStore init (so
    # install.sh / operator probes don't accidentally create state.json
    # before the main service has had a chance to populate it).
    data = _read_state_raw()
    kv = data.get("kv", {})
    tunnel = kv.get("tunnel_token", "") or ""
    ai_providers = sorted(data.get("ai_keys", {}).keys())
    # Read UID without triggering generate-on-first-call side effect —
    # `status` must be side-effect-free so install.sh can probe before
    # the first service start.
    from pathlib import Path as _Path
    from .uid import UID_PATH as _UID_PATH
    device_uid = None
    try:
        _p = _Path(_UID_PATH)
        if _p.exists():
            val = _p.read_text().strip()
            if val:
                device_uid = val
    except OSError:
        pass
    bound_email = kv.get("bound_customer_email")
    out = {
        "device_uid": device_uid,
        "activated": bound_email is not None,
        "bound_customer_email": bound_email,
        "bootstrap_done": (kv.get("bootstrap_done") or "").lower() == "true",
        "needs_reactivation": (kv.get("needs_reactivation") or "").lower() == "true",
        "tunnel_token_present": bool(tunnel),
        "ai_providers": ai_providers,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="kdkvm",
        description="kdkvm device CLI — state.db glue for systemd + operators.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "tunnel-token",
        help="Print the Cloudflare tunnel token from state.db to stdout.",
    )

    reset = sub.add_parser(
        "reset",
        help="Wipe activation + tunnel_token from state.db.",
    )
    reset.add_argument(
        "--wipe-ai-keys", action="store_true",
        help="Also drop stored AI provider keys (default: preserve).",
    )

    sub.add_parser(
        "status",
        help="Print a JSON summary of state.db.",
    )

    args = parser.parse_args(argv)
    if args.command == "tunnel-token":
        return _cmd_tunnel_token(args)
    if args.command == "reset":
        return _cmd_reset(args)
    if args.command == "status":
        return _cmd_status(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
