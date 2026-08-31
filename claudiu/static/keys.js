// claudiu/static/keys.js
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Fabio Campolim
"use strict";
window.ClaudiuKeys = (function () {
  function normalize(spec) {
    const parts = spec.split("+");
    const key = parts.pop();
    return {
      alt: parts.includes("Alt"),
      ctrl: parts.includes("Ctrl"),
      shift: parts.includes("Shift"),
      key: key.toLowerCase(),
    };
  }
  function matches(ev, spec) {
    const n = normalize(spec);
    return ev.altKey === n.alt && ev.ctrlKey === n.ctrl &&
      ev.shiftKey === n.shift && ev.key.toLowerCase() === n.key;
  }
  // display form: "Alt+h" -> "Alt+H" (single-letter keys are matched
  // case-insensitively, shown upper-case like every keyboard legend)
  function pretty(spec) {
    const parts = spec.split("+");
    const key = parts.pop();
    parts.push(key.length === 1 ? key.toUpperCase() : key);
    return parts.join("+");
  }
  return { normalize, matches, pretty };
})();
