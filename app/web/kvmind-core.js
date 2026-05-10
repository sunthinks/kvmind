/**
 * kvmind-core.js — KVMind Console Core Logic
 * 
 * Handles: i18n, themes, API calls, WebSocket, event binding,
 * chat, screenshots, analysis, keyboard overlay, logging.
 * 
 * DOM structure is in index.html. Styles are in kvmind.css.
 */
(function() {
"use strict";

// ── HTML escape helper (XSS prevention for dynamic API data) ──
function _escHtml(s){if(s==null)return"";var d=document.createElement("div");d.textContent=String(s);return d.innerHTML;}
window._escHtml=_escHtml; // expose for dashboard.html and other files

// Standalone mode

var KVMIND_API="/kdkvm";
var wsConn=null,agentMode="suggest",panelOpen=true,logCount=0,currentSubscription={plan:"free",messaging:false};

// ── i18n：本文件是注入到 PiKVM 控制台 /kvm/index.html 的 overlay，所以 i18n
//    命名空间名字叫 "kvm"；i18n 字典本身仍由 /kdkvm/kvmind-i18n.js 提供（KVMind
//    自己的资源全部在 /kdkvm/ 下，不部署到 /kvm/ 路径）。──
if(window.KVMindI18n&&window.KVMindI18n.init){try{window.KVMindI18n.init("kvm");}catch(e){}}

// Module-owned keys merged into the 'kvm' namespace via registerDict — keeps
// chat-overlay strings co-located with the code that uses them (chat sender
// label, error banners, AI error fallbacks, transient status messages) while
// flowing through the same KVMindI18n engine as the rest of the app.
if(window.KVMindI18n && typeof window.KVMindI18n.registerDict === "function"){
  window.KVMindI18n.registerDict("kvm", {
    zh: {
      chat_sender_user: "你",
      chat_err_device_unbound_title: "设备未绑定或签名被拒，请重新激活。",
      chat_err_device_unbound_cta: "前往激活",
      chat_err_rate_limit_title: "本次额度已用完。",
      chat_err_rate_limit_cta: "升级订阅",
      chat_err_schedule_title: "定时任务需要 Pro 订阅。",
      chat_err_schedule_cta: "升级 Pro",
      chat_err_budget_title: "本轮操作预算已用尽，请稍后再试。",
      chat_offline_unreachable_title: "MyClaw 服务连不上，请检查网络。",
      chat_offline_unreachable_cta: "重试",
      chat_offline_server_error_title: "MyClaw 服务器暂不可用，请稍后再试。",
      chat_offline_clock_skew_title: "设备时钟异常（签名超出 5 分钟窗口），请在系统设置检查 NTP。",
      ai_err_no_providers: "AI 未配置，请在设置中填入 API Key。",
      ai_err_ai_timeout: "AI 超时，请稍后重试。",
      ai_err_ai_connect: "无法连接 AI 服务。",
      ai_err_ai_empty: "AI 返回空结果，请重试。",
      ai_err_ai_no_tools: "当前模型不支持工具调用。",
      ai_err_ai_failed: "AI 请求失败。",
      ai_err_no_video: "无视频信号，请检查 HDMI。",
      msg_ai_disconnected: "⚠ AI 未连接，请刷新页面",
      msg_analysing: "分析中…",
      msg_screenshot_failed: "⚠ 截图获取失败",
    },
    ja: {
      chat_sender_user: "あなた",
      chat_err_device_unbound_title: "デバイス未連携または署名が拒否されました。再連携してください。",
      chat_err_device_unbound_cta: "アクティベーションへ",
      chat_err_rate_limit_title: "今回の使用枠を使い切りました。",
      chat_err_rate_limit_cta: "プランをアップグレード",
      chat_err_schedule_title: "スケジュールタスクには Pro プランが必要です。",
      chat_err_schedule_cta: "Pro にアップグレード",
      chat_err_budget_title: "本ターンの操作予算を使い切りました。しばらくしてから再度お試しください。",
      chat_offline_unreachable_title: "MyClaw に接続できません。ネットワークをご確認ください。",
      chat_offline_unreachable_cta: "再試行",
      chat_offline_server_error_title: "MyClaw サーバーが一時的に利用できません。後ほど再試行してください。",
      chat_offline_clock_skew_title: "デバイスの時刻が 5 分以上ずれています。NTP をご確認ください。",
      ai_err_no_providers: "AI が未設定です。",
      ai_err_ai_timeout: "AI タイムアウトしました。",
      ai_err_ai_connect: "AI に接続できません。",
      ai_err_ai_empty: "AI が空の応答を返しました。",
      ai_err_ai_no_tools: "現在のモデルはツール呼び出し未対応です。",
      ai_err_ai_failed: "AI リクエスト失敗。",
      ai_err_no_video: "ビデオ信号がありません。",
      msg_ai_disconnected: "⚠ AI 未接続です。ページを更新してください",
      msg_analysing: "分析中…",
      msg_screenshot_failed: "⚠ スクリーンショットの取得に失敗しました",
    },
    en: {
      chat_sender_user: "You",
      chat_err_device_unbound_title: "Device unbound or signature rejected — please re-activate.",
      chat_err_device_unbound_cta: "Activate",
      chat_err_rate_limit_title: "Usage quota reached.",
      chat_err_rate_limit_cta: "Upgrade plan",
      chat_err_schedule_title: "Scheduled tasks require Pro.",
      chat_err_schedule_cta: "Upgrade to Pro",
      chat_err_budget_title: "Operation budget exceeded — retry later.",
      chat_offline_unreachable_title: "MyClaw unreachable — check the network.",
      chat_offline_unreachable_cta: "Retry",
      chat_offline_server_error_title: "MyClaw server unavailable — retry later.",
      chat_offline_clock_skew_title: "Device clock drift exceeds 5 min — please check NTP.",
      ai_err_no_providers: "AI is not configured.",
      ai_err_ai_timeout: "AI request timed out.",
      ai_err_ai_connect: "Cannot reach AI service.",
      ai_err_ai_empty: "AI returned an empty response.",
      ai_err_ai_no_tools: "Current model does not support tool calls.",
      ai_err_ai_failed: "AI request failed.",
      ai_err_no_video: "No video signal.",
      msg_ai_disconnected: "⚠ AI not connected — please refresh the page",
      msg_analysing: "Analysing…",
      msg_screenshot_failed: "⚠ Screenshot capture failed",
    },
  });
}

function kvmindGetLang(){return (window.KVMindI18n && window.KVMindI18n.getLang()) || "zh";}
function kvmindT(k){return (window.KVMindI18n && window.KVMindI18n.t(k, null, "kvm")) || k;}
function kvmindApplyLang(){
var t=kvmindT;
var map={"kvmind-btn-snap":"snap","kvmind-btn-analyse":"analyse","kvmind-btn-copy":"copy","kvmind-btn-kb":"keyboard","kvmind-btn-term":"terminal","kvmind-btn-settings":"settings","kvmind-btn-power":"power","kvmind-btn-panel":"myclaw","kvmind-pm-suggest":"pmSuggest","kvmind-pm-auto":"pmAuto","kvmind-abort-mini":"abort","kvmind-char-hint":"sendHint","kvmind-send-btn":"send","kvmind-um-profile":"umProfile","kvmind-um-changepw":"umChangePw","kvmind-claw-ready":"clawReady","kvmind-claw-try":"clawTry","kvmind-claw-ex1":"clawEx1","kvmind-claw-ex2":"clawEx2","kvmind-claw-ex3":"clawEx3","kvmind-um-dashboard-text":"umDashboard","kvmind-um-theme-label":"umTheme","kvmind-um-lang-label":"umLang","kvmind-um-logout":"umLogout"};
for(var id in map){var el=document.getElementById(id);if(el)el.textContent=t(map[id]);}
// Update entitlement-dependent text (upgrade/subscription button + badge)
var _planBtn=document.getElementById("kvmind-btn-upgrade");
var _planText=document.getElementById("kvmind-um-upgrade-text");
if(currentSubscription.paid){
if(_planBtn)_planBtn.textContent=t("umSubscription");
if(_planText)_planText.textContent=t("umSubscription");
}else{
if(_planBtn)_planBtn.textContent=t("umUpgrade");
if(_planText)_planText.textContent=t("umUpgrade");
}
var ct=document.getElementById("kvmind-conn-text");
if(ct){var isOff=ct.textContent.indexOf("\u65ad")>=0||ct.textContent.indexOf("Disconn")>=0;ct.textContent=t(isOff?"disconnected":"connected");}
var qKeys=["qAnalyse","qError","qTerminal","qRestart","qDisk"];
document.querySelectorAll(".kvmind-quick-cmd").forEach(function(btn,i){if(qKeys[i])btn.textContent=t(qKeys[i]);});
var ci=document.getElementById("kvmind-chat-input");
// panel event interceptor moved to kvmindInit
if(ci)ci.placeholder=t("chatPH");
var ki=document.getElementById("kvmind-kb-input");if(ki)ki.placeholder=t("kbPH");
var sh=document.getElementById("kvmind-snap-hint");if(sh&&sh.style.display!=="none")sh.textContent=t("welcomeHint");
var kh=document.getElementById("kvmind-kb-hint");if(kh)kh.textContent=t("kbHint");
var lt=document.getElementById("kvmind-um-lang");if(lt)lt.value=kvmindGetLang();kvmindTranslateKVM();
var pwKeys=["powerOn","powerOff","restart","forceOff"];var pwIdx=0;
document.querySelectorAll(".kvmind-power-item").forEach(function(item){if(!item.classList.contains("kvmind-power-divider")){if(pwKeys[pwIdx])item.textContent=t(pwKeys[pwIdx]);pwIdx++;}});
document.querySelectorAll(".kvmind-settings-title").forEach(function(el){
if(el.textContent.match(/System/i))el.textContent=t("sysTitle");
if(el.textContent.match(/Keyboard|Text|键盘|キーボード/i))el.textContent=t("kbTitle");
});
}


// kvmd 设置菜单翻译（英文原文 → 本地化）：字典由 KVMindI18n._kvmdSettings 维护
function kvmindTranslateKVM(){
var lang=kvmindGetLang();
var menu=document.getElementById("kvmind-settings-menu");
if(!menu)return;
var xlate=function(orig){
if(window.KVMindI18n&&window.KVMindI18n.translateKvmdSetting){
var r=window.KVMindI18n.translateKvmdSetting(orig);
if(r!=null)return r;
}
return null;
};
// Translate <td>, <summary>, <b>, <sub>, <sup> text content (not inputs/selects)
var targets=menu.querySelectorAll("td,summary,b,sub,sup,div.text b");
targets.forEach(function(el){
if(el.tagName==="SELECT"||el.tagName==="INPUT"||el.tagName==="TEXTAREA")return;
if(el.children.length>0&&el.tagName!=="SUMMARY"&&el.tagName!=="B")return;
var txt=el.textContent.trim();
if(!txt||txt.length<2)return;
if(!el.getAttribute("data-kv-orig")){el.setAttribute("data-kv-orig",txt);}
var orig=el.getAttribute("data-kv-orig");
var tr=xlate(orig);
if(tr!=null){el.textContent=tr;}
else if(lang==="en"){el.textContent=orig;}
});
// Translate buttons: only if their text (without bullet) is in the dictionary
menu.querySelectorAll("button").forEach(function(el){
if(el.closest("#kvmind-toolbar"))return;
var raw=el.textContent.trim();
var hasBullet=raw.charAt(0)==="\u2022";
var clean=hasBullet?raw.replace(/^\u2022\s*/,""):raw;
if(!clean||clean.length<2)return;
if(!el.getAttribute("data-kv-orig")){el.setAttribute("data-kv-orig",clean);el.setAttribute("data-kv-bullet",hasBullet?"1":"0");}
var orig=el.getAttribute("data-kv-orig");
var useBullet=el.getAttribute("data-kv-bullet")==="1";
var tr=xlate(orig);
if(tr!=null){el.textContent=(useBullet?"\u2022 ":"")+tr;}
else if(lang==="en"){el.textContent=(useBullet?"\u2022 ":"")+orig;}
});
}

// ── Theme ──
var KVMIND_THEME_ORDER=["light","dark","kvmind-light","kvmind-dark"];
var KVMIND_THEME_ICONS={"light":"\u2600\ufe0f","dark":"\ud83c\udf19","kvmind-light":"\u26a1","kvmind-dark":"\ud83c\udf0a"};
function kvmindGetAutoTheme(){var h=new Date().getHours();return(h>=6&&h<18)?"light":"dark";}
function kvmindApplyTheme(t){if(KVMIND_THEME_ORDER.indexOf(t)<0)t="light";document.documentElement.setAttribute("data-theme",t);document.body.setAttribute("data-theme",t);var sel=document.getElementById("kvmind-um-theme");if(sel)sel.value=t;}
function kvmindOnThemeChange(sel){var t=sel.value;kvmindApplyTheme(t);try{localStorage.setItem("kvmind-theme",t);}catch(e){}}

// ── Device Info Dialog ──
function kvmindShowProfile(){
var existing=document.getElementById("kvmind-profile-dialog");if(existing)existing.remove();
var overlay=document.createElement("div");overlay.id="kvmind-profile-dialog";
overlay.style.cssText="position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45)";
var card=document.createElement("div");
card.style.cssText="background:var(--kvsurface);border:1px solid var(--kvborder-lt);border-radius:12px;padding:24px;min-width:340px;max-width:420px;box-shadow:0 12px 40px rgba(0,0,0,.2)";
card.innerHTML='<div style="text-align:center;color:var(--kvtext-muted);font-size:13px;padding:24px 0">Loading...</div>';
overlay.appendChild(card);document.body.appendChild(overlay);
overlay.addEventListener("click",function(e){if(e.target===overlay)overlay.remove();});
function _row(label,val,mono){return '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--kvborder)"><span style="color:var(--kvtext-muted)">'+_escHtml(label)+'</span><span style="'+(mono?'font-family:\'JetBrains Mono\',monospace;font-size:12px':'')+'">'+val+'</span></div>';}
function _badge(text,color){return '<span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;background:'+_escHtml(color)+'20;color:'+_escHtml(color)+'">'+_escHtml(text)+'</span>';}
Promise.all([
fetch(KVMIND_API+"/api/device/uid").then(function(r){return r.json();}),
fetch(KVMIND_API+"/api/ai/config").then(function(r){return r.json();}),
fetch(KVMIND_API+"/api/status").then(function(r){return r.json();}),
fetch("/kdkvm/version.json?t="+Date.now()).then(function(r){return r.json();}).catch(function(){return {};}),
fetch(KVMIND_API+"/api/update/status").then(function(r){return r.json();}).catch(function(){return {};})
]).then(function(results){
var uid=results[0].uid||"\u2014";
var aiCfg=results[1]||{};
var status=results[2]||{};
var verInfo=results[3]||{};
var updateInfo=results[4]||{};
var sub=aiCfg.subscription||{};
currentSubscription={paid:sub.entitlement_state==="paid",messaging:!!sub.messaging};
var planInfo=currentSubscription.paid?["Paid","#3ecf8e"]:["Free","#6b7280"];
var kvmOk=(status.kvm||status.pikvm)==="ok";
if(status.stream_urls&&window.KVMStream){window.KVMStream.configure(status.stream_urls);}
var bridgeOk=status.bridge==="ok";
var mode=aiCfg.mode||status.mode||"suggest";
var providerCount=(aiCfg.active_providers||[]).length;
var providerNames=(aiCfg.active_providers||[]).join(", ")||"\u2014";
var model=aiCfg.model||"\u2014";
var fwVer=verInfo.version||"unknown";
var fwBuild=verInfo.build||"";
var hasUpdate=updateInfo.status==="available";
var latestVer=updateInfo.latest_version||"";
var changelog=updateInfo.changelog||"";
var fwDisplay="v"+_escHtml(fwVer)+(_escHtml(fwBuild)?" ("+_escHtml(fwBuild)+")":"");
var fwVal=hasUpdate?fwDisplay+' <span style="color:#ef4444;font-size:11px;margin-left:4px">\u2192 v'+_escHtml(latestVer)+'</span>':fwDisplay;
// 头部：图标 + 标题
card.innerHTML='<div style="text-align:center;margin-bottom:16px">'
+'<div style="width:48px;height:48px;border-radius:14px;background:var(--kvaccent-dim);color:var(--kvaccent);display:flex;align-items:center;justify-content:center;font-size:24px;margin:0 auto 8px">💻</div>'
+'<div style="font-size:15px;font-weight:600;color:var(--kvtext)">'+_escHtml(kvmindT("pfDeviceInfo"))+'</div>'
+'</div>'
// 核心组：UID（带复制按钮）/ 订阅 / 固件
+'<div style="display:flex;flex-direction:column;font-size:13px;color:var(--kvtext);margin-bottom:8px">'
+'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--kvborder)">'
+'<span style="color:var(--kvtext-muted)">'+_escHtml(kvmindT("pfDeviceUid"))+'</span>'
+'<span style="display:flex;align-items:center;gap:6px">'
+'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px">'+_escHtml(uid)+'</span>'
+'<button id="kvmind-pf-copy-uid" title="'+_escHtml(kvmindT("pfCopyUid"))+'" style="border:none;background:transparent;cursor:pointer;color:var(--kvtext-muted);padding:2px 6px;border-radius:4px;font-size:14px;line-height:1">📋</button>'
+'</span></div>'
+_row(kvmindT("pfPlan"),_badge(planInfo[0],planInfo[1]))
+_row(kvmindT("pfFirmware"),fwVal)
+'</div>'
// 升级提示框
+(hasUpdate?'<div id="kvmind-update-section" style="margin-top:8px;padding:12px;border:1px solid rgba(59,130,246,.3);border-radius:8px;background:rgba(59,130,246,.05)">'
+'<div style="font-size:12px;font-weight:600;color:var(--kvtext);margin-bottom:4px">'+kvmindT("updateNewVer")+' v'+_escHtml(latestVer)+'</div>'
+(changelog?'<div style="font-size:11px;color:var(--kvtext-muted);margin-bottom:10px">'+_escHtml(changelog)+'</div>':'')
+'<button id="kvmind-update-btn" style="width:100%;padding:8px 0;border:none;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer;font-size:13px;font-weight:600">'+kvmindT("updateBtn")+'</button>'
+'</div>':'')
// 折叠：技术详情
+'<details style="margin-top:10px"><summary style="cursor:pointer;color:var(--kvtext-muted);font-size:12px;padding:4px 0;list-style:none;user-select:none">▸ '+_escHtml(kvmindT("pfTechDetails"))+'</summary>'
+'<div style="margin-top:6px;font-size:13px;color:var(--kvtext)">'
+_row("AI Provider",_escHtml(providerNames),false)
+_row("Model",_escHtml(model),true)
+_row("Mode",'<span style="text-transform:capitalize">'+_escHtml(mode)+'</span>',false)
+_row("Bridge",bridgeOk?_badge("Online","#3ecf8e"):_badge("Offline","#ef5350"))
+_row(status.backend||"KVM",kvmOk?_badge("Online","#3ecf8e"):_badge("Offline","#ef5350"))
+'</div></details>'
+'<button id="kvmind-profile-close" style="margin-top:'+(hasUpdate?'10':'14')+'px;width:100%;padding:8px 0;border:1px solid var(--kvborder);border-radius:6px;background:var(--kvsurface2);color:var(--kvtext);cursor:pointer;font-size:13px">OK</button>';
document.getElementById("kvmind-profile-close").addEventListener("click",function(){overlay.remove();});
// 复制 UID 处理
var copyUidBtn=document.getElementById("kvmind-pf-copy-uid");
if(copyUidBtn)copyUidBtn.addEventListener("click",function(){
    var doneFlash=function(){var orig=copyUidBtn.textContent;copyUidBtn.textContent="✓";copyUidBtn.style.color="var(--kvgreen)";setTimeout(function(){copyUidBtn.textContent=orig;copyUidBtn.style.color="";},1500);};
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(uid).then(doneFlash).catch(function(){});}
    else{var ta=document.createElement("textarea");ta.value=uid;ta.style.position="fixed";ta.style.left="-9999px";document.body.appendChild(ta);ta.select();try{document.execCommand("copy");doneFlash();}catch(e){}document.body.removeChild(ta);}
});
if(hasUpdate){
var ubtn=document.getElementById("kvmind-update-btn");
if(ubtn)ubtn.addEventListener("click",function(){
ubtn.disabled=true;ubtn.textContent=kvmindT("updateInstalling");ubtn.style.opacity="0.6";
fetch(KVMIND_API+"/api/update/apply",{method:"POST",credentials:"same-origin"}).then(function(r){return r.json();}).then(function(){
ubtn.textContent=kvmindT("updateStarted");
setTimeout(function(){
var dots=0;var pollCount=0;var poll=setInterval(function(){
dots++;pollCount++;ubtn.textContent=kvmindT("updateWait")+".".repeat(dots%4);
fetch(KVMIND_API+"/api/update/status").then(function(r){return r.json();}).then(function(s){
if(s.status==="updated"){clearInterval(poll);ubtn.textContent=kvmindT("updateDone");ubtn.style.background="#3ecf8e";setTimeout(function(){location.reload();},2000);}
else if(s.status==="error"||s.status==="rollback"){clearInterval(poll);ubtn.textContent=kvmindT("updateFailed");ubtn.style.background="#ef4444";}
else if(s.status==="updating"&&pollCount>5){
fetch("/kdkvm/version.json?t="+Date.now()).then(function(r2){return r2.json();}).then(function(v){
if(v.build&&v.build!==fwBuild){clearInterval(poll);ubtn.textContent=kvmindT("updateDone");ubtn.style.background="#3ecf8e";setTimeout(function(){location.reload();},2000);}
}).catch(function(e){console.warn("[kvmind]",e);});}
}).catch(function(){
if(pollCount>5){fetch("/kdkvm/version.json?t="+Date.now()).then(function(r2){return r2.json();}).then(function(v){
if(v.build&&v.build!==fwBuild){clearInterval(poll);ubtn.textContent=kvmindT("updateDone");ubtn.style.background="#3ecf8e";setTimeout(function(){location.reload();},2000);}
}).catch(function(e){console.warn("[kvmind]",e);});}
});
},3000);
},2000);
}).catch(function(){ubtn.textContent=kvmindT("updateFailed");ubtn.style.background="#ef4444";});
});
}
}).catch(function(){
card.innerHTML='<div style="color:var(--kvtext);font-size:14px;font-weight:600;margin-bottom:8px">Device Info</div>'
+'<div style="color:var(--kvtext-muted);font-size:13px">Could not load device info</div>'
+'<button id="kvmind-profile-close" style="margin-top:16px;width:100%;padding:8px 0;border:1px solid var(--kvborder);border-radius:6px;background:var(--kvsurface2);color:var(--kvtext);cursor:pointer;font-size:13px">OK</button>';
document.getElementById("kvmind-profile-close").addEventListener("click",function(){overlay.remove();});
});
}

// ── Fetch ──
function kvmindFetch(path,opts){return fetch(KVMIND_API+path,opts);}

// ── Connection ──
// 3 态融合：connected · 画面正常 / connected · 等待画面 / disconnected
// 视频流状态从 #kvmind-no-signal 元素的可见性推断（kvmind-stream.js 控制）
function kvmindCheckStatus(){
    kvmindFetch("/api/status").then(function(r){return r.json();}).then(function(){
        var noSig=document.getElementById("kvmind-no-signal");
        var hasSignal=!noSig||noSig.style.display==="none"||noSig.style.display==="";
        // 仅当 noSig 元素显式 inline display !== "none" 时认为无信号
        var visible=noSig&&noSig.style.display&&noSig.style.display!=="none";
        kvmindSetConn(visible?"no-signal":"connected");
    }).catch(function(){kvmindSetConn("disconnected");});
    kvmindSyncPlan();
}
function kvmindSyncPlan(){fetch(KVMIND_API+"/api/subscription").then(function(r){return r.json();}).then(function(sub){var paid=sub.entitlement_state==="paid";var claimed=sub.claim_state==="claimed";if(paid!==currentSubscription.paid||claimed!==currentSubscription.claimed){currentSubscription={paid:paid,messaging:!!sub.messaging,claimed:claimed};kvmindUpdatePlanUI(paid);}}).catch(function(e){console.warn("[kvmind]",e);});}
function kvmindSetConn(state){
    var el=document.getElementById("kvmind-conn-status");
    var txt=document.getElementById("kvmind-conn-text");
    if(!el)return;
    // 兼容旧 boolean 入参
    if(state===true)state="connected"; else if(state===false)state="disconnected";
    var stateMap={
        "connected":   {cls:"online",    key:"connStatusOk"},
        "no-signal":   {cls:"no-signal", key:"connStatusNoSignal"},
        "disconnected":{cls:"offline",   key:"connStatusOffline"}
    };
    var s=stateMap[state]||stateMap["disconnected"];
    el.className=s.cls;
    txt.textContent=kvmindT(s.key);
}
function kvmindUpdatePlanUI(paid){
    var btn=document.getElementById("kvmind-btn-upgrade");
    var umUpgrade=document.getElementById("kvmind-um-upgrade");
    var umText=document.getElementById("kvmind-um-upgrade-text");
    var badge=document.getElementById("kvmind-plan-badge");
    var label=paid?"Paid":"Free";
    var color=paid?"#3ecf8e":"#6b7280";
    if(badge){badge.textContent=label;badge.style.background=color;}
    // 设备绑定状态：参考 umProfile 模式，文案后追加状态后缀（✓ 绿 / ⚠ 红）
    var claimText=document.getElementById("kvmind-um-claim-text");
    if(claimText){
        var claimKey,statusColor="";
        if(currentSubscription.claimed===true){claimKey="umClaimBound";statusColor="var(--kvgreen)";}
        else if(currentSubscription.claimed===false){claimKey="umClaimUnbound";statusColor="var(--kvred)";}
        else{claimKey="umClaim";}
        claimText.setAttribute("data-i18n",claimKey);
        var raw=kvmindT(claimKey);
        if(statusColor){
            // i18n 文案是受控字符串，仅 ✓/⚠ 符号被 span 包色，其余 textContent 安全
            claimText.innerHTML=raw
                .replace("✓",'<span style="color:'+statusColor+';font-weight:700">✓</span>')
                .replace("⚠",'<span style="color:'+statusColor+';font-weight:700">⚠</span>');
        }else{
            claimText.textContent=raw;
        }
    }
    if(!paid){
        // Free：顶栏「⚡ 升级订阅」CTA 显示，引导到 pricing；菜单项「订阅」也指向 pricing
        if(btn){btn.style.display="";btn.textContent=kvmindT("umUpgrade");btn.style.background="#f59e0b";btn.href="https://kvmind.com/pricing";}
        if(umText)umText.textContent=kvmindT("umSubscription");
        if(umUpgrade){umUpgrade.style.display="";umUpgrade.href="https://kvmind.com/pricing";}
    }else{
        // Paid：顶栏 CTA 隐藏（避免与菜单重复），菜单项「订阅」指向 account 看详情
        if(btn){btn.style.display="none";}
        if(umText)umText.textContent=kvmindT("umSubscription");
        if(umUpgrade){umUpgrade.style.display="";umUpgrade.href="https://kvmind.com/account";}
    }
    kvmindUpdateModeTooltip(paid);
}

// 聊天面板 [💡 Suggest] [⚡ Auto] 模式按钮 tooltip + Free 用户 Auto 锁标
function kvmindUpdateModeTooltip(paid){
    var pmSuggest=document.getElementById("kvmind-pm-suggest");
    var pmAuto=document.getElementById("kvmind-pm-auto");
    if(pmSuggest)pmSuggest.title=kvmindT("pmSuggestTooltip");
    if(pmAuto){
        pmAuto.title=paid?kvmindT("pmAutoTooltip"):kvmindT("pmAutoLockTooltip");
        var hasLock=pmAuto.classList.contains("kv-pm-locked");
        if(paid&&hasLock)pmAuto.classList.remove("kv-pm-locked");
        else if(!paid&&!hasLock)pmAuto.classList.add("kv-pm-locked");
    }
}

// ── WebSocket ──
var _wsReconnectAttempts=0;
function _wsScheduleReconnect(){
var delay=Math.min(1000*Math.pow(1.5,_wsReconnectAttempts),30000);
delay+=Math.random()*1000;
_wsReconnectAttempts++;
setTimeout(kvmindConnectWS,delay);
}
function kvmindConnectWS(){
var proto=location.protocol==="https:"?"wss:":"ws:";
try{wsConn=new WebSocket(proto+"//"+location.host+"/kdkvm/ws/agent");
wsConn.onopen=function(){_wsReconnectAttempts=0;kvmindAddLog("ok","WebSocket connected");};
wsConn.onmessage=function(e){try{kvmindHandleWSMsg(JSON.parse(e.data));}catch(err){console.warn("WS message parse error:",err);}};
wsConn.onclose=function(){kvmindAddLog("warn","WebSocket closed, reconnecting...");_wsScheduleReconnect();};
wsConn.onerror=function(){};
}catch(e){_wsScheduleReconnect();}
}

// Unified chat lifecycle cleanup — called by ALL terminal events
function _endChat(){
if(window._kvmindAgentTimeout){clearTimeout(window._kvmindAgentTimeout);window._kvmindAgentTimeout=null;}
window._kvmindStreaming=false;
var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.remove("show");
var sb=document.querySelector(".kvmind-chat-msg.ai.streaming");if(sb)sb.classList.remove("streaming");
}

function kvmindHandleWSMsg(msg){
var ev=msg.event||msg.type||"";
// Agent WS: device status events only (AI chat events flow exclusively via Gateway WS)
if(ev==="action_start"){if(msg.action==="thinking"){var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent=kvmindT("aiWorking");}else{kvmindAppendMsg("action","\u25b6 "+msg.action);var sb=document.getElementById("kvmind-ai-step-badge");if(sb&&msg.step)sb.textContent=(msg.step||0)+"/30";}}
else if(ev==="action_done"){kvmindAddLog("ok","\u2713 "+(msg.action||""));}
else if(ev==="action_error"){kvmindAppendMsg("action","\u2717 "+(msg.action||"")+": "+(msg.error||""),null,"err");}
}

// ── Chat ──
function kvmindAppendMsg(role,text,status,extraClass){
var c=document.getElementById("kvmind-chat-messages");if(!c)return;
var row=document.createElement("div");row.className="kvmind-msg-row "+role;
if(role==="user"||role==="ai"){var s=document.createElement("div");s.className="kvmind-msg-sender";if(role==="user"){s.setAttribute("data-i18n","chat_sender_user");s.textContent=kvmindT("chat_sender_user");}else{s.textContent="MyClaw";}row.appendChild(s);}
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg "+role;
if(extraClass)bubble.classList.add(extraClass);if(status)bubble.classList.add(status);
bubble.textContent=text;row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
}

function kvmindAppendNotice(notice){
var c=document.getElementById("kvmind-chat-messages");if(!c)return;
var row=document.createElement("div");row.className="kvmind-msg-row ai";
var s=document.createElement("div");s.className="kvmind-msg-sender";s.textContent="MyClaw";row.appendChild(s);
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg notice";
if(notice&&notice.code)bubble.setAttribute("data-notice-code",notice.code);
var icon=document.createElement("span");icon.className="kvmind-notice-icon";icon.textContent="\u26a0\ufe0f";
var body=document.createElement("span");body.className="kvmind-notice-body";body.textContent=(notice&&notice.message)||"";
bubble.appendChild(icon);bubble.appendChild(body);row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
kvmindAddLog("warn","notice: "+((notice&&notice.code)||"generic"));
}

// ── V6 Gateway error → CTA bubble ────────────────────────────────────────
// Contract: see dev/kdcms/api-spec/error-codes.md. The three pipeline layers
// (kdcms → kdkvm → this UI) must match 1:1; editing the table below without
// updating websocket.py / DeviceSigFilter.java will break the UX.
//
// Each entry provides (a) a localized {title} for the bubble and (b) an
// optional {cta} with localized {label} and {action}. Actions:
//   - "href:<url>"   — anchor click to URL (new tab allowed)
//   - "retry"        — resend window._kvLastChatText via the gateway
//   - null           — no button, text-only bubble (used for advisory codes)
// Code → i18n key + action. The strings themselves live in the 'kvm'
// namespace registered via registerDict at the top of this file. Keeping
// the routing table here lets the dispatch logic stay code-driven (one
// entry per known error code) while string lookups flow through the
// shared KVMindI18n engine — language switches automatically picked up.
var _KV_CHAT_ERROR_TEXTS = {
  // HTTP 401 family → re-activate CTA. invalid_signature / unknown_device_uid /
  // replay / unsupported_sig_version all share the same remediation.
  device_unbound: {
    title_key: "chat_err_device_unbound_title",
    cta: {label_key: "chat_err_device_unbound_cta", action: "href:/activate.html"},
  },
  // HTTP 429 → Upgrade CTA. retry_after seconds is appended to the title.
  myclaw_rate_limit: {
    title_key: "chat_err_rate_limit_title",
    cta: {label_key: "chat_err_rate_limit_cta", action: "href:https://kvmind.com/pricing"},
  },
  // HTTP 403 schedule_not_allowed → Pro upgrade. PolicyError.code is carried
  // in the WS code suffix so this dispatch needs one entry per known slug.
  myclaw_forbidden_schedule_not_allowed: {
    title_key: "chat_err_schedule_title",
    cta: {label_key: "chat_err_schedule_cta", action: "href:https://kvmind.com/pricing"},
  },
  // Budget is a transient ceiling (per-turn), not a plan limit — no upsell.
  myclaw_forbidden_budget_exceeded: {
    title_key: "chat_err_budget_title",
    cta: null,
  },
  // myclaw_offline is handled specially below because the CTA depends on
  // err.reason (unreachable/server_error/clock_skew), not just the code.
};

// myclaw_offline sub-reason → localized CTA. Kept separate so the reason
// dispatch has one place to live.
var _KV_CHAT_OFFLINE_TEXTS = {
  unreachable: {
    title_key: "chat_offline_unreachable_title",
    cta: {label_key: "chat_offline_unreachable_cta", action: "retry"},
  },
  server_error: {
    title_key: "chat_offline_server_error_title",
    cta: null,
  },
  clock_skew: {
    title_key: "chat_offline_clock_skew_title",
    cta: null,
  },
};

// Build and return the {title, cta} bundle for a given err payload, or null
// if we don't know the code. Callers decide how to render / fall back.
function _kvResolveChatError(err){
  if(!err||typeof err!=="object")return null;
  var entry;
  if(err.code==="myclaw_offline"){
    var reason = err.reason || "unreachable";
    entry = _KV_CHAT_OFFLINE_TEXTS[reason] || _KV_CHAT_OFFLINE_TEXTS.unreachable;
  } else {
    entry = _KV_CHAT_ERROR_TEXTS[err.code];
  }
  if(!entry) return null;
  return {
    title: kvmindT(entry.title_key),
    cta: entry.cta ? {label: kvmindT(entry.cta.label_key), action: entry.cta.action} : null,
  };
}

function kvmindAppendChatError(err){
  // Gateway layer (myclaw-gateway.js) owns reconnection; ws_not_open is a
  // transient device-side state that deserves a simpler text bubble instead
  // of a branded CTA — the reconnect is automatic.
  if(err&&err.code==="ws_not_open"){
    var t = kvmindT("wsReconnecting")||"Reconnecting — please try again in a moment.";
    kvmindAppendMsg("system","\u26a0 "+t);
    kvmindAddLog("warn","ws_not_open");
    return;
  }
  var bundle = _kvResolveChatError(err);
  // Unknown code → server-localized fallback (backend always ships a
  // `message` field), or the raw code if nothing else is available.
  if(!bundle){
    var fallback = (err&&err.message) || (err&&err.code&&_kvAiErrorText(err.code)) || "unknown error";
    kvmindAppendMsg("system","\u26a0 "+fallback);
    kvmindAddLog("error",(err&&err.code)||"unknown");
    return;
  }

  var c=document.getElementById("kvmind-chat-messages");if(!c){kvmindAddLog("error",err.code);return;}
  var row=document.createElement("div");row.className="kvmind-msg-row ai";
  var bubble=document.createElement("div");bubble.className="kvmind-chat-msg err";
  bubble.setAttribute("data-err-code",err.code||"");
  if(err.reason)bubble.setAttribute("data-err-reason",err.reason);

  var head=document.createElement("div");head.className="kvmind-err-head";
  var icon=document.createElement("span");icon.className="kvmind-err-icon";icon.textContent="\u26a0\ufe0f";
  var title=document.createElement("span");title.className="kvmind-err-title";
  // For rate limit, prefer the server-formatted message (it already carries
  // the localized X/Y count + retry_after seconds, e.g. "MyClaw 使用已达上限
  // (5/5)，3600 秒后重试"). The bundle.title is a stripped fallback used only
  // when the server didn't include a message. Either way the bundle.cta
  // ("升级订阅") still gets attached below.
  var titleText = bundle.title;
  if(err.code==="myclaw_rate_limit"){
    if(err.message){
      titleText = err.message;
    } else if(err.retry_after){
      titleText += " ("+err.retry_after+"s)";
    }
  }
  title.textContent = titleText;
  head.appendChild(icon);head.appendChild(title);
  bubble.appendChild(head);

  if(bundle.cta){
    var btn=document.createElement("button");
    btn.type="button";
    btn.className="kvmind-err-cta";
    btn.textContent=bundle.cta.label;
    var action=bundle.cta.action||"";
    if(action.indexOf("href:")===0){
      var url=action.substring(5);
      btn.addEventListener("click",function(){
        try{
          if(url.charAt(0)==="/"){ window.location.assign(url); }
          else{ window.open(url,"_blank","noopener,noreferrer"); }
        }catch(e){ console.warn("[kvmind] err cta open:",e); }
      });
    }else if(action==="retry"){
      btn.addEventListener("click",function(){
        var last = window._kvLastChatText;
        if(!last||!window._kvGw){ kvmindAddLog("warn","retry: nothing to resend"); return; }
        kvmindAppendMsg("user",last);
        var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");
        var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent=kvmindT("aiWorking");
        window._kvGw.sendChat(last,{mode:typeof agentMode!=="undefined"?agentMode:"suggest",lang:kvmindGetLang()});
        btn.disabled=true;btn.classList.add("disabled");
      });
    }
    bubble.appendChild(btn);
  }
  row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
  kvmindAddLog("error",(err.code||"")+(err.reason?":"+err.reason:""));
}

function kvmindShowToast(message,opts){
opts=opts||{};
var severity=opts.severity||"info";
var host=document.getElementById("kvmind-toast-host");
if(!host){host=document.createElement("div");host.id="kvmind-toast-host";
host.style.cssText="position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:10000;display:flex;flex-direction:column;gap:8px;pointer-events:none";
document.body.appendChild(host);}
var toast=document.createElement("div");
toast.className="kvmind-toast kvmind-toast-"+severity;
var msg=document.createElement("span");msg.className="kvmind-toast-msg";msg.textContent=message;
var close=document.createElement("button");close.type="button";close.className="kvmind-toast-close";close.setAttribute("aria-label","Close");close.textContent="×";
toast.appendChild(msg);toast.appendChild(close);
host.appendChild(toast);
var dismissed=false;
function dismiss(){if(dismissed)return;dismissed=true;toast.style.transition="opacity .2s";toast.style.opacity="0";setTimeout(function(){if(toast.parentNode)toast.parentNode.removeChild(toast);},220);}
close.addEventListener("click",dismiss);
var timer=setTimeout(dismiss,opts.duration||5000);
// hover 暂停自动消失（防止用户读到一半被关掉）
toast.addEventListener("mouseenter",function(){if(!dismissed)clearTimeout(timer);});
toast.addEventListener("mouseleave",function(){if(!dismissed)timer=setTimeout(dismiss,2000);});
}
window.kvmindShowToast=kvmindShowToast;

function kvmindShowConfirm(text,cid,runId){
var c=document.getElementById("kvmind-chat-messages");if(!c)return;
var row=document.createElement("div");row.className="kvmind-msg-row ai";
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg warn-confirm";
var warnText=document.createTextNode("\u26a0\ufe0f ");bubble.appendChild(warnText);var msgSpan=document.createElement("span");msgSpan.textContent=text;bubble.appendChild(msgSpan);var btnsDiv=document.createElement("div");btnsDiv.className="kvmind-confirm-btns";var noBtn=document.createElement("button");noBtn.className="kvmind-confirm-btn no";noBtn.textContent="\u2717";var yesBtn=document.createElement("button");yesBtn.className="kvmind-confirm-btn yes";yesBtn.textContent="\u2713";btnsDiv.appendChild(noBtn);btnsDiv.appendChild(yesBtn);bubble.appendChild(btnsDiv);
row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
bubble.querySelector(".yes").onclick=function(){kvmindDoConfirm(cid,true,bubble,runId);};
bubble.querySelector(".no").onclick=function(){kvmindDoConfirm(cid,false,bubble,runId);};
}

function kvmindDoConfirm(id,approved,bubble,runId){
if(bubble){var btns=bubble.querySelector(".kvmind-confirm-btns");if(btns)btns.remove();var r=document.createElement("div");r.style.cssText="margin-top:6px;font-size:11px;font-weight:600";r.textContent=approved?"\u26a1 Approved":"\u2717 Denied";bubble.appendChild(r);bubble.style.opacity=".6";}
if(id&&id.startsWith("power-")&&approved){var act=id.replace("power-","");kvmindFetch("/api/atx/power",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:act})});}
}

// ── Send ──
function kvmindDoSend(){
var inp=document.getElementById("kvmind-chat-input");if(!inp)return;var text=inp.value.trim();if(!text)return;
// PR#3: remember the last user input so myclaw_offline/unreachable error
// bubbles can offer a one-click "Retry" without the user re-typing.
window._kvLastChatText=text;
kvmindAppendMsg("user",text);inp.value="";kvmindAddLog("info","CMD: "+text.slice(0,60));
var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");
var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent=kvmindT("aiWorking");
// No client-side timeout — server budget (300s) is authoritative.
// Server sends task_error when budget exhausted; client just responds.
// Send via Gateway WebSocket
if(window._kvGw&&window._kvGw.connected){
window._kvGw.sendChat(text,{mode:agentMode,lang:kvmindGetLang()});
}else{
var ab3=document.getElementById("kvmind-ai-bar");if(ab3)ab3.classList.remove("show");
kvmindAppendMsg("system",kvmindT("msg_ai_disconnected"));
}
}

// ── Toolbar button loading state ──
function kvmindSetBtnLoading(id,on){var b=document.getElementById(id);if(!b)return;if(on){b.classList.add("loading");b.setAttribute("disabled","disabled");}else{b.classList.remove("loading");b.removeAttribute("disabled");}}

// ── AI error fallback (if backend didn't provide a message) ──
// Used as defense-in-depth — backend already localizes via lang param.
function _kvAiErrorText(code,fallback){
// Strings live in the 'kvm' namespace (registered at top), prefixed
// "ai_err_" — language switches propagate automatically.
var key = "ai_err_" + code;
var v = kvmindT(key);
return (v && v !== key) ? v : (fallback || code);
}

// Unified response parser for REST AI endpoints.
// Returns {ok:true, data} on success, {ok:false, code, message} on failure.
function _kvParseAiResponse(txt,httpOk){
var d=null;try{d=JSON.parse(txt);}catch(_e){}
if(!d){return {ok:false,code:"ai_failed",message:_kvAiErrorText("ai_failed")};}
if(!httpOk||d.error){
var err=d.error||{};
var code=(typeof err==="object"&&err.code)||"ai_failed";
var message=(typeof err==="object"&&err.message)||(typeof err==="string"?err:"")||_kvAiErrorText(code);
return {ok:false,code:code,message:message};
}
return {ok:true,data:d};
}

// ── Analyse ──
function kvmindDoAnalyse(){
var sh=document.getElementById("kvmind-snap-hint");if(sh)sh.style.display="none";
kvmindAppendMsg("system",kvmindT("msg_analysing"));kvmindAddLog("info","Analysing...");
kvmindSetBtnLoading("kvmind-btn-analyse",true);
kvmindFetch("/api/analyse",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lang:kvmindGetLang()})}).then(function(r){var ok=r.ok;return r.text().then(function(t){return {ok:ok,txt:t};});}).then(function(res){
var parsed=_kvParseAiResponse(res.txt,res.ok);
if(!parsed.ok){console.warn("Analyse error:",parsed.code,parsed.message);kvmindAppendMsg("action","\u26a0 "+parsed.message,null,"err");kvmindAddLog("error","Analyse "+parsed.code);return;}
var d=parsed.data;
if(!d.text||!d.text.trim()){var msg=_kvAiErrorText("ai_empty");kvmindAppendMsg("action","\u26a0 "+msg,null,"err");kvmindAddLog("warn","Analyse empty");return;}
kvmindAppendMsg("ai",d.text);kvmindAddLog("ok","Analysis done");
}).catch(function(e){console.error("Analyse fetch error:",e);kvmindAppendMsg("system","\u26a0 "+_kvAiErrorText("ai_failed"));}).finally(function(){kvmindSetBtnLoading("kvmind-btn-analyse",false);});
}

// ── Screen Copy (OCR) ──
function kvmindDoScreenCopy(){
kvmindAppendMsg("system",kvmindT("copyExtracting"));kvmindAddLog("info","Screen copy...");
kvmindSetBtnLoading("kvmind-btn-copy",true);
kvmindFetch("/api/screen/copy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lang:kvmindGetLang()})}).then(function(r){var ok=r.ok;return r.text().then(function(t){return {ok:ok,txt:t};});}).then(function(res){
var parsed=_kvParseAiResponse(res.txt,res.ok);
if(!parsed.ok){kvmindAppendMsg("action","\u26a0 "+parsed.message,null,"err");kvmindAddLog("error","Screen copy "+parsed.code);return;}
var d=parsed.data;
if(!d.text||!d.text.trim()){var msg=_kvAiErrorText("ai_empty");kvmindAppendMsg("action","\u26a0 "+msg,null,"err");kvmindAddLog("warn","Screen copy empty");return;}
kvmindShowCopyModal(d.text);kvmindAddLog("ok","Screen copy done");
}).catch(function(e){console.error("Screen copy error:",e);kvmindAppendMsg("system","\u26a0 "+_kvAiErrorText("ai_failed"));}).finally(function(){kvmindSetBtnLoading("kvmind-btn-copy",false);});
}
function kvmindShowCopyModal(text){
var modal=document.getElementById("kvmind-copy-modal");if(!modal)return;
document.getElementById("kvmind-copy-title").textContent=kvmindT("copyTitle");
document.getElementById("kvmind-copy-text").textContent=text;
var clipBtn=document.getElementById("kvmind-copy-clipboard-btn");
clipBtn.textContent=kvmindT("copyToClipboard");clipBtn.classList.remove("copied");
clipBtn.onclick=function(){
navigator.clipboard.writeText(text).then(function(){clipBtn.textContent=kvmindT("copyCopied");clipBtn.classList.add("copied");setTimeout(function(){clipBtn.textContent=kvmindT("copyToClipboard");clipBtn.classList.remove("copied");},2000);}).catch(function(){
// Fallback for older browsers
var ta=document.createElement("textarea");ta.value=text;ta.style.cssText="position:fixed;opacity:0";document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);clipBtn.textContent=kvmindT("copyCopied");clipBtn.classList.add("copied");setTimeout(function(){clipBtn.textContent=kvmindT("copyToClipboard");clipBtn.classList.remove("copied");},2000);
});
};
document.getElementById("kvmind-copy-close-btn").onclick=function(){modal.style.display="none";};
modal.querySelector(".kvmind-copy-backdrop").onclick=function(){modal.style.display="none";};
modal.style.display="flex";
}

// ── Screenshot ──
function kvmindDoScreenshot(){
var sh=document.getElementById("kvmind-snap-hint");if(sh)sh.style.display="none";
kvmindSetBtnLoading("kvmind-btn-snap",true);
fetch("/streamer/snapshot").then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.blob();}).then(function(blob){
var url=URL.createObjectURL(blob);var c=document.getElementById("kvmind-chat-messages");if(!c)return;
var row=document.createElement("div");row.className="kvmind-msg-row ai";
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg snap";
var img=document.createElement("img");img.src=url;img.style.cssText="width:100%;display:block";img.onload=function(){URL.revokeObjectURL(url);};
var cap=document.createElement("div");cap.className="kvmind-snap-cap";var capL=document.createElement("span");capL.textContent="Screenshot";var capR=document.createElement("span");capR.textContent=new Date().toLocaleTimeString();cap.appendChild(capL);cap.appendChild(capR);
bubble.appendChild(img);bubble.appendChild(cap);row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
}).catch(function(e){console.error("Screenshot error:",e);kvmindAppendMsg("system",kvmindT("msg_screenshot_failed"));}).finally(function(){kvmindSetBtnLoading("kvmind-btn-snap",false);});
}

function kvmindDoAbort(){if(window._kvGw&&window._kvGw.connected)window._kvGw.abortChat();else kvmindFetch("/api/agent/abort",{method:"POST"});_endChat();}
function kvmindSetMode(mode){
agentMode=mode;["suggest","auto"].forEach(function(m){var pm=document.getElementById("kvmind-pm-"+m);if(pm)pm.classList.toggle("active",m===mode);});
if(mode==="auto"){
// 优先判订阅：未订阅设备根本无权 auto，与本地模型能力无关。否则用户会
// 看到"换模型"提示但实际换模型也没用 —— 真正缺的是 seat。
if(!currentSubscription||!currentSubscription.paid){
kvmindShowToast(kvmindT("autoToastNoSubscription"),{severity:"warn",duration:6000});
}else if(window._kvmindSupportsTools===false){
// 已订阅但用户在本机又填了不支持 tool calling 的自家模型
kvmindShowToast(kvmindT("autoToastNoTools"),{severity:"warn",duration:6000});
}
}
}
function kvmindTogglePower(){var m=document.getElementById("kvmind-power-menu");if(m)m.classList.toggle("show");}
function kvmindPowerAction(action,label){var m=document.getElementById("kvmind-power-menu");if(m)m.classList.remove("show");if(action==="on"){kvmindFetch("/api/atx/power",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:action})});}else{kvmindShowConfirm(label+"?","power-"+action);}}
function kvmindToggleTerm(){var _termWin=document.getElementById("webterm-window");var _termBtn=document.getElementById("kvmind-btn-term");if(!_termWin)return;_termWin.classList.toggle("kvmind-hidden");var _isOpen=!_termWin.classList.contains("kvmind-hidden");if(_termBtn)_termBtn.classList.toggle("active",_isOpen);var _iframe=document.getElementById("webterm-iframe");if(_isOpen){_termWin.style.display="flex";if(_iframe){_iframe.src="/extras/webterm/ttyd/?disableLeaveAlert=true";_iframe.style.cssText="width:100%;height:100%;border:none;";}}else{_termWin.style.display="none";if(_iframe)_iframe.src="about:blank";}}
function kvmindTogglePanel(){var p=document.getElementById("kvmind-chat-panel");var e=document.getElementById("kvmind-expand-tab");var b=document.getElementById("kvmind-btn-panel");if(!p)return;var isCollapsed=p.classList.contains("collapsed");if(isCollapsed){p.classList.remove("collapsed");p.style.display="flex";if(e)e.classList.remove("show");if(b)b.classList.add("active");document.body.classList.remove("kvmind-panel-collapsed");}else{p.classList.add("collapsed");if(e)e.classList.add("show");if(b)b.classList.remove("active");document.body.classList.add("kvmind-panel-collapsed");}}
function kvmindToggleFullscreen(){if(!document.fullscreenElement)document.documentElement.requestFullscreen();else document.exitFullscreen();}
function kvmindToggleKb(){var w=document.getElementById("kvmind-kb-overlay");if(!w)return;var isVis=w.classList.contains("show");if(isVis){w.classList.remove("show");}else{w.classList.add("show");var inp=document.getElementById("kvmind-kb-input");if(inp)inp.focus();}var b=document.getElementById("kvmind-btn-kb");if(b)b.classList.toggle("active",!isVis);}
function kvmindSetupKbInput(){
var inp=document.getElementById("kvmind-kb-input");
var sendBtn=document.getElementById("kvmind-kb-send");
if(!inp)return;
inp.addEventListener("keydown",function(e){e.stopPropagation();if(e.key==="Escape"){kvmindToggleKb();return;}if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();kvmindKbSendText();}});
inp.addEventListener("keyup",function(e){e.stopPropagation();});
inp.addEventListener("keypress",function(e){e.stopPropagation();});
if(sendBtn)sendBtn.addEventListener("click",function(e){e.stopPropagation();kvmindKbSendText();});
// Shortcut buttons
document.querySelectorAll(".kvmind-kb-key[data-shortcut]").forEach(function(btn){
btn.addEventListener("mousedown",function(e){e.stopPropagation();e.preventDefault();var code=btn.getAttribute("data-shortcut");if(window._kvmindSession){window._kvmindSession.sendKey(code,true,false);btn.classList.add("pressed");}});
btn.addEventListener("mouseup",function(e){e.stopPropagation();e.preventDefault();var code=btn.getAttribute("data-shortcut");if(window._kvmindSession){window._kvmindSession.sendKey(code,false,false);btn.classList.remove("pressed");}});
btn.addEventListener("mouseleave",function(){var code=btn.getAttribute("data-shortcut");if(btn.classList.contains("pressed")&&window._kvmindSession){window._kvmindSession.sendKey(code,false,false);btn.classList.remove("pressed");}});
});
// Combo buttons (e.g. Ctrl+Alt+Del)
document.querySelectorAll(".kvmind-kb-key[data-combo]").forEach(function(btn){
btn.addEventListener("click",function(e){e.stopPropagation();e.preventDefault();var codes=btn.getAttribute("data-combo").split(" ");if(!window._kvmindSession)return;
var idx=0;function press(){if(idx<codes.length){window._kvmindSession.sendKey(codes[idx],true,false);idx++;setTimeout(press,50);}else{setTimeout(release,100);}}
var ridx=codes.length-1;function release(){if(ridx>=0){window._kvmindSession.sendKey(codes[ridx],false,false);ridx--;setTimeout(release,50);}else{kvmindAddLog("ok","KB: "+btn.textContent);}}
press();});
});
}
function kvmindKbSendText(){var inp=document.getElementById("kvmind-kb-input");if(!inp)return;var t=inp.value;if(!t)return;
if(window._kvmindSession){var i=0;function typeNext(){if(i<t.length){var ch=t[i];var code=kvmindCharToCode(ch);if(code){if(code.shift)window._kvmindSession.sendKey("ShiftLeft",true,false);setTimeout(function(){window._kvmindSession.sendKey(code.code,true,false);setTimeout(function(){window._kvmindSession.sendKey(code.code,false,false);if(code.shift)window._kvmindSession.sendKey("ShiftLeft",false,false);i++;setTimeout(typeNext,30);},30);},code.shift?30:0);}else{i++;setTimeout(typeNext,10);}}else{kvmindAddLog("ok","KB: "+t.slice(0,30));inp.value="";}}typeNext();}
else{kvmindFetch("/api/hid/keyboard/type",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t})}).then(function(r){if(r.ok)kvmindAddLog("ok","KB: "+t.slice(0,30));else kvmindAddLog("error","KB send failed");}).catch(function(e2){console.error("KB send error:",e2);kvmindAddLog("error","\u952e\u76d8\u8f93\u5165\u5931\u8d25");});inp.value="";}
}
function kvmindCharToCode(ch){var map={"a":"KeyA","b":"KeyB","c":"KeyC","d":"KeyD","e":"KeyE","f":"KeyF","g":"KeyG","h":"KeyH","i":"KeyI","j":"KeyJ","k":"KeyK","l":"KeyL","m":"KeyM","n":"KeyN","o":"KeyO","p":"KeyP","q":"KeyQ","r":"KeyR","s":"KeyS","t":"KeyT","u":"KeyU","v":"KeyV","w":"KeyW","x":"KeyX","y":"KeyY","z":"KeyZ","0":"Digit0","1":"Digit1","2":"Digit2","3":"Digit3","4":"Digit4","5":"Digit5","6":"Digit6","7":"Digit7","8":"Digit8","9":"Digit9"," ":"Space","\n":"Enter","\t":"Tab","-":"Minus","=":"Equal","[":"BracketLeft","]":"BracketRight","\\":"Backslash",";":"Semicolon","'":"Quote",",":"Comma",".":"Period","/":"Slash","`":"Backquote"};
var shiftMap={"!":"Digit1","@":"Digit2","#":"Digit3","$":"Digit4","%":"Digit5","^":"Digit6","&":"Digit7","*":"Digit8","(":"Digit9",")":"Digit0","_":"Minus","+":"Equal","{":"BracketLeft","}":"BracketRight","|":"Backslash",":":"Semicolon","\"":"Quote","<":"Comma",">":"Period","?":"Slash","~":"Backquote"};
var lower=ch.toLowerCase();if(map[lower])return{code:map[lower],shift:ch!==lower&&ch===ch.toUpperCase()};if(shiftMap[ch])return{code:shiftMap[ch],shift:true};return null;}
function kvmindToggleLog(){var b=document.getElementById("kvmind-log-bar");var t=document.getElementById("kvmind-log-tab");var w=document.getElementById("kvmind-log-wrap");if(b)b.classList.toggle("open");if(t)t.classList.toggle("open");if(w)w.classList.toggle("open");}
function kvmindAddLog(level,text){logCount++;var ent=document.getElementById("kvmind-log-entries");var cnt=document.getElementById("kvmind-log-tab-count");if(cnt)cnt.textContent=logCount;if(!ent)return;var line=document.createElement("div");line.className="kvmind-log-line "+level;var ts=new Date().toLocaleTimeString();var tsSpan=document.createElement("span");tsSpan.className="kvmind-log-ts";tsSpan.textContent=ts;var msgSpan=document.createElement("span");msgSpan.className="kvmind-log-msg";msgSpan.textContent=text;line.appendChild(tsSpan);line.appendChild(msgSpan);ent.appendChild(line);while(ent.children.length>200)ent.removeChild(ent.firstChild);ent.scrollTop=ent.scrollHeight;}
function kvmindStopProp(el){if(!el)return;["keydown","keyup","keypress"].forEach(function(evt){el.addEventListener(evt,function(e){e.stopPropagation();});});}
function kvmindQuickCmd(btn){var inp=document.getElementById("kvmind-chat-input");if(inp){inp.value=btn.textContent;kvmindDoSend();}}
window.kvmindDoSend=kvmindDoSend;
window.kvmindTogglePanel=kvmindTogglePanel;
window.kvmindQuickCmd=kvmindQuickCmd;

// ════════════════════════════════════
//  INIT
// ════════════════════════════════════


// ════════════════════════════════════════════════════════
// INIT — bind events, apply theme/lang, start services
// ════════════════════════════════════════════════════════
function kvmindInit() {

// Apply saved theme
var saved = null;
try { saved = localStorage.getItem("kvmind-theme"); } catch(e) {}
kvmindApplyTheme(saved || kvmindGetAutoTheme());

// Apply i18n
kvmindApplyLang();

// Helper: close settings menu
function _kvCloseSettings(){var sm=document.getElementById("kvmind-settings-menu");if(sm)sm.style.display="none";}

// Event listeners
document.getElementById("kvmind-btn-snap").addEventListener("click",function(){_kvCloseSettings();kvmindDoScreenshot();});
document.getElementById("kvmind-btn-analyse").addEventListener("click",function(){_kvCloseSettings();kvmindDoAnalyse();});
document.getElementById("kvmind-btn-copy").addEventListener("click",function(){_kvCloseSettings();kvmindDoScreenCopy();});
document.getElementById("kvmind-btn-kb").addEventListener("click",function(){_kvCloseSettings();kvmindToggleKb();});
document.getElementById("kvmind-btn-fullscreen").addEventListener("click",function(){_kvCloseSettings();kvmindToggleFullscreen();});
document.getElementById("kvmind-btn-panel").addEventListener("click",function(){_kvCloseSettings();kvmindTogglePanel();});
document.getElementById("kvmind-btn-power").addEventListener("click",function(){_kvCloseSettings();kvmindTogglePower();});
var abm=document.getElementById("kvmind-abort-mini");if(abm)abm.addEventListener("click",kvmindDoAbort);
document.getElementById("kvmind-pm-suggest").addEventListener("click",function(){kvmindSetMode("suggest");});
document.getElementById("kvmind-pm-auto").addEventListener("click",function(){kvmindSetMode("auto");});

var ci=document.getElementById("kvmind-chat-input");
ci.addEventListener("keydown",function(e){e.stopPropagation();if(e.key==="Enter"&&(e.ctrlKey||e.metaKey)){e.preventDefault();kvmindDoSend();}});
ci.addEventListener("keyup",function(e){e.stopPropagation();});
ci.addEventListener("keypress",function(e){e.stopPropagation();});
document.getElementById("kvmind-send-btn").addEventListener("click",kvmindDoSend);
document.getElementById("kvmind-analyse-btn2").addEventListener("click",kvmindDoAnalyse);
document.querySelectorAll(".kvmind-quick-cmd").forEach(function(btn){btn.addEventListener("click",function(e){e.stopPropagation();e.preventDefault();kvmindQuickCmd(this);});});
document.getElementById("kvmind-expand-tab").addEventListener("click",function(){_kvCloseSettings();kvmindTogglePanel();});
var snapHint=document.getElementById("kvmind-snap-hint");if(snapHint)snapHint.addEventListener("click",kvmindDoScreenshot);
document.getElementById("kvmind-collapse-btn").addEventListener("click",kvmindTogglePanel);
document.getElementById("kvmind-log-tab").addEventListener("click",kvmindToggleLog);
document.querySelectorAll(".kvmind-power-item").forEach(function(item){item.addEventListener("click",function(){kvmindPowerAction(this.getAttribute("data-action"),this.getAttribute("data-label"));});});
kvmindSetupKbInput();
kvmindStopProp(ci);

// Panel event interceptor (one-time setup)
var kvmindPanel=document.getElementById("kvmind-panel");if(kvmindPanel){["mousedown","mouseup","click"].forEach(function(evt){kvmindPanel.addEventListener(evt,function(e){if(e.target.closest&&(e.target.closest(".kvmind-quick-cmd")||e.target.closest("#kvmind-chat-input")||e.target.closest("#kvmind-send-btn")||e.target.closest(".kvmind-abort-btn"))){e.stopImmediatePropagation();}},true);});}

// Stop native KVM from stealing focus
var _cp=document.getElementById("kvmind-chat-panel");
if(_cp){["mousedown","click","mouseup","touchstart"].forEach(function(evt){_cp.addEventListener(evt,function(e){e.stopPropagation();if(evt==="click")_kvCloseSettings();});});}


// Settings menu (standalone KVM settings)
var _settingsBtn=document.getElementById("kvmind-btn-settings");
var _settingsMenu=document.getElementById("kvmind-settings-menu");
if(_settingsBtn&&_settingsMenu){
_settingsBtn.addEventListener("click",function(){
var vis=_settingsMenu.style.display==="none";
_settingsMenu.style.display=vis?"block":"none";
if(vis)kvmindLoadSettings();
});
document.addEventListener("click",function(e){if(!_settingsBtn.contains(e.target)&&!_settingsMenu.contains(e.target)){_settingsMenu.style.display="none";}});
}
var _kvSettingsActiveTab=localStorage.getItem("kvmind-settings-tab")||"mouse";
function kvmindLoadSettings(tab){
var m=document.getElementById("kvmind-settings-menu");if(!m)return;
if(tab){_kvSettingsActiveTab=tab;localStorage.setItem("kvmind-settings-tab",tab);}
var hid=window._kvmindHid;
var T=kvmindT;
function row(label,ctrlHtml){return '<div class="kvs-row"><span class="kvs-label">'+label+'</span><span class="kvs-ctrl-inline">'+ctrlHtml+'</span></div>';}
function section(title,inner){return '<div class="kvmind-settings-section"><div class="kvmind-settings-title">'+title+'</div>'+inner+'</div>';}

var tabs=[
  {id:"video",   icon:"🎬", labelKey:"setTabVideo"},
  {id:"mouse",   icon:"🖱", labelKey:"setTabMouse"},
  {id:"hid",     icon:"⌨",       labelKey:"setTabHID"},
  {id:"actions", icon:"⚙",       labelKey:"setTabActions"}
];
var html='<div class="kvmind-settings-tabs">';
for(var t=0;t<tabs.length;t++){
  var tb=tabs[t];
  html+='<button class="kvmind-settings-tab'+(tb.id===_kvSettingsActiveTab?' active':'')+'" onclick="event.stopPropagation();kvmindLoadSettings(\''+tb.id+'\')">'+tb.icon+' '+T(tb.labelKey)+'</button>';
}
html+='</div>';

// ============ Video Tab ============
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="video"?" active":"")+'">';
var _curSM=(window._kvmindStream&&window._kvmindStream.getPreferredMode)?window._kvmindStream.getPreferredMode():"auto";
var _actSM=(window._kvmindStream&&window._kvmindStream.getMode)?window._kvmindStream.getMode():"";
var _modeLabel={"webrtc":"WebRTC","media":"H.264","mjpeg":"MJPEG"};

// 流媒体分区
var _smOpts=["auto","webrtc","media","mjpeg"];
var _smLabels={"auto":T("setStreamModeAuto"),"webrtc":"WebRTC","media":"H.264","mjpeg":"MJPEG"};
var pillsHtml='<div class="kvmind-mode-pills" id="kvs-stream-mode">';
for(var _si=0;_si<_smOpts.length;_si++){
  var _sv=_smOpts[_si];
  pillsHtml+='<button class="kvmind-pill'+(_curSM===_sv?" active":"")+'" data-val="'+_sv+'" onclick="window._kvmindStream&&window._kvmindStream.setMode(\''+_sv+'\');kvmindLoadSettings(\'video\')">'+_smLabels[_sv]+'</button>';
}
pillsHtml+='</div>';
var streamSec=row(T("setStreamMode"),pillsHtml)
  +row(T("setCodec"),'<span class="kvs-display" id="kvs-codec-display">--'+(_actSM&&_modeLabel[_actSM]?" ["+_modeLabel[_actSM]+"]":"")+'</span>');
html+=section(T("setStreamSection"),streamSec);

// H.264 编码分区
var encSec=row(T("setH264Bitrate"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-h264-bitrate" min="1000" max="20000" step="500" value="20000" class="kvmind-settings-range" oninput="document.getElementById(\'kvs-br-val\').textContent=this.value+\' kbps\'" onchange="fetch(\'/api/streamer/set_params?h264_bitrate=\'+this.value,{method:\'POST\',credentials:\'same-origin\'})"><span id="kvs-br-val" class="kvmind-slider-val">20000 kbps</span></div>')
  +row(T("setH264Gop"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-h264-gop" min="0" max="60" step="5" value="0" class="kvmind-settings-range" oninput="document.getElementById(\'kvs-gop-val\').textContent=this.value" onchange="fetch(\'/api/streamer/set_params?h264_gop=\'+this.value,{method:\'POST\',credentials:\'same-origin\'})"><span id="kvs-gop-val" class="kvmind-slider-val">0</span></div>');
html+=section(T("setEncodeSection"),encSec);

// 音频分区
var _audioVol=window._kvmindStream&&window._kvmindStream.getVolume?window._kvmindStream.getVolume():0.5;
var _audioVolPct=Math.round(_audioVol*100);
var audSec=row(T("setVolume"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-audio-vol" min="0" max="100" step="5" value="'+_audioVolPct+'" class="kvmind-settings-range" oninput="var v=this.value/100;window._kvmindStream&&window._kvmindStream.setVolume(v);document.getElementById(\'kvs-vol-val\').textContent=this.value+\'%\'" onchange="var v=this.value/100;window._kvmindStream&&window._kvmindStream.setVolume(v)"><span id="kvs-vol-val" class="kvmind-slider-val">'+_audioVolPct+'%</span></div>')
  +'<div class="kvs-hint">ⓘ '+T("setAudioHint")+'</div>';
html+=section(T("setAudioSection"),audSec);

html+='</div>';

// ============ Mouse Tab ============
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="mouse"?" active":"")+'">';

var mMode=hid&&hid.getMouseMode?hid.getMouseMode():"absolute";
var modeHtml='<div class="kvmind-mode-pills" id="kvs-mouse-mode">'
  +'<button class="kvmind-pill'+(mMode==="absolute"?" active":"")+'" onclick="window._kvmindHid&&window._kvmindHid.setMouseMode(\'absolute\');kvmindLoadSettings(\'mouse\')">'+T("setMouseAbs")+'</button>'
  +'<button class="kvmind-pill'+(mMode==="relative"?" active":"")+'" onclick="window._kvmindHid&&window._kvmindHid.setMouseMode(\'relative\');kvmindLoadSettings(\'mouse\')">'+T("setMouseRel")+'</button>'
  +'</div>';
var curStyle=hid&&hid.getCursorStyle?hid.getCursorStyle():"blue-dot";
var csOpts=["none","blue-dot","crosshair","default","pointer"];
var csLabels={"none":T("setCursorNone"),"blue-dot":T("setCursorBlue"),"crosshair":T("setCursorCross"),"default":T("setCursorArrow"),"pointer":T("setCursorHand")};
var cursorHtml='<select id="kvs-cursor-style" class="kvmind-settings-select" onchange="window._kvmindHid&&window._kvmindHid.setCursorStyle(this.value)">';
for(var i=0;i<csOpts.length;i++){
  cursorHtml+='<option value="'+csOpts[i]+'"'+(curStyle===csOpts[i]?' selected':'')+'>'+csLabels[csOpts[i]]+'</option>';
}
cursorHtml+='</select>';
html+=section(T("setPointerSection"),row(T("setMouseMode"),modeHtml)+row(T("setCursorStyle"),cursorHtml));

var revScroll=hid&&hid.getScrollReverse?hid.getScrollReverse():false;
var scrollRate=hid&&hid.getScrollRate?hid.getScrollRate():5;
var sens=hid&&hid.getSensitivity?hid.getSensitivity():1.0;
var squash=hid&&hid.getSquashEnabled?hid.getSquashEnabled():true;
var mRate=hid&&hid.getMoveRate?hid.getMoveRate():10;
var scrollSec=row(T("setReverseScroll"),'<label class="kvmind-toggle"><input type="checkbox" id="kvs-reverse-scroll"'+(revScroll?' checked':'')+' onchange="window._kvmindHid&&window._kvmindHid.setScrollReverse(this.checked)"><span class="kvmind-toggle-slider"></span></label>')
  +row(T("setScrollSpeed"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-scroll-rate" min="1" max="25" value="'+scrollRate+'" class="kvmind-settings-range" oninput="window._kvmindHid&&window._kvmindHid.setScrollRate(this.value);document.getElementById(\'kvs-scroll-val\').textContent=this.value"><span id="kvs-scroll-val" class="kvmind-slider-val">'+scrollRate+'</span></div>');
if(mMode==="relative"){
  scrollSec+=row(T("setSensitivity"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-sensitivity" min="1" max="19" value="'+Math.round(sens*10)+'" class="kvmind-settings-range" oninput="var v=this.value/10;window._kvmindHid&&window._kvmindHid.setSensitivity(v);document.getElementById(\'kvs-sens-val\').textContent=v.toFixed(1)"><span id="kvs-sens-val" class="kvmind-slider-val">'+sens.toFixed(1)+'</span></div>');
}
scrollSec+=row(T("setMoveSquash"),'<label class="kvmind-toggle"><input type="checkbox" id="kvs-squash"'+(squash?' checked':'')+' onchange="window._kvmindHid&&window._kvmindHid.setSquashEnabled(this.checked)"><span class="kvmind-toggle-slider"></span></label>')
  +row(T("setSquashRate"),'<div class="kvmind-slider-wrap"><input type="range" id="kvs-move-rate" min="10" max="100" step="10" value="'+mRate+'" class="kvmind-settings-range" oninput="window._kvmindHid&&window._kvmindHid.setMoveRate(this.value);document.getElementById(\'kvs-rate-val\').textContent=this.value+\'ms\'"><span id="kvs-rate-val" class="kvmind-slider-val">'+mRate+'ms</span></div>');
html+=section(T("setScrollSection"),scrollSec);

html+='</div>';

// ============ HID Tab ============
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="hid"?" active":"")+'">';
var kbLayout=(hid&&hid.getKeyboardLayout)?hid.getKeyboardLayout():"en-us";
var kbOpts=[["en-us","English (US)"],["en-gb","English (UK)"],["de","Deutsch"],["fr","Français"],["es","Español"],["it","Italiano"],["ja","Japanese"],["ko","Korean"],["zh","Chinese"]];
var kbHtml='<select id="kvs-kb-layout" class="kvmind-settings-select" onchange="window._kvmindHid&&window._kvmindHid.setKeyboardLayout&&window._kvmindHid.setKeyboardLayout(this.value)">';
for(var k=0;k<kbOpts.length;k++){
  kbHtml+='<option value="'+kbOpts[k][0]+'"'+(kbLayout===kbOpts[k][0]?' selected':'')+'>'+kbOpts[k][1]+'</option>';
}
kbHtml+='</select>';
html+=section(T("setKbSection"),row(T("setKbLayout"),kbHtml)
  +'<div class="kvs-action-grid"><button class="kvs-action-btn" onclick="window._kvmindHid&&window._kvmindHid.resetHID();kvmindAddLog(\'ok\',\'HID reset\')">'+T("setResetHid")+'</button></div>');
html+='</div>';

// ============ Actions Tab ============
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="actions"?" active":"")+'">';
html+=section(T("setToolsSection"),
  '<div class="kvs-action-grid">'
  +'<button class="kvs-action-btn" onclick="window.open(\'/api/streamer/snapshot\',\'_blank\')">'+T("setActScreenshot")+'</button>'
  +'<button class="kvs-action-btn" onclick="window.open(\'/api/log?seek=3600&follow=1\',\'_blank\')">'+T("setActViewLog")+'</button>'
  +'</div>');
html+=section(T("setMaintSection"),
  '<div class="kvs-action-grid">'
  +'<button class="kvs-action-btn danger" onclick="fetch(\'/api/streamer/reset\',{method:\'POST\',credentials:\'same-origin\'});kvmindAddLog(\'ok\',\'Stream reset\')">'+T("setActResetStream")+'</button>'
  +'</div>');
html+='</div>';

m.innerHTML=html;
if(_kvSettingsActiveTab==="video"){
  fetch("/api/streamer",{credentials:"same-origin"}).then(function(r){return r.json();}).then(function(d){
    var p=d.result.params;var s=d.result.streamer;
    var brEl=document.getElementById("kvs-h264-bitrate");
    var gopEl=document.getElementById("kvs-h264-gop");
    var codecEl=document.getElementById("kvs-codec-display");
    if(brEl){brEl.value=p.h264_bitrate;document.getElementById("kvs-br-val").textContent=p.h264_bitrate+" kbps";}
    if(gopEl){gopEl.value=p.h264_gop;document.getElementById("kvs-gop-val").textContent=p.h264_gop;}
    if(codecEl&&s){
      var res=(s.source||{}).resolution||{};
      var _modeNow=(window._kvmindStream&&window._kvmindStream.getMode)||"";
      if(typeof _modeNow==="function")_modeNow=_modeNow();
      var _modeTag={"webrtc":" [WebRTC]","media":" [H.264]","mjpeg":" [MJPEG]"};
      codecEl.textContent="H.264 "+res.width+"x"+res.height+" @ "+s.h264.fps+" fps"+(s.h264.online?" ✔":"")+(_modeTag[_modeNow]||"");
    }
  }).catch(function(e){console.warn("[kvmind]",e);});
}
}
function _kvSettT(key){if(window.KVMindI18n&&window.KVMindI18n.translateKvmdSetting){var r=window.KVMindI18n.translateKvmdSetting(key);if(r!=null)return r;}return key;}

// User avatar dropdown (with theme/lang selectors)
(function(){
var _uWrap=document.getElementById("kvmind-user-wrap");
var _uAvatar=document.getElementById("kvmind-user-avatar");
var _uMenu=document.getElementById("kvmind-user-menu");
if(!_uWrap||!_uAvatar||!_uMenu)return;
_uAvatar.textContent="K";

// Toggle menu
_uAvatar.addEventListener("click",function(e){
e.stopPropagation();
var show=_uMenu.style.display==="none";
_uMenu.style.display=show?"block":"none";
if(show)kvmindLoadUserMenu();
});
document.addEventListener("mousedown",function(e){if(!_uWrap.contains(e.target))_uMenu.style.display="none";},true);

// Load UID + plan badge on menu open
function kvmindLoadUserMenu(){
var uidEl=document.getElementById("kvmind-um-uid");
var badge=document.getElementById("kvmind-plan-badge");
fetch(KVMIND_API+"/api/device/uid").then(function(r){return r.json();}).then(function(d){if(d.uid&&uidEl)uidEl.textContent=d.uid;}).catch(function(e){console.warn("[kvmind]",e);});
fetch(KVMIND_API+"/api/subscription").then(function(r){return r.json();}).then(function(sub){
if(!badge)return;
var paid=sub.entitlement_state==="paid";
badge.textContent=paid?"Paid":"Free";
badge.style.background=paid?"#3ecf8e":"#6b7280";
badge.style.color="#fff";
}).catch(function(e){console.warn("[kvmind]",e);});
}

// Menu button actions
_uMenu.querySelectorAll(".kvmind-user-item").forEach(function(item){
item.addEventListener("click",function(){
var act=this.getAttribute("data-action");
if(act)_uMenu.style.display="none";
if(act==="logout"){fetch("/api/auth/logout",{method:"POST"}).then(function(){window.location.href="/login";}).catch(function(){window.location.href="/login";});}
else if(act==="changepw"){window.location.href="/change-password.html";}
else if(act==="profile"){kvmindShowProfile();}
});});

// Theme select in menu
var _umTheme=document.getElementById("kvmind-um-theme");
if(_umTheme){
try{var st=localStorage.getItem("kvmind-theme");if(st)_umTheme.value=st;}catch(e){}
["keydown","keyup","keypress","mousedown","click","mouseup","touchstart"].forEach(function(evt){_umTheme.addEventListener(evt,function(e){e.stopPropagation();});});
_umTheme.addEventListener("change",function(){kvmindOnThemeChange(this);});
}

// Language select in menu
var _umLang=document.getElementById("kvmind-um-lang");
if(_umLang){
_umLang.value=kvmindGetLang();
["keydown","keyup","keypress","mousedown","click","mouseup","touchstart"].forEach(function(evt){_umLang.addEventListener(evt,function(e){e.stopPropagation();});});
_umLang.addEventListener("change",function(){if(window.KVMindI18n&&window.KVMindI18n.setLang){window.KVMindI18n.setLang(this.value);}else{localStorage.setItem("kvmind_lang",this.value);}kvmindApplyLang();});
}
})();

// Terminal toggle (uses standalone kvmindToggleTerm)
var _termBtn=document.getElementById("kvmind-btn-term");
var _termWin=document.getElementById("webterm-window");
if(_termWin)_termWin.classList.add("kvmind-hidden");
if(_termBtn)_termBtn.addEventListener("click",function(){_kvCloseSettings();kvmindToggleTerm();});

// Start Gateway client for MyClaw chat (via KVMind Bridge InnerClaw)
if(typeof KVMindGateway!=="undefined"){
window._kvGw=new KVMindGateway({url:(location.protocol==="https:"?"wss:":"ws:")+"//"+location.host+"/kdkvm/ws/chat",token:localStorage.getItem("kvmind-gw-token")||"",sessionKey:"agent:main:main"});
window._kvGw.onConnected=function(){kvmindAddLog("ok","Gateway connected");};
window._kvGw.onDisconnected=function(){kvmindAddLog("warn","Gateway disconnected");};
window._kvGw.onChatDelta=function(text){
var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");
var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent=kvmindT("aiWorking");
if(text&&text.trim()){
var _msgs=document.getElementById("kvmind-chat-messages");
var _streamBubble=_msgs?_msgs.querySelector(".kvmind-chat-msg.ai.streaming"):null;
if(_streamBubble){_streamBubble.textContent=text;_msgs.scrollTop=_msgs.scrollHeight;}
else{kvmindAppendMsg("ai",text);var _all=_msgs?_msgs.querySelectorAll(".kvmind-chat-msg.ai"):[];var _newBubble=_all.length?_all[_all.length-1]:null;if(_newBubble)_newBubble.classList.add("streaming");window._kvmindStreaming=true;}
}
};
window._kvGw.onChatFinal=function(text){
// Process streaming bubble BEFORE _endChat() — _endChat removes .streaming class,
// which would prevent finding the bubble and cause a duplicate append.
if(text&&text.trim()){
var _msgs=document.getElementById("kvmind-chat-messages");
var _streamBubble=_msgs?_msgs.querySelector(".kvmind-chat-msg.ai.streaming"):null;
if(_streamBubble){_streamBubble.textContent=text;_streamBubble.classList.remove("streaming");_msgs.scrollTop=_msgs.scrollHeight;}
else{kvmindAppendMsg("ai",text);}
}
_endChat();
kvmindAddLog("ok","MyClaw replied");
};
window._kvGw.onChatAborted=function(text){
_endChat();
if(text&&text.trim())kvmindAppendMsg("ai",text+" [aborted]");
};
window._kvGw.onChatError=function(err){
_endChat();
// V6 PR#3: dispatch the error payload to a CTA-aware bubble. See
// dev/kdcms/api-spec/error-codes.md for the full contract. String-shape
// errors are legacy paths that still flow through here — wrap them into
// the struct shape so the downstream logic has one branch to worry about.
if(typeof err==="string") err={code:null,message:err};
kvmindAppendChatError(err||{});
};
window._kvGw.onToolStart=function(name,id,input){
var inputStr="";
if(input){try{inputStr=typeof input==="string"?input:JSON.stringify(input,null,2);if(inputStr.length>800)inputStr=inputStr.substring(0,800)+"…";}catch(e){console.warn("[kvmind] tool input serialize:",e);}}
var c=document.getElementById("kvmind-chat-messages");if(c){
var row=document.createElement("div");row.className="kvmind-msg-row action";
var det=document.createElement("details");det.className="kvmind-tool-details";
if(id)det.setAttribute("data-tool-id",id);
var sum=document.createElement("summary");sum.className="kvmind-tool-summary";sum.textContent="\u25b6 "+name;
det.appendChild(sum);
if(inputStr){var pre=document.createElement("pre");pre.className="kvmind-tool-content";pre.textContent=inputStr;det.appendChild(pre);}
row.appendChild(det);c.appendChild(row);c.scrollTop=c.scrollHeight;}
kvmindAddLog("info","Tool: "+name);
var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");
var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent="\u26a1 "+name+"...";
};
window._kvGw.onToolResult=function(name,result,id){
var c=document.getElementById("kvmind-chat-messages");
if(c&&result){
var det=id?c.querySelector('.kvmind-tool-details[data-tool-id="'+id+'"]'):null;
if(det){det.querySelector(".kvmind-tool-summary").textContent="\u2713 "+name;
var pre=document.createElement("pre");pre.className="kvmind-tool-content kvmind-tool-result";pre.textContent=result;det.appendChild(pre);
}else{var row=document.createElement("div");row.className="kvmind-msg-row action";
var d2=document.createElement("details");d2.className="kvmind-tool-details";
var sum=document.createElement("summary");sum.className="kvmind-tool-summary";sum.textContent="\u2713 "+name;
d2.appendChild(sum);var pre2=document.createElement("pre");pre2.className="kvmind-tool-content kvmind-tool-result";pre2.textContent=result;d2.appendChild(pre2);
row.appendChild(d2);c.appendChild(row);c.scrollTop=c.scrollHeight;}}
kvmindAddLog("ok","\u2713 "+name+(result?" → "+result.substring(0,60):""));
};
window._kvGw.onThinkingStart=function(){
var ab=document.getElementById("kvmind-ai-bar");if(ab)ab.classList.add("show");
var at=document.getElementById("kvmind-ai-bar-text");if(at)at.textContent=kvmindT("aiWorking");
var _old=document.querySelector(".kvmind-chat-msg.ai.streaming");if(_old)_old.classList.remove("streaming");
window._kvmindStreaming=false;
};
window._kvGw.onThinkingEnd=function(){};
window._kvGw.onNotice=function(notice){kvmindAppendNotice(notice);};
window._kvGw.onLog=function(level,msg){kvmindAddLog(level,msg);};
window._kvGw.connect();
}

// Load version
fetch("/kdkvm/version.json?t="+Date.now()).then(function(r){return r.json()}).then(function(d){var el=document.getElementById("kvmind-ver");if(el)el.textContent="v"+d.version;}).catch(function(e){console.warn("[kvmind]",e);});

// Cache supports_tools flag for proactive auto-mode warning.
// Sidebar also mirrors this value when the user runs Test Connection.
window._kvmindSupportsTools=true;
fetch(KVMIND_API+"/api/ai/config").then(function(r){return r.json();}).then(function(d){window._kvmindSupportsTools=d&&d.supports_tools!==false;}).catch(function(e){console.warn("[kvmind] supports_tools:",e);});

// Check OTA update status
fetch("/kdkvm/api/update/status").then(function(r){return r.json()}).then(function(d){
    if(d.status==="available"){
        var verEl=document.getElementById("kvmind-ver");
        if(verEl){verEl.style.position="relative";var _dot=document.createElement("span");_dot.style.cssText="display:inline-block;width:6px;height:6px;background:#ef4444;border-radius:50%;margin-left:4px;vertical-align:top";_dot.title=kvmindT("updateAvailable");verEl.parentNode.insertBefore(_dot,verEl.nextSibling);}
        var profileEl=document.getElementById("kvmind-um-profile");
        if(profileEl)profileEl.textContent=kvmindT("umProfileUpdate");
    }
}).catch(function(e){console.warn("[kvmind]",e);});

// Start services
kvmindConnectWS();
kvmindCheckStatus();
var _statusCheckTimer=setInterval(kvmindCheckStatus,30000);
kvmindAddLog("ok","KVMind initialized");

// V15: banner 只在"账户主动发起 ACCOUNT_TO_DEVICE 待审请求"时显示。设计原则：
//   * **不挡 KVM 控制台主操作** — 右上角浮动小卡片，不全宽顶部条
//   * **可关闭** — × 按钮 dismiss 进 sessionStorage，本会话不再弹；下次有**新**
//                 pending（不同 request_id）或换浏览器会话才会重新出现
//   * **不强制** — 用户可以"晾着"这个 pending 继续做别的，跳到 activate 处理或忽略
var _DISMISS_KEY="kvmind:bind_banner_dismissed_ids";
function _bannerDismissedIds(){
    try { return JSON.parse(sessionStorage.getItem(_DISMISS_KEY) || "[]") || []; }
    catch(e){ return []; }
}
function _bannerDismissAdd(id){
    try {
        var arr=_bannerDismissedIds();
        if(arr.indexOf(String(id))<0) arr.push(String(id));
        sessionStorage.setItem(_DISMISS_KEY, JSON.stringify(arr));
    } catch(e){}
}
function kvmindRenderBindBanner(visible, requestId){
    var ID="kvmind-bind-banner";
    var existing=document.getElementById(ID);
    if(!visible){ if(existing) existing.remove(); return; }
    var banner=existing||document.createElement("div");
    banner.id=ID;
    banner.dataset.requestId=String(requestId || "");
    banner.style.cssText="position:fixed;top:16px;right:16px;z-index:99999;"+
        "max-width:320px;padding:10px 12px 10px 14px;border-radius:10px;"+
        "font:13px/1.4 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"+
        "background:#fef3c7;color:#92400e;border:1px solid #fde68a;"+
        "box-shadow:0 4px 16px rgba(0,0,0,0.12);"+
        "display:flex;align-items:center;gap:10px";
    banner.innerHTML=
        '<span style="flex:1;cursor:pointer;font-weight:500" data-role="open">⚠ '+kvmindT("bindBannerPending")+' →</span>'+
        '<button type="button" data-role="dismiss" aria-label="'+kvmindT("bindBannerDismiss")+'" '+
        'title="'+kvmindT("bindBannerDismiss")+'" '+
        'style="border:0;background:transparent;color:#92400e;cursor:pointer;'+
        'font-size:18px;line-height:1;padding:2px 6px;border-radius:4px;opacity:0.7">×</button>';
    var openEl=banner.querySelector('[data-role="open"]');
    if(openEl) openEl.onclick=function(){ window.location.href="/activate.html"; };
    var dismissEl=banner.querySelector('[data-role="dismiss"]');
    if(dismissEl) dismissEl.onclick=function(ev){
        ev.stopPropagation();
        if(requestId) _bannerDismissAdd(requestId);
        banner.remove();
    };
    if(!existing) document.body.appendChild(banner);
}
// 只在有账户主动发起的 pending 且未被本会话 dismiss 时显示。轮询 active=1s, idle=15s。
var _kvmindBindActive=false;
var _kvmindBindTimer=null;
function _scheduleBindBanner(){
    if(_kvmindBindTimer) clearTimeout(_kvmindBindTimer);
    _kvmindBindTimer=setTimeout(kvmindCheckBindBanner, _kvmindBindActive ? 1000 : 15000);
}
function kvmindCheckBindBanner(){
    fetch(KVMIND_API+"/api/binding/state",{cache:"no-store"}).then(function(r){return r.json();}).then(function(st){
        var pending=(st.pending||[]).filter(function(p){
            return p && (p.direction==="ACCOUNT_TO_DEVICE" || p.initiator==="account");
        });
        if(pending.length===0){
            kvmindRenderBindBanner(false);
            _kvmindBindActive=false;
            _scheduleBindBanner();
            return;
        }
        var dismissed=_bannerDismissedIds();
        var firstUndismissed=null;
        for(var i=0;i<pending.length;i++){
            var pid=String(pending[i].id || "");
            if(dismissed.indexOf(pid)<0){ firstUndismissed=pending[i]; break; }
        }
        if(firstUndismissed){
            kvmindRenderBindBanner(true, firstUndismissed.id);
            _kvmindBindActive=true;
        } else {
            // 全部已 dismiss — 隐藏 banner，但保持 1s 轮询：用户主动 accept/cancel
            // 后让 banner 立即消失（避免 stale）；新 pending（不同 id）也能秒弹。
            kvmindRenderBindBanner(false);
            _kvmindBindActive=true;
        }
        _scheduleBindBanner();
    }).catch(function(){
        kvmindRenderBindBanner(false);
        _kvmindBindActive=false;
        _scheduleBindBanner();
    });
}
kvmindCheckBindBanner();

// Update toolbar & menu buttons based on subscription
fetch(KVMIND_API+"/api/subscription").then(function(r){return r.json()}).then(function(sub){
    var claimed=sub.claim_state==="claimed";
    currentSubscription={paid:sub.entitlement_state==="paid",messaging:!!sub.messaging,claimed:claimed};
    kvmindUpdatePlanUI(currentSubscription.paid);
    // 升级订阅按钮一律跳 kvmind.com/pricing，不再走 /activate.html。
    // 设备未 claim 的引导走顶栏 bind banner / 用户菜单的"激活"入口，与"升级订阅"语义解耦。
    var url = "https://kvmind.com/pricing";
    function _wireUpgrade(el){
        if(!el||currentSubscription.paid) return;
        el.href = url;
        el.setAttribute("target","_blank");
        el.setAttribute("rel","noopener");
        // 兜底：直接绑 click，绕开 <a> 默认行为可能被吞的边界场景
        if(!el._kvUpgradeBound){
            el.addEventListener("click", function(e){
                e.preventDefault(); e.stopPropagation();
                window.open(url, "_blank", "noopener");
            });
            el._kvUpgradeBound = true;
        }
    }
    _wireUpgrade(document.getElementById("kvmind-btn-upgrade"));
    _wireUpgrade(document.getElementById("kvmind-um-upgrade"));
}).catch(function(e){console.warn("[kvmind]",e);});

// Expose functions used by inline onclick handlers
window.kvmindLoadSettings=kvmindLoadSettings;
window.kvmindAddLog=kvmindAddLog;
}

// Run init immediately (standalone mode)
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function() { setTimeout(kvmindInit, 100); });
} else {
    setTimeout(kvmindInit, 100);
}

})();
// build:1774226084
