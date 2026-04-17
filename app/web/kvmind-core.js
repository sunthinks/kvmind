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
var wsConn=null,agentMode="suggest",panelOpen=true,logCount=0,currentSubscription={plan:"community",messaging:false};

// ── i18n ──
var KVMIND_I18N={
zh:{snap:"\ud83d\udcf7 \u622a\u56fe",analyse:"\ud83d\udd0d \u5206\u6790",keyboard:"\u2328\ufe0f \u952e\u76d8",suggest:"\ud83d\udca1 \u5efa\u8bae",auto:"\u26a1 \u81ea\u52a8",terminal:"\ud83d\udda5 \u7ec8\u7aef",settings:"\u2699 KVM\u8bbe\u7f6e",power:"\u23fb \u7535\u6e90",myclaw:"\u2726 MyClaw",powerOn:"\ud83d\udfe2 \u5f00\u673a",powerOff:"\u26ab \u5173\u673a",restart:"\ud83d\udd04 \u91cd\u542f",forceOff:"\u26a0\ufe0f \u5f3a\u5236\u65ad\u7535",connected:"KVM \u5df2\u8fde\u63a5",disconnected:"\u8fde\u63a5\u65ad\u5f00",aiWorking:"MyClaw \u6267\u884c\u4e2d\u2026",abort:"\u4e2d\u65ad",pmSuggest:"\u5efa\u8bae",pmAuto:"\u81ea\u52a8",qAnalyse:"\u5206\u6790\u5f53\u524d\u72b6\u6001",qError:"\u8fd9\u4e2a\u62a5\u9519\u662f\u4ec0\u4e48",qTerminal:"\u6253\u5f00\u7ec8\u7aef",qRestart:"\u91cd\u542f\u670d\u52a1",qDisk:"\u68c0\u67e5\u78c1\u76d8\u7a7a\u95f4",chatPH:"\u8f93\u5165\u6307\u4ee4\uff0c\u4f8b\u5982\uff1a\n\u2022 \u5e2e\u6211\u5b89\u88c5 nginx \u5e76\u914d\u7f6e\n\u2022 \u8fd9\u4e2a\u62a5\u9519\u600e\u4e48\u4fee\uff1f\n\u2022 \u68c0\u67e5\u78c1\u76d8\u4f7f\u7528\u60c5\u51b5",kbPH:"\u8f93\u5165\u6587\u5b57\u53d1\u9001\u81f3\u8fdc\u7a0b\u4e3b\u673a (Enter\u53d1\u9001 \u00b7 Esc\u5173\u95ed)",sendHint:"Ctrl+\u21a9 \u53d1\u9001",clawReady:"MyClaw AI Ready",clawTry:"\u8bd5\u8bd5\u8bf4\uff1a",clawEx1:"\u300c\u5e2e\u6211\u68c0\u67e5\u670d\u52a1\u5668\u72b6\u6001\u300d",clawEx2:"\u300c\u8fd9\u4e2a\u753b\u9762\u6709\u4ec0\u4e48\u95ee\u9898\uff1f\u300d",clawEx3:"\u300c\u81ea\u52a8\u5e2e\u6211\u5b89\u88c5 nginx\u300d",welcomeHint:"\ud83d\udcf7 \u70b9\u51fb\u622a\u56fe\uff0cMyClaw \u5373\u53ef\u770b\u5230\u5f53\u524d\u753b\u9762\u5e76\u5f00\u59cb\u5de5\u4f5c",kbHint:"Ctrl+A \u00b7 Ctrl+C \u00b7 Ctrl+V",send:"\u25b6 \u53d1\u9001",logout:"\u9000\u51fa",sysTitle:"System & Stream",kbTitle:"\u952e\u76d8\u5e03\u5c40 & \u6587\u5b57\u8f93\u5165",umProfile:"\ud83d\udcbb \u8bbe\u5907\u4fe1\u606f",umChangePw:"\ud83d\udd12 \u4fee\u6539\u5bc6\u7801",umDashboard:"\ud83d\udcca \u4eea\u8868\u76d8",umProfileUpdate:"\ud83d\udcbb \u8bbe\u5907\u4fe1\u606f \u00b7 \u2b06\ufe0f \u6709\u66f4\u65b0",updateAvailable:"\u6709\u65b0\u7248\u672c\u53ef\u7528",pfFirmware:"\u56fa\u4ef6\u7248\u672c",updateNewVer:"\u53d1\u73b0\u65b0\u7248\u672c",updateBtn:"\u7acb\u5373\u66f4\u65b0",updateInstalling:"\u6b63\u5728\u66f4\u65b0\u2026",updateStarted:"\u66f4\u65b0\u5df2\u542f\u52a8",updateWait:"\u66f4\u65b0\u4e2d\uff0c\u8bf7\u7a0d\u5019",updateDone:"\u2705 \u66f4\u65b0\u5b8c\u6210\uff0c\u5373\u5c06\u5237\u65b0",updateFailed:"\u274c \u66f4\u65b0\u5931\u8d25",umUpgrade:"\u26a1 \u5347\u7ea7\u8ba2\u9605",umSubscription:"\ud83d\udccb \u8ba2\u9605\u4fe1\u606f",umTheme:"\ud83c\udf19 \u4e3b\u9898",umLang:"\ud83c\udf10 \u8bed\u8a00",umLogout:"\ud83d\udeaa \u9000\u51fa\u767b\u5f55",upgradeAutoTitle:"\u81ea\u52a8\u6a21\u5f0f\u9700\u8981\u5347\u7ea7",upgradeAutoDesc:"\u81ea\u52a8\u6267\u884c\u6a21\u5f0f\u9700\u8981 Standard \u6216 Pro \u8ba2\u9605\u8ba1\u5212\u3002",upgradeAutoBtn:"\u7acb\u5373\u5347\u7ea7 \u2192",copy:"\ud83d\udccb \u590d\u5236",copyTitle:"\u5c4f\u5e55\u6587\u5b57",copyExtracting:"\u6b63\u5728\u63d0\u53d6\u5c4f\u5e55\u6587\u5b57\u2026",copyToClipboard:"\u590d\u5236\u5230\u526a\u8d34\u677f",copyCopied:"\u2705 \u5df2\u590d\u5236",copyFailed:"\u63d0\u53d6\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5",wsReconnecting:"\u8fde\u63a5\u5df2\u65ad\u5f00\uff0c\u6b63\u5728\u91cd\u8fde\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002\u82e5\u957f\u65f6\u95f4\u4e0d\u6062\u590d\uff0c\u8bf7\u5237\u65b0\u9875\u9762\u3002"},
ja:{snap:"\ud83d\udcf7 \u30b9\u30ca\u30c3\u30d7",analyse:"\ud83d\udd0d \u5206\u6790",keyboard:"\u2328\ufe0f \u30ad\u30fc\u30dc\u30fc\u30c9",suggest:"\ud83d\udca1 \u63d0\u6848",auto:"\u26a1 \u81ea\u52d5",terminal:"\ud83d\udda5 \u30bf\u30fc\u30df\u30ca\u30eb",settings:"\u2699 KVM\u8a2d\u5b9a",power:"\u23fb \u96fb\u6e90",myclaw:"\u2726 MyClaw",powerOn:"\ud83d\udfe2 \u96fb\u6e90ON",powerOff:"\u26ab \u96fb\u6e90OFF",restart:"\ud83d\udd04 \u518d\u8d77\u52d5",forceOff:"\u26a0\ufe0f \u5f37\u5236OFF",connected:"KVM \u63a5\u7d9a\u6e08\u307f",disconnected:"\u5207\u65ad",aiWorking:"MyClaw \u5b9f\u884c\u4e2d\u2026",abort:"\u4e2d\u65ad",pmSuggest:"\u63d0\u6848",pmAuto:"\u81ea\u52d5",qAnalyse:"\u73fe\u5728\u306e\u72b6\u614b\u3092\u5206\u6790",qError:"\u3053\u306e\u30a8\u30e9\u30fc\u306f\u4f55\uff1f",qTerminal:"\u30bf\u30fc\u30df\u30ca\u30eb\u3092\u958b\u304f",qRestart:"\u30b5\u30fc\u30d3\u30b9\u3092\u518d\u8d77\u52d5",qDisk:"\u30c7\u30a3\u30b9\u30af\u5bb9\u91cf\u3092\u78ba\u8a8d",chatPH:"\u30b3\u30de\u30f3\u30c9\u3092\u5165\u529b\u2026",kbPH:"\u30ea\u30e2\u30fc\u30c8\u30db\u30b9\u30c8\u306b\u30c6\u30ad\u30b9\u30c8\u9001\u4fe1 (Enter\u9001\u4fe1 \u00b7 Esc\u9589\u3058\u308b)",sendHint:"Ctrl+\u21a9 \u9001\u4fe1",clawReady:"MyClaw AI Ready",clawTry:"\u8a66\u3057\u3066\u307f\u3066\u304f\u3060\u3055\u3044\uff1a",clawEx1:"\u300c\u30b5\u30fc\u30d0\u30fc\u306e\u72b6\u614b\u3092\u78ba\u8a8d\u3057\u3066\u300d",clawEx2:"\u300c\u3053\u306e\u753b\u9762\u306b\u554f\u984c\u306f\uff1f\u300d",clawEx3:"\u300cnginx \u3092\u81ea\u52d5\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u300d",welcomeHint:"\ud83d\udcf7 \u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8\u3092\u30af\u30ea\u30c3\u30af",kbHint:"Ctrl+A \u00b7 Ctrl+C \u00b7 Ctrl+V",send:"\u25b6 \u9001\u4fe1",logout:"\u30ed\u30b0\u30a2\u30a6\u30c8",sysTitle:"System & Stream",kbTitle:"\u30ad\u30fc\u30dc\u30fc\u30c9 & \u30c6\u30ad\u30b9\u30c8\u5165\u529b",umProfile:"\ud83d\udcbb \u30c7\u30d0\u30a4\u30b9\u60c5\u5831",umChangePw:"\ud83d\udd12 \u30d1\u30b9\u30ef\u30fc\u30c9\u5909\u66f4",umDashboard:"\ud83d\udcca \u30c0\u30c3\u30b7\u30e5\u30dc\u30fc\u30c9",umProfileUpdate:"\ud83d\udcbb \u30c7\u30d0\u30a4\u30b9\u60c5\u5831 \u00b7 \u2b06\ufe0f \u66f4\u65b0\u3042\u308a",updateAvailable:"\u30a2\u30c3\u30d7\u30c7\u30fc\u30c8\u304c\u3042\u308a\u307e\u3059",pfFirmware:"\u30d5\u30a1\u30fc\u30e0\u30a6\u30a7\u30a2",updateNewVer:"\u65b0\u30d0\u30fc\u30b8\u30e7\u30f3\u304c\u3042\u308a\u307e\u3059",updateBtn:"\u4eca\u3059\u3050\u66f4\u65b0",updateInstalling:"\u66f4\u65b0\u4e2d\u2026",updateStarted:"\u66f4\u65b0\u958b\u59cb",updateWait:"\u66f4\u65b0\u4e2d\u3001\u304a\u5f85\u3061\u304f\u3060\u3055\u3044",updateDone:"\u2705 \u66f4\u65b0\u5b8c\u4e86\u3001\u30ea\u30ed\u30fc\u30c9\u3057\u307e\u3059",updateFailed:"\u274c \u66f4\u65b0\u5931\u6557",umUpgrade:"\u26a1 \u30d7\u30e9\u30f3\u5347\u7d1a",umSubscription:"\ud83d\udccb \u30b5\u30d6\u30b9\u30af\u60c5\u5831",umTheme:"\ud83c\udf19 \u30c6\u30fc\u30de",umLang:"\ud83c\udf10 \u8a00\u8a9e",umLogout:"\ud83d\udeaa \u30ed\u30b0\u30a2\u30a6\u30c8",upgradeAutoTitle:"\u81ea\u52d5\u30e2\u30fc\u30c9\u306b\u306f\u30a2\u30c3\u30d7\u30b0\u30ec\u30fc\u30c9\u304c\u5fc5\u8981",upgradeAutoDesc:"\u81ea\u52d5\u5b9f\u884c\u30e2\u30fc\u30c9\u306b\u306f Standard \u307e\u305f\u306f Pro \u30d7\u30e9\u30f3\u304c\u5fc5\u8981\u3067\u3059\u3002",upgradeAutoBtn:"\u30a2\u30c3\u30d7\u30b0\u30ec\u30fc\u30c9 \u2192",copy:"\ud83d\udccb \u30b3\u30d4\u30fc",copyTitle:"\u753b\u9762\u30c6\u30ad\u30b9\u30c8",copyExtracting:"\u30c6\u30ad\u30b9\u30c8\u62bd\u51fa\u4e2d\u2026",copyToClipboard:"\u30af\u30ea\u30c3\u30d7\u30dc\u30fc\u30c9\u306b\u30b3\u30d4\u30fc",copyCopied:"\u2705 \u30b3\u30d4\u30fc\u3057\u307e\u3057\u305f",copyFailed:"\u62bd\u51fa\u306b\u5931\u6557\u3057\u307e\u3057\u305f",wsReconnecting:"\u63a5\u7d9a\u304c\u5207\u308c\u307e\u3057\u305f\u3002\u518d\u63a5\u7d9a\u4e2d\u3067\u3059\u3002\u5c11\u3057\u5f85\u3063\u3066\u3082\u3046\u4e00\u5ea6\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002\u6539\u5584\u3057\u306a\u3044\u5834\u5408\u306f\u30da\u30fc\u30b8\u3092\u66f4\u65b0\u3057\u3066\u304f\u3060\u3055\u3044\u3002"},
en:{snap:"\ud83d\udcf7 Snap",analyse:"\ud83d\udd0d Analyse",keyboard:"\u2328\ufe0f Keyboard",suggest:"\ud83d\udca1 Suggest",auto:"\u26a1 Auto",terminal:"\ud83d\udda5 Terminal",settings:"\u2699 KVM Settings",power:"\u23fb Power",myclaw:"\u2726 MyClaw",powerOn:"\ud83d\udfe2 Power On",powerOff:"\u26ab Power Off",restart:"\ud83d\udd04 Restart",forceOff:"\u26a0\ufe0f Force Off",connected:"KVM Connected",disconnected:"Disconnected",aiWorking:"MyClaw working\u2026",abort:"Abort",pmSuggest:"Suggest",pmAuto:"Auto",qAnalyse:"Analyze status",qError:"What's this error",qTerminal:"Open terminal",qRestart:"Restart service",qDisk:"Check disk space",chatPH:"Enter command, e.g.:\n\u2022 Install and configure nginx\n\u2022 How to fix this error?\n\u2022 Check disk usage",kbPH:"Type text to send (Enter send \u00b7 Esc close)",sendHint:"Ctrl+\u21a9 Send",clawReady:"MyClaw AI Ready",clawTry:"Try saying:",clawEx1:"\u201cCheck my server status\u201d",clawEx2:"\u201cWhat\u2019s wrong with this screen?\u201d",clawEx3:"\u201cAuto-install nginx for me\u201d",welcomeHint:"\ud83d\udcf7 Click screenshot to start",kbHint:"Ctrl+A \u00b7 Ctrl+C \u00b7 Ctrl+V",send:"\u25b6 Send",logout:"Logout",sysTitle:"System & Stream",kbTitle:"Keyboard & Text Input",umProfile:"\ud83d\udcbb Device Info",umChangePw:"\ud83d\udd12 Change Password",umDashboard:"\ud83d\udcca Dashboard",umProfileUpdate:"\ud83d\udcbb Device Info \u00b7 \u2b06\ufe0f Update",updateAvailable:"Update available",pfFirmware:"Firmware",updateNewVer:"New version available",updateBtn:"Update Now",updateInstalling:"Updating\u2026",updateStarted:"Update started",updateWait:"Updating, please wait",updateDone:"\u2705 Update complete, reloading",updateFailed:"\u274c Update failed",umUpgrade:"\u26a1 Upgrade",umSubscription:"\ud83d\udccb Subscription",umTheme:"\ud83c\udf19 Theme",umLang:"\ud83c\udf10 Language",umLogout:"\ud83d\udeaa Logout",upgradeAutoTitle:"Auto mode requires upgrade",upgradeAutoDesc:"Auto execution mode requires a Standard or Pro subscription.",upgradeAutoBtn:"Upgrade now \u2192",copy:"\ud83d\udccb Copy",copyTitle:"Screen Text",copyExtracting:"Extracting text\u2026",copyToClipboard:"Copy to Clipboard",copyCopied:"\u2705 Copied!",copyFailed:"Extraction failed, please retry",wsReconnecting:"Connection lost \u2014 reconnecting. Please try again in a moment; if it keeps failing, refresh the page."}
};
function kvmindGetLang(){return localStorage.getItem("kvmind_lang")||"zh";}
function kvmindT(k){var l=kvmindGetLang();return(KVMIND_I18N[l]&&KVMIND_I18N[l][k])||(KVMIND_I18N.zh[k])||k;}
function kvmindApplyLang(){
var t=kvmindT;
var map={"kvmind-btn-snap":"snap","kvmind-btn-analyse":"analyse","kvmind-btn-copy":"copy","kvmind-btn-kb":"keyboard","kvmind-btn-term":"terminal","kvmind-btn-settings":"settings","kvmind-btn-power":"power","kvmind-btn-panel":"myclaw","kvmind-pm-suggest":"pmSuggest","kvmind-pm-auto":"pmAuto","kvmind-abort-mini":"abort","kvmind-char-hint":"sendHint","kvmind-send-btn":"send","kvmind-um-profile":"umProfile","kvmind-um-changepw":"umChangePw","kvmind-claw-ready":"clawReady","kvmind-claw-try":"clawTry","kvmind-claw-ex1":"clawEx1","kvmind-claw-ex2":"clawEx2","kvmind-claw-ex3":"clawEx3","kvmind-um-dashboard-text":"umDashboard","kvmind-um-theme-label":"umTheme","kvmind-um-lang-label":"umLang","kvmind-um-logout":"umLogout"};
for(var id in map){var el=document.getElementById(id);if(el)el.textContent=t(map[id]);}
// Update plan-dependent text (upgrade/subscription button + badge)
var _planBtn=document.getElementById("kvmind-btn-upgrade");
var _planText=document.getElementById("kvmind-um-upgrade-text");
if(currentSubscription.plan!=="community"){
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


var KVMIND_KVM_I18N={
zh:{"Runtime settings & tools":"\u8fd0\u884c\u65f6\u8bbe\u7f6e\u4e0e\u5de5\u5177","Resolution:":"\u5206\u8fa8\u7387:","JPEG quality:":"JPEG \u8d28\u91cf:","JPEG max fps:":"JPEG \u6700\u5927\u5e27\u7387:","H.264 kbps:":"H.264 kbps:","H.264 gop:":"H.264 gop:","Video mode":"\u89c6\u9891\u6a21\u5f0f","Orientation:":"\u65b9\u5411:","Default":"\u9ed8\u8ba4","Audio volume:":"\u97f3\u91cf:","Microphone:":"\u9ea6\u514b\u98ce:","Show stream":"\u663e\u793a\u89c6\u9891\u6d41","Screenshot":"\u622a\u56fe","Reset stream":"\u91cd\u7f6e\u89c6\u9891\u6d41","Keyboard mode:":"\u952e\u76d8\u6a21\u5f0f:","Mouse mode":"\u9f20\u6807\u6a21\u5f0f","Keyboard & mouse (HID) settings":"\u952e\u76d8\u4e0e\u9f20\u6807 (HID) \u8bbe\u7f6e","Swap Left Ctrl and Caps keys:":"\u4ea4\u6362\u5de6Ctrl\u548cCaps\u952e:","Mouse polling:":"\u9f20\u6807\u8f6e\u8be2\u7387:","Relative sensitivity:":"\u76f8\u5bf9\u7075\u654f\u5ea6:","Squash relative moves:":"\u538b\u7f29\u76f8\u5bf9\u79fb\u52a8:","Reverse scrolling:":"\u53cd\u5411\u6eda\u52a8:","Cumulative scrolling:":"\u7d2f\u79ef\u6eda\u52a8:","Scroll rate:":"\u6eda\u52a8\u901f\u7387:","Show the blue dot:":"\u663e\u793a\u84dd\u8272\u5149\u6807\u70b9:","Show local cursor:":"\u663e\u793a\u672c\u5730\u5149\u6807:","Web UI settings":"Web UI \u8bbe\u7f6e","Ask page close confirmation:":"\u5173\u95ed\u9875\u9762\u65f6\u786e\u8ba4:","Expand for the entire tab by default:":"\u9ed8\u8ba4\u5168\u5c4f\u5c55\u5f00:","Bad link mode (release keys immediately):":"\u5f31\u8fde\u63a5\u6a21\u5f0f(\u7acb\u5373\u91ca\u653e\u6309\u952e):","Connect HID to Server:":"HID\u8fde\u63a5\u670d\u52a1\u5668:","Mouse jiggler":"\u9f20\u6807\u9632\u7761","Mute all input HID events:":"\u9759\u97f3\u6240\u6709HID\u8f93\u5165:","Connect main USB to Server:":"\u4e3bUSB\u8fde\u63a5\u670d\u52a1\u5668:","Enable locator LED:":"\u542f\u7528\u5b9a\u4f4d LED:","Reset HID":"\u91cd\u7f6eHID","Show keyboard":"\u663e\u793a\u952e\u76d8","Paste text as keypress sequence":"\u7c98\u8d34\u6587\u5b57\u4e3a\u6309\u952e\u5e8f\u5217","Please note that KVMind cannot switch the keyboard layout":"\u6ce8\u610f: KVMind \u65e0\u6cd5\u5207\u6362\u952e\u76d8\u5e03\u5c40","Slow typing:":"\u6162\u901f\u8f93\u5165:","Hide input text:":"\u9690\u85cf\u8f93\u5165\u6587\u5b57:","Ask paste confirmation:":"\u7c98\u8d34\u65f6\u786e\u8ba4:","using host keymap":"\u4f7f\u7528\u4e3b\u673a\u952e\u4f4d\u6620\u5c04",
"Video Settings":"\u89c6\u9891\u8bbe\u7f6e","Stream mode:":"\u6d41\u6a21\u5f0f:","sm-auto":"\u81ea\u52a8","sm-webrtc":"WebRTC","sm-h264":"H.264","sm-mjpeg":"MJPEG","Audio volume:":"\u97f3\u91cf:","audio-hint":"HDMI \u97f3\u9891\u4ec5\u5728 WebRTC \u6a21\u5f0f\u4e0b\u53ef\u7528","Codec:":"\u7f16\u7801:","H.264 kbps:":"H.264 kbps:","H.264 gop:":"H.264 gop:","\ud83c\udfac Video":"\ud83c\udfac \u89c6\u9891","Mouse Settings":"\u9f20\u6807\u8bbe\u7f6e","Cursor style:":"\u5149\u6807\u6837\u5f0f:","cs-none":"\u9690\u85cf","cs-blue-dot":"\u84dd\u70b9","cs-crosshair":"\u5341\u5b57","cs-default":"\u7bad\u5934","cs-pointer":"\u624b\u578b","Mouse mode:":"\u9f20\u6807\u6a21\u5f0f:","mm-absolute":"\u7edd\u5bf9","mm-relative":"\u76f8\u5bf9","Reverse scroll:":"\u53cd\u5411\u6eda\u52a8:","Scroll speed:":"\u6eda\u52a8\u901f\u5ea6:","Sensitivity:":"\u7075\u654f\u5ea6:","Move squash:":"\u79fb\u52a8\u538b\u7f29:","Squash rate:":"\u538b\u7f29\u95f4\u9694:","Actions":"\u64cd\u4f5c","Reset Stream":"\u91cd\u7f6e\u89c6\u9891\u6d41","View Log":"\u67e5\u770b\u65e5\u5fd7","\ud83d\uddb1 Mouse":"\ud83d\uddb1 \u9f20\u6807","\u2699 Actions":"\u2699 \u64cd\u4f5c","\u2328 HID":"\u2328 HID","Keyboard layout:":"\u952e\u76d8\u5e03\u5c40:"},
ja:{"Runtime settings & tools":"\u30e9\u30f3\u30bf\u30a4\u30e0\u8a2d\u5b9a\u3068\u30c4\u30fc\u30eb","Resolution:":"\u89e3\u50cf\u5ea6:","JPEG quality:":"JPEG \u54c1\u8cea:","JPEG max fps:":"JPEG \u6700\u5927fps:","H.264 kbps:":"H.264 kbps:","H.264 gop:":"H.264 gop:","Video mode":"\u30d3\u30c7\u30aa\u30e2\u30fc\u30c9","Orientation:":"\u5411\u304d:","Default":"\u30c7\u30d5\u30a9\u30eb\u30c8","Audio volume:":"\u97f3\u91cf:","Microphone:":"\u30de\u30a4\u30af:","Show stream":"\u30b9\u30c8\u30ea\u30fc\u30e0\u8868\u793a","Screenshot":"\u30b9\u30af\u30ea\u30fc\u30f3\u30b7\u30e7\u30c3\u30c8","Reset stream":"\u30b9\u30c8\u30ea\u30fc\u30e0\u30ea\u30bb\u30c3\u30c8","Keyboard mode:":"\u30ad\u30fc\u30dc\u30fc\u30c9\u30e2\u30fc\u30c9:","Mouse mode":"\u30de\u30a6\u30b9\u30e2\u30fc\u30c9","Keyboard & mouse (HID) settings":"\u30ad\u30fc\u30dc\u30fc\u30c9\u3068\u30de\u30a6\u30b9 (HID) \u8a2d\u5b9a","Swap Left Ctrl and Caps keys":"\u5de6Ctrl\u3068Caps\u3092\u5165\u308c\u66ff\u3048:","Mouse polling:":"\u30de\u30a6\u30b9\u30dd\u30fc\u30ea\u30f3\u30b0:","Relative sensitivity:":"\u76f8\u5bfe\u611f\u5ea6:","Squash relative moves:":"\u76f8\u5bfe\u79fb\u52d5\u3092\u5727\u7e2e:","Reverse scrolling:":"\u30b9\u30af\u30ed\u30fc\u30eb\u53cd\u8ee2:","Cumulative scrolling:":"\u7d2f\u7a4d\u30b9\u30af\u30ed\u30fc\u30eb:","Scroll rate:":"\u30b9\u30af\u30ed\u30fc\u30eb\u901f\u5ea6:","Show the blue dot:":"\u9752\u3044\u30c9\u30c3\u30c8\u3092\u8868\u793a:","Show local cursor:":"\u30ed\u30fc\u30ab\u30eb\u30ab\u30fc\u30bd\u30eb\u8868\u793a:","Web UI settings":"Web UI \u8a2d\u5b9a","Ask page close confirmation:":"\u30da\u30fc\u30b8\u9589\u3058\u308b\u6642\u306b\u78ba\u8a8d:","Expand for the entire tab by default:":"\u30c7\u30d5\u30a9\u30eb\u30c8\u3067\u5168\u753b\u9762:","Bad link mode (release keys immediately):":"\u4e0d\u5b89\u5b9a\u63a5\u7d9a\u30e2\u30fc\u30c9:","Connect HID to Server:":"HID\u3092\u30b5\u30fc\u30d0\u30fc\u306b\u63a5\u7d9a:","Mouse jiggler":"\u30de\u30a6\u30b9\u30b8\u30b0\u30e9\u30fc","Mute all input HID events:":"\u5168HID\u5165\u529b\u3092\u30df\u30e5\u30fc\u30c8:","Connect main USB to Server:":"\u30e1\u30a4\u30f3USB\u3092\u30b5\u30fc\u30d0\u30fc\u306b\u63a5\u7d9a:","Enable locator LED:":"\u30ed\u30b1\u30fc\u30bf\u30fcLED:","Reset HID":"HID\u30ea\u30bb\u30c3\u30c8","Show keyboard":"\u30ad\u30fc\u30dc\u30fc\u30c9\u8868\u793a","Paste text as keypress sequence":"\u30c6\u30ad\u30b9\u30c8\u3092\u30ad\u30fc\u5165\u529b\u3068\u3057\u3066\u8cbc\u308a\u4ed8\u3051","Please note that KVMind cannot switch the keyboard layout":"KVMind\u306f\u30ad\u30fc\u30dc\u30fc\u30c9\u30ec\u30a4\u30a2\u30a6\u30c8\u3092\u5207\u308a\u66ff\u3048\u3089\u308c\u307e\u305b\u3093","Slow typing:":"\u4f4e\u901f\u5165\u529b:","Hide input text:":"\u5165\u529b\u30c6\u30ad\u30b9\u30c8\u3092\u96a0\u3059:","Ask paste confirmation:":"\u8cbc\u308a\u4ed8\u3051\u6642\u306b\u78ba\u8a8d:","using host keymap":"\u30db\u30b9\u30c8\u30ad\u30fc\u30de\u30c3\u30d7\u4f7f\u7528",
"Video Settings":"\u30d3\u30c7\u30aa\u8a2d\u5b9a","Stream mode:":"\u30b9\u30c8\u30ea\u30fc\u30e0\u30e2\u30fc\u30c9:","sm-auto":"\u81ea\u52d5","sm-webrtc":"WebRTC","sm-h264":"H.264","sm-mjpeg":"MJPEG","Audio volume:":"\u97f3\u91cf:","audio-hint":"HDMI\u97f3\u58f0\u306fWebRTC\u30e2\u30fc\u30c9\u306e\u307f","Codec:":"\u30b3\u30fc\u30c7\u30c3\u30af:","\ud83c\udfac Video":"\ud83c\udfac \u30d3\u30c7\u30aa","Mouse Settings":"\u30de\u30a6\u30b9\u8a2d\u5b9a","Cursor style:":"\u30ab\u30fc\u30bd\u30eb\u30b9\u30bf\u30a4\u30eb:","cs-none":"\u975e\u8868\u793a","cs-blue-dot":"\u9752\u30c9\u30c3\u30c8","cs-crosshair":"\u5341\u5b57","cs-default":"\u77e2\u5370","cs-pointer":"\u6307\u578b","Mouse mode:":"\u30de\u30a6\u30b9\u30e2\u30fc\u30c9:","mm-absolute":"\u7d76\u5bfe","mm-relative":"\u76f8\u5bfe","Reverse scroll:":"\u30b9\u30af\u30ed\u30fc\u30eb\u53cd\u8ee2:","Scroll speed:":"\u30b9\u30af\u30ed\u30fc\u30eb\u901f\u5ea6:","Sensitivity:":"\u611f\u5ea6:","Move squash:":"\u79fb\u52d5\u5727\u7e2e:","Squash rate:":"\u5727\u7e2e\u9593\u9694:","Actions":"\u64cd\u4f5c","Reset Stream":"\u30b9\u30c8\u30ea\u30fc\u30e0\u30ea\u30bb\u30c3\u30c8","View Log":"\u30ed\u30b0\u8868\u793a","\ud83d\uddb1 Mouse":"\ud83d\uddb1 \u30de\u30a6\u30b9","\u2699 Actions":"\u2699 \u64cd\u4f5c","\u2328 HID":"\u2328 HID","Keyboard layout:":"\u30ad\u30fc\u30dc\u30fc\u30c9\u30ec\u30a4\u30a2\u30a6\u30c8:"},
en:{"Video Settings":"Video Settings","Stream mode:":"Stream mode:","sm-auto":"Auto","sm-webrtc":"WebRTC","sm-h264":"H.264","sm-mjpeg":"MJPEG","Audio volume:":"Audio volume:","audio-hint":"HDMI audio only available in WebRTC mode","Codec:":"Codec:","H.264 kbps:":"H.264 kbps:","H.264 gop:":"H.264 gop:","\ud83c\udfac Video":"\ud83c\udfac Video","Mouse Settings":"Mouse Settings","Cursor style:":"Cursor style:","cs-none":"None","cs-blue-dot":"Blue Dot","cs-crosshair":"Crosshair","cs-default":"Arrow","cs-pointer":"Hand","Mouse mode:":"Mouse mode:","mm-absolute":"Absolute","mm-relative":"Relative","Reverse scroll:":"Reverse scroll:","Scroll speed:":"Scroll speed:","Sensitivity:":"Sensitivity:","Move squash:":"Move squash:","Squash rate:":"Squash rate:","Actions":"Actions","Reset Stream":"Reset Stream","Screenshot":"Screenshot","View Log":"View Log","\ud83d\uddb1 Mouse":"\ud83d\uddb1 Mouse","\u2699 Actions":"\u2699 Actions","\u2328 HID":"\u2328 HID","Keyboard layout:":"Keyboard layout:","Reset HID":"Reset HID","Runtime settings & tools":"Runtime settings & tools","Resolution:":"Resolution:","JPEG quality:":"JPEG quality:","JPEG max fps:":"JPEG max fps:","Video mode":"Video mode","Orientation:":"Orientation:","Default":"Default","Audio volume:":"Audio volume:","Microphone:":"Microphone:","Show stream":"Show stream","Reset stream":"Reset stream","Keyboard mode:":"Keyboard mode:","Mouse mode":"Mouse mode","Keyboard & mouse (HID) settings":"Keyboard & mouse (HID) settings","Swap Left Ctrl and Caps keys:":"Swap Left Ctrl and Caps keys:","Mouse polling:":"Mouse polling:","Relative sensitivity:":"Relative sensitivity:","Squash relative moves:":"Squash relative moves:","Reverse scrolling:":"Reverse scrolling:","Cumulative scrolling:":"Cumulative scrolling:","Scroll rate:":"Scroll rate:","Show the blue dot:":"Show the blue dot:","Show local cursor:":"Show local cursor:","Web UI settings":"Web UI settings","Ask page close confirmation:":"Ask page close confirmation:","Expand for the entire tab by default:":"Expand for the entire tab by default:","Bad link mode (release keys immediately):":"Bad link mode (release keys immediately):","Connect HID to Server:":"Connect HID to Server:","Mouse jiggler":"Mouse jiggler","Mute all input HID events:":"Mute all input HID events:","Connect main USB to Server:":"Connect main USB to Server:","Enable locator LED:":"Enable locator LED:","Show keyboard":"Show keyboard","Paste text as keypress sequence":"Paste text as keypress sequence","Please note that KVMind cannot switch the keyboard layout":"Please note that KVMind cannot switch the keyboard layout","Slow typing:":"Slow typing:","Hide input text:":"Hide input text:","Ask paste confirmation:":"Ask paste confirmation:","using host keymap":"using host keymap"}
};
function kvmindTranslateKVM(){
var lang=kvmindGetLang();
var enDict=KVMIND_KVM_I18N.en||{};
var dict=KVMIND_KVM_I18N[lang]||{};
var menu=document.getElementById("kvmind-settings-menu");
if(!menu)return;
// Build reverse lookup: any translated value -> english key
var allKeys={};
for(var k in(KVMIND_KVM_I18N.zh||{}))allKeys[k]=true;
for(var k2 in(KVMIND_KVM_I18N.ja||{}))allKeys[k2]=true;
// Translate <td>, <summary>, <b>, <sub>, <sup> text content (not inputs/selects)
var targets=menu.querySelectorAll("td,summary,b,sub,sup,div.text b");
targets.forEach(function(el){
if(el.tagName==="SELECT"||el.tagName==="INPUT"||el.tagName==="TEXTAREA")return;
if(el.children.length>0&&el.tagName!=="SUMMARY"&&el.tagName!=="B")return;
var txt=el.textContent.trim();
if(!txt||txt.length<2)return;
// Save original on first visit
if(!el.getAttribute("data-kv-orig")){el.setAttribute("data-kv-orig",txt);}
var orig=el.getAttribute("data-kv-orig");
// Strip trailing colon for matching
var origClean=orig;
if(dict[origClean]){el.textContent=dict[origClean];}
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
if(dict[orig]){el.textContent=(useBullet?"\u2022 ":"")+dict[orig];}
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
currentSubscription={plan:sub.plan||"community",messaging:!!sub.messaging};
var planMap={community:["Community","#6b7280"],standard:["Standard","#3ecf8e"],pro:["Pro","#8f77b5"]};
var planInfo=planMap[currentSubscription.plan]||[currentSubscription.plan,"#888"];
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
card.innerHTML='<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">'
+'<div style="width:44px;height:44px;border-radius:50%;background:var(--kvaccent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;flex-shrink:0">K</div>'
+'<div><div style="font-size:15px;font-weight:600;color:var(--kvtext)">KVMind Device</div>'
+'<div style="font-size:12px;color:var(--kvtext-muted);font-family:\'JetBrains Mono\',monospace">'+_escHtml(uid)+'</div></div></div>'
+'<div style="display:flex;flex-direction:column;font-size:13px;color:var(--kvtext)">'
+_row(kvmindT("pfFirmware"),fwVal)
+_row("AI Plan",_badge(planInfo[0],planInfo[1]))
+_row("AI Provider",_escHtml(providerNames),false)
+_row("Model",_escHtml(model),true)
+_row("Mode",'<span style="text-transform:capitalize">'+_escHtml(mode)+'</span>',false)
+_row("Bridge",bridgeOk?_badge("Online","#3ecf8e"):_badge("Offline","#ef5350"))
+_row(status.backend||"KVM",kvmOk?_badge("Online","#3ecf8e"):_badge("Offline","#ef5350"))
+'</div>'
+(hasUpdate?'<div id="kvmind-update-section" style="margin-top:14px;padding:12px;border:1px solid rgba(59,130,246,.3);border-radius:8px;background:rgba(59,130,246,.05)">'
+'<div style="font-size:12px;font-weight:600;color:var(--kvtext);margin-bottom:4px">'+kvmindT("updateNewVer")+' v'+_escHtml(latestVer)+'</div>'
+(changelog?'<div style="font-size:11px;color:var(--kvtext-muted);margin-bottom:10px">'+_escHtml(changelog)+'</div>':'')
+'<button id="kvmind-update-btn" style="width:100%;padding:8px 0;border:none;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer;font-size:13px;font-weight:600">'+kvmindT("updateBtn")+'</button>'
+'</div>':'')
+'<button id="kvmind-profile-close" style="margin-top:'+(hasUpdate?'10':'18')+'px;width:100%;padding:8px 0;border:1px solid var(--kvborder);border-radius:6px;background:var(--kvsurface2);color:var(--kvtext);cursor:pointer;font-size:13px">OK</button>';
document.getElementById("kvmind-profile-close").addEventListener("click",function(){overlay.remove();});
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
function kvmindCheckStatus(){kvmindFetch("/api/status").then(function(r){return r.json();}).then(function(){kvmindSetConn(true);}).catch(function(){kvmindSetConn(false);});kvmindSyncPlan();}
function kvmindSyncPlan(){fetch(KVMIND_API+"/api/subscription").then(function(r){return r.json();}).then(function(sub){var plan=sub.plan||"community";if(plan!==currentSubscription.plan){currentSubscription={plan:plan,messaging:!!sub.messaging};kvmindUpdatePlanUI(plan);}}).catch(function(e){console.warn("[kvmind]",e);});}
function kvmindSetConn(online){var el=document.getElementById("kvmind-conn-status");var txt=document.getElementById("kvmind-conn-text");if(!el)return;el.className=online?"online":"offline";txt.textContent=kvmindT(online?"connected":"disconnected");}

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
if(role==="user"||role==="ai"){var s=document.createElement("div");s.className="kvmind-msg-sender";s.textContent=role==="user"?"\u4f60":"MyClaw";row.appendChild(s);}
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg "+role;
if(extraClass)bubble.classList.add(extraClass);if(status)bubble.classList.add(status);
bubble.textContent=text;row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
}

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
else if(window._kvGw){window._kvGw.sendConfirm(approved,runId);}
}

// ── Send ──
function kvmindDoSend(){
var inp=document.getElementById("kvmind-chat-input");if(!inp)return;var text=inp.value.trim();if(!text)return;
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
kvmindAppendMsg("system","\u26a0 AI \u672a\u8fde\u63a5\uff0c\u8bf7\u5237\u65b0\u9875\u9762");
}
}

// ── Analyse ──
function kvmindDoAnalyse(){
var sh=document.getElementById("kvmind-snap-hint");if(sh)sh.style.display="none";
kvmindAppendMsg("system","\u5206\u6790\u4e2d\u2026");kvmindAddLog("info","Analysing...");
kvmindFetch("/api/analyse",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lang:kvmindGetLang()})}).then(function(r){return r.text();}).then(function(txt){
var d;try{d=JSON.parse(txt);}catch(e){d=null;}
if(!d||d.error){console.error("Analyse error:",d?d.error:txt);kvmindAppendMsg("action","\u26a0 AI \u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528",null,"err");return;}
kvmindAppendMsg("ai",d.text||JSON.stringify(d));kvmindAddLog("ok","Analysis done");
}).catch(function(e){console.error("Analyse fetch error:",e);kvmindAppendMsg("system","\u26a0 \u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5");});
}

// ── Screen Copy (OCR) ──
function kvmindDoScreenCopy(){
kvmindAppendMsg("system",kvmindT("copyExtracting"));kvmindAddLog("info","Screen copy...");
kvmindFetch("/api/screen/copy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lang:kvmindGetLang()})}).then(function(r){return r.text();}).then(function(txt){
var d;try{d=JSON.parse(txt);}catch(e){d=null;}
if(!d||d.error){kvmindAppendMsg("action",kvmindT("copyFailed"),null,"err");kvmindAddLog("error","Screen copy failed");return;}
kvmindShowCopyModal(d.text||"");kvmindAddLog("ok","Screen copy done");
}).catch(function(e){console.error("Screen copy error:",e);kvmindAppendMsg("system",kvmindT("copyFailed"));});
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
fetch("/streamer/snapshot").then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.blob();}).then(function(blob){
var url=URL.createObjectURL(blob);var c=document.getElementById("kvmind-chat-messages");if(!c)return;
var row=document.createElement("div");row.className="kvmind-msg-row ai";
var bubble=document.createElement("div");bubble.className="kvmind-chat-msg snap";
var img=document.createElement("img");img.src=url;img.style.cssText="width:100%;display:block";img.onload=function(){URL.revokeObjectURL(url);};
var cap=document.createElement("div");cap.className="kvmind-snap-cap";var capL=document.createElement("span");capL.textContent="Screenshot";var capR=document.createElement("span");capR.textContent=new Date().toLocaleTimeString();cap.appendChild(capL);cap.appendChild(capR);
bubble.appendChild(img);bubble.appendChild(cap);row.appendChild(bubble);c.appendChild(row);c.scrollTop=c.scrollHeight;
}).catch(function(e){console.error("Screenshot error:",e);kvmindAppendMsg("system","\u26a0 \u622a\u56fe\u83b7\u53d6\u5931\u8d25");});
}

function kvmindDoAbort(){if(window._kvGw&&window._kvGw.connected)window._kvGw.abortChat();else kvmindFetch("/api/agent/abort",{method:"POST"});_endChat();}
function kvmindSetMode(mode){
agentMode=mode;["suggest","auto"].forEach(function(m){var pm=document.getElementById("kvmind-pm-"+m);if(pm)pm.classList.toggle("active",m===mode);});
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
var T=_kvSettT;
var tabs=[{id:"video",label:T("\ud83c\udfac Video")},{id:"mouse",label:T("\ud83d\uddb1 Mouse")},{id:"actions",label:T("\u2699 Actions")},{id:"hid",label:T("\u2328 HID")}];
var html='<div class="kvmind-settings-tabs">';
for(var t=0;t<tabs.length;t++){
html+='<button class="kvmind-settings-tab'+(tabs[t].id===_kvSettingsActiveTab?' active':'')+'" onclick="event.stopPropagation();kvmindLoadSettings(\''+tabs[t].id+'\')">'+tabs[t].label+'</button>';
}
html+='</div>';

// ── Video Tab ──
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="video"?" active":"")+'">';
html+='<div class="kvmind-settings-section"><div class="kvmind-settings-title">'+T("Video Settings")+'</div>';
html+='<table class="kvmind-settings-table">';
var _curSM=(window._kvmindStream&&window._kvmindStream.getPreferredMode)?window._kvmindStream.getPreferredMode():"auto";
var _actSM=(window._kvmindStream&&window._kvmindStream.getMode)?window._kvmindStream.getMode():"";
html+='<tr><td class="kvs-label">'+T("Stream mode:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-mode-pills" id="kvs-stream-mode">';
var _smOpts=["auto","webrtc","media","mjpeg"];
var _smKeys={"auto":"sm-auto","webrtc":"sm-webrtc","media":"sm-h264","mjpeg":"sm-mjpeg"};
for(var _si=0;_si<_smOpts.length;_si++){var _sv=_smOpts[_si];html+='<button class="kvmind-pill'+(_curSM===_sv?" active":"")+'" data-val="'+_sv+'" onclick="window._kvmindStream&&window._kvmindStream.setMode(\''+_sv+'\');kvmindLoadSettings(\'video\')">'+T(_smKeys[_sv])+'</button>';}
html+='</div></td></tr>';
var _modeLabel={"webrtc":"WebRTC","media":"H.264","mjpeg":"MJPEG"};
html+='<tr><td class="kvs-label">'+T("Codec:")+'</td><td class="kvs-ctrl"><span id="kvs-codec-display" style="font-family:monospace;font-weight:600">--'+(_actSM&&_modeLabel[_actSM]?" ["+_modeLabel[_actSM]+"]":"")+'</span></td></tr>';
html+='<tr><td class="kvs-label">'+T("H.264 kbps:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-h264-bitrate" min="1000" max="20000" step="500" value="20000" class="kvmind-settings-range" oninput="document.getElementById(\'kvs-br-val\').textContent=this.value+\' kbps\'" onchange="fetch(\'/api/streamer/set_params?h264_bitrate=\'+this.value,{method:\'POST\',credentials:\'same-origin\'})"><span id="kvs-br-val" class="kvmind-slider-val">20000 kbps</span></div></td></tr>';
html+='<tr><td class="kvs-label">'+T("H.264 gop:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-h264-gop" min="0" max="60" step="5" value="0" class="kvmind-settings-range" oninput="document.getElementById(\'kvs-gop-val\').textContent=this.value" onchange="fetch(\'/api/streamer/set_params?h264_gop=\'+this.value,{method:\'POST\',credentials:\'same-origin\'})"><span id="kvs-gop-val" class="kvmind-slider-val">0</span></div></td></tr>';
var _audioVol=window._kvmindStream&&window._kvmindStream.getVolume?window._kvmindStream.getVolume():0.5;
var _audioVolPct=Math.round(_audioVol*100);
html+='<tr><td class="kvs-label">'+T("Audio volume:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-audio-vol" min="0" max="100" step="5" value="'+_audioVolPct+'" class="kvmind-settings-range" oninput="var v=this.value/100;window._kvmindStream&&window._kvmindStream.setVolume(v);document.getElementById(\'kvs-vol-val\').textContent=this.value+\'%\'" onchange="var v=this.value/100;window._kvmindStream&&window._kvmindStream.setVolume(v)"><span id="kvs-vol-val" class="kvmind-slider-val">'+_audioVolPct+'%</span></div>';
html+='<div style="font-size:11px;color:var(--kvtext-muted);margin-top:2px">'+T("audio-hint")+'</div></td></tr>';
html+='</table></div></div>';

// ── Mouse Tab ──
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="mouse"?" active":"")+'">';
html+='<div class="kvmind-settings-section"><div class="kvmind-settings-title">'+T("Mouse Settings")+'</div>';
html+='<table class="kvmind-settings-table">';

var curStyle=hid&&hid.getCursorStyle?hid.getCursorStyle():"blue-dot";
html+='<tr><td class="kvs-label">'+T("Cursor style:")+'</td>';
html+='<td class="kvs-ctrl"><select id="kvs-cursor-style" class="kvmind-settings-select" onchange="window._kvmindHid&&window._kvmindHid.setCursorStyle(this.value)">';
var csOpts=["none","blue-dot","crosshair","default","pointer"];
for(var i=0;i<csOpts.length;i++){
  html+='<option value="'+csOpts[i]+'"'+(curStyle===csOpts[i]?' selected':'')+'>'+T("cs-"+csOpts[i])+'</option>';
}
html+='</select></td></tr>';

var mMode=hid&&hid.getMouseMode?hid.getMouseMode():"absolute";
html+='<tr><td class="kvs-label">'+T("Mouse mode:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-mode-pills" id="kvs-mouse-mode">';
html+='<button class="kvmind-pill'+(mMode==="absolute"?" active":"")+'" data-val="absolute" onclick="window._kvmindHid&&window._kvmindHid.setMouseMode(\'absolute\');kvmindLoadSettings(\'mouse\')">'+T("mm-absolute")+'</button>';
html+='<button class="kvmind-pill'+(mMode==="relative"?" active":"")+'" data-val="relative" onclick="window._kvmindHid&&window._kvmindHid.setMouseMode(\'relative\');kvmindLoadSettings(\'mouse\')">'+T("mm-relative")+'</button>';
html+='</div></td></tr>';

var revScroll=hid&&hid.getScrollReverse?hid.getScrollReverse():false;
html+='<tr><td class="kvs-label">'+T("Reverse scroll:")+'</td>';
html+='<td class="kvs-ctrl"><label class="kvmind-toggle"><input type="checkbox" id="kvs-reverse-scroll"'+(revScroll?' checked':'')+' onchange="window._kvmindHid&&window._kvmindHid.setScrollReverse(this.checked)"><span class="kvmind-toggle-slider"></span></label></td></tr>';

var scrollRate=hid&&hid.getScrollRate?hid.getScrollRate():5;
html+='<tr><td class="kvs-label">'+T("Scroll speed:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-scroll-rate" min="1" max="25" value="'+scrollRate+'" class="kvmind-settings-range" oninput="window._kvmindHid&&window._kvmindHid.setScrollRate(this.value);document.getElementById(\'kvs-scroll-val\').textContent=this.value"><span id="kvs-scroll-val" class="kvmind-slider-val">'+scrollRate+'</span></div></td></tr>';

var sens=hid&&hid.getSensitivity?hid.getSensitivity():1.0;
html+='<tr class="kvs-rel-only" style="'+(mMode==="relative"?"":"display:none")+'"><td class="kvs-label">'+T("Sensitivity:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-sensitivity" min="1" max="19" value="'+Math.round(sens*10)+'" class="kvmind-settings-range" oninput="var v=this.value/10;window._kvmindHid&&window._kvmindHid.setSensitivity(v);document.getElementById(\'kvs-sens-val\').textContent=v.toFixed(1)"><span id="kvs-sens-val" class="kvmind-slider-val">'+sens.toFixed(1)+'</span></div></td></tr>';

var squash=hid&&hid.getSquashEnabled?hid.getSquashEnabled():true;
html+='<tr><td class="kvs-label">'+T("Move squash:")+'</td>';
html+='<td class="kvs-ctrl"><label class="kvmind-toggle"><input type="checkbox" id="kvs-squash"'+(squash?' checked':'')+' onchange="window._kvmindHid&&window._kvmindHid.setSquashEnabled(this.checked)"><span class="kvmind-toggle-slider"></span></label></td></tr>';

var mRate=hid&&hid.getMoveRate?hid.getMoveRate():10;
html+='<tr><td class="kvs-label">'+T("Squash rate:")+'</td>';
html+='<td class="kvs-ctrl"><div class="kvmind-slider-wrap"><input type="range" id="kvs-move-rate" min="10" max="100" step="10" value="'+mRate+'" class="kvmind-settings-range" oninput="window._kvmindHid&&window._kvmindHid.setMoveRate(this.value);document.getElementById(\'kvs-rate-val\').textContent=this.value+\'ms\'"><span id="kvs-rate-val" class="kvmind-slider-val">'+mRate+'ms</span></div></td></tr>';

html+='</table></div>';
html+='</div>';

// ── Actions Tab ──
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="actions"?" active":"")+'">';
html+='<div class="kvmind-settings-section"><div class="kvmind-settings-title">'+T("Actions")+'</div>';
html+='<div style="display:flex;flex-wrap:wrap;gap:6px">';
html+='<button class="kvmind-tb-btn" onclick="fetch(\'/api/streamer/reset\',{method:\'POST\',credentials:\'same-origin\'});kvmindAddLog(\'ok\',\'Stream reset\')">'+T("Reset Stream")+'</button>';
html+='<button class="kvmind-tb-btn" onclick="window.open(\'/api/streamer/snapshot\',\'_blank\')">'+T("Screenshot")+'</button>';
html+='<button class="kvmind-tb-btn" onclick="window.open(\'/api/log?seek=3600&follow=1\',\'_blank\')">'+T("View Log")+'</button>';
html+='</div></div>';
html+='</div>';

// ── HID Tab ──
html+='<div class="kvmind-settings-tab-panel'+(_kvSettingsActiveTab==="hid"?" active":"")+'">';
html+='<div class="kvmind-settings-section"><div class="kvmind-settings-title">HID</div>';
html+='<table class="kvmind-settings-table">';
html+='<tr><td class="kvs-label">'+T("Keyboard layout:")+'</td>';
html+='<td class="kvs-ctrl"><select id="kvs-kb-layout" class="kvmind-settings-select" onchange="window._kvmindHid&&window._kvmindHid.setKeyboardLayout&&window._kvmindHid.setKeyboardLayout(this.value)">';
var kbLayout=(hid&&hid.getKeyboardLayout)?hid.getKeyboardLayout():"en-us";
var kbOpts=[["en-us","English (US)"],["en-gb","English (UK)"],["de","Deutsch"],["fr","Fran\u00e7ais"],["es","Espa\u00f1ol"],["it","Italiano"],["ja","Japanese"],["ko","Korean"],["zh","Chinese"]];
for(var k=0;k<kbOpts.length;k++){
html+='<option value="'+kbOpts[k][0]+'"'+(kbLayout===kbOpts[k][0]?' selected':'')+'>'+kbOpts[k][1]+'</option>';
}
html+='</select></td></tr>';
html+='</table>';
html+='<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:12px">';
html+='<button class="kvmind-tb-btn" onclick="window._kvmindHid&&window._kvmindHid.resetHID();kvmindAddLog(\'ok\',\'HID reset\')">'+T("Reset HID")+'</button>';
html+='</div></div>';
html+='</div>';

m.innerHTML=html;
kvmindTranslateKVM();
if(_kvSettingsActiveTab==="video"){
fetch("/api/streamer",{credentials:"same-origin"}).then(function(r){return r.json();}).then(function(d){
var p=d.result.params;
var s=d.result.streamer;
var brEl=document.getElementById("kvs-h264-bitrate");
var gopEl=document.getElementById("kvs-h264-gop");
var codecEl=document.getElementById("kvs-codec-display");
if(brEl){brEl.value=p.h264_bitrate;document.getElementById("kvs-br-val").textContent=p.h264_bitrate+" kbps";}
if(gopEl){gopEl.value=p.h264_gop;document.getElementById("kvs-gop-val").textContent=p.h264_gop;}
if(codecEl&&s){
var src=s.source||{};
var res=src.resolution||{};
var _modeNow=(window._kvmindStream&&window._kvmindStream.getMode)||"";
if(typeof _modeNow==="function")_modeNow=_modeNow();
var _modeTag={"webrtc":" [WebRTC]","media":" [H.264]","mjpeg":" [MJPEG]"};
codecEl.textContent="H.264 "+res.width+"x"+res.height+" @ "+s.h264.fps+" fps"+(s.h264.online?" \u2714":"")+(_modeTag[_modeNow]||"");
}
}).catch(function(e){console.warn("[kvmind]",e);});
}
}
function _kvSettT(key){var lang=kvmindGetLang();var d=KVMIND_KVM_I18N[lang]||{};return d[key]||key;}

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
var plan=sub.plan||"community";
var labels={community:"Community",standard:"Standard",pro:"Pro"};
var colors={community:"#6b7280",standard:"#3ecf8e",pro:"#8f77b5"};
badge.textContent=labels[plan]||plan;
badge.style.background=colors[plan]||"#6b7280";
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
_umLang.addEventListener("change",function(){localStorage.setItem("kvmind_lang",this.value);kvmindApplyLang();});
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
var text=err,logText=err;
if(err&&typeof err==="object"){
if(err.code==="ws_not_open"){text=kvmindT("wsReconnecting")||"Reconnecting — please try again in a moment.";logText="ws_not_open";}
else{text=err.message||err.code||"unknown error";logText=text;}}
kvmindAppendMsg("system","\u26a0 "+text);kvmindAddLog("error",logText);
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
window._kvGw.onLog=function(level,msg){kvmindAddLog(level,msg);};
window._kvGw.onConfirmRequired=function(action,args,runId){
var ctext=action==="dangerous_instruction"?(args.instruction||action):(action+": "+JSON.stringify(args));
kvmindShowConfirm(ctext,action,runId);
};
window._kvGw.connect();
}

// Load version
fetch("/kdkvm/version.json?t="+Date.now()).then(function(r){return r.json()}).then(function(d){var el=document.getElementById("kvmind-ver");if(el)el.textContent="v"+d.version;}).catch(function(e){console.warn("[kvmind]",e);});

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

// Update toolbar & menu buttons based on subscription
fetch(KVMIND_API+"/api/subscription").then(function(r){return r.json()}).then(function(sub){
    currentSubscription={plan:sub.plan||"community",messaging:!!sub.messaging};
    kvmindUpdatePlanUI(currentSubscription.plan);
}).catch(function(e){console.warn("[kvmind]",e);});

function kvmindUpdatePlanUI(plan){
    var badge=document.getElementById("kvmind-plan-badge");
    var planLabels={community:"Community",standard:"Standard",pro:"Pro"};
    var planColors={community:"#6b7280",standard:"#3ecf8e",pro:"#8f77b5"};
    var label=planLabels[plan]||plan;
    var color=planColors[plan]||"#6b7280";
    if(badge){badge.textContent=label;badge.style.background=color;}
}

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
