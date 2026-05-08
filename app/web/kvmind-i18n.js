/* ============================================================================
 * KVMind Unified i18n Runtime
 * ----------------------------------------------------------------------------
 * Single source of truth for every HTML page and JS module served by kdkvm.
 *
 * Usage (per page):
 *   <script src="/kdkvm/kvmind-i18n.js?v=..."></script>
 *   <script>KVMindI18n.init('setup');</script>          // binds this page's namespace
 *   <button data-i18n="btn_save">保存</button>           // auto-translated on apply
 *   KVMindI18n.t('plan_sub_countdown',{min:9,sec:40})   // runtime lookup
 *
 * Cross-namespace lookup (e.g. widget calling from inside setup/activate):
 *   KVMindI18n.t('plan_sub_start', null, 'widget')
 *
 * Adding a page's keys: append a new top-level entry in DICTS below with
 * {zh:{...},ja:{...},en:{...}}. Duplicate keys within the same object are
 * caught by scripts/check-i18n.py (not by JS — last-wins at runtime).
 * ============================================================================ */
(function (global) {
  'use strict';

  // ── dictionaries (namespace → lang → key → string) ──────────────────────────
  var DICTS = {

    // =======================================================================
    // setup.html
    // =======================================================================
    setup: {
      zh: {
        wizard_title: 'KVMind 初始化向导',
        wizard_subtitle: '首次使用请完成以下配置，大约需要 2 分钟',
        step_network: '网络配置',
        step_test: '连接测试',
        step_subscription: '订阅与通讯',
        step_ai: 'AI 配置',
        step_done: '完成',
        wifi_title: '选择 WiFi 网络',
        wifi_desc: '设备将通过 WiFi 连接到您的局域网',
        wifi_scan: '🔍 扫描网络',
        wifi_scan_hint: '点击"扫描网络"查看可用 WiFi',
        wifi_scanning: '扫描中…',
        wifi_rescan: '🔍 重新扫描',
        wifi_no_network: '未发现网络',
        wifi_scan_fail: '扫描失败：',
        wifi_connected: '已连接',
        wifi_password_label: 'WiFi 密码',
        wifi_password_placeholder: '输入密码',
        wifi_password_hint: 'WPA/WPA2 密码，如为开放网络可留空',
        wifi_skip_hint: '也可跳过，使用有线以太网',
        btn_skip: '跳过',
        btn_connect_wifi: '连接 WiFi',
        wifi_connecting: '连接中…',
        wifi_connect_ok: '✓ 已连接到 {ssid}，IP: {ip}',
        wifi_connect_fail: '✗ 连接失败: {msg}',
        wifi_connect_err: '✗ 错误: {msg}',
        test_title: '连接测试',
        test_desc: '正在验证网络连接和 KVM 服务状态',
        test_network: '⏳ 检测网络连接…',
        test_pikvm: '⏳ 检测 KVM 服务…',
        test_kvmind: '⏳ 检测 KVMind 服务…',
        test_network_ok: '✓ 网络正常，IP: {ip}',
        test_network_ok2: '✓ 网络已连接（IP获取中）',
        test_network_fail: '✗ 无法获取网络状态',
        test_pikvm_ok: '✓ KVM 服务正常',
        test_pikvm_fail: '✗ KVM 服务未响应',
        test_pikvm_err: '✗ 无法连接 KVM 服务',
        test_kvmind_ok: '✓ KVMind 服务就绪',
        test_kvmind_warn: '⚠️ KVMind 未启动（可稍后配置）',
        test_all_ok: '所有服务正常，可以继续',
        test_partial_fail: '部分服务异常，请检查配置后重试',
        btn_prev: '← 上一步',
        btn_next: '下一步 →',
        ai_title: 'KVMind AI 配置',
        ai_desc: '按下方三部分分别完成：订阅选择、AI 代理配置、消息渠道绑定',
        ai_host_label: 'KVMind 主机地址',
        ai_host_hint: 'KVMind 服务运行的主机（默认本机）',
        ai_port_label: '端口',
        ai_apikey_label: 'API Key（可选）',
        ai_apikey_placeholder: '留空表示无认证',
        ai_mode_label: '默认操作模式',
        ai_mode_suggest: '💡 建议模式（AI提建议，人工执行）',
        ai_mode_auto: '⚡ 自动执行模式（AI自动操作，危险操作需确认）',
        btn_save: '保存并继续 →',
        config_saved: '✓ 配置已保存',
        config_deferred: '配置将在下次重启生效',
        done_title: '最后一步：设置访问密码',
        done_desc2: '设置密码后即可完成初始化，通过远程访问控制设备',
        setup_uid_label: '设备 UID',
        setup_password_label: '设置访问密码',
        setup_password_confirm: '确认密码',
        setup_password_hint: '此密码用于通过 UID 远程访问设备时登录',
        setup_password_short: '密码至少 8 位',
        setup_password_mismatch: '两次输入的密码不一致',
        setup_activating: '正在完成初始化…',
        setup_activate_ok: '设备初始化完成！正在跳转…',
        setup_activate_partial: '设备密码已设置，但云端初始化失败。设备可正常使用，在线功能将在下次联网时同步。',
        setup_activate_fail: '初始化失败，请检查网络连接后重试',
        btn_complete_setup: '完成初始化 ✓',
        btn_enter_console: '进入控制台 →',
        plan_free_title: '免费试用',
        plan_free_desc: '开箱即用，包含基础 AI 功能',
        plan_sub_title: '已订阅',
        plan_sub_desc: '获取 claim code，在浏览器中完成账号绑定',
        plan_sub_go_activate: '前往激活页 →',
        plan_sub_start_free: '开始使用免费版',
        plan_sub_learn_more: '了解订阅',
        plan_sub_skipped: '已选择免费版，可继续下一步',
        plan_sub_not_activated: '请先完成 claim（或选"开始使用免费版"）',
        plan_sub_pending_hint: '订阅状态尚未激活，已按免费版保存；账号绑定后会自动升级权益',
        plan_sub_current: '当前计划：Free · 设备尚未绑定账号',
        plan_custom_provider_label: 'AI 服务商',
        ai_provider_label: 'AI 服务商',
        ai_key_label: 'API Key',
        ai_key_hint: '从服务商控制台获取的 API Key',
        ai_model_label: '模型名称',
        ai_model_hint: '可手动修改为其他模型',
        ai_test_btn: '🔗 测试连接',
        ai_testing: '测试中…',
        ai_test_ok: '✓ AI 连接成功！',
        ai_test_ok_tools: '✓ 连接成功 — 支持自动执行',
        ai_test_ok_suggest: '⚠ 连接成功 — 仅建议模式（模型不支持工具调用）',
        ai_test_fail: '✗ 连接失败: {msg}',
        ai_error_missing_api_key: '请填写 API Key',
        ai_error_invalid_api_key: 'API Key 无效或已被吊销',
        ai_error_insufficient_quota: 'API Key 配额或余额不足',
        ai_error_invalid_model: '模型名无效，请检查拼写或从下拉列表中重新选择',
        ai_error_rate_limit: '调用过于频繁，请稍后重试',
        ai_error_upstream_unavailable: 'AI 服务暂时不可用，请稍后重试',
        ai_error_endpoint_not_found: 'API 路径未找到，请检查 Base URL 是否填写正确',
        ai_error_forbidden: 'API 访问被拒绝（可能是地区限制或 IP 黑名单）',
        ai_error_bad_request: '请求格式错误，请检查 Base URL 和模型设置',
        ai_error_upstream_error: 'AI 服务返回错误',
        ai_error_network_unreachable: '无法连接到 AI 服务，请检查网络或 Base URL 是否正确',
        ai_error_timeout: 'AI 服务响应超时，请稍后重试',
        ai_error_internal: '测试过程出错，请稍后重试',
        ai_error_invalid_base_url: 'Base URL 格式无效，请检查后重试',
        ai_error_blocked_base_url: '该 Base URL 被安全策略阻止',
        ai_error_request_failed: '连接测试失败，请检查网络后重试',
        ai_error_unknown: '连接测试失败，请检查配置后重试',
        ai_error_messaging_not_enabled: 'Telegram 需要有效订阅',
        ai_base_url_required: '请填写 Base URL',
        ai_no_key: '请至少配置一个 AI 服务',
        ai_no_model: '请先选择或填写模型',
        ai_skipped_hint: '已跳过 AI 配置（可登录后在 Dashboard 中设置）',
        ai_other_option: '其他…（手动输入）',
        ai_free_input_hint: '无法获取模型列表 — 请手动输入模型名',
        more_channels: '更多渠道即将支持（WeChat、LINE 等）',
        setup_sec_plan: '订阅',
        setup_sec_plan_hint: '选择使用方式；已订阅账号可在浏览器中完成绑定',
        setup_sec_ai: 'AI 代理',
        setup_sec_ai_hint: '可选；填写自己的 AI 服务商 API Key 并选择默认操作模式',
        setup_sec_msg: '消息渠道',
        setup_sec_msg_hint: '配置后可通过 Telegram / 微信 / LINE 远程控制桌面',
        telegram_hint: '从 @BotFather 创建 Bot 获取',
      },
      ja: {
        wizard_title: 'KVMind セットアップウィザード',
        wizard_subtitle: '初回設定を完了してください。約2分で完了します',
        step_network: 'ネットワーク',
        step_test: '接続テスト',
        step_subscription: 'プラン・通知',
        step_ai: 'AI 設定',
        step_done: '完了',
        wifi_title: 'WiFiネットワークを選択',
        wifi_desc: 'デバイスはWiFi経由でローカルネットワークに接続します',
        wifi_scan: '🔍 ネットワークをスキャン',
        wifi_scan_hint: '「スキャン」をクリックして利用可能なWiFiを表示',
        wifi_scanning: 'スキャン中…',
        wifi_rescan: '🔍 再スキャン',
        wifi_no_network: 'ネットワークが見つかりません',
        wifi_scan_fail: 'スキャン失敗：',
        wifi_connected: '接続済み',
        wifi_password_label: 'WiFiパスワード',
        wifi_password_placeholder: 'パスワードを入力',
        wifi_password_hint: 'WPA/WPA2パスワード。オープンネットワークの場合は空欄',
        wifi_skip_hint: 'スキップして有線LANを使用することもできます',
        btn_skip: 'スキップ',
        btn_connect_wifi: 'WiFiに接続',
        wifi_connecting: '接続中…',
        wifi_connect_ok: '✓ {ssid}に接続しました、IP: {ip}',
        wifi_connect_fail: '✗ 接続失敗: {msg}',
        wifi_connect_err: '✗ エラー: {msg}',
        test_title: '接続テスト',
        test_desc: 'ネットワーク接続とKVMサービスの状態を確認中',
        test_network: '⏳ ネットワーク接続を確認中…',
        test_pikvm: '⏳ KVMサービスを確認中…',
        test_kvmind: '⏳ KVMindサービスを確認中…',
        test_network_ok: '✓ ネットワーク正常、IP: {ip}',
        test_network_ok2: '✓ ネットワーク接続済み（IP取得中）',
        test_network_fail: '✗ ネットワーク状態を取得できません',
        test_pikvm_ok: '✓ KVMサービス正常',
        test_pikvm_fail: '✗ KVMサービスが応答しません',
        test_pikvm_err: '✗ KVMサービスに接続できません',
        test_kvmind_ok: '✓ KVMindサービス準備完了',
        test_kvmind_warn: '⚠️ KVMind未起動（後で設定可能）',
        test_all_ok: 'すべてのサービスが正常です。続行できます',
        test_partial_fail: '一部のサービスに異常があります。設定を確認してください',
        btn_prev: '← 前へ',
        btn_next: '次へ →',
        ai_title: 'KVMind AI設定',
        ai_desc: '以下の3セクションを順に設定：サブスクリプション、AI エージェント、メッセージチャネル',
        ai_host_label: 'KVMindホストアドレス',
        ai_host_hint: 'KVMindサービスが稼働するホスト（デフォルト: ローカル）',
        ai_port_label: 'ポート',
        ai_apikey_label: 'API Key（任意）',
        ai_apikey_placeholder: '空欄で認証なし',
        ai_mode_label: 'デフォルト操作モード',
        ai_mode_suggest: '💡 提案モード（AIが提案、人間が実行）',
        ai_mode_auto: '⚡ 自動実行モード（AIが自動操作、危険操作は確認）',
        btn_save: '保存して続行 →',
        config_saved: '✓ 設定を保存しました',
        config_deferred: '設定は次回再起動時に反映されます',
        done_title: '最後のステップ：アクセスパスワードの設定',
        done_desc2: 'パスワードを設定すると初期設定が完了し、リモートアクセスでデバイスを制御できます',
        setup_uid_label: 'デバイス UID',
        setup_password_label: 'アクセスパスワードを設定',
        setup_password_confirm: 'パスワード確認',
        setup_password_hint: 'このパスワードはUID経由でリモートアクセスする際のログインに使用します',
        setup_password_short: 'パスワードは8文字以上必要です',
        setup_password_mismatch: 'パスワードが一致しません',
        setup_activating: 'デバイスをアクティベート中…',
        setup_activate_ok: 'デバイスのアクティベーション成功！リダイレクト中…',
        setup_activate_partial: 'パスワード設定完了。クラウド有効化に失敗しましたが、デバイスは正常に使用可能です。',
        setup_activate_fail: 'アクティベーション失敗、ネットワーク接続を確認して再試行してください',
        btn_complete_setup: '初期設定を完了 ✓',
        btn_enter_console: 'コンソールへ →',
        plan_free_title: '無料トライアル',
        plan_free_desc: 'すぐに使える基本AI機能付き',
        plan_sub_title: 'サブスクリプション済み',
        plan_sub_desc: '認証コードを取得してブラウザで紐付け',
        plan_sub_go_activate: 'アクティベーション画面へ →',
        plan_sub_start_free: '無料プランを使う',
        plan_sub_learn_more: 'プランを見る',
        plan_sub_current: '現在のプラン：Free · アカウント未紐付け',
        plan_custom_provider_label: 'AI プロバイダー',
        plan_sub_skipped: '無料プランを選択しました。次に進めます',
        plan_sub_not_activated: '先に Claim コード認証を完了してください（または「無料版を使用」を選択してください）',
        plan_sub_pending_hint: 'サブスクリプションは未認証のため無料版として保存しました。アカウント連携後に自動でアップグレードされます',
        ai_provider_label: 'AIプロバイダー',
        ai_key_label: 'API Key',
        ai_key_hint: 'プロバイダーのコンソールから取得したAPIキー',
        ai_model_label: 'モデル名',
        ai_model_hint: '他のモデルに変更可能',
        ai_test_btn: '🔗 接続テスト',
        ai_testing: 'テスト中…',
        ai_test_ok: '✓ AI接続成功！',
        ai_test_ok_tools: '✓ 接続成功 — 自動実行対応',
        ai_test_ok_suggest: '⚠ 接続成功 — 提案モードのみ（ツール呼び出し非対応）',
        ai_test_fail: '✗ 接続失敗: {msg}',
        ai_error_missing_api_key: 'API Key を入力してください',
        ai_error_invalid_api_key: 'API Key が無効、または取り消されています',
        ai_error_insufficient_quota: 'API Key のクォータまたは残高が不足しています',
        ai_error_invalid_model: 'モデル名が無効です。スペルを確認するか、リストから選び直してください',
        ai_error_rate_limit: 'リクエストが多すぎます。しばらくしてから再試行してください',
        ai_error_upstream_unavailable: 'AI サービスが一時的に利用できません。しばらくしてから再試行してください',
        ai_error_endpoint_not_found: 'API パスが見つかりません。Base URL が正しいか確認してください',
        ai_error_forbidden: 'API アクセスが拒否されました（地域制限または IP 制限の可能性があります）',
        ai_error_bad_request: 'リクエスト形式が正しくありません。Base URL とモデル設定を確認してください',
        ai_error_upstream_error: 'AI サービスからエラーが返されました',
        ai_error_network_unreachable: 'AI サービスに接続できません。ネットワークまたは Base URL を確認してください',
        ai_error_timeout: 'AI サービスの応答がタイムアウトしました。しばらくしてから再試行してください',
        ai_error_internal: 'テスト中にエラーが発生しました。しばらくしてから再試行してください',
        ai_error_invalid_base_url: 'Base URL の形式が正しくありません。確認して再試行してください',
        ai_error_blocked_base_url: 'この Base URL は安全ポリシーによりブロックされています',
        ai_error_request_failed: '接続テストに失敗しました。ネットワークを確認して再試行してください',
        ai_error_unknown: '接続テストに失敗しました。設定を確認して再試行してください',
        ai_error_messaging_not_enabled: 'Telegram には有効なサブスクリプションが必要です',
        ai_base_url_required: 'Base URL を入力してください',
        ai_no_key: '少なくとも1つのAIサービスを設定してください',
        ai_no_model: 'モデルを選択または入力してください',
        ai_skipped_hint: 'AI設定をスキップしました（ログイン後にダッシュボードで設定できます）',
        ai_other_option: 'その他…（手動入力）',
        ai_free_input_hint: 'モデルリストを取得できません — 手動で入力してください',
        more_channels: 'その他のチャネルも近日対応予定（WeChat、LINE など）',
        setup_sec_plan: 'サブスクリプション',
        setup_sec_plan_hint: '利用プランを選択。契約済みアカウントはブラウザで紐付けを完了',
        setup_sec_ai: 'AI エージェント',
        setup_sec_ai_hint: '任意；独自の AI サービス API Key を入力し、操作モードを選択',
        setup_sec_msg: 'メッセージチャネル',
        setup_sec_msg_hint: '設定すると Telegram / WeChat / LINE からデスクトップを遠隔操作可能',
        telegram_hint: '@BotFather でボットを作成して取得',
      },
      en: {
        wizard_title: 'KVMind Setup Wizard',
        wizard_subtitle: 'Complete the initial setup. Takes about 2 minutes.',
        step_network: 'Network',
        step_test: 'Test',
        step_subscription: 'Plan & Msg',
        step_ai: 'AI Config',
        step_done: 'Done',
        wifi_title: 'Select WiFi Network',
        wifi_desc: 'The device will connect to your local network via WiFi',
        wifi_scan: '🔍 Scan Networks',
        wifi_scan_hint: 'Click "Scan Networks" to view available WiFi',
        wifi_scanning: 'Scanning…',
        wifi_rescan: '🔍 Rescan',
        wifi_no_network: 'No networks found',
        wifi_scan_fail: 'Scan failed: ',
        wifi_connected: 'Connected',
        wifi_password_label: 'WiFi Password',
        wifi_password_placeholder: 'Enter password',
        wifi_password_hint: 'WPA/WPA2 password. Leave empty for open networks.',
        wifi_skip_hint: 'You can also skip and use wired Ethernet',
        btn_skip: 'Skip',
        btn_connect_wifi: 'Connect WiFi',
        wifi_connecting: 'Connecting…',
        wifi_connect_ok: '✓ Connected to {ssid}, IP: {ip}',
        wifi_connect_fail: '✗ Connection failed: {msg}',
        wifi_connect_err: '✗ Error: {msg}',
        test_title: 'Connection Test',
        test_desc: 'Verifying network connectivity and KVM service status',
        test_network: '⏳ Checking network…',
        test_pikvm: '⏳ Checking KVM service…',
        test_kvmind: '⏳ Checking KVMind service…',
        test_network_ok: '✓ Network OK, IP: {ip}',
        test_network_ok2: '✓ Network connected (obtaining IP)',
        test_network_fail: '✗ Unable to get network status',
        test_pikvm_ok: '✓ KVM service is running',
        test_pikvm_fail: '✗ KVM service not responding',
        test_pikvm_err: '✗ Cannot connect to KVM service',
        test_kvmind_ok: '✓ KVMind service ready',
        test_kvmind_warn: '⚠️ KVMind not started (can configure later)',
        test_all_ok: 'All services OK. You can continue.',
        test_partial_fail: 'Some services have issues. Please check configuration.',
        btn_prev: '← Back',
        btn_next: 'Next →',
        ai_title: 'KVMind AI Configuration',
        ai_desc: 'Work through the three sections below: Plan, AI Provider, Messaging',
        ai_host_label: 'KVMind Host',
        ai_host_hint: 'Host where KVMind service runs (default: localhost)',
        ai_port_label: 'Port',
        ai_apikey_label: 'API Key (optional)',
        ai_apikey_placeholder: 'Leave empty for no auth',
        ai_mode_label: 'Default Operation Mode',
        ai_mode_suggest: '💡 Suggest Mode (AI suggests, you execute)',
        ai_mode_auto: '⚡ Auto Mode (AI executes, confirms dangerous ops)',
        btn_save: 'Save & Continue →',
        config_saved: '✓ Configuration saved',
        config_deferred: 'Configuration will take effect on next restart',
        done_title: 'Final Step: Set Access Password',
        done_desc2: 'Set a password to complete setup and enable remote access to your device',
        setup_uid_label: 'Device UID',
        setup_password_label: 'Set Access Password',
        setup_password_confirm: 'Confirm Password',
        setup_password_hint: 'This password is used to log in when accessing the device remotely via UID',
        setup_password_short: 'Password must be at least 8 characters',
        setup_password_mismatch: 'Passwords do not match',
        setup_activating: 'Finalizing setup…',
        setup_activate_ok: 'Setup complete! Redirecting…',
        setup_activate_partial: 'Password set. Cloud sync failed — device works locally; online features sync on next connection.',
        setup_activate_fail: 'Setup failed. Please check your network and try again',
        btn_complete_setup: 'Complete Setup ✓',
        btn_enter_console: 'Enter Console →',
        plan_free_title: 'Free Trial',
        plan_free_desc: 'Ready to use with basic AI features',
        plan_sub_title: 'Subscribed',
        plan_sub_desc: 'Get a claim code and complete the account link in the browser',
        plan_sub_go_activate: 'Go to Activation Page →',
        plan_sub_start_free: 'Use Free',
        plan_sub_learn_more: 'Learn about plans',
        plan_sub_current: 'Current plan: Free · Device not linked to any account',
        plan_custom_provider_label: 'AI provider',
        plan_sub_skipped: 'Free plan selected — you can continue',
        plan_sub_not_activated: 'Please finish the claim first (or pick "Use Free")',
        plan_sub_pending_hint: 'Subscription not activated yet — saved as Free for now; entitlements upgrade automatically after binding',
        ai_provider_label: 'AI Provider',
        ai_key_label: 'API Key',
        ai_key_hint: 'API Key from provider console',
        ai_model_label: 'Model Name',
        ai_model_hint: 'Can be changed to another model',
        ai_test_btn: '🔗 Test Connection',
        ai_testing: 'Testing…',
        ai_test_ok: '✓ AI connection successful!',
        ai_test_ok_tools: '✓ Connected — auto-execution supported',
        ai_test_ok_suggest: '⚠ Connected — suggest mode only (model does not support tool calling)',
        ai_test_fail: '✗ Connection failed: {msg}',
        ai_error_missing_api_key: 'Please enter an API Key',
        ai_error_invalid_api_key: 'The API Key is invalid or has been revoked',
        ai_error_insufficient_quota: 'The API Key has insufficient quota or balance',
        ai_error_invalid_model: 'Invalid model name. Check spelling or choose again from the list',
        ai_error_rate_limit: 'Too many requests. Please try again later',
        ai_error_upstream_unavailable: 'The AI service is temporarily unavailable. Please try again later',
        ai_error_endpoint_not_found: 'API path not found. Check whether the Base URL is correct',
        ai_error_forbidden: 'API access was denied, possibly due to region or IP restrictions',
        ai_error_bad_request: 'Bad request. Check the Base URL and model settings',
        ai_error_upstream_error: 'The AI service returned an error',
        ai_error_network_unreachable: 'Cannot connect to the AI service. Check the network or Base URL',
        ai_error_timeout: 'The AI service timed out. Please try again later',
        ai_error_internal: 'An error occurred during the test. Please try again later',
        ai_error_invalid_base_url: 'Invalid Base URL. Please check it and try again',
        ai_error_blocked_base_url: 'This Base URL was blocked by the security policy',
        ai_error_request_failed: 'Connection test failed. Check the network and try again',
        ai_error_unknown: 'Connection test failed. Check the configuration and try again',
        ai_error_messaging_not_enabled: 'Telegram requires an active subscription',
        ai_base_url_required: 'Base URL is required',
        ai_no_key: 'Please configure at least one AI service',
        ai_no_model: 'Please select or type a model first',
        ai_skipped_hint: 'AI config skipped — you can set it up in the Dashboard after signing in',
        ai_other_option: 'Other… (type manually)',
        ai_free_input_hint: "Couldn't load model list — enter the model name manually",
        more_channels: 'More channels coming soon (WeChat, LINE, etc.)',
        setup_sec_plan: 'Plan',
        setup_sec_plan_hint: 'Choose how you use KVMind; subscribed accounts can finish linking in a browser',
        setup_sec_ai: 'AI Provider',
        setup_sec_ai_hint: 'Optional; fill in your own AI provider API key and pick the operation mode',
        setup_sec_msg: 'Messaging',
        setup_sec_msg_hint: 'Configure to control the desktop remotely via Telegram / WeChat / LINE',
        telegram_hint: 'Create a bot with @BotFather to get the token',
      },
    },

    // =======================================================================
    // activate.html
    // =======================================================================
    activate: {
      zh: {
        // 默认 / form 视图文案（applyViewChrome 会按 view 覆盖）
        page_title: '激活设备 · 绑定到账户',
        page_subtitle: '点击下方按钮发起绑定请求，再到 kvmind.com 输入屏幕显示的 6 位码即可完成绑定。',
        // view-driven chrome：标题/副标题/skip 按钮随当前视图切换
        view_form_title: '激活设备 · 绑定到账户',
        view_form_subtitle: '点击下方按钮发起绑定请求，再到 kvmind.com 输入屏幕显示的 6 位码即可完成绑定。',
        view_awaiting_title: '在账户端输入 6 位确认码',
        view_awaiting_subtitle: '请在 kvmind.com/account 打开本设备的绑定请求并输入屏幕显示的 6 位码（10 分钟内有效）。',
        view_incoming_title: '账户请求绑定本设备',
        view_incoming_subtitle: '云端账户发来了绑定本设备的请求，请确认后同意；拒绝若累计过多，该设备会进入冷却期。',
        view_bound_title: '✓ 设备已就绪',
        view_bound_subtitle: '本设备已绑定到账户，权益已激活。可直接进入 KVM 控制台开始使用。',
        cta_enter_kvm: '进入 KVM 控制台',
        label_uid: '设备 UID:',
        label_plan: '当前权益:',
        ent_state: 'Entitlement',
        ent_tunnel: 'Tunnel',
        ent_messaging: 'Messaging',
        ent_ota: 'OTA',
        ent_myclaw: 'MyClaw / 天',
        ent_tasks: '定时任务',
        skip_later: '稍后再说 · 回到 KVM',
        skip_done: '进入 KVM 控制台',
        badge_claimed: '已绑定',
        badge_unclaimed: '未绑定',
        ent_paid: 'Paid',
        ent_claimed_free: 'Claimed Free',
        ent_local_free: 'Local Free',
        val_on: '开启',
        val_off: '关闭',
        loading: '更新中',
      },
      ja: {
        page_title: 'デバイスの認証 · アカウント紐付け',
        page_subtitle: '下のボタンで紐付けリクエストを送信し、kvmind.com で画面に表示される 6 桁のコードを入力してください。',
        view_form_title: 'デバイスの認証 · アカウント紐付け',
        view_form_subtitle: '下のボタンで紐付けリクエストを送信し、kvmind.com で画面に表示される 6 桁のコードを入力してください。',
        view_awaiting_title: 'アカウント側で 6 桁の確認コードを入力',
        view_awaiting_subtitle: 'kvmind.com/account で本デバイスの紐付けリクエストを開き、画面に表示されている 6 桁のコードを入力してください（10 分以内に有効）。',
        view_incoming_title: 'アカウントからの紐付けリクエスト',
        view_incoming_subtitle: 'アカウントがこのデバイスの紐付けを要求しています。確認のうえ承認してください。繰り返し拒否するとクールダウン期間に入ります。',
        view_bound_title: '✓ デバイス準備完了',
        view_bound_subtitle: 'デバイスがアカウントに紐付けられ、権限が有効化されました。KVM コンソールをすぐにご利用いただけます。',
        cta_enter_kvm: 'KVM コンソールへ',
        label_uid: 'デバイス UID:',
        label_plan: '現在の権限:',
        ent_state: '権限',
        ent_tunnel: 'トンネル',
        ent_messaging: 'メッセージング',
        ent_ota: 'OTA',
        ent_myclaw: 'MyClaw / 日',
        ent_tasks: 'タスク',
        skip_later: '後で · KVM に戻る',
        skip_done: 'KVM コンソールへ',
        badge_claimed: '紐付け済み',
        badge_unclaimed: '未紐付け',
        ent_paid: 'Paid',
        ent_claimed_free: 'Claimed Free',
        ent_local_free: 'Local Free',
        val_on: '有効',
        val_off: '無効',
        loading: '更新中…',
      },
      en: {
        page_title: 'Activate Device · Link to Account',
        page_subtitle: 'Tap the button below to start a binding request, then enter the 6-digit code shown on this screen at kvmind.com.',
        view_form_title: 'Activate Device · Link to Account',
        view_form_subtitle: 'Tap the button below to start a binding request, then enter the 6-digit code shown on this screen at kvmind.com.',
        view_awaiting_title: 'Enter the 6-digit code on the account side',
        view_awaiting_subtitle: 'Open the binding request for this device at kvmind.com/account and enter the 6-digit code shown on this screen (valid for 10 minutes).',
        view_incoming_title: 'Account requested to bind this device',
        view_incoming_subtitle: 'A KVMind account is requesting to bind this device. Accept if it\'s yours; repeated declines trigger a cooldown window.',
        view_bound_title: '✓ Device ready',
        view_bound_subtitle: 'Device is linked to your account and entitlements are active. You can enter the KVM console and start using it.',
        cta_enter_kvm: 'Enter KVM console',
        label_uid: 'Device UID:',
        label_plan: 'Current:',
        ent_state: 'Entitlement',
        ent_tunnel: 'Tunnel',
        ent_messaging: 'Messaging',
        ent_ota: 'OTA',
        ent_myclaw: 'MyClaw / day',
        ent_tasks: 'Scheduled Tasks',
        skip_later: 'Skip for now · Back to KVM',
        skip_done: 'Enter KVM console',
        badge_claimed: 'Linked',
        badge_unclaimed: 'Not linked',
        ent_paid: 'Paid',
        ent_claimed_free: 'Claimed Free',
        ent_local_free: 'Local Free',
        val_on: 'On',
        val_off: 'Off',
        loading: 'Loading…',
      },
    },

    // =======================================================================
    // login.html
    // =======================================================================
    login: {
      zh: {
        welcome_back: '欢迎回来', login_subtitle: '请输入设备密码以继续', brand_tagline: 'AI 驱动的远程 KVM 管理平台',
        feat_ai: '🤖 AI 智能控制', feat_remote: '🌐 远程 KVM', feat_secure: '🔒 安全加密', feat_fast: '⚡ 低延迟',
        label_device: '设备:', label_password: '密码', ph_password: '输入设备密码', remember_device: '记住登录 · 7天',
        btn_login: '登录', btn_logging_in: '登录中...', help_link: '帮助', terms_link: '条款',
        err_pw: '请输入密码', err_fail: '登录失败', err_net: '网络错误',
        help_title: 'KVMind 使用帮助', help_login_t: '密码登录',
        help_login_p: '使用设备密码登录。首次使用时请查看设备标签上的初始密码，登录后系统会要求您修改密码。',
        help_forgot_t: '忘记密码', help_forgot_p: '请联系管理员重置设备密码，或通过SSH执行 kvmind-init.sh --force 重新生成。',
        help_support_t: '技术支持',
        terms_title: '服务条款与隐私政策', terms_tos_t: '服务条款',
        terms_tos_p: 'KVMind远程KVM管理服务由观落株式会社提供。使用本服务即表示您同意遵守相关服务条款。',
        terms_privacy_t: '隐私政策', terms_privacy_p: '我们重视您的隐私，仅收集服务运行所需的必要信息。',
        terms_security_t: '数据安全', terms_security_p: '所有远程连接均采用端到端加密，设备控制数据不会存储在云端。',
      },
      ja: {
        welcome_back: 'おかえりなさい', login_subtitle: 'デバイスパスワードを入力してください', brand_tagline: 'AI駆動リモートKVM管理プラットフォーム',
        feat_ai: '🤖 AIスマート制御', feat_remote: '🌐 リモートKVM', feat_secure: '🔒 セキュア暗号化', feat_fast: '⚡ 低遅延',
        label_device: 'デバイス:', label_password: 'パスワード', ph_password: 'デバイスパスワードを入力', remember_device: 'ログインを記憶 · 7日間',
        btn_login: 'ログイン', btn_logging_in: 'ログイン中...', help_link: 'ヘルプ', terms_link: '利用規約',
        err_pw: 'パスワードを入力してください', err_fail: 'ログインに失敗しました', err_net: 'ネットワークエラー',
        help_title: 'KVMind ヘルプ', help_login_t: 'パスワードログイン',
        help_login_p: 'デバイスパスワードでログインします。初回使用時はデバイスラベルの初期パスワードを確認し、ログイン後にパスワード変更が求められます。',
        help_forgot_t: 'パスワードを忘れた場合', help_forgot_p: '管理者にパスワードリセットを依頼するか、SSHで kvmind-init.sh --force を実行して再生成してください。',
        help_support_t: 'テクニカルサポート',
        terms_title: '利用規約とプライバシーポリシー', terms_tos_t: '利用規約',
        terms_tos_p: 'KVMindリモートKVM管理サービスは観落株式会社が提供。本サービスの利用は規約への同意を意味します。',
        terms_privacy_t: 'プライバシーポリシー', terms_privacy_p: 'お客様のプライバシーを重視し、サービス運用に必要な情報のみ収集します。',
        terms_security_t: 'データセキュリティ', terms_security_p: 'すべてのリモート接続はエンドツーエンド暗号化。デバイス制御データはクラウドに保存されません。',
      },
      en: {
        welcome_back: 'Welcome Back', login_subtitle: 'Enter device password to continue', brand_tagline: 'AI-Powered Remote KVM Management',
        feat_ai: '🤖 AI Smart Control', feat_remote: '🌐 Remote KVM', feat_secure: '🔒 Secure Encryption', feat_fast: '⚡ Low Latency',
        label_device: 'Device:', label_password: 'Password', ph_password: 'Enter device password', remember_device: 'Remember login · 7 days',
        btn_login: 'Login', btn_logging_in: 'Logging in...', help_link: 'Help', terms_link: 'Terms',
        err_pw: 'Please enter password', err_fail: 'Login failed', err_net: 'Network error',
        help_title: 'KVMind Help', help_login_t: 'Password Login',
        help_login_p: 'Log in with the device password. On first use, check the initial password on the device label. You will be prompted to change it after login.',
        help_forgot_t: 'Forgot Password', help_forgot_p: 'Contact the administrator to reset, or run kvmind-init.sh --force via SSH to regenerate.',
        help_support_t: 'Technical Support',
        terms_title: 'Terms of Service & Privacy Policy', terms_tos_t: 'Terms of Service',
        terms_tos_p: 'KVMind remote KVM management is provided by Gwanlor Inc. By using this service you agree to our terms.',
        terms_privacy_t: 'Privacy Policy', terms_privacy_p: 'We value your privacy and only collect information necessary to operate the service.',
        terms_security_t: 'Data Security', terms_security_p: 'All remote connections use end-to-end encryption. Device control data is never stored in the cloud.',
      },
    },

    // =======================================================================
    // change-password.html
    // =======================================================================
    change_password: {
      zh: {
        title: '修改设备密码', desc: '首次登录需要修改默认密码。新密码至少8个字符。',
        label_current: '当前密码', ph_current: '输入当前密码', label_new: '新密码', ph_new: '至少8个字符',
        label_confirm: '确认新密码', ph_confirm: '再次输入新密码',
        btn_change: '修改密码', btn_changing: '修改中...', btn_cancel: '取消',
        pw_hint_weak: '弱 — 建议使用更长的密码', pw_hint_medium: '中等', pw_hint_strong: '强', pw_hint_none: '',
        err_old: '请输入当前密码', err_new_short: '新密码至少8个字符', err_mismatch: '两次输入的密码不一致',
        err_same: '新密码不能与当前密码相同', err_net: '网络错误',
        success: '密码已修改，正在跳转...',
      },
      ja: {
        title: 'デバイスパスワード変更', desc: '初回ログイン時はデフォルトパスワードの変更が必要です。8文字以上で設定してください。',
        label_current: '現在のパスワード', ph_current: '現在のパスワードを入力', label_new: '新しいパスワード', ph_new: '8文字以上',
        label_confirm: '新しいパスワード（確認）', ph_confirm: 'もう一度入力',
        btn_change: 'パスワード変更', btn_changing: '変更中...', btn_cancel: 'キャンセル',
        pw_hint_weak: '弱い — より長いパスワードを推奨', pw_hint_medium: '普通', pw_hint_strong: '強い', pw_hint_none: '',
        err_old: '現在のパスワードを入力してください', err_new_short: '新しいパスワードは8文字以上',
        err_mismatch: 'パスワードが一致しません', err_same: '新しいパスワードは現在と異なる必要があります', err_net: 'ネットワークエラー',
        success: 'パスワードが変更されました。リダイレクト中...',
      },
      en: {
        title: 'Change Device Password', desc: 'First login requires changing the default password. New password must be at least 8 characters.',
        label_current: 'Current Password', ph_current: 'Enter current password', label_new: 'New Password', ph_new: 'At least 8 characters',
        label_confirm: 'Confirm New Password', ph_confirm: 'Enter new password again',
        btn_change: 'Change Password', btn_changing: 'Changing...', btn_cancel: 'Cancel',
        pw_hint_weak: 'Weak \u2014 use a longer password', pw_hint_medium: 'Medium', pw_hint_strong: 'Strong', pw_hint_none: '',
        err_old: 'Please enter current password', err_new_short: 'New password must be at least 8 characters',
        err_mismatch: 'Passwords do not match', err_same: 'New password must differ from current', err_net: 'Network error',
        success: 'Password changed. Redirecting...',
      },
    },

    // =======================================================================
    // dashboard.html
    // =======================================================================
    dashboard: {
      zh: {
        title: '📊 仪表板', device: '设备信息', version: '版本', hostname: '主机名', uid: '设备 ID', uptime: '运行时间',
        ai: 'AI 使用', tasksToday: '今日任务', tasksWeek: '本周任务', actionsWeek: '本周操作', errorsWeek: '本周错误',
        health: '系统健康', cpuTemp: 'CPU 温度', memory: '内存', disk: '磁盘',
        recent: '最近活动', refresh: '自动刷新 30s', hours: '小时', loading: '加载中...',
      },
      ja: {
        title: '📊 ダッシュボード', device: 'デバイス情報', version: 'バージョン', hostname: 'ホスト名', uid: 'デバイスID', uptime: '稼働時間',
        ai: 'AI使用状況', tasksToday: '今日のタスク', tasksWeek: '今週のタスク', actionsWeek: '今週の操作', errorsWeek: '今週のエラー',
        health: 'システム健全性', cpuTemp: 'CPU温度', memory: 'メモリ', disk: 'ディスク',
        recent: '最近のアクティビティ', refresh: '自動更新 30秒', hours: '時間', loading: '読み込み中...',
      },
      en: {
        title: '📊 Dashboard', device: 'Device Info', version: 'Version', hostname: 'Hostname', uid: 'Device ID', uptime: 'Uptime',
        ai: 'AI Usage', tasksToday: 'Tasks Today', tasksWeek: 'Tasks This Week', actionsWeek: 'Actions This Week', errorsWeek: 'Errors This Week',
        health: 'System Health', cpuTemp: 'CPU Temp', memory: 'Memory', disk: 'Disk',
        recent: 'Recent Activity', refresh: 'Auto-refresh 30s', hours: 'hours', loading: 'Loading...',
      },
    },

    // =======================================================================
    // kvmind-core.js — 注入到 PiKVM 控制台 /kvm/index.html 的 overlay；命名空间
    // 名字叫 "kvm" 是因为这层 overlay 服务于 PiKVM 控制台。文件本身在 /kdkvm/。
    // =======================================================================
    kvm: {
      zh: {
        snap: '📷 截图', analyse: '🔍 分析', keyboard: '⌨️ 键盘', suggest: '💡 建议', auto: '⚡ 自动',
        terminal: '🖥 终端', settings: '⚙ KVM设置', power: '⏻ 电源', myclaw: '✦ MyClaw',
        powerOn: '🟢 开机', powerOff: '⚫ 关机', restart: '🔄 重启', forceOff: '⚠️ 强制断电',
        connected: 'KVM 已连接', disconnected: '连接断开', aiWorking: 'MyClaw 执行中…', abort: '中断',
        connStatusOk: '已连接 · 画面正常', connStatusNoSignal: '已连接 · 等待画面', connStatusOffline: '连接已断开',
        setTabVideo: '视频', setTabMouse: '鼠标', setTabHID: 'HID', setTabActions: '工具',
        setStreamSection: '流媒体', setStreamMode: '流模式', setStreamModeAuto: '自动', setCodec: '编码',
        setEncodeSection: '视频编码', setH264Bitrate: 'H.264 码率', setH264Gop: 'H.264 GOP',
        setAudioSection: '音频', setVolume: '音量', setAudioHint: 'HDMI 音频仅在 WebRTC 模式可用',
        setPointerSection: '指针', setMouseMode: '鼠标模式', setMouseAbs: '绝对', setMouseRel: '相对',
        setCursorStyle: '光标样式', setCursorNone: '隐藏', setCursorBlue: '蓝点', setCursorCross: '十字', setCursorArrow: '箭头', setCursorHand: '手型',
        setScrollSection: '滚动与移动', setReverseScroll: '反向滚动', setScrollSpeed: '滚动速度', setSensitivity: '灵敏度', setMoveSquash: '移动压缩', setSquashRate: '压缩间隔',
        setKbSection: '键盘', setKbLayout: '键盘布局', setResetHid: '重置 HID',
        setToolsSection: '工具', setActScreenshot: '📷 截图', setActViewLog: '📋 查看日志',
        setMaintSection: '维护', setActResetStream: '🔄 重置视频流',
        pmSuggestTooltip: 'AI 提建议，你确认后执行', pmAutoTooltip: 'AI 直接操作，危险操作仍需确认', pmAutoLockTooltip: '需要 Standard 或 Pro 订阅',
        pfDeviceInfo: '设备信息', pfDeviceUid: '设备 UID', pfCopyUid: '复制 UID', pfPlan: '订阅', pfTechDetails: '技术详情',
        pmSuggest: '建议', pmAuto: '自动',
        qAnalyse: '分析当前状态', qError: '这个报错是什么', qTerminal: '打开终端', qRestart: '重启服务', qDisk: '检查磁盘空间',
        chatPH: '输入指令，例如：\n• 帮我安装 nginx 并配置\n• 这个报错怎么修？\n• 检查磁盘使用情况',
        kbPH: '输入文字发送至远程主机 (Enter发送 · Esc关闭)',
        sendHint: 'Ctrl+↩ 发送',
        clawReady: 'MyClaw AI Ready', clawTry: '试试说：',
        clawEx1: '「帮我检查服务器状态」', clawEx2: '「这个画面有什么问题？」', clawEx3: '「自动帮我安装 nginx」',
        welcomeHint: '📷 点击截图，MyClaw 即可看到当前画面并开始工作',
        kbHint: 'Ctrl+A · Ctrl+C · Ctrl+V', send: '▶ 发送', logout: '退出',
        sysTitle: 'System & Stream', kbTitle: '键盘布局 & 文字输入',
        umProfile: '💻 设备信息', umChangePw: '🔒 修改密码', umDashboard: '📊 仪表盘',
        umProfileUpdate: '💻 设备信息 · ⬆️ 有更新', updateAvailable: '有新版本可用', pfFirmware: '固件版本',
        updateNewVer: '发现新版本', updateBtn: '立即更新', updateInstalling: '正在更新…', updateStarted: '更新已启动',
        updateWait: '更新中，请稍候', updateDone: '✅ 更新完成，即将刷新', updateFailed: '❌ 更新失败',
        umUpgrade: '⚡ 升级订阅', umSubscription: '📋 订阅信息', umTheme: '🌙 主题', umLang: '🌐 语言', umLogout: '🚪 退出登录',
        umClaim: '🔗 查看绑定', umClaimBound: '🔗 查看绑定 · ✓ 已绑定', umClaimUnbound: '🔗 查看绑定 · ⚠ 未绑定', claimModalTitle: '设备 Claim 码', claimRegenerate: '🔄 重置并重新生成',
        upgradeAutoTitle: '自动模式需要升级', upgradeAutoDesc: '自动执行模式需要 Standard 或 Pro 订阅计划。', upgradeAutoBtn: '立即升级 →',
        copy: '📋 复制', copyTitle: '屏幕文字', copyExtracting: '正在提取屏幕文字…', copyToClipboard: '复制到剪贴板',
        copyCopied: '✅ 已复制', copyFailed: '提取失败，请重试',
        wsReconnecting: '连接已断开，正在重连，请稍后重试。若长时间不恢复，请刷新页面。',
        autoToastNoTools: '当前模型不支持工具调用，切换到自动模式后仍会退回建议模式。请在设置中选择支持 Function Calling 的模型。',
        autoToastNoSubscription: '自动模式需要 Standard 或 Pro 订阅。当前设备未订阅，仅可使用建议模式。请前往 kvmind.com 升级。',
        bindBannerPending: '有账户请求绑定本设备，点击前往确认',
        bindBannerHint: '点击前往激活页',
        bindBannerDismiss: '关闭（本次浏览不再提示）',
      },
      ja: {
        snap: '📷 スナップ', analyse: '🔍 分析', keyboard: '⌨️ キーボード', suggest: '💡 提案', auto: '⚡ 自動',
        terminal: '🖥 ターミナル', settings: '⚙ KVM設定', power: '⏻ 電源', myclaw: '✦ MyClaw',
        powerOn: '🟢 電源ON', powerOff: '⚫ 電源OFF', restart: '🔄 再起動', forceOff: '⚠️ 強制OFF',
        connected: 'KVM 接続済み', disconnected: '切断', aiWorking: 'MyClaw 実行中…', abort: '中断',
        connStatusOk: '接続済み · 画面正常', connStatusNoSignal: '接続済み · 信号待ち', connStatusOffline: '接続が切れました',
        setTabVideo: '映像', setTabMouse: 'マウス', setTabHID: 'HID', setTabActions: 'ツール',
        setStreamSection: 'ストリーム', setStreamMode: 'ストリームモード', setStreamModeAuto: '自動', setCodec: 'コーデック',
        setEncodeSection: 'エンコード', setH264Bitrate: 'H.264 ビットレート', setH264Gop: 'H.264 GOP',
        setAudioSection: 'オーディオ', setVolume: '音量', setAudioHint: 'HDMI オーディオは WebRTC モードのみ',
        setPointerSection: 'ポインター', setMouseMode: 'マウスモード', setMouseAbs: '絶対', setMouseRel: '相対',
        setCursorStyle: 'カーソル', setCursorNone: '非表示', setCursorBlue: '青い点', setCursorCross: '十字', setCursorArrow: '矢印', setCursorHand: '手型',
        setScrollSection: 'スクロール / 移動', setReverseScroll: '反転スクロール', setScrollSpeed: 'スクロール速度', setSensitivity: '感度', setMoveSquash: '移動圧縮', setSquashRate: '圧縮間隔',
        setKbSection: 'キーボード', setKbLayout: 'キーボードレイアウト', setResetHid: 'HID をリセット',
        setToolsSection: 'ツール', setActScreenshot: '📷 スクリーンショット', setActViewLog: '📋 ログを見る',
        setMaintSection: 'メンテナンス', setActResetStream: '🔄 ストリームをリセット',
        pmSuggestTooltip: 'AI が提案、確認後に実行', pmAutoTooltip: 'AI が直接実行、危険な操作は確認', pmAutoLockTooltip: 'Standard または Pro プランが必要',
        pfDeviceInfo: 'デバイス情報', pfDeviceUid: 'デバイス UID', pfCopyUid: 'UID をコピー', pfPlan: 'サブスクリプション', pfTechDetails: '技術詳細',
        pmSuggest: '提案', pmAuto: '自動',
        qAnalyse: '現在の状態を分析', qError: 'このエラーは何？', qTerminal: 'ターミナルを開く', qRestart: 'サービスを再起動', qDisk: 'ディスク容量を確認',
        chatPH: 'コマンドを入力…',
        kbPH: 'リモートホストにテキスト送信 (Enter送信 · Esc閉じる)',
        sendHint: 'Ctrl+↩ 送信',
        clawReady: 'MyClaw AI Ready', clawTry: '試してみてください：',
        clawEx1: '「サーバーの状態を確認して」', clawEx2: '「この画面に問題は？」', clawEx3: '「nginx を自動インストール」',
        welcomeHint: '📷 スクリーンショットをクリック',
        kbHint: 'Ctrl+A · Ctrl+C · Ctrl+V', send: '▶ 送信', logout: 'ログアウト',
        sysTitle: 'System & Stream', kbTitle: 'キーボード & テキスト入力',
        umProfile: '💻 デバイス情報', umChangePw: '🔒 パスワード変更', umDashboard: '📊 ダッシュボード',
        umProfileUpdate: '💻 デバイス情報 · ⬆️ 更新あり', updateAvailable: 'アップデートがあります', pfFirmware: 'ファームウェア',
        updateNewVer: '新バージョンがあります', updateBtn: '今すぐ更新', updateInstalling: '更新中…', updateStarted: '更新開始',
        updateWait: '更新中、お待ちください', updateDone: '✅ 更新完了、リロードします', updateFailed: '❌ 更新失敗',
        umUpgrade: '⚡ プラン昇級', umSubscription: '📋 サブスク情報', umTheme: '🌙 テーマ', umLang: '🌐 言語', umLogout: '🚪 ログアウト',
        umClaim: '🔗 紐付け状況', umClaimBound: '🔗 紐付け状況 · ✓ 紐付け済み', umClaimUnbound: '🔗 紐付け状況 · ⚠ 未紐付け', claimModalTitle: 'デバイス Claim コード', claimRegenerate: '🔄 リセットして再生成',
        upgradeAutoTitle: '自動モードにはアップグレードが必要', upgradeAutoDesc: '自動実行モードには Standard または Pro プランが必要です。', upgradeAutoBtn: 'アップグレード →',
        copy: '📋 コピー', copyTitle: '画面テキスト', copyExtracting: 'テキスト抽出中…', copyToClipboard: 'クリップボードにコピー',
        copyCopied: '✅ コピーしました', copyFailed: '抽出に失敗しました',
        wsReconnecting: '接続が切れました。再接続中です。少し待ってもう一度お試しください。改善しない場合はページを更新してください。',
        autoToastNoTools: '現在のモデルはツール呼び出し非対応のため、自動モードに切り替えても提案モードに戻ります。設定で Function Calling 対応モデルを選択してください。',
        autoToastNoSubscription: '自動モードには Standard または Pro プランが必要です。本デバイスは未契約のため提案モードのみご利用いただけます。kvmind.com からアップグレードしてください。',
        bindBannerPending: 'アカウントからの紐付けリクエストがあります。クリックして確認',
        bindBannerHint: 'クリックでアクティベーション画面へ',
        bindBannerDismiss: '閉じる（このセッションでは再表示しない）',
      },
      en: {
        snap: '📷 Snap', analyse: '🔍 Analyse', keyboard: '⌨️ Keyboard', suggest: '💡 Suggest', auto: '⚡ Auto',
        terminal: '🖥 Terminal', settings: '⚙ KVM Settings', power: '⏻ Power', myclaw: '✦ MyClaw',
        powerOn: '🟢 Power On', powerOff: '⚫ Power Off', restart: '🔄 Restart', forceOff: '⚠️ Force Off',
        connected: 'KVM Connected', disconnected: 'Disconnected', aiWorking: 'MyClaw working…', abort: 'Abort',
        connStatusOk: 'Connected · Live', connStatusNoSignal: 'Connected · Waiting for signal', connStatusOffline: 'Disconnected',
        setTabVideo: 'Video', setTabMouse: 'Mouse', setTabHID: 'HID', setTabActions: 'Tools',
        setStreamSection: 'Streaming', setStreamMode: 'Stream mode', setStreamModeAuto: 'Auto', setCodec: 'Codec',
        setEncodeSection: 'Video encoding', setH264Bitrate: 'H.264 bitrate', setH264Gop: 'H.264 GOP',
        setAudioSection: 'Audio', setVolume: 'Volume', setAudioHint: 'HDMI audio is available only in WebRTC mode',
        setPointerSection: 'Pointer', setMouseMode: 'Mouse mode', setMouseAbs: 'Absolute', setMouseRel: 'Relative',
        setCursorStyle: 'Cursor style', setCursorNone: 'Hidden', setCursorBlue: 'Blue dot', setCursorCross: 'Crosshair', setCursorArrow: 'Arrow', setCursorHand: 'Hand',
        setScrollSection: 'Scroll & motion', setReverseScroll: 'Reverse scroll', setScrollSpeed: 'Scroll speed', setSensitivity: 'Sensitivity', setMoveSquash: 'Move squash', setSquashRate: 'Squash rate',
        setKbSection: 'Keyboard', setKbLayout: 'Keyboard layout', setResetHid: 'Reset HID',
        setToolsSection: 'Tools', setActScreenshot: '📷 Screenshot', setActViewLog: '📋 View Log',
        setMaintSection: 'Maintenance', setActResetStream: '🔄 Reset Stream',
        pmSuggestTooltip: 'AI suggests, you confirm before execution', pmAutoTooltip: 'AI executes directly, risky actions still confirmed', pmAutoLockTooltip: 'Requires Standard or Pro plan',
        pfDeviceInfo: 'Device Info', pfDeviceUid: 'Device UID', pfCopyUid: 'Copy UID', pfPlan: 'Plan', pfTechDetails: 'Technical details',
        pmSuggest: 'Suggest', pmAuto: 'Auto',
        qAnalyse: 'Analyze status', qError: "What's this error", qTerminal: 'Open terminal', qRestart: 'Restart service', qDisk: 'Check disk space',
        chatPH: 'Enter command, e.g.:\n• Install and configure nginx\n• How to fix this error?\n• Check disk usage',
        kbPH: 'Type text to send (Enter send · Esc close)',
        sendHint: 'Ctrl+↩ Send',
        clawReady: 'MyClaw AI Ready', clawTry: 'Try saying:',
        clawEx1: '\u201cCheck my server status\u201d', clawEx2: '\u201cWhat\u2019s wrong with this screen?\u201d', clawEx3: '\u201cAuto-install nginx for me\u201d',
        welcomeHint: '📷 Click screenshot to start',
        kbHint: 'Ctrl+A · Ctrl+C · Ctrl+V', send: '▶ Send', logout: 'Logout',
        sysTitle: 'System & Stream', kbTitle: 'Keyboard & Text Input',
        umProfile: '💻 Device Info', umChangePw: '🔒 Change Password', umDashboard: '📊 Dashboard',
        umProfileUpdate: '💻 Device Info · ⬆️ Update', updateAvailable: 'Update available', pfFirmware: 'Firmware',
        updateNewVer: 'New version available', updateBtn: 'Update Now', updateInstalling: 'Updating…', updateStarted: 'Update started',
        updateWait: 'Updating, please wait', updateDone: '✅ Update complete, reloading', updateFailed: '❌ Update failed',
        umUpgrade: '⚡ Upgrade', umSubscription: '📋 Subscription', umTheme: '🌙 Theme', umLang: '🌐 Language', umLogout: '🚪 Logout',
        umClaim: '🔗 View binding', umClaimBound: '🔗 View binding · ✓ Bound', umClaimUnbound: '🔗 View binding · ⚠ Not bound', claimModalTitle: 'Device Claim Code', claimRegenerate: '🔄 Reset & Regenerate',
        upgradeAutoTitle: 'Auto mode requires upgrade', upgradeAutoDesc: 'Auto execution mode requires a Standard or Pro subscription.', upgradeAutoBtn: 'Upgrade now →',
        copy: '📋 Copy', copyTitle: 'Screen Text', copyExtracting: 'Extracting text…', copyToClipboard: 'Copy to Clipboard',
        copyCopied: '✅ Copied!', copyFailed: 'Extraction failed, please retry',
        wsReconnecting: 'Connection lost \u2014 reconnecting. Please try again in a moment; if it keeps failing, refresh the page.',
        autoToastNoTools: 'Current model does not support tool calling; auto mode will fall back to suggest. Pick a model that supports Function Calling in Settings.',
        autoToastNoSubscription: 'Auto mode requires a Standard or Pro subscription. This device is not subscribed and can only use Suggest mode. Upgrade at kvmind.com.',
        bindBannerPending: 'A binding request is waiting \u2014 click to confirm',
        bindBannerHint: 'Open activation page',
        bindBannerDismiss: 'Dismiss (won\'t reappear in this session)',
      },
    },
  };

  // Legacy-shaped dict: kvmd settings menu translated by English original string.
  // Kept separate from DICTS because lookup is keyed by the English string itself,
  // not a symbolic key. Migrated verbatim from kvmind-core.js KVMIND_KVM_I18N.
  var KVMD_SETTINGS = {
    zh: {
      'Runtime settings & tools': '运行时设置与工具', 'Resolution:': '分辨率:', 'JPEG quality:': 'JPEG 质量:', 'JPEG max fps:': 'JPEG 最大帧率:',
      'H.264 kbps:': 'H.264 kbps:', 'H.264 gop:': 'H.264 gop:', 'Video mode': '视频模式', 'Orientation:': '方向:', 'Default': '默认',
      'Audio volume:': '音量:', 'Microphone:': '麦克风:', 'Show stream': '显示视频流', 'Screenshot': '截图', 'Reset stream': '重置视频流',
      'Keyboard mode:': '键盘模式:', 'Mouse mode': '鼠标模式', 'Keyboard & mouse (HID) settings': '键盘与鼠标 (HID) 设置',
      'Swap Left Ctrl and Caps keys:': '交换左Ctrl和Caps键:', 'Mouse polling:': '鼠标轮询率:', 'Relative sensitivity:': '相对灵敏度:',
      'Squash relative moves:': '压缩相对移动:', 'Reverse scrolling:': '反向滚动:', 'Cumulative scrolling:': '累积滚动:', 'Scroll rate:': '滚动速率:',
      'Show the blue dot:': '显示蓝色光标点:', 'Show local cursor:': '显示本地光标:',
      'Web UI settings': 'Web UI 设置', 'Ask page close confirmation:': '关闭页面时确认:', 'Expand for the entire tab by default:': '默认全屏展开:',
      'Bad link mode (release keys immediately):': '弱连接模式(立即释放按键):', 'Connect HID to Server:': 'HID连接服务器:',
      'Mouse jiggler': '鼠标防睡', 'Mute all input HID events:': '静音所有HID输入:', 'Connect main USB to Server:': '主USB连接服务器:',
      'Enable locator LED:': '启用定位 LED:', 'Reset HID': '重置HID', 'Show keyboard': '显示键盘',
      'Paste text as keypress sequence': '粘贴文字为按键序列',
      'Please note that KVMind cannot switch the keyboard layout': '注意: KVMind 无法切换键盘布局',
      'Slow typing:': '慢速输入:', 'Hide input text:': '隐藏输入文字:', 'Ask paste confirmation:': '粘贴时确认:',
      'using host keymap': '使用主机键位映射',
      'Video Settings': '视频设置', 'Stream mode:': '流模式:', 'sm-auto': '自动', 'sm-webrtc': 'WebRTC', 'sm-h264': 'H.264', 'sm-mjpeg': 'MJPEG',
      'audio-hint': 'HDMI 音频仅在 WebRTC 模式下可用', 'Codec:': '编码:', '🎬 Video': '🎬 视频',
      'Mouse Settings': '鼠标设置', 'Cursor style:': '光标样式:',
      'cs-none': '隐藏', 'cs-blue-dot': '蓝点', 'cs-crosshair': '十字', 'cs-default': '箭头', 'cs-pointer': '手型',
      'Mouse mode:': '鼠标模式:', 'mm-absolute': '绝对', 'mm-relative': '相对',
      'Reverse scroll:': '反向滚动:', 'Scroll speed:': '滚动速度:', 'Sensitivity:': '灵敏度:', 'Move squash:': '移动压缩:', 'Squash rate:': '压缩间隔:',
      'Actions': '操作', 'Reset Stream': '重置视频流', 'View Log': '查看日志',
      '🖱 Mouse': '🖱 鼠标', '⚙ Actions': '⚙ 操作', '⌨ HID': '⌨ HID', 'Keyboard layout:': '键盘布局:',
    },
    ja: {
      'Runtime settings & tools': 'ランタイム設定とツール', 'Resolution:': '解像度:', 'JPEG quality:': 'JPEG 品質:', 'JPEG max fps:': 'JPEG 最大fps:',
      'H.264 kbps:': 'H.264 kbps:', 'H.264 gop:': 'H.264 gop:', 'Video mode': 'ビデオモード', 'Orientation:': '向き:', 'Default': 'デフォルト',
      'Audio volume:': '音量:', 'Microphone:': 'マイク:', 'Show stream': 'ストリーム表示', 'Screenshot': 'スクリーンショット', 'Reset stream': 'ストリームリセット',
      'Keyboard mode:': 'キーボードモード:', 'Mouse mode': 'マウスモード', 'Keyboard & mouse (HID) settings': 'キーボードとマウス (HID) 設定',
      'Swap Left Ctrl and Caps keys': '左CtrlとCapsを入れ替え:', 'Mouse polling:': 'マウスポーリング:', 'Relative sensitivity:': '相対感度:',
      'Squash relative moves:': '相対移動を圧縮:', 'Reverse scrolling:': 'スクロール反転:', 'Cumulative scrolling:': '累積スクロール:', 'Scroll rate:': 'スクロール速度:',
      'Show the blue dot:': '青いドットを表示:', 'Show local cursor:': 'ローカルカーソル表示:',
      'Web UI settings': 'Web UI 設定', 'Ask page close confirmation:': 'ページ閉じる時に確認:', 'Expand for the entire tab by default:': 'デフォルトで全画面:',
      'Bad link mode (release keys immediately):': '不安定接続モード:', 'Connect HID to Server:': 'HIDをサーバーに接続:',
      'Mouse jiggler': 'マウスジグラー', 'Mute all input HID events:': '全HID入力をミュート:', 'Connect main USB to Server:': 'メインUSBをサーバーに接続:',
      'Enable locator LED:': 'ロケーターLED:', 'Reset HID': 'HIDリセット', 'Show keyboard': 'キーボード表示',
      'Paste text as keypress sequence': 'テキストをキー入力として貼り付け',
      'Please note that KVMind cannot switch the keyboard layout': 'KVMindはキーボードレイアウトを切り替えられません',
      'Slow typing:': '低速入力:', 'Hide input text:': '入力テキストを隠す:', 'Ask paste confirmation:': '貼り付け時に確認:',
      'using host keymap': 'ホストキーマップ使用',
      'Video Settings': 'ビデオ設定', 'Stream mode:': 'ストリームモード:', 'sm-auto': '自動', 'sm-webrtc': 'WebRTC', 'sm-h264': 'H.264', 'sm-mjpeg': 'MJPEG',
      'audio-hint': 'HDMI音声はWebRTCモードのみ', 'Codec:': 'コーデック:', '🎬 Video': '🎬 ビデオ',
      'Mouse Settings': 'マウス設定', 'Cursor style:': 'カーソルスタイル:',
      'cs-none': '非表示', 'cs-blue-dot': '青ドット', 'cs-crosshair': '十字', 'cs-default': '矢印', 'cs-pointer': '指型',
      'Mouse mode:': 'マウスモード:', 'mm-absolute': '絶対', 'mm-relative': '相対',
      'Reverse scroll:': 'スクロール反転:', 'Scroll speed:': 'スクロール速度:', 'Sensitivity:': '感度:', 'Move squash:': '移動圧縮:', 'Squash rate:': '圧縮間隔:',
      'Actions': '操作', 'Reset Stream': 'ストリームリセット', 'View Log': 'ログ表示',
      '🖱 Mouse': '🖱 マウス', '⚙ Actions': '⚙ 操作', '⌨ HID': '⌨ HID', 'Keyboard layout:': 'キーボードレイアウト:',
    },
    en: {
      'Video Settings': 'Video Settings', 'Stream mode:': 'Stream mode:', 'sm-auto': 'Auto', 'sm-webrtc': 'WebRTC', 'sm-h264': 'H.264', 'sm-mjpeg': 'MJPEG',
      'Audio volume:': 'Audio volume:', 'audio-hint': 'HDMI audio only available in WebRTC mode', 'Codec:': 'Codec:',
      'H.264 kbps:': 'H.264 kbps:', 'H.264 gop:': 'H.264 gop:', '🎬 Video': '🎬 Video',
      'Mouse Settings': 'Mouse Settings', 'Cursor style:': 'Cursor style:',
      'cs-none': 'None', 'cs-blue-dot': 'Blue Dot', 'cs-crosshair': 'Crosshair', 'cs-default': 'Arrow', 'cs-pointer': 'Hand',
      'Mouse mode:': 'Mouse mode:', 'mm-absolute': 'Absolute', 'mm-relative': 'Relative',
      'Reverse scroll:': 'Reverse scroll:', 'Scroll speed:': 'Scroll speed:', 'Sensitivity:': 'Sensitivity:', 'Move squash:': 'Move squash:', 'Squash rate:': 'Squash rate:',
      'Actions': 'Actions', 'Reset Stream': 'Reset Stream', 'Screenshot': 'Screenshot', 'View Log': 'View Log',
      '🖱 Mouse': '🖱 Mouse', '⚙ Actions': '⚙ Actions', '⌨ HID': '⌨ HID', 'Keyboard layout:': 'Keyboard layout:', 'Reset HID': 'Reset HID',
      'Runtime settings & tools': 'Runtime settings & tools', 'Resolution:': 'Resolution:', 'JPEG quality:': 'JPEG quality:', 'JPEG max fps:': 'JPEG max fps:',
      'Video mode': 'Video mode', 'Orientation:': 'Orientation:', 'Default': 'Default', 'Microphone:': 'Microphone:',
      'Show stream': 'Show stream', 'Reset stream': 'Reset stream',
      'Keyboard mode:': 'Keyboard mode:', 'Mouse mode': 'Mouse mode', 'Keyboard & mouse (HID) settings': 'Keyboard & mouse (HID) settings',
      'Swap Left Ctrl and Caps keys:': 'Swap Left Ctrl and Caps keys:', 'Mouse polling:': 'Mouse polling:', 'Relative sensitivity:': 'Relative sensitivity:',
      'Squash relative moves:': 'Squash relative moves:', 'Reverse scrolling:': 'Reverse scrolling:', 'Cumulative scrolling:': 'Cumulative scrolling:', 'Scroll rate:': 'Scroll rate:',
      'Show the blue dot:': 'Show the blue dot:', 'Show local cursor:': 'Show local cursor:',
      'Web UI settings': 'Web UI settings', 'Ask page close confirmation:': 'Ask page close confirmation:', 'Expand for the entire tab by default:': 'Expand for the entire tab by default:',
      'Bad link mode (release keys immediately):': 'Bad link mode (release keys immediately):', 'Connect HID to Server:': 'Connect HID to Server:',
      'Mouse jiggler': 'Mouse jiggler', 'Mute all input HID events:': 'Mute all input HID events:', 'Connect main USB to Server:': 'Connect main USB to Server:',
      'Enable locator LED:': 'Enable locator LED:', 'Show keyboard': 'Show keyboard', 'Paste text as keypress sequence': 'Paste text as keypress sequence',
      'Please note that KVMind cannot switch the keyboard layout': 'Please note that KVMind cannot switch the keyboard layout',
      'Slow typing:': 'Slow typing:', 'Hide input text:': 'Hide input text:', 'Ask paste confirmation:': 'Ask paste confirmation:',
      'using host keymap': 'using host keymap',
    },
  };

  // Keys whose i18n values are trusted HTML (injected via innerHTML).
  // Currently empty — add here if a translation needs <a> / <b> tags.
  var HTML_SAFE_KEYS = {};

  // ── runtime state (per page) ─────────────────────────────────────────────
  var _page = null;       // which namespace to read from by default
  var _lang = 'zh';       // current language (zh|ja|en)
  var _listeners = [];    // langchange callbacks

  function detectLang() {
    try {
      var saved = localStorage.getItem('kvmind_lang');
      if (saved && DICTS.setup[saved]) return saved;
    } catch (e) { /* localStorage unavailable */ }
    var nav = (navigator.language || '').toLowerCase();
    if (nav.indexOf('zh') === 0) return 'zh';
    if (nav.indexOf('ja') === 0) return 'ja';
    return 'en';
  }

  function interpolate(tpl, vars) {
    if (!vars || typeof tpl !== 'string') return tpl;
    for (var k in vars) {
      if (Object.prototype.hasOwnProperty.call(vars, k)) {
        tpl = tpl.split('{' + k + '}').join(vars[k]);
      }
    }
    return tpl;
  }

  function lookup(page, lang, key) {
    var ns = DICTS[page];
    if (!ns) return null;
    var dict = ns[lang] || ns.zh || ns.en;
    if (!dict) return null;
    return Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : null;
  }

  /**
   * @param {string} key
   * @param {object} [vars]       interpolation map (e.g. {min:9,sec:40})
   * @param {string} [pageOverride]  optional namespace override (e.g. 'widget')
   * @returns {string}            translated text, or the key itself on miss
   */
  function t(key, vars, pageOverride) {
    var page = pageOverride || _page;
    if (!page) return key;
    var v = lookup(page, _lang, key);
    if (v == null) v = lookup(page, 'en', key);   // fall back to English for missing zh/ja
    if (v == null) return key;                    // last resort: return key verbatim
    return interpolate(v, vars);
  }

  function applyDOM(root, pageOverride) {
    var scope = root || document;
    var page = pageOverride || _page;
    // Plain text replacement — host namespace.
    if (page) {
      var nodes = scope.querySelectorAll('[data-i18n]');
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var key = el.getAttribute('data-i18n');
        var text = lookup(page, _lang, key);
        if (text == null) text = lookup(page, 'en', key);
        if (text == null) continue;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          el.placeholder = text;
        } else if (HTML_SAFE_KEYS[key]) {
          el.innerHTML = text;
        } else {
          el.textContent = text;
        }
      }
      // Explicit placeholder-only attribute (some pages mark placeholders separately).
      var phNodes = scope.querySelectorAll('[data-i18n-ph]');
      for (var j = 0; j < phNodes.length; j++) {
        var pel = phNodes[j];
        var pkey = pel.getAttribute('data-i18n-ph');
        var ptext = lookup(page, _lang, pkey);
        if (ptext == null) ptext = lookup(page, 'en', pkey);
        if (ptext != null) pel.placeholder = ptext;
      }
    }
    // Widget namespace (data-kv-i18n) — always resolved in 'widget' namespace
    // regardless of host page, so the shared activation widget renders correctly.
    var kvNodes = scope.querySelectorAll('[data-kv-i18n]');
    for (var w = 0; w < kvNodes.length; w++) {
      var kel = kvNodes[w];
      var kkey = kel.getAttribute('data-kv-i18n');
      var ktext = lookup('widget', _lang, kkey);
      if (ktext == null) ktext = lookup('widget', 'en', kkey);
      if (ktext == null) continue;
      kel.textContent = ktext;
    }
    // Toggle .active on language buttons whose label matches the current language.
    var labels = { zh: '中文', ja: '日本語', en: 'EN' };
    var langBtns = scope.querySelectorAll('.lang-btn');
    for (var b = 0; b < langBtns.length; b++) {
      var btn = langBtns[b];
      btn.classList.toggle('active', btn.textContent.trim() === labels[_lang]);
    }
  }

  function setLang(lang) {
    if (!DICTS.setup[lang]) return;        // guard against unknown langs
    _lang = lang;
    try { localStorage.setItem('kvmind_lang', lang); } catch (e) { /* ignore */ }
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : lang;
    applyDOM();
    for (var i = 0; i < _listeners.length; i++) {
      try { _listeners[i](lang); } catch (e) { console.warn('[kvmind-i18n] listener error:', e); }
    }
  }

  function onLangChange(cb) {
    if (typeof cb === 'function') _listeners.push(cb);
  }

  function init(page) {
    _page = page;
    _lang = detectLang();
    document.documentElement.lang = _lang === 'zh' ? 'zh-CN' : _lang;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { applyDOM(); });
    } else {
      applyDOM();
    }
  }

  /**
   * Translate a kvmd-style settings menu where keys are the ENGLISH original text
   * (not symbolic). Returns null if no match, so callers can keep the original.
   */
  function translateKvmdSetting(englishText) {
    if (!englishText) return null;
    var dict = KVMD_SETTINGS[_lang];
    if (!dict) return null;
    return Object.prototype.hasOwnProperty.call(dict, englishText) ? dict[englishText] : null;
  }

  global.KVMindI18n = {
    init: init,
    t: t,
    setLang: setLang,
    getLang: function () { return _lang; },
    applyDOM: applyDOM,
    onLangChange: onLangChange,
    translateKvmdSetting: translateKvmdSetting,
    _dicts: DICTS,
    _kvmdSettings: KVMD_SETTINGS,
  };
})(typeof window !== 'undefined' ? window : this);
