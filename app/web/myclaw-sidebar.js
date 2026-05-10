/**
 * sidebar-patch.js — MyClaw Panel Sidebar Enhancement
 * Version: 4
 *
 * Adds a sidebar with view switching (Chat / Tasks / Settings) to the
 * MyClaw chat panel. Loaded dynamically by inject.js after the panel
 * is created.
 *
 * Architecture:
 *   #kvmind-chat-panel (flex row, 400px wide)
 *   ├── #kvmind-sidebar (45px, nav buttons)
 *   ├── #kvmind-chat-view (flex:1, original chat content)
 *   ├── #kvmind-task-view (flex:1, hidden by default)
 *   └── #kvmind-settings-view (flex:1, hidden by default)
 *
 * native KVM Compatibility:
 *   native KVM's wm.js registers global mouse handlers at capture phase.
 *   We intercept pointer/mouse events on the sidebar at document level
 *   (capture phase, stopImmediatePropagation) to prevent native KVM from
 *   swallowing clicks.
 */
(function () {
  "use strict";

  // =========================================================================
  // i18n — module-owned dict registered into the shared KVMindI18n engine.
  // All sidebar text (nav tooltips / settings panel / task view labels)
  // flows through KVMindI18n.t() / applyDOM() so language switches
  // propagate live. Stateful text (subscription card, telegram lock,
  // memory tags) is rendered via L(key) + textContent inside the relevant
  // paint helpers; static text uses data-i18n attributes + applyDOM.
  // =========================================================================

  var _SIDEBAR_I18N = {
    zh: {
      // sidebar nav
      chat: "聊天", tasks: "任务", settings: "MyClaw 设置",
      // settings panel
      hd: "⚙️ MyClaw 设置",
      g_ai: "🤖 AI 服务", g_ch: "📱 消息通道", g_pref: "🌐 语言与模式", g_mem: "🧠 AI 记忆",
      provider: "AI 服务商", model: "模型", test: "🔗 测试连接",
      base_url: "Base URL", api_key: "API Key",
      provider_ollama: "Ollama (Local)", provider_gemini: "Gemini",
      provider_anthropic: "Claude", provider_openai: "ChatGPT",
      provider_deepseek: "DeepSeek", provider_custom: "OpenAI 兼容（自定义）",
      testing: "测试中...",
      test_ok: "✅ 连接成功",
      test_ok_tools: "✅ 连接成功 — 支持自动执行",
      test_ok_suggest: "⚠ 连接成功 — 仅建议模式（当前模型不支持工具调用）。请更换为支持 Function Calling 的模型。",
      test_fail: "❌ 连接失败",
      no_model: "请先选择模型",
      free_input_hint: "无法拉取模型列表，请手动输入模型名。",
      other_option: "其他… (手动输入)",
      tg_token: "Telegram Bot Token", tg_hint: "从 @BotFather 创建 Bot 获取",
      more_channels: "更多渠道即将支持（WeChat、LINE 等）",
      // task view
      task_title: "📋 任务管理", task_empty: "暂无任务。",
      task_empty_hint: "通过聊天让 MyClaw 创建定时任务。",
      task_unnamed: "未命名任务",
      task_status_on: "● 启用", task_status_off: "○ 禁用",
      task_every_min: "每 {n} 分钟", task_every_sec: "每 {n} 秒",
      task_just_now: "刚才", task_min_ago: "{n} 分钟前",
      task_toggle: "切换", task_delete: "删除",
      task_runs: "已执行 {n} 次", task_last: "上次: ",
      // mode (legacy keys, kept for compat)
      mode: "操作模式", mode_suggest: "💡 建议模式", mode_auto: "⚡ 自动执行",
      mode_suggest_d: "AI 提建议，你确认后执行",
      mode_auto_d: "AI 直接操作，危险操作需确认",
      // memory
      mem_loading: "加载中...", mem_count: "已记住 {n} 条偏好",
      mem_clear: "清除记忆", mem_cleared: "✅ 已清除 {n} 条",
      mem_hint: "AI 会记住你的使用偏好和设备信息，用于提升后续对话质量",
      mem_empty: "暂无记忆",
      mem_tag_user_pref: "偏好", mem_tag_device_info: "设备",
      mem_tag_knowledge: "知识", mem_tag_instruction: "指令",
      // save
      save: "保存", saving: "保存中...",
      saved: "✅ 已保存", saved_tools: "✅ 已保存 — 支持自动执行",
      saved_suggest: "⚠ 已保存 — 仅建议模式（当前模型不支持工具调用）",
      save_fail: "❌ 保存失败",
      no_key: "请输入 API Key",
      // subscription card (stateful)
      plan_free: "Free", plan_paid: "Paid",
      plan_upgrade: "升级 →", plan_manage: "管理 →",
      feat_tunnel: "Tunnel", feat_messaging: "Messaging", feat_ota: "OTA",
      // telegram lock + placeholder
      tg_locked_msg: "🔒 Telegram Bot 需要订阅",
      tg_locked_cta: "升级以启用 →",
      tg_configured_ph: "•••••• (已配置)",
      // errors
      base_url_required: "请填写 Base URL",
      telegram_subscription_required: "Telegram 需要有效订阅",
    },
    ja: {
      chat: "チャット", tasks: "タスク", settings: "MyClaw 設定",
      hd: "⚙️ MyClaw 設定",
      g_ai: "🤖 AI サービス", g_ch: "📱 メッセージチャネル", g_pref: "🌐 言語・モード", g_mem: "🧠 AI メモリ",
      provider: "AI プロバイダ", model: "モデル", test: "🔗 接続テスト",
      base_url: "Base URL", api_key: "API Key",
      provider_ollama: "Ollama (Local)", provider_gemini: "Gemini",
      provider_anthropic: "Claude", provider_openai: "ChatGPT",
      provider_deepseek: "DeepSeek", provider_custom: "OpenAI 互換（カスタム）",
      testing: "テスト中...",
      test_ok: "✅ 接続成功",
      test_ok_tools: "✅ 接続成功 — 自動実行対応",
      test_ok_suggest: "⚠ 接続成功 — 提案モードのみ（現在のモデルはツール呼び出し非対応）。Function Calling 対応モデルへの変更をご検討ください。",
      test_fail: "❌ 接続失敗",
      no_model: "先にモデルを選択してください",
      free_input_hint: "モデル一覧を取得できません。モデル名を手動で入力してください。",
      other_option: "その他… (手動入力)",
      tg_token: "Telegram Bot Token", tg_hint: "@BotFather で Bot を作成して取得",
      more_channels: "他のチャネルは近日対応予定（WeChat、LINE等）",
      task_title: "📋 タスク管理", task_empty: "タスクがありません。",
      task_empty_hint: "チャットで MyClaw に定期タスクを作成してもらいましょう。",
      task_unnamed: "名称未設定",
      task_status_on: "● 有効", task_status_off: "○ 無効",
      task_every_min: "{n} 分ごと", task_every_sec: "{n} 秒ごと",
      task_just_now: "たった今", task_min_ago: "{n} 分前",
      task_toggle: "切替", task_delete: "削除",
      task_runs: "{n} 回実行済", task_last: "前回: ",
      mode: "動作モード", mode_suggest: "💡 提案モード", mode_auto: "⚡ 自動実行",
      mode_suggest_d: "AI が提案、確認後実行",
      mode_auto_d: "AI が直接操作、危険操作は確認",
      mem_loading: "読み込み中...", mem_count: "{n} 件の記憶を保持",
      mem_clear: "メモリをクリア", mem_cleared: "✅ {n} 件を削除しました",
      mem_hint: "AI が使用傾向やデバイス情報を記憶し、今後の対話を改善します",
      mem_empty: "メモリなし",
      mem_tag_user_pref: "好み", mem_tag_device_info: "デバイス",
      mem_tag_knowledge: "知識", mem_tag_instruction: "指示",
      save: "保存", saving: "保存中...",
      saved: "✅ 保存しました", saved_tools: "✅ 保存しました — 自動実行対応",
      saved_suggest: "⚠ 保存しました — 提案モードのみ（現在のモデルはツール呼び出し非対応）",
      save_fail: "❌ 保存失敗",
      no_key: "API Key を入力してください",
      plan_free: "Free", plan_paid: "Paid",
      plan_upgrade: "アップグレード →", plan_manage: "管理 →",
      feat_tunnel: "Tunnel", feat_messaging: "Messaging", feat_ota: "OTA",
      tg_locked_msg: "🔒 Telegram Bot はサブスクリプションが必要",
      tg_locked_cta: "アップグレードで有効化 →",
      tg_configured_ph: "•••••• (設定済み)",
      base_url_required: "Base URL を入力してください",
      telegram_subscription_required: "Telegram には有効なサブスクリプションが必要",
    },
    en: {
      chat: "Chat", tasks: "Tasks", settings: "MyClaw Settings",
      hd: "⚙️ MyClaw Settings",
      g_ai: "🤖 AI Service", g_ch: "📱 Channels", g_pref: "🌐 Language & Mode", g_mem: "🧠 AI Memory",
      provider: "AI Provider", model: "Model", test: "🔗 Test Connection",
      base_url: "Base URL", api_key: "API Key",
      provider_ollama: "Ollama (Local)", provider_gemini: "Gemini",
      provider_anthropic: "Claude", provider_openai: "ChatGPT",
      provider_deepseek: "DeepSeek", provider_custom: "OpenAI Compatible (Custom)",
      testing: "Testing...",
      test_ok: "✅ Connected",
      test_ok_tools: "✅ Connected — auto-execution supported",
      test_ok_suggest: "⚠ Connected — suggest mode only (model does not support tool calls). For auto mode, pick a model that supports Function Calling.",
      test_fail: "❌ Failed",
      no_model: "Please select a model first",
      free_input_hint: "Couldn't load model list — enter the model name manually.",
      other_option: "Other… (type manually)",
      tg_token: "Telegram Bot Token", tg_hint: "Create a Bot via @BotFather",
      more_channels: "More channels coming soon (WeChat, LINE, etc.)",
      task_title: "📋 Task Management", task_empty: "No tasks.",
      task_empty_hint: "Ask MyClaw via chat to create scheduled tasks.",
      task_unnamed: "Untitled",
      task_status_on: "● Enabled", task_status_off: "○ Disabled",
      task_every_min: "Every {n} min", task_every_sec: "Every {n} sec",
      task_just_now: "just now", task_min_ago: "{n}m ago",
      task_toggle: "Toggle", task_delete: "Delete",
      task_runs: "{n} runs", task_last: "Last: ",
      mode: "Operation Mode", mode_suggest: "💡 Suggest Mode", mode_auto: "⚡ Auto Execute",
      mode_suggest_d: "AI suggests, you confirm before execution",
      mode_auto_d: "AI executes directly, confirms for risky actions",
      mem_loading: "Loading...", mem_count: "{n} preferences remembered",
      mem_clear: "Clear Memory", mem_cleared: "✅ Cleared {n} items",
      mem_hint: "AI remembers your preferences and device info to improve future conversations",
      mem_empty: "No memories",
      mem_tag_user_pref: "Pref", mem_tag_device_info: "Device",
      mem_tag_knowledge: "Knowledge", mem_tag_instruction: "Instruction",
      save: "Save", saving: "Saving...",
      saved: "✅ Saved", saved_tools: "✅ Saved — auto-execution supported",
      saved_suggest: "⚠ Saved — suggest mode only (current model doesn't support tool calling)",
      save_fail: "❌ Save failed",
      no_key: "Please enter API Key",
      plan_free: "Free", plan_paid: "Paid",
      plan_upgrade: "Upgrade →", plan_manage: "Manage →",
      feat_tunnel: "Tunnel", feat_messaging: "Messaging", feat_ota: "OTA",
      tg_locked_msg: "🔒 Telegram Bot requires subscription",
      tg_locked_cta: "Upgrade to enable →",
      tg_configured_ph: "•••••• (configured)",
      base_url_required: "Please enter Base URL",
      telegram_subscription_required: "Telegram requires an active subscription",
    },
  };

  if (window.KVMindI18n && typeof window.KVMindI18n.registerDict === "function") {
    window.KVMindI18n.registerDict("sidebar", _SIDEBAR_I18N);
  }

  // Single i18n accessor — wraps KVMindI18n.t() with the sidebar namespace.
  // Falls back to the bundled dict if the runtime isn't loaded (defensive).
  function L(k) {
    if (window.KVMindI18n && window.KVMindI18n.t) {
      return window.KVMindI18n.t(k, null, "sidebar");
    }
    var lang = (window.localStorage && localStorage.getItem("kvmind_lang")) || "zh";
    var d = _SIDEBAR_I18N[lang] || _SIDEBAR_I18N.en;
    return (d && d[k]) || (_SIDEBAR_I18N.en && _SIDEBAR_I18N.en[k]) || k;
  }

  // =========================================================================
  // Constants
  // =========================================================================

  var PANEL_WIDTH = 400;       // Total panel width (px)
  var SIDEBAR_WIDTH = 45;      // Sidebar nav width (px)

  // =========================================================================
  // CSS
  // =========================================================================

  var CSS = [
    // Layout overrides
    "#kvmind-chat-panel:not(.collapsed) { width: var(--kvmind-panel-width, " + PANEL_WIDTH + "px) !important }",
    "body:not(.kvmind-panel-collapsed) #stream-window { right: var(--kvmind-panel-width, " + PANEL_WIDTH + "px) !important }",
    "body:not(.kvmind-panel-collapsed) #kvmind-stream-area { right: var(--kvmind-panel-width, " + PANEL_WIDTH + "px) !important }",
    "body:not(.kvmind-panel-collapsed) #kvmind-log-bar { right: var(--kvmind-panel-width, " + PANEL_WIDTH + "px) !important }",
    "body.kvmind-panel-collapsed #stream-window { right: 0 !important }",
    "body.kvmind-panel-collapsed #kvmind-stream-area { right: 0 !important }",
    "body.kvmind-panel-collapsed #kvmind-log-bar { right: 0 !important }",

    // Sidebar
    "#kvmind-sidebar {",
    "  width: " + SIDEBAR_WIDTH + "px; min-width: " + SIDEBAR_WIDTH + "px;",
    "  background: var(--kvsurface); border-right: 1px solid var(--kvborder);",
    "  display: flex; flex-direction: column; align-items: center;",
    "  padding: 8px 0; gap: 2px; flex-shrink: 0;",
    "}",

    // Sidebar buttons
    ".kvmind-sb-btn {",
    "  width: 36px; height: 36px;",
    "  display: flex; align-items: center; justify-content: center;",
    "  border-radius: 6px; font-size: 16px; cursor: pointer;",
    "  background: transparent; border: none;",
    "  color: var(--kvtext-muted); position: relative;",
    "  transition: background 0.12s;",
    "}",
    ".kvmind-sb-btn:hover { background: var(--kvsurface3) }",
    ".kvmind-sb-btn.active { background: var(--kvaccent-dim); color: var(--kvaccent) }",
    ".kvmind-sb-btn.active::before {",
    "  content: ''; position: absolute; left: 0; top: 6px; bottom: 6px;",
    "  width: 3px; background: var(--kvaccent); border-radius: 0 3px 3px 0;",
    "}",
    ".kvmind-sb-spacer { flex: 1 }",

    // View containers (shared)
    "#kvmind-chat-view, #kvmind-task-view, #kvmind-settings-view {",
    "  flex: 1; display: flex; flex-direction: column;",
    "  overflow: hidden; min-width: 0;",
    "}",
    "#kvmind-task-view, #kvmind-settings-view { display: none }",

    // Task view
    "#kvmind-task-header {",
    "  padding: 10px 14px; border-bottom: 1px solid var(--kvborder);",
    "  font-size: 13px; font-weight: 700; color: var(--kvtext); flex-shrink: 0;",
    "}",
    "#kvmind-task-list { flex: 1; overflow-y: auto; padding: 12px; font-size: 13px; color: var(--kvtext-muted) }",
    ".kvmind-task-empty { text-align: center; padding: 40px 16px; color: var(--kvtext-sub); font-size: 12px; line-height: 1.6 }",
    ".kvmind-task-item { padding: 10px 12px; border: 1px solid var(--kvborder); border-radius: 6px; margin-bottom: 8px; background: var(--kvsurface2) }",
    ".kvmind-task-item .name { font-weight: 600; color: var(--kvtext); font-size: 13px }",
    ".kvmind-task-item .schedule { font-size: 11px; color: var(--kvtext-sub); margin-top: 2px }",
    ".kvmind-task-item .status { font-size: 11px; margin-top: 4px }",
    ".kvmind-task-item .status.enabled { color: var(--kvgreen) }",
    ".kvmind-task-item .status.disabled { color: var(--kvtext-sub) }",
    ".kvmind-task-meta { font-size: 10px; color: var(--kvtext-sub); margin-top: 3px }",
    ".kvmind-task-actions { display: flex; gap: 6px; margin-top: 6px }",
    ".kvmind-task-actions button { font-size: 11px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--kvborder); background: var(--kvsurface); color: var(--kvtext-muted); cursor: pointer }",
    ".kvmind-task-actions button:hover { border-color: var(--kvaccent); color: var(--kvaccent) }",
    ".kvmind-task-actions button.del:hover { border-color: #e05252; color: #e05252 }",

    // Settings view
    "#kvmind-settings-view-header {",
    "  padding: 10px 14px; border-bottom: 1px solid var(--kvborder);",
    "  font-size: 13px; font-weight: 700; color: var(--kvtext); flex-shrink: 0;",
    "}",
    "#kvmind-settings-view-body { flex: 1; overflow-y: auto; padding: 0; font-size: 13px; color: var(--kvtext-muted) }",

    // Settings: accordion
    ".kv-set-group { border-bottom: 1px solid var(--kvborder) }",
    ".kv-set-group-hd {",
    "  padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 8px;",
    "  font-size: 13px; font-weight: 600; color: var(--kvtext); user-select: none;",
    "}",
    ".kv-set-group-hd:hover { background: var(--kvsurface2) }",
    ".kv-set-group-hd .arrow { font-size: 10px; color: var(--kvtext-sub); transition: transform .15s; margin-left: auto }",
    ".kv-set-group.open .arrow { transform: rotate(90deg) }",
    ".kv-set-group-bd { display: none; padding: 4px 16px 16px }",
    ".kv-set-group.open .kv-set-group-bd { display: block }",

    // Settings: form elements
    ".kv-set-label { font-size: 12px; color: var(--kvtext-muted); margin-bottom: 4px; display: block }",
    ".kv-set-row { margin-bottom: 12px }",
    ".kv-set-input, .kv-set-select {",
    "  box-sizing: border-box; width: 100%; max-width: 100%;",
    "  padding: 7px 10px; font-size: 13px; border-radius: 6px;",
    "  border: 1px solid var(--kvborder); background: var(--kvsurface2); color: var(--kvtext);",
    "  outline: none; font-family: inherit;",
    "}",
    ".kv-set-input:focus, .kv-set-select:focus { border-color: var(--kvaccent) }",
    ".kv-set-input-wrap { position: relative; display: block; box-sizing: border-box }",
    // Reserve space on the right for the eye-toggle button so masked text
    // doesn't slide underneath it. Eye-btn at right:8px (~22px wide) → 36px.
    ".kv-set-input-wrap .kv-set-input { padding-right: 36px }",
    ".kv-set-input-wrap .eye-btn {",
    "  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);",
    "  background: none; border: none; color: var(--kvtext-sub); cursor: pointer; font-size: 14px; padding: 2px;",
    "}",
    ".kv-set-hint { font-size: 11px; color: var(--kvtext-sub); margin-top: 3px }",
    ".kv-set-hint a { color: var(--kvaccent) }",

    // Settings: buttons
    ".kv-set-btn {",
    "  padding: 7px 14px; font-size: 12px; border-radius: 6px; cursor: pointer;",
    "  border: 1px solid var(--kvborder); background: var(--kvsurface2); color: var(--kvtext);",
    "  font-family: inherit; transition: background .12s;",
    "}",
    ".kv-set-btn:hover { background: var(--kvsurface3) }",
    ".kv-set-btn.primary { background: var(--kvaccent); color: #fff; border-color: var(--kvaccent) }",
    ".kv-set-btn.primary:hover { opacity: 0.85 }",
    ".kv-set-btn:disabled { opacity: 0.5; cursor: not-allowed }",
    ".kv-set-save-row { padding: 12px 16px; border-top: 1px solid var(--kvborder); display: flex; gap: 8px; align-items: center }",
    ".kv-set-status { font-size: 12px; flex: 1 }",
    ".kv-set-status.ok { color: var(--kvgreen, #3fb950) }",
    ".kv-set-status.err { color: var(--kvred, #f85149) }",
    ".kv-set-status.warn { color: #e3b341 }",

    // Settings: lang toggle
    ".kv-lang-btns { display: flex; gap: 0; border: 1px solid var(--kvborder); border-radius: 6px; overflow: hidden }",
    ".kv-lang-btn {",
    "  flex: 1; padding: 7px 0; text-align: center; font-size: 12px; cursor: pointer;",
    "  background: transparent; border: none; border-right: 1px solid var(--kvborder);",
    "  color: var(--kvtext-muted); font-family: inherit;",
    "}",
    ".kv-lang-btn:last-child { border-right: none }",
    ".kv-lang-btn.active { background: var(--kvaccent); color: #fff }",

    // Settings: channel status badge
    ".kv-ch-status { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 6px }",
    ".kv-ch-status.on { background: rgba(63,185,80,0.15); color: var(--kvgreen, #3fb950) }",
    ".kv-ch-status.off { background: rgba(139,148,158,0.15); color: var(--kvtext-sub) }",

    // Settings: memory list
    ".kv-mem-item {",
    "  padding: 6px 8px; border-radius: 4px; margin-bottom: 4px;",
    "  background: var(--kvsurface2); font-size: 12px; line-height: 1.4;",
    "  color: var(--kvtext); display: flex; gap: 6px; align-items: flex-start;",
    "}",
    ".kv-mem-item .kv-mem-tag {",
    "  font-size: 10px; padding: 1px 5px; border-radius: 3px; white-space: nowrap; flex-shrink: 0;",
    "  background: rgba(0,180,216,0.12); color: var(--kvaccent);",
    "}",
    ".kv-mem-item .kv-mem-text { flex: 1; word-break: break-word; color: var(--kvtext-muted) }",
  ].join("\n");

  // =========================================================================
  // Sidebar button definitions
  // =========================================================================

  // (i18n: _SB_I18N + _sbL/_sbLang removed \u2014 see _SIDEBAR_I18N + L() at top)

  var SIDEBAR_BUTTONS = [
    { id: "chat",     icon: "\uD83D\uDCAC", title: L("chat"),     active: true  },
    { id: "tasks",    icon: "\uD83D\uDCCB", title: L("tasks"),    active: false },
    { id: "_spacer" },
    { id: "settings", icon: "\u2699\uFE0F", title: L("settings"), active: false },
  ];

  // =========================================================================
  // DOM helpers
  // =========================================================================

  function createEl(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "className") el.className = attrs[k];
        else if (k === "textContent") el.textContent = attrs[k];
        else if (k === "innerHTML") { /* SECURITY: innerHTML via createEl is disallowed — use textContent or build DOM */ console.warn("[createEl] innerHTML ignored for safety; use textContent or DOM API"); }
        else if (k === "style") el.style.cssText = attrs[k];
        else el.setAttribute(k, attrs[k]);
      });
    }
    if (children) children.forEach(function (c) { el.appendChild(c); });
    return el;
  }

  function injectCSS(css) {
    var el = document.createElement("style");
    el.textContent = css;
    document.head.appendChild(el);
  }

  // =========================================================================
  // Task loader (placeholder — AI backend not yet connected)
  // =========================================================================

  function loadTasks() {
    var list = document.getElementById("kvmind-task-list");
    if (!list) return;

    var emptyHTML = '<div class="kvmind-task-empty">' + L("task_empty") + '<br>' + L("task_empty_hint") + '</div>';

    fetch("/kdkvm/api/tasks", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var jobs = data.jobs || data || [];
        if (!Array.isArray(jobs) || jobs.length === 0) { list.innerHTML = emptyHTML; return; }

        list.innerHTML = "";
        jobs.forEach(function (job) {
          var name  = job.name || job.command || job.id || L("task_unnamed");
          var rawSched = job.schedule || {};
          var sched = "";
          if (typeof rawSched === "string") { sched = rawSched; }
          else if (rawSched.kind === "every" && rawSched.every_ms) {
            var sec = rawSched.every_ms / 1000;
            sched = sec >= 60 ? L("task_every_min").replace("{n}", sec/60) : L("task_every_sec").replace("{n}", sec);
          } else if (rawSched.kind === "cron" && rawSched.expr) { sched = rawSched.expr; }
          else { sched = JSON.stringify(rawSched); }
          var on    = job.enabled !== false;
          var item  = createEl("div", { className: "kvmind-task-item" });
          var nameEl=createEl("div",{className:"name"});nameEl.textContent=name;item.appendChild(nameEl);
          if(sched){var schedEl=createEl("div",{className:"schedule"});schedEl.textContent="\u23F0 "+sched;item.appendChild(schedEl);}
          var statusEl=createEl("div",{className:"status "+(on?"enabled":"disabled")});statusEl.textContent=on?L("task_status_on"):L("task_status_off");item.appendChild(statusEl);
          // Tracking meta
          var meta = createEl("div", { className: "kvmind-task-meta" });
          var parts = [];
          if (job.run_count > 0) parts.push(L("task_runs").replace("{n}", job.run_count));
          if (job.last_run_at) {
            var ago = Math.floor((Date.now()/1000 - job.last_run_at) / 60);
            parts.push(L("task_last") + (ago < 1 ? L("task_just_now") : L("task_min_ago").replace("{n}", ago)));
          }
          if (parts.length) { meta.textContent = parts.join(" \u00B7 "); item.appendChild(meta); }
          // Action buttons
          var acts = createEl("div", { className: "kvmind-task-actions" });
          var toggleBtn = createEl("button"); toggleBtn.textContent = L("task_toggle");
          toggleBtn.onclick = function(e) { e.stopPropagation(); fetch("/kdkvm/api/tasks/" + job.id + "/toggle", {method:"POST", credentials:"same-origin"}).then(function(){ loadTasks(); }).catch(function(err){console.warn("Task toggle error:",err);}); };
          var delBtn = createEl("button", { className: "del" }); delBtn.textContent = L("task_delete");
          delBtn.onclick = function(e) { e.stopPropagation(); fetch("/kdkvm/api/tasks/" + job.id, {method:"DELETE", credentials:"same-origin"}).then(function(){ loadTasks(); }).catch(function(err){console.warn("Task delete error:",err);}); };
          acts.appendChild(toggleBtn); acts.appendChild(delBtn);
          item.appendChild(acts);
          list.appendChild(item);
        });
      })
      .catch(function (err) { console.warn("Task API error:", err); list.innerHTML = emptyHTML; });
  }

  // =========================================================================
  // Event interception (native KVM compatibility)
  //
  // native KVM's wm.js registers __globalMouseButtonHandler on document at
  // capture phase. We must register our own capture-phase listeners
  // *before* that handler runs and call stopImmediatePropagation() to
  // prevent native KVM from swallowing sidebar clicks.
  // =========================================================================

  function installEventInterceptor(sidebar, onSidebarClick) {
    // Intercept panel toggle buttons (native KVM wm.js blocks their events)
    var toggleIds = ["kvmind-btn-panel", "kvmind-collapse-btn", "kvmind-expand-tab"];
    ["pointerdown", "pointerup", "mousedown", "mouseup", "click"].forEach(function(evt) {
      document.addEventListener(evt, function(e) {
        var el = e.target.closest && (e.target.closest("#kvmind-btn-panel") || e.target.closest("#kvmind-collapse-btn") || e.target.closest("#kvmind-expand-tab"));
        if (!el) return;
        e.stopImmediatePropagation();
        if (evt === "pointerdown" && typeof window.kvmindTogglePanel === "function") {
          window.kvmindTogglePanel();
        }
      }, true);
    });

    // Primary: pointerdown triggers view switch
    document.addEventListener("pointerdown", function (e) {
      if (!sidebar.contains(e.target)) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      var btn = e.target.closest(".kvmind-sb-btn");
      if (btn) onSidebarClick(btn.getAttribute("data-view"));
    }, true);

    // Block remaining events from reaching native KVM
    ["pointerup", "mousedown", "mouseup", "click"].forEach(function (evt) {
      document.addEventListener(evt, function (e) {
        if (sidebar.contains(e.target)) {
          e.stopImmediatePropagation();
          e.preventDefault();
        }
      }, true);
    });
  }


  // =========================================================================
  // Main injection logic
  // =========================================================================

  var injected = false;

  function injectSidebar(panel) {
    if (injected) return;
    injected = true;

    // -- Inject CSS --
    injectCSS(CSS);

    // -- Reconfigure panel as flex row --
    panel.style.display = "flex";
    panel.style.flexDirection = "row";
    // width set via CSS, not inline

    // -- Wrap existing panel children into chatView --
    var chatView = createEl("div", { id: "kvmind-chat-view" });
    while (panel.firstChild) chatView.appendChild(panel.firstChild);

    // -- Build sidebar --
    var sidebar = createEl("div", { id: "kvmind-sidebar" });
    var buttons = [];

    SIDEBAR_BUTTONS.forEach(function (def) {
      if (def.id === "_spacer") {
        sidebar.appendChild(createEl("div", { className: "kvmind-sb-spacer" }));
        return;
      }
      var btn = createEl("button", {
        className: "kvmind-sb-btn" + (def.active ? " active" : ""),
        "data-view": def.id,
        title: def.title,
        textContent: def.icon,
      });
      buttons.push(btn);
      sidebar.appendChild(btn);
    });

    // -- Build task view --
    var taskView = createEl("div", { id: "kvmind-task-view" });
    var taskHeader = createEl("div", { id: "kvmind-task-header", textContent: L("task_title") });
    var taskList = createEl("div", { id: "kvmind-task-list" });
    var taskEmpty = createEl("div", { className: "kvmind-task-empty" });
    taskEmpty.appendChild(document.createTextNode(L("task_empty")));
    taskEmpty.appendChild(document.createElement("br"));
    taskEmpty.appendChild(document.createTextNode(L("task_empty_hint")));
    taskList.appendChild(taskEmpty);
    taskView.appendChild(taskHeader);
    taskView.appendChild(taskList);

    // -- Build settings view --
    var settingsView = createEl("div", { id: "kvmind-settings-view" });
    settingsView.innerHTML = _buildSettingsHTML();
    var settingsBody = null; // lazy ref

    // -- Assemble panel: sidebar first, then views --
    panel.appendChild(sidebar);
    panel.appendChild(chatView);
    panel.appendChild(taskView);
    panel.appendChild(settingsView);
    panel.insertBefore(sidebar, panel.firstChild);

    // -- View switching --
    var views = { chat: chatView, tasks: taskView, settings: settingsView };

    function switchView(name) {
      if (!name || !views[name]) return;
      buttons.forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-view") === name);
      });
      Object.keys(views).forEach(function (k) {
        views[k].style.display = (k === name) ? "flex" : "none";
      });
      if (name === "tasks") loadTasks();
      if (name === "settings") _loadSettings();
    }

    // -- Install native KVM-safe event handlers --
    installEventInterceptor(sidebar, switchView);

    // -- C3-2: Resizable panel width via drag handle --
    var PANEL_MIN = 320, PANEL_MAX = 500;
    var resizeHandle = createEl("div", { id: "kvmind-resize-handle" });
    panel.style.position = "fixed"; // ensure position context
    panel.insertBefore(resizeHandle, panel.firstChild);

    // Restore saved width
    var savedWidth = localStorage.getItem("kvmind_panel_width");
    if (savedWidth) {
      var sw = parseInt(savedWidth, 10);
      if (sw >= PANEL_MIN && sw <= PANEL_MAX) {
        applyPanelWidth(sw);
      }
    }

    function applyPanelWidth(w) {
      document.documentElement.style.setProperty("--kvmind-panel-width", w + "px");
    }

    var dragging = false;
    var dragPointerId = null;

    function clampPanelWidth(w) {
      if (w < PANEL_MIN) return PANEL_MIN;
      if (w > PANEL_MAX) return PANEL_MAX;
      return w;
    }

    function savePanelWidth() {
      var finalW = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--kvmind-panel-width"), 10);
      if (finalW >= PANEL_MIN && finalW <= PANEL_MAX) {
        localStorage.setItem("kvmind_panel_width", String(finalW));
      }
    }

    function onDragMove(ev) {
      if (!dragging) return;
      if (dragPointerId !== null && ev.pointerId !== undefined && ev.pointerId !== dragPointerId) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      applyPanelWidth(clampPanelWidth(window.innerWidth - ev.clientX));
    }

    function endDrag(ev) {
      if (!dragging) return;
      if (ev && dragPointerId !== null && ev.pointerId !== undefined && ev.pointerId !== dragPointerId) return;
      dragging = false;
      var pointerId = dragPointerId;
      dragPointerId = null;
      resizeHandle.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        if (resizeHandle.releasePointerCapture && pointerId !== null) resizeHandle.releasePointerCapture(pointerId);
      } catch (_) {}
      window.removeEventListener("pointermove", onDragMove, true);
      window.removeEventListener("pointerup", endDrag, true);
      window.removeEventListener("pointercancel", endDrag, true);
      window.removeEventListener("blur", endDrag, true);
      savePanelWidth();
    }

    resizeHandle.addEventListener("pointerdown", function (e) {
      if (e.button !== undefined && e.button !== 0) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      dragging = true;
      dragPointerId = e.pointerId;
      resizeHandle.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      try {
        if (resizeHandle.setPointerCapture && e.pointerId !== undefined) resizeHandle.setPointerCapture(e.pointerId);
      } catch (_) {}
      window.addEventListener("pointermove", onDragMove, true);
      window.addEventListener("pointerup", endDrag, true);
      window.addEventListener("pointercancel", endDrag, true);
      window.addEventListener("blur", endDrag, true);
    });

    // -- C3-3: Hide empty guide when messages are added --
    var emptyGuide = document.getElementById("kvmind-empty-guide");
    var chatMsgs = document.getElementById("kvmind-chat-messages");
    if (emptyGuide && chatMsgs) {
      // Check if there are already user/ai messages
      function checkEmptyGuide() {
        var msgs = chatMsgs.querySelectorAll(".kvmind-msg-row:not(.system):not(#kvmind-empty-guide)");
        if (msgs.length > 0) {
          emptyGuide.classList.add("hidden");
        } else {
          emptyGuide.classList.remove("hidden");
        }
      }
      checkEmptyGuide();
      // Observe new messages being added
      var msgObserver = new MutationObserver(function () {
        checkEmptyGuide();
      });
      msgObserver.observe(chatMsgs, { childList: true });
    }

    // -- Settings: accordion toggle --
    settingsView.addEventListener("click", function(e) {
      var hd = e.target.closest(".kv-set-group-hd");
      if (!hd) return;
      hd.parentElement.classList.toggle("open");
    });

    // -- Settings: init event handlers --
    _initSettingsEvents(settingsView);

    // -- Language change: applyDOM rewrites all [data-i18n] textContent in
    //    place (no DOM rebuild → input.value, select selected, accordion
    //    open state, scroll position all preserved). Stateful text (sub
    //    card, telegram lock, memory tags) is re-painted via the cached
    //    last-state path inside _loadSettings / _loadMemoryCount.
    if (window.KVMindI18n && typeof window.KVMindI18n.onLangChange === "function") {
      window.KVMindI18n.onLangChange(function () {
        // Sidebar nav tooltips (button.title isn't in [data-i18n] scope).
        buttons.forEach(function (b) {
          var id = b.getAttribute("data-view");
          if (id && L(id)) b.title = L(id);
        });
        // Static labels under settings/task views — bulk-translate via attr.
        if (window.KVMindI18n.applyDOM) {
          window.KVMindI18n.applyDOM(settingsView, "sidebar");
          window.KVMindI18n.applyDOM(taskView, "sidebar");
        }
        // Task header + dynamic task list rows must reload (rows aren't
        // [data-i18n] tagged — built from _setL via L() at render time).
        var th = document.getElementById("kvmind-task-header");
        if (th) th.textContent = L("task_title");
        if (taskView.style.display !== "none") loadTasks();
        // Stateful: subscription card + memory list + telegram placeholder.
        // Re-paint from last-known state cached on settingsView. Skip if
        // _loadSettings / _loadMemoryCount hasn't run yet (next open will
        // render correctly with new lang).
        if (settingsView._lastSub) _paintSubscriptionCard(settingsView, settingsView._lastSub);
        if (settingsView._lastMem) _paintMemoryList(settingsView, settingsView._lastMem);
        _paintTelegramPlaceholder(settingsView);
      });
    }

    if (window.KVMindI18n && typeof window.KVMindI18n.applyDOM === "function") {
      window.KVMindI18n.applyDOM(panel, "sidebar");
    }

    console.log("[sidebar-patch v5] injected");
  }

  // =========================================================================
  // Settings: i18n
  // (i18n: _SET_I18N + _setL removed — see _SIDEBAR_I18N + L() at top)
  // =========================================================================

  // Client-side display hints. Do NOT list models here — model discovery is
  // done at runtime by hitting the provider's own list-models endpoint.
  // See config.py AI Model Catalog Principle.
  var _PROVIDER_HINTS = {
    ollama:    { ph: "API Key (optional)", label: "Ollama Library",       noKey: true,  needsBase: true },
    gemini:    { ph: "AIza...",             label: "Google AI Studio",    needsBase: false },
    anthropic: { ph: "sk-ant-...",          label: "Anthropic Console",   needsBase: false },
    openai:    { ph: "sk-...",              label: "OpenAI Platform",     needsBase: false },
    deepseek:  { ph: "sk-...",              label: "DeepSeek Platform",   needsBase: false },
    custom:    { ph: "sk-...",              label: "OpenAI Compatible",   needsBase: true  },
  };

  // =========================================================================
  // Settings: HTML builder
  // =========================================================================

  function _buildSettingsHTML() {
    return '' +
    '<div id="kvmind-settings-view-header" data-i18n="hd">' + L("hd") + '</div>' +
    '<div id="kvmind-settings-view-body">' +

    // ── Subscription status (read-only) ──
    '<div id="kv-set-sub-card" class="kv-subscription-card" style="margin:0 12px 12px;padding:10px 14px;border-radius:10px;border:1px solid var(--kvborder);background:var(--kvbg-card)">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<span id="kv-sub-plan-label" style="font-weight:600;font-size:13px">' + L("plan_free") + '</span>' +
        '<a id="kv-sub-action-link" href="https://kvmind.com/pricing" target="_blank" style="font-size:12px;color:var(--kvaccent);text-decoration:none">' + L("plan_upgrade") + '</a>' +
      '</div>' +
      '<div id="kv-sub-features" style="font-size:11px;color:var(--kvtext-sub);margin-top:4px">\u2716 ' + L("feat_tunnel") + ' &nbsp; \u2716 ' + L("feat_messaging") + ' &nbsp; \u2716 ' + L("feat_ota") + '</div>' +
    '</div>' +

    // ── Group 1: AI Service (provider config only) ──
    '<div class="kv-set-group open">' +
      '<div class="kv-set-group-hd"><span data-i18n="g_ai">' + L("g_ai") + '</span><span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label" data-i18n="provider">' + L("provider") + '</label>' +
            '<select class="kv-set-select" id="kv-set-provider">' +
              '<option value="ollama" data-i18n="provider_ollama">' + L("provider_ollama") + '</option>' +
              '<option value="gemini" data-i18n="provider_gemini">' + L("provider_gemini") + '</option>' +
              '<option value="anthropic" data-i18n="provider_anthropic">' + L("provider_anthropic") + '</option>' +
              '<option value="openai" data-i18n="provider_openai">' + L("provider_openai") + '</option>' +
              '<option value="deepseek" data-i18n="provider_deepseek">' + L("provider_deepseek") + '</option>' +
              '<option value="custom" data-i18n="provider_custom">' + L("provider_custom") + '</option>' +
            '</select>' +
          '</div>' +
          '<div class="kv-set-row" id="kv-set-baseurl-row" style="display:none">' +
            '<label class="kv-set-label" data-i18n="base_url">' + L("base_url") + '</label>' +
            '<input type="text" class="kv-set-input" id="kv-set-baseurl" placeholder="https://...">' +
          '</div>' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label" data-i18n="api_key">' + L("api_key") + '</label>' +
            '<div class="kv-set-input-wrap">' +
              '<input type="password" class="kv-set-input" id="kv-set-apikey" placeholder="AIza...">' +
              '<button class="eye-btn" data-target="kv-set-apikey">\uD83D\uDC41</button>' +
            '</div>' +
            '<div class="kv-set-hint" id="kv-set-key-hint"></div>' +
          '</div>' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label" data-i18n="model">' + L("model") + '</label>' +
            '<select class="kv-set-select" id="kv-set-model"></select>' +
            '<input type="text" class="kv-set-input" id="kv-set-model-text" placeholder="" style="display:none;margin-top:6px">' +
            '<div class="kv-set-hint" id="kv-set-model-hint" style="margin-top:4px"></div>' +
          '</div>' +
          '<button class="kv-set-btn" id="kv-set-test-btn" data-i18n="test">' + L("test") + '</button>' +
          '<div class="kv-set-status" id="kv-set-test-status" style="margin-top:6px"></div>' +
      '</div>' +
    '</div>' +

    // ── Group 2: Channels (messaging gated by subscription) ──
    '<div class="kv-set-group">' +
      '<div class="kv-set-group-hd"><span data-i18n="g_ch">' + L("g_ch") + '</span><span id="kv-set-ch-badges"></span><span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
        '<div id="kv-set-tg-section">' +
          '<div class="kv-set-row" id="kv-set-tg-locked" style="display:none">' +
            '<div style="text-align:center;padding:8px 0;color:var(--kvtext-sub);font-size:12px">' +
              '<span data-i18n="tg_locked_msg">' + L("tg_locked_msg") + '</span>' +
              '<br><a href="https://kvmind.com/pricing" target="_blank" style="color:var(--kvaccent);text-decoration:none;font-size:12px" data-i18n="tg_locked_cta">' + L("tg_locked_cta") + '</a>' +
            '</div>' +
          '</div>' +
          '<div class="kv-set-row" id="kv-set-tg-unlocked">' +
            '<label class="kv-set-label" data-i18n="tg_token">' + L("tg_token") + '</label>' +
            '<div class="kv-set-input-wrap">' +
              '<input type="password" class="kv-set-input" id="kv-set-tg-token" placeholder="123456:ABC-DEF...">' +
              '<button class="eye-btn" data-target="kv-set-tg-token">\uD83D\uDC41</button>' +
            '</div>' +
            '<div class="kv-set-hint" data-i18n="tg_hint">' + L("tg_hint") + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="kv-set-row" style="opacity:0.4;text-align:center;padding:8px">' +
          '<span style="font-size:11px" data-i18n="more_channels">' + L("more_channels") + '</span>' +
        '</div>' +
      '</div>' +
    '</div>' +

    // ── Group 3: AI Memory ──
    '<div class="kv-set-group">' +
      '<div class="kv-set-group-hd"><span data-i18n="g_mem">' + L("g_mem") + '</span><span class="kv-set-mem-count"></span><span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">' +
          '<span class="kv-set-label" style="margin:0" id="kv-set-mem-info">' + L("mem_loading") + '</span>' +
          '<button class="kv-set-btn" id="kv-set-mem-clear" style="white-space:nowrap" data-i18n="mem_clear">' + L("mem_clear") + '</button>' +
        '</div>' +
        '<div id="kv-set-mem-list"></div>' +
        '<div class="kv-set-hint" style="margin-top:8px" data-i18n="mem_hint">' + L("mem_hint") + '</div>' +
      '</div>' +
    '</div>' +

    '</div>' + // end body

    // ── Save bar ──
    '<div class="kv-set-save-row">' +
      '<div class="kv-set-status" id="kv-set-save-status"></div>' +
      '<button class="kv-set-btn primary" id="kv-set-save-btn" data-i18n="save">' + L("save") + '</button>' +
    '</div>';
  }


  // =========================================================================
  // Settings: event wiring
  // =========================================================================

  function _initSettingsEvents(root) {
    // Eye buttons (toggle password visibility)
    root.addEventListener("click", function(e) {
      var eyeBtn = e.target.closest(".eye-btn");
      if (!eyeBtn) return;
      var inp = root.querySelector("#" + eyeBtn.getAttribute("data-target"));
      if (!inp) return;
      if (inp.type === "password") { inp.type = "text"; eyeBtn.textContent = "\uD83D\uDE48"; }
      else { inp.type = "password"; eyeBtn.textContent = "\uD83D\uDC41"; }
    });

    // Provider change
    var provSel = root.querySelector("#kv-set-provider");
    if (provSel) provSel.addEventListener("change", function() { _onProviderChange(root); });

    // Test connection
    var testBtn = root.querySelector("#kv-set-test-btn");
    if (testBtn) testBtn.addEventListener("click", function() { _testConnection(root); });

    // Clear memory
    var memBtn = root.querySelector("#kv-set-mem-clear");
    if (memBtn) memBtn.addEventListener("click", function() { _clearMemory(root); });

    // Save
    var saveBtn = root.querySelector("#kv-set-save-btn");
    if (saveBtn) saveBtn.addEventListener("click", function() { _saveSettings(root); });
  }

  // =========================================================================
  // Settings: provider change handler
  // =========================================================================

  // Unified provider handler. For every provider:
  //   1. Set placeholder and console_url link for the API key.
  //   2. Show base_url row for providers that need it (ollama).
  //   3. Fetch the live model list with current key + base_url.
  //   4. Populate dropdown with fetched models + "Other..." tail option.
  //   5. If fetch fails, fall back to free text input.
  // Device code never ships a hardcoded model list; see config.py AI Model
  // Catalog Principle.
  async function _onProviderChange(root, opts) {
    opts = opts || {};
    var prov = root.querySelector("#kv-set-provider").value;
    var urlRow = root.querySelector("#kv-set-baseurl-row");
    var urlInput = root.querySelector("#kv-set-baseurl");
    var keyInput = root.querySelector("#kv-set-apikey");
    var hintEl = root.querySelector("#kv-set-key-hint");
    var modelSel = root.querySelector("#kv-set-model");
    var modelText = root.querySelector("#kv-set-model-text");
    var modelHint = root.querySelector("#kv-set-model-hint");

    var h = _PROVIDER_HINTS[prov] || {};
    // Ollama is user-hosted — always show Base URL. Cloud providers hide it.
    urlRow.style.display = h.needsBase ? "" : "none";
    keyInput.placeholder = h.ph || "API Key";

    // Always show console_url (picked up from backend metadata below).
    hintEl.innerHTML = "";

    // Default to showing the dropdown; we'll hide it only if fetch fails hard.
    modelSel.style.display = "";
    modelText.style.display = "none";
    modelSel.innerHTML = '<option value="">\u2014</option>';
    if (modelHint) modelHint.textContent = "";

    var currentKey = keyInput.value.trim();
    var currentBase = urlInput.value.trim();
    var payload = { provider: prov };
    if (currentKey) payload.api_key = currentKey;
    if (currentBase) payload.base_url = currentBase;

    var d = null;
    try {
      var r = await fetch("/kdkvm/api/ai/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "same-origin",
      });
      d = await r.json();
    } catch (e) {
      d = { models: [], free_input_only: true, error: String(e) };
    }

    // console_url hint is always useful — link to provider's own catalog.
    if (d && d.console_url) {
      var label = h.label || prov;
      hintEl.innerHTML = '<a href="' + d.console_url + '" target="_blank">' + label + ' \u2197</a>';
    }

    // Reflect returned canonical base_url if the row is visible and empty.
    if (h.needsBase && !urlInput.value && d && d.base_url) {
      urlInput.value = d.base_url;
    }

    var models = (d && d.models) || [];
    var freeOnly = !!(d && d.free_input_only);
    var preselect = opts.preselect || "";

    if (freeOnly || models.length === 0) {
      // Provider unreachable or no key yet — collapse to free input.
      modelSel.innerHTML = "";
      var only = document.createElement("option");
      only.value = "__other__";
      only.textContent = L("other_option");
      modelSel.appendChild(only);
      modelSel.value = "__other__";
      modelText.style.display = "";
      modelText.placeholder = preselect || "";
      modelText.value = preselect;
      if (modelHint) modelHint.textContent = L("free_input_hint");
    } else {
      modelSel.innerHTML = "";
      models.forEach(function(m) {
        var opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        modelSel.appendChild(opt);
      });
      var otherOpt = document.createElement("option");
      otherOpt.value = "__other__";
      otherOpt.textContent = L("other_option");
      modelSel.appendChild(otherOpt);

      if (preselect && models.indexOf(preselect) !== -1) {
        modelSel.value = preselect;
        modelText.style.display = "none";
      } else if (preselect) {
        modelSel.value = "__other__";
        modelText.style.display = "";
        modelText.value = preselect;
      } else {
        modelSel.selectedIndex = 0;
        modelText.style.display = "none";
        modelText.value = "";
      }
    }

    // Toggle text input when user picks "Other..."
    if (!modelSel._kvOtherBound) {
      modelSel.addEventListener("change", function() {
        if (modelSel.value === "__other__") {
          modelText.style.display = "";
          modelText.focus();
        } else {
          modelText.style.display = "none";
        }
      });
      modelSel._kvOtherBound = true;
    }
  }

  // Read whichever of the two model inputs is currently active.
  function _readSelectedModel(root) {
    var modelSel = root.querySelector("#kv-set-model");
    var modelText = root.querySelector("#kv-set-model-text");
    if (!modelSel) return "";
    if (modelSel.value === "__other__" || modelText.style.display !== "none") {
      return (modelText.value || "").trim();
    }
    var v = modelSel.value || "";
    if (v === "" || v === "__other__") return "";
    return v;
  }

  // =========================================================================
  // Settings: test connection
  // =========================================================================

  async function _testConnection(root) {
    var prov = root.querySelector("#kv-set-provider").value;
    var key = root.querySelector("#kv-set-apikey").value.trim();
    var statusEl = root.querySelector("#kv-set-test-status");
    var btn = root.querySelector("#kv-set-test-btn");
    var h = _PROVIDER_HINTS[prov] || {};
    var keyOptional = !!h.noKey;
    if (!key && !keyOptional) { statusEl.className = "kv-set-status err"; statusEl.textContent = L("no_key"); return; }
    var model = _readSelectedModel(root);
    // Provider API is the sole model-name validator. Device-side we only
    // require the user to pick/type *something* before calling /api/ai/test.
    if (!model) {
      statusEl.className = "kv-set-status err";
      statusEl.textContent = L("no_model");
      return;
    }
    var baseUrl = root.querySelector("#kv-set-baseurl").value.trim();
    if (h.needsBase && !baseUrl) {
      statusEl.className = "kv-set-status err"; statusEl.textContent = L("base_url_required"); return;
    }
    btn.textContent = L("testing"); btn.disabled = true;
    try {
      var payload = { provider: prov, api_key: key || "none", model: model };
      if (baseUrl) payload.base_url = baseUrl;
      var r = await fetch("/kdkvm/api/ai/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      var d = await r.json();
      if (d.success) {
        if (d.supports_tools === false) {
          statusEl.className = "kv-set-status warn";
          statusEl.textContent = L("test_ok_suggest");
        } else {
          statusEl.className = "kv-set-status ok";
          statusEl.textContent = L("test_ok_tools");
        }
      } else {
        statusEl.className = "kv-set-status err";
        statusEl.textContent = L("test_fail") + ": " + (d.error || "");
      }
    } catch (e) {
      statusEl.className = "kv-set-status err";
      statusEl.textContent = L("test_fail") + ": " + e.message;
    } finally {
      btn.textContent = L("test"); btn.disabled = false;
    }
  }

  // =========================================================================
  // Settings: load from API
  // =========================================================================

  async function _loadSettings() {
    try {
      var root = document.getElementById("kvmind-settings-view");
      if (!root) return;

      // ── 1. Load subscription status ──
      var sub = { entitlement_state: "local_free", tunnel: false, messaging: false, ota: false };
      try {
        var sr = await fetch("/kdkvm/api/subscription");
        sub = await sr.json();
      } catch (e) { console.warn("[Settings] subscription fetch failed:", e); }

      var paid = sub.entitlement_state === "paid";

      var planLabel = root.querySelector("#kv-sub-plan-label");
      if (planLabel) planLabel.textContent = paid ? L("plan_paid") : L("plan_free");

      var featEl = root.querySelector("#kv-sub-features");
      if (featEl) {
        var f = [];
        f.push((sub.tunnel ? "\u2714" : "\u2716") + " " + L("feat_tunnel"));
        f.push((sub.messaging ? "\u2714" : "\u2716") + " " + L("feat_messaging"));
        f.push((sub.ota ? "\u2714" : "\u2716") + " " + L("feat_ota"));
        featEl.textContent = f.join("  \u00B7  ");
      }

      var actionLink = root.querySelector("#kv-sub-action-link");
      if (actionLink) {
        if (!paid) {
          actionLink.textContent = L("plan_upgrade");
          actionLink.href = "https://kvmind.com/pricing";
        } else {
          actionLink.textContent = L("plan_manage");
          actionLink.href = "https://kvmind.com/account";
        }
      }

      // Telegram gate: show locked or unlocked section
      var tgLocked = root.querySelector("#kv-set-tg-locked");
      var tgUnlocked = root.querySelector("#kv-set-tg-unlocked");
      if (tgLocked && tgUnlocked) {
        if (sub.messaging) {
          tgLocked.style.display = "none";
          tgUnlocked.style.display = "";
        } else {
          tgLocked.style.display = "";
          tgUnlocked.style.display = "none";
        }
      }

      // ── 2. Load AI config ──
      var r = await fetch("/kdkvm/api/ai/config");
      var d = await r.json();
      window._kvmindSupportsTools = d.supports_tools !== false;

      // Provider details — always load if providers exist.
      // Unknown provider names are skipped (no more "other" fallback — the
      // custom/other concept is dead; every provider uses the same UI path).
      if (d.providers && d.providers.length > 0) {
        var p = d.providers[0];
        var provName = p.name || "";
        var provSel = root.querySelector("#kv-set-provider");
        var hasOpt = Array.from(provSel.options).some(function(o) { return o.value === provName; });
        if (hasOpt) provSel.value = provName;
        if (p.api_key_preview) root.querySelector("#kv-set-apikey").placeholder = p.api_key_preview;
        if (p.base_url && provName === "ollama") root.querySelector("#kv-set-baseurl").value = p.base_url;
        // Kick off runtime model discovery with the saved model preselected.
        await _onProviderChange(root, { preselect: p.default_model || "" });
      } else {
        // No provider configured yet — initialize provider dropdown.
        await _onProviderChange(root);
      }

      // Channel badges
      var badges = "";
      if (d.telegram_configured) badges += '<span class="kv-ch-status on">Telegram</span>';
      var badgeEl = root.querySelector("#kv-set-ch-badges");
      if (badgeEl) badgeEl.innerHTML = badges;

      // Telegram token placeholder (cached for re-paint on lang change).
      root._tgConfigured = !!d.telegram_configured;
      _paintTelegramPlaceholder(root);

      // Memory count
      _loadMemoryCount(root);
    } catch (e) {
      console.warn("[Settings] load failed:", e);
    }
  }

  // (i18n: _MEM_TAG_MAP removed \u2014 keys live under sidebar/mem_tag_* via L())
  var _MEM_VALID_TAGS = { user_pref: 1, device_info: 1, knowledge: 1, instruction: 1 };

  // Re-paint memory section from cached data (called both after fetch and
  // on language switch — count text + per-item tag both depend on lang).
  function _paintMemoryList(root, data) {
    if (!root) return;
    var info = root.querySelector("#kv-set-mem-info");
    var badge = root.querySelector(".kv-set-mem-count");
    var listEl = root.querySelector("#kv-set-mem-list");
    var n = (data && data.count) || 0;
    var memories = (data && data.memories) || [];
    if (info) info.textContent = n > 0 ? L("mem_count").replace("{n}", n) : L("mem_empty");
    if (badge) { badge.textContent = n > 0 ? " (" + n + ")" : ""; badge.style.color = "var(--kvtext-sub)"; badge.style.fontSize = "12px"; }
    var btn = root.querySelector("#kv-set-mem-clear");
    if (btn) btn.disabled = (n === 0);
    if (!listEl) return;
    if (memories.length === 0) {
      listEl.innerHTML = "";
      return;
    }
    var html = "";
    memories.forEach(function(m) {
      var tagKey = "mem_tag_" + (_MEM_VALID_TAGS[m.category] ? m.category : "knowledge");
      var tag = L(tagKey);
      html += '<div class="kv-mem-item">' +
        '<span class="kv-mem-tag">' + tag + '</span>' +
        '<span class="kv-mem-text">' + _escHtml(m.content) + '</span>' +
      '</div>';
    });
    listEl.innerHTML = html;
  }

  async function _loadMemoryCount(root) {
    try {
      var r = await fetch("/kdkvm/api/ai/memory");
      var d = await r.json();
      root._lastMem = d;
      _paintMemoryList(root, d);
    } catch (e) {
      root._lastMem = { count: 0, memories: [] };
      _paintMemoryList(root, root._lastMem);
    }
  }

  function _escHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function _clearMemory(root) {
    var btn = root.querySelector("#kv-set-mem-clear");
    var info = root.querySelector("#kv-set-mem-info");
    btn.disabled = true;
    try {
      var r = await fetch("/kdkvm/api/ai/memory", { method: "DELETE" });
      var d = await r.json();
      if (info) info.textContent = L("mem_cleared").replace("{n}", d.deleted || 0);
      var badge = root.querySelector(".kv-set-mem-count");
      if (badge) badge.textContent = "";
      setTimeout(function() { _loadMemoryCount(root); }, 2000);
    } catch (e) {
      if (info) info.textContent = L("mem_empty");
      btn.disabled = false;
    }
  }

  // =========================================================================
  // Settings: save to API
  // =========================================================================

  async function _saveSettings(root) {
    var statusEl = root.querySelector("#kv-set-save-status");
    var btn = root.querySelector("#kv-set-save-btn");

    // Saving may take a few seconds because we internally call /api/ai/test
    // first to determine supports_tools for the current model. Show progress
    // immediately so the user knows the click was registered.
    btn.disabled = true;
    btn.textContent = L("saving");
    statusEl.className = "kv-set-status";
    statusEl.textContent = "";

    try {
      var body = {};

      // AI provider config — unified for all known providers. No more
      // "other"/"custom" branch: every provider uses the same save payload.
      // Model validation is deferred to the provider API itself.
      var prov = root.querySelector("#kv-set-provider").value;
      var key = root.querySelector("#kv-set-apikey").value.trim();
      var model = _readSelectedModel(root);
      var h = _PROVIDER_HINTS[prov] || {};
      if (key || h.noKey) {
        var keyMap = { ollama: "ollama_key", gemini: "gemini_key", anthropic: "claude_key", openai: "openai_key", deepseek: "deepseek_key", custom: "custom_key" };
        if (key) body[keyMap[prov]] = key;
        if (h.noKey) body[prov + "_enabled"] = true;
        if (h.needsBase) {
          var baseVal = root.querySelector("#kv-set-baseurl").value.trim();
          if (baseVal) body[prov + "_url"] = baseVal;
        }
        if (model) body[prov + "_model"] = model;
      }

      // Detect tool support for the model being saved by calling the test API.
      // Backend falls back to the saved api_key when this request is empty
      // (authenticated callers only), so users can change models without
      // having to re-type their key. Default to true if no model selected
      // or the test errors out — never let a stale false block auto mode.
      var supportsTools = true;
      var testRan = false;
      if (model) {
        try {
          var testPayload = { provider: prov, api_key: key || "none", model: model };
          var baseVal2 = root.querySelector("#kv-set-baseurl").value.trim();
          if (baseVal2) testPayload.base_url = baseVal2;
          var tr = await fetch("/kdkvm/api/ai/test", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(testPayload),
          });
          var td = await tr.json();
          if (td.success) {
            supportsTools = td.supports_tools !== false;
            testRan = true;
          }
        } catch (e) { /* keep default true */ }
      }
      body.supports_tools = supportsTools;

      // Telegram (only if unlocked section is visible)
      var tgUnlocked = root.querySelector("#kv-set-tg-unlocked");
      if (tgUnlocked && tgUnlocked.style.display !== "none") {
        var tg = root.querySelector("#kv-set-tg-token").value.trim();
        if (tg) body.telegram_token = tg;
      }

      try {
        var r = await fetch("/kdkvm/api/ai/config", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        var d = await r.json();
        if (r.status === 403 && d.error === "messaging_not_enabled") {
          statusEl.className = "kv-set-status err";
          statusEl.textContent = L("telegram_subscription_required");
        } else if (d.status === "ok") {
          window._kvmindSupportsTools = supportsTools;
          if (testRan && !supportsTools) {
            statusEl.className = "kv-set-status warn";
            statusEl.textContent = L("saved_suggest");
          } else if (testRan) {
            statusEl.className = "kv-set-status ok";
            statusEl.textContent = L("saved_tools");
          } else {
            statusEl.className = "kv-set-status ok";
            statusEl.textContent = L("saved");
          }
        } else {
          statusEl.className = "kv-set-status err";
          statusEl.textContent = L("save_fail") + ": " + (d.error || "");
        }
      } catch (e) {
        statusEl.className = "kv-set-status err";
        statusEl.textContent = L("save_fail") + ": " + e.message;
      }
    } finally {
      btn.disabled = false;
      btn.textContent = L("save");
      setTimeout(function() { statusEl.textContent = ""; }, 3000);
    }
  }


  // =========================================================================
  // Wait for #kvmind-chat-panel to appear (created dynamically by inject.js)
  // =========================================================================

  function waitForPanel() {
    var panel = document.getElementById("kvmind-chat-panel");
    if (panel && panel.children.length > 0) {
      injectSidebar(panel);
      return;
    }

    // MutationObserver: fires when inject.js creates the panel
    var observer = new MutationObserver(function (_, obs) {
      var p = document.getElementById("kvmind-chat-panel");
      if (p && p.children.length > 0) {
        obs.disconnect();
        setTimeout(function () { injectSidebar(p); }, 150);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Fallback polling (in case MutationObserver misses it)
    var attempts = 0;
    var iv = setInterval(function () {
      var p = document.getElementById("kvmind-chat-panel");
      if (p && p.children.length > 0) { clearInterval(iv); injectSidebar(p); }
      if (++attempts > 50) clearInterval(iv);
    }, 200);
  }

  // -- Entry point --
function init() {
    var panel = document.getElementById("kvmind-chat-panel");
    if (panel && panel.children.length > 0) {
        injectSidebar(panel);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function() { setTimeout(init, 200); });
} else {
    setTimeout(init, 200);
}

})();
