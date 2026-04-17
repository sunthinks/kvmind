/**
 * kvmind-theme.js — KVMind Theme Enhancements
 * Handles dynamic theme-related JS (logo gradient, etc.)
 * CSS variables and styles are all in kvmind.css.
 */
(function () {
  "use strict";

  // =========================================================================
  // Logo gradient
  // =========================================================================

  function fixLogoGradient() {
    var logo = document.querySelector(".kvmind-tb-logo");
    if (!logo) return;

    var textNodes = [];
    logo.childNodes.forEach(function (n) {
      if (n.nodeType === 3 && n.textContent.trim()) textNodes.push(n);
    });

    textNodes.forEach(function (n) {
      var span = document.createElement("span");
      span.style.cssText = [
        "background: linear-gradient(135deg, #68B0AB, #8F77B5)",
        "-webkit-background-clip: text",
        "-webkit-text-fill-color: transparent",
        "background-clip: text"
      ].join(";");
      span.textContent = n.textContent;
      n.parentNode.replaceChild(span, n);
    });
  }

  // =========================================================================
  // Entry point
  // =========================================================================

  function init() {
    fixLogoGradient();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
