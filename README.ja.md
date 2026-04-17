<p align="right">
  <a href="README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>日本語</b>
</p>

# KVMind — AI 搭載の KVM アシスタント

KVMind は PiKVM デバイスに自然言語 AI アシスタントを追加し、キーボード、
マウス、画面解析を通じてリモートサーバーを操作できるようにします。
すべてモダンな Web コンソールから完結します。

> プロジェクト状態：**beta**。完全にデバイス上で動作し、クラウドアカウントは不要です。

## 主な特徴

- **PiKVM にドロップイン** — `kvmd` と並行してインストール。PiKVM V3/V4
  および PiKVM-OS 互換ボード（BliKVM v4 検証済み、NanoKVM 対応予定）に対応。
- **好きな AI を選べる** — Gemini、Claude、ChatGPT、Ollama、その他 OpenAI
  互換エンドポイントで動作します。
- **エアギャップ環境に優しい** — すべての設定、認証情報、チャット履歴は
  ローカルに保存されます。テレメトリなし、クラウドバックエンド不要。
- **安全なツール実行** — 電源操作やシステムコマンドなどの危険な操作は
  確認機構とアクションレベルポリシーでゲートされます。
- **モダンなコンソール** — H.264 / MJPEG 映像、仮想キーボード、クリップボード、
  フルスクリーン、ダーク/ライトテーマ、zh/ja/en の多言語対応。

## アーキテクチャ

```
┌─────────────────────────────────────────────┐
│ ブラウザ（KVMind コンソール）               │
│ kvmind-core.js · kvmind-stream.js           │
│ kvmind-hid.js  · kvmind-session.js          │
│ myclaw-sidebar.js · kvmind-theme.js         │
└──────────────┬──────────────────────────────┘
               │ wss://<host>/kdkvm/ws/*
┌──────────────▼──────────────────────────────┐
│ kvmd-nginx（TLS 終端）                      │
│ /kvm/*        → KVMind コンソール           │
│ /kdkvm/api/*  → Bridge API                  │
│ /kdkvm/ws/*   → Bridge WebSocket            │
│ /api/*        → kvmd（PiKVM 上流）          │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ KVMind Bridge（Python、127.0.0.1:8765）     │
│ server.py · config.py · auth_manager.py     │
│ kvmind_client.py · model_router.py          │
│ lib/kvm/      — ハードウェア抽象層          │
│ lib/innerclaw — ツール実行器とガードレール  │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│ PiKVM kvmd（HID、メディア、ATX）            │
└─────────────────────────────────────────────┘
```

## クイックインストール

PiKVM デバイス上で：

```bash
# GitHub Releases から最新の zip をダウンロードし、次を実行：
unzip kdkvm-vX.Y.Z.zip && cd kdkvm-vX.Y.Z
sudo ./install.sh
```

サービスが起動したら `https://<デバイス-IP>/kvm/` を開いてください。
`/setup.html` のセットアップウィザードが初期パスワードと AI プロバイダー設定を
案内します。

## 動作要件

- ハードウェア：PiKVM-OS（Arch Linux ARM）を搭載した PiKVM V3 / V4
  または BliKVM v4
- デバイス上で到達可能な `kvmd` サービス（PiKVM 標準構成）
- いずれか一つの AI プロバイダー：
  - [Google AI Studio](https://aistudio.google.com/apikey)（Gemini）
  - [Anthropic](https://console.anthropic.com/settings/keys)（Claude）
  - [OpenAI](https://platform.openai.com/api-keys)（GPT-4o / 4.1 / o シリーズ）
  - [Ollama](https://ollama.com) またはその他の OpenAI 互換エンドポイント

## デバイス上のディレクトリ構成

| パス | 用途 |
|------|------|
| `/opt/kvmind/kdkvm/lib/` | Python バックエンド（bridge） |
| `/opt/kvmind/kdkvm/web/` | フロントエンドアセット |
| `/opt/kvmind/kdkvm/bin/` | ヘルパースクリプト |
| `/etc/kdkvm/` | `config.yaml`、`ai.env`、`device.uid`、プロンプト |
| `/var/lib/kvmd/msd/.kdkvm/` | MSD パーティション上の永続ストア（`memory.db`、`auth.json`） |

## Systemd サービス

| ユニット | 用途 |
|------|------|
| `kvmind.service` | KVMind bridge（Python、ポート 8765） |
| `kvmind-register.timer` | オプションのクラウド登録（`backend_url` が空なら何もしない） |
| `kvmind-heartbeat.timer` | オプションのクラウドハートビート（`backend_url` が空なら何もしない） |
| `kvmind-updater.timer` | オプションの OTA 更新（`update_url` 未設定なら何もしない） |
| `kvmind-tunnel.service` | オプションの Cloudflare Tunnel（各自の CF アカウントが必要） |

`/etc/kdkvm/config.yaml` の `backend_url` / `update_url` が空の場合、
オプションのクラウドサービスはすべてデフォルトで無効化されます。
これらがなくても KVMind は完全に動作します。

## 設定

最小構成の `/etc/kdkvm/config.yaml`：

```yaml
kvm:
  backend: pikvm
  unix_socket: /run/kvmd/kvmd.sock

ai:
  gemini_key: "AIza..."       # もしくは claude_key / openai_key
  timeout: 120

bridge:
  host: 127.0.0.1
  port: 8765
  mode: suggest               # suggest | auto
  # backend_url: ""           # 完全ローカル動作にする場合は空のまま
  # update_url: ""            # OTA を無効にする場合は空のまま
```

すべてのサポートオプションについては `app/config.yaml.example` を参照してください。

## ソースからのビルド

```bash
./release/build.sh            # release/dist/kdkvm-vX.Y.Z.zip を生成
```

## 開発

Bridge のテストは独立して実行できます：

```bash
cd app && python -m pytest tests/ -v
```

コードスタイル、モジュール境界、貢献ガイドラインは
[CODING_RULES.md](CODING_RULES.md) にまとめています。

## セキュリティ

- Bridge はデフォルトで `127.0.0.1` にバインドされます。外部アクセスは
  すべて `kvmd-nginx` を経由し TLS で保護されます。
- デバイスパスワードはハッシュ化されて保存されます。リリースに初期認証情報は含まれません。
- 環境変数で渡された API キーはディスクに書き戻されません
  （`save_config` の `source: env` スキップルール）。
- 問題報告：https://github.com/sunthinks/kvmind/issues

## ライセンス

Apache License 2.0 — 詳細は [LICENSE](LICENSE) を参照してください。
