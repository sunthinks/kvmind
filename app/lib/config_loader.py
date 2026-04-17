"""
Configuration Loader — multi-source config resolution.

Reads from YAML, environment variables, and legacy formats.
Handles provider key priority, env overrides, and backward compatibility.

Extracted from config.py to separate loading concerns from dataclass definitions.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .config import AIConfig, Config

from .config import KNOWN_PROVIDERS, ProviderConfig

log = logging.getLogger(__name__)


def load_config(path: str) -> "Config":
    """Load configuration from YAML file + environment variables.

    This is the single entry point for all config loading.
    """
    from .config import Config

    cfg = Config()
    raw: dict = {}
    p = Path(path)
    if p.exists():
        with open(p) as f:
            raw = yaml.safe_load(f) or {}

    # ── KVM hardware backend ──
    kvm_raw = raw.get("kvm") or raw.get("pikvm") or {}
    for k, v in kvm_raw.items():
        if hasattr(cfg.kvm, k):
            setattr(cfg.kvm, k, v)

    # ── AI providers (multiple sources, merged) ──
    _load_ai_config(cfg.ai, raw)

    # ── Bridge ──
    if "bridge" in raw:
        for k, v in raw["bridge"].items():
            if hasattr(cfg.bridge, k):
                setattr(cfg.bridge, k, v)

    # ── Telegram ──
    if "telegram" in raw:
        tg = raw["telegram"]
        cfg.telegram.bot_token = (tg.get("bot_token") or "").strip()
        cfg.telegram.allowed_chats = tg.get("allowed_chats") or []
    tg_token_env = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tg_token_env:
        cfg.telegram.bot_token = tg_token_env

    # ── Subscription (read-only, synced by heartbeat) ──
    if "subscription" in raw:
        sub = raw["subscription"]
        cfg.subscription.plan = sub.get("plan", "community")
        cfg.subscription.tunnel = bool(sub.get("tunnel", False))
        cfg.subscription.messaging = bool(sub.get("messaging", False))
        cfg.subscription.ota = bool(sub.get("ota", False))
        cfg.subscription.synced_at = sub.get("synced_at", "")
        cfg.subscription.myclaw_limit = int(sub.get("myclaw_limit", 5))
        cfg.subscription.myclaw_daily_limit = int(sub.get("myclaw_daily_limit", 20))
        cfg.subscription.myclaw_max_action_level = int(sub.get("myclaw_max_action_level", 1))
        cfg.subscription.scheduled_tasks = bool(sub.get("scheduled_tasks", False))
    elif "ai" in raw and "plan_type" in raw["ai"]:
        old_pt = (raw["ai"].get("plan_type", "") or "").strip()
        if old_pt == "subscribed":
            cfg.subscription.plan = "standard"
            cfg.subscription.tunnel = True
            cfg.subscription.messaging = True
            cfg.subscription.ota = True

    # ── Simple env var overrides ──
    _apply_env_overrides(cfg)

    return cfg


def _apply_env_overrides(cfg: "Config") -> None:
    """Apply environment variable overrides to config."""
    env_map = {
        "KVM_BACKEND": ("kvm", "backend"),
        "KVM_TRANSPORT": ("kvm", "transport"),
        "KVM_UNIX_SOCKET": ("kvm", "unix_socket"),
        "PIKVM_HOST": ("kvm", "host"),
        "PIKVM_PORT": ("kvm", "port"),
        "PIKVM_USER": ("kvm", "username"),
        "PIKVM_PASS": ("kvm", "password"),
        "BRIDGE_PORT": ("bridge", "port"),
        "BRIDGE_MODE": ("bridge", "mode"),
    }
    for env_key, (section, attr) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            obj = getattr(cfg, section)
            current = getattr(obj, attr)
            if isinstance(current, int):
                val = int(val)
            elif isinstance(current, bool):
                val = val.lower() in ("1", "true", "yes")
            setattr(obj, attr, val)


def _load_ai_config(ai: "AIConfig", raw: dict) -> None:
    """Load AI provider configuration from multiple sources.

    Priority (highest first):
      1. Environment variables (GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.)
      2. config.yaml shorthand (ai.gemini_key, ai.claude_key)
      3. config.yaml advanced (ai.providers list)
      4. config.yaml legacy (kvmind: section)
      5. Legacy env var (AI_API_KEY + AI_BASE_URL)
    """
    ai_raw = raw.get("ai", {})
    seen_providers: set = set()

    # ── Source 1+2: env vars + config shorthand keys ──
    for name, info in KNOWN_PROVIDERS.items():
        requires_key = info.get("requires_key", True)

        key = None
        key_source = "config"
        for env_name in info["key_envs"]:
            key = os.environ.get(env_name, "").strip()
            if key:
                key_source = "env"
                break

        if not key:
            key = (ai_raw.get(info["config_key"], "") or "").strip()

        if not requires_key and not key:
            enabled_flag = ai_raw.get(f"{name}_enabled", False)
            custom_url = (ai_raw.get(f"{name}_url", "") or "").strip()
            if enabled_flag or custom_url:
                key = "no-key-required"

        if key:
            base_url = info["base_url"]
            custom_url = (ai_raw.get(f"{name}_url", "") or "").strip()
            if custom_url:
                base_url = custom_url
            model = (ai_raw.get(f"{name}_model", "") or "").strip() or info["default_model"]
            ai.providers.append(ProviderConfig(
                name=name,
                base_url=base_url,
                api_key=key if requires_key else (key if key != "no-key-required" else ""),
                default_model=model,
                source=key_source,
            ))
            seen_providers.add(name)
            log.info("[Config] Provider '%s' loaded%s", name,
                     f" (key: {key[:8]}***)" if key and key != "no-key-required" else " (no key required)")

    # ── Source 3: advanced ai.providers list ──
    if "providers" in ai_raw:
        for prov_raw in ai_raw["providers"]:
            pname = prov_raw.get("name", "")
            if pname in seen_providers:
                continue
            requires_key = KNOWN_PROVIDERS.get(pname, {}).get("requires_key", True)
            pkey = (prov_raw.get("api_key", "") or "").strip()
            if requires_key and not pkey:
                continue
            ai.providers.append(ProviderConfig(
                name=pname,
                base_url=prov_raw.get("base_url", ""),
                api_key=pkey,
                default_model=prov_raw.get("default_model", ""),
            ))
            seen_providers.add(pname)

    # ── Source 4: legacy kvmind: section ──
    if not ai.providers and "kvmind" in raw:
        kv = raw["kvmind"]
        legacy_key = (kv.get("api_key", "") or "").strip()
        if legacy_key:
            host = kv.get("host", "localhost")
            port = kv.get("port", 8080)
            scheme = "https" if port == 443 else "http"
            port_suffix = "" if port in (80, 443) else f":{port}"
            base_url = f"{scheme}://{host}{port_suffix}"
            name = "gemini"
            if "anthropic" in base_url:
                name = "anthropic"
            elif "openai.com" in base_url:
                name = "openai"
            if "googleapis" in base_url and "/v1beta" not in base_url:
                base_url += "/v1beta/openai"
            ai.providers.append(ProviderConfig(
                name=name, base_url=base_url,
                api_key=legacy_key, default_model=kv.get("model", "default"),
            ))
            log.info("[Config] Provider '%s' loaded from legacy kvmind config", name)

    # ── Source 5: legacy AI_API_KEY env var (from ai.env) ──
    if not ai.providers:
        legacy_key = os.environ.get("AI_API_KEY", "").strip()
        if legacy_key:
            legacy_url = os.environ.get("AI_BASE_URL", "").strip()
            legacy_model = os.environ.get("AI_MODEL", "").strip()
            name = "gemini"
            base_url = KNOWN_PROVIDERS["gemini"]["base_url"]
            default_model = legacy_model or KNOWN_PROVIDERS["gemini"]["default_model"]
            if legacy_url:
                if "anthropic" in legacy_url:
                    name = "anthropic"
                    base_url = legacy_url
                    default_model = legacy_model or KNOWN_PROVIDERS["anthropic"]["default_model"]
                elif "openai.com" in legacy_url:
                    name = "openai"
                    base_url = legacy_url
                    default_model = legacy_model or KNOWN_PROVIDERS["openai"]["default_model"]
                elif "googleapis" in legacy_url:
                    base_url = legacy_url
                    if "/v1beta" not in base_url:
                        base_url += "/v1beta/openai"
                else:
                    name = "openai"
                    base_url = legacy_url
            ai.providers.append(ProviderConfig(
                name=name, base_url=base_url,
                api_key=legacy_key, default_model=default_model,
                source="env",
            ))
            log.info("[Config] Provider '%s' loaded from AI_API_KEY env var", name)

    # ── AI timeout/max_tokens ──
    if ai_raw:
        ai.timeout = ai_raw.get("timeout", ai.timeout)
        ai.max_tokens = ai_raw.get("max_tokens", ai.max_tokens)
        ai.supports_tools = ai_raw.get("supports_tools", ai.supports_tools)
        ai.allow_local_execution = ai_raw.get("allow_local_execution", ai.allow_local_execution)
    elif "kvmind" in raw:
        kv = raw["kvmind"]
        ai.timeout = kv.get("timeout", ai.timeout)
        ai.max_tokens = kv.get("max_tokens", ai.max_tokens)

    if not ai.providers:
        log.warning("[Config] No AI providers configured! Set GEMINI_API_KEY or ai.gemini_key in config.yaml")
