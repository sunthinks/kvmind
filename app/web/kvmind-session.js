/**
 * kvmind-session.js -- KVM WebSocket Session Manager
 *
 * Connects to KVM backend's /api/ws endpoint.
 * Dispatches state events to KVMindStream, KVMindHID, and UI.
 * Binary HID protocol for keyboard/mouse.
 */
(function(global) {
"use strict";

function KVMindSession() {
  var self = this;
  var ws = null;
  var pingTimer = null;
  var missedHeartbeats = 0;
  var stopped = false;
  var _reconnectAttempts = 0;
  var asciiEncoder = new TextEncoder("ascii");

  // State callbacks
  self.onStreamerState = null;   // function(state)
  self.onHidState = null;        // function(state)
  self.onAtxState = null;        // function(state)
  self.onInfoState = null;       // function(state)
  self.onConnected = null;       // function()
  self.onDisconnected = null;    // function()

  self.isConnected = function() { return ws && ws.readyState === WebSocket.OPEN; };

  self.start = function() {
    stopped = false;
    _connect();
  };

  self.stop = function() {
    stopped = true;
    _forceClose();
  };

  // ── HID send methods ──

  self.sendKey = function(code, state, finish) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    var data = asciiEncoder.encode("\x01\x00" + code);
    data[1] = state ? 1 : 0;
    if (finish) data[1] |= 0x02;
    ws.send(data);
  };

  self.sendMouseButton = function(button, state) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    var data = asciiEncoder.encode("\x02\x00" + button);
    data[1] = state ? 1 : 0;
    ws.send(data);
  };

  self.sendMouseMove = function(x, y) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // x, y are -32768..32767
    var ux = x & 0xFFFF;
    var uy = y & 0xFFFF;
    var data = new Uint8Array([3, (ux >> 8) & 0xFF, ux & 0xFF, (uy >> 8) & 0xFF, uy & 0xFF]);
    ws.send(data);
  };

  self.sendMouseRelative = function(dx, dy) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    var data = new Int8Array([4, 0, dx, dy]);
    ws.send(data);
  };

  self.sendMouseWheel = function(dx, dy) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    var data = new Int8Array([5, 0, dx, dy]);
    ws.send(data);
  };

  // ── Internal ──

  function _connect() {
    if (stopped || ws) return;
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + "/api/ws";
    console.log("[KVMind Session] Connecting to", url);

    try {
      ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
    } catch (e) {
      console.error("[KVMind Session] WS create failed:", e);
      ws = null;
      _scheduleReconnect();
      return;
    }

    ws.onopen = function() {
      console.log("[KVMind Session] Connected");
      missedHeartbeats = 0;
      _reconnectAttempts = 0;
      pingTimer = setInterval(_ping, 1000);
      if (self.onConnected) self.onConnected();
    };

    ws.onmessage = function(ev) {
      if (typeof ev.data === "string") {
        try {
          var msg = JSON.parse(ev.data);
          _handleJson(msg.event_type, msg.event);
        } catch (e) { console.warn("[KVMind Session] message parse error:", e); }
      } else {
        _handleBinary(new Uint8Array(ev.data));
      }
    };

    ws.onerror = function(ev) {
      console.error("[KVMind Session] WS error:", ev);
      _forceClose();
    };

    ws.onclose = function() {
      console.log("[KVMind Session] WS closed");
      _cleanup();
      if (self.onDisconnected) self.onDisconnected();
      _scheduleReconnect();
    };
  }

  function _ping() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    missedHeartbeats++;
    if (missedHeartbeats >= 15) {
      console.warn("[KVMind Session] Too many missed heartbeats");
      _forceClose();
      return;
    }
    try {
      ws.send(new Uint8Array([0]));
    } catch (e) {
      _forceClose();
    }
  }

  function _handleBinary(data) {
    if (data[0] === 255) { // Pong
      missedHeartbeats = 0;
    }
  }

  function _handleJson(evType, ev) {
    switch (evType) {
      case "streamer":
        if (self.onStreamerState) self.onStreamerState(ev);
        break;
      case "hid":
        if (self.onHidState) self.onHidState(ev);
        break;
      case "atx":
        if (self.onAtxState) self.onAtxState(ev);
        break;
      case "info":
        if (self.onInfoState) self.onInfoState(ev);
        break;
    }
  }

  function _forceClose() {
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch(e) {}
    }
    _cleanup();
    if (self.onDisconnected) self.onDisconnected();
  }

  function _cleanup() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
    missedHeartbeats = 0;
    ws = null;
  }

  function _scheduleReconnect() {
    if (stopped) return;
    var delay = Math.min(1000 * Math.pow(1.5, _reconnectAttempts), 30000);
    delay += Math.random() * 1000; // jitter
    _reconnectAttempts++;
    setTimeout(_connect, delay);
  }
}

global.KVMindSession = KVMindSession;
console.log("[kvmind-session] loaded");

})(typeof window !== "undefined" ? window : this);
