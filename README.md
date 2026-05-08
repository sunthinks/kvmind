# KVMind — AI-Powered Remote Server Management

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-PiKVM%20%7C%20BliKVM-lightgrey)](https://pikvm.org/)

KVMind adds an AI assistant (MyClaw) to PiKVM, enabling natural language control of remote servers via keyboard, mouse, and screen analysis.

**License**: MIT — see [LICENSE](./LICENSE) for full text. Third-party dependency notices: see [NOTICES.md](./NOTICES.md).

## Architecture

```
┌─────────────────────────────────────────────┐
│ Browser (KVMind Console + MyClaw Panel)     │
│ ├── kvmind-core.js    (主逻辑・i18n・API)  │
│ ├── kvmind-stream.js  (H.264/MJPEG 视频流)  │
│ ├── kvmind-hid.js     (键鼠输入)            │
│ ├── kvmind-session.js (PiKVM WS 会话)       │
│ ├── myclaw-gateway.js (MyClaw WS 客户端)    │
│ ├── myclaw-sidebar.js (侧栏 Chat/Tasks)     │
│ └── kvmind-theme.js   (主题切换)            │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx (TLS termination, port 443)      │
│ ├── /kvm/*           → KVMind 控制台 UI     │
│ ├── /login/          → 登录页               │
│ ├── /setup.html      → 初始化向导           │
│ ├── /kdkvm/api/*     → KVMind Bridge API    │
│ ├── /kdkvm/ws/*      → KVMind Bridge WS     │
│ ├── /api/*           → PiKVM kvmd API       │
│ ├── /api/media/ws    → PiKVM H.264 流       │
│ ├── /streamer/*      → PiKVM MJPEG 流       │
│ └── /share/*         → PiKVM 静态资源       │
└──────────────┬──────────────────────────────┘
               │
  ┌────────────▼──────────────────────────────┐
  │ KVMind Bridge (Python, port 8765)         │
  │ ├── server.py        (HTTP/WS 服务)       │
  │ ├── config.py        (配置 + KNOWN_PROVIDERS) │
  │ ├── auth_manager.py  (设备认证)            │
  │ ├── kvmind_client.py (AI 调用 + 阶段超时 + 记忆注入) │
  │ ├── model_router.py  (顺序 fallback + 语义校验 + 兜底) │
  │ ├── ai_provider.py   (OpenAI/Anthropic 适配) │
  │ ├── ai_intents.py   (Fallback Prompt)     │
  │ ├── memory_store.py  (长期记忆 SQLite)    │
  │ ├── chat_store.py    (聊天持久化 SQLite)  │
  │ ├── kvm/             (KVM 硬件抽象层)     │
  │ └── innerclaw/       (InnerClaw v3 AI 执行引擎)     │
  └────────────┬──────────────────────────────┘
  ┌────────────▼────────┐
  │ PiKVM (kvmd)        │
  │ ├── HID (keyboard/  │
  │ │   mouse control)   │
  │ ├── Media (WebRTC/   │
  │ │   H.264/MJPEG)     │
  │ └── ATX (power)      │
  └─────────────────────┘
```

## Quick Install

```bash
# One-line install (latest release):
curl -sSL https://kvmind.com/install.sh | bash

# Install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s kdkvm-v0.5.61.zip

# Reset to clean state (wipes config, memory, auth — keeps OS):
curl -sSL https://kvmind.com/install.sh | bash -s reset

# Reset and install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s reset kdkvm-v0.5.61.zip

# Then open: https://<device-ip>/setup.html
```

### Install Parameters

| Parameter | Description |
|-----------|-------------|
| *(none)* | Install / upgrade to latest release |
| `kdkvm-vX.Y.Z.zip` | Install a specific release version |
| `--reset` | Full reset before install: removes `/etc/kdkvm/` config, `/var/lib/kvmd/msd/.kdkvm/` data (memory, auth, chat), and unregisters the device from KVMind cloud. Use when re-deploying or troubleshooting a stuck state. |
| `--reset kdkvm-vX.Y.Z.zip` | Reset then install a specific version |

## Requirements

- Supported hardware: PiKVM V3/V4, BliKVM v4 (PiKVM OS). NanoKVM is on the v0.4.x roadmap and **not yet implemented** — `install.sh` will refuse to run on NanoKVM hardware.
- Device OS with KVM daemon running (kvmd or equivalent)
- AI provider: Gemini / Claude / OpenAI API key, or Ollama / custom OpenAI-compatible endpoint

## Files

| Path | Description |
|------|-------------|
| /opt/kvmind/kdkvm/lib/ | Python backend modules |
| /opt/kvmind/kdkvm/web/ | Frontend JS/HTML/CSS |
| /opt/kvmind/kdkvm/bin/ | Shell scripts (register, heartbeat, tunnel) |
| /etc/kdkvm/ | Configuration (config.yaml, ai.env, device.uid, tunnel.token, prompts/) |
| /var/lib/kvmd/msd/.kdkvm/ | Persistent data (memory.db, auth.json) on MSD partition (hidden dir) |

## Systemd Services

| Service | Description |
|---------|-------------|
| kdkvm.service | kdkvm Bridge (Python, port 8765) — also drives heartbeat, registration and OTA as in-process asyncio tasks |
| kdkvm-cloudflared.service | Cloudflare Tunnel (cloudflared, auto-managed) |

> The earlier `kvmind-heartbeat.timer` / `kvmind-register.timer` / `kvmind-updater.timer` systemd units were retired in M3.4 / M5 §16 — those loops now live inside the bridge process (`lib/heartbeat.py`, `lib/ota.py`) so there is no shell-script / cron-style indirection left.

## Subscription & Tunnel Lifecycle

```
购买订阅（带 device_uid）
  → Stripe webhook → 创建 Order + Subscription
  → 绑定设备（device.customer_id + plan_id）
  → 自动开通 Cloudflare Tunnel
  → 心跳同步 → 设备启动 cloudflared

取消订阅
  → status: active → cancelling（服务继续到 endDate）
  → 到期后定时任务：回收隧道 + status → expired

设备心跳（每60秒）
  → POST /api/devices/heartbeat → 返回 planType + tunnelToken + features
  → heartbeat 直连 bridge 8765（POST http://127.0.0.1:8765/api/subscription/sync）
  → Nginx 封堵外部 /kdkvm/api/subscription/sync（返回 403）
  → tunnelToken / features 变化时自动启停 cloudflared、OTA、Telegram、MyClaw 限额和定时任务
```

**关键路径**：所有配置文件路径统一为 `/etc/kdkvm/`（不是 `/etc/kvmind/`）

## Post-Install

1. Open setup wizard: `https://<pikvm-ip>/setup.html`
2. Choose AI plan (free trial / subscription / custom API key)
3. Set access password and complete initialization
4. Open console: `https://<pikvm-ip>/kvm/`

## MyClaw Capabilities

- **Screenshot & Analysis**: Captures remote screen, analyzes via AI Vision
- **Keyboard/Mouse**: Sends keystrokes and mouse clicks via PiKVM HID API
- **System Management**: Runs commands, checks services, manages storage
- **Multi-Provider AI**: Gemini, Claude, ChatGPT, Ollama, or custom OpenAI-compatible
- **Safe Local Models**: Local models that emit tool JSON as text are downgraded to suggest mode, not executed
- **Long-term Memory**: Remembers user preferences and device info across sessions
- **Natural Language**: Chinese, Japanese, English
