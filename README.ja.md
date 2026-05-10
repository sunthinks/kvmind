<p align="right">
  <a href="README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>日本語</b>
</p>

# KVMind コミュニティ版

KVMind は PiKVM デバイスに自然言語 AI アシスタントを追加し、キーボード、
マウス、画面解析を通じてリモートサーバーを操作できるようにします。
すべてモダンな Web コンソールから完結します。

> このリポジトリは **KVMind コミュニティ版** です — 完全ローカル、DIY フレンドリー、
> Apache 2.0 ライセンス。マネージド**クラウド版**（自動実行、リモート Tunnel、マルチデバイス管理、
> チーム協作）は [kvmind.com](https://kvmind.com) をご覧ください。
>
> プロジェクト状態：**beta**。完全にデバイス上で動作し、クラウドアカウントは不要です。
> 現在のバージョン：**v0.5.71** (Hanami)。

## 主な特徴

- **PiKVM にドロップイン** — `kvmd` と並行してインストール。PiKVM V3/V4
  および PiKVM-OS 互換ボード（BliKVM v4 検証済み、NanoKVM 対応予定）に対応。
- **好きな AI を選べる** — Gemini、Claude、ChatGPT、DeepSeek、Ollama、
  その他 OpenAI 互換エンドポイント（vLLM、llama.cpp server、LM Studio、
  LiteLLM proxy、Together、Groq、Fireworks、Moonshot、Zhipu など）で動作します。
- **エアギャップ環境に優しい** — すべての設定、認証情報、チャット履歴は
  ローカルに保存されます。テレメトリなし、クラウドバックエンド不要。
- **安全なツール実行** — 電源操作やシステムコマンドなどの危険な操作は
  確認機構とアクションレベルポリシーでゲートされます。
- **モダンなコンソール** — H.264 / MJPEG 映像、仮想キーボード、クリップボード、
  フルスクリーン、ダーク/ライトテーマ、zh/ja/en の多言語対応。

## コミュニティ版 vs クラウド版

両エディションはデバイス側の同じコアを共有しており、違いは実行権限と
フリート管理の所在にあります。

| | コミュニティ版（本リポジトリ） | [クラウド版](https://kvmind.com) |
|---|:---:|:---:|
| 画面解析と提案 | ✅ | ✅ |
| AI Key を自前で用意（Gemini / Claude / OpenAI / Ollama） | ✅ | ✅ |
| 手動ツール実行（確認付き） | ✅ | ✅ |
| ローカルチャット履歴とメモリ | ✅ | ✅ |
| セルフホスト、エアギャップ対応 | ✅ | — |
| Apache 2.0 ライセンスでソースを fork・改変 | ✅ | — |
| **自動実行（手動確認なし）** | — | ✅ |
| **署名・検証付きツール実行（MyClaw Cloud）** | — | ✅ |
| **マネージド Tunnel によるリモートアクセス** | — | ✅ |
| **マルチデバイス・フリートダッシュボード** | — | ✅ |
| **スケジュールタスク** | — | ✅ |
| **チームアクセスとロール権限** | — | ✅ |
| **マネージド OTA アップデート** | — | ✅ |

**コミュニティ版** はいじりたい方・セルフホスト派向け — 自由に改変、完全オフライン
動作、全データを自分のハードウェアに保持。Apache 2.0 ライセンス。

**クラウド版** は本番運用向け — マネージド署名、フリート運用、自動化、チーム
ワークフローを [kvmind.com](https://kvmind.com) で提供。

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

**方法 A — kvmind.com からワンライン インストール（PiKVM デバイス上で実行）：**

```bash
# 最新版をインストール / アップグレード：
curl -sSL https://kvmind.com/install.sh | bash

# 特定バージョンをインストール：
curl -sSL https://kvmind.com/install.sh | bash -s kdkvm-v0.5.71.zip

# 完全リセット（設定・メモリ・認証・クラウド連携を消去）後に最新版をインストール：
curl -sSL https://kvmind.com/install.sh | bash -s reset

# 完全リセット後に特定バージョンをインストール：
curl -sSL https://kvmind.com/install.sh | bash -s reset kdkvm-v0.5.71.zip
```

**方法 B — ソース / Release zip からインストール（コミュニティ版推奨）：**

```bash
# ワークステーションからデバイスへプッシュ（ローカルに sshpass が必要）：
git clone https://github.com/sunthinks/kvmind.git
cd kvmind/kdkvm
./install.sh <デバイス-IP> [デバイスパスワード]   # デフォルトパスワード root

# または GitHub Releases から zip をダウンロードし、scp でデバイスに転送して実行：
unzip kdkvm-v0.5.71.zip && cd kdkvm-v0.5.71
sudo ./install.sh
```

### インストールパラメーター

| パラメーター | 説明 |
|-------------|------|
| *(なし)* | 最新版をインストール / アップグレード |
| `<デバイス-IP> [パスワード]` | リモートモード：ワークステーションからソースをデバイスにプッシュして実行（`sshpass` 必須） |
| `--reset` または `reset` | インストール前に完全リセット：`/etc/kdkvm/` の設定、`/var/lib/kvmd/msd/.kdkvm/` のデータ（メモリ・認証・チャット履歴）を削除し、KVMind クラウドへのデバイス登録を解除します。再デプロイや障害対応時に使用。**破壊的操作：既存のクラウド連携が無効になります。再度 kvmind.com での連携が必要です。** |
| `--keep-root-pw` | OS root パスワード自動更新をスキップ（既に独自に非デフォルトパスワードを設定済みの場合のみ使用） |

サービスが起動したら `https://<デバイス-IP>/kvm/` を開いてください。
`/setup.html` のセットアップウィザードが初期パスワードと AI プロバイダー設定を
案内します。

> **インストーラーについて**：`install.sh` はそのまま使える標準版です ——
> デバイスを [kvmind.com](https://kvmind.com) のフルマネージド体験
> （リモートアクセス、自動実行、フリート管理）向けに設定します。完全ローカル /
> エアギャップインストールをご希望の場合は、初回起動後に
> `/etc/kdkvm/config.yaml` を編集して `bridge.backend_url` を空にするか、
> 本リポジトリを fork し `./release/build.sh` でカスタムインストーラーを
> ビルドしてください。

## 動作要件

- ハードウェア：PiKVM-OS（Arch Linux ARM）を搭載した PiKVM V3 / V4
  または BliKVM v4
- デバイス上で到達可能な `kvmd` サービス（PiKVM 標準構成）
- いずれか一つの AI プロバイダー：
  - [Google AI Studio](https://aistudio.google.com/apikey)（Gemini）
  - [Anthropic](https://console.anthropic.com/settings/keys)（Claude）
  - [OpenAI](https://platform.openai.com/api-keys)（GPT-4o / 4.1 / o シリーズ）
  - [DeepSeek](https://platform.deepseek.com/api_keys)（deepseek-v4-flash / v4-pro）
  - [Ollama](https://ollama.com) または任意の OpenAI 互換エンドポイント（カスタム base_url + API Key）

## デバイス上のディレクトリ構成

| パス | 用途 |
|------|------|
| `/opt/kvmind/kdkvm/lib/` | Python バックエンド（bridge） |
| `/opt/kvmind/kdkvm/web/` | フロントエンドアセット |
| `/opt/kvmind/kdkvm/bin/kvmind-updater.sh` | OTA 更新ヘルパースクリプト（bridge から呼び出し） |
| `/etc/kdkvm/` | `config.yaml`、`ai.env`、`device.uid`、`*.pub` 信頼ルート、プロンプト |
| `/var/lib/kvmd/msd/.kdkvm/` | MSD パーティション上の永続ストア（`state.db`、`memory.db`、`auth.json`、`chat.db`） |

## Systemd サービス

| ユニット | 用途 |
|------|------|
| `kdkvm.service` | KVMind bridge（Python、ポート 8765）—— ハートビート・登録・OTA はプロセス内 asyncio タスクとして実行 |
| `kdkvm-cloudflared.service` | オプションの Cloudflare Tunnel（クラウド版が tunnel token を配信した場合のみ起動。純ローカル利用では不要） |
| `kdkvm-updater.service` / `kdkvm-updater.timer` | OTA 更新（クラウドハートビートが新バージョンを通知した場合のみ起動。ローカルモードではデフォルトで何もしません） |

> 旧来の `kvmind-register.timer` / `kvmind-heartbeat.timer` / `kvmind-tunnel.service`
> 等のユニットは M3.4 / M5 §16 で廃止されました — これらのループはすべて
> bridge プロセス内（`lib/heartbeat.py`、`lib/ota.py`）に統合され、
> shell スクリプトや cron 風の間接層は残っていません。

`/etc/kdkvm/config.yaml` の `bridge.backend_url` が空の場合、ハートビートと
Tunnel はクラウドへの接続を行いません。クラウドに依存せず KVMind は完全に動作します。

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

Apache License 2.0 — 詳細は [LICENSE](LICENSE) を参照してください。サードパーティ依存関係の表示： [NOTICES.md](NOTICES.md) を参照。

---

自動実行、リモートアクセス、マルチデバイス・フリート管理、チーム協作を
お求めですか？マネージド KVMind クラウド版は
[**kvmind.com**](https://kvmind.com) でご利用いただけます。
