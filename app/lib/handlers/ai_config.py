"""AI configuration handlers — models, config get/save, connection test."""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

from ..config import KNOWN_PROVIDERS, ProviderConfig, save_config
from ..ai_provider import OpenAIProvider, AnthropicProvider
from ..model_router import ModelRouter
from ..kvmind_client import KVMindClient
from ..subscription_binder import bind_subscription_key
from .helpers import json_response

log = logging.getLogger("kvmind.handlers.ai_config")


def _build_providers(ai_cfg) -> dict:
    """Create provider instances from config (with default_model)."""
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


def _rebuild_router(cfg, memory=None) -> tuple:
    """Build new providers, router, and KVMindClient from config."""
    providers = _build_providers(cfg.ai)
    router = ModelRouter(providers, default_timeout=cfg.ai.timeout)
    kvmind = KVMindClient(cfg.ai, router, memory=memory)
    log.info("[Registry] Rebuilt providers: %s", list(providers.keys()))
    return providers, router, kvmind


def _start_telegram(app, token, cfg, kvm, kvmind, audit) -> bool:
    """Start (or restart) the Telegram bot with a new token."""
    if not cfg.subscription.messaging:
        return False
    cfg.telegram.bot_token = token
    old_task = app.get("telegram_task")
    if old_task:
        old_task.cancel()
    from ..telegram_bot import TelegramBot
    tg_bot = TelegramBot(
        token=token, kvm=kvm, kvmind=kvmind, audit=audit,
        allowed_chats=cfg.telegram.allowed_chats or None,
    )
    app["telegram_task"] = asyncio.create_task(tg_bot.start())
    log.info("[Telegram] Bot (re)started via config save")
    return True


async def _test_tool_calling(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    model: str,
) -> bool:
    """Send a small tool-calling request to check if the model supports it."""
    payload = {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Type 'hello' on the keyboard"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "type_text",
                "description": "Type text on the keyboard",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }],
    }
    async with session.post(url, json=payload, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=30),
                            ssl=url.startswith("https://")) as r:
        if r.status != 200:
            return False
        data = await r.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        return bool(msg.get("tool_calls"))


def register(app: dict) -> None:
    """Register AI config routes on the aiohttp app."""

    cfg = app["cfg"]
    kvm = app["kvm"]
    audit = app["audit"]

    async def h_ai_models(req: web.Request) -> web.Response:
        """GET /api/ai/models -- return known model list for a provider."""
        provider = req.query.get("provider", "")
        info = KNOWN_PROVIDERS.get(provider)
        if not info:
            return json_response({"error": f"Unknown provider: {provider}"}, status=400)
        return json_response({
            "provider": provider,
            "models": info.get("models", []),
            "default": info.get("default_model", ""),
            "base_url": info.get("base_url", ""),
            "display_name": info.get("display_name", provider),
            "requires_key": info.get("requires_key", True),
        })

    async def h_ai_config_get(req: web.Request) -> web.Response:
        """GET /api/ai/config -- return current AI configuration."""
        providers = app["providers"]
        providers_info = []
        for p in cfg.ai.providers:
            known = KNOWN_PROVIDERS.get(p.name, {})
            key_configured = bool(p.api_key and p.api_key != "none")
            preview = p.api_key[:4] + "***" + p.api_key[-2:] if key_configured else ""
            providers_info.append({
                "name": p.name,
                "default_model": p.default_model,
                "base_url": p.base_url,
                "api_key_preview": preview,
                "api_key_configured": key_configured,
                "display_name": known.get("display_name", p.name),
                "requires_key": known.get("requires_key", p.name != "custom"),
            })
        return json_response({
            "providers": providers_info,
            "active_providers": list(providers.keys()),
            "mode": cfg.bridge.mode,
            "plan_type": "custom" if cfg.ai.providers else "free_trial",
            "subscription": {
                "plan": cfg.subscription.plan,
                "messaging": cfg.subscription.messaging,
            },
            "telegram_configured": bool(cfg.telegram.bot_token),
            "wechat_configured": False,
            "line_configured": False,
            "supports_tools": cfg.ai.supports_tools,
        })

    async def h_ai_config_save(req: web.Request) -> web.Response:
        """POST /api/ai/config -- save AI configuration and rebuild router."""
        body = await req.json()

        # ── Bridge mode ──
        cfg.bridge.mode = body.get("mode", cfg.bridge.mode)

        # ── Provider keys ──
        new_providers_list = []

        for pname, info in KNOWN_PROVIDERS.items():
            requires_key = info.get("requires_key", True)
            key = body.get(info["config_key"], "").strip()
            model = body.get(f"{pname}_model", info["default_model"])
            enabled = body.get(f"{pname}_enabled", False)
            custom_url = body.get(f"{pname}_url", "").strip()
            if key or (not requires_key and (enabled or custom_url)):
                new_providers_list.append(ProviderConfig(
                    name=pname,
                    base_url=custom_url or info["base_url"],
                    api_key=key,
                    default_model=model,
                    source="ui",
                ))

        custom = body.get("custom_provider")
        if custom and isinstance(custom, dict):
            cu_url = custom.get("base_url", "").strip()
            cu_key = custom.get("api_key", "").strip()
            cu_model = custom.get("model", "").strip()
            if cu_url and cu_model:
                new_providers_list.append(ProviderConfig(
                    name="custom",
                    base_url=cu_url,
                    api_key=cu_key or "none",
                    default_model=cu_model,
                    source="ui",
                ))

        if new_providers_list:
            cfg.ai.providers = new_providers_list

        # ── Rebuild router ──
        new_providers, new_router, new_kvmind = _rebuild_router(
            cfg, memory=req.app.get("memory_store"),
        )
        app["providers"] = new_providers
        app["router"] = new_router
        app["kvmind"] = new_kvmind

        # ── Subscription binding ──
        sub_key = body.get("subscription_key", "").strip()
        if sub_key:
            result = await bind_subscription_key(cfg, sub_key)
            if "error" in result:
                return json_response(
                    {"error": result["error"], "message": result["message"]},
                    status=result.get("status", 400),
                )

        # ── Tool support flag (from last test result) ──
        if "supports_tools" in body:
            cfg.ai.supports_tools = bool(body["supports_tools"])

        # ── Messaging channels ──
        channels_started: list[str] = []
        tg_token = body.get("telegram_token", "").strip()
        if tg_token:
            if not cfg.subscription.messaging:
                return json_response({
                    "error": "messaging_not_enabled",
                    "message": "Telegram requires an active subscription",
                }, status=403)
            kvmind = app["kvmind"]
            if _start_telegram(req.app, tg_token, cfg, kvm, kvmind, audit):
                channels_started.append("telegram")

        # ── Persist ──
        try:
            save_config(cfg)
        except Exception as e:
            log.warning("Failed to save config: %s", e)

        return json_response({
            "status": "ok",
            "active_providers": list(new_providers.keys()),
            "channels_started": channels_started,
        })

    async def h_ai_test(req: web.Request) -> web.Response:
        """POST /api/ai/test -- test AI connection."""
        body = await req.json()
        provider = body.get("provider", "anthropic")
        api_key = body.get("api_key", "")
        model = body.get("model", "")
        info = KNOWN_PROVIDERS.get(provider)
        requires_key = info.get("requires_key", True) if info else provider != "custom"
        if requires_key and not api_key:
            return json_response({"success": False, "error": "API Key is required"})
        try:
            if provider == "anthropic":
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model or "claude-sonnet-4-20250514",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hi"}],
                }
                url = "https://api.anthropic.com/v1/messages"
            elif provider == "gemini":
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model or "gemini-2.5-flash",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hi"}],
                }
                url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            else:
                headers = {
                    "Content-Type": "application/json",
                }
                if api_key and api_key != "none":
                    headers["Authorization"] = f"Bearer {api_key}"
                default_model = info.get("default_model", "gpt-4o") if info else "gpt-4o"
                payload = {
                    "model": model or default_model,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hi"}],
                }
                base_url = body.get("base_url", "").strip()
                if not base_url and info:
                    base_url = info.get("base_url", "")
                if not base_url and provider == "custom":
                    return json_response({"success": False, "error": "Base URL is required"})
                if not base_url:
                    url = "https://api.openai.com/v1/chat/completions"
                else:
                    url = base_url.rstrip("/") + "/chat/completions"

            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=30),
                                  ssl=url.startswith("https://")) as r:
                    if r.status != 200:
                        body_text = await r.text()
                        return json_response({"success": False, "error": f"HTTP {r.status}: {body_text[:200]}"})

                supports_tools = True
                if provider != "anthropic":
                    try:
                        supports_tools = await _test_tool_calling(
                            s, url, headers, payload.get("model", ""),
                        )
                    except Exception:
                        supports_tools = False

                return json_response({
                    "success": True,
                    "provider": provider,
                    "supports_tools": supports_tools,
                })
        except Exception as e:
            return json_response({"success": False, "error": str(e)})

    # ── Route registration ──────────────────────────────────────────────────

    app.router.add_get("/api/ai/models", h_ai_models)
    app.router.add_get("/api/ai/config", h_ai_config_get)
    app.router.add_post("/api/ai/config", h_ai_config_save)
    app.router.add_post("/api/ai/test", h_ai_test)
