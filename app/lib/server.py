"""
KVMind Integration - Bridge HTTP/WebSocket Server

Universal KVM control platform — supports PiKVM, BliKVM, NanoKVM and more.
Listens on port 8765 (default).

Handler modules are registered via handlers.register_all(app).
See handlers/ for individual route definitions.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from .audit_log import AuditLog
from .bootstrap import ensure_bootstrapped
from .config import get_config
from .device_keys import ensure_keypair
from .kvm import create_backend
from .wifi_manager import WiFiManager
from .kvmind_client import KVMindClient
from .model_router import ModelRouter
from .memory_store import MemoryStore
from .chat_store import ChatStore
from .myclaw_gateway import MyClawGateway
from .uid import get_uid
from .middleware import auth_middleware, WSHub, TRUSTED_PROXIES, start_session_cleaner
from .config import KNOWN_PROVIDERS
from .ai_provider import OpenAIProvider, AnthropicProvider
from .telegram_bot import start_bot, stop_bot
from .handlers import register_all

log = logging.getLogger(__name__)

WEB_DIR = Path("/opt/kvmind/kdkvm/web")


def _build_providers(ai_cfg) -> dict:
    """Create provider instances from config.

    Providers without a user-selected model are skipped with a warning.
    Device code no longer maintains a model catalog (see config.py
    AI Model Catalog Principle), so there is nothing to fall back to.
    """
    provs = {}
    for pcfg in ai_cfg.providers:
        if not pcfg.base_url:
            continue
        requires_key = KNOWN_PROVIDERS.get(pcfg.name, {}).get("requires_key", True)
        if requires_key and not pcfg.api_key:
            continue
        if not pcfg.default_model:
            log.warning(
                "[Startup] Skip provider %s — no model selected. "
                "User must pick a model in MyClaw settings.",
                pcfg.name,
            )
            continue
        if pcfg.name == "anthropic":
            provs[pcfg.name] = AnthropicProvider(pcfg.base_url, pcfg.api_key, pcfg.default_model)
        else:
            provs[pcfg.name] = OpenAIProvider(pcfg.base_url, pcfg.api_key, pcfg.default_model)
    return provs


def create_app() -> web.Application:
    cfg = get_config()

    # Initialize trusted proxies from config
    TRUSTED_PROXIES.clear()
    TRUSTED_PROXIES.update(cfg.bridge.trusted_proxies)
    log.info("[Startup] Trusted proxies: %s", TRUSTED_PROXIES)

    # ── Core services ──────────────────────────────────────────────────────
    kvm = create_backend(cfg.kvm)
    providers = _build_providers(cfg.ai)
    router = ModelRouter(providers, default_timeout=cfg.ai.timeout)

    db_path = cfg.bridge.db_path if hasattr(cfg.bridge, "db_path") else "/var/lib/kvmd/msd/.kdkvm/memory.db"
    memory_store = MemoryStore(db_path)
    chat_store = ChatStore(db_path)
    log.info("[Startup] SQLite store: %s", db_path)

    kvmind = KVMindClient(cfg.ai, router, memory=memory_store)

    if providers:
        log.info("[Startup] AI providers: %s", list(providers.keys()))
    else:
        log.warning("[Startup] No AI providers configured! AI features will not work.")

    audit = AuditLog(cfg.bridge.log_path, cfg.bridge.max_log_size_mb)
    wifi = WiFiManager()
    hub = WSHub()

    # ── MyClaw Gateway (cloud signing) ────────────────────────────────────
    # V6: every outbound kdcms call is signed in-line via the Ed25519
    # keypair at /etc/kdkvm/device_ed25519.key. Gateway construction is
    # unconditional; the signing path lazy-loads the key on first call so
    # process startup doesn't fail if the keypair happens to be missing at
    # import time (e.g. on a freshly flashed device before ensure_keypair
    # runs a few lines below).
    gateway = MyClawGateway(
        cfg=cfg,
        device_uid=get_uid(),
    )
    log.info("[Startup] MyClaw gateway initialized (device=%s)", get_uid())

    # V6: ensure device identity material exists before the heartbeat loop
    # spins up. ``ensure_keypair`` creates /etc/kdkvm/device_ed25519.{key,pub}
    # on first boot and is idempotent afterwards — doing it synchronously
    # here means the first heartbeat / MyClaw call can load the private key
    # without racing the generation path.
    ensure_keypair()

    # ── Lifecycle hooks ────────────────────────────────────────────────────

    async def _start_cloudflared_if_inactive() -> None:
        """0.5.40 hotfix — kdkvm-cloudflared.service has ``Requires=kdkvm.service``,
        which only propagates *stop* in systemd's dependency model.  Any kdkvm
        restart (OTA, on-failure self-heal, manual ``systemctl restart``) leaves
        cloudflared dead; the tunnel hostname then fails to resolve at the
        Cloudflare edge (Error 1033) until something pokes the unit again.

        The original design relied on ``heartbeat._restart_cloudflared()`` to
        fire only on tunnel_token *change*, which doesn't happen on a same-
        subscription restart.  We close the loop here: if the unit is inactive
        when lib.server comes up, kick it once.  Idempotent — a no-op when
        already active, so it's safe on every boot.

        Pure-Python so the OTA updater (which only syncs ``lib/`` / ``web/`` /
        ``bin/`` and skips ``systemd/``) ships the fix without needing
        ``systemctl daemon-reload`` plumbing in the updater itself.
        """
        try:
            check = await asyncio.create_subprocess_exec(
                "/bin/systemctl", "is-active", "--quiet",
                "kdkvm-cloudflared.service",
            )
            if await check.wait() == 0:
                return  # already running
            log.info("[Startup] kdkvm-cloudflared is inactive — starting it")
            start = await asyncio.create_subprocess_exec(
                "/bin/systemctl", "start", "--no-block",
                "kdkvm-cloudflared.service",
            )
            await start.wait()
        except FileNotFoundError:
            # systemctl missing (test runner, container) — silently skip.
            pass
        except Exception as e:
            log.warning("[Startup] cloudflared self-heal failed: %s", e)

    async def on_startup(app: web.Application) -> None:
        await kvm.open()
        # V6: register this device's pubkey with kdcms so every subsequent
        # signed call is verifiable. Best-effort — if kdcms is unreachable
        # at boot, the heartbeat recovery path will retry on the first 401.
        try:
            await ensure_bootstrapped(cfg)
        except Exception as e:
            log.warning("[Startup] ensure_bootstrapped failed: %s", e)
        try:
            await chat_store.cleanup(cfg.bridge.chat_retention_days)
            mem_count = await memory_store.count()
            if mem_count > 500:
                await memory_store.cleanup(days=30)
            log.info("[Startup] DB maintenance done (memories: %d)", mem_count)
        except Exception as e:
            log.warning("[Startup] DB maintenance error: %s", e)
        await _start_cloudflared_if_inactive()
        log.info("KVMind Bridge started on :%d", cfg.bridge.port)

    async def on_shutdown(app: web.Application) -> None:
        await kvm.close()
        memory_store.close()
        chat_store.close()
        # R4-CQ-04: release the shared aiohttp ClientSession pools so the
        # underlying connector fires its __del__ cleanly instead of warning.
        from . import ai_provider as _ai_provider
        from . import myclaw_gateway as _myclaw_gateway
        try:
            await _ai_provider.close_shared_session()
        except Exception as e:
            log.warning("[Shutdown] ai_provider session close failed: %s", e)
        try:
            await _myclaw_gateway.close_shared_session()
        except Exception as e:
            log.warning("[Shutdown] myclaw_gateway session close failed: %s", e)

    # ── Telegram Bot ───────────────────────────────────────────────────────
    # Lifecycle unified via telegram_bot.start_bot/stop_bot — shared with
    # handlers/subscription.py (subscription activation) and handlers/ai_config.py
    # (AI config save). start_bot gates on cfg.subscription.messaging +
    # bot_token internally, so we always register the hook and let it no-op
    # when disabled. Keeps gateway injection and task binding in one place.

    async def _on_startup_telegram(app: web.Application) -> None:
        start_bot(app, cfg)

    async def _on_cleanup_telegram(app: web.Application) -> None:
        stop_bot(app)

    # ── Build app ──────────────────────────────────────────────────────────

    app = web.Application(middlewares=[auth_middleware])
    start_session_cleaner(app)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_startup.append(_on_startup_telegram)
    app.on_cleanup.append(_on_cleanup_telegram)

    # Store shared dependencies in app dict (handlers access via req.app)
    app["cfg"] = cfg
    app["kvm"] = kvm
    app["kvmind"] = kvmind
    app["providers"] = providers
    app["router"] = router
    app["audit"] = audit
    app["memory_store"] = memory_store
    app["chat_store"] = chat_store
    app["hub"] = hub
    app["wifi"] = wifi
    app["gateway"] = gateway
    app["web_dir"] = WEB_DIR

    # Register all handler routes
    register_all(app)

    # M3.4: in-process heartbeat loop replaces kvmind-heartbeat.sh/.timer.
    # Kept behind cfg.bridge.heartbeat_enabled so unit tests can disable it.
    hb_enabled = getattr(cfg.bridge, "heartbeat_enabled", True)
    if hb_enabled:
        from .heartbeat import start_heartbeat
        interval = int(getattr(cfg.bridge, "heartbeat_interval_seconds", 60))
        start_heartbeat(app, interval_seconds=interval)

    # Static files (catch-all, must be last)
    if WEB_DIR.exists():
        app.router.add_static("/static/", WEB_DIR, show_index=False)

    return app


def main() -> None:
    cfg = get_config()
    logging.basicConfig(
        level=logging.DEBUG if cfg.bridge.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app()
    web.run_app(app, host=cfg.bridge.host, port=cfg.bridge.port)


if __name__ == "__main__":
    main()
