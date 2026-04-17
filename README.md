# KVMind — AI-Powered KVM Assistant

KVMind adds a natural-language AI assistant to your PiKVM device, letting you
control remote servers through keyboard, mouse and screen analysis — all from
a modern web console.

> Project status: **beta**. Runs fully on-device; no cloud account required.

## Highlights

- **Drop-in for PiKVM** — installs alongside `kvmd` on PiKVM V3/V4 and PiKVM-OS
  compatible boards (BliKVM v4 tested; NanoKVM planned).
- **Bring your own AI** — works with Gemini, Claude, ChatGPT, Ollama, or any
  OpenAI-compatible endpoint.
- **Air-gapped friendly** — all configuration, credentials and chat history are
  stored locally. No telemetry, no mandatory cloud backend.
- **Safe tool execution** — dangerous operations (power, system commands) are
  gated through confirmation and action-level policies.
- **Modern console** — H.264 / MJPEG video, virtual keyboard, clipboard,
  full-screen, dark/light themes, zh/ja/en i18n.

## Architecture

```
┌─────────────────────────────────────────────┐
│ Browser (KVMind console)                    │
│ kvmind-core.js · kvmind-stream.js           │
│ kvmind-hid.js  · kvmind-session.js          │
│ myclaw-sidebar.js · kvmind-theme.js         │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx (TLS termination)                │
│ /kvm/*        → KVMind console              │
│ /kdkvm/api/*  → bridge API                  │
│ /kdkvm/ws/*   → bridge WebSocket            │
│ /api/*        → kvmd (PiKVM upstream)       │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ KVMind Bridge (Python, 127.0.0.1:8765)      │
│ server.py · config.py · auth_manager.py     │
│ kvmind_client.py · model_router.py          │
│ lib/kvm/      — hardware abstraction        │
│ lib/innerclaw — tool executor & guardrails  │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ PiKVM kvmd (HID, media, ATX)                │
└─────────────────────────────────────────────┘
```

## Quick install

On your PiKVM device:

```bash
# Download the latest release zip from GitHub Releases, then:
unzip kdkvm-vX.Y.Z.zip && cd kdkvm-vX.Y.Z
sudo ./install.sh
```

Once the service is up, open `https://<device-ip>/kvm/` — the setup wizard at
`/setup.html` will guide you through the initial password and AI provider
configuration.

## Requirements

- Hardware: PiKVM V3 / V4 or BliKVM v4 running PiKVM-OS (Arch Linux ARM)
- `kvmd` service reachable on the device (default PiKVM layout)
- An AI provider — one of:
  - [Google AI Studio](https://aistudio.google.com/apikey) (Gemini)
  - [Anthropic](https://console.anthropic.com/settings/keys) (Claude)
  - [OpenAI](https://platform.openai.com/api-keys) (GPT-4o / 4.1 / o-series)
  - [Ollama](https://ollama.com) or any other OpenAI-compatible endpoint

## Layout on device

| Path | Purpose |
|------|---------|
| `/opt/kvmind/kdkvm/lib/` | Python backend (bridge) |
| `/opt/kvmind/kdkvm/web/` | Frontend assets |
| `/opt/kvmind/kdkvm/bin/` | Helper scripts |
| `/etc/kdkvm/` | `config.yaml`, `ai.env`, `device.uid`, prompts |
| `/var/lib/kvmd/msd/.kdkvm/` | Persistent store (`memory.db`, `auth.json`) on MSD partition |

## Systemd services

| Unit | Purpose |
|------|---------|
| `kvmind.service` | KVMind bridge (Python, port 8765) |
| `kvmind-register.timer` | Optional cloud registration (no-op if `backend_url` empty) |
| `kvmind-heartbeat.timer` | Optional cloud heartbeat (no-op if `backend_url` empty) |
| `kvmind-updater.timer` | Optional OTA updates (no-op unless `update_url` configured) |
| `kvmind-tunnel.service` | Optional Cloudflare Tunnel (requires your own CF account) |

All optional cloud services are disabled by default when `backend_url` /
`update_url` are empty in `/etc/kdkvm/config.yaml`. KVMind is fully operational
without them.

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
  # backend_url: ""           # leave empty for fully local operation
  # update_url: ""            # leave empty to disable OTA
```

See `app/config.yaml.example` for all supported options.

## Building from source

```bash
./release/build.sh            # produces release/dist/kdkvm-vX.Y.Z.zip
```

## Development

Tests run against the bridge in isolation:

```bash
cd app && python -m pytest tests/ -v
```

Code style, module boundaries and contribution guidelines are documented in
[CODING_RULES.md](CODING_RULES.md).

## Security

- Bridge binds to `127.0.0.1` by default; all external access goes through
  `kvmd-nginx` with TLS.
- Device password is hashed at rest; no default credentials ship in the release.
- API keys supplied via environment variables are never written back to disk
  (`source: env` skip rule in `save_config`).
- Report issues: https://github.com/sunthinks/kvmind/issues

## License

Apache License 2.0 — see [LICENSE](LICENSE).
