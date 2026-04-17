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
  // Constants
  // =========================================================================

  var PANEL_WIDTH = 400;       // Total panel width (px)
  var SIDEBAR_WIDTH = 45;      // Sidebar nav width (px)

  // =========================================================================
  // CSS
  // =========================================================================

  var CSS = [
    // Layout overrides
    "#kvmind-chat-panel:not(.collapsed) { width: " + PANEL_WIDTH + "px !important }",
    "#stream-window { right: " + PANEL_WIDTH + "px !important }",
    "#kvmind-log-bar { right: " + PANEL_WIDTH + "px !important }",
    "body.kvmind-panel-collapsed #stream-window { right: 0 !important }",
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
    "  width: 100%; padding: 7px 10px; font-size: 13px; border-radius: 6px;",
    "  border: 1px solid var(--kvborder); background: var(--kvsurface2); color: var(--kvtext);",
    "  outline: none; font-family: inherit;",
    "}",
    ".kv-set-input:focus, .kv-set-select:focus { border-color: var(--kvaccent) }",
    ".kv-set-input-wrap { position: relative }",
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

  var _SB_I18N = {
    zh: { chat: "\u804A\u5929", tasks: "\u4EFB\u52A1", settings: "MyClaw\u8BBE\u7F6E" },
    ja: { chat: "\u30C1\u30E3\u30C3\u30C8", tasks: "\u30BF\u30B9\u30AF", settings: "MyClaw\u8A2D\u5B9A" },
    en: { chat: "Chat", tasks: "Tasks", settings: "MyClaw Settings" }
  };
  var _sbLang = localStorage.getItem("kvmind_lang") || "zh";
  var _sbL = _SB_I18N[_sbLang] || _SB_I18N.en;

  var SIDEBAR_BUTTONS = [
    { id: "chat",     icon: "\uD83D\uDCAC", title: _sbL.chat,     active: true  },
    { id: "tasks",    icon: "\uD83D\uDCCB", title: _sbL.tasks,    active: false },
    { id: "_spacer" },
    { id: "settings", icon: "\u2699\uFE0F", title: _sbL.settings, active: false },
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
    var L = _setL;

    var emptyHTML = '<div class="kvmind-task-empty">\u6682\u65E0\u4EFB\u52A1\u3002<br>\u901A\u8FC7\u804A\u5929\u8BA9 MyClaw \u521B\u5EFA\u5B9A\u65F6\u4EFB\u52A1\u3002</div>';

    fetch("/kdkvm/api/tasks", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var jobs = data.jobs || data || [];
        if (!Array.isArray(jobs) || jobs.length === 0) { list.innerHTML = emptyHTML; return; }

        list.innerHTML = "";
        jobs.forEach(function (job) {
          var name  = job.name || job.command || job.id || "\u672A\u547D\u540D\u4EFB\u52A1";
          var rawSched = job.schedule || {};
          var sched = "";
          if (typeof rawSched === "string") { sched = rawSched; }
          else if (rawSched.kind === "every" && rawSched.every_ms) {
            var sec = rawSched.every_ms / 1000;
            sched = sec >= 60 ? "\u6BCF" + (sec/60) + "\u5206\u949F" : "\u6BCF" + sec + "\u79D2";
          } else if (rawSched.kind === "cron" && rawSched.expr) { sched = rawSched.expr; }
          else { sched = JSON.stringify(rawSched); }
          var on    = job.enabled !== false;
          var item  = createEl("div", { className: "kvmind-task-item" });
          var nameEl=createEl("div",{className:"name"});nameEl.textContent=name;item.appendChild(nameEl);
          if(sched){var schedEl=createEl("div",{className:"schedule"});schedEl.textContent="\u23F0 "+sched;item.appendChild(schedEl);}
          var statusEl=createEl("div",{className:"status "+(on?"enabled":"disabled")});statusEl.textContent=on?"\u25CF \u542F\u7528":"\u25CB \u7981\u7528";item.appendChild(statusEl);
          // Tracking meta
          var meta = createEl("div", { className: "kvmind-task-meta" });
          var parts = [];
          if (job.run_count > 0) parts.push(L.task_runs.replace("{n}", job.run_count));
          if (job.last_run_at) {
            var ago = Math.floor((Date.now()/1000 - job.last_run_at) / 60);
            parts.push(L.task_last + (ago < 1 ? "just now" : ago + "m ago"));
          }
          if (parts.length) { meta.textContent = parts.join(" \u00B7 "); item.appendChild(meta); }
          // Action buttons
          var acts = createEl("div", { className: "kvmind-task-actions" });
          var toggleBtn = createEl("button"); toggleBtn.textContent = L.task_toggle;
          toggleBtn.onclick = function(e) { e.stopPropagation(); fetch("/kdkvm/api/tasks/" + job.id + "/toggle", {method:"POST", credentials:"same-origin"}).then(function(){ loadTasks(); }).catch(function(err){console.warn("Task toggle error:",err);}); };
          var delBtn = createEl("button", { className: "del" }); delBtn.textContent = L.task_delete;
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
    var taskHeader = createEl("div", { id: "kvmind-task-header", textContent: "\uD83D\uDCCB \u4EFB\u52A1\u7BA1\u7406" });
    var taskList = createEl("div", { id: "kvmind-task-list" });
    var taskEmpty = createEl("div", { className: "kvmind-task-empty" });
    taskEmpty.appendChild(document.createTextNode("\u6682\u65E0\u4EFB\u52A1\u3002"));
    taskEmpty.appendChild(document.createElement("br"));
    taskEmpty.appendChild(document.createTextNode("\u901A\u8FC7\u804A\u5929\u8BA9 MyClaw \u521B\u5EFA\u5B9A\u65F6\u4EFB\u52A1\u3002"));
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
      panel.style.width = w + "px";
      // Update stream area and related elements
      var streamArea = document.getElementById("kvmind-stream-area");
      if (streamArea) streamArea.style.right = w + "px";
      var logBar = document.getElementById("kvmind-log-bar");
      if (logBar) logBar.style.right = w + "px";
      var webterm = document.getElementById("webterm-window");
      if (webterm && !webterm.classList.contains("kvmind-hidden")) webterm.style.right = w + "px";
    }

    var dragging = false;
    resizeHandle.addEventListener("mousedown", function (e) {
      e.preventDefault();
      e.stopImmediatePropagation();
      dragging = true;
      resizeHandle.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      function onMove(ev) {
        if (!dragging) return;
        var newW = window.innerWidth - ev.clientX;
        if (newW < PANEL_MIN) newW = PANEL_MIN;
        if (newW > PANEL_MAX) newW = PANEL_MAX;
        applyPanelWidth(newW);
      }
      function onUp() {
        dragging = false;
        resizeHandle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        var finalW = parseInt(panel.style.width, 10);
        if (finalW >= PANEL_MIN && finalW <= PANEL_MAX) {
          localStorage.setItem("kvmind_panel_width", String(finalW));
        }
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
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

    console.log("[sidebar-patch v5] injected");
  }

  // =========================================================================
  // Settings: i18n
  // =========================================================================

  var _SET_I18N = {
    zh: {
      hd: "\u2699\uFE0F MyClaw \u8BBE\u7F6E",
      g_ai: "\uD83E\uDD16 AI \u670D\u52A1", g_ch: "\uD83D\uDCF1 \u6D88\u606F\u901A\u9053", g_pref: "\uD83C\uDF10 \u8BED\u8A00\u4E0E\u6A21\u5F0F",
      provider: "AI \u670D\u52A1\u5546", model: "\u6A21\u578B", test: "\uD83D\uDD17 \u6D4B\u8BD5\u8FDE\u63A5",
      testing: "\u6D4B\u8BD5\u4E2D...", test_ok: "\u2705 \u8FDE\u63A5\u6210\u529F", test_ok_tools: "\u2705 \u8FDE\u63A5\u6210\u529F \u2014 \u652F\u6301\u81EA\u52A8\u6267\u884C", test_ok_suggest: "\u26A0 \u8FDE\u63A5\u6210\u529F \u2014 \u4EC5\u5EFA\u8BAE\u6A21\u5F0F\uFF08\u6A21\u578B\u4E0D\u652F\u6301\u5DE5\u5177\u8C03\u7528\uFF09", test_fail: "\u274C \u8FDE\u63A5\u5931\u8D25",
      tg_token: "Telegram Bot Token", tg_hint: "\u4ECE @BotFather \u521B\u5EFA Bot \u83B7\u53D6",
      more_channels: "\u66F4\u591A\u6E20\u9053\u5373\u5C06\u652F\u6301\uFF08WeChat\u3001LINE \u7B49\uFF09",
      task_toggle: "\u5207\u6362", task_delete: "\u5220\u9664", task_runs: "\u5DF2\u6267\u884C {n} \u6B21", task_last: "\u4E0A\u6B21: ",
      mode: "\u64CD\u4F5C\u6A21\u5F0F", mode_suggest: "\uD83D\uDCA1 \u5EFA\u8BAE\u6A21\u5F0F", mode_auto: "\u26A1 \u81EA\u52A8\u6267\u884C",
      mode_suggest_d: "AI \u63D0\u5EFA\u8BAE\uFF0C\u4F60\u786E\u8BA4\u540E\u6267\u884C", mode_auto_d: "AI \u76F4\u63A5\u64CD\u4F5C\uFF0C\u5371\u9669\u64CD\u4F5C\u9700\u786E\u8BA4",
      g_mem: "\uD83E\uDDE0 AI \u8BB0\u5FC6",
      mem_loading: "\u52A0\u8F7D\u4E2D...", mem_count: "\u5DF2\u8BB0\u4F4F {n} \u6761\u504F\u597D",
      mem_clear: "\u6E05\u9664\u8BB0\u5FC6", mem_cleared: "\u2705 \u5DF2\u6E05\u9664 {n} \u6761",
      mem_hint: "AI \u4F1A\u8BB0\u4F4F\u4F60\u7684\u4F7F\u7528\u504F\u597D\u548C\u8BBE\u5907\u4FE1\u606F\uFF0C\u7528\u4E8E\u63D0\u5347\u540E\u7EED\u5BF9\u8BDD\u8D28\u91CF",
      mem_empty: "\u6682\u65E0\u8BB0\u5FC6",
      save: "\u4FDD\u5B58", saved: "\u2705 \u5DF2\u4FDD\u5B58", save_fail: "\u274C \u4FDD\u5B58\u5931\u8D25",
      no_key: "\u8BF7\u8F93\u5165 API Key",
      learn_cloud: "\u4E86\u89E3\u4E91\u7AEF\u7248 \u2192",
    },
    ja: {
      hd: "\u2699\uFE0F MyClaw \u8A2D\u5B9A",
      g_ai: "\uD83E\uDD16 AI \u30B5\u30FC\u30D3\u30B9", g_ch: "\uD83D\uDCF1 \u30E1\u30C3\u30BB\u30FC\u30B8\u30C1\u30E3\u30CD\u30EB", g_pref: "\uD83C\uDF10 \u8A00\u8A9E\u30FB\u30E2\u30FC\u30C9",
      provider: "AI \u30D7\u30ED\u30D0\u30A4\u30C0", model: "\u30E2\u30C7\u30EB", test: "\uD83D\uDD17 \u63A5\u7D9A\u30C6\u30B9\u30C8",
      testing: "\u30C6\u30B9\u30C8\u4E2D...", test_ok: "\u2705 \u63A5\u7D9A\u6210\u529F", test_ok_tools: "\u2705 \u63A5\u7D9A\u6210\u529F \u2014 \u81EA\u52D5\u5B9F\u884C\u5BFE\u5FDC", test_ok_suggest: "\u26A0 \u63A5\u7D9A\u6210\u529F \u2014 \u63D0\u6848\u30E2\u30FC\u30C9\u306E\u307F\uFF08\u30C4\u30FC\u30EB\u547C\u3073\u51FA\u3057\u975E\u5BFE\u5FDC\uFF09", test_fail: "\u274C \u63A5\u7D9A\u5931\u6557",
      tg_token: "Telegram Bot Token", tg_hint: "@BotFather \u3067 Bot \u3092\u4F5C\u6210\u3057\u3066\u53D6\u5F97",
      more_channels: "\u4ED6\u306E\u30C1\u30E3\u30CD\u30EB\u306F\u8FD1\u65E5\u5BFE\u5FDC\u4E88\u5B9A\uFF08WeChat\u3001LINE\u7B49\uFF09",
      task_toggle: "\u5207\u66FF", task_delete: "\u524A\u9664", task_runs: "{n} \u56DE\u5B9F\u884C\u6E08", task_last: "\u524D\u56DE: ",
      mode: "\u52D5\u4F5C\u30E2\u30FC\u30C9", mode_suggest: "\uD83D\uDCA1 \u63D0\u6848\u30E2\u30FC\u30C9", mode_auto: "\u26A1 \u81EA\u52D5\u5B9F\u884C",
      mode_suggest_d: "AI \u304C\u63D0\u6848\u3001\u78BA\u8A8D\u5F8C\u5B9F\u884C", mode_auto_d: "AI \u304C\u76F4\u63A5\u64CD\u4F5C\u3001\u5371\u967A\u64CD\u4F5C\u306F\u78BA\u8A8D",
      g_mem: "\uD83E\uDDE0 AI \u30E1\u30E2\u30EA",
      mem_loading: "\u8AAD\u307F\u8FBC\u307F\u4E2D...", mem_count: "{n} \u4EF6\u306E\u8A18\u61B6\u3092\u4FDD\u6301",
      mem_clear: "\u30E1\u30E2\u30EA\u3092\u30AF\u30EA\u30A2", mem_cleared: "\u2705 {n} \u4EF6\u3092\u524A\u9664\u3057\u307E\u3057\u305F",
      mem_hint: "AI \u304C\u4F7F\u7528\u50BE\u5411\u3084\u30C7\u30D0\u30A4\u30B9\u60C5\u5831\u3092\u8A18\u61B6\u3057\u3001\u4ECA\u5F8C\u306E\u5BFE\u8A71\u3092\u6539\u5584\u3057\u307E\u3059",
      mem_empty: "\u30E1\u30E2\u30EA\u306A\u3057",
      save: "\u4FDD\u5B58", saved: "\u2705 \u4FDD\u5B58\u3057\u307E\u3057\u305F", save_fail: "\u274C \u4FDD\u5B58\u5931\u6557",
      no_key: "API Key \u3092\u5165\u529B\u3057\u3066\u304F\u3060\u3055\u3044",
      learn_cloud: "\u30AF\u30E9\u30A6\u30C9\u7248\u3092\u898B\u308B \u2192",
    },
    en: {
      hd: "\u2699\uFE0F MyClaw Settings",
      g_ai: "\uD83E\uDD16 AI Service", g_ch: "\uD83D\uDCF1 Channels", g_pref: "\uD83C\uDF10 Language & Mode",
      provider: "AI Provider", model: "Model", test: "\uD83D\uDD17 Test Connection",
      testing: "Testing...", test_ok: "\u2705 Connected", test_ok_tools: "\u2705 Connected \u2014 auto-execution supported", test_ok_suggest: "\u26A0 Connected \u2014 suggest mode only (no tool calling)", test_fail: "\u274C Failed",
      tg_token: "Telegram Bot Token", tg_hint: "Create a Bot via @BotFather",
      more_channels: "More channels coming soon (WeChat, LINE, etc.)",
      task_toggle: "Toggle", task_delete: "Delete", task_runs: "{n} runs", task_last: "Last: ",
      mode: "Operation Mode", mode_suggest: "\uD83D\uDCA1 Suggest Mode", mode_auto: "\u26A1 Auto Execute",
      mode_suggest_d: "AI suggests, you confirm before execution", mode_auto_d: "AI executes directly, confirms for risky actions",
      g_mem: "\uD83E\uDDE0 AI Memory",
      mem_loading: "Loading...", mem_count: "{n} preferences remembered",
      mem_clear: "Clear Memory", mem_cleared: "\u2705 Cleared {n} items",
      mem_hint: "AI remembers your preferences and device info to improve future conversations",
      mem_empty: "No memories",
      save: "Save", saved: "\u2705 Saved", save_fail: "\u274C Save failed",
      no_key: "Please enter API Key",
      learn_cloud: "Learn about Cloud \u2192",
    }
  };

  var _setL = _SET_I18N[_sbLang] || _SET_I18N.en;
  var _lastSupportsTools = true;

  var _PROVIDER_HINTS = {
    ollama:    { ph: "API Key (optional)", label: "Local Ollama", noKey: true },
    gemini:    { ph: "AIza...",    link: "https://aistudio.google.com/apikey",              label: "Google AI Studio" },
    anthropic: { ph: "sk-ant-...", link: "https://console.anthropic.com/settings/keys",     label: "Anthropic Console" },
    openai:    { ph: "sk-...",     link: "https://platform.openai.com/api-keys",            label: "OpenAI Platform" },
  };

  // =========================================================================
  // Settings: HTML builder
  // =========================================================================

  function _buildSettingsHTML() {
    var L = _setL;
    return '' +
    '<div id="kvmind-settings-view-header">' + L.hd + '</div>' +
    '<div id="kvmind-settings-view-body">' +

    // ── Plan status (read-only, community edition) ──
    '<div id="kv-set-sub-card" class="kv-subscription-card" style="margin:0 12px 12px;padding:10px 14px;border-radius:10px;border:1px solid var(--kvborder);background:var(--kvbg-card)">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">' +
        '<span id="kv-sub-plan-label" style="font-weight:600;font-size:13px">Community</span>' +
        '<a href="https://kvmind.com" target="_blank" rel="noopener" style="font-size:11px;color:var(--kvtext-sub);text-decoration:none;white-space:nowrap">' + L.learn_cloud + '</a>' +
      '</div>' +
      '<div id="kv-sub-features" style="font-size:11px;color:var(--kvtext-sub);margin-top:4px">\u2716 Tunnel &nbsp; \u2716 Messaging &nbsp; \u2716 OTA</div>' +
    '</div>' +

    // ── Group 1: AI Service (provider config only) ──
    '<div class="kv-set-group open">' +
      '<div class="kv-set-group-hd">' + L.g_ai + '<span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label">' + L.provider + '</label>' +
            '<select class="kv-set-select" id="kv-set-provider">' +
              '<option value="ollama">Ollama (Local)</option>' +
              '<option value="gemini">Gemini</option>' +
              '<option value="anthropic">Claude</option>' +
              '<option value="openai">ChatGPT</option>' +
              '<option value="other">Other (OpenAI Compatible)</option>' +
            '</select>' +
          '</div>' +
          '<div class="kv-set-row" id="kv-set-baseurl-row" style="display:none">' +
            '<label class="kv-set-label">Base URL</label>' +
            '<input type="text" class="kv-set-input" id="kv-set-baseurl" placeholder="https://...">' +
          '</div>' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label">API Key</label>' +
            '<div class="kv-set-input-wrap">' +
              '<input type="password" class="kv-set-input" id="kv-set-apikey" placeholder="AIza...">' +
              '<button class="eye-btn" data-target="kv-set-apikey">\uD83D\uDC41</button>' +
            '</div>' +
            '<div class="kv-set-hint" id="kv-set-key-hint"></div>' +
          '</div>' +
          '<div class="kv-set-row">' +
            '<label class="kv-set-label">' + L.model + '</label>' +
            '<select class="kv-set-select" id="kv-set-model"></select>' +
            '<input type="text" class="kv-set-input" id="kv-set-model-text" placeholder="gpt-4o / llama3 / ..." style="display:none">' +
          '</div>' +
          '<button class="kv-set-btn" id="kv-set-test-btn">' + L.test + '</button>' +
          '<div class="kv-set-status" id="kv-set-test-status" style="margin-top:6px"></div>' +
      '</div>' +
    '</div>' +

    // ── Group 2: Channels (messaging gated by subscription) ──
    '<div class="kv-set-group">' +
      '<div class="kv-set-group-hd">' + L.g_ch + '<span id="kv-set-ch-badges"></span><span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
        '<div id="kv-set-tg-section">' +
          '<div class="kv-set-row" id="kv-set-tg-locked" style="display:none">' +
            '<div style="text-align:center;padding:8px 0;color:var(--kvtext-sub);font-size:12px">' +
              '\uD83D\uDD12 Telegram Bot feature disabled' +
            '</div>' +
          '</div>' +
          '<div class="kv-set-row" id="kv-set-tg-unlocked">' +
            '<label class="kv-set-label">' + L.tg_token + '</label>' +
            '<div class="kv-set-input-wrap">' +
              '<input type="password" class="kv-set-input" id="kv-set-tg-token" placeholder="123456:ABC-DEF...">' +
              '<button class="eye-btn" data-target="kv-set-tg-token">\uD83D\uDC41</button>' +
            '</div>' +
            '<div class="kv-set-hint">' + L.tg_hint + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="kv-set-row" style="opacity:0.4;text-align:center;padding:8px">' +
          '<span style="font-size:11px">' + L.more_channels + '</span>' +
        '</div>' +
      '</div>' +
    '</div>' +

    // ── Group 3: AI Memory ──
    '<div class="kv-set-group">' +
      '<div class="kv-set-group-hd">' + L.g_mem + '<span class="kv-set-mem-count"></span><span class="arrow">\u25B6</span></div>' +
      '<div class="kv-set-group-bd">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">' +
          '<span class="kv-set-label" style="margin:0" id="kv-set-mem-info">' + L.mem_loading + '</span>' +
          '<button class="kv-set-btn" id="kv-set-mem-clear" style="white-space:nowrap">' + L.mem_clear + '</button>' +
        '</div>' +
        '<div id="kv-set-mem-list"></div>' +
        '<div class="kv-set-hint" style="margin-top:8px">' + L.mem_hint + '</div>' +
      '</div>' +
    '</div>' +

    '</div>' + // end body

    // ── Save bar ──
    '<div class="kv-set-save-row">' +
      '<div class="kv-set-status" id="kv-set-save-status"></div>' +
      '<button class="kv-set-btn primary" id="kv-set-save-btn">' + L.save + '</button>' +
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

  async function _onProviderChange(root) {
    var prov = root.querySelector("#kv-set-provider").value;
    var urlRow = root.querySelector("#kv-set-baseurl-row");
    var urlInput = root.querySelector("#kv-set-baseurl");
    var keyInput = root.querySelector("#kv-set-apikey");
    var hintEl = root.querySelector("#kv-set-key-hint");
    var modelSel = root.querySelector("#kv-set-model");
    var modelText = root.querySelector("#kv-set-model-text");

    if (prov === "other") {
      urlRow.style.display = "";
      urlInput.value = "";
      keyInput.placeholder = "API Key";
      hintEl.innerHTML = "";
      modelSel.style.display = "none";
      modelText.style.display = "";
    } else {
      var h = _PROVIDER_HINTS[prov] || {};
      urlRow.style.display = prov === "ollama" ? "" : "none";
      keyInput.placeholder = h.ph || "API Key";
      hintEl.innerHTML = h.link ? '<a href="' + h.link + '" target="_blank">' + h.label + '</a>' : "";
      modelSel.style.display = "";
      modelText.style.display = "none";
      try {
        var r = await fetch("/kdkvm/api/ai/models?provider=" + prov);
        var d = await r.json();
        if (prov === "ollama") urlInput.value = d.base_url || urlInput.value;
        modelSel.innerHTML = "";
        (d.models || []).forEach(function(m) {
          var opt = document.createElement("option");
          opt.value = m; opt.textContent = m;
          if (m === d.default) opt.selected = true;
          modelSel.appendChild(opt);
        });
      } catch (e) {
        modelSel.innerHTML = "<option>\u2014</option>";
      }
    }
  }

  // =========================================================================
  // Settings: test connection
  // =========================================================================

  async function _testConnection(root) {
    var L = _setL;
    var prov = root.querySelector("#kv-set-provider").value;
    var key = root.querySelector("#kv-set-apikey").value.trim();
    var statusEl = root.querySelector("#kv-set-test-status");
    var btn = root.querySelector("#kv-set-test-btn");
    var keyOptional = prov === "ollama" || prov === "other";
    if (!key && !keyOptional) { statusEl.className = "kv-set-status err"; statusEl.textContent = L.no_key; return; }
    var model = prov === "other"
      ? root.querySelector("#kv-set-model-text").value.trim()
      : root.querySelector("#kv-set-model").value;
    if (prov === "other" && !root.querySelector("#kv-set-baseurl").value.trim()) {
      statusEl.className = "kv-set-status err"; statusEl.textContent = "Base URL is required"; return;
    }
    btn.textContent = L.testing; btn.disabled = true;
    try {
      var payload = { provider: prov === "other" ? "custom" : prov, api_key: key || "none", model: model };
      if (prov === "other" || prov === "ollama") payload.base_url = root.querySelector("#kv-set-baseurl").value.trim();
      var r = await fetch("/kdkvm/api/ai/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      var d = await r.json();
      if (d.success) {
        _lastSupportsTools = d.supports_tools !== false;
        if (d.supports_tools === false) {
          statusEl.className = "kv-set-status warn";
          statusEl.textContent = L.test_ok_suggest;
        } else {
          statusEl.className = "kv-set-status ok";
          statusEl.textContent = L.test_ok_tools;
        }
      } else {
        statusEl.className = "kv-set-status err";
        statusEl.textContent = L.test_fail + ": " + (d.error || "");
      }
    } catch (e) {
      statusEl.className = "kv-set-status err";
      statusEl.textContent = L.test_fail + ": " + e.message;
    } finally {
      btn.textContent = L.test; btn.disabled = false;
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
      var sub = { plan: "community", tunnel: false, messaging: false, ota: false };
      try {
        var sr = await fetch("/kdkvm/api/subscription");
        sub = await sr.json();
      } catch (e) { console.warn("[Settings] subscription fetch failed:", e); }

      // Update subscription card
      var planLabels = { community: "Community (Free)", standard: "Standard", pro: "Pro" };
      var planLabel = root.querySelector("#kv-sub-plan-label");
      if (planLabel) planLabel.textContent = planLabels[sub.plan] || sub.plan;

      var featEl = root.querySelector("#kv-sub-features");
      if (featEl) {
        var f = [];
        f.push((sub.tunnel ? "\u2714" : "\u2716") + " Tunnel");
        f.push((sub.messaging ? "\u2714" : "\u2716") + " Messaging");
        f.push((sub.ota ? "\u2714" : "\u2716") + " OTA");
        featEl.textContent = f.join("  \u00B7  ");
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
      _lastSupportsTools = d.supports_tools !== false;

      // Provider details — always load if providers exist
      if (d.providers && d.providers.length > 0) {
        var p = d.providers[0];
        var provName = p.name || "other";
        var provSel = root.querySelector("#kv-set-provider");
        var hasOpt = Array.from(provSel.options).some(function(o) { return o.value === provName; });
        provSel.value = hasOpt ? provName : "other";
        await _onProviderChange(root);
        if (p.api_key_preview) root.querySelector("#kv-set-apikey").placeholder = p.api_key_preview;
        if (p.base_url && (provName === "ollama" || !hasOpt)) root.querySelector("#kv-set-baseurl").value = p.base_url;
        if (p.default_model) {
          var ms = root.querySelector("#kv-set-model");
          if (ms.style.display !== "none") ms.value = p.default_model;
          else root.querySelector("#kv-set-model-text").value = p.default_model;
        }
      } else {
        // No provider configured yet — initialize provider dropdown
        await _onProviderChange(root);
      }

      // Channel badges
      var badges = "";
      if (d.telegram_configured) badges += '<span class="kv-ch-status on">Telegram</span>';
      var badgeEl = root.querySelector("#kv-set-ch-badges");
      if (badgeEl) badgeEl.innerHTML = badges;

      // Telegram token placeholder
      if (d.telegram_configured) {
        var tgInput = root.querySelector("#kv-set-tg-token");
        if (tgInput) tgInput.placeholder = "\u2022\u2022\u2022\u2022\u2022\u2022 (\u5DF2\u914D\u7F6E)";
      }

      // Memory count
      _loadMemoryCount(root);
    } catch (e) {
      console.warn("[Settings] load failed:", e);
    }
  }

  var _MEM_TAG_MAP = {
    user_pref: { zh: "\u504F\u597D", ja: "\u597D\u307F", en: "Pref" },
    device_info: { zh: "\u8BBE\u5907", ja: "\u30C7\u30D0\u30A4\u30B9", en: "Device" },
    knowledge: { zh: "\u77E5\u8BC6", ja: "\u77E5\u8B58", en: "Knowledge" },
    instruction: { zh: "\u6307\u4EE4", ja: "\u6307\u793A", en: "Instruction" },
  };

  async function _loadMemoryCount(root) {
    var L = _setL;
    var info = root.querySelector("#kv-set-mem-info");
    var badge = root.querySelector(".kv-set-mem-count");
    var listEl = root.querySelector("#kv-set-mem-list");
    try {
      var r = await fetch("/kdkvm/api/ai/memory");
      var d = await r.json();
      var n = d.count || 0;
      var memories = d.memories || [];
      if (info) info.textContent = n > 0 ? L.mem_count.replace("{n}", n) : L.mem_empty;
      if (badge) { badge.textContent = n > 0 ? " (" + n + ")" : ""; badge.style.color = "var(--kvtext-sub)"; badge.style.fontSize = "12px"; }
      var btn = root.querySelector("#kv-set-mem-clear");
      if (btn) btn.disabled = (n === 0);
      // Render memory list
      if (listEl) {
        if (memories.length === 0) {
          listEl.innerHTML = "";
        } else {
          var html = "";
          memories.forEach(function(m) {
            var tagMap = _MEM_TAG_MAP[m.category] || _MEM_TAG_MAP.knowledge;
            var tag = tagMap[_sbLang] || tagMap.en;
            html += '<div class="kv-mem-item">' +
              '<span class="kv-mem-tag">' + tag + '</span>' +
              '<span class="kv-mem-text">' + _escHtml(m.content) + '</span>' +
            '</div>';
          });
          listEl.innerHTML = html;
        }
      }
    } catch (e) {
      if (info) info.textContent = L.mem_empty;
      if (listEl) listEl.innerHTML = "";
    }
  }

  function _escHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function _clearMemory(root) {
    var L = _setL;
    var btn = root.querySelector("#kv-set-mem-clear");
    var info = root.querySelector("#kv-set-mem-info");
    btn.disabled = true;
    try {
      var r = await fetch("/kdkvm/api/ai/memory", { method: "DELETE" });
      var d = await r.json();
      if (info) info.textContent = L.mem_cleared.replace("{n}", d.deleted || 0);
      var badge = root.querySelector(".kv-set-mem-count");
      if (badge) badge.textContent = "";
      setTimeout(function() { _loadMemoryCount(root); }, 2000);
    } catch (e) {
      if (info) info.textContent = L.mem_empty;
      btn.disabled = false;
    }
  }

  // =========================================================================
  // Settings: save to API
  // =========================================================================

  async function _saveSettings(root) {
    var L = _setL;
    var statusEl = root.querySelector("#kv-set-save-status");
    var btn = root.querySelector("#kv-set-save-btn");

    var body = {};

    // AI provider config
    var prov = root.querySelector("#kv-set-provider").value;
    var key = root.querySelector("#kv-set-apikey").value.trim();
    var model = prov === "other"
      ? root.querySelector("#kv-set-model-text").value.trim()
      : root.querySelector("#kv-set-model").value;
    if (prov === "other") {
      var customUrl = root.querySelector("#kv-set-baseurl").value.trim();
      if (customUrl && model) body.custom_provider = { base_url: customUrl, api_key: key, model: model };
    } else if (key || prov === "ollama") {
      var keyMap = { ollama: "ollama_key", gemini: "gemini_key", anthropic: "claude_key", openai: "openai_key" };
      if (key) body[keyMap[prov]] = key;
      if (prov === "ollama") {
        body.ollama_enabled = true;
        body.ollama_url = root.querySelector("#kv-set-baseurl").value.trim();
      }
      body[prov + "_model"] = model;
    }

    // Tool support flag from last test
    body.supports_tools = _lastSupportsTools;

    // Telegram (only if unlocked section is visible)
    var tgUnlocked = root.querySelector("#kv-set-tg-unlocked");
    if (tgUnlocked && tgUnlocked.style.display !== "none") {
      var tg = root.querySelector("#kv-set-tg-token").value.trim();
      if (tg) body.telegram_token = tg;
    }

    btn.disabled = true;
    try {
      var r = await fetch("/kdkvm/api/ai/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      var d = await r.json();
      if (r.status === 403 && d.error === "messaging_not_enabled") {
        statusEl.className = "kv-set-status err";
        statusEl.textContent = "Telegram requires an active subscription";
      } else if (d.status === "ok") {
        statusEl.className = "kv-set-status ok";
        statusEl.textContent = L.saved;
      } else {
        statusEl.className = "kv-set-status err";
        statusEl.textContent = L.save_fail + ": " + (d.error || "");
      }
    } catch (e) {
      statusEl.className = "kv-set-status err";
      statusEl.textContent = L.save_fail + ": " + e.message;
    } finally {
      btn.disabled = false;
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
