"""
KVMind Integration - Configuration Module

Reads from /etc/kdkvm/config.yaml, environment variables, or both.

Provider key resolution (highest priority first):
  1. Environment variables: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY
  2. config.yaml shorthand: ai.gemini_key, ai.claude_key, ai.openai_key
  3. config.yaml advanced: ai.providers list
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
#
# AI 模型目录原则（AI Model Catalog Principle）
# --------------------------------------------------
# 设备端不维护模型列表。新模型 / 新 provider 不发 kdkvm 版本。
#
# 具体约束：
#   1. KNOWN_PROVIDERS 不含 `models` 和 `default_model` 字段
#   2. 模型名是给 provider API 的参数，由运营 / 用户填
#   3. UI 打开设置面板时才向 provider 现拉一次可用模型清单（作为建议）
#   4. 用户手填任意模型名都接受，校验由 provider API 本身完成
#      （测试连接时它说 "model not found" 才是真报错）
#   5. 查不到（无网 / 无 key / provider 不支持）→ 纯自由文本输入 + console_url 兜底
#
# 字段语义：
#   base_url              – canonical endpoint（云 provider 固定，ollama 必须用户填）
#   display_name          – UI 显示名
#   requires_key          – 是否需要 API key（Ollama=False）
#   config_key            – config.yaml 中对应的 shorthand key（如 "gemini_key"）
#   key_envs              – 可覆盖的环境变量列表
#   models_endpoint       – 相对 base_url 的 HTTP path，用于运行时拉模型清单
#   models_endpoint_host  – 可选：不挂在 base_url 下（Ollama /api/tags 挂在 root，不在 /v1）
#   models_id_path        – 响应 JSON 里提取模型 id 的路径，如 "data[].id"
#   models_id_prefix_strip– 可选：剥掉的 id 前缀（Gemini 的 "models/"）
#   models_id_filter      – 可选：id 必须匹配的正则（OpenAI 只保留 chat 类）
#   console_url           – provider 控制台链接，给用户兜底查最新模型

KNOWN_PROVIDERS: Dict[str, Dict] = {
    "ollama": {
        # No default URL — user must enter the full URL of their Ollama server
        # during setup, e.g. "http://192.168.1.50:11434/v1". Shipping a LAN IP
        # as default leaks the developer's environment and wastes every other
        # user's first-run (requests disappear into the void and surface as a
        # 502 on /api/analyse with no hint of the cause).
        "base_url": "",
        "key_envs": ["OLLAMA_API_KEY"],
        "config_key": "ollama_key",
        "display_name": "Ollama",
        "requires_key": False,
        # Ollama's native list-models endpoint is /api/tags at the root (not under /v1).
        # When base_url is "http://host:11434/v1" we strip the /v1 suffix before appending.
        "models_endpoint": "/api/tags",
        "models_endpoint_strip_suffix": "/v1",
        "models_id_path": "models[].name",
        "console_url": "https://ollama.com/library",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_envs": ["GEMINI_API_KEY"],
        "config_key": "gemini_key",
        "display_name": "Gemini",
        "models_endpoint": "/models",
        "models_id_path": "data[].id",
        "models_id_prefix_strip": "models/",
        "console_url": "https://aistudio.google.com/apikey",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "key_envs": ["ANTHROPIC_API_KEY"],
        "config_key": "claude_key",
        "display_name": "Claude",
        "models_endpoint": "/models?limit=1000",
        "models_id_path": "data[].id",
        "console_url": "https://docs.anthropic.com/en/docs/about-claude/models",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_envs": ["OPENAI_API_KEY"],
        "config_key": "openai_key",
        "display_name": "ChatGPT",
        "models_endpoint": "/models",
        "models_id_path": "data[].id",
        # Keep only chat-capable families; drop embeddings/tts/whisper/dall-e.
        "models_id_filter": r"^(gpt-|o1-|o3-|o4-|chatgpt-)",
        "console_url": "https://platform.openai.com/api-keys",
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
    backend_url: str = "https://kvmind.com"  # kdcms backend URL
    trusted_proxies: List[str] = field(default_factory=lambda: ["127.0.0.1"])
    # M3.4: in-process heartbeat replaces kvmind-heartbeat.sh/.timer.
    # Tests set heartbeat_enabled=False to keep the event loop quiet.
    heartbeat_enabled: bool = True
    heartbeat_interval_seconds: int = 60


@dataclass
class TelegramConfig:
    bot_token: str = ""
    allowed_chats: List[int] = field(default_factory=list)


@dataclass
class SubscriptionConfig:
    """订阅 / 权益状态 — 只读，由 heartbeat 覆盖；用户改了下次心跳覆盖回来。

    V1 Seat 模型（0.4.0）：设备不再感知 standard/pro 具体计划，只关心
      - claim_state: 是否已绑账号
      - entitlement_state: 是否处于付费态
    云端心跳响应包含 planType / features，由设备端消费派生功能开关。
    """
    # ── V1 Seat 模型 · 权威真源 ──
    claim_state: str = "unclaimed"           # unclaimed / claimed
    entitlement_state: str = "local_free"    # local_free / claimed_free / paid
    assigned_subscription_id: Optional[int] = None  # 当前占用的订阅 id；paid 态必填

    # ── Feature flags（由云端心跳下发，设备端被动消费） ──
    tunnel: bool = False
    messaging: bool = False
    ota: bool = False
    myclaw_limit: int = 5            # 每小时 MyClaw 次数限制 (-1 无限)
    myclaw_daily_limit: int = 20     # 每日 MyClaw 次数限制 (-1 无限)
    myclaw_max_action_level: int = 1 # 最高 action 等级 (1/2/3)
    scheduled_tasks: bool = False    # 是否允许定时任务

    # ── 元信息 ──
    synced_at: str = ""              # ISO timestamp，最后一次心跳同步时间


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
            # Always persist user-selected model — no "known default" to diff against.
            if prov.default_model:
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

    # Subscription (V1 Seat 模型 · heartbeat-managed, read-only for user)
    data["subscription"] = {
        "claim_state": cfg.subscription.claim_state,
        "entitlement_state": cfg.subscription.entitlement_state,
        "assigned_subscription_id": cfg.subscription.assigned_subscription_id,
        "tunnel": cfg.subscription.tunnel,
        "messaging": cfg.subscription.messaging,
        "ota": cfg.subscription.ota,
        "myclaw_limit": cfg.subscription.myclaw_limit,
        "myclaw_daily_limit": cfg.subscription.myclaw_daily_limit,
        "myclaw_max_action_level": cfg.subscription.myclaw_max_action_level,
        "scheduled_tasks": cfg.subscription.scheduled_tasks,
        "synced_at": cfg.subscription.synced_at,
    }
    # 清理旧字段
    if "ai" in data:
        data["ai"].pop("plan_type", None)

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
