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
from .config import get_config
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
from .handlers import register_all

log = logging.getLogger(__name__)

WEB_DIR = Path("/opt/kvmind/kdkvm/web")


def _build_providers(ai_cfg) -> dict:
    """Create provider instances from config."""
    provs = {}
    for pcfg in ai_cfg.providers:
        if not pcfg.base_url:
            continue
        requires_key = KNOWN_PROVIDERS.get(pcfg.name, {}).get("requires_key", True)
        if requires_key and not pcfg.api_key:
            continue
        model = pcfg.default_model or KNOWN_PROVIDERS.get(pcfg.name, {}).get("default_model", "default")
        if pcfg.name == "anthropic":
            provs[pcfg.name] = AnthropicProvider(pcfg.base_url, pcfg.api_key, model)
        else:
            provs[pcfg.name] = OpenAIProvider(pcfg.base_url, pcfg.api_key, model)
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
    gateway = None
    token_path = Path("/etc/kdkvm/device.token")
    if token_path.exists():
        device_token = token_path.read_text().strip()
        if device_token:
            gateway = MyClawGateway(
                backend_url=cfg.bridge.backend_url,
                device_uid=get_uid(),
                device_token=device_token,
            )
            log.info("[Startup] MyClaw gateway initialized (device=%s)", get_uid())
    if not gateway:
        log.info("[Startup] MyClaw gateway not available (device not registered)")

    # ── Lifecycle hooks ────────────────────────────────────────────────────

    async def on_startup(app: web.Application) -> None:
        await kvm.open()
        try:
            await chat_store.cleanup(cfg.bridge.chat_retention_days)
            mem_count = await memory_store.count()
            if mem_count > 500:
                await memory_store.cleanup(days=30)
            log.info("[Startup] DB maintenance done (memories: %d)", mem_count)
        except Exception as e:
            log.warning("[Startup] DB maintenance error: %s", e)
        log.info("KVMind Bridge started on :%d", cfg.bridge.port)

    async def on_shutdown(app: web.Application) -> None:
        await kvm.close()
        memory_store.close()
        chat_store.close()

    # ── Telegram Bot (conditional startup) ─────────────────────────────────

    start_telegram = None
    stop_telegram = None

    if cfg.telegram.bot_token and cfg.subscription.messaging:
        from .telegram_bot import TelegramBot
        tg_bot = TelegramBot(
            token=cfg.telegram.bot_token,
            kvm=kvm,
            kvmind=kvmind,
            audit=audit,
            allowed_chats=cfg.telegram.allowed_chats or None,
            gateway=gateway,
        )

        async def start_telegram(app: web.Application) -> None:
            app["telegram_task"] = asyncio.create_task(tg_bot.start())
            log.info("[Telegram] Bot started (allowed_chats=%s)",
                     cfg.telegram.allowed_chats or "all")

        async def stop_telegram(app: web.Application) -> None:
            tg_bot.stop()
            task = app.get("telegram_task")
            if task:
                task.cancel()
            log.info("[Telegram] Bot stopped")
    else:
        if cfg.telegram.bot_token:
            log.info("[Telegram] Bot configured but messaging not enabled (subscription required)")

    # ── Build app ──────────────────────────────────────────────────────────

    app = web.Application(middlewares=[auth_middleware])
    start_session_cleaner(app)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    if start_telegram:
        app.on_startup.append(start_telegram)
        app.on_cleanup.append(stop_telegram)

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
