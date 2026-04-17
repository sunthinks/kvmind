"""
KVMind Integration - Configuration Module

Reads from /etc/kdkvm/config.yaml, environment variables, or both.

Provider key resolution (highest priority first):
  1. Environment variables: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY
  2. Legacy env var: AI_API_KEY (from ai.env)
  3. config.yaml shorthand: ai.gemini_key, ai.claude_key, ai.openai_key
  4. config.yaml advanced: ai.providers list
  5. config.yaml legacy: kvmind.api_key
"""
from __future__ import annotations

import logging
import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("KVMIND_KVM_CONFIG", "/etc/kdkvm/config.yaml")


# ── Known provider definitions (code-builtin knowledge) ─────────────────────

KNOWN_PROVIDERS: Dict[str, Dict] = {
    "ollama": {
        # No default URL — user must enter the full URL of their Ollama server
        # during setup, e.g. "http://192.168.1.50:11434/v1". Shipping a LAN IP
        # as default leaks the developer's environment and wastes every other
        # user's first-run (requests disappear into the void and surface as a
        # 502 on /api/analyse with no hint of the cause).
        "base_url": "",
        "default_model": "qwen3-vl:8b",
        "models": ["qwen3-vl:8b", "qwen3-vl:2b"],
        "key_envs": ["OLLAMA_API_KEY"],
        "config_key": "ollama_key",
        "display_name": "Ollama",
        "requires_key": False,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "key_envs": ["GEMINI_API_KEY"],
        "config_key": "gemini_key",
        "display_name": "Gemini",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-6-20250819",
        "models": ["claude-sonnet-4-6-20250819", "claude-opus-4-6-20250819", "claude-haiku-4-5-20251001", "claude-sonnet-4-20250514"],
        "key_envs": ["ANTHROPIC_API_KEY"],
        "config_key": "claude_key",
        "display_name": "Claude",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini"],
        "key_envs": ["OPENAI_API_KEY"],
        "config_key": "openai_key",
        "display_name": "ChatGPT",
    },
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class KVMConfig:
    """Hardware backend configuration (supports pikvm, nanokvm, blikvm)."""
    backend: str = "pikvm"       # "pikvm" | "nanokvm" | "blikvm"
    transport: str = "unix"      # "unix" (local kvmd socket) | "tcp" (explicit remote/dev mode)
    unix_socket: str = "/run/kvmd/kvmd.sock"
    host: str = "localhost"
    port: int = 443
    https: bool = True
    username: str = "admin"
    password: str = "admin"
    ws_path: str = "/api/ws"

    @property
    def base_url(self) -> str:
        scheme = "https" if self.https else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self.https else "ws"
        return f"{scheme}://{self.host}:{self.port}{self.ws_path}"


@dataclass
class ProviderConfig:
    """Configuration for a single AI provider."""
    name: str = ""              # "gemini" / "anthropic" / "openai"
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    source: str = "config"      # "env" | "config" | "ui" — where the key came from


@dataclass
class AIConfig:
    """Multi-provider AI configuration."""
    providers: List[ProviderConfig] = field(default_factory=list)
    timeout: int = 120
    max_tokens: int = 4096
    supports_tools: bool = True
    allow_local_execution: bool = False  # True = dev/offline mode allows unsigned tool execution

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        for p in self.providers:
            if p.name == name:
                return p
        return None


@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = False
    log_path: str = "/var/log/kdkvm/audit.log"
    max_log_size_mb: int = 100
    auto_inspect_interval: int = 0   # seconds, 0 = disabled
    confirm_dangerous_ops: bool = True
    mode: str = "suggest"            # "suggest" | "auto"
    password: str = "admin"          # Bridge login password
    db_path: str = "/var/lib/kvmd/msd/.kdkvm/memory.db"  # SQLite on MSD partition (p4, persistent ext4)
    chat_retention_days: int = 30    # auto-cleanup chat older than N days
    backend_url: str = ""  # Optional cloud backend URL (leave empty for fully local/air-gapped mode)
    trusted_proxies: List[str] = field(default_factory=lambda: ["127.0.0.1"])


@dataclass
class TelegramConfig:
    bot_token: str = ""
    allowed_chats: List[int] = field(default_factory=list)


@dataclass
class SubscriptionConfig:
    """订阅状态 — 只读，由 heartbeat 覆盖，用户改了下次心跳覆盖回来"""
    plan: str = "community"          # community / standard / pro
    tunnel: bool = False
    messaging: bool = False
    ota: bool = False
    synced_at: str = ""              # ISO timestamp，最后一次心跳同步时间
    myclaw_limit: int = 5            # 每小时 MyClaw 次数限制 (-1 无限)
    myclaw_daily_limit: int = 20     # 每日 MyClaw 次数限制 (-1 无限)
    myclaw_max_action_level: int = 1 # 最高 action 等级 (1/2/3)
    scheduled_tasks: bool = False    # 是否允许定时任务


@dataclass
class Config:
    kvm: KVMConfig = field(default_factory=KVMConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    subscription: SubscriptionConfig = field(default_factory=SubscriptionConfig)

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Config":
        from .config_loader import load_config
        return load_config(path)


def save_config(cfg: Config, path: str = CONFIG_PATH) -> None:
    """Save configuration to YAML file."""
    data: dict = {}
    p = Path(path)

    # Preserve existing file structure
    if p.exists():
        with open(p) as f:
            data = yaml.safe_load(f) or {}

    # KVM hardware backend
    data["kvm"] = {
        "backend": cfg.kvm.backend,
        "transport": cfg.kvm.transport,
        "unix_socket": cfg.kvm.unix_socket,
        "host": cfg.kvm.host,
        "port": cfg.kvm.port,
        "https": cfg.kvm.https,
        "username": cfg.kvm.username,
        "password": cfg.kvm.password,
    }
    data.pop("pikvm", None)  # Remove legacy section

    # AI — write shorthand format
    ai_section: dict = {
        "timeout": cfg.ai.timeout,
        "max_tokens": cfg.ai.max_tokens,
        "supports_tools": cfg.ai.supports_tools,
        "allow_local_execution": cfg.ai.allow_local_execution,
    }
    for prov in cfg.ai.providers:
        # Skip env-sourced API keys — never persist secrets from environment to disk
        if prov.source == "env":
            continue
        known = KNOWN_PROVIDERS.get(prov.name)
        if known:
            if prov.api_key:
                ai_section[known["config_key"]] = prov.api_key
            if not known.get("requires_key", True):
                ai_section[f"{prov.name}_enabled"] = True
            if prov.default_model and prov.default_model != known.get("default_model"):
                ai_section[f"{prov.name}_model"] = prov.default_model
            if prov.base_url and prov.base_url.rstrip("/") != known.get("base_url", "").rstrip("/"):
                ai_section[f"{prov.name}_url"] = prov.base_url
        else:
            # Unknown provider — use advanced format
            if "providers" not in ai_section:
                ai_section["providers"] = []
            ai_section["providers"].append({
                "name": prov.name, "base_url": prov.base_url,
                "api_key": prov.api_key, "default_model": prov.default_model,
            })
    # Remove legacy kvmind section
    data.pop("kvmind", None)
    data["ai"] = ai_section

    # Bridge — merge into existing section to preserve unknown keys
    bridge_section = data.get("bridge", {})
    bridge_section.update({
        "host": cfg.bridge.host,
        "port": cfg.bridge.port,
        "mode": cfg.bridge.mode,
        "log_path": cfg.bridge.log_path,
        "max_log_size_mb": cfg.bridge.max_log_size_mb,
        "confirm_dangerous_ops": cfg.bridge.confirm_dangerous_ops,
        "auto_inspect_interval": cfg.bridge.auto_inspect_interval,
        "debug": cfg.bridge.debug,
        "backend_url": cfg.bridge.backend_url,
        "trusted_proxies": list(cfg.bridge.trusted_proxies),
        "db_path": cfg.bridge.db_path,
        "chat_retention_days": cfg.bridge.chat_retention_days,
        "password": cfg.bridge.password,
    })
    data["bridge"] = bridge_section

    # Telegram
    if cfg.telegram.bot_token:
        data["telegram"] = {
            "bot_token": cfg.telegram.bot_token,
            "allowed_chats": cfg.telegram.allowed_chats,
        }

    # Subscription (heartbeat-managed, read-only for user)
    data["subscription"] = {
        "plan": cfg.subscription.plan,
        "tunnel": cfg.subscription.tunnel,
        "messaging": cfg.subscription.messaging,
        "ota": cfg.subscription.ota,
        "synced_at": cfg.subscription.synced_at,
        "myclaw_limit": cfg.subscription.myclaw_limit,
        "myclaw_daily_limit": cfg.subscription.myclaw_daily_limit,
        "myclaw_max_action_level": cfg.subscription.myclaw_max_action_level,
        "scheduled_tasks": cfg.subscription.scheduled_tasks,
    }
    # 清理旧字段
    if "ai" in data:
        data["ai"].pop("plan_type", None)
        data["ai"].pop("subscription_key", None)

    # /etc/kdkvm is on read-only root partition; remount rw briefly
    from .remount import remount_rw
    with remount_rw(str(p)):
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        log.info("[Config] Saved to %s", path)

    # Invalidate singleton so next get_config() re-reads from disk
    global _config
    _config = None


# Singleton
_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.load()
    return _config
