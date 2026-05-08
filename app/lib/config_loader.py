"""
Configuration Loader — multi-source config resolution.

Reads from YAML and environment variables.
Handles provider key priority and env overrides.

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

    # ── Subscription (V1 Seat 模型 · read-only, synced by heartbeat) ──
    if "subscription" in raw:
        sub = raw["subscription"]
        cfg.subscription.claim_state = sub.get("claim_state", "unclaimed")
        cfg.subscription.entitlement_state = sub.get("entitlement_state", "local_free")
        asid = sub.get("assigned_subscription_id")
        cfg.subscription.assigned_subscription_id = int(asid) if asid is not None else None
        cfg.subscription.tunnel = bool(sub.get("tunnel", False))
        cfg.subscription.messaging = bool(sub.get("messaging", False))
        cfg.subscription.ota = bool(sub.get("ota", False))
        cfg.subscription.synced_at = sub.get("synced_at", "")
        cfg.subscription.myclaw_limit = int(sub.get("myclaw_limit", 5))
        cfg.subscription.myclaw_daily_limit = int(sub.get("myclaw_daily_limit", 20))
        cfg.subscription.myclaw_max_action_level = int(sub.get("myclaw_max_action_level", 1))
        cfg.subscription.scheduled_tasks = bool(sub.get("scheduled_tasks", False))

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
            # No fallback to a built-in default model — device code no longer
            # maintains a model catalog (see config.py AI Model Catalog Principle).
            # An empty default_model means the user hasn't picked one yet;
            # ai_config._build_providers skips such entries with a warning.
            model = (ai_raw.get(f"{name}_model", "") or "").strip()
            ai.providers.append(ProviderConfig(
                name=name,
                base_url=base_url,
                api_key=key if requires_key else (key if key != "no-key-required" else ""),
                default_model=model,
                source=key_source,
            ))
            seen_providers.add(name)
            log.info("[Config] Provider '%s' loaded%s model=%s", name,
                     f" (key: {key[:8]}***)" if key and key != "no-key-required" else " (no key required)",
                     model or "<unset>")

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

    # ── AI timeout/max_tokens ──
    if ai_raw:
        ai.timeout = ai_raw.get("timeout", ai.timeout)
        ai.max_tokens = ai_raw.get("max_tokens", ai.max_tokens)
        ai.supports_tools = ai_raw.get("supports_tools", ai.supports_tools)

    if not ai.providers:
        log.warning("[Config] No AI providers configured! Set GEMINI_API_KEY or ai.gemini_key in config.yaml")
