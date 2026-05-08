"""AI configuration handlers — models, config get/save, connection test."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from ..config import KNOWN_PROVIDERS, ProviderConfig, save_config
from ..ai_provider import OpenAIProvider, AnthropicProvider
from ..model_router import ModelRouter
from ..kvmind_client import KVMindClient
from ..telegram_bot import start_bot
from .helpers import json_response

log = logging.getLogger("kvmind.handlers.ai_config")


# audit-r4 R4-SEC-02 / P0-1 (2026-04-19): SSRF guard for any AI endpoint that
# forwards a stored or user-supplied api_key to an outbound base_url.
#
# Cloud metadata endpoints return IAM credentials to whoever can reach them,
# and are the single most abused SSRF target. Blocked unconditionally for any
# provider on /api/ai/test and /api/ai/models regardless of user input.
_AI_TEST_METADATA_HOSTS = {
    "169.254.169.254",           # AWS / GCE / Azure / Tencent
    "metadata.google.internal",  # GCE
    "metadata.goog",             # GCE
    "100.100.100.200",           # Alibaba Cloud
    "metadata.tencentyun.com",   # Tencent Cloud
    "metadata.aliyun.com",       # Alibaba Cloud
}


def _resolve_and_validate_base_url(
    user_base: str, provider: str, info: dict | None
) -> tuple[str | None, str | None]:
    """Resolve and validate the base URL used by AI provider-facing handlers.

    Shared by ``/api/ai/test`` and ``/api/ai/models`` — both forward headers
    containing an api_key to the returned URL, so they need identical SSRF
    rules. Returns ``(final_url, error)``. If ``error`` is non-None the caller
    should reject the request. If both are None the caller falls back to the
    pinned default for the provider.

    Rules (R4-SEC-02 + P0-1):
      * For pinned cloud providers (openai / gemini / anthropic) the user-
        supplied ``base_url`` is ignored — the canonical URL is always used,
        so the api_key cannot be redirected to an attacker-controlled host.
      * Cloud metadata hosts (AWS/GCE/Azure/Aliyun/Tencent) are always blocked.
      * Link-local IPs (169.254/16) are blocked; they cover the metadata
        range on every major cloud.
      * ``custom`` provider must use HTTPS (plaintext api_key over the LAN
        or ISP hop is not acceptable).
      * ``ollama`` is the explicit self-hosted case and remains permissive
        (http or https, LAN addresses allowed) but metadata hosts are still
        blocked.
    """
    pinned = (info or {}).get("base_url", "")

    if provider in ("openai", "gemini", "anthropic") and pinned:
        return pinned, None

    if not user_base:
        if provider == "custom":
            return None, "请填写 Base URL"
        return None, None

    try:
        parsed = urlparse(user_base)
    except Exception:
        return None, "Base URL 格式无效"

    if parsed.scheme not in ("http", "https"):
        return None, "Base URL 必须以 http:// 或 https:// 开头"

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None, "Base URL 缺少主机名"

    if host in _AI_TEST_METADATA_HOSTS:
        return None, "Base URL 指向云元数据(metadata)地址，已被安全策略阻止"

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_link_local:
            return None, "Base URL 指向 link-local 地址，已被安全策略阻止"
    except ValueError:
        pass

    if provider == "custom" and parsed.scheme != "https":
        return None, "自定义服务商必须使用 https:// Base URL"

    if provider == "ollama":
        return user_base, None

    if parsed.scheme != "https":
        return None, "Base URL 必须使用 https://"

    return user_base, None


def _base_url_error_code(error: str) -> str:
    """Map base URL validation text to a stable UI-facing semantic code."""
    blocked_markers = ("安全策略", "metadata", "元数据", "link-local", "169.254")
    if any(marker in (error or "") for marker in blocked_markers):
        return "blocked_base_url"
    return "invalid_base_url"


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
                "[Registry] Skip provider %s — no model selected. "
                "User must pick a model in MyClaw settings.",
                pcfg.name,
            )
            continue
        if pcfg.name == "anthropic":
            provs[pcfg.name] = AnthropicProvider(pcfg.base_url, pcfg.api_key, pcfg.default_model)
        else:
            provs[pcfg.name] = OpenAIProvider(pcfg.base_url, pcfg.api_key, pcfg.default_model)
    return provs


def _rebuild_router(cfg, memory=None) -> tuple:
    """Build new providers, router, and KVMindClient from config."""
    providers = _build_providers(cfg.ai)
    router = ModelRouter(providers, default_timeout=cfg.ai.timeout)
    kvmind = KVMindClient(cfg.ai, router, memory=memory)
    log.info("[Registry] Rebuilt providers: %s", list(providers.keys()))
    return providers, router, kvmind


# ── Runtime model discovery ──────────────────────────────────────────────────

def _extract_models(data: dict | list, id_path: str) -> list[str]:
    """Extract model IDs from provider response using a tiny JSONPath subset.

    Supported forms:
      "data[].id"     — iterate ``data`` list, take ``.id`` of each element
      "models[].name" — same shape, different keys
    """
    if not isinstance(id_path, str) or "[]" not in id_path:
        return []
    list_key, _, item_key = id_path.partition("[].")
    if not list_key or not item_key:
        return []
    container = data.get(list_key) if isinstance(data, dict) else None
    if not isinstance(container, list):
        return []
    out: list[str] = []
    for entry in container:
        if isinstance(entry, dict):
            val = entry.get(item_key)
            if isinstance(val, str) and val:
                out.append(val)
    return out


def _resolve_list_url(info: dict, base_url: str) -> str:
    """Compute the URL to hit for runtime model discovery.

    Ollama's /api/tags lives at the root, not under /v1. We strip the
    suffix declared in ``models_endpoint_strip_suffix`` before appending
    ``models_endpoint``.
    """
    endpoint = info.get("models_endpoint") or "/models"
    base = (base_url or "").rstrip("/")
    strip_suffix = info.get("models_endpoint_strip_suffix")
    if strip_suffix and base.endswith(strip_suffix):
        base = base[: -len(strip_suffix)].rstrip("/")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return base + endpoint


async def _fetch_provider_models(
    provider: str,
    info: dict,
    base_url: str,
    api_key: str,
) -> tuple[list[str], str | None]:
    """Call the provider's list-models endpoint. Returns (models, error)."""
    list_url = _resolve_list_url(info, base_url)
    parsed = urlparse(list_url)
    if not parsed.scheme or not parsed.netloc:
        return [], f"invalid list URL: {list_url}"

    headers: dict[str, str] = {}
    if provider == "anthropic":
        if not api_key:
            return [], "missing api_key"
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif provider in ("openai", "gemini"):
        if not api_key:
            return [], "missing api_key"
        headers["Authorization"] = f"Bearer {api_key}"
    # ollama: no auth

    timeout = aiohttp.ClientTimeout(total=3.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(list_url, headers=headers,
                             ssl=parsed.scheme == "https") as r:
                if r.status != 200:
                    body = await r.text()
                    return [], f"HTTP {r.status}: {body[:160]}"
                data = await r.json(content_type=None)
    except asyncio.TimeoutError:
        return [], "timeout"
    except aiohttp.ClientError as exc:
        return [], f"connection error: {exc}"

    ids = _extract_models(data, info.get("models_id_path", "data[].id"))

    prefix = info.get("models_id_prefix_strip")
    if prefix:
        ids = [m[len(prefix):] if m.startswith(prefix) else m for m in ids]

    filt = info.get("models_id_filter")
    if filt:
        try:
            pattern = re.compile(filt)
            ids = [m for m in ids if pattern.match(m)]
        except re.error:
            pass

    ids = sorted(dict.fromkeys(ids))
    return ids, None


def _classify_provider_error(status: int, body_text: str) -> tuple[str, str]:
    """从上游 LLM API 错误响应里抽出用户友好的中文提示 + 语义 code。

    输入是上游（OpenAI/Anthropic/Gemini/DeepSeek/兼容 API）返回的非-200 响应体；
    它们大都遵循 {error: {message, type, code}} 形状。本函数 fingerprint message
    关键词 + status code 推断错误类型，转成 UI 安全的中文短句。

    返回 (friendly_message_zh, semantic_code)。语义 code 用于前端做 i18n 二次映射
    或埋点。**不要**把 body_text 传给 UI——内部细节（API path、上游 trace id、SQL
    片段等）属于运维信息，不应暴露给终端用户。
    """
    msg_lower = ""
    try:
        j = json.loads(body_text)
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict):
                msg_lower = (err.get("message") or "").lower()
            elif isinstance(err, str):
                msg_lower = err.lower()
    except (ValueError, TypeError):
        msg_lower = body_text.lower()[:200]

    # 模型相关错误（最常见 — 用户拼错模型名 / 选了下架的模型）
    if "model" in msg_lower and (
        "not found" in msg_lower
        or "invalid" in msg_lower
        or "does not exist" in msg_lower
        or "unknown" in msg_lower
        or "not exist" in msg_lower
    ):
        return ("模型名无效，请检查拼写或从下拉列表中重新选择", "invalid_model")
    # 鉴权类
    if (
        "api key" in msg_lower
        or "api-key" in msg_lower
        or "authentication" in msg_lower
        or "unauthorized" in msg_lower
        or "incorrect" in msg_lower and "key" in msg_lower
        or status == 401
    ):
        return ("API Key 无效或已被吊销", "invalid_api_key")
    # 配额 / 余额
    if (
        "quota" in msg_lower
        or "billing" in msg_lower
        or "insufficient" in msg_lower
        or "credit" in msg_lower
        or "balance" in msg_lower
    ):
        return ("API Key 配额或余额不足", "insufficient_quota")
    # 限流
    if "rate limit" in msg_lower or "too many requests" in msg_lower or status == 429:
        return ("调用过于频繁，请稍后重试", "rate_limit")
    # 服务端错误
    if status >= 500:
        return ("AI 服务暂时不可用，请稍后重试", "upstream_unavailable")
    if status == 404:
        return ("API 路径未找到，请检查 Base URL 是否填写正确", "endpoint_not_found")
    if status == 403:
        return ("API 访问被拒绝（可能是地区限制或 IP 黑名单）", "forbidden")
    if status == 400:
        return ("请求格式错误，请检查 Base URL 和模型设置", "bad_request")
    return (f"AI 服务返回错误（状态码 {status}）", "upstream_error")


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

    async def h_ai_models(req: web.Request) -> web.Response:
        """GET/POST /api/ai/models -- runtime fetch of provider's model list.

        Behaviour (AI Model Catalog Principle):
          * Device code no longer ships a hardcoded model list.
          * The handler hits the provider's own list-models endpoint with
            whatever base_url + api_key the user has configured.
          * On any failure (no key, bad key, timeout, endpoint unreachable)
            the response still returns 200 with free_input_only=true so the
            UI falls back to a plain text input.

        Inputs (GET query or POST JSON body):
          provider : one of ollama/gemini/anthropic/openai
          base_url : optional override (used for ollama where user supplies it)
          api_key  : optional; only falls back to the saved key when the
                     request is authenticated (P0-1 2026-04-19)

        Security (P0-1):
          * base_url is validated through the shared SSRF guard; cloud
            providers always use their pinned URL, metadata / link-local
            hosts are rejected.
          * In an unauthenticated context (first-boot /setup.html flow), the
            handler refuses to fall back to ``cfg.ai.providers[*].api_key``.
            Otherwise a caller could supply only ``provider`` + a rogue
            ``base_url`` and receive the device's stored key in the outbound
            Authorization header.
        """
        provider = req.query.get("provider", "")
        overrides: dict = {}
        if req.method == "POST":
            try:
                overrides = await req.json()
            except Exception:
                overrides = {}
            if not provider:
                provider = overrides.get("provider", "")

        info = KNOWN_PROVIDERS.get(provider)
        if not info:
            return json_response({"error": f"Unknown provider: {provider}"}, status=400)

        user_base = (overrides.get("base_url") or "").strip()
        resolved, err = _resolve_and_validate_base_url(user_base, provider, info)
        if err:
            return json_response({"code": _base_url_error_code(err), "error": err}, status=400)
        base_url = resolved or info.get("base_url", "")

        api_key = (overrides.get("api_key") or "").strip()

        # P0-1: only authenticated callers may inherit a previously-saved
        # api_key for this provider. See middleware.auth_middleware for the
        # ``authenticated`` flag — it is False on every request that reaches
        # here via NO_AUTH_PATHS / SETUP_ONLY_NO_AUTH_PATHS without a valid
        # session cookie.
        if req.get("authenticated", False):
            saved = next((p for p in cfg.ai.providers if p.name == provider), None)
            if saved:
                if not base_url:
                    base_url = saved.base_url
                if not api_key and saved.api_key and saved.api_key != "none":
                    api_key = saved.api_key

        requires_key = info.get("requires_key", True)
        if requires_key and not api_key:
            return json_response({
                "provider": provider,
                "models": [],
                "free_input_only": True,
                "error": "missing_api_key",
                "base_url": info.get("base_url", ""),
                "display_name": info.get("display_name", provider),
                "requires_key": requires_key,
                "console_url": info.get("console_url", ""),
            })

        if not base_url:
            return json_response({
                "provider": provider,
                "models": [],
                "free_input_only": True,
                "error": "missing_base_url",
                "base_url": "",
                "display_name": info.get("display_name", provider),
                "requires_key": requires_key,
                "console_url": info.get("console_url", ""),
            })

        t0 = time.monotonic()
        models, err = await _fetch_provider_models(provider, info, base_url, api_key)
        dt_ms = int((time.monotonic() - t0) * 1000)

        if err:
            log.info("[AIConfig] list_models provider=%s took=%dms error=%s",
                     provider, dt_ms, err)
            return json_response({
                "provider": provider,
                "models": [],
                "free_input_only": True,
                "error": err,
                "base_url": base_url,
                "display_name": info.get("display_name", provider),
                "requires_key": requires_key,
                "console_url": info.get("console_url", ""),
            })

        log.info("[AIConfig] list_models provider=%s took=%dms returned=%d",
                 provider, dt_ms, len(models))
        return json_response({
            "provider": provider,
            "models": models,
            "free_input_only": False,
            "base_url": base_url,
            "display_name": info.get("display_name", provider),
            "requires_key": requires_key,
            "console_url": info.get("console_url", ""),
        })

    async def h_ai_config_get(req: web.Request) -> web.Response:
        """GET /api/ai/config -- return current AI configuration."""
        import urllib.parse as _urlparse
        providers = app["providers"]
        providers_info = []
        for p in cfg.ai.providers:
            known = KNOWN_PROVIDERS.get(p.name, {})
            key_configured = bool(p.api_key and p.api_key != "none")
            preview = p.api_key[:4] + "***" + p.api_key[-2:] if key_configured else ""
            # R4-SEC-01: mask base_url to scheme://host/*** to avoid leaking path/token
            _u = _urlparse.urlparse(p.base_url or "")
            base_url_preview = f"{_u.scheme}://{_u.netloc}/***" if _u.netloc else ""
            providers_info.append({
                "name": p.name,
                "default_model": p.default_model,
                "base_url_preview": base_url_preview,
                # Full URL only for user-supplied endpoints — cloud providers
                # use canonical URLs, and their paths may carry token material.
                "base_url": p.base_url if p.name in ("ollama", "custom") else "",
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
                "claim_state": cfg.subscription.claim_state,
                "entitlement_state": cfg.subscription.entitlement_state,
                "assigned_subscription_id": cfg.subscription.assigned_subscription_id,
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
            # Accept either "{pname}_model" (legacy field name) or plain "model".
            # Do NOT fall back to any built-in default — empty model means
            # "user hasn't picked one" and _build_providers will skip it.
            model = (body.get(f"{pname}_model") or body.get("model") or "").strip()
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
            cfg.telegram.bot_token = tg_token
            if start_bot(req.app, cfg):
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
        model = (body.get("model") or "").strip()
        info = KNOWN_PROVIDERS.get(provider)
        requires_key = info.get("requires_key", True) if info else provider != "custom"
        if requires_key and not api_key:
            return json_response({"success": False, "code": "missing_api_key", "error": "请填写 API Key"})
        # No hardcoded model fallback — device code no longer maintains a
        # model catalog. User must pick a model before testing.
        if not model:
            return json_response({
                "success": False,
                "code": "no_model",
                "error": "请先选择模型 / Please select a model first",
            })
        try:
            if provider == "anthropic":
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
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
                    "model": model,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hi"}],
                }
                url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            else:
                payload = {
                    "model": model,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hi"}],
                }
                user_base = body.get("base_url", "").strip()
                resolved, err = _resolve_and_validate_base_url(user_base, provider, info)
                if err:
                    return json_response({
                        "success": False,
                        "code": _base_url_error_code(err),
                        "error": err,
                    }, status=400)
                base_url = resolved or "https://api.openai.com/v1"
                url = base_url.rstrip("/") + "/chat/completions"

                headers = {"Content-Type": "application/json"}
                if api_key and api_key != "none":
                    headers["Authorization"] = f"Bearer {api_key}"

            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=30),
                                  ssl=url.startswith("https://")) as r:
                    if r.status != 200:
                        body_text = await r.text()
                        # 不把 raw HTTP body 透传给 UI——解析 LLM 标准 {error:{message}} JSON，
                        # 按错误特征映射成中文友好提示 + 语义 code。原始信息进 server log 备查。
                        log.info("AI test upstream %s %s body=%s", r.status, url, body_text[:300])
                        friendly, code = _classify_provider_error(r.status, body_text)
                        return json_response({"success": False, "code": code, "error": friendly})

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
        except aiohttp.ClientConnectorError as e:
            log.info("AI test connect failure: %s", e)
            return json_response({
                "success": False, "code": "network_unreachable",
                "error": "无法连接到 AI 服务，请检查网络或 Base URL 是否正确",
            })
        except asyncio.TimeoutError:
            return json_response({
                "success": False, "code": "timeout",
                "error": "AI 服务响应超时，请稍后重试",
            })
        except Exception as e:
            log.warning("AI test unexpected error: %r", e)
            return json_response({
                "success": False, "code": "internal",
                "error": "测试过程出错，请稍后重试",
            })

    # ── Route registration ──────────────────────────────────────────────────

    app.router.add_get("/api/ai/models", h_ai_models)
    app.router.add_post("/api/ai/models", h_ai_models)
    app.router.add_get("/api/ai/config", h_ai_config_get)
    app.router.add_post("/api/ai/config", h_ai_config_save)
    app.router.add_post("/api/ai/test", h_ai_test)
