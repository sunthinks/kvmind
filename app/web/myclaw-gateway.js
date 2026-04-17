/**
 * myclaw-gateway.js — MyClaw AI Chat WebSocket Client
 *
 * Connects to the KVMind server's /ws/chat endpoint for AI chat.
 *
 * Usage:
 *   var gw = new KVMindGateway({ url: "wss://host/ws/chat", token: "xxx" });
 *   gw.connect();
 *   gw.sendChat("hello");
 *   gw.onChatDelta = function(text) { ... };
 *   gw.onChatFinal = function(message) { ... };
 *   gw.onConnected = function() { ... };
 */
(function(global) {
"use strict";

function uuid() {
  if (crypto && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0;
    return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

function getOrCreateSessionId() {
  var key = "myclaw_session_id";
  var id = sessionStorage.getItem(key);
  if (!id) {
    id = uuid();
    sessionStorage.setItem(key, id);
  }
  return id;
}

function KVMindGateway(opts) {
  this.url = opts.url;
  this.token = opts.token || "";
  this.sessionKey = opts.sessionKey || "";
  this.clientName = opts.clientName || "gateway-client";
  this.clientVersion = opts.clientVersion || "2.0.0";

  this.ws = null;
  this.connected = false;
  this.closed = false;
  this.chatRunId = null;
  this.currentRunId = null;
  this._lastAbortedRunId = null;
  this.chatStream = "";
  this.backoffMs = 800;
  this._thinking = false;

  // Callbacks (same API as OpenClaw version)
  this.onConnected = null;
  this.onDisconnected = null;
  this.onChatDelta = null;       // function(text, runId)
  this.onChatFinal = null;       // function(message, runId)
  this.onChatAborted = null;     // function(partialText)
  this.onChatError = null;       // function(errorMessage)
  this.onToolStart = null;       // function(toolName, toolCallId, inputObj)
  this.onToolResult = null;      // function(toolName, resultText, toolCallId)
  this.onThinkingStart = null;   // function()
  this.onThinkingEnd = null;     // function()
  this.onConfirmRequired = null; // function(action, args)
  this.onScreenshot = null;      // function(base64)
  this.onLog = null;             // function(level, msg)
}

KVMindGateway.prototype._log = function(level, msg) {
  if (this.onLog) this.onLog(level, msg);
  console.log("[KVMind GW] [" + level + "] " + msg);
};

KVMindGateway.prototype.connect = function() {
  if (this.closed) return;
  var self = this;

  // Build WS URL with session_id param
  var sessionId = getOrCreateSessionId();
  var separator = this.url.indexOf("?") >= 0 ? "&" : "?";
  var wsUrl = this.url + separator + "session_id=" + encodeURIComponent(sessionId);
  // TODO: Security — move token out of URL to avoid server access-log exposure.
  // Preferred: send auth message after onopen: ws.send(JSON.stringify({type:"auth",token:...}))
  // Requires backend (websocket.py) to support message-based auth.
  // Keeping URL token as fallback until backend is updated.
  if (this.token) {
    wsUrl += "&token=" + encodeURIComponent(this.token);
  }

  try {
    this.ws = new WebSocket(wsUrl);
  } catch (e) {
    console.error("WebSocket create failed:", e);
    this._log("error", "连接失败");
    this._scheduleReconnect();
    return;
  }

  this.ws.onopen = function() {
    self.connected = true;
    self.backoffMs = 800;
    self._log("ok", "Connected to MyClaw Gateway");
    if (self.onConnected) self.onConnected({});
  };

  this.ws.onmessage = function(e) {
    self._handleMessage(e.data);
  };

  this.ws.onclose = function(e) {
    var wasConnected = self.connected;
    self.connected = false;
    self.ws = null;
    // Clear run_id state on disconnect to prevent stale filtering after reconnect
    self.chatRunId = null;
    self.currentRunId = null;
    self._lastAbortedRunId = null;
    self.chatStream = "";
    if (wasConnected && self.onDisconnected) self.onDisconnected(e.code, e.reason);
    self._log("warn", "WebSocket closed (" + e.code + ")");
    self._scheduleReconnect();
  };

  this.ws.onerror = function() {};
};

KVMindGateway.prototype.disconnect = function() {
  this.closed = true;
  if (this.ws) this.ws.close();
  this.ws = null;
  this.connected = false;
  this.chatRunId = null;
  this.currentRunId = null;
  this._lastAbortedRunId = null;
  this.chatStream = "";
};

KVMindGateway.prototype._scheduleReconnect = function() {
  if (this.closed) return;
  var self = this;
  var delay = this.backoffMs;
  this.backoffMs = Math.min(this.backoffMs * 1.7, 15000);
  setTimeout(function() { self.connect(); }, delay);
};

KVMindGateway.prototype._handleMessage = function(raw) {
  var msg;
  try { msg = JSON.parse(raw); } catch (e) { console.error("[Gateway] JSON parse error:", e); if (this.onLog) this.onLog("error", "Message parse error"); return; }

  var type = msg.type || "";

  // ── run_id filtering: discard stale events from previous or aborted runs ──
  if (msg.run_id && msg.run_id !== this.currentRunId) {
    if (this.currentRunId || msg.run_id === this._lastAbortedRunId) {
      return; // stale event from a different or aborted run
    }
  }

  // Abort acknowledged — runner has exited, safe to send next message
  if (type === "abort_ack") {
    return;
  }

  // AI is thinking (waiting for AI API response)
  if (type === "thinking") {
    this._thinking = true;
    if (this.onThinkingStart) this.onThinkingStart();
    return;
  }

  // Any non-thinking message ends the thinking state
  if (this._thinking) {
    this._thinking = false;
    if (this.onThinkingEnd) this.onThinkingEnd();
  }

  // Streaming text chunk
  if (type === "chunk") {
    var chunkText = msg.content || "";
    this.chatStream += chunkText;
    if (this.onChatDelta) this.onChatDelta(this.chatStream, this.chatRunId);
    return;
  }

  // Final complete message or done signal
  if (type === "message" || type === "done") {
    var finalText = msg.full_response || msg.content || this.chatStream;
    if (this._isNoReply(finalText)) finalText = "";
    this.chatRunId = null;
    this.currentRunId = null;
    var accumulated = this.chatStream;
    this.chatStream = "";
    if (this.onChatFinal) this.onChatFinal(finalText || accumulated, null);
    return;
  }

  // Tool call start
  if (type === "tool_call") {
    if (this.onToolStart) {
      this.onToolStart(msg.name || "tool", msg.id || "", msg.input || null);
    }
    return;
  }

  // Tool result
  if (type === "tool_result") {
    if (this.onToolResult) {
      var resultText = msg.output || "";
      if (resultText.length > 500) resultText = resultText.substring(0, 500) + "…";
      this.onToolResult(msg.name || "tool", resultText, msg.id || "");
    }
    return;
  }

  // Error
  if (type === "error") {
    this.chatRunId = null;
    this.chatStream = "";
    console.error("Chat API error:", msg.message || msg.content);
    if (this.onChatError) this.onChatError(msg.message || msg.content || "unknown error");
    return;
  }

  // Confirmation required (dangerous action)
  if (type === "confirm_required") {
    if (this.onConfirmRequired) this.onConfirmRequired(msg.action || "", msg.args || {}, msg.run_id || null);
    return;
  }

  // Screenshot
  if (type === "screenshot") {
    if (this.onScreenshot) this.onScreenshot(msg.data || "");
    return;
  }
};

// ── Chat API ──

KVMindGateway.prototype.sendChat = function(message, opts) {
  if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
    // Kick a reconnect so the next click actually has a chance to land.
    // Don't show a raw English "Not connected" — onChatError gets a typed
    // marker that core.js translates to a bilingual, actionable message.
    var rs = this.ws ? this.ws.readyState : null;
    if (rs === null || rs === WebSocket.CLOSED || rs === WebSocket.CLOSING) {
      this.connect();
    }
    if (this.onChatError) this.onChatError({code: "ws_not_open", reason: rs});
    return Promise.resolve(null);
  }

  opts = opts || {};
  var runId = uuid();
  this.chatRunId = runId;
  this.currentRunId = runId;
  this._lastAbortedRunId = null;  // new run started, clear abort filter
  this.chatStream = "";

  // Server expects: { type: "message", content: "...", mode: "suggest"|"auto", run_id: "..." }
  var payload = {
    type: "message",
    content: message,
    run_id: runId
  };
  if (opts.mode) payload.mode = opts.mode;
  if (opts.lang) payload.lang = opts.lang;

  this.ws.send(JSON.stringify(payload));

  // No optimistic onThinkingStart — server sends "thinking" event when ready.
  return Promise.resolve(runId);
};

KVMindGateway.prototype.sendConfirm = function(approved, runId) {
  if (this.ws && this.ws.readyState === WebSocket.OPEN) {
    var msg = { type: "confirm", approved: !!approved };
    var rid = runId || this.currentRunId;
    if (rid) msg.run_id = rid;
    this.ws.send(JSON.stringify(msg));
  }
};

KVMindGateway.prototype.abortChat = function() {
  // Send abort command over the existing WebSocket — no reconnect needed.
  // Server-side Runner checks _abort flag and exits cleanly.
  var partialText = this.chatStream;
  var abortRunId = this.currentRunId;
  this.chatRunId = null;
  this._lastAbortedRunId = this.currentRunId;
  this.currentRunId = null;  // null immediately so abort_ack (carrying old run_id) won't match
  this.chatStream = "";
  if (this.ws && this.ws.readyState === WebSocket.OPEN) {
    var msg = { type: "abort" };
    if (abortRunId) msg.run_id = abortRunId;
    this.ws.send(JSON.stringify(msg));
  }
  if (this.onChatAborted) this.onChatAborted(partialText);
  return Promise.resolve();
};

KVMindGateway.prototype.loadHistory = function(opts) {
  // History not supported over WS — return empty
  return Promise.resolve({ messages: [] });
};

KVMindGateway.prototype._isNoReply = function(text) {
  return /^\s*NO_REPLY\s*$/.test(text);
};

// ── Expose ──
global.KVMindGateway = KVMindGateway;

})(typeof window !== "undefined" ? window : this);
console.log("[MyClaw Gateway v4] loaded");
