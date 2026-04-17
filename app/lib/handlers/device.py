"""Device control handlers — status, analyse, HID proxies, power."""
from __future__ import annotations

import logging

from aiohttp import web

from ..kvm.base import NoVideoSignalError
from .helpers import json_response

log = logging.getLogger("kvmind.handlers.device")

VALID_POWER_ACTIONS = {"on", "off", "reset", "force_off", "cycle"}


def register(app: dict) -> None:
    """Register device-related routes on the aiohttp app."""

    kvm = app["kvm"]
    cfg = app["cfg"]
    audit = app["audit"]

    # ── REST handlers ───────────────────────────────────────────────────────

    async def h_status(req: web.Request) -> web.Response:
        try:
            info = await kvm.get_info()
            kvm_ok = True
        except Exception:
            info = {}
            kvm_ok = False
        return json_response({
            "bridge": "ok",
            "kvm": "ok" if kvm_ok else "error",
            "kvm_info": info,
            "stream_urls": kvm.stream_urls(),
            "backend": cfg.kvm.backend,
            "mode": cfg.bridge.mode,
        })

    async def h_analyse(req: web.Request) -> web.Response:
        lang = "en"
        try:
            body = await req.json()
            lang = body.get("lang", "en")
        except Exception as e:
            log.debug("No JSON body for analyse, using default lang: %s", e)
        try:
            screenshot = await kvm.snapshot_b64()
            text = await req.app["kvmind"].analyse(
                "Analyze what is currently displayed on the screen.",
                screenshot_b64=screenshot,
                lang=lang,
            )
            return json_response({
                "event": "ai_text",
                "text": text,
                "screenshot": screenshot,
            })
        except NoVideoSignalError as exc:
            log.warning("Analyse: no video signal (%s)", exc)
            msg = {"zh": "无视频信号，请检查 HDMI 连接。",
                   "ja": "ビデオ信号がありません。HDMI 接続をご確認ください。",
                   "en": "No video signal — please check the HDMI connection."}
            return json_response({"error": msg.get(lang, msg["en"])}, status=503)
        except Exception as exc:
            log.exception("Analyse failed: %s", exc)
            providers = app["providers"]
            if not providers:
                msg = {"zh": "AI 未配置。请在 KVM设置 中设置 AI API Key。",
                       "ja": "AI が未設定です。KVM設定で AI API Key を設定してください。",
                       "en": "AI is not configured. Please set your AI API Key in KVM Settings."}
            else:
                msg = {"zh": "AI 分析失败，请稍后重试。",
                       "ja": "AI 分析に失敗しました。しばらくしてから再試行してください。",
                       "en": "AI analysis failed. Please try again later."}
            return json_response({"error": msg.get(lang, msg["en"])}, status=502)

    async def h_screen_copy(req: web.Request) -> web.Response:
        """POST /api/screen/copy — Extract text from remote screen via AI OCR."""
        lang = "en"
        region = None
        try:
            body = await req.json()
            lang = body.get("lang", "en")
            region = body.get("region")
        except Exception:
            pass
        try:
            screenshot = await kvm.snapshot_b64()
            if region and all(k in region for k in ("x1", "y1", "x2", "y2")):
                from ..innerclaw.tools import crop_screenshot_b64
                screenshot = crop_screenshot_b64(
                    screenshot,
                    float(region["x1"]), float(region["y1"]),
                    float(region["x2"]), float(region["y2"]),
                )
            text = await req.app["kvmind"].ocr(screenshot_b64=screenshot, lang=lang)
            return json_response({"text": text, "region": region})
        except Exception as exc:
            log.exception("Screen copy failed: %s", exc)
            msg = {"zh": "屏幕文字提取失败，请稍后重试。",
                   "ja": "画面テキスト抽出に失敗しました。",
                   "en": "Screen text extraction failed. Please try again later."}
            return json_response({"error": msg.get(lang, msg["en"])}, status=502)

    # ── HID proxies ─────────────────────────────────────────────────────────
    # Mouse move/click: no REST proxy needed — frontend uses kvmd WebSocket
    # binary protocol (kvmind-session.js), InnerClaw uses kvm adapter directly.

    async def h_keyboard_type(req: web.Request) -> web.Response:
        body = await req.json()
        text = body.get("text")
        if not isinstance(text, str) or not text:
            return json_response({"error": "text is required"}, status=400)
        if len(text) > 4096:
            return json_response({"error": "text too long (max 4096)"}, status=400)
        await kvm.type_text(text)
        await audit.log("manual_type", {"length": len(text)})
        return json_response({"status": "ok"})

    async def h_keyboard_key(req: web.Request) -> web.Response:
        body = await req.json()
        key = body.get("key")
        if not isinstance(key, str) or not key:
            return json_response({"error": "key is required"}, status=400)
        await kvm.key_tap(key)
        await audit.log("manual_key", body)
        return json_response({"status": "ok"})

    async def h_power(req: web.Request) -> web.Response:
        body = await req.json()
        action = body.get("action", "")
        if action not in VALID_POWER_ACTIONS:
            return json_response({"error": f"action must be one of {VALID_POWER_ACTIONS}"}, status=400)
        await kvm.power_action(action)
        await audit.log("power", {"action": action})
        return json_response({"status": "ok"})

    # ── Route registration ──────────────────────────────────────────────────

    app.router.add_get("/api/status", h_status)
    app.router.add_post("/api/analyse", h_analyse)
    app.router.add_post("/api/screen/copy", h_screen_copy)
    app.router.add_post("/api/hid/keyboard/type", h_keyboard_type)
    app.router.add_post("/api/hid/keyboard/key", h_keyboard_key)
    app.router.add_post("/api/atx/power", h_power)
