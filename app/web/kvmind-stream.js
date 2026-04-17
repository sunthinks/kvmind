/**
 * kvmind-stream.js -- KVM Video Stream (Three-Mode)
 *
 * Mode 1 (WebRTC): Janus gateway → janus.plugin.ustreamer → <video> → Canvas
 * Mode 2 (H.264):  WebSocket /api/media/ws + VideoDecoder → Canvas
 * Mode 3 (MJPEG):  HTTP MJPEG via hidden <img> → Canvas blit
 *
 * Auto mode priority: WebRTC > H.264 > MJPEG
 * User can override via setMode(). Preference persisted in localStorage.
 *
 * Provides getGeometry() for mouse coordinate conversion.
 */
(function(global) {
"use strict";

var is_https = (location.protocol === "https:");

var _STREAM_I18N = {
  zh: { webrtcConn: "WebRTC 连接中...", noWebRTC: "WebRTC 不可用", h264conn: "H.264 连接中...", noH264: "无 H.264", noDecoder: "不支持 VideoDecoder", mjpegConn: "MJPEG 连接中...", conn: "连接中...", noSig: "无信号" },
  ja: { webrtcConn: "WebRTC 接続中...", noWebRTC: "WebRTC 利用不可", h264conn: "H.264 接続中...", noH264: "H.264 利用不可", noDecoder: "VideoDecoder 非対応", mjpegConn: "MJPEG 接続中...", conn: "接続中...", noSig: "信号なし" },
  en: { webrtcConn: "WebRTC connecting...", noWebRTC: "WebRTC not available", h264conn: "H.264 connecting...", noH264: "No H.264 available", noDecoder: "VideoDecoder not supported", mjpegConn: "MJPEG connecting...", conn: "Connecting...", noSig: "No signal" }
};
function _st(k) { var l = localStorage.getItem("kvmind_lang") || "zh"; return (_STREAM_I18N[l] && _STREAM_I18N[l][k]) || _STREAM_I18N.en[k] || k; }

function KVMindStream() {
  var self = this;

  var canvas = null;
  var ctx = null;
  var fallbackImg = null;
  var infoEl = null;
  var noSignalEl = null;

  var resolution = { width: 640, height: 480 };
  var sourceOnline = false;
  var streamActive = false;

  // Mode preference: "auto", "webrtc", "media", "mjpeg"
  var preferredMode = localStorage.getItem("kvmind_stream_mode") || "auto";
  // Actual running mode: "webrtc", "media", "mjpeg", or ""
  var mode = "";

  // ── Stream URLs (loaded from /kdkvm/api/status, defaults match PiKVM paths) ──
  var streamUrls = {
    mjpeg: "/streamer/stream",
    h264_ws: "/api/media/ws",
    webrtc_ws: "/api/janus/ws",
    snapshot: "/streamer/snapshot"
  };

  // ── H.264 Media state ──
  var __stop = true;
  var __ensuring = false;
  var __ws = null;
  var __ping_timer = null;
  var __missed_heartbeats = 0;
  var __codec = "";
  var __decoder = null;
  var __frame = null;
  var __hwAcceleration = "no-preference";
  var __state = null;
  var __fps_accum = 0;

  // ── MJPEG fallback state ──
  var mjpegRafId = null;
  var mjpegFpsCount = 0;
  var mjpegFpsDisplay = 0;
  var mjpegFpsTimer = null;

  // ── WebRTC / Janus state ──
  var __janusSession = null;
  var __janusHandle = null;
  var __janusStop = true;
  var __rtcVideo = null;
  var __rtcAudio = null;       // Audio element for WebRTC audio playback
  var __rtcStream = null;
  var __rtcAudioStream = null;
  var __rtcRafId = null;
  var __rtcFpsCount = 0;
  var __rtcFpsDisplay = 0;
  var __rtcFpsTimer = null;
  var __janusInitDone = false;

  // ══════════════════════════════════════════════════════════════
  //  Init
  // ══════════════════════════════════════════════════════════════

  self.init = function() {
    canvas = document.getElementById("kvmind-stream-canvas");
    fallbackImg = document.getElementById("kvmind-stream-img");
    infoEl = document.getElementById("kvmind-stream-info");
    noSignalEl = document.getElementById("kvmind-no-signal");

    if (canvas) {
      ctx = canvas.getContext("2d");
    }

    // Fallback img events (for MJPEG mode)
    if (fallbackImg) {
      fallbackImg.addEventListener("load", function() {
        if (mode === "mjpeg") {
          streamActive = true;
          sourceOnline = true;
          if (fallbackImg.naturalWidth) {
            resolution = { width: fallbackImg.naturalWidth, height: fallbackImg.naturalHeight };
          }
          _updateUI();
        }
      });
      fallbackImg.addEventListener("error", function() {
        if (mode === "mjpeg") {
          streamActive = false;
          _updateUI();
          setTimeout(function() { if (mode === "mjpeg") _startMjpeg(); }, 2000);
        }
      });
    }

    // Create hidden <video> for WebRTC stream → canvas blit (muted: audio via separate element)
    __rtcVideo = document.createElement("video");
    __rtcVideo.autoplay = true;
    __rtcVideo.playsInline = true;
    __rtcVideo.muted = true;
    __rtcVideo.style.cssText = "position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;z-index:-1";
    document.body.appendChild(__rtcVideo);

    // Create hidden <audio> for WebRTC HDMI audio playback
    __rtcAudio = document.createElement("audio");
    __rtcAudio.autoplay = true;
    __rtcAudio.style.cssText = "display:none";
    document.body.appendChild(__rtcAudio);
  };

  // ══════════════════════════════════════════════════════════════
  //  Public API
  // ══════════════════════════════════════════════════════════════

  self.configure = function(urls) {
    if (urls && typeof urls === "object") {
      if (urls.mjpeg) streamUrls.mjpeg = urls.mjpeg;
      if (urls.h264_ws) streamUrls.h264_ws = urls.h264_ws;
      if (urls.webrtc_ws) streamUrls.webrtc_ws = urls.webrtc_ws;
      if (urls.snapshot) streamUrls.snapshot = urls.snapshot;
      _log("Stream URLs configured: " + JSON.stringify(streamUrls));
    }
  };

  self.startStream = function() {
    var target = preferredMode;
    if (target === "auto") {
      target = _resolveAutoMode();
    }
    _startMode(target);
  };

  self.stopStream = function() {
    _stopWebRTC();
    _stopMedia();
    _stopMjpeg();
    mode = "";
    streamActive = false;
    sourceOnline = false;
    _updateUI();
  };

  // Called from session.js on streamer state events
  self.setState = function(state) {
    if (!state) {
      sourceOnline = false;
      _updateUI();
      return;
    }
    if (state.source && state.source.online !== undefined) {
      sourceOnline = state.source.online;
    }
    if (state.source && state.source.resolution) {
      resolution = state.source.resolution;
    }
    if (mode === "media" || mode === "webrtc") {
      __state = state;
    }
    _updateUI();
  };

  self.getGeometry = function() {
    var el = canvas;
    if (!el || (!el.width && !el.offsetWidth)) {
      if (mode === "mjpeg" && fallbackImg && fallbackImg.naturalWidth) {
        el = fallbackImg;
      } else {
        return { x: 0, y: 0, width: resolution.width, height: resolution.height,
                 real_width: resolution.width, real_height: resolution.height };
      }
    }

    var realW, realH;
    if (el === canvas) {
      realW = canvas.width || canvas.offsetWidth;
      realH = canvas.height || canvas.offsetHeight;
    } else {
      realW = el.naturalWidth || resolution.width;
      realH = el.naturalHeight || resolution.height;
    }

    var viewW = el.offsetWidth;
    var viewH = el.offsetHeight;
    var ratio = Math.min(viewW / realW, viewH / realH);
    var renderW = Math.round(ratio * realW);
    var renderH = Math.round(ratio * realH);

    return {
      x: Math.round((viewW - renderW) / 2),
      y: Math.round((viewH - renderH) / 2),
      width: renderW, height: renderH,
      real_width: realW, real_height: realH
    };
  };

  self.isOnline = function() { return sourceOnline; };
  self.isActive = function() { return streamActive; };
  self.getMode = function() { return mode; };
  self.getPreferredMode = function() { return preferredMode; };

  self.setMode = function(m) {
    if (["auto","webrtc","media","mjpeg"].indexOf(m) === -1) return;
    preferredMode = m;
    localStorage.setItem("kvmind_stream_mode", m);
    self.refresh();
  };

  // Audio volume control (WebRTC mode only, 0.0 ~ 1.0)
  self.setVolume = function(v) {
    v = Math.max(0, Math.min(1, parseFloat(v) || 0));
    localStorage.setItem("kvmind_audio_volume", v);
    if (__rtcAudio) __rtcAudio.volume = v;
  };

  self.getVolume = function() {
    return parseFloat(localStorage.getItem("kvmind_audio_volume") || "0.5");
  };

  self.hasAudio = function() {
    return mode === "webrtc" && __rtcAudioStream !== null;
  };

  self.refresh = function() {
    self.stopStream();
    setTimeout(function() { self.startStream(); }, 200);
  };

  // ══════════════════════════════════════════════════════════════
  //  Mode resolution & switching
  // ══════════════════════════════════════════════════════════════

  function _resolveAutoMode() {
    // Priority: H.264 > WebRTC > MJPEG
    // H.264 WebSocket has lower latency than WebRTC for KVM use (no Janus relay overhead)
    if (global.VideoDecoder && is_https && canvas) return "media";
    if (global.Janus && global.RTCPeerConnection && is_https) return "webrtc";
    return "mjpeg";
  }

  function _startMode(target) {
    // Stop everything first
    _stopWebRTC();
    _stopMedia();
    _stopMjpeg();
    mode = "";

    if (target === "webrtc") {
      _startWebRTC();
    } else if (target === "media") {
      _startMedia();
    } else {
      _startMjpeg();
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  WebRTC via Janus (janus.plugin.ustreamer)
  // ══════════════════════════════════════════════════════════════

  function _startWebRTC() {
    if (!global.Janus) {
      _log("Janus library not loaded");
      _fallbackFromWebRTC();
      return;
    }
    mode = "webrtc";
    __janusStop = false;
    _showCanvas(true);
    _setInfo(_st("webrtcConn"));

    if (!__janusInitDone) {
      Janus.init({
        debug: false,
        callback: function() {
          __janusInitDone = true;
          if (!__janusStop) __connectJanus();
        }
      });
    } else {
      __connectJanus();
    }
  }

  function __connectJanus() {
    if (__janusStop) return;

    var proto = is_https ? "wss:" : "ws:";
    var wsUrl = proto + "//" + location.host + streamUrls.webrtc_ws;

    __janusSession = new Janus({
      server: wsUrl,
      iceServers: [],  // Local network, no STUN/TURN needed
      success: function() {
        _log("Janus session created");
        if (!__janusStop) __attachUstreamer();
      },
      error: function(err) {
        _log("Janus session error:", err);
        __cleanupJanus();
        _fallbackFromWebRTC();
      },
      destroyed: function() {
        _log("Janus session destroyed");
      }
    });
  }

  function __attachUstreamer() {
    if (__janusStop || !__janusSession) return;

    __janusSession.attach({
      plugin: "janus.plugin.ustreamer",
      opaqueId: "kvmind-" + Janus.randomString(12),

      success: function(handle) {
        _log("Attached to janus.plugin.ustreamer");
        __janusHandle = handle;
        handle.send({ message: { request: "watch" } });
      },

      error: function(err) {
        _log("Janus attach error:", err);
        __cleanupJanus();
        _fallbackFromWebRTC();
      },

      onmessage: function(msg, jsep) {
        if (jsep) {
          _log("Received JSEP offer from Janus");
          __janusHandle.createAnswer({
            jsep: jsep,
            tracks: [
              { type: "video", capture: false, recv: true },
              { type: "audio", capture: false, recv: true }
            ],
            success: function(ourJsep) {
              _log("Sending SDP answer to Janus");
              __janusHandle.send({
                message: { request: "start" },
                jsep: ourJsep
              });
            },
            error: function(err) {
              _log("createAnswer error:", err);
              __cleanupJanus();
              _fallbackFromWebRTC();
            }
          });
        }
      },

      onremotetrack: function(track, mid, added) {
        if (!added) return;

        if (track.kind === "audio") {
          _log("WebRTC remote audio track received, mid=" + mid);
          __rtcAudioStream = new MediaStream();
          __rtcAudioStream.addTrack(track);
          if (__rtcAudio) {
            __rtcAudio.srcObject = __rtcAudioStream;
            __rtcAudio.volume = self.getVolume();
            __rtcAudio.play().catch(function(e) {
              _log("Audio play error (user interaction may be required):", e);
            });
          }
          return;
        }

        if (track.kind !== "video") return;
        _log("WebRTC remote video track received, mid=" + mid);

        __rtcStream = new MediaStream();
        __rtcStream.addTrack(track);
        __rtcVideo.srcObject = __rtcStream;
        __rtcVideo.play().catch(function(e) {
          _log("Video play error:", e);
        });

        streamActive = true;
        sourceOnline = true;
        _updateUI();

        // Start canvas blit loop
        if (!__rtcRafId) _rtcBlitLoop();

        // Start FPS counter
        if (!__rtcFpsTimer) {
          __rtcFpsTimer = setInterval(function() {
            __rtcFpsDisplay = __rtcFpsCount;
            __rtcFpsCount = 0;
            if (streamActive && sourceOnline && mode === "webrtc") {
              _setInfo(resolution.width + "x" + resolution.height
                + " / " + __rtcFpsDisplay + " fps (WebRTC)");
            }
          }, 1000);
        }
      },

      oncleanup: function() {
        _log("Janus plugin cleanup");
        __rtcStream = null;
        __rtcAudioStream = null;
        if (__rtcVideo) __rtcVideo.srcObject = null;
        if (__rtcAudio) __rtcAudio.srcObject = null;
      }
    });
  }

  var __rtcLastTime = 0; // track video.currentTime to skip redundant draws

  function _rtcBlitLoop() {
    __rtcRafId = requestAnimationFrame(_rtcBlitLoop);
    if (!__rtcVideo || __rtcVideo.readyState < 2 || !canvas || !ctx) return;

    // Only draw when a new frame is available
    var t = __rtcVideo.currentTime;
    if (t === __rtcLastTime) return;
    __rtcLastTime = t;

    var w = __rtcVideo.videoWidth;
    var h = __rtcVideo.videoHeight;
    if (!w || !h) return;

    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      resolution = { width: w, height: h };
    }
    ctx.drawImage(__rtcVideo, 0, 0);
    __rtcFpsCount++;
  }

  function _stopWebRTC() {
    __janusStop = true;

    if (__rtcRafId) {
      cancelAnimationFrame(__rtcRafId);
      __rtcRafId = null;
    }
    if (__rtcFpsTimer) {
      clearInterval(__rtcFpsTimer);
      __rtcFpsTimer = null;
    }
    __rtcFpsCount = 0;
    __rtcFpsDisplay = 0;
    __rtcLastTime = 0;
    if (__rtcVideo) __rtcVideo.srcObject = null;
    if (__rtcAudio) __rtcAudio.srcObject = null;
    __rtcStream = null;
    __rtcAudioStream = null;

    __cleanupJanus();
  }

  function __cleanupJanus() {
    if (__janusHandle) {
      try { __janusHandle.detach(); } catch(e) {}
      __janusHandle = null;
    }
    if (__janusSession) {
      try { __janusSession.destroy({ cleanupHandles: true }); } catch(e) {}
      __janusSession = null;
    }
  }

  function _fallbackFromWebRTC() {
    if (preferredMode !== "auto") {
      // User explicitly chose WebRTC — show error, don't fallback
      _setInfo(_st("noWebRTC"));
      return;
    }
    // Auto mode: WebRTC is second priority, fallback to MJPEG
    _log("WebRTC unavailable, falling back to MJPEG");
    _startMjpeg();
  }

  // ══════════════════════════════════════════════════════════════
  //  H.264 Media WebSocket
  //  Faithfully ported from PiKVM stream_media.js
  // ══════════════════════════════════════════════════════════════

  function _startMedia() {
    mode = "media";
    __stop = false;
    _showCanvas(true);
    __ensureMedia(false);
  }

  function _stopMedia() {
    __stop = true;
    __ensuring = false;
    __wsForceClose();
  }

  function __ensureMedia(internal) {
    if (__ws !== null || __stop || (__ensuring && !internal)) return;
    __ensuring = true;
    streamActive = false;
    _setInfo(_st("h264conn"));
    _log("Starting Media ...");

    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + streamUrls.h264_ws;

    __ws = new WebSocket(url);
    __ws.binaryType = "arraybuffer";
    __ws.onopen = __wsOpenHandler;
    __ws.onerror = __wsErrorHandler;
    __ws.onclose = __wsCloseHandler;
    __ws.onmessage = function(ev) {
      try {
        if (typeof ev.data === "string") {
          var msg = JSON.parse(ev.data);
          __wsJsonHandler(msg.event_type, msg.event);
        } else {
          __wsBinHandler(ev.data);
        }
      } catch (ex) {
        __wsErrorHandler(ex);
      }
    };
  }

  function __wsOpenHandler() {
    _log("Media WS opened");
    __missed_heartbeats = 0;
    __ping_timer = setInterval(__ping, 1000);
  }

  function __ping() {
    try {
      __missed_heartbeats += 1;
      if (__missed_heartbeats >= 5) {
        throw new Error("Too many missed heartbeats");
      }
      __ws.send(new Uint8Array([0]));

      if (__decoder && __decoder.state === "configured") {
        var online = !!(__state && __state.source && __state.source.online);
        var info = __fps_accum + " fps (H.264)";
        __fps_accum = 0;
        sourceOnline = online || streamActive;
        streamActive = true;
        if (infoEl) infoEl.textContent = info;
        _updateUI();
      }
    } catch (ex) {
      console.error("Stream WS error:", ex);
      __wsErrorHandler("stream error");
    }
  }

  function __wsForceClose() {
    if (__ws) {
      __ws.onclose = null;
      __ws.close();
    }
    __wsCloseHandler(null);
    streamActive = false;
  }

  function __wsErrorHandler(ev) {
    _log("Media WS error:", ev);
    __wsForceClose();
  }

  function __wsCloseHandler() {
    if (__ping_timer) {
      clearInterval(__ping_timer);
      __ping_timer = null;
    }
    __closeDecoder();
    __missed_heartbeats = 0;
    __fps_accum = 0;
    __ws = null;
    if (!__stop) {
      setTimeout(function() { __ensureMedia(true); }, 1000);
    }
  }

  function __wsJsonHandler(ev_type, ev) {
    if (ev_type === "media") {
      __setupCodec(ev.video);
    }
  }

  function __setupCodec(formats) {
    __closeDecoder();
    if (!formats || formats.h264 === undefined) {
      _log("No H.264 stream available");
      _setInfo(_st("noH264"));
      return;
    }
    if (!window.VideoDecoder) {
      _log("VideoDecoder not supported");
      _setInfo(_st("noDecoder"));
      return;
    }
    __codec = "avc1." + formats.h264.profile_level_id;
    _log("H.264 codec:", __codec);

    // One-time async check for hardware-accelerated decoding support
    if (window.VideoDecoder && VideoDecoder.isConfigSupported) {
      VideoDecoder.isConfigSupported({
        codec: __codec,
        hardwareAcceleration: "prefer-hardware"
      }).then(function(result) {
        __hwAcceleration = result.supported ? "prefer-hardware" : "no-preference";
        _log("HW accel:", __hwAcceleration);
      }).catch(function() {
        __hwAcceleration = "no-preference";
      });
    }

    __ws.send(JSON.stringify({
      "event_type": "start",
      "event": {"type": "video", "format": "h264"}
    }));
  }

  function __wsBinHandler(data) {
    var header = new Uint8Array(data.slice(0, 2));
    if (header[0] === 255) { // Pong
      __missed_heartbeats = 0;
    } else if (header[0] === 1) { // Video frame
      var key = !!header[1];
      if (__ensureDecoder(key)) {
        __processFrame(key, data.slice(2));
      }
    }
  }

  function __ensureDecoder(key) {
    if (__codec === "") return false;

    if (__decoder === null || __decoder.state === "closed") {
      var savedCodec = __codec;
      __closeDecoder();
      __codec = savedCodec;
      __decoder = new VideoDecoder({
        "output": __renderFrame,
        "error": function(err) { console.error("Decoder error:", err); _log("Decoder error"); }
      });
      if (__ws && __ws.readyState === WebSocket.OPEN) {
        __ws.send(new Uint8Array([0]));
      }
    }

    if (__decoder.state !== "configured") {
      if (!key) return false;
      __decoder.configure({"codec": __codec, "optimizeForLatency": true, "hardwareAcceleration": __hwAcceleration});
    }

    if (__decoder.state === "configured") {
      streamActive = true;
      return true;
    }
    return false;
  }

  function __processFrame(key, raw) {
    // TCP Backpressure Recovery
    if (__decoder && __decoder.decodeQueueSize > 4) {
      if (!key) return;
      _log("Frame skip: queue=" + __decoder.decodeQueueSize + ", resetting decoder");
      var savedCodec = __codec;
      __closeDecoder();
      __codec = savedCodec;
      return;
    }

    var chunk = new EncodedVideoChunk({
      "timestamp": (performance.now() + performance.timeOrigin) * 1000,
      "type": (key ? "key" : "delta"),
      "data": raw
    });
    __decoder.decode(chunk);
  }

  function __closeDecoder() {
    if (__decoder !== null) {
      try {
        __decoder.close();
      } finally {
        __codec = "";
        __decoder = null;
        if (__frame !== null) {
          try { __frame.close(); } catch(e) {}
          __frame = null;
        }
      }
    }
  }

  function __renderFrame(frame) {
    if (__frame === null) {
      __frame = frame;
      window.requestAnimationFrame(__drawPendingFrame);
    } else {
      frame.close();
    }
  }

  function __drawPendingFrame() {
    if (__frame === null) return;
    try {
      var width = __frame.displayWidth;
      var height = __frame.displayHeight;

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        resolution = { width: width, height: height };
      }

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(__frame, 0, 0);
      __fps_accum += 1;
      streamActive = true;
      sourceOnline = true;
    } finally {
      __frame.close();
      __frame = null;
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  MJPEG Fallback (HTTP stream → hidden img → Canvas blit)
  // ══════════════════════════════════════════════════════════════

  function _startMjpeg() {
    mode = "mjpeg";
    _showCanvas(false);
    if (!fallbackImg) return;

    fallbackImg.src = streamUrls.mjpeg + "?t=" + Date.now();
    _setInfo(_st("mjpegConn"));

    // Blit img → canvas at display refresh rate
    if (canvas && ctx && !mjpegRafId) {
      _mjpegBlitLoop();
    }

    // FPS counter
    if (!mjpegFpsTimer) {
      mjpegFpsTimer = setInterval(function() {
        mjpegFpsDisplay = mjpegFpsCount;
        mjpegFpsCount = 0;
        if (streamActive && sourceOnline && mode === "mjpeg") {
          _setInfo(resolution.width + "x" + resolution.height + " / " + mjpegFpsDisplay + " fps (MJPEG)");
        }
      }, 1000);
    }
  }

  function _mjpegBlitLoop() {
    mjpegRafId = requestAnimationFrame(_mjpegBlitLoop);
    if (!fallbackImg || !fallbackImg.naturalWidth || !canvas || !ctx) return;

    var w = fallbackImg.naturalWidth;
    var h = fallbackImg.naturalHeight;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      resolution = { width: w, height: h };
    }
    ctx.drawImage(fallbackImg, 0, 0);
    mjpegFpsCount++;
  }

  function _stopMjpeg() {
    if (fallbackImg) fallbackImg.src = "";
    if (mjpegRafId) {
      cancelAnimationFrame(mjpegRafId);
      mjpegRafId = null;
    }
    if (mjpegFpsTimer) {
      clearInterval(mjpegFpsTimer);
      mjpegFpsTimer = null;
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  UI helpers
  // ══════════════════════════════════════════════════════════════

  function _showCanvas(mediaMode) {
    if (canvas) canvas.style.display = "block";
    if (fallbackImg) {
      if (mediaMode) {
        // Media/WebRTC mode: hide img entirely
        fallbackImg.style.display = "none";
      } else {
        // MJPEG mode: img loads stream but is visually hidden; canvas renders
        fallbackImg.style.display = "block";
        fallbackImg.style.position = "absolute";
        fallbackImg.style.width = "1px";
        fallbackImg.style.height = "1px";
        fallbackImg.style.opacity = "0";
        fallbackImg.style.pointerEvents = "none";
      }
    }
  }

  function _setInfo(text) {
    if (infoEl) infoEl.textContent = text;
  }

  function _updateUI() {
    if (noSignalEl) {
      noSignalEl.textContent = "\ud83d\udce1 " + _st("noSig");
      noSignalEl.style.display = (!sourceOnline && streamActive) ? "flex" : "none";
    }
    if (infoEl) {
      if (streamActive && sourceOnline) {
        infoEl.style.display = "block";
      } else if (!streamActive) {
        if (mode === "") {
          infoEl.textContent = _st("conn");
        }
        infoEl.style.display = "block";
      } else {
        infoEl.textContent = _st("noSig");
        infoEl.style.display = "block";
      }
    }
  }

  function _log() {
    var args = ["[KVMind Stream]"].concat(Array.prototype.slice.call(arguments));
    console.log.apply(console, args);
  }
}

global.KVMindStream = KVMindStream;
console.log("[kvmind-stream] loaded");

})(typeof window !== "undefined" ? window : this);
