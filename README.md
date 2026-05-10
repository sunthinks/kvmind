<p align="right">
  <b>English</b> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.ja.md">日本語</a>
</p>

# KVMind — AI-Powered Remote Server Management

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-PiKVM%20%7C%20BliKVM-lightgrey)](https://pikvm.org/)

KVMind adds an AI assistant (MyClaw) to PiKVM, enabling natural language control of remote servers via keyboard, mouse, and screen analysis.

> Project status: **beta**. Current version: **v0.5.71** (Hanami).

**License**: Apache License 2.0 — see [LICENSE](./LICENSE) for full text. Third-party dependency notices: see [NOTICES.md](./NOTICES.md).

## Architecture

```
┌─────────────────────────────────────────────┐
│ Browser (KVMind Console + MyClaw Panel)     │
│ ├── kvmind-core.js    (core logic / i18n / API) │
│ ├── kvmind-stream.js  (H.264 / MJPEG video)     │
│ ├── kvmind-hid.js     (keyboard / mouse input)  │
│ ├── kvmind-session.js (PiKVM WS session)        │
│ ├── myclaw-gateway.js (MyClaw WS client)        │
│ ├── myclaw-sidebar.js (sidebar Chat / Tasks)    │
│ └── kvmind-theme.js   (theme toggle)            │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx (TLS termination, port 443)      │
│ ├── /kvm/*           → KVMind console UI    │
│ ├── /login/          → login page           │
│ ├── /setup.html      → setup wizard         │
│ ├── /kdkvm/api/*     → KVMind Bridge API    │
│ ├── /kdkvm/ws/*      → KVMind Bridge WS     │
│ ├── /api/*           → PiKVM kvmd API       │
│ ├── /api/media/ws    → PiKVM H.264 stream   │
│ ├── /streamer/*      → PiKVM MJPEG stream   │
│ └── /share/*         → PiKVM static assets  │
└──────────────┬──────────────────────────────┘
               │
  ┌────────────▼──────────────────────────────┐
  │ KVMind Bridge (Python, port 8765)         │
  │ ├── server.py        (HTTP / WS server)              │
  │ ├── config.py        (config + KNOWN_PROVIDERS)      │
  │ ├── auth_manager.py  (device authentication)         │
  │ ├── kvmind_client.py (AI calls + per-stage timeout + memory) │
  │ ├── model_router.py  (sequential fallback + semantic validation) │
  │ ├── ai_provider.py   (OpenAI / Anthropic adapters)   │
  │ ├── ai_intents.py    (fallback prompts)              │
  │ ├── memory_store.py  (long-term memory, SQLite)      │
  │ ├── chat_store.py    (chat persistence, SQLite)      │
  │ ├── kvm/             (KVM hardware abstraction)      │
  │ └── innerclaw/       (InnerClaw v3 tool execution)   │
  └────────────┬──────────────────────────────┘
  ┌────────────▼────────┐
  │ PiKVM (kvmd)        │
  │ ├── HID (keyboard / │
  │ │   mouse control)  │
  │ ├── Media (WebRTC / │
  │ │   H.264 / MJPEG)  │
  │ └── ATX (power)     │
  └─────────────────────┘
```

## Quick Install

```bash
# One-line install (latest release):
curl -sSL https://kvmind.com/install.sh | bash

# Install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s kdkvm-v0.5.71.zip

# Reset to clean state (wipes config, memory, auth — keeps OS):
curl -sSL https://kvmind.com/install.sh | bash -s reset

# Reset and install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s reset kdkvm-v0.5.71.zip

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
Purchase subscription (with device_uid)
  → Stripe webhook → create Order + Subscription
  → bind device (device.customer_id + plan_id)
  → auto-provision Cloudflare Tunnel
  → heartbeat sync → device starts cloudflared

Cancel subscription
  → status: active → cancelling (service continues until endDate)
  → after expiry, scheduled job: tear down tunnel + status → expired

Device heartbeat (every 60 s)
  → POST /api/devices/heartbeat → returns planType + tunnelToken + features
  → heartbeat reaches bridge 8765 directly
    (POST http://127.0.0.1:8765/api/subscription/sync)
  → Nginx blocks external /kdkvm/api/subscription/sync (returns 403)
  → on tunnelToken / features change, auto-start/stop cloudflared, OTA,
    Telegram, MyClaw rate limits and scheduled tasks
```

**Path convention**: all configuration files live under `/etc/kdkvm/` (not `/etc/kvmind/`).

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
