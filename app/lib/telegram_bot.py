"""
KVMind Telegram Bot — Long-polling bot connecting Telegram to InnerClaw.

Modes:
  - Normal text → ask mode (screenshot + AI analysis)
  - /plan <task> → suggest mode (generate plan, no execution)
  - /do <instruction> → auto mode (Runner plans + executes)
  - /ss or /screenshot → screenshot only (no AI)
  - /help → command list

Runs as an asyncio background task inside the KVMind server.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Set

import aiohttp

from .innerclaw import Runner
from .innerclaw.adapters.telegram import TelegramAdapter
from .myclaw_gateway import MyClawRateLimitError, MyClawForbiddenError, MyClawOfflineError

log = logging.getLogger(__name__)

HELP_TEXT = """🤖 *KVMind Telegram Bot*

直接发文字 → AI 分析当前屏幕并回答
/plan <任务> → AI 生成执行计划（不执行）
/do <指令> → AI 自动执行操作（如：/do 打开终端）
/ss → 截取当前屏幕
/help → 显示帮助"""


class TelegramBot:
    """
    Telegram Bot using getUpdates long-polling.

    Designed to run as ``asyncio.create_task(bot.start())``
    alongside the aiohttp web server.
    """

    def __init__(
        self,
        token: str,
        kvm: object,
        kvmind: object,
        audit: object,
        allowed_chats: Optional[list[int]] = None,
        gateway: object | None = None,
    ) -> None:
        self._token = token
        self._api = f"https://api.telegram.org/bot{token}"
        self._kvm = kvm
        self._kvmind = kvmind
        self._audit = audit
        self._gateway = gateway
        self._allowed: Set[int] = set(allowed_chats) if allowed_chats else set()
        self._offset: int = 0
        self._running: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Main polling loop — runs until stop() is called."""
        self._running = True
        log.info("[Telegram] Bot polling started")
        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    updates = await self._poll(session)
                    for update in updates:
                        # Handle each message in its own task so one slow
                        # response doesn't block the next update.
                        asyncio.create_task(self._safe_handle(update))
                except asyncio.CancelledError:
                    break
                except Exception:
                    log.exception("[Telegram] Polling error, retry in 5s")
                    await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False

    # ── Polling ──────────────────────────────────────────────────────────────

    async def _poll(self, session: aiohttp.ClientSession) -> list[dict]:
        """getUpdates with 30s long-poll timeout."""
        try:
            async with session.post(
                f"{self._api}/getUpdates",
                json={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    log.warning("[Telegram] getUpdates error: %s", data)
                    await asyncio.sleep(3)
                    return []
                results = data.get("result", [])
                if results:
                    self._offset = results[-1]["update_id"] + 1
                return results
        except asyncio.TimeoutError:
            return []

    # ── Message handling ─────────────────────────────────────────────────────

    async def _safe_handle(self, update: dict) -> None:
        """Wrapper that catches errors per-message so the loop continues."""
        try:
            await self._handle(update)
        except Exception:
            log.exception("[Telegram] Error handling update %s", update.get("update_id"))

    async def _handle(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return

        # Auth
        if self._allowed and chat_id not in self._allowed:
            log.debug("[Telegram] Ignored message from unauthorized chat %d", chat_id)
            return

        adapter = TelegramAdapter(self._token, chat_id)
        try:
            if text in ("/start", "/help"):
                await adapter._send_text(HELP_TEXT)

            elif text in ("/screenshot", "/ss"):
                await self._cmd_screenshot(adapter)

            elif text.startswith("/plan ") or text.startswith("/plan@"):
                instruction = text.split(None, 1)[1] if " " in text else ""
                await self._cmd_plan(adapter, instruction)

            elif text.startswith("/do ") or text.startswith("/do@"):
                instruction = text.split(None, 1)[1] if " " in text else ""
                await self._cmd_do(adapter, instruction)

            else:
                await self._cmd_ask(adapter, text)

        finally:
            await adapter.close()

    # ── Commands ─────────────────────────────────────────────────────────────

    async def _cmd_screenshot(self, adapter: TelegramAdapter) -> None:
        """Send current screen screenshot."""
        try:
            screenshot = await self._kvm.snapshot_b64()
            await adapter._send_photo(screenshot, caption="📸 当前屏幕")
        except Exception as e:
            await adapter._send_text(f"❌ 截图失败: {e}")

    async def _cmd_ask(self, adapter: TelegramAdapter, question: str) -> None:
        """Ask mode: screenshot + AI analysis via Runner."""
        try:
            runner = Runner(
                kvm=self._kvm,
                ai_client=self._kvmind,
                audit=self._audit,
                mode="ask",
                lang="zh",
                gateway=self._gateway,
                trigger="im",
            )
            await adapter._send_photo(
                await self._kvm.snapshot_b64(), caption="📸 当前屏幕",
            )
            async for event in runner.run(question):
                await adapter.send_event(event.as_dict())
        except MyClawRateLimitError as e:
            await adapter._send_text(f"⏳ MyClaw 使用已达上限（{e.usage_count}/{e.usage_limit}），{e.retry_after}秒后重试")
        except MyClawForbiddenError as e:
            await adapter._send_text(f"🚫 操作被拒绝: {e.code}")
        except MyClawOfflineError:
            await adapter._send_text("⚠️ MyClaw 服务暂时不可用")
        except Exception as e:
            log.exception("[Telegram] Ask error")
            await adapter._send_text(f"❌ AI 分析失败: {e}")

    async def _cmd_plan(self, adapter: TelegramAdapter, instruction: str) -> None:
        """Suggest mode: generate plan without executing."""
        if not instruction:
            await adapter._send_text("用法: /plan <任务>\n例如: /plan 安装 nginx")
            return

        try:
            runner = Runner(
                kvm=self._kvm,
                ai_client=self._kvmind,
                audit=self._audit,
                mode="suggest",
                lang="zh",
                gateway=self._gateway,
                trigger="im",
            )
            async for event in runner.run(instruction):
                await adapter.send_event(event.as_dict())
        except MyClawRateLimitError as e:
            await adapter._send_text(f"⏳ MyClaw 使用已达上限，{e.retry_after}秒后重试")
        except MyClawForbiddenError as e:
            await adapter._send_text(f"🚫 操作被拒绝: {e.code}")
        except MyClawOfflineError:
            await adapter._send_text("⚠️ MyClaw 服务暂时不可用")
        except Exception as e:
            log.exception("[Telegram] Plan error")
            await adapter._send_text(f"❌ 规划失败: {e}")

    async def _cmd_do(self, adapter: TelegramAdapter, instruction: str) -> None:
        """Auto mode: Runner plans and executes the instruction."""
        if not instruction:
            await adapter._send_text("用法: /do <指令>\n例如: /do 打开终端")
            return

        await adapter._send_text(f"🤖 执行中: {instruction}")

        try:
            runner = Runner(
                kvm=self._kvm,
                ai_client=self._kvmind,
                audit=self._audit,
                mode="auto",
                lang="zh",
                gateway=self._gateway,
                trigger="im",
            )
            async for event in runner.run(instruction):
                await adapter.send_event(event.as_dict())
        except MyClawRateLimitError as e:
            await adapter._send_text(f"⏳ MyClaw 使用已达上限，{e.retry_after}秒后重试")
        except MyClawForbiddenError as e:
            await adapter._send_text(f"🚫 操作被拒绝: {e.code}")
        except MyClawOfflineError:
            await adapter._send_text("⚠️ MyClaw 服务暂时不可用")
        except Exception as e:
            log.exception("[Telegram] Runner error")
            await adapter._send_text(f"❌ 执行失败: {e}")

        # Send final screenshot after execution
        try:
            screenshot = await self._kvm.snapshot_b64()
            await adapter._send_photo(screenshot, caption="📸 执行完成后的屏幕")
        except Exception as e:
            log.warning("[Telegram] Failed to send final screenshot: %s", e)
