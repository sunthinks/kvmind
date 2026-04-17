/**
 * kvmind-hid.js -- Keyboard & Mouse HID Control
 *
 * Captures keyboard/mouse events on #kvmind-stream-overlay and sends
 * them to the KVM device via the KVMindSession binary protocol.
 *
 * Settings (NanoKVM-style):
 *   - Cursor Style: none / blue-dot / crosshair / default / pointer
 *   - Mouse Mode: absolute / relative (calls KVM backend API)
 *   - Scroll Direction: normal / reverse
 *   - Scroll Speed: 1-25 (default 5)
 *   - Sensitivity: 0.1-1.9 (relative mode only, default 1.0)
 *   - Move Squash: on/off with adjustable rate
 */
(function(global) {
"use strict";

// KVM cursor indicator SVG as data URI (from stream-mouse-cursor.svg)
var BLUE_DOT_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10'%3E%3Ccircle cx='5' cy='5' r='4.5' fill='%235b90bb' fill-opacity='0.5' stroke='%23e8e8e8' stroke-width='0.5' stroke-opacity='0.8'/%3E%3C/svg%3E";

// Cursor style map (NanoKVM-style 5 options)
var CURSOR_STYLES = {
  "none":      "none",
  "blue-dot":  "url(" + BLUE_DOT_SVG + ") 5 5, crosshair",
  "crosshair": "crosshair",
  "default":   "default",
  "pointer":   "pointer"
};

function KVMindHID(session, streamGetter) {
  var self = this;
  var overlay = null;
  var online = false;
  var hidOnline = false;

  // ── Settings (persisted in localStorage) ──
  var _cursorStyle = "blue-dot";      // none | blue-dot | crosshair | default | pointer
  var _mouseMode = "absolute";        // absolute | relative
  var _scrollReverse = false;         // reverse scroll direction
  var _scrollRate = 5;                // 1-25
  var _sensitivity = 1.0;            // 0.1-1.9 (relative mode only)
  var _squashEnabled = true;          // squash mouse moves
  var _moveRate = 10;                 // squash timer ms (10-100)

  // Mouse move planning
  var moveTimer = null;
  var pendingAbsPos = null;
  var pendingRelDelta = null;

  // Track pressed keys for release-all
  var pressedKeys = {};
  var pressedButtons = {};

  // Pointer Lock state (for relative mode)
  var _pointerLocked = false;

  // ── Load settings from localStorage ──
  function _loadSettings() {
    try {
      var s = localStorage.getItem("kvmind-hid-settings");
      if (s) {
        var o = JSON.parse(s);
        if (o.cursorStyle && CURSOR_STYLES[o.cursorStyle] !== undefined) _cursorStyle = o.cursorStyle;
        if (o.mouseMode === "absolute" || o.mouseMode === "relative") _mouseMode = o.mouseMode;
        if (o.scrollReverse !== undefined) _scrollReverse = !!o.scrollReverse;
        if (typeof o.scrollRate === "number" && o.scrollRate >= 1 && o.scrollRate <= 25) _scrollRate = o.scrollRate;
        if (typeof o.sensitivity === "number" && o.sensitivity >= 0.1 && o.sensitivity <= 1.9) _sensitivity = Math.round(o.sensitivity * 10) / 10;
        if (o.squashEnabled !== undefined) _squashEnabled = !!o.squashEnabled;
        if (typeof o.moveRate === "number" && o.moveRate >= 10 && o.moveRate <= 100) _moveRate = o.moveRate;
      }
    } catch(e) {}
  }

  function _saveSettings() {
    try {
      localStorage.setItem("kvmind-hid-settings", JSON.stringify({
        cursorStyle: _cursorStyle,
        mouseMode: _mouseMode,
        scrollReverse: _scrollReverse,
        scrollRate: _scrollRate,
        sensitivity: _sensitivity,
        squashEnabled: _squashEnabled,
        moveRate: _moveRate
      }));
    } catch(e) {}
  }

  // ── Init ──
  self.init = function() {
    overlay = document.getElementById("kvmind-stream-overlay");
    if (!overlay) {
      console.error("[KVMind HID] #kvmind-stream-overlay not found");
      return;
    }

    _loadSettings();

    // Mouse events
    overlay.addEventListener("contextmenu", function(ev) { ev.preventDefault(); });
    overlay.addEventListener("mousedown", function(ev) { _mouseButton(ev, true); });
    overlay.addEventListener("mouseup", function(ev) { _mouseButton(ev, false); });
    overlay.addEventListener("mousemove", _mouseMove);
    overlay.addEventListener("wheel", _mouseWheel, { passive: false });

    // Touch events
    overlay.addEventListener("touchstart", _touchStart, { passive: false });
    overlay.addEventListener("touchmove", _touchMove, { passive: false });
    overlay.addEventListener("touchend", _touchEnd, { passive: false });

    // Keyboard events
    overlay.tabIndex = -1;
    overlay.addEventListener("keydown", function(ev) { _keyHandler(ev, true); });
    overlay.addEventListener("keyup", function(ev) { _keyHandler(ev, false); });

    // Focus overlay
    overlay.addEventListener("mousedown", function() { overlay.focus(); });
    setTimeout(function() { if (overlay) overlay.focus(); }, 500);

    // Move timer for squashed moves
    moveTimer = setInterval(_sendPlannedMove, _moveRate);

    // Release all on visibility change / blur
    document.addEventListener("visibilitychange", function() {
      if (document.visibilityState === "hidden") self.releaseAll();
    });
    window.addEventListener("blur", function() { self.releaseAll(); });

    // Pointer Lock event listeners (for relative mode)
    document.addEventListener("pointerlockchange", function() {
      _pointerLocked = (document.pointerLockElement === overlay);
      _applyCursor();
    });
    document.addEventListener("pointerlockerror", function() {
      _pointerLocked = false;
      console.warn("[KVMind HID] Pointer Lock error");
    });

    _applyCursor();
    console.log("[KVMind HID] initialized, mode=" + _mouseMode + " cursor=" + _cursorStyle);
  };

  self.setState = function(state) {
    if (!state) {
      online = false;
      hidOnline = false;
      return;
    }
    if (state.online !== undefined) online = state.online;
    if (state.busy !== undefined) online = online && !state.busy;
    if (state.mouse && state.mouse.absolute !== undefined) {
      // Sync from server state (may differ from our setting if another client changed it)
      var serverAbs = state.mouse.absolute;
      if (serverAbs && _mouseMode === "relative") {
        _mouseMode = "absolute";
        _saveSettings();
      } else if (!serverAbs && _mouseMode === "absolute") {
        _mouseMode = "relative";
        _saveSettings();
      }
    }
    if (state.keyboard && state.keyboard.online !== undefined) {
      hidOnline = state.keyboard.online;
    }
    if (state.mouse && state.mouse.online !== undefined) {
      hidOnline = hidOnline || state.mouse.online;
    }
  };

  self.releaseAll = function() {
    for (var code in pressedKeys) {
      if (pressedKeys[code]) {
        session.sendKey(code, false, false);
      }
    }
    pressedKeys = {};
    for (var btn in pressedButtons) {
      if (pressedButtons[btn]) {
        session.sendMouseButton(btn, false);
      }
    }
    pressedButtons = {};
  };

  // ══════════════════════════════════════════════════
  // Settings API (called from kvmind-core.js settings UI)
  // ══════════════════════════════════════════════════

  // ── Cursor Style ──
  self.setCursorStyle = function(style) {
    if (CURSOR_STYLES[style] === undefined) return;
    _cursorStyle = style;
    _applyCursor();
    _saveSettings();
  };
  self.getCursorStyle = function() { return _cursorStyle; };

  // Legacy API compatibility
  self.setLocalCursor = function(show) {
    self.setCursorStyle(show ? "blue-dot" : "none");
  };
  self.getLocalCursor = function() {
    return _cursorStyle !== "none";
  };

  // ── Mouse Mode ──
  self.setMouseMode = function(mode) {
    if (mode !== "absolute" && mode !== "relative") return;
    _mouseMode = mode;
    _saveSettings();

    // Call KVM backend API to switch mouse output
    var output = (mode === "relative") ? "usb_rel" : "usb";
    fetch("/api/hid/set_params?mouse_output=" + output, {
      method: "POST",
      credentials: "same-origin"
    }).then(function(r) {
      console.log("[KVMind HID] Mouse output set to " + output + " → " + r.status);
    }).catch(function(e) {
      console.error("[KVMind HID] Failed to set mouse output:", e);
    });

    // Handle Pointer Lock for relative mode
    if (mode === "relative" && overlay && !_pointerLocked) {
      overlay.requestPointerLock();
    } else if (mode === "absolute" && _pointerLocked) {
      document.exitPointerLock();
    }

    _applyCursor();
  };
  self.getMouseMode = function() { return _mouseMode; };

  // ── Scroll Direction ──
  self.setScrollReverse = function(rev) {
    _scrollReverse = !!rev;
    _saveSettings();
  };
  self.getScrollReverse = function() { return _scrollReverse; };

  // ── Scroll Rate ──
  self.setScrollRate = function(rate) {
    rate = parseInt(rate, 10);
    if (rate >= 1 && rate <= 25) {
      _scrollRate = rate;
      _saveSettings();
    }
  };
  self.getScrollRate = function() { return _scrollRate; };

  // ── Sensitivity (relative mode) ──
  self.setSensitivity = function(val) {
    val = Math.round(parseFloat(val) * 10) / 10;
    if (val >= 0.1 && val <= 1.9) {
      _sensitivity = val;
      _saveSettings();
    }
  };
  self.getSensitivity = function() { return _sensitivity; };

  // ── Squash ──
  self.setSquashEnabled = function(on) {
    _squashEnabled = !!on;
    _saveSettings();
  };
  self.getSquashEnabled = function() { return _squashEnabled; };

  self.setMoveRate = function(rate) {
    rate = parseInt(rate, 10);
    if (rate >= 10 && rate <= 100) {
      _moveRate = rate;
      _saveSettings();
      // Restart timer with new rate
      if (moveTimer) clearInterval(moveTimer);
      moveTimer = setInterval(_sendPlannedMove, _moveRate);
    }
  };
  self.getMoveRate = function() { return _moveRate; };

  // ── Reset HID ──
  self.resetHID = function() {
    fetch("/api/hid/reset", { method: "POST", credentials: "same-origin" })
    .then(function() { console.log("[KVMind HID] HID reset"); })
    .catch(function(e) { console.error("[KVMind HID] HID reset failed:", e); });
  };

  // ══════════════════════════════════════════════════
  // Internal: Cursor
  // ══════════════════════════════════════════════════

  function _applyCursor() {
    if (!overlay) return;
    if (_mouseMode === "relative" && !_pointerLocked) {
      // Waiting for Pointer Lock — show alias cursor
      overlay.style.cursor = "alias";
    } else if (_mouseMode === "relative" && _pointerLocked) {
      // Pointer Lock active — cursor is hidden by browser
      overlay.style.cursor = "none";
    } else {
      // Absolute mode — use selected cursor style
      overlay.style.cursor = CURSOR_STYLES[_cursorStyle] || "crosshair";
    }
  }

  // ══════════════════════════════════════════════════
  // Internal: Keyboard
  // ══════════════════════════════════════════════════

  function _keyHandler(ev, state) {
    ev.preventDefault();
    ev.stopPropagation();
    if (ev.repeat) return;

    var code = ev.code;

    // Mac: release all when Meta released
    if (!state && (code === "MetaLeft" || code === "MetaRight")) {
      self.releaseAll();
      return;
    }

    if (state) {
      pressedKeys[code] = true;
    } else {
      delete pressedKeys[code];
    }

    session.sendKey(code, state, false);
  }

  // ══════════════════════════════════════════════════
  // Internal: Mouse
  // ══════════════════════════════════════════════════

  function _mouseButton(ev, state) {
    ev.preventDefault();
    ev.stopPropagation();

    // Click to request Pointer Lock in relative mode
    if (state && _mouseMode === "relative" && !_pointerLocked && overlay) {
      overlay.requestPointerLock();
    }

    var buttonName;
    switch (ev.button) {
      case 0: buttonName = "left"; break;
      case 1: buttonName = "middle"; break;
      case 2: buttonName = "right"; break;
      case 3: buttonName = "up"; break;
      case 4: buttonName = "down"; break;
      default: return;
    }

    if (state) {
      pressedButtons[buttonName] = true;
    } else {
      delete pressedButtons[buttonName];
    }

    _sendPlannedMove();
    session.sendMouseButton(buttonName, state);
  }

  function _mouseMove(ev) {
    if (_mouseMode === "relative") {
      // Relative mode: use movementX/Y (Pointer Lock provides these)
      var dx = ev.movementX || 0;
      var dy = ev.movementY || 0;
      if (!dx && !dy) return;

      // Apply sensitivity
      dx = Math.round(dx * _sensitivity);
      dy = Math.round(dy * _sensitivity);

      // Clamp to -127..127 per PiKVM protocol
      dx = Math.min(127, Math.max(-127, dx));
      dy = Math.min(127, Math.max(-127, dy));

      if (_squashEnabled) {
        // Accumulate for squash
        if (!pendingRelDelta) pendingRelDelta = { x: 0, y: 0 };
        pendingRelDelta.x += dx;
        pendingRelDelta.y += dy;
        // Clamp accumulated
        pendingRelDelta.x = Math.min(127, Math.max(-127, pendingRelDelta.x));
        pendingRelDelta.y = Math.min(127, Math.max(-127, pendingRelDelta.y));
      } else {
        session.sendMouseRelative(dx, dy);
      }
      return;
    }

    // Absolute mode
    var geo = streamGetter();
    if (!geo || !geo.width || !geo.height) return;

    var rect = overlay.getBoundingClientRect();
    var mouseX = ev.clientX - rect.left;
    var mouseY = ev.clientY - rect.top;

    var vidX = mouseX - geo.x;
    var vidY = mouseY - geo.y;

    var absX = _remap(vidX, 0, geo.width - 1, -32768, 32767);
    var absY = _remap(vidY, 0, geo.height - 1, -32768, 32767);

    if (_squashEnabled) {
      pendingAbsPos = { x: absX, y: absY };
    } else {
      session.sendMouseMove(absX, absY);
    }
  }

  function _mouseWheel(ev) {
    ev.preventDefault();
    if (!ev.deltaY && !ev.deltaX) return;

    var dirMul = _scrollReverse ? 1 : -1;

    // Normalize deltaY across browsers:
    // - deltaMode 0 (pixels): typical ~100-150 per notch → divide by 30
    // - deltaMode 1 (lines): already ~3 per notch → use directly
    // - deltaMode 2 (pages): rare → multiply by 10
    var normY = ev.deltaY || 0;
    var normX = ev.deltaX || 0;
    if (ev.deltaMode === 0) { normY /= 30; normX /= 30; }
    else if (ev.deltaMode === 2) { normY *= 10; normX *= 10; }

    // Apply scroll rate and direction, then clamp to Int8 range (-127..127)
    var dy = normY ? Math.round(normY * dirMul * (_scrollRate / 5)) : 0;
    var dx = normX ? Math.round(normX * dirMul * (_scrollRate / 5)) : 0;
    dy = Math.max(-127, Math.min(127, dy));
    dx = Math.max(-127, Math.min(127, dx));

    // Ensure at least ±1 step if there was any delta
    if (ev.deltaY && !dy) dy = Math.sign(ev.deltaY) * dirMul;
    if (ev.deltaX && !dx) dx = Math.sign(ev.deltaX) * dirMul;

    if (dx || dy) {
      session.sendMouseWheel(dx, dy);
    }
  }

  // ══════════════════════════════════════════════════
  // Internal: Touch
  // ══════════════════════════════════════════════════

  var touchPos = null;

  function _touchStart(ev) {
    ev.preventDefault();
    if (ev.touches.length === 1) {
      var pos = _getTouchPos(ev, 0);
      if (_mouseMode === "absolute" && pos) {
        var geo = streamGetter();
        if (geo && geo.width && geo.height) {
          var vidX = pos.x - geo.x;
          var vidY = pos.y - geo.y;
          var absX = _remap(vidX, 0, geo.width - 1, -32768, 32767);
          var absY = _remap(vidY, 0, geo.height - 1, -32768, 32767);
          session.sendMouseMove(absX, absY);
        }
        touchPos = pos;
      }
    }
  }

  function _touchMove(ev) {
    ev.preventDefault();
    if (ev.touches.length === 1 && _mouseMode === "absolute") {
      var pos = _getTouchPos(ev, 0);
      if (pos) {
        var geo = streamGetter();
        if (geo && geo.width && geo.height) {
          var vidX = pos.x - geo.x;
          var vidY = pos.y - geo.y;
          var absX = _remap(vidX, 0, geo.width - 1, -32768, 32767);
          var absY = _remap(vidY, 0, geo.height - 1, -32768, 32767);
          session.sendMouseMove(absX, absY);
        }
        touchPos = pos;
      }
    }
  }

  function _touchEnd(ev) {
    ev.preventDefault();
    if (touchPos && ev.changedTouches.length === 1) {
      session.sendMouseButton("left", true);
      setTimeout(function() { session.sendMouseButton("left", false); }, 50);
    }
    touchPos = null;
  }

  function _getTouchPos(ev, index) {
    var touch = ev.touches[index];
    if (!touch) return null;
    var rect = overlay.getBoundingClientRect();
    return {
      x: Math.round(touch.clientX - rect.left),
      y: Math.round(touch.clientY - rect.top)
    };
  }

  // ── Planned move (throttled/squashed) ──

  function _sendPlannedMove() {
    if (pendingAbsPos) {
      session.sendMouseMove(pendingAbsPos.x, pendingAbsPos.y);
      pendingAbsPos = null;
    }
    if (pendingRelDelta) {
      if (pendingRelDelta.x || pendingRelDelta.y) {
        session.sendMouseRelative(pendingRelDelta.x, pendingRelDelta.y);
      }
      pendingRelDelta = null;
    }
  }

  // ── Utils ──

  function _remap(value, inMin, inMax, outMin, outMax) {
    var result = Math.round((value - inMin) * (outMax - outMin) / ((inMax - inMin) || 1) + outMin);
    return Math.min(Math.max(result, outMin), outMax);
  }

  // ── Cleanup ──
  self.destroy = function() {
    // Clear move timer
    if (moveTimer) {
      clearInterval(moveTimer);
      moveTimer = null;
    }
    // Release all pressed keys/buttons
    self.releaseAll();
    // Note: event listeners are bound to overlay element.
    // Removing overlay from DOM will GC them. No manual removal needed
    // unless overlay is reused without re-init.
    overlay = null;
    online = false;
    hidOnline = false;
  };
}

global.KVMindHID = KVMindHID;
console.log("[kvmind-hid] loaded");

})(typeof window !== "undefined" ? window : this);
