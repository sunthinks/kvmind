<p align="right">
  <b>English</b> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.ja.md">日本語</a>
</p>

# KVMind Community Edition

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-PiKVM%20%7C%20BliKVM-lightgrey)](https://pikvm.org/)

KVMind adds a natural-language AI assistant to your PiKVM device, letting you
drive a remote server through keyboard, mouse and screen analysis — all from a
modern web console.

> This repository is the **Community Edition** of KVMind — fully local,
> DIY-friendly, MIT-licensed. The managed **Cloud Edition** (auto-execute,
> remote tunnel, multi-device fleet, team collaboration) lives at
> [kvmind.com](https://kvmind.com).
>
> Project status: **beta**. Runs entirely on the device — no cloud account
> required. Current version: **v0.5.61** (Hanami).

## Highlights

- **Drop-in for PiKVM** — installs alongside `kvmd` on PiKVM V3/V4 and
  PiKVM-OS-compatible boards (BliKVM v4 verified, NanoKVM planned).
- **Bring your own AI** — works with Gemini, Claude, ChatGPT, Ollama, or any
  OpenAI-compatible endpoint.
- **Air-gap friendly** — config, credentials, and chat history stay on the
  device. No telemetry, no required cloud backend.
- **Safe tool execution** — power, system commands and other dangerous actions
  are gated by confirmation prompts and an action-level policy.
- **Modern console** — H.264 / MJPEG video, on-screen keyboard, clipboard,
  full-screen, dark/light themes, and zh / ja / en i18n.

## Community vs Cloud

Both editions share the same on-device core. The difference is *where*
execution authority and fleet management live.

| | Community (this repo) | [Cloud](https://kvmind.com) |
|---|:---:|:---:|
| Screen analysis & suggestions | ✅ | ✅ |
| Bring-your-own AI key (Gemini / Claude / OpenAI / Ollama) | ✅ | ✅ |
| Manual tool execution (with confirmation) | ✅ | ✅ |
| Local chat history & memory | ✅ | ✅ |
| Self-host, air-gap capable | ✅ | — |
| MIT source — fork & modify freely | ✅ | — |
| **Auto-execute (no manual confirmation)** | — | ✅ |
| **Signed & verified tool execution (MyClaw Cloud)** | — | ✅ |
| **Remote access via managed tunnel** | — | ✅ |
| **Multi-device fleet dashboard** | — | ✅ |
| **Scheduled tasks** | — | ✅ |
| **Team access & role permissions** | — | ✅ |
| **Managed OTA updates** | — | ✅ |

**Community Edition** is for tinkerers and self-hosters — modify freely, run
fully offline, every byte of data stays on your hardware. MIT-licensed.

**Cloud Edition** is for production — managed signing, fleet operations,
automation and team workflows. See [kvmind.com](https://kvmind.com).

## Architecture

```
┌─────────────────────────────────────────────┐
│ Browser (KVMind Console)                    │
│ kvmind-core.js · kvmind-stream.js           │
│ kvmind-hid.js  · kvmind-session.js          │
│ myclaw-sidebar.js · kvmind-theme.js         │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx (TLS termination)                │
│ /kvm/*        → KVMind console              │
│ /kdkvm/api/*  → Bridge API                  │
│ /kdkvm/ws/*   → Bridge WebSocket            │
│ /api/*        → kvmd (PiKVM upstream)       │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ KVMind Bridge (Python, 127.0.0.1:8765)      │
│ server.py · config.py · auth_manager.py     │
│ kvmind_client.py · model_router.py          │
│ lib/kvm/      — hardware abstraction layer  │
│ lib/innerclaw — tool executor & guardrails  │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ PiKVM kvmd (HID, media, ATX)                │
└─────────────────────────────────────────────┘
```

## Quick Install

**Method A — kvmind.com one-line install (run on the PiKVM device):**

```bash
# Install / upgrade to latest:
curl -sSL https://kvmind.com/install.sh | bash

# Install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s kdkvm-v0.5.61.zip

# Full reset (wipes config, memory, auth, cloud binding) then install latest:
curl -sSL https://kvmind.com/install.sh | bash -s reset

# Reset then install a specific version:
curl -sSL https://kvmind.com/install.sh | bash -s reset kdkvm-v0.5.61.zip
```

**Method B — install from source / release zip (recommended for Community Edition):**

```bash
# Push from your workstation to the device (requires sshpass locally):
git clone https://github.com/sunthinks/kvmind.git
cd kvmind/kdkvm
./install.sh <device-ip> [device-password]   # default password: root

# Or download a zip from GitHub Releases, scp to the device, and run on-device:
unzip kdkvm-v0.5.61.zip && cd kdkvm-v0.5.61
sudo ./install.sh
```

### Install Parameters

| Parameter | Description |
|-----------|-------------|
| *(none)* | Install / upgrade to latest |
| `<device-ip> [password]` | Remote mode — push source from workstation and run on the device (requires `sshpass`) |
| `--reset` or `reset` | Full reset before install: wipes `/etc/kdkvm/` config, `/var/lib/kvmd/msd/.kdkvm/` data (memory, auth, chat history), and unregisters the device from the KVMind cloud. Use when re-deploying or recovering from a stuck state. **Destructive: existing cloud binding is invalidated; you must re-bind on kvmind.com.** |
| `--keep-root-pw` | Skip OS root password rotation (only when you have already provisioned a non-default root password yourself) |

After the service is up, open `https://<device-ip>/kvm/` — the setup wizard at
`/setup.html` will walk you through the initial password and AI provider
configuration.

> **About the installer**: `install.sh` is the batteries-included build —
> it provisions the device for the full managed [kvmind.com](https://kvmind.com)
> experience (remote access, auto-execute, fleet management). For a fully
> local / air-gapped install, edit `/etc/kdkvm/config.yaml` after first boot
> and clear `bridge.backend_url`; or fork this repo and rebuild a custom
> installer with `./release/build.sh`.

## Requirements

- Hardware: PiKVM V3 / V4, or BliKVM v4 running PiKVM-OS (Arch Linux ARM)
- A reachable `kvmd` service on the device (default PiKVM layout)
- Any one AI provider:
  - [Google AI Studio](https://aistudio.google.com/apikey) (Gemini)
  - [Anthropic](https://console.anthropic.com/settings/keys) (Claude)
  - [OpenAI](https://platform.openai.com/api-keys) (GPT-4o / 4.1 / o-series)
  - [Ollama](https://ollama.com) or any other OpenAI-compatible endpoint

## On-Device Layout

| Path | Purpose |
|------|---------|
| `/opt/kvmind/kdkvm/lib/` | Python backend (bridge) |
| `/opt/kvmind/kdkvm/web/` | Frontend assets |
| `/opt/kvmind/kdkvm/bin/kvmind-updater.sh` | OTA updater helper (invoked by the bridge) |
| `/etc/kdkvm/` | `config.yaml`, `ai.env`, `device.uid`, `*.pub` trust roots, prompts |
| `/var/lib/kvmd/msd/.kdkvm/` | Persistent store on the MSD partition (`state.db`, `memory.db`, `auth.json`, `chat.db`) |

## Systemd Services

| Unit | Purpose |
|------|---------|
| `kdkvm.service` | KVMind bridge (Python, port 8765) — heartbeat, registration, and OTA all run as in-process asyncio tasks |
| `kdkvm-cloudflared.service` | Optional Cloudflare Tunnel (only started after the cloud delivers a tunnel token; pure-local users can ignore it) |
| `kdkvm-updater.service` / `kdkvm-updater.timer` | OTA updates (only triggered when a cloud heartbeat advertises a new version; no-ops in local-only mode) |

> The legacy `kvmind-register.timer` / `kvmind-heartbeat.timer` /
> `kvmind-tunnel.service` units were retired in M3.4 / M5 §16 — those loops
> now live inside the bridge process (`lib/heartbeat.py`, `lib/ota.py`),
> so there is no shell-script or cron-style indirection left.

When `bridge.backend_url` in `/etc/kdkvm/config.yaml` is empty, neither the
heartbeat nor the tunnel will reach out to the cloud. KVMind runs fully on
its own without any cloud dependency.

## Configuration

A minimal `/etc/kdkvm/config.yaml`:

```yaml
kvm:
  backend: pikvm
  unix_socket: /run/kvmd/kvmd.sock

ai:
  gemini_key: "AIza..."       # or claude_key / openai_key
  timeout: 120

bridge:
  host: 127.0.0.1
  port: 8765
  mode: suggest               # suggest | auto
  # backend_url: ""           # leave empty to run fully local
  # update_url: ""            # leave empty to disable OTA
```

See `app/config.yaml.example` for the complete option surface.

## Build From Source

```bash
./release/build.sh            # produces release/dist/kdkvm-vX.Y.Z.zip
```

## Development

Bridge unit tests run standalone:

```bash
cd app && python -m pytest tests/ -v
```

Code style, module boundaries, and contribution conventions are documented in
[CODING_RULES.md](CODING_RULES.md).

## Security

- The bridge binds to `127.0.0.1` by default; all external access goes through
  `kvmd-nginx` over TLS.
- Device passwords are stored hashed; releases ship with no default credentials.
- API keys passed via environment variables are never written back to disk
  (the `source: env` skip rule in `save_config`).
- Report issues: https://github.com/sunthinks/kvmind/issues

## License

MIT License — see [LICENSE](LICENSE) for the full text. Third-party dependency
notices: see [NOTICES.md](NOTICES.md).

---

Need auto-execute, remote access, multi-device fleet management, and team
collaboration? The managed KVMind Cloud Edition is available at
[**kvmind.com**](https://kvmind.com).
