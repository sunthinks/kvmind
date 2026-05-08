"""V15: device-side client for the bidirectional device-binding flow.

Two paths:
* Device-initiated (``DEVICE_TO_ACCOUNT``): user clicks "request binding" on
  activate.html → server generates a one-time 6-digit OOB ``confirmation_code``;
  device shows it on screen; account-side accept must enter the same code.
* Account-initiated (``ACCOUNT_TO_DEVICE``): account types UID on kvmind.com;
  device receives the pending in heartbeat; user accepts / declines locally.

Responsibilities:
* sign + POST to kdcms ``/api/device/binding-requests/**`` (create / decide / cancel)
* cache the heartbeat-delivered pending list in state.db (account → device path)
* surface a snapshot for the aiohttp handlers (``confirmation_code``, account_url, …)

Module stays thin — validation / state machine / expiry / OOB code generation all
live in kdcms ``DeviceBindingRequestService``. We just carry bytes.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp

from .config import Config
from .device_keys import load_signing_key, sign_request
from .state_db import get_state_db
from .uid import get_uid

log = logging.getLogger(__name__)

# state.db keys (keep documented; consumers import via module constants).
KV_PENDING_SNAPSHOT = "binding_pending_snapshot"   # JSON list from last heartbeat
KV_LAST_RESULT      = "binding_last_result"        # JSON object {status, code, ts}
KV_PENDING_MINE     = "binding_pending_mine"       # device-initiated 待审请求的
                                                   # 本地缓存：{id, code, accountUrl,
                                                   # deviceUid, expiresAt, createdAt}
                                                   # TTL 10 分钟（与 kdcms binding
                                                   # 请求 TTL 对齐），accept/reject/
                                                   # cancel 时清除。**不**像
                                                   # KV_LAST_RESULT 30s 就自动消失。
KV_FAST_POLL_UNTIL  = "binding_fast_poll_until"    # epoch seconds (str). While
                                                   # > now, heartbeat shortens
                                                   # its sleep (~5s) so the
                                                   # device picks up the
                                                   # counterpart's decision
                                                   # quickly. Mirrors the kdcms
                                                   # binding TTL (10 min).

# 心跳"绑定进行中"加速窗口：设置后设备端心跳从 60s → 5s；claim_state='claimed'
# 后由 heartbeat._one_tick 清除，否则自然过期。10 分钟对齐 kdcms 的 TTL。
BINDING_FAST_POLL_SECONDS = 600


# ── state.db helpers ────────────────────────────────────────────────────────


def save_pending_snapshot(items: list[dict] | None) -> None:
    """Called by heartbeat after each tick. ``None`` clears the cache."""
    db = get_state_db()
    if not items:
        db.kv_delete(KV_PENDING_SNAPSHOT)
        return
    db.kv_set(KV_PENDING_SNAPSHOT, json.dumps(items, separators=(",", ":")))


def load_pending_snapshot() -> list[dict]:
    db = get_state_db()
    raw = db.kv_get(KV_PENDING_SNAPSHOT)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# lastResult 是"瞬时 UI 反馈"语义（toast）——记下用户刚刚的动作结果（已发送 /
# 已同意 / 已拒绝），让 activate.html 跨刷新仍能看到。**不是持久状态**：因此有
# TTL（默认 30s）且由 build_state_snapshot 做跨字段一致性校验——避免老的
# "已同意" toast 在设备后来被解绑、或升级前留下的状态下与当前真实 state 矛盾。
LAST_RESULT_TTL_SECONDS = 30


def save_last_result(code: str, extra: Optional[dict] = None) -> None:
    """Record the most recent binding UI action（toast 语义，{LAST_RESULT_TTL_SECONDS}s 内有效）。"""
    payload = {"code": code, "ts": int(time.time())}
    if extra:
        payload.update(extra)
    get_state_db().kv_set(KV_LAST_RESULT, json.dumps(payload, separators=(",", ":")))


def load_last_result(max_age_seconds: int = LAST_RESULT_TTL_SECONDS) -> Optional[dict]:
    """加 TTL 读取：超期记录自动清掉返回 None。防止历史 toast 污染当前 UI。"""
    raw = get_state_db().kv_get(KV_LAST_RESULT)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        get_state_db().kv_delete(KV_LAST_RESULT)
        return None
    ts = data.get("ts")
    if isinstance(ts, int) and (int(time.time()) - ts) > max_age_seconds:
        get_state_db().kv_delete(KV_LAST_RESULT)
        return None
    return data


def clear_last_result() -> None:
    get_state_db().kv_delete(KV_LAST_RESULT)


# ── pending mine（设备发起的请求 — 持有 6 位 OOB 码 + account_url）─────────
PENDING_MINE_TTL_SECONDS = 600  # 10 分钟，与 kdcms 端 binding 请求 TTL 对齐


def save_pending_mine(data: dict) -> None:
    """request_binding 成功后调用：把 6 位 code / account_url / expiresAt 缓存到
    state.db，activate.html 在整个绑定窗口内（10 分钟）持续从这里读出展示。
    """
    payload = {
        "id": data.get("request_id") or data.get("id"),
        "code": data.get("confirmation_code"),
        "accountUrl": data.get("account_url"),
        "deviceUid": data.get("device_uid"),
        "expiresAt": data.get("expires_at"),
        "createdAt": int(time.time()),
    }
    get_state_db().kv_set(KV_PENDING_MINE, json.dumps(payload, separators=(",", ":")))


def load_pending_mine() -> Optional[dict]:
    raw = get_state_db().kv_get(KV_PENDING_MINE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        get_state_db().kv_delete(KV_PENDING_MINE)
        return None
    ts = data.get("createdAt")
    if isinstance(ts, int) and (int(time.time()) - ts) > PENDING_MINE_TTL_SECONDS:
        get_state_db().kv_delete(KV_PENDING_MINE)
        return None
    return data


def clear_pending_mine() -> None:
    get_state_db().kv_delete(KV_PENDING_MINE)


# ── fast-poll window (绑定进行中加速心跳) ───────────────────────────────────


def arm_fast_poll(duration_seconds: int = BINDING_FAST_POLL_SECONDS) -> None:
    """标记 "绑定进行中"，期间心跳循环用 5s 周期而非 60s。

    设置 deadline = now + duration。heartbeat._run 动态读取这个 key 决定下次
    sleep；heartbeat._one_tick 在看到 claim_state='claimed' 后立即 disarm，
    或者自然过期。"""
    deadline = int(time.time()) + max(1, int(duration_seconds))
    get_state_db().kv_set(KV_FAST_POLL_UNTIL, str(deadline))


def disarm_fast_poll() -> None:
    get_state_db().kv_delete(KV_FAST_POLL_UNTIL)


def fast_poll_active(now: Optional[int] = None) -> bool:
    raw = get_state_db().kv_get(KV_FAST_POLL_UNTIL)
    if not raw:
        return False
    try:
        deadline = int(raw)
    except (TypeError, ValueError):
        return False
    if deadline <= (now if now is not None else int(time.time())):
        return False
    return True


# ── kdcms call helpers (Ed25519-signed) ─────────────────────────────────────


def _serialize_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signed_headers(method: str, url: str, body_bytes: bytes) -> dict[str, str]:
    sk = load_signing_key()
    path = urlsplit(url).path or "/"
    headers = sign_request(sk, get_uid(), method, path, body_bytes)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers


async def _post_signed(url: str, payload: dict, timeout: int = 15) -> tuple[int, dict]:
    """Signed POST to kdcms. Network / signing failures raise BindingError
    so callers never need to handle raw aiohttp / asyncio exceptions."""
    try:
        body_bytes = _serialize_body(payload)
        headers = _signed_headers("POST", url, body_bytes)
    except Exception as e:
        log.error("binding: signing failed for %s: %s", url, e)
        raise BindingError("binding.signing.failed", 500)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                headers=headers,
                data=body_bytes,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    body = {}
                return r.status, body if isinstance(body, dict) else {}
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("binding: network error calling %s: %s", url, e)
        raise BindingError("binding.network.unreachable", 502)


# ── Operations ──────────────────────────────────────────────────────────────


class BindingError(Exception):
    """Surface kdcms error code to the UI layer. ``code`` is the i18n key."""

    def __init__(self, code: str, http_status: int = 400):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


async def request_binding(cfg: Config) -> dict:
    """V15 · 设备端发起绑定请求（不指定目标账户）。

    服务端生成一次性 6 位 ``confirmation_code`` 并塞回 response；activate.html 显示给
    用户；账户在 kvmind.com 上 accept 时必须输入此码（OOB 防 UID 偷窥劫持）。
    设备端**不**输入 email——这是 V15 的核心安全约束。
    """
    url = f"{cfg.bridge.backend_url}/api/device/binding-requests"
    uid = get_uid()
    payload = {
        "device_uid": uid,
        "device_name": uid,
        "online_status": "online",
    }
    status, body = await _post_signed(url, payload)
    data = _unwrap(status, body, "binding.request.failed")
    # 发起成功 → 进入"绑定进行中"窗口：心跳降到 fast 间隔，UI 能在 1s 内看到对端
    # 决策，而不用等 60s 一跳。对端 accept 后 heartbeat._one_tick 自动 disarm。
    arm_fast_poll()
    # 缓存 6 位 OOB 码 + account_url 到 state.db（10 分钟 TTL，与 kdcms binding
    # 请求 TTL 对齐）— activate.html 持续从这里读，不会受 30s lastResult TTL 影响。
    save_pending_mine(data)
    return data


async def decide_binding(cfg: Config, request_id: int, accept: bool) -> dict:
    url = f"{cfg.bridge.backend_url}/api/device/binding-requests/{int(request_id)}/decide"
    decision = "accept" if accept else "decline"
    status, body = await _post_signed(url, {"decision": decision})
    data = _unwrap(status, body, "binding.decide.failed")
    # 本设备作为对端 accept 了 account-initiated 请求：保持 fast_poll 让下一次
    # 心跳最多 5s 就能把 claimState='claimed' 同步回 state.db，UI 立刻切 bound。
    if accept:
        arm_fast_poll()
    return data


async def release_binding(cfg: Config) -> dict:
    """V15 · 设备主动解除当前账户绑定。保留 device_keys（**不**走 factory reset），
    清 customer_id + 释放 seat。
    """
    url = f"{cfg.bridge.backend_url}/api/device/binding-requests/release"
    status, body = await _post_signed(url, {})
    data = _unwrap(status, body, "binding.release.failed")
    # 立即清本地缓存：bound_customer_email + pending_mine + last_result。
    try:
        get_state_db().kv_delete("bound_customer_email")
    except Exception:
        pass
    clear_pending_mine()
    clear_last_result()
    disarm_fast_poll()
    # 关键：主动把进程内 cfg.subscription 翻 unclaimed / local_free —— 设备本地
    # /api/subscription 端点直接从 cfg 读，不等下一拍心跳同步；否则 UI
    # refreshEntitlement 会拿到 stale claimed 状态，把 state.claimed 重新翻回 true，
    # bound 视图卡住不动。features 全部 reset 到 free 默认。
    try:
        cfg.subscription.claim_state = "unclaimed"
        cfg.subscription.entitlement_state = "local_free"
        cfg.subscription.assigned_subscription_id = None
        cfg.subscription.tunnel = False
        cfg.subscription.messaging = False
        cfg.subscription.ota = False
        cfg.subscription.scheduled_tasks = False
        cfg.subscription.myclaw_limit = 5
        cfg.subscription.myclaw_daily_limit = 20
        cfg.subscription.myclaw_max_action_level = 1
        from .config import save_config
        save_config(cfg)
    except Exception as e:
        log.warning("release_binding: cfg sync failed: %s", e)
    return data


async def cancel_binding(cfg: Config, request_id: int) -> dict:
    url = f"{cfg.bridge.backend_url}/api/device/binding-requests/{int(request_id)}/cancel"
    status, body = await _post_signed(url, {})
    data = _unwrap(status, body, "binding.cancel.failed")
    # 用户主动取消自己发起的请求 → 立即退出加速窗口，心跳回落 60s。
    disarm_fast_poll()
    # 取消即丢失对应 6 位码上下文，清缓存让 UI 回到 form 视图。
    clear_pending_mine()
    return data


def _unwrap(status: int, body: dict, fallback_code: str) -> dict:
    """kdcms success envelope: {code:200, data:..., message:...}. Non-200 or
    envelope code != 200 → raise BindingError carrying the message (which is
    an i18n key; see DeviceBindingRequestsController / AccountDevicesController)."""
    if status == 401 or status == 403:
        raise BindingError("binding.auth.invalid", status)
    envelope_code = body.get("code") if isinstance(body, dict) else None
    if status == 200 and envelope_code == 200:
        return body.get("data") or {}
    msg = (body.get("message") if isinstance(body, dict) else None) or fallback_code
    raise BindingError(str(msg), status if status else 500)


# ── Public snapshot for /api/binding/state ──────────────────────────────────


def build_state_snapshot() -> dict[str, Any]:
    """Handler-facing view:

    - ``pending``: list of account-initiated requests waiting for this device
      (heartbeat writes this slot).
    - ``lastResult``: most recent UI-visible action outcome ({code, ts, ...}).
      TTL 30s + 跨字段一致性校验（见下）。
    - ``boundCustomerEmail``: filled by subscription sync once device is
      successfully bound; UI flips to the "bound" view as soon as this is set.
    """
    db = get_state_db()
    pending = load_pending_snapshot()
    bound_email = db.kv_get("bound_customer_email") or None
    last_result = load_last_result()

    # 一致性校验：lastResult 是 toast 语义。V15 之后 6 位码不再依赖 lastResult
    # （由 pending_mine 承载），lastResult 只用作"刚刚发生的对端动作 toast"。
    #
    # 规则：
    #   binding.accepted       需要 bound_customer_email 非空（已绑定）
    #   binding.declined       toast 由 heartbeat 发现 REJECTED 时主动写入；保留 30s
    #                          让用户看到"被拒绝了"，过 TTL 自动消失
    #   binding.expired        同上
    #   binding.request.sent   仅辅助提示，6 位码本身在 pending_mine 里独立显示
    if last_result:
        code = last_result.get("code")
        consistent = True
        if code == "binding.accepted" and not bound_email:
            consistent = False
        if not consistent:
            clear_last_result()
            last_result = None

    return {
        "pending": pending,
        "lastResult": last_result,
        "boundCustomerEmail": bound_email,
        "pendingMine": load_pending_mine(),
    }
