"""Tests for TaskStore concurrency + TaskScheduler entitlement lifecycle."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import Config, SubscriptionConfig
from lib.handlers.tasks import TaskScheduler, TaskStore, _build_cmd


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "tasks.json")


@pytest.fixture
def store(store_path):
    return TaskStore(store_path)


def _make_cfg(scheduled: bool = True) -> Config:
    cfg = Config()
    cfg.subscription = SubscriptionConfig(scheduled_tasks=scheduled)
    return cfg


def _stub_task_def(tid: str = "t1", enabled: bool = True, every_ms: int = 60_000) -> dict:
    return {
        "id": tid,
        "name": "stub",
        "task_type": "check_uptime",
        "args": None,
        "schedule": {"kind": "every", "every_ms": every_ms},
        "enabled": enabled,
        "created_at": 0,
        "last_run_at": None,
        "run_count": 0,
        "last_result": None,
    }


# ── TaskStore ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_missing_file_returns_empty(store):
    assert await store.list() == []


@pytest.mark.asyncio
async def test_append_then_list(store):
    await store.append(_stub_task_def("a"))
    await store.append(_stub_task_def("b"))
    listed = await store.list()
    assert [t["id"] for t in listed] == ["a", "b"]


@pytest.mark.asyncio
async def test_toggle_flips_enabled(store):
    await store.append(_stub_task_def("x", enabled=True))
    found = await store.toggle("x")
    assert found is not None and found["enabled"] is False

    listed = await store.list()
    assert listed[0]["enabled"] is False


@pytest.mark.asyncio
async def test_toggle_unknown_returns_none(store):
    assert await store.toggle("nope") is None


@pytest.mark.asyncio
async def test_delete_returns_true_when_removed(store):
    await store.append(_stub_task_def("a"))
    await store.append(_stub_task_def("b"))
    assert await store.delete("a") is True
    listed = await store.list()
    assert [t["id"] for t in listed] == ["b"]


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(store):
    assert await store.delete("nope") is False


@pytest.mark.asyncio
async def test_update_runtime_state_partial(store):
    await store.append(_stub_task_def("a"))
    await store.update_runtime_state("a", last_run_at=123, run_count=7, last_result="ok")
    [row] = await store.list()
    assert row["last_run_at"] == 123
    assert row["run_count"] == 7
    assert row["last_result"] == "ok"
    assert row["task_type"] == "check_uptime"  # unaffected fields preserved


@pytest.mark.asyncio
async def test_concurrent_appends_do_not_lose_updates(store):
    """50 coroutines all append in parallel — final file must contain 50 unique rows.

    Pre-refactor _save_tasks did read-modify-write without any lock; aiohttp
    coroutines yielded inside msd_rw and could overwrite each other. This test
    pins the lock contract: with the asyncio.Lock + atomic temp+rename, no
    update is silently dropped under concurrency.
    """
    n = 50
    await asyncio.gather(*[
        store.append(_stub_task_def(f"id{i:02d}")) for i in range(n)
    ])
    listed = await store.list()
    ids = sorted(t["id"] for t in listed)
    assert len(ids) == n
    assert len(set(ids)) == n


@pytest.mark.asyncio
async def test_corrupt_file_recovers_to_empty(store, store_path):
    # Simulate a truncated / corrupt write — _read_unsafe must not crash.
    Path(store_path).write_text("{ this is not valid json")
    assert await store.list() == []
    # And subsequent append still works (overwrites with valid JSON).
    await store.append(_stub_task_def("recovered"))
    assert [t["id"] for t in await store.list()] == ["recovered"]


@pytest.mark.asyncio
async def test_no_temp_file_left_behind(store, store_path):
    await store.append(_stub_task_def("a"))
    parent = Path(store_path).parent
    leftovers = list(parent.glob("tasks.json.tmp.*"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_atomic_write_uses_replace(store, store_path):
    """The on-disk file should always be a complete JSON array — never a partial write.

    Validate by inspecting the bytes after each append.
    """
    for i in range(10):
        await store.append(_stub_task_def(f"id{i}"))
        with open(store_path, "r") as f:
            parsed = json.load(f)  # would throw if mid-write torn
        assert len(parsed) == i + 1


# ── TaskScheduler ─────────────────────────────────────────────────────────────


@pytest.fixture
def noop_run_loop(monkeypatch):
    """Replace _run_loop with a long sleep so tests don't actually exec commands."""
    async def fake_loop(self, task_def):
        await asyncio.sleep(60)  # cancelled before asserts
    monkeypatch.setattr(TaskScheduler, "_run_loop", fake_loop)


@pytest.mark.asyncio
async def test_is_entitled_reads_cfg(store):
    sched_on = TaskScheduler(store, _make_cfg(True))
    sched_off = TaskScheduler(store, _make_cfg(False))
    assert sched_on.is_entitled() is True
    assert sched_off.is_entitled() is False


@pytest.mark.asyncio
async def test_start_noop_when_not_entitled(store, noop_run_loop):
    sched = TaskScheduler(store, _make_cfg(False))
    assert sched.start(_stub_task_def("a")) is False
    assert sched.is_running("a") is False


@pytest.mark.asyncio
async def test_start_skips_disabled_and_legacy(store, noop_run_loop):
    sched = TaskScheduler(store, _make_cfg(True))
    assert sched.start(_stub_task_def("a", enabled=False)) is False
    legacy = _stub_task_def("b")
    legacy["legacy"] = True
    assert sched.start(legacy) is False


@pytest.mark.asyncio
async def test_start_then_stop(store, noop_run_loop):
    sched = TaskScheduler(store, _make_cfg(True))
    assert sched.start(_stub_task_def("a")) is True
    assert sched.is_running("a") is True
    assert sched.stop("a") is True
    assert sched.is_running("a") is False
    # double-stop is a no-op
    assert sched.stop("a") is False


@pytest.mark.asyncio
async def test_start_all_if_entitled_starts_only_enabled(store, noop_run_loop):
    await store.append(_stub_task_def("a", enabled=True))
    await store.append(_stub_task_def("b", enabled=False))
    legacy = _stub_task_def("c", enabled=True)
    legacy["legacy"] = True
    await store.append(legacy)

    sched = TaskScheduler(store, _make_cfg(True))
    started = await sched.start_all_if_entitled()
    assert started == 1
    assert sched.is_running("a") is True
    assert sched.is_running("b") is False
    assert sched.is_running("c") is False

    sched.stop_all()


@pytest.mark.asyncio
async def test_start_all_if_entitled_noop_when_off(store, noop_run_loop):
    await store.append(_stub_task_def("a", enabled=True))
    sched = TaskScheduler(store, _make_cfg(False))
    started = await sched.start_all_if_entitled()
    assert started == 0
    assert sched.is_running("a") is False


@pytest.mark.asyncio
async def test_stop_all_then_restart_after_entitlement_back(store, noop_run_loop):
    """The exact scenario from the audit: subscription off → on toggle should
    cleanly stop and restart tasks without dangling asyncio handles."""
    await store.append(_stub_task_def("a"))
    await store.append(_stub_task_def("b"))

    cfg = _make_cfg(True)
    sched = TaskScheduler(store, cfg)
    assert await sched.start_all_if_entitled() == 2

    # entitlement revoked
    cfg.subscription.scheduled_tasks = False
    stopped = sched.stop_all()
    assert stopped == 2
    assert sched.is_running("a") is False

    # stop_all is idempotent
    assert sched.stop_all() == 0

    # entitlement restored
    cfg.subscription.scheduled_tasks = True
    assert await sched.start_all_if_entitled() == 2
    sched.stop_all()


@pytest.mark.asyncio
async def test_shutdown_persists_live_defs(store, noop_run_loop):
    await store.append(_stub_task_def("a"))
    sched = TaskScheduler(store, _make_cfg(True))
    sched.start(_stub_task_def("a"))

    # simulate the run loop having ticked
    sched._live_defs["a"]["last_run_at"] = 999
    sched._live_defs["a"]["run_count"] = 3
    sched._live_defs["a"]["last_result"] = "ok"

    await sched.shutdown()
    [row] = await store.list()
    assert row["last_run_at"] == 999
    assert row["run_count"] == 3
    assert row["last_result"] == "ok"


@pytest.mark.asyncio
async def test_shutdown_no_deadlock_when_run_loop_owns_lock(store):
    """0.5.36 regression: cleanup ordering deadlocked when a _run_loop held
    TaskStore._lock while shutdown's flush phase tried to acquire it.

    We simulate a run_loop that grabs the lock and never releases it (worst-case),
    then call shutdown(). Pre-fix this would hang forever and systemd SIGKILLed
    the process at 90s. Post-fix: cancel runs first, await them (they unwind their
    lock guards via finally), then flush — bounded total time.
    """
    await store.append(_stub_task_def("a"))
    sched = TaskScheduler(store, _make_cfg(True))

    lock_held = asyncio.Event()
    cancel_acked = asyncio.Event()

    async def hostile_loop(self, task_def):
        # Acquire the store lock, then sleep forever. If shutdown() were to
        # await flush *before* cancellation, it would deadlock here.
        async with self._store._lock:
            lock_held.set()
            try:
                await asyncio.sleep(3600)
            finally:
                cancel_acked.set()

    # Replace _run_loop on this instance only
    bound = hostile_loop.__get__(sched, TaskScheduler)
    sched._run_loop = bound  # type: ignore[assignment]

    sched.start(_stub_task_def("a"))
    await asyncio.wait_for(lock_held.wait(), timeout=2.0)

    # Must complete within a few seconds — pre-fix this hung indefinitely
    await asyncio.wait_for(sched.shutdown(), timeout=5.0)
    assert cancel_acked.is_set()
    assert sched.is_running("a") is False


@pytest.mark.asyncio
async def test_shutdown_noop_when_no_tasks(store):
    sched = TaskScheduler(store, _make_cfg(True))
    # Should return immediately without touching the store lock
    await asyncio.wait_for(sched.shutdown(), timeout=1.0)


# ── Helpers around _build_cmd (covers ping arg validation regression) ────────


def test_build_cmd_unknown_type():
    assert _build_cmd("nonexistent") is None


def test_build_cmd_ping_validates_target():
    assert _build_cmd("ping", {"target": "8.8.8.8"}) == ["ping", "-c", "1", "-W", "3", "8.8.8.8"]
    assert _build_cmd("ping", {"target": "; rm -rf /"}) is None
    assert _build_cmd("ping", {}) is None


def test_build_cmd_zero_arg_template():
    assert _build_cmd("check_uptime") == ["uptime"]
