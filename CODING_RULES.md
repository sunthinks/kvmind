# KVMind — 编码规范与架构规则

> **所有开发者和 AI 代理在修改 KVMind 代码前必须阅读并遵守本文档。**
> **违反这些规则的代码不得合入主分支。**

版本：6.3 ｜ 更新日期：2026-04-21
基准：kdkvm — 运行版本以 [app/web/version.json](app/web/version.json) 为唯一真源 · InnerClaw v3 (AI Kernel) · kvmd 4.165 · Linux 6.12.56-8-rpi (aarch64)

---

## 一、项目概览

### 1.1 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 基础层 | KVM 硬件抽象层（支持 PiKVM/BliKVM/NanoKVM） | ArchLinux aarch64，通过 KVMBackend 接口与硬件交互 |
| 后端 | Python 3 + aiohttp | KVMind Bridge，端口 8765 |
| AI 引擎 | InnerClaw v3 (Python) | 模型无关、协议驱动、两层 fallback、自恢复、native tool_use、文件驱动 Prompt |
| 前端 | Vanilla JS + CSS | 全新独立页面，不依赖 KVM 硬件原生 JS 模块，无框架依赖 |
| 入口 | kvmd-nginx (443) | TLS 终止、路由分发 |
| 持久化 | SQLite + auth.json | 均位于 MSD 分区（`/var/lib/kvmd/msd/.kdkvm/`） |

### 1.2 文件结构

```
dev/kdkvm/
├── app/
│   ├── lib/                       # Python 后端模块
│   │   ├── server.py              # Bridge 主入口（薄编排层：初始化依赖 → app dict → register_all）
│   │   ├── middleware.py           # 会话管理、auth_middleware、WSHub、可信代理
│   │   ├── config.py              # 配置加载（KNOWN_PROVIDERS、SubscriptionConfig）
│   │   ├── auth_manager.py        # 设备认证（密码哈希、登录锁定）
│   │   ├── kvm/                   # KVM 硬件抽象层（KVMBackend ABC + 适配器）
│   │   ├── kvmind_client.py       # AI 调用入口（按阶段超时 + 记忆注入）
│   │   ├── model_router.py        # 顺序 fallback + 语义校验 + 最终兜底
│   │   ├── ai_provider.py         # OpenAI/Anthropic API 适配（带 default_model）
│   │   ├── ai_intents.py          # Intent 定义 + fallback prompt（云端 prompt 由 MyClaw gateway 下发）
│   │   ├── memory_store.py        # SQLite 长期记忆存储
│   │   ├── chat_store.py          # SQLite 聊天记录持久化
│   │   ├── audit_log.py           # 操作审计日志
│   │   ├── remount.py             # rw/ro 文件系统 remount 工具（统一入口）
│   │   ├── uid.py                 # 设备 UID 管理
│   │   ├── wifi_manager.py        # WiFi 管理
│   │   ├── telegram_bot.py        # Telegram Bot 集成
│   │   ├── handlers/              # HTTP/WS 路由处理模块（register(app) 模式）
│   │   │   ├── __init__.py        # register_all(app)：注册所有路由
│   │   │   ├── helpers.py         # 共享工具（json_response）
│   │   │   ├── pages.py           # 页面路由（index、login 等）
│   │   │   ├── auth.py            # 认证路由（login/logout/check/change-password）
│   │   │   ├── device.py          # 设备路由（status/analyse/HID/power）
│   │   │   ├── wifi.py            # WiFi 路由（scan/status/connect/disconnect）
│   │   │   ├── dashboard.py       # 仪表盘路由（stats）
│   │   │   ├── update.py          # OTA 更新路由（status/check/apply）
│   │   │   ├── subscription.py    # 订阅路由（GET + sync POST）
│   │   │   ├── ai_config.py       # AI 配置路由（config/models/test）+ build_providers
│   │   │   ├── memory.py          # AI 记忆路由（GET）
│   │   │   └── websocket.py       # WebSocket 路由（ws/chat + ws/agent）
│   │   └── innerclaw/             # InnerClaw v3 AI 执行引擎
│   │       ├── runner.py          # Runner v3: 协议驱动 agentic 执行引擎（核心）
│   │       ├── tools.py           # INNERCLAW_TOOLS 定义 + Action/ActionResult 强类型
│   │       ├── policy.py          # ExecutionPolicy：去重、防循环、stale 检测
│   │       ├── memory.py          # HistoryManager：history 压缩防 token 爆炸
│   │       ├── budget.py          # 预算对象（只增不减的资源计数器）
│   │       ├── loop_detector.py   # 环路检测（screenshot+action hash）
│   │       ├── executor.py        # HID 动作执行（通过 KVMBackend 分发到 KVM 设备）
│   │       ├── guardrails.py      # 安全护栏（白名单、速率、重复、确认）
│   │       ├── validator.py       # 动作参数校验（Pydantic schema）
│   │       └── adapters/          # 通道适配器（Web/Telegram/WeChat/LINE）
│   ├── web/                       # 前端文件
│   │   ├── index.html             # 主页面（KVMind 独立前端，不依赖 KVM 硬件原生 JS）
│   │   ├── login.html             # 登录页
│   │   ├── setup.html             # 初始化向导（含三选项 AI 配置）
│   │   ├── change-password.html   # 密码修改页
│   │   ├── dashboard.html         # 设备仪表盘页
│   │   ├── kvmind.css             # 所有样式 + 布局 + 响应式 + 4 套主题变量
│   │   ├── kvmind-core.js         # 核心逻辑（i18n、工具栏、API、WS、聊天、截图）
│   │   ├── kvmind-stream.js       # 三模式视频流（WebRTC/H.264/MJPEG）
│   │   ├── kvmind-hid.js          # 键鼠输入处理
│   │   ├── kvmind-session.js      # KVM 硬件 WebSocket 会话
│   │   ├── myclaw-sidebar.js      # Sidebar 视图切换（Chat/Tasks/Settings）
│   │   ├── myclaw-gateway.js      # MyClaw Gateway WebSocket 客户端
│   │   ├── kvmind-theme.js        # 主题切换
│   │   ├── version.json           # 版本号（语义化版本 + 构建日期 + 代号）
│   │   └── static/                # 静态资源
│   └── bin/                       # 设备端脚本
├── nginx/                         # kvmd-nginx 配置片段
├── systemd/                       # systemd 服务文件
├── install.sh                     # 一键部署脚本
└── CODING_RULES.md                # 本文档
```

### 1.3 MSD 持久化分区

KVM 设备根分区默认只读，所有可写数据统一存放在 MSD 分区（**隐藏目录**，避免 kvmd MSD scanner 干扰）：

```
/var/lib/kvmd/msd/.kdkvm/
├── memory.db    ← SQLite（长期记忆 + 聊天记录）
└── auth.json    ← 设备认证状态（密码哈希、登录锁定）
```

- systemd `ExecStartPre` remount rw、`ExecStopPost` remount ro
- `install.sh` 中涉及 MSD 写入的步骤前后必须 remount rw/ro
- **禁止**在根分区（`/opt/kvmind/`）下写入运行时数据

### 1.4 Remount 工具模块

Python 代码中所有 rw/ro 操作统一使用 `lib/remount.py` 提供的上下文管理器：

```python
from .remount import remount_rw, msd_rw, async_remount_rw

# 写入根分区（/etc/kdkvm/）— 同步
with remount_rw("/etc/kdkvm/config.yaml"):
    Path(path).write_text(data)

# 写入 MSD 分区（/var/lib/kvmd/msd/.kdkvm/）— 同步
with msd_rw("/var/lib/kvmd/msd/.kdkvm/memory.db"):
    conn.execute(...)

# 异步代码中使用异步版本
async with async_remount_rw("/etc/kdkvm/wpa_supplicant.conf"):
    await write_config(...)
```

**并发安全**：`remount_rw` / `async_remount_rw` 内部使用引用计数，嵌套调用同一挂载点时仅最外层执行 mount 命令，避免并发写入时过早恢复 ro。`msd_rw` 委托给 `remount_rw`，共享计数。

**规则：**
- 禁止在 `remount.py` 之外直接调用 `/bin/mount -o remount`
- Shell 脚本中写入只读分区前后必须加 `mount -o remount,rw/ro`，并使用 `trap` 确保异常退出时恢复 ro

### 1.5 前端加载顺序

`index.html` 按以下顺序加载 KVMind 前端：

```
1. kvmind.css              (样式 + 主题变量 + 响应式)
2. Google Fonts             (Inter + JetBrains Mono)
3. kvmind-session.js        (KVM 硬件 kvmd WebSocket 会话管理)
4. janus.js                 (Janus WebRTC 客户端库)
5. kvmind-stream.js         (三模式视频流：WebRTC/H.264/MJPEG)
6. kvmind-hid.js            (键盘/鼠标 HID 输入)
7. myclaw-gateway.js        (MyClaw WebSocket 客户端)
8. kvmind-core.js           (主逻辑：i18n、工具栏、API、聊天)
9. myclaw-sidebar.js        (Sidebar 视图切换)
10. kvmind-theme.js          (主题系统)
```

---

## 二、前端架构方针

### 核心原则：完全独立的前端，通过 KVM 抽象层 API 交互

KVMind 的 `index.html` 是**全新独立页面**，不加载任何 KVM 硬件原生 JS 模块。画面布局、工具栏、MyClaw 面板、视频流、HID 输入等全部是 KVMind 自有实现。

| KVMind 模块 | 职责 | 与 KVM 硬件的关系 |
|-------------|------|----------------|
| `kvmind-session.js` | kvmd WebSocket 会话 | 直接连接 KVM 硬件的 WebSocket API |
| `kvmind-stream.js` | 三模式视频流 | WebRTC (Janus) / H.264 (kvmd ws) / MJPEG (kvmd http) |
| `kvmind-hid.js` | 键盘/鼠标输入 | 通过 kvmd WebSocket 发送 HID 事件 |
| `kvmind-core.js` | 主逻辑 | 通过 KVMind Bridge REST API 控制 ATX 电源等 |

**开发守则：**
- 所有 KVMind UI 使用 KVMind 命名空间（`#kvmind-*`、`.kvmind-*`）
- 与 KVM 硬件的交互仅通过 kvmd 的 WebSocket/REST API，不依赖硬件原生前端代码
- 视频流、HID、ATX 控制均为 KVMind 自有实现

### KVM 硬件升级适配方针

> **KVMind 前端不依赖 KVM 硬件原生 JS，仅依赖 kvmd API。硬件固件升级时只需确认 kvmd API 兼容性。**

**禁止事项：**
- 禁止因为 KVM 硬件升级而重新设计 KVMind 的 UI
- 禁止引入 KVM 硬件原生前端 JS 模块作为依赖

---

## 三、前端编码规则

### 3.1 错误信息处理（安全规则）

**禁止将内部技术错误直接展示给用户。** 所有 catch 块和 API 错误响应必须：

1. 使用 `console.error()` 记录技术细节（供 F12 调试）
2. 向用户显示通用友好提示（通过 i18n key）

```js
// ✗ 禁止：暴露内部错误
catch (e) {
  showMsg('status', 'error', e.message);
}

// ✗ 禁止：暴露服务端错误
if (d.error) {
  showMsg('status', 'error', d.error);
}

// ✓ 正确：友好提示 + console 调试
catch (e) {
  console.error('操作描述:', e);
  showMsg('status', 'error', t('i18n_key_for_friendly_msg'));
}

// ✓ 正确：服务端错误也用友好提示
if (d.error) {
  console.error('操作描述:', d.error);
  showMsg('status', 'error', t('i18n_key_for_friendly_msg'));
}
```

**适用范围：** 所有 `.html` 和 `.js` 文件中面向用户的错误显示（`showMsg`、`showErr`、`kvmindAppendMsg`、`textContent`、`innerHTML` 等）。

### 3.2 CSS 布局：唯一真相源

所有布局尺寸必须通过 CSS 自定义属性定义。

**规则：**
- 新代码必须使用 `var(--kv-*)` 引用布局值，禁止硬编码数字
- JS 读取布局值用 `getComputedStyle(document.documentElement).getPropertyValue('--kv-panel-w')`
- JS 修改布局值用 `document.documentElement.style.setProperty('--kv-panel-w', newValue)`

### 3.3 禁止 `!important` 覆盖布局

布局相关属性上的 `!important` 会破坏响应式系统。

**唯一例外：**
- 确有必要的布局覆盖（需注释说明原因）

### 3.4 主题系统

KVMind 支持 4 套主题，通过 `data-theme` 属性切换：

| 主题 | CSS 选择器 | 说明 |
|------|-----------|------|
| Light | `:root, [data-theme="light"]` | 默认浅色 |
| Dark | `[data-theme="dark"]` | 深色（GitHub 风格） |
| KVMind Light | `[data-theme="kvmind-light"]` | 品牌浅色（绿色强调） |
| KVMind Dark | `[data-theme="kvmind-dark"]` | 品牌深色（绿色强调） |

**规则：**
- 所有颜色必须通过 CSS 变量（`--kv*` 前缀）引用，禁止硬编码颜色值
- 新增主题变量时，必须同时在 4 套主题中定义对应值

### 3.5 文件职责分离

| 文件 | 职责 | 可以做 | 不可以做 |
|------|------|--------|---------|
| `index.html` | 页面结构 + KVMind 模块加载 + 工具栏 DOM | HTML 结构、script/link 标签 | 内联 JS 逻辑（超过 5 行） |
| `kvmind.css` | 所有样式 + 布局 + 响应式 + 主题变量 | 定义变量、样式、@media | 包含 JS 逻辑 |
| `kvmind-core.js` | 主逻辑：i18n、工具栏、API、WS、聊天、截图、键盘覆盖 | 事件处理、DOM 操作、API 调用 | 定义布局尺寸、注入布局 CSS |
| `myclaw-sidebar.js` | Sidebar 视图切换（Chat/Tasks/Settings） | 管理视图切换、sidebar 内部样式 | 定义面板宽度 |
| `myclaw-gateway.js` | MyClaw Gateway WebSocket 通信 | 连接管理、消息收发、会话管理 | 任何 DOM/CSS 操作 |
| `setup.html` | 初始化向导（自包含 CSS/JS/i18n） | 页面逻辑、API 调用 | 引用外部 JS 文件 |

### 3.6 i18n 国际化

KVMind 支持三语：中文（zh）、日本語（ja）、English（en）。

**规则：**
- 所有用户可见文本必须通过 i18n 字典定义，禁止硬编码
- `index.html` 系通过 `KVMIND_I18N` 字典 + `kvmindTranslatePiKVM()`
- `setup.html` 系通过内置 `I18N` 对象 + `t()` 函数 + `data-i18n` 属性
- 新增 i18n key 时，必须同时在 zh/ja/en 三个语言中添加
- 语言偏好存储在 `localStorage.kvmind_lang`

### 3.7 KVM 硬件兼容性

- **kvmd-nginx 路由**：KVMind 的页面通过 kvmd-nginx 的自定义 location 提供服务
- **kvmd API 依赖**：KVMind 通过 kvmd 的 WebSocket/REST API 获取视频流、发送 HID 事件、控制 ATX 电源
- **无硬件原生 JS 依赖**：KVMind 前端不加载任何 KVM 硬件原生的 JS/CSS 文件

---

## 四、后端规则

### 4.1 架构约束

- Bridge 采用 hardware-agnostic 设计，**严禁修改 kvmd 代码或配置**
- `server.py` 是薄编排层：初始化依赖 → 存入 `app` dict → `register_all(app)` 注册路由
- 路由处理拆分到 `handlers/` 子模块，每个模块导出 `register(app)` 函数，handler 作为闭包从 `app` dict 获取依赖
- 可变状态（providers/router/kvmind）存入 `app` dict，WebSocket handler 在请求时读取（非注册时），确保 ai_config_save 重建后生效
- 所有 KVM 硬件功能必须通过 `kvm/` 模块的 KVMBackend 接口访问，禁止在 `kvm/` 模块外直接调用 kvmd API
- AI 功能通过 InnerClaw v3 引擎（模型无关、协议驱动、两层 fallback + 自恢复）

### 4.2 Python 编码规范

- Python 3.9+ 语法，使用 `from __future__ import annotations`
- 异步优先：所有 I/O 操作使用 `async/await`（aiohttp）
- 配置通过 `config.yaml` + 环境变量加载，禁止硬编码密钥或端口
- 日志统一使用 `logging` 模块，格式 `[模块名] 消息`

### 4.3 AI Provider 配置（KNOWN_PROVIDERS）

**AI 模型目录原则**（0.2.27-beta 起）：

> **设备端不维护模型产品目录**。新模型 / 新 provider 不发 kdkvm 版本。
> `KNOWN_PROVIDERS` 只描述 provider 的 API 形状（base_url、鉴权、列模型端点），
> 实际模型名**运行时**向 provider 的 `GET /models` 类端点拉取作为 UI 建议。
> 用户也可以随时在 UI 里选 "其他…" 手动填任意模型名。
> 模型名的唯一校验者是 provider API 本身（它说 "model not found" 才是真报错）。

`config.py` 中维护已知 Provider 的中心注册表：

```python
KNOWN_PROVIDERS = {
    "ollama": {
        "base_url": "",  # 用户自填，Ollama 在 LAN 上
        "key_envs": ["OLLAMA_API_KEY"],
        "config_key": "ollama_key",
        "display_name": "Ollama",
        "requires_key": False,
        "models_endpoint": "/api/tags",            # 相对 base_url
        "models_endpoint_strip_suffix": "/v1",     # Ollama /api/tags 在根路径
        "models_id_path": "models[].name",
        "console_url": "https://ollama.com/library",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_envs": ["OPENAI_API_KEY"],
        "config_key": "openai_key",
        "display_name": "OpenAI",
        "requires_key": True,
        "models_endpoint": "/models",
        "models_id_path": "data[].id",
        "models_id_filter": r"^(gpt-|o1-|o3-|o4-|chatgpt-)",
        "console_url": "https://platform.openai.com/api-keys",
    },
    # anthropic, gemini ...
}
```

**规则：**
- **禁止**在 `KNOWN_PROVIDERS` 里写 `models` 或 `default_model` 字段
- 新 provider 只描述 API 形状（list-models 端点 + JSON 路径），不列任何型号
- 模型列表通过 `POST /api/ai/models` 运行时向 provider 实际查询（3s 超时）
- 查不到（无网 / 无 key / 端点失败）→ 前端切纯自由文本输入，显示 `console_url` 外链
- `_build_providers` 跳过没有 `default_model` 的 provider 并 `log.warning`，不构造"空模型"的 provider
- `OpenAIProvider` / `AnthropicProvider` 构造函数 `default_model` 必填，空值直接 `raise ValueError`
- API Key 优先级：环境变量 > config.yaml shorthand > config.yaml providers list > legacy
- Ollama / no-key Provider 必须通过 `*_enabled` 或自定义 URL 显式启用；自动模式还必须通过原生 tool_calls 能力测试

### 4.4 订阅配置（SubscriptionConfig · V1 Seat 模型）

`config.py` 中的 `SubscriptionConfig` dataclass 管理权益状态，由心跳（`/api/subscription/sync`）同步写入：

| 字段 | 类型 | 说明 |
|------|------|------|
| `claim_state` | str | `unclaimed` / `claimed`，设备是否已 claim 到账号 |
| `entitlement_state` | str | `local_free` / `claimed_free` / `paid`，权益态 |
| `assigned_subscription_id` | int? | 当前占用的订阅 id（paid 态必填，其他态 None） |
| `tunnel` / `messaging` / `ota` | bool | Feature flags（由云端心跳派生下发，本地被动消费） |
| `myclaw_limit` / `myclaw_daily_limit` | int | MyClaw 小时 / 日限额，`-1` 无限制 |
| `myclaw_max_action_level` | int | 最高 action level 1/2/3 |
| `scheduled_tasks` | bool | MyClaw 定时任务开关（Pro 独有） |
| `synced_at` | str | 上次心跳同步 ISO 时间 |

**派生规则**（云端 EntitlementService.resolveForDevice 决定）：

- `device.claim_state = unclaimed` ⇒ `local_free`，基础 KVM 本地自治
- `claimed` 但无活跃 seat ⇒ `claimed_free`，基础功能 + 显示"未分配 seat"
- 占用活跃订阅 seat ⇒ `paid`，按 subscription.plan_type（standard / pro）展开 feature flags

**0.4.0 去 Trial 化**：老 `plan` / `linked` 字段彻底删除；不保留向后兼容层（发售前无付费客户，无已部署设备）。

### 4.5 持久化路径规则

| 数据类型 | 路径 | 说明 |
|---------|------|------|
| SQLite DB | `/var/lib/kvmd/msd/.kdkvm/memory.db` | 长期记忆 + 聊天记录 |
| 认证状态 | `/var/lib/kvmd/msd/.kdkvm/auth.json` | 密码哈希、锁定状态 |
| 配置文件 | `/etc/kdkvm/config.yaml` | 只读分区，install 时写入 |
| AI 环境变量 | `/etc/kdkvm/ai.env` | 只读分区，install 时写入 |
| Prompt 文件 | `/etc/kdkvm/prompts/*.md` | 只读分区，热更新需 SSH rw |

**规则：**
- 运行时可写数据**只能**放在 MSD 分区（`/var/lib/kvmd/msd/.kdkvm/`）
- 旧路径迁移：代码中检测旧路径存在时自动复制到新路径（如 auth_manager.py 的 `_LEGACY_AUTH`）
- Python 代码中 remount 操作必须使用 `lib/remount.py` 中的 `remount_rw()` 或 `msd_rw()`
- Shell 脚本中涉及 MSD 写入前后必须 `mount -o remount,rw/ro`

### 4.6 API 路由

所有 KVMind API 挂载在 `/kdkvm` 前缀下（由 kvmd-nginx 路由），Bridge 内部路径以 `/api` 开头：

```
/kdkvm/api/auth/*         → 认证（login、logout、check、change-password）
/kdkvm/api/device/uid     → 设备 UID
/kdkvm/api/setup/complete → 初始化完成（改密码 + 激活设备）
/kdkvm/api/status         → 状态
/kdkvm/api/analyse        → AI 分析
/kdkvm/api/hid/*          → 键鼠代理（mouse/move、mouse/click、keyboard/type、keyboard/key）
/kdkvm/api/atx/power      → 电源控制
/kdkvm/api/subscription   → 订阅状态（GET）
/kdkvm/api/subscription/sync → Nginx 对外统一 403；本地 subscription_sync.py 走 http://127.0.0.1:8765/api/subscription/sync 直连 bridge
/kdkvm/api/ai/config      → AI 配置读写（GET/POST）
/kdkvm/api/ai/models      → 运行时向 provider 拉模型列表（POST，带 api_key/base_url）
/kdkvm/api/ai/test        → AI 连接测试（POST）
/kdkvm/api/ai/memory      → AI 长期记忆（GET）
/kdkvm/api/wifi/*         → WiFi 管理（scan、status、connect、disconnect）
/kdkvm/api/vpn/status     → VPN 状态
/kdkvm/api/audit/recent   → 审计日志
/kdkvm/api/dashboard/stats → 设备仪表盘统计（GET）
/kdkvm/api/update/status  → OTA 更新状态（GET）
/kdkvm/api/update/check   → OTA 更新检查（POST）
/kdkvm/api/update/apply   → OTA 更新执行（POST）
/kdkvm/ws/chat            → MyClaw 聊天 WebSocket
/kdkvm/ws/agent           → AI 事件流 WebSocket
```

### 4.7 server.py 错误响应规则

- API 返回 4xx/5xx 时，`error` 字段使用通用描述（如 `"unauthorized"`、`"invalid request"`）
- **禁止**在 JSON 响应中包含 Python traceback、内部异常信息、文件路径
- 技术细节通过 `log.error()` / `log.warning()` 记录到 journalctl

---

## 五、通用规则

### 5.1 命名约定

| 范围 | 前缀/规则 | 示例 |
|------|----------|------|
| CSS 布局变量 | `--kv-` | `--kv-panel-w`, `--kv-toolbar-h` |
| CSS 颜色/主题变量 | `--kv` | `--kvaccent`, `--kvbg`, `--kvsurface` |
| JS 全局函数 | `kvmind` | `kvmindGetLang()`, `kvmindApplyLang()` |
| DOM 元素 ID | `kvmind-` | `#kvmind-toolbar`, `#kvmind-chat-panel` |
| DOM 元素 class | `kvmind-` | `.kvmind-tb-btn`, `.kvmind-msg-row` |
| setup.html 内部 | `plan-*`, `custom-*` | `#plan-detail-custom`, `#custom-provider-select` |

### 5.2 禁止"打补丁"式修复

- 不允许新增 `*-patch.js`、`*-fix.js` 文件来修复已有文件的 bug
- 修复必须在原始文件中进行
- 如果原始文件架构有问题，应重构原始文件

### 5.3 及时删除废弃文件

- 功能被合并或替代后，原文件必须删除
- 设备上的部署文件也必须通过 `install.sh` 同步清理
- `index.html` 中对已删除文件的 `<script>` / `<link>` 引用必须清除

### 5.4 Cache Bust

- 所有 JS/CSS 的 `<script>` / `<link>` 标签必须使用版本参数 `?v={timestamp}`
- 修改任何 JS/CSS 文件后，必须同时更新版本号
- 当前使用 epoch 秒作为版本号（如 `kvmind.css?v=1774226084`）

### 5.5 版本管理

`version.json` 记录当前版本信息（格式示例，实际值以仓库中 [app/web/version.json](app/web/version.json) 为准）：

```json
{
  "version": "0.2.x-beta",
  "build": "YYYYMMDD",
  "codename": "<代号>"
}
```

- `version`：语义化版本号 (semver)
- `build`：构建日期 YYYYMMDD
- `codename`：版本代号
- 每次功能发布必须更新此文件

### 5.6 部署

- 一键部署使用 `install.sh`，支持远程和本地两种模式
- 部署目标路径：`/opt/kvmind/kdkvm/`（代码）、`/etc/kdkvm/`（配置）
- **所有配置路径统一为 `/etc/kdkvm/`**，禁止使用已废弃的 `/etc/kvmind/`
- 持久化数据路径：`/var/lib/kvmd/msd/.kdkvm/`（MSD 分区，隐藏目录，运行时可写）
- KVM 设备根文件系统默认只读，`install.sh` 内部处理 rw/ro 切换
- **首次安装末尾强制轮换 OS root 密码**（step 9）：PiKVM/BliKVM 出厂镜像 root:root 任何局域网都能登录，install.sh 在最后一步生成 24 位随机密码、`chpasswd`、写标记 `/etc/kdkvm/.root-rotated` 防重复；新密码只在 summary 里打印一次，丢失需重刷卡。跳过：`install.sh --keep-root-pw`（仅当运维已外部管理 root 时使用）
- systemd 服务：`kdkvm.service`（Python bridge，端口 8765）、`kdkvm-cloudflared.service`（隧道），仅此两个。心跳 / 注册 / OTA / 订阅同步全部迁为 bridge 进程内的 asyncio 任务（M3.4，`lib/heartbeat.py` / `lib/subscription_sync.py` / `lib/ota.py`），历史上的 `kvmind-heartbeat.timer` / `kvmind-register.timer` / `kvmind-updater.timer` 已随 M5 §16 一起删除
- 心跳上行 `POST /api/devices/heartbeat` → kdcms；心跳响应里的 features 由本地 `subscription_sync.py` 通过 `POST http://127.0.0.1:8765/api/subscription/sync`（trusted-proxy 限制）同步 tunnel/messaging/ota、MyClaw 限额、action level、scheduled_tasks，不直接改文件、不重启服务

### 5.7 订阅-设备业务规则（V1 Seat 模型 · 0.4.0）

**设备状态双维度**：
- `claim_state ∈ {unclaimed, claimed}`：设备是否已绑账号
- `entitlement_state ∈ {local_free, claimed_free, paid}`（外加 Phase 2 预留 `grace_period` / `suspended`）：权益态

**Claim 流程**（取代老 `bindBySubscriptionKey`）：
1. 设备 `POST /api/devices/claim/initiate`（包装 RFC 8628 Device Authorization Grant）→ 返回 `claim_code` + `registration_token`
2. 用户在 `kvmind.com/activate` 输入 `claim_code` 完成绑定
3. 设备 `claim_state = claimed`，立即触发 `SeatAssignmentService.tryAutoAssign`
4. 若账号有空 seat → `entitlement_state = paid` + `assigned_subscription_id`；否则 `claimed_free`

**自动 seat 分配优先级**：空闲 Standard → 已部分占用 Pro → 全新 Pro → `claimed_free`。
**手动 seat 指派**：`manual_assignment_preference` 记录偏好，跨订阅周期自动恢复。

**Seat 释放时机**：
1. 订阅到期（`SubscriptionExpiryScheduler` 每天 03:00 → `releaseAllForSubscription`）
2. Stripe 退款（`handleChargeRefunded`）/ 订阅取消确认（`handleSubscriptionDeleted`）
3. 用户 Web 端主动释放（`POST /api/customer/seats/{seatId}/release`）
4. 设备主动解绑（`POST /api/customer/seats/device/{uid}/unlink`）

**隧道开通 / 回收**：
- `entitlement_state = paid` 的首次心跳 → `TunnelProvisioningService.provisionIfNeeded`
- 释放 seat 后若该设备最终 `!= paid` → `cloudflareService.deleteTunnel` + `deviceMapper.clearTunnel`
- 其他订阅 seat 上的设备 tunnel 不受影响（按本订阅所占 seat 粒度，而非 customer 全局）

**MyBatis NULL 写入规则**：`deviceMapper.update()` 无法设字段为 NULL。
专用方法：`clearCustomerId(uid)` / `clearTunnel(uid)` / `clearAssignedSubscription(uid)` / `unclaim(uid)`。

**Cloudflare 隧道幂等性**：`CloudflareService.provisionDevice()` 处理隧道和 DNS 已存在（409 冲突→复用）。

**订阅状态流转**（与 seat 语义正交）：
```
pending → active → cancelling / paused → expired
         ↘ active → expired（直接过期）
```
Stripe webhook / SubscriptionExpiryScheduler 驱动；seat 释放永远随订阅"离开 active/cancelling/paused"而发生。

---

## 六、响应式设计规则

### 6.1 断点定义

| 名称 | 范围 | 策略 |
|------|------|------|
| XL | ≥1280px | 默认值：面板 360px，Sidebar + Chat 并排 |
| LG | 1024–1279px | 面板缩窄为 300px |
| MD | 768–1023px | 面板变为 Drawer 覆盖层 |
| SM | ≤767px | 汉堡菜单 + 全屏面板 |

### 6.2 响应式样式只在 `kvmind.css` 中编写

不允许在 JS 中根据 `window.innerWidth` 动态修改样式。所有断点适配通过 CSS `@media` 查询实现。

**唯一例外：** JS 可以监听 `resize` 事件来切换 CSS class（如 `drawer-open`），但不能直接设置 `element.style.width`。

---

## 七、安全规则

### 7.1 KVM 硬件隔离

- KVMind 通过 KVMBackend 抽象接口与硬件交互，**绝不修改 kvmd 源代码**
- 不修改 `/usr/lib/python3.*/site-packages/kvmd/` 下的任何文件
- 不修改 kvmd 的 htpasswd 或 TOML 配置（除安装初始化脚本外）
- **所有硬件交互必须通过 KVMBackend 接口**：禁止在 `kvm/` 模块外直接调用 kvmd REST/WS API

### 7.2 敏感信息

- API Key 通过环境变量或 `/etc/kdkvm/ai.env` 加载，禁止写入代码
- KVM 硬件内部凭据仅在 `config.yaml` 中配置
- 前端 JS 中禁止出现任何凭据或密钥
- API 响应中 API Key 只返回前 8 字符预览（`api_key_preview`）
- **部署辅助脚本禁止硬编码 secret**（2026-04-16 教训）：任何 `deploy/*.sh` 脚本需要 Key 时必须从 env 读取，脚本首部加 `: "${FOO_KEY:?FOO_KEY env var required; see .env.test.example}"` 做校验。开发者本地 Key 放 `dev/kdkvm/deploy/.env.test.local`（被 root `.gitignore` 覆盖），先 `source` 再执行脚本。参考：`dev/kdkvm/deploy/test-setup.sh` + `.env.test.example`。

### 7.3 错误信息安全

- 前端禁止将 `e.message`、`d.error`、`JSON.stringify(err)` 直接显示给用户
- 后端 API 禁止在 JSON 响应中返回 Python traceback 或内部路径
- 技术细节只出现在 `console.error`（前端）和 `log.error`（后端）

### 7.4 危险操作确认

- ATX 电源操作（关机、重启、强制断电）必须在前端弹出二次确认
- AI Agent 的自动模式下，电源和格式化操作需用户明确确认
