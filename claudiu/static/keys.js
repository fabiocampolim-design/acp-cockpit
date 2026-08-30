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
  return { normalize, matches };
})();
