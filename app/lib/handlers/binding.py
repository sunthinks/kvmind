"""V15 local aiohttp routes for the binding flow.

UI (activate.html) calls these device-local endpoints — the handler signs
requests with the device Ed25519 key and forwards to kdcms. The device UI
never sees a raw signing key.

V15 changes vs prior:
* ``/api/binding/request`` no longer accepts ``target_email`` — device-initiated
  binding does not specify a target account; account-side accept proves
  ownership via the 6-digit OOB ``confirmation_code`` returned here.
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ..binding import (
    BindingError,
    build_state_snapshot,
    cancel_binding,
    clear_last_result,
    decide_binding,
    release_binding,
    request_binding,
    save_last_result,
)
from ..config import Config
from ..heartbeat import request_heartbeat_tick

log = logging.getLogger(__name__)


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status)


def _err(code: str, status: int = 400, extra: dict | None = None) -> web.Response:
    body = {"status": "error", "code": code}
    if extra:
        body.update(extra)
    return _json(body, status=status)


def register(app) -> None:
    """Mount the /api/binding/** routes. Matches the handler-module convention
    used by ``auth``/``subscription``/``ai_config`` — ``register(app)`` is
    invoked by :func:`handlers.register_all` at server startup."""
    cfg: Config = app["cfg"]

    async def h_state(_req: web.Request) -> web.Response:
        # 0.5.24: state.db 异常不许裸抛 500——其它 handler 都有 try/except 兜底。
        try:
            return _json({"status": "ok", **build_state_snapshot()})
        except Exception as e:
            log.exception("binding.state unexpected error")
            return _err("binding.internal", status=500, extra={"detail": repr(e)[:200]})

    async def h_request(req: web.Request) -> web.Response:
        # V15: 设备发起绑定不再需要 body 字段（目标账户由账户端 accept 时确认，
        # 服务端生成的 6 位 confirmation_code 通过 response 回到设备 UI）。
        # 仍然 try-parse JSON 以兼容旧前端发空 {} 的情况，但不读任何字段。
        try:
            await req.json()
        except Exception:
            pass
        try:
            data = await request_binding(cfg)
            save_last_result(
                "binding.request.sent",
                extra={
                    "id": data.get("request_id"),
                    "expiresAt": data.get("expires_at"),
                    "accountUrl": data.get("account_url"),
                    "deviceUid": data.get("device_uid"),
                    "status": data.get("status"),
                    "confirmationCode": data.get("confirmation_code"),
                    "cooldownUntil": data.get("cooldown_until"),
                },
            )
            request_heartbeat_tick(app)
            return _json({"status": "ok", "data": data})
        except BindingError as e:
            log.info("binding.request failed: %s (http=%s)", e.code, e.http_status)
            return _err(e.code, status=e.http_status if e.http_status >= 400 else 400)
        except Exception as e:
            log.exception("binding.request unexpected error")
            return _err("binding.internal", status=500, extra={"detail": repr(e)[:200]})

    async def h_decide(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _err("binding.body.invalid")
        req_id = body.get("id")
        decision = body.get("decision")
        if not req_id or decision not in ("accept", "decline"):
            return _err("binding.body.invalid")
        try:
            accept = decision == "accept"
            data = await decide_binding(cfg, int(req_id), accept)
            save_last_result(
                "binding.accepted" if accept else "binding.declined",
                extra={"id": data.get("id")},
            )
            if accept:
                request_heartbeat_tick(app)
            return _json({"status": "ok", "data": data})
        except BindingError as e:
            log.info("binding.decide failed: %s (http=%s)", e.code, e.http_status)
            return _err(e.code, status=e.http_status if e.http_status >= 400 else 400)
        except Exception as e:
            log.exception("binding.decide unexpected error")
            return _err("binding.internal", status=500, extra={"detail": repr(e)[:200]})

    async def h_cancel(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _err("binding.body.invalid")
        req_id = body.get("id")
        if not req_id:
            return _err("binding.body.invalid")
        try:
            await cancel_binding(cfg, int(req_id))
            clear_last_result()
            return _json({"status": "ok"})
        except BindingError as e:
            return _err(e.code, status=e.http_status if e.http_status >= 400 else 400)
        except Exception as e:
            log.exception("binding.cancel unexpected error")
            return _err("binding.internal", status=500, extra={"detail": repr(e)[:200]})

    async def h_clear_last_result(_req: web.Request) -> web.Response:
        clear_last_result()
        return _json({"status": "ok"})

    async def h_release(_req: web.Request) -> web.Response:
        try:
            await release_binding(cfg)
            # release_binding 把 cfg.subscription.scheduled_tasks 强制翻 False；
            # TaskScheduler 已经运行的循环不会自检 cfg，必须显式 stop_all。
            sched = app.get("task_scheduler")
            if sched is not None:
                stopped = sched.stop_all()
                if stopped:
                    log.info("[Binding] Stopped %d scheduled tasks (release)", stopped)
            return _json({"status": "ok"})
        except BindingError as e:
            log.info("binding.release failed: %s (http=%s)", e.code, e.http_status)
            return _err(e.code, status=e.http_status if e.http_status >= 400 else 400)
        except Exception as e:
            log.exception("binding.release unexpected error")
            return _err("binding.internal", status=500, extra={"detail": repr(e)[:200]})

    app.router.add_get("/api/binding/state", h_state)
    app.router.add_post("/api/binding/request", h_request)
    app.router.add_post("/api/binding/decide", h_decide)
    app.router.add_post("/api/binding/cancel", h_cancel)
    app.router.add_post("/api/binding/release", h_release)
    app.router.add_post("/api/binding/clear-result", h_clear_last_result)
