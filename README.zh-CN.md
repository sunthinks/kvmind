<p align="right">
  <a href="README.md">English</a> ·
  <b>简体中文</b> ·
  <a href="README.ja.md">日本語</a>
</p>

# KVMind 社区版

KVMind 为你的 PiKVM 设备添加一个自然语言 AI 助手，通过键盘、鼠标与屏幕分析
远程操控服务器——全部在一个现代化 Web 控制台中完成。

> 本仓库是 KVMind 的**社区版** —— 完全本地、适合 DIY、基于 Apache 2.0。
> 如需托管式**云端版**（自动执行、远程 Tunnel、多设备舰队、团队协作），
> 请访问 [kvmind.com](https://kvmind.com)。
>
> 项目状态：**beta**。完全在设备本地运行，无需任何云端账号。

## 亮点

- **PiKVM 即插即用** — 与 `kvmd` 并行安装，支持 PiKVM V3/V4 以及兼容 PiKVM-OS
  的板卡（已测试 BliKVM v4，NanoKVM 计划中）。
- **自带 AI 后端** — 支持 Gemini、Claude、ChatGPT、Ollama，以及任何兼容
  OpenAI 接口的端点。
- **离线友好** — 所有配置、凭据与对话历史均保存在本地，无遥测、无强制云端。
- **安全的工具执行** — 电源、系统命令等危险操作通过确认机制与动作等级策略加以限制。
- **现代化控制台** — H.264 / MJPEG 视频、虚拟键盘、剪贴板、全屏、深浅色主题、
  中日英三语 i18n。

## 社区版 vs 云端版

两个版本共享相同的设备端核心，差异在于执行权限和舰队管理在哪里。

| | 社区版（本仓库） | [云端版](https://kvmind.com) |
|---|:---:|:---:|
| 屏幕分析与建议 | ✅ | ✅ |
| 自带 AI Key（Gemini / Claude / OpenAI / Ollama） | ✅ | ✅ |
| 手动工具执行（需确认） | ✅ | ✅ |
| 本地对话历史与记忆 | ✅ | ✅ |
| 可自托管、离线友好 | ✅ | — |
| Apache 2.0 源码可 fork 与修改 | ✅ | — |
| **自动执行（无需手动确认）** | — | ✅ |
| **签名与验签工具执行（MyClaw Cloud）** | — | ✅ |
| **经托管 Tunnel 远程访问** | — | ✅ |
| **多设备舰队面板** | — | ✅ |
| **计划任务** | — | ✅ |
| **团队成员与权限控制** | — | ✅ |
| **托管 OTA 更新** | — | ✅ |

**社区版**适合 DIY 玩家和自托管用户 —— 随意修改、完全离线运行，每一字节数据都
留在自己硬件上。

**云端版**适合生产环境 —— 托管签名、舰队运维、自动化与团队协作，详见
[kvmind.com](https://kvmind.com)。

## 架构

```
┌─────────────────────────────────────────────┐
│ 浏览器（KVMind 控制台）                     │
│ kvmind-core.js · kvmind-stream.js           │
│ kvmind-hid.js  · kvmind-session.js          │
│ myclaw-sidebar.js · kvmind-theme.js         │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx（TLS 终端）                      │
│ /kvm/*        → KVMind 控制台               │
│ /kdkvm/api/*  → Bridge API                  │
│ /kdkvm/ws/*   → Bridge WebSocket            │
│ /api/*        → kvmd（PiKVM 上游）          │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ KVMind Bridge（Python，127.0.0.1:8765）     │
│ server.py · config.py · auth_manager.py     │
│ kvmind_client.py · model_router.py          │
│ lib/kvm/      — 硬件抽象层                  │
│ lib/innerclaw — 工具执行器与安全护栏        │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ PiKVM kvmd（HID、媒体、ATX）                │
└─────────────────────────────────────────────┘
```

## 快速安装

在 PiKVM 设备上：

```bash
# 从 GitHub Releases 下载最新 zip 包，然后：
unzip kdkvm-vX.Y.Z.zip && cd kdkvm-vX.Y.Z
sudo ./install.sh
```

服务启动后打开 `https://<设备-IP>/kvm/`——`/setup.html` 的设置向导会引导你
完成初始密码和 AI 提供商配置。

> **关于安装脚本**：`install.sh` 是默认开箱即用的版本 —— 会把设备配置为
> [kvmind.com](https://kvmind.com) 的完整托管模式（远程访问、自动执行、
> 舰队管理）。如需完全本地 / 离线安装，请在首次启动后编辑
> `/etc/kdkvm/config.yaml`，将 `bridge.backend_url` 置空；或 fork 本仓库，
> 用 `./release/build.sh` 构建自定义安装包。

## 系统要求

- 硬件：PiKVM V3 / V4 或运行 PiKVM-OS（Arch Linux ARM）的 BliKVM v4
- 设备上可访问的 `kvmd` 服务（默认 PiKVM 布局）
- 任一 AI 提供商：
  - [Google AI Studio](https://aistudio.google.com/apikey)（Gemini）
  - [Anthropic](https://console.anthropic.com/settings/keys)（Claude）
  - [OpenAI](https://platform.openai.com/api-keys)（GPT-4o / 4.1 / o 系列）
  - [Ollama](https://ollama.com) 或任何其他兼容 OpenAI 的端点

## 设备上的目录布局

| 路径 | 用途 |
|------|------|
| `/opt/kvmind/kdkvm/lib/` | Python 后端（bridge） |
| `/opt/kvmind/kdkvm/web/` | 前端资源 |
| `/opt/kvmind/kdkvm/bin/` | 辅助脚本 |
| `/etc/kdkvm/` | `config.yaml`、`ai.env`、`device.uid`、提示词 |
| `/var/lib/kvmd/msd/.kdkvm/` | MSD 分区上的持久化存储（`memory.db`、`auth.json`） |

## Systemd 服务

| 单元 | 用途 |
|------|------|
| `kvmind.service` | KVMind bridge（Python，端口 8765） |
| `kvmind-register.timer` | 可选云端注册（`backend_url` 为空时不执行任何操作） |
| `kvmind-heartbeat.timer` | 可选云端心跳（`backend_url` 为空时不执行任何操作） |
| `kvmind-updater.timer` | 可选 OTA 更新（未配置 `update_url` 时不执行任何操作） |
| `kvmind-tunnel.service` | 可选 Cloudflare Tunnel（需要你自己的 CF 账号） |

当 `/etc/kdkvm/config.yaml` 中的 `backend_url` / `update_url` 为空时，所有
可选云端服务默认均处于禁用状态。不依赖这些服务 KVMind 也能完整运行。

## 配置

一个最小化的 `/etc/kdkvm/config.yaml`：

```yaml
kvm:
  backend: pikvm
  unix_socket: /run/kvmd/kvmd.sock

ai:
  gemini_key: "AIza..."       # 或 claude_key / openai_key
  timeout: 120

bridge:
  host: 127.0.0.1
  port: 8765
  mode: suggest               # suggest | auto
  # backend_url: ""           # 留空以完全本地化运行
  # update_url: ""            # 留空以禁用 OTA
```

完整选项请参阅 `app/config.yaml.example`。

## 从源码构建

```bash
./release/build.sh            # 生成 release/dist/kdkvm-vX.Y.Z.zip
```

## 开发

Bridge 的单元测试可独立运行：

```bash
cd app && python -m pytest tests/ -v
```

代码风格、模块边界和贡献规范详见
[CODING_RULES.md](CODING_RULES.md)。

## 安全

- Bridge 默认绑定到 `127.0.0.1`；所有外部访问均通过 `kvmd-nginx` 以 TLS 方式进行。
- 设备密码以哈希形式落盘；发布包不含任何默认凭据。
- 通过环境变量提供的 API Key 不会被写回磁盘（`save_config` 中的
  `source: env` 跳过规则）。
- 报告问题：https://github.com/sunthinks/kvmind/issues

## 许可证

Apache License 2.0——详见 [LICENSE](LICENSE)。

---

需要自动执行、远程访问、多设备舰队管理和团队协作？
托管式 KVMind 云端版可在 [**kvmind.com**](https://kvmind.com) 获取。
