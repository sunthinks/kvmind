"""Tests for config.py — configuration loading and defaults."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
from unittest.mock import patch

from lib.config import (
    Config,
    KVMConfig,
    AIConfig,
    ProviderConfig,
    BridgeConfig,
    TelegramConfig,
    SubscriptionConfig,
    KNOWN_PROVIDERS,
    save_config,
)


class TestKVMConfigDefaults:
    def test_default_values(self):
        cfg = KVMConfig()

        assert cfg.backend == "pikvm"
        assert cfg.transport == "unix"
        assert cfg.unix_socket == "/run/kvmd/kvmd.sock"
        assert cfg.host == "localhost"
        assert cfg.port == 443
        assert cfg.https is True
        assert cfg.username == "admin"
        assert cfg.password == "admin"
        assert cfg.ws_path == "/api/ws"

    def test_base_url_https(self):
        cfg = KVMConfig(host="10.0.0.1", port=443, https=True)

        assert cfg.base_url == "https://10.0.0.1:443"

    def test_base_url_http(self):
        cfg = KVMConfig(host="10.0.0.1", port=8080, https=False)

        assert cfg.base_url == "http://10.0.0.1:8080"

    def test_ws_url(self):
        cfg = KVMConfig(host="10.0.0.1", port=443, https=True)

        assert cfg.ws_url == "wss://10.0.0.1:443/api/ws"

    def test_ws_url_insecure(self):
        cfg = KVMConfig(host="10.0.0.1", port=80, https=False)

        assert cfg.ws_url == "ws://10.0.0.1:80/api/ws"


class TestConfigLoadFromYAML:
    def test_load_empty_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        # Clear env vars that could pollute results
        env_keys = [
            "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY",
            "AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "TELEGRAM_BOT_TOKEN",
            "KVM_BACKEND", "KVM_TRANSPORT", "KVM_UNIX_SOCKET",
            "PIKVM_HOST", "PIKVM_PORT", "PIKVM_USER", "PIKVM_PASS",
            "BRIDGE_PORT", "BRIDGE_MODE",
        ]
        saved = {k: os.environ.pop(k) for k in env_keys if k in os.environ}
        try:
            cfg = Config.load(str(config_file))

            assert cfg.kvm.backend == "pikvm"
            assert cfg.ai.providers == []
        finally:
            os.environ.update(saved)

    def test_load_kvm_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "kvm": {
                "backend": "nanokvm",
                "host": "192.168.1.100",
                "port": 8080,
                "https": False,
                "username": "root",
                "password": "secret",
            }
        }
        config_file.write_text(yaml.dump(data))

        cfg = Config.load(str(config_file))

        assert cfg.kvm.backend == "nanokvm"
        assert cfg.kvm.host == "192.168.1.100"
        assert cfg.kvm.port == 8080
        assert cfg.kvm.https is False
        assert cfg.kvm.username == "root"
        assert cfg.kvm.password == "secret"

    def test_load_legacy_pikvm_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {"pikvm": {"host": "192.168.0.22", "port": 443}}
        config_file.write_text(yaml.dump(data))

        cfg = Config.load(str(config_file))

        assert cfg.kvm.host == "192.168.0.22"

    def test_load_bridge_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {"bridge": {"port": 9999, "mode": "auto", "debug": True}}
        config_file.write_text(yaml.dump(data))

        cfg = Config.load(str(config_file))

        assert cfg.bridge.port == 9999
        assert cfg.bridge.mode == "auto"
        assert cfg.bridge.debug is True

    def test_load_nonexistent_file(self, tmp_path):
        cfg = Config.load(str(tmp_path / "nonexistent.yaml"))

        assert cfg.kvm.backend == "pikvm"

    def test_load_ai_timeout_and_max_tokens(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {"ai": {"timeout": 60, "max_tokens": 2048}}
        config_file.write_text(yaml.dump(data))

        cfg = Config.load(str(config_file))

        assert cfg.ai.timeout == 60
        assert cfg.ai.max_tokens == 2048


class TestProviderConfigFromEnv:
    def test_gemini_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        saved = {k: os.environ.pop(k) for k in ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "AI_API_KEY"] if k in os.environ}
        os.environ["GEMINI_API_KEY"] = "test-gemini-key"
        try:
            cfg = Config.load(str(config_file))

            gemini = cfg.ai.get_provider("gemini")
            assert gemini is not None
            assert gemini.api_key == "test-gemini-key"
            assert gemini.source == "env"
            assert gemini.name == "gemini"
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.update(saved)

    def test_env_takes_priority_over_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {"ai": {"gemini_key": "yaml-key"}}
        config_file.write_text(yaml.dump(data))

        saved = {k: os.environ.pop(k) for k in ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "AI_API_KEY"] if k in os.environ}
        os.environ["GEMINI_API_KEY"] = "env-key"
        try:
            cfg = Config.load(str(config_file))

            gemini = cfg.ai.get_provider("gemini")
            assert gemini.api_key == "env-key"
            assert gemini.source == "env"
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.update(saved)

    def test_deepseek_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        saved = {k: os.environ.pop(k) for k in [
            "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "OLLAMA_API_KEY", "DEEPSEEK_API_KEY", "AI_API_KEY",
        ] if k in os.environ}
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        try:
            cfg = Config.load(str(config_file))

            ds = cfg.ai.get_provider("deepseek")
            assert ds is not None
            assert ds.api_key == "test-deepseek-key"
            assert ds.source == "env"
            assert ds.base_url == "https://api.deepseek.com"
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)
            os.environ.update(saved)

    def test_custom_provider_from_yaml_shorthand(self, tmp_path):
        """Generic OpenAI-compatible endpoint loaded from yaml shorthand.

        custom 在 KNOWN_PROVIDERS 里 base_url 留空，必须由用户在 yaml 里填
        custom_url；单测验证 custom_key + custom_url + custom_model 三件套
        都被解析进 ProviderConfig。
        """
        config_file = tmp_path / "config.yaml"
        data = {"ai": {
            "custom_key": "sk-userkey",
            "custom_url": "https://my-llm.example.com/v1",
            "custom_model": "qwen2.5-72b",
        }}
        config_file.write_text(yaml.dump(data))

        saved = {k: os.environ.pop(k) for k in [
            "CUSTOM_AI_API_KEY", "OPENAI_API_KEY", "AI_API_KEY",
        ] if k in os.environ}
        try:
            cfg = Config.load(str(config_file))

            cu = cfg.ai.get_provider("custom")
            assert cu is not None
            assert cu.api_key == "sk-userkey"
            assert cu.base_url == "https://my-llm.example.com/v1"
            assert cu.default_model == "qwen2.5-72b"
            assert cu.source == "config"
        finally:
            os.environ.update(saved)


class TestProviderConfigFromYAML:
    def test_shorthand_gemini_key(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {"ai": {"gemini_key": "yaml-gemini-key"}}
        config_file.write_text(yaml.dump(data))

        saved = {k: os.environ.pop(k) for k in ["GEMINI_API_KEY"] if k in os.environ}
        try:
            cfg = Config.load(str(config_file))

            gemini = cfg.ai.get_provider("gemini")
            assert gemini is not None
            assert gemini.api_key == "yaml-gemini-key"
            assert gemini.source == "config"
        finally:
            os.environ.update(saved)

    def test_ollama_no_key_with_model_and_url(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "ai": {
                "ollama_enabled": True,
                "ollama_url": "http://127.0.0.1:11434/v1",
                "ollama_model": "qwen3-vl:2b",
            },
        }
        config_file.write_text(yaml.dump(data))

        saved = {k: os.environ.pop(k) for k in ["OLLAMA_API_KEY"] if k in os.environ}
        try:
            cfg = Config.load(str(config_file))

            ollama = cfg.ai.get_provider("ollama")
            assert ollama is not None
            assert ollama.api_key == ""
            assert ollama.base_url == "http://127.0.0.1:11434/v1"
            assert ollama.default_model == "qwen3-vl:2b"
        finally:
            os.environ.update(saved)

    def test_save_known_provider_model_and_url(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        cfg = Config()
        cfg.ai.providers = [
            ProviderConfig(
                name="ollama",
                base_url="http://127.0.0.1:11434/v1",
                api_key="",
                default_model="qwen3-vl:2b",
            ),
        ]

        with patch("lib.remount._remount", return_value=True):
            save_config(cfg, str(config_file))

        data = yaml.safe_load(config_file.read_text())
        assert data["ai"]["ollama_enabled"] is True
        assert data["ai"]["ollama_url"] == "http://127.0.0.1:11434/v1"
        assert data["ai"]["ollama_model"] == "qwen3-vl:2b"


class TestProviderConfigValidation:
    def test_get_provider_returns_none_for_missing(self):
        ai = AIConfig(providers=[ProviderConfig(name="gemini")])

        assert ai.get_provider("openai") is None

    def test_get_provider_returns_match(self):
        ai = AIConfig(providers=[
            ProviderConfig(name="gemini", api_key="k1"),
            ProviderConfig(name="openai", api_key="k2"),
        ])

        p = ai.get_provider("openai")
        assert p is not None
        assert p.api_key == "k2"


class TestKnownProviders:
    def test_all_providers_have_required_fields(self):
        # "AI Model Catalog Principle" (config.py): device does not ship a
        # model list. Fields `models` and `default_model` are intentionally
        # absent — models are discovered at runtime from provider APIs.
        required = {"base_url", "display_name", "config_key", "console_url",
                    "models_endpoint", "models_id_path"}
        for name, cfg in KNOWN_PROVIDERS.items():
            for f in required:
                assert f in cfg, f"Provider '{name}' missing field '{f}'"

    def test_ollama_does_not_require_key(self):
        assert KNOWN_PROVIDERS["ollama"].get("requires_key") is False

    def test_no_provider_hardcodes_models(self):
        # Enforce the catalog principle: models must never be shipped in-tree.
        for name, cfg in KNOWN_PROVIDERS.items():
            assert "models" not in cfg, (
                f"Provider '{name}' must not hardcode a 'models' list — "
                "model discovery is runtime-only"
            )
            assert "default_model" not in cfg, (
                f"Provider '{name}' must not hardcode 'default_model' — "
                "users pick the model at setup time"
            )


class TestDefaultValues:
    def test_bridge_defaults(self):
        cfg = BridgeConfig()

        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8765
        assert cfg.debug is False
        assert cfg.mode == "suggest"
        assert cfg.chat_retention_days == 30

    def test_ai_config_defaults(self):
        cfg = AIConfig()

        assert cfg.providers == []
        assert cfg.timeout == 120
        assert cfg.max_tokens == 4096

    def test_telegram_defaults(self):
        cfg = TelegramConfig()

        assert cfg.bot_token == ""
        assert cfg.allowed_chats == []


class TestSubscriptionConfigDefaults:
    def test_v1_seat_defaults(self):
        cfg = SubscriptionConfig()

        assert cfg.claim_state == "unclaimed"
        assert cfg.entitlement_state == "local_free"
        assert cfg.assigned_subscription_id is None
        assert cfg.myclaw_limit == 5
        assert cfg.myclaw_daily_limit == 20
        assert cfg.myclaw_max_action_level == 1
        assert cfg.scheduled_tasks is False

    def test_tunnel_and_messaging_defaults(self):
        cfg = SubscriptionConfig()

        assert cfg.tunnel is False
        assert cfg.messaging is False
        assert cfg.ota is False

    def test_subscription_in_config(self):
        cfg = Config()

        # V1 Seat 模型: 默认 unclaimed + local_free
        assert cfg.subscription.claim_state == "unclaimed"
        assert cfg.subscription.entitlement_state == "local_free"
        assert cfg.subscription.assigned_subscription_id is None
        assert cfg.subscription.myclaw_limit == 5

    def test_load_subscription_from_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "subscription": {
                "claim_state": "claimed",
                "entitlement_state": "paid",
                "assigned_subscription_id": 42,
                "myclaw_limit": -1,
                "myclaw_daily_limit": -1,
                "myclaw_max_action_level": 3,
                "scheduled_tasks": True,
            }
        }
        config_file.write_text(yaml.dump(data))

        env_keys = [
            "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY",
            "AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "TELEGRAM_BOT_TOKEN",
            "KVM_BACKEND", "KVM_TRANSPORT", "KVM_UNIX_SOCKET",
            "PIKVM_HOST", "PIKVM_PORT", "PIKVM_USER", "PIKVM_PASS",
            "BRIDGE_PORT", "BRIDGE_MODE",
        ]
        saved = {k: os.environ.pop(k) for k in env_keys if k in os.environ}
        try:
            cfg = Config.load(str(config_file))

            assert cfg.subscription.claim_state == "claimed"
            assert cfg.subscription.entitlement_state == "paid"
            assert cfg.subscription.assigned_subscription_id == 42
            assert cfg.subscription.myclaw_limit == -1
            assert cfg.subscription.myclaw_daily_limit == -1
            assert cfg.subscription.myclaw_max_action_level == 3
            assert cfg.subscription.scheduled_tasks is True
        finally:
            os.environ.update(saved)
