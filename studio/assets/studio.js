/* 디자인 스튜디오 — 아무 웹 앱의 진짜 화면 위에 얹는 편집 도구.
   화면을 직접 만져 보고(색·크기·간격·위치·글자) 영역마다 댓글을 달아 저장하면,
   Claude Code 가 저장본(<앱 저장소>/.design-studio/requests/*.md·json)을 읽어 실제 코드에 옮긴다.
   앱마다 다른 것(화면 이름·테마·색 토큰·화면 바꾸기)은 window.__STUDIO_APP__ (앱 설정의 client 스크립트)이 알려 준다.
   없으면 :root 의 CSS 변수를 찾아 토큰으로 쓰고, 화면은 하나('page')로 본다.

   지키는 것
   - 앱 화면 코드는 한 줄도 건드리지 않는다. 바꾼 모양은 맨 뒤에 붙인 <style> 한 장(덮어쓰기 규칙)으로만 보여 준다.
     그래서 앱이 목록을 다시 그려도 모양 변경은 그대로 남고, 저장본에 '그대로 붙일 수 있는 CSS' 가 함께 나간다.
   - 도구 화면은 Shadow DOM 안에 둔다. 앱의 전역 스타일([hidden]·button 등)과 서로 섞이지 않게.
   - 고르기·댓글 모드에서는 앱이 누르기를 받지 않는다(동기화 단추를 눌러도 아무 일 없음). Alt 를 누른 채 누르면 앱이 그대로 받는다. */
(() => {
  "use strict";
  const INFO = window.__STUDIO__ || {};
  // 시안을 보며 단 댓글과 원래 화면에서 단 댓글은 따로 이어 한다
  const APP = window.__STUDIO_APP__ || {};
  const APP_KEY = String(INFO.app || "app").replace(/[^\w가-힣-]/g, "");
  const DRAFT_KEY = `studio-draft-v1:${APP_KEY}` + (INFO.ctx ? `:${INFO.ctx}` : "");
  const PARAMS = new URLSearchParams(location.search);

  // '지금 열려 있음·골라짐' 같은 상태 이름표는 모양 범위를 정할 때 빼야 같은 모양을 모두 잡는다
  const STATE_CLS = /^(active|open|opened|selected|current|is-|has-|show|shown|visible|collapsed|expanded|dragging|drag-|drop-|loading|focus|hover|today|now)/;
  // 앱이 알려 준 것 (없으면 아래 기본값과 자동 찾기)
  const VIEW_LABEL = APP.views || {};
  const THEMES = APP.themes && APP.themes.length ? APP.themes : [{ key: "default", label: "기본", selector: ":root" }];
  const SHADOWS = [
    ["그대로", ""], ["없음", "none"], ["약하게", "0 1px 2px rgba(0,0,0,.06)"],
    ...(APP.shadowToken ? [["앱 기본", `var(${APP.shadowToken})`]] : []),
    ["강하게", "0 14px 34px -12px rgba(0,0,0,.30)"],
  ];
  const ACCENT = { main: "--accent", strong: "--accent-strong", soft: "--accent-soft", surface: "--surface", ...(APP.accent || {}) };
  const KINDS = [["fix", "고쳐 줘"], ["idea", "아이디어"], ["keep", "좋아요·유지"], ["question", "질문"]];

  /* ---------- 상태 ---------- */
  let seq = 1;
  const uid = (p) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;
  const newVariant = (name, changes = []) => ({ id: uid("v"), name, changes });
  const S = {
    mode: "browse",
    variants: [newVariant("조합 A")],
    active: 0,
    comments: [],
    title: "",
    note: "",
    freedom: "refine",
    tab: "palette",
    hover: null,
    sel: null, // { el, path }
    scope: null, // 고른 요소에 쓸 선택자
    undo: [],
    redo: [],
    editKey: null,
    editing: null, // 글자 고치는 중인 요소
    side: "right",
    collapsed: false,
    clean: PARAMS.get("clean") === "1",
    savedAs: "",
    proposals: [], // 시안 목록 (서버에서 2.5초마다)
    drag: null, // 고른 요소를 직접 끌어 옮기는 중
    justDragged: false,
    demoing: false, // 동작 흐름·추천 시연 중 (앱이 누르기를 그대로 받는다)
    flow: null, // 고른 단추의 동작 흐름 편집본 { path, steps, before, summary, where, job }
    ai: { status: "idle", open: false, job: null, items: [], idx: 0, ask: "", lastAt: 0, auto: loadPref("ai-auto", true) },
  };
  const cur = () => S.variants[S.active];
  function loadPref(key, fallback) {
    try {
      const v = localStorage.getItem(`studio-${key}`);
      return v == null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  }
  function savePref(key, value) {
    try { localStorage.setItem(`studio-${key}`, JSON.stringify(value)); } catch { /* 이번 창에서만 기억 */ }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ---------- 작은 도구 ---------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeMatches = (el, sel) => { try { return el.matches(sel); } catch { return false; } };
  const themeKey = () => {
    if (APP.currentTheme) { try { return APP.currentTheme() || THEMES[0].key; } catch { /* 아래 기본 */ } }
    const hit = THEMES.find((t) => t.selector && t.selector !== ":root" && safeMatches(document.documentElement, t.selector));
    return (hit || THEMES[0]).key;
  };
  const themeLabel = (k) => (THEMES.find((t) => t.key === k) || { label: k }).label;
  const viewKey = () => {
    try { return (APP.currentView && APP.currentView()) || "page"; } catch { return "page"; }
  };
  const viewLabel = (v) => VIEW_LABEL[v] || v;
  const rootVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  /* 색·크기 토큰: 앱이 알려 주지 않으면 :root(html) 규칙에 적힌 CSS 변수를 모아 만든다 */
  let AUTO = null;
  function autoScan() {
    if (AUTO) return AUTO;
    const names = new Set();
    const walk = (rules) => {
      for (const r of rules) {
        try {
          if (r.cssRules && !r.selectorText) walk(r.cssRules); // @media·@supports 안
          else if (r.style && /(^|,)\s*(:root|html)\b/.test(r.selectorText || "")) for (const prop of r.style) if (prop.startsWith("--")) names.add(prop);
        } catch { /* 이 규칙만 건너뛴다 */ }
      }
    };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules); } catch { /* 다른 출처 시트는 못 읽는다 */ } }
    const colors = [], sizes = [];
    for (const n of names) {
      const v = rootVar(n);
      if (!v || v.length > 60) continue;
      if (/^(#|rgb|hsl|oklch|oklab|lab|lch|color\()/i.test(v) && CSS.supports("color", v)) colors.push([n, n.slice(2)]);
      else if (/^-?[\d.]+px$/.test(v)) sizes.push([n, n.slice(2), 0, Math.max(48, Math.ceil(parseFloat(v) * 2))]);
    }
    AUTO = { colors: colors.length ? [["색", colors.slice(0, 80)]] : [], sizes: sizes.slice(0, 12) };
    return AUTO;
  }
  const tokenGroups = () => APP.tokens || autoScan().colors;
  const sizeTokens = () => APP.sizeTokens || autoScan().sizes;
  const px = (v) => Math.round(parseFloat(v) || 0);
  // 패널은 바깥 틀 문서에 있어 앱의 색 토큰(var(--accent))이 거기선 안 풀린다. 앱 문서에서 값을 읽어 넘긴다.
  const resolveColor = (v) => String(v).replace(/var\((--[\w-]+)\)/g, (_, name) => rootVar(name) || "transparent");

  const colorCtx = document.createElement("canvas").getContext("2d");
  function toHex(color) {
    if (!color) return "#000000";
    colorCtx.fillStyle = "#000000";
    colorCtx.fillStyle = color;
    const v = colorCtx.fillStyle; // '#rrggbb' 또는 'rgba(r, g, b, a)'
    if (v.startsWith("#")) return v;
    const m = v.match(/[\d.]+/g) || [0, 0, 0];
    return "#" + m.slice(0, 3).map((n) => Math.round(+n).toString(16).padStart(2, "0")).join("");
  }
  const isClear = (c) => /^transparent$|rgba\([^)]*,\s*0\)$/.test(String(c).trim());
  function hexToHsl(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0;
    const l = (max + min) / 2;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h /= 6;
    }
    return [h, s, l];
  }
  function hslToHex(h, s, l) {
    l = Math.min(1, Math.max(0, l));
    const f = (n) => {
      const k = (n + h * 12) % 12;
      const a = s * Math.min(l, 1 - l);
      return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))).toString(16).padStart(2, "0");
    };
    return `#${f(0)}${f(8)}${f(4)}`;
  }
  function mix(a, b, t) {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const ch = (p, sh) => (p >> sh) & 255;
    return "#" + [16, 8, 0].map((sh) => Math.round(ch(pa, sh) * (1 - t) + ch(pb, sh) * t).toString(16).padStart(2, "0")).join("");
  }

  /* ---------- 요소 이름 붙이기 ---------- */
  function goodClasses(el) {
    return [...el.classList].filter((c) => !STATE_CLS.test(c) && !c.startsWith("__studio"));
  }
  function cssPath(el) {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      if (n !== el && n.id) { parts.unshift(`#${CSS.escape(n.id)}`); break; }
      let s = n.tagName.toLowerCase();
      const c = goodClasses(n)[0];
      if (c) s += `.${CSS.escape(c)}`;
      const p = n.parentElement;
      if (p && n !== document.body) {
        const same = [...p.children].filter((x) => x.tagName === n.tagName);
        if (same.length > 1) s += `:nth-of-type(${same.indexOf(n) + 1})`;
      }
      parts.unshift(s);
      if (n === document.body) break;
    }
    return parts.join(" > ");
  }
  function nearestNamed(el) {
    for (let n = el, i = 0; n && n !== document.body && i < 4; n = n.parentElement, i++) {
      if (n.id) return `#${CSS.escape(n.id)}`;
      const c = goodClasses(n)[0];
      if (c) return `.${CSS.escape(c)}`;
    }
    return "";
  }
  const countOf = (sel) => {
    try { return document.querySelectorAll(sel).length; } catch { return 0; }
  };
  function scopeOptions(el) {
    const out = [];
    const push = (sel, label) => {
      if (!sel || out.some((o) => o.sel === sel)) return;
      const n = countOf(sel);
      if (n) out.push({ sel, n, label });
    };
    const cls = goodClasses(el);
    const tag = el.tagName.toLowerCase();
    if (cls.length) {
      const full = "." + cls.map((c) => CSS.escape(c)).join(".");
      push(full, "같은 모양 모두");
      if (cls.length > 1) push(`.${CSS.escape(cls[0])}`, "더 넓게");
      const p = el.parentElement && nearestNamed(el.parentElement);
      if (p) push(`${p} ${full}`, "이 묶음 안에서만");
    } else {
      const p = el.parentElement && nearestNamed(el.parentElement);
      if (p) push(`${p} ${tag}`, "같은 묶음의 같은 태그");
    }
    if (el.id) push(`#${CSS.escape(el.id)}`, "이 요소(id)");
    push(cssPath(el), "이 요소만");
    return out;
  }

  let RULES = null;
  const UNIVERSAL = /^\s*(\*|\*?::?[\w-]+(\([^)]*\))?|html|body|:root)\s*$/;
  function cssRules() {
    if (RULES) return RULES;
    RULES = [];
    const walk = (rules, media) => {
      for (const r of rules) {
        if (r.selectorText) RULES.push({ sel: r.selectorText, media, rule: r });
        else if (r.cssRules) walk(r.cssRules, r.conditionText || (r.media && r.media.mediaText) || media);
      }
    };
    for (const sh of document.styleSheets) {
      if (!sh.href || !/\/styles\.css/.test(sh.href)) continue;
      try { walk(sh.cssRules, ""); } catch { /* 다른 출처 스타일시트는 못 읽는다 */ }
    }
    return RULES;
  }
  function matchedRules(el) {
    const out = [];
    for (const r of cssRules()) {
      if (r.sel.split(",").every((part) => UNIVERSAL.test(part))) continue;
      let ok = false;
      try { ok = el.matches(r.sel); } catch { ok = false; }
      if (!ok) continue;
      const text = r.media ? `${r.sel}  (@media ${r.media})` : r.sel;
      if (!out.includes(text)) out.push(text);
    }
    return out.slice(-8);
  }
  function matchedRuleTexts(el, max = 6) {
    const out = [];
    for (const r of cssRules()) {
      if (r.sel.split(",").every((part) => UNIVERSAL.test(part))) continue;
      let ok = false;
      try { ok = el.matches(r.sel); } catch { ok = false; }
      if (ok) out.push((r.media ? `@media ${r.media} { ` : "") + r.rule.cssText.slice(0, 420) + (r.media ? " }" : ""));
    }
    return out.slice(-max);
  }
  function textOf(el) {
    const t = el.innerText || el.value || el.getAttribute("aria-label") || el.title || el.alt || "";
    return String(t).trim().replace(/\s+/g, " ").slice(0, 80);
  }
  function shortLabel(el) {
    const c = goodClasses(el).slice(0, 2).map((x) => "." + x).join("");
    return el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + c;
  }
  function describe(el, scope) {
    const r = el.getBoundingClientRect();
    return {
      selector: scope || (scopeOptions(el)[0] || {}).sel || cssPath(el),
      path: cssPath(el),
      label: shortLabel(el),
      text: textOf(el),
      rules: matchedRules(el),
      view: viewKey(),
      size: `${Math.round(r.width)}×${Math.round(r.height)}`,
    };
  }
  function resolve(target, cached) {
    if (cached && cached.isConnected) return cached;
    if (!target) return null;
    try {
      const el = document.querySelector(target.path);
      if (el && el !== ovHost) return el;
    } catch { /* 선택자가 이제 안 맞을 수 있다 */ }
    return null;
  }

  /* ---------- 바꾼 것 적용 ---------- */
  const overrideStyle = document.createElement("style");
  overrideStyle.id = "__studio-overrides";
  document.head.appendChild(overrideStyle);

  function applyAppTheme(key) {
    if (APP.applyTheme) { try { return APP.applyTheme(key); } catch { /* 아래 기본 */ } }
    // 기본: 선택자의 [data-이름="값"] 을 html 에 붙인다. 붙일 것이 없는 테마(":root")면 다른 테마들 것을 뗀다.
    const t = THEMES.find((x) => x.key === key);
    if (!t) return;
    const html = document.documentElement;
    for (const o of THEMES) for (const m of (o.selector || "").matchAll(/\[([\w-]+)="([^"]*)"\]/g)) html.removeAttribute(m[1]);
    for (const m of (t.selector || "").matchAll(/\[([\w-]+)="([^"]*)"\]/g)) html.setAttribute(m[1], m[2]);
  }
  function themeSelector(theme) {
    return (THEMES.find((t) => t.key === theme) || THEMES[0]).selector || ":root";
  }
  function compileCss(changes) {
    const tokens = new Map();
    const styles = new Map();
    for (const c of changes) {
      if (c.type === "token") {
        if (!tokens.has(c.theme)) tokens.set(c.theme, new Map());
        tokens.get(c.theme).set(c.name, c.to);
      } else if (c.type === "style") {
        if (!styles.has(c.selector)) styles.set(c.selector, new Map());
        const m = styles.get(c.selector);
        m.delete(c.prop); // 마지막에 바꾼 것이 뒤에 오게
        m.set(c.prop, c.to);
      }
    }
    const blocks = [];
    for (const [theme, m] of tokens) {
      blocks.push(`${themeSelector(theme)} {\n${[...m].map(([k, v]) => `  ${k}: ${v};`).join("\n")}\n}`);
    }
    for (const [sel, m] of styles) {
      blocks.push(`${sel} {\n${[...m].map(([k, v]) => `  ${k}: ${v};`).join("\n")}\n}`);
    }
    return blocks.join("\n\n");
  }
  function applyCss() {
    // 화면에서는 !important 로 덮어 보여 준다 (원래 규칙이 더 구체적이어도 이기게). 저장본 CSS 에는 붙이지 않는다.
    overrideStyle.textContent = compileCss(cur().changes).replace(/;\n/g, " !important;\n");
    scheduleDraw();
  }

  function applyDom(c) {
    const el = resolve(c.target, c._el);
    if (!el) return false;
    c._el = el;
    if (c.type === "text") {
      if (c._html == null) c._html = el.innerHTML;
      if (c._live) {
        c._live = false; // 방금 화면에서 고친 그대로라 다시 넣지 않는다
        return true;
      }
      // 아이콘(<span><svg>)이 든 단추는 innerText 를 통째로 바꾸면 아이콘이 사라진다. 글자 조각이 하나면 그것만 바꾼다.
      const texts = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if (walker.currentNode.data.trim()) texts.push(walker.currentNode);
      if (texts.length === 1) texts[0].data = c.to;
      else el.innerText = c.to;
    } else if (c.type === "move") {
      const ref = resolve(c.ref, c._ref);
      if (!ref || ref.parentElement !== el.parentElement) return false;
      c._ref = ref;
      if (!c._home) c._home = { parent: el.parentElement, next: el.nextSibling };
      ref.parentElement.insertBefore(el, c.where === "before" ? ref : ref.nextSibling);
    }
    return true;
  }
  function revertDom(c) {
    const el = c._el;
    if (!el || !el.isConnected) return;
    if (c.type === "text" && c._html != null) el.innerHTML = c._html;
    if (c.type === "move" && c._home && c._home.parent.isConnected) {
      const next = c._home.next && c._home.next.parentNode === c._home.parent ? c._home.next : null;
      c._home.parent.insertBefore(el, next);
    }
  }
  const isDom = (c) => c.type === "text" || c.type === "move";

  function commit(change, { coalesce = false } = {}) {
    const list = cur().changes;
    // 끌고 있는 동안(같은 편집 묶음)에 같은 자리를 바꾼 줄이 있으면 그 줄의 값만 고친다
    const same = coalesce && S.editKey && list.find((c) => c._k === S.editKey && c.type === change.type &&
      c.selector === change.selector && c.prop === change.prop && c.name === change.name && c.theme === change.theme);
    if (same) {
      same.to = change.to;
    } else {
      change.id = uid("c");
      change._k = S.editKey;
      change.createdAt = new Date().toISOString();
      list.push(change);
      S.undo.push({ op: "add", vid: cur().id, change, group: S.group });
      S.redo = [];
    }
    if (isDom(change)) applyDom(change);
    applyCss();
    saveDraftSoon();
    renderPanelSoon();
  }
  function removeChange(id) {
    const list = cur().changes;
    const i = list.findIndex((c) => c.id === id);
    if (i < 0) return;
    const [c] = list.splice(i, 1);
    if (isDom(c)) revertDom(c);
    S.undo.push({ op: "remove", vid: cur().id, change: c, index: i });
    S.redo = [];
    applyCss();
    saveDraftSoon();
    renderPanel();
  }
  function undoRedo(from, to) {
    const step = from.pop();
    if (!step) return toast(from === S.undo ? "되돌릴 것이 없어요" : "다시 할 것이 없어요");
    undoOne(step, from, to);
    while (step.group && from.length && from[from.length - 1].group === step.group) undoOne(from.pop(), from, to);
    S.editKey = null;
    applyCss();
    saveDraftSoon();
    renderPanel();
  }
  function undoOne(step, from, to) {
    const vi = S.variants.findIndex((v) => v.id === step.vid);
    if (vi < 0) return;
    if (vi !== S.active) switchVariant(vi);
    const list = cur().changes;
    const adding = (from === S.undo) === (step.op === "remove");
    if (adding) {
      list.splice(step.index ?? list.length, 0, step.change);
      if (isDom(step.change)) applyDom(step.change);
    } else {
      const i = list.indexOf(step.change);
      if (i >= 0) {
        step.index = i;
        list.splice(i, 1);
      }
      if (isDom(step.change)) revertDom(step.change);
    }
    to.push(step);
  }
  const undo = () => undoRedo(S.undo, S.redo);
  const redo = () => undoRedo(S.redo, S.undo);

  function switchVariant(i) {
    if (i === S.active || !S.variants[i]) return;
    [...cur().changes].reverse().filter(isDom).forEach(revertDom);
    S.active = i;
    cur().changes.filter(isDom).forEach(applyDom);
    S.editKey = null;
    applyCss();
    saveDraftSoon(false);
    render();
  }

  /* ---------- 값 바꾸기 ---------- */
  function setStyle(prop, value) {
    if (!S.sel) return;
    const el = S.sel.el;
    // 같은 곳을 두 번째 만질 때는 이미 덮어쓴 값이 보인다. '원래' 값은 처음 바꿀 때 것을 이어 쓴다.
    const prev = cur().changes.find((c) => c.type === "style" && c.selector === S.scope && c.prop === prop);
    commit(
      { type: "style", selector: S.scope, prop, from: prev ? prev.from : getComputedStyle(el).getPropertyValue(prop).trim(), to: value,
        target: describe(el, S.scope), count: countOf(S.scope) },
      { coalesce: true },
    );
  }
  function resetStyle(prop) {
    const list = cur().changes.filter((c) => c.type === "style" && c.selector === S.scope && c.prop === prop);
    list.forEach((c) => removeChange(c.id));
  }
  function setToken(name, value) {
    const theme = themeKey();
    const prev = cur().changes.find((c) => c.type === "token" && c.theme === theme && c.name === name);
    commit({ type: "token", theme, name, from: prev ? prev.from : rootVar(name), to: value }, { coalesce: true });
  }
  function setAccent(hex) {
    const theme = themeKey();
    const surface = toHex(rootVar(ACCENT.surface) || getComputedStyle(document.body).backgroundColor || "#ffffff");
    // 어두운 테마인지는 이름이 아니라 바탕 밝기로 본다 (앱마다 테마 이름이 다르다)
    const dark = APP.darkThemes ? APP.darkThemes.includes(theme) : hexToHsl(surface)[2] < 0.4;
    const [h, s, l] = hexToHsl(hex);
    // 세 줄을 한 묶음으로: 직접 고르기 창을 끄는 동안에는 같은 세 줄만 고치고, 되돌리기는 한 번에
    const base = S.editKey || uid("k");
    S.group = base;
    S.editKey = base;
    setToken(ACCENT.main, hex);
    if (rootVar(ACCENT.strong)) setToken(ACCENT.strong, hslToHex(h, s, dark ? l + 0.14 : l - 0.13));
    if (rootVar(ACCENT.soft)) setToken(ACCENT.soft, mix(hex, surface, dark ? 0.78 : 0.87));
    S.editKey = base;
    S.group = null;
  }

  /* ---------- 도구 화면 (Shadow DOM 두 장) ----------
     앱은 바깥 틀(/ 의 shell) 안의 iframe 에서 돈다. 패널을 옆에 붙이면 iframe 이 실제로 좁아져서,
     앱이 그 너비에 맞는 진짜 배치(미디어 쿼리 포함)로 그려진다. 예전처럼 body 에 여백만 주면
     1440px 배치가 1086px 에 욱여넣어져 실제 앱에서는 절대 안 나오는 화면을 보고 고치게 됐다.
       - 겹쳐 그리기(고른 상자·핀·옮기기 손잡이): 앱 문서 안 (좌표가 앱과 같다)
       - 막대·패널·댓글 창·저장 창: 바깥 틀 문서 안 (iframe 이 좁아져도 그대로)
     바깥 틀 없이 열리면(?clean=1 사진 찍기) 둘 다 앱 문서에 둔다. */
  const TOP = (() => {
    try {
      return window.parent !== window && window.parent.__STUDIO_SHELL__ ? window.parent : window;
    } catch {
      return window;
    }
  })();
  const IN_SHELL = TOP !== window;
  const ovHost = document.createElement("div");
  ovHost.id = "__studio-ov";
  const ovRoot = ovHost.attachShadow({ mode: "open" });
  const host = TOP.document.createElement("div");
  host.id = "__studio";
  const root = host.attachShadow({ mode: "open" });
  // 앱 좌표 → 바깥 틀 좌표 (패널을 왼쪽에 붙이면 iframe 이 오른쪽으로 밀린다)
  const toTop = (x, y) => {
    if (!IN_SHELL || !window.frameElement) return { x, y };
    const r = window.frameElement.getBoundingClientRect();
    return { x: x + r.left, y: y + r.top };
  };
  ovRoot.innerHTML = `
    <style>${STUDIO_CSS()}</style>
    <div class="ov" part="overlay">
      <div class="hover" hidden><span class="tag"></span></div>
      <div class="selbox" hidden>
        <span class="tag"></span>
        <button class="grip" title="끌어서 형제 사이 순서 바꾸기">⠿ 순서</button>
        <button class="scopechip" title="누르면 '같은 모양 모두' ↔ '이것만'"></button>
        <span class="resize" title="끌어서 크기 바꾸기 (글자는 글자 크기, 아이콘은 비율대로, 상자는 너비·높이 · Ctrl: 상자처럼)"></span>
      </div>
      <div class="dropline" hidden></div>
      <div class="drag-rect" hidden></div>
      <div class="pins"></div>
      <div class="busy" hidden><span class="spin2"></span><span class="busytext"></span></div>
    </div>`;
  root.innerHTML = `
    <style>${STUDIO_CSS()}</style>
    <div class="bar"></div>
    <aside class="panel"></aside>
    <div class="ai"></div>
    <div class="picker" hidden>
      <div class="ptitle"></div>
      <div class="sv"><i class="knob"></i></div>
      <div class="hue"><i class="knob"></i></div>
      <div class="prow"><span class="pfrom" title="처음 색 (누르면 되돌리기)" data-pick-from></span><span class="pv"></span>
        <input class="phex" maxlength="7" spellcheck="false"><button data-pick-eye title="화면 어디서든 색 따오기 (앱 밖도)">스포이트</button></div>
      <div class="prow end"><button data-pick-close>다 됐어요</button></div>
    </div>
    <div class="pop" hidden></div>
    <div class="modal" hidden></div>
    <div class="toast" hidden></div>`;
  const $ = (sel) => root.querySelector(sel);
  const $o = (sel) => ovRoot.querySelector(sel);
  const ov = { hover: $o(".hover"), sel: $o(".selbox"), drop: $o(".dropline"), rect: $o(".drag-rect"), pins: $o(".pins") };

  function render() {
    renderBar();
    renderPanel();
    renderAi();
    scheduleDraw();
  }

  function renderBar() {
    const bar = $(".bar");
    bar.hidden = S.clean;
    const mode = (k, label, key, icon) =>
      `<button class="mode ${S.mode === k ? "on" : ""}" data-mode="${k}" title="${label} (${key})"><b>${icon}</b>${label}<kbd>${key}</kbd></button>`;
    bar.innerHTML = `
      <div class="grp">
        ${mode("browse", "둘러보기", "V", "☞")}
        ${mode("select", "고르기", "S", "⬚")}
        ${mode("comment", "댓글", "C", "✎")}
      </div>
      <div class="grp">
        <button class="icon" data-act="undo" title="되돌리기 (Ctrl+Z)">↶</button>
        <button class="icon" data-act="redo" title="다시 하기 (Ctrl+Shift+Z)">↷</button>
        ${INFO.claude ? `<button class="icon ai-btn" data-ai="open" title="AI 추천">✨</button>` : ""}
      </div>
      <div class="grp variants" title="조합마다 따로 바꿔 보고 숫자 키(1~9)로 오가며 비교해요">
        ${S.variants.map((v, i) => `<button class="vpill ${i === S.active ? "on" : ""}" data-variant="${i}" title="${esc(v.name)} · 바꾼 것 ${v.changes.length}">${esc(v.name.replace(/^조합\s*/, "")) || i + 1}</button>`).join("")}
        <button class="icon" data-act="variant-dup" title="지금 조합을 복사해 새 조합 만들기">＋</button>
      </div>
      <div class="grp">
        <button class="save" data-act="save">${INFO.ctx ? "이 시안 더 고쳐 달라기" : "저장해서 Claude에게"}</button>
        <button class="icon" data-act="toggle-panel" title="패널 접기/펴기">${S.collapsed ? "◧" : "◨"}</button>
      </div>
      ${ctxPill()}
      <div class="hint">${esc(hintText())}</div>`;
    setBarHeight();
  }
  function ctxPill() {
    if (INFO.ctx) {
      return `<div class="grp ctx"><span class="ctxlabel">시안 보는 중</span>
        <button data-prop-act="original" data-name="${esc(INFO.ctx)}" title="진짜 화면으로">원래</button>
        <button class="on" disabled>시안</button></div>`;
    }
    const ready = S.proposals.filter((p) => p.status === "ready");
    const running = S.proposals.filter((p) => p.status === "running" || p.status === "queued");
    if (running.length) return `<div class="grp ctx"><button data-tab-go="proposals"><span class="spin"></span>Claude 가 시안을 만드는 중</button></div>`;
    if (ready.length) return `<div class="grp ctx"><button data-prop-act="view" data-name="${esc(ready[0].name)}">시안 ${ready.length}개 보기</button></div>`;
    return "";
  }
  // 좁은 창에서는 아래 막대가 두세 줄로 접힌다. 패널·AI 카드가 그 위에서 끝나게 실제 높이를 알려 준다
  // (420px 폭에서 막대가 패널 아래 53px 를 덮었다 — 검증 중 실측)
  function setBarHeight() {
    const bar = $(".bar");
    host.style.setProperty("--barh", `${(bar && !bar.hidden && bar.offsetHeight) || 0}px`);
  }
  function hintText() {
    if (INFO.ctx && S.mode === "browse") return "Claude 가 만든 시안이에요 · 마음에 안 드는 곳에 댓글을 달고 '더 고쳐 달라기', 좋으면 시안 탭에서 '이대로 반영'";
    if (S.mode === "select") return "누르면 골라져요 · 두 번 누르면 글자 고치기 · ↑ 바깥 상자 · Alt+누르기는 앱이 그대로 받아요";
    if (S.mode === "comment") return "누르면 그 자리에, 끌면 그 영역에 댓글 · Alt+누르기는 앱이 그대로 받아요";
    return `앱처럼 눌러서 화면을 옮겨 다녀요 · ${INFO.mode === "real" ? "내 데이터(읽기만)" : "연습용 가짜 데이터"} · 실제로는 아무것도 보내지 않아요`;
  }

  /* ----- 오른쪽 패널 ----- */
  let panelTimer = 0;
  function renderPanelSoon() {
    clearTimeout(panelTimer);
    panelTimer = setTimeout(() => {
      // 색 고르는 창을 끌고 있는 동안 패널을 다시 그리면 그 창이 닫힌다. 바뀐 개수만 고친다.
      const active = root.activeElement;
      if (active && active.matches("input, select, textarea")) return refreshCounts();
      renderPanel();
    }, 160);
  }
  function refreshCounts() {
    root.querySelectorAll("[data-count]").forEach((n) => {
      n.textContent = String(cur().changes.length);
    });
    renderBar();
  }
  function renderPanel() {
    const panel = $(".panel");
    panel.hidden = S.clean || S.collapsed;
    panel.classList.toggle("left", S.side === "left");
    const dock = IN_SHELL && !panel.hidden && TOP.innerWidth >= 1000;
    TOP.document.documentElement.classList.toggle("dock-right", dock && S.side === "right");
    TOP.document.documentElement.classList.toggle("dock-left", dock && S.side === "left");
    $(".bar").classList.toggle("dock-right", dock && S.side === "right");
    $(".bar").classList.toggle("dock-left", dock && S.side === "left");
    const tab = (k, label, n) => `<button class="tab ${S.tab === k ? "on" : ""}" data-tab="${k}">${label}${n != null ? ` <i>${n}</i>` : ""}</button>`;
    panel.innerHTML = `
      <header>
        <div class="brand">디자인 스튜디오 <small>${esc(INFO.app || "")} · ${INFO.mode === "real" ? "내 데이터 · 읽기만" : "연습용"}${INFO.version ? ` · v${esc(INFO.version)}` : ""}</small></div>
        <button class="icon" data-act="swap-side" title="패널을 반대쪽으로">⇄</button>
      </header>
      <nav>${tab("palette", "색·테마")}${tab("element", "요소")}${tab("comments", "댓글", S.comments.length)}${tab("changes", "바뀐 것", cur().changes.length)}${tab("proposals", "시안", S.proposals.filter((p) => !["applied", "discarded"].includes(p.status)).length || null)}</nav>
      <div class="body">${panelBody()}</div>`;
    if (S.tab === "changes") fillSaved();
  }
  function panelBody() {
    if (S.tab === "palette") return paletteHtml();
    if (S.tab === "element") return elementHtml();
    if (S.tab === "comments") return commentsHtml();
    if (S.tab === "proposals") return proposalsHtml();
    return changesHtml();
  }

  /* ----- 시안: 요청 → Claude 가 복사본에 고침 → 보고 → 반영 / 더 고쳐 줘 / 버리기 ----- */
  const PROP_STATUS = {
    queued: ["기다리는 중", "run"], running: ["만드는 중", "run"], ready: ["다 됨", "ok"], failed: ["실패", "bad"],
    cancelled: ["멈춤", "bad"], applied: ["반영함", "done"], discarded: ["버림", "done"],
  };
  function proposalsHtml() {
    const intro = INFO.claude
      ? `<p class="small">저장할 때 <b>저장하고 시안 만들기</b>를 누르면 Claude 가 진짜 화면 파일은 그대로 두고 복사본(시안)에만 고쳐요. 시안을 보고 반영할지 정하세요.</p>`
      : `<p class="small">이 컴퓨터에서 <code>claude</code> 명령을 못 찾아 시안을 자동으로 만들 수 없어요. Claude Code 를 설치하면 여기서 바로 시안을 받아 볼 수 있어요. 지금은 저장본을 Claude Code 에 직접 넘겨 주세요.</p>`;
    if (!S.proposals.length) return `<div class="empty">${intro}</div>`;
    return intro + S.proposals.map((p) => {
      const [label, tone] = PROP_STATUS[p.status] || [p.status, "run"];
      const rounds = p.rounds || [];
      const last = rounds[rounds.length - 1] || {};
      const viewing = INFO.ctx === p.name;
      const btn = (act, text, cls = "") => `<button class="${cls}" data-prop-act="${act}" data-name="${esc(p.name)}">${text}</button>`;
      let body = "";
      if (p.status === "running" || p.status === "queued") {
        body = `<div class="act">${(p.activity || []).slice(-8).map((a) => `<div>${esc(a)}</div>`).join("")}</div>
          <div class="pacts2">${btn("cancel", "멈추기")}</div>`;
      } else if (p.status === "ready") {
        body = `${last.result ? `<div class="res">${mdLite(last.result)}</div>` : ""}
          ${(p.changed || []).length ? `<div class="files">${p.changed.map((f) => `<span><code>${esc(f.file)}</code> <i class="plus">+${f.plus}</i> <i class="minus">−${f.minus}</i></span>`).join("")}</div>` : `<p class="small">바뀐 파일이 없어요.</p>`}
          <div class="pacts2">${viewing ? btn("original", "원래 보기") : btn("view", "시안 보기", "primary")}${btn("diff", "코드 보기")}</div>
          <div class="pacts2">${btn("apply", "이대로 반영", "good")}${btn("revise", "더 고쳐 줘")}${btn("discard", "버리기", "danger")}</div>`;
      } else if (p.status === "failed" || p.status === "cancelled") {
        body = `<p class="err">${esc(p.error || "")}</p>${last.result ? `<div class="res">${mdLite(last.result)}</div>` : ""}
          <div class="act">${(p.activity || []).slice(-4).map((a) => `<div>${esc(a)}</div>`).join("")}</div>
          <div class="pacts2">${(p.changed || []).length ? btn("view", "지금까지 된 것 보기") : ""}${btn("revise", "다시 시키기")}${btn("discard", "버리기", "danger")}</div>`;
      } else if (p.status === "applied") {
        const r = p.applyReport || {};
        body = `<p class="small">진짜 화면 파일에 반영했어요: ${esc([...(r.applied || []), ...(r.merged || [])].join(", ") || "-")}</p>
          <p class="small">설치된 앱에 넣으려면 설치 파일을 다시 만들어야 해요 (Claude Code 에 "설치 파일 만들어 줘").</p>`;
      }
      const conflicts = (p.applyReport || {}).conflicts || [];
      if (p.status === "ready" && conflicts.length) {
        body = `<p class="err">반영하려 했지만 이 파일들은 시안을 만든 뒤 진짜 화면에서도 같은 곳이 바뀌어 합치지 못했어요: ${esc(conflicts.join(", "))}. 반만 바뀌지 않게 아무 파일도 바꾸지 않았어요. Claude Code 에 "시안 ${esc(p.name)} 충돌 정리해 줘" 라고 해 주세요.</p>` + body;
      }
      return `<div class="prop ${viewing ? "viewing" : ""}">
        <div class="phead2"><b>${esc(p.title || p.name)}</b><span class="st st-${tone}">${label}</span></div>
        <div class="meta">${rounds.length}회차 · ${esc(String(p.updatedAt || "").slice(5, 16).replace("T", " "))}${p.cost ? ` · 약 $${(+p.cost).toFixed(2)}` : ""}${viewing ? " · <b>지금 보는 중</b>" : ""}</div>
        ${body}</div>`;
    }).join("");
  }
  // Claude 설명의 **굵게**·`코드` 만 살린다 (글자는 먼저 이스케이프해서 HTML 이 끼어들 수 없다)
  const mdLite = (text) => esc(text)
    .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
  function setCtx(name, hint = "") {
    // 화면 폴더는 쿠키로 고른다 (studio_server._context). 앱만 다시 불러오면 바깥 틀·패널은 그대로 다시 붙는다.
    document.cookie = name ? `studio_web=${encodeURIComponent(name)}; path=/; SameSite=Lax` : "studio_web=; path=/; max-age=0; SameSite=Lax";
    try { if (hint) sessionStorage.setItem("studio-hint", hint); } catch { /* 안내만 못 보인다 */ }
    location.reload();
  }
  let propSig = "";
  async function refreshProposals() {
    let res;
    try {
      res = await fetch("/__studio/proposals").then((r) => r.json());
    } catch {
      return;
    }
    const before = new Map(S.proposals.map((p) => [p.name, p.status]));
    S.proposals = res.items || [];
    for (const p of S.proposals) {
      if (before.get(p.name) === "running" && p.status === "ready") toast(`시안이 다 됐어요: ${p.title || p.name} — 시안 탭에서 보세요`);
      if (before.get(p.name) === "running" && p.status === "failed") toast(`시안 만들기가 실패했어요: ${p.title || p.name}`);
    }
    const sig = JSON.stringify(S.proposals.map((p) => [p.name, p.status, (p.activity || []).length, (p.rounds || []).length]));
    if (sig === propSig) return;
    propSig = sig;
    renderBar();
    const typing = root.activeElement && root.activeElement.matches("input, select, textarea");
    if (!typing) renderPanel();
    else refreshCounts();
  }
  async function proposalAction(act, name) {
    const post = (path, body) => fetch(`/__studio/proposal/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => r.json());
    const p = S.proposals.find((x) => x.name === name) || { name };
    if (act === "view") return setCtx(name);
    if (act === "original") return setCtx("");
    if (act === "diff") {
      const res = await fetch(`/__studio/proposal-diff?name=${encodeURIComponent(name)}`).then((r) => r.json());
      const m = $(".modal");
      m.innerHTML = `<div class="card wide"><h3>바뀐 코드 — ${esc(p.title || name)}</h3>
        <pre class="diff">${(res.diff || "(바뀐 것 없음)").split("\n").map((l) => `<span class="${l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : l.startsWith("@@") ? "h" : ""}">${esc(l)}</span>`).join("\n")}</pre>
        <div class="macts"><button data-modal="close">닫기</button></div></div>`;
      m.hidden = false;
      return;
    }
    if (act === "cancel") {
      await post("cancel", { name });
      return refreshProposals();
    }
    if (act === "discard") {
      if (!confirm("이 시안을 버릴까요? 진짜 화면 파일은 그대로예요. (시안 폴더는 proposals/_discarded 로 옮겨 둬요)")) return;
      await post("discard", { name });
      if (INFO.ctx === name) return setCtx("");
      return refreshProposals();
    }
    if (act === "apply") {
      if (!confirm("이 시안을 진짜 화면 파일에 반영할까요?\n반영 전 파일은 시안 폴더의 before-apply/ 에 남겨 둬요.")) return;
      const res = await post("apply", { name });
      if (!res.ok) return toast(res.message || "반영하지 못했어요");
      const r = res.report;
      const n = r.applied.length + r.merged.length;
      if (r.conflicts.length) toast(`${r.conflicts.length}개 파일이 겹쳐서 아무것도 반영하지 않았어요 (시안 탭 참고)`);
      else return setCtx("", `반영했어요 (${n}개 파일). 지금 보이는 것이 진짜 화면이에요.`);
      return refreshProposals();
    }
    if (act === "revise") {
      if (INFO.ctx !== name) {
        return setCtx(name, "시안 위에서 고칠 곳에 댓글을 달거나 직접 바꾼 뒤 '이 시안 더 고쳐 달라기' 를 누르세요.");
      }
      if (!S.comments.length && !cur().changes.length) {
        return toast("시안 위에 댓글을 달거나 직접 바꾼 뒤 '이 시안 더 고쳐 달라기' 를 누르세요");
      }
      return openSaveModal();
    }
  }

  function paletteHtml() {
    const theme = themeKey();
    const changed = new Map(cur().changes.filter((c) => c.type === "token" && c.theme === theme).map((c) => [c.name, c]));
    const row = ([name, label]) => {
      const v = rootVar(name);
      return `<label class="tok ${changed.has(name) ? "changed" : ""}">
        <button class="swatch" data-pick="token" data-key="${name}" style="--c:${esc(v)}" title="그라데이션 판에서 고르기"></button>
        <span class="tname">${label}<code>${name}</code></span>
        <span class="tval">${esc(v)}</span>
        ${changed.has(name) ? `<button class="mini" data-token-reset="${name}" title="원래대로">↺</button>` : ""}
      </label>`;
    };
    return `
      <section ${THEMES.length > 1 ? "" : "hidden"}>
        <h4>테마 <small>지금 보는 테마에 따로 적혀요</small></h4>
        <div class="seg">${THEMES.map((t) => `<button data-theme-set="${t.key}" class="${theme === t.key ? "on" : ""}">${t.label}</button>`).join("")}</div>
      </section>
      <section>
        <h4>${rootVar(ACCENT.main) ? "강조색 한 번에 <small>진한·옅은 강조도 함께 맞춰요</small>" : "스포이트"}</h4>
        <div class="accentrow" ${rootVar(ACCENT.main) ? "" : "hidden"}><button class="swatch big" data-pick="accent" data-key="${esc(ACCENT.main)}" style="--c:${esc(rootVar(ACCENT.main))}" title="그라데이션 판에서 고르기"></button>
          <span class="small">눌러서 판에서 고르거나, 판의 스포이트로 화면 어디서든 색을 따와요</span></div>
        <button data-eyecopy>스포이트로 색 따서 복사</button>
      </section>
      ${tokenGroups().map(([g, rows]) => `<section><h4>${g}</h4>${rows.map(row).join("")}</section>`).join("")}
      <section ${sizeTokens().length ? "" : "hidden"}>
        <h4>모양</h4>
        ${sizeTokens().map(([name, label, min, max]) => {
          const v = px(rootVar(name));
          return `<div class="ctl"><span>${label} <code>${name}</code></span>
            <input type="range" min="${min}" max="${max}" value="${v}" data-token-px="${name}"><output>${v}px</output>
            ${changed.has(name) ? `<button class="mini" data-token-reset="${name}">↺</button>` : ""}</div>`;
        }).join("")}
      </section>`;
  }

  function elementHtml() {
    if (!S.sel || !S.sel.el.isConnected) {
      return `<div class="empty">
        <p><b>고르기(S)</b>로 바꾸고 싶은 곳을 누르세요.</p>
        <p>글자 색·크기, 배경, 모서리, 간격, 크기를 바로 바꿔 볼 수 있어요. 고른 상자 왼쪽 위 <b>⠿ 옮기기</b>를 끌면 순서가 바뀌고, 오른쪽 아래 모서리를 끌면 크기가 바뀌어요.</p>
        <button class="primary" data-mode="select">고르기 시작</button></div>`;
    }
    const el = S.sel.el;
    const cs = getComputedStyle(el);
    const opts = scopeOptions(el);
    if (!opts.some((o) => o.sel === S.scope)) S.scope = (opts[0] || {}).sel;
    const crumbs = [];
    for (let n = el, i = 0; n && n !== document.body && i < 6; n = n.parentElement, i++) crumbs.unshift(n);
    const mine = cur().changes.filter((c) => c.type === "style" && c.selector === S.scope);
    const has = (p) => mine.some((c) => c.prop === p);
    const reset = (p) => (has(p) ? `<button class="mini" data-style-reset="${p}" title="원래대로">↺</button>` : "");
    const color = (prop, label) => `
      <div class="ctl color ${has(prop) ? "changed" : ""}"><span>${label}${isClear(cs.getPropertyValue(prop)) ? "<code>투명</code>" : ""}</span>
        <button class="swatch ${isClear(cs.getPropertyValue(prop)) ? "clear" : ""}" data-pick="style" data-key="${prop}" style="--c:${esc(cs.getPropertyValue(prop))}" title="그라데이션 판에서 고르기"></button>
        <code class="hexv">${esc(isClear(cs.getPropertyValue(prop)) ? "투명" : toHex(cs.getPropertyValue(prop)))}</code>
        ${reset(prop)}</div>`;
    const range = (prop, label, min, max, step = 1, unit = "px") => {
      const raw = cs.getPropertyValue(prop);
      const v = unit === "px" ? px(raw) : +parseFloat(raw || "1").toFixed(2);
      return `<div class="ctl ${has(prop) ? "changed" : ""}"><span>${label}</span>
        <input type="range" min="${min}" max="${max}" step="${step}" value="${v}" data-style-range="${prop}" data-unit="${unit}"><output>${v}${unit}</output>${reset(prop)}</div>`;
    };
    const select = (prop, label, items) => {
      const v = cs.getPropertyValue(prop).trim();
      return `<div class="ctl ${has(prop) ? "changed" : ""}"><span>${label}</span>
        <select data-style-select="${prop}">${items.map(([l, val]) => `<option value="${esc(val)}" ${val === v ? "selected" : ""}>${l}</option>`).join("")}</select>${reset(prop)}</div>`;
    };
    const isFlex = /flex|grid/.test(cs.display);
    const n = mine.length;
    return `
      <div class="crumbs">${crumbs.map((c, i) => `<button data-crumb="${crumbs.length - 1 - i}" class="${c === el ? "on" : ""}">${esc(shortLabel(c))}</button>`).join("<i>›</i>")}</div>
      <div class="selinfo"><b>${esc(shortLabel(el))}</b> <span>${Math.round(el.getBoundingClientRect().width)}×${Math.round(el.getBoundingClientRect().height)}</span>
        ${textOf(el) ? `<div class="txt">“${esc(textOf(el).slice(0, 60))}”</div>` : ""}</div>
      <section>
        <h4>어디까지 바꿀까요</h4>
        <select class="wide" data-scope>${opts.map((o) => `<option value="${esc(o.sel)}" ${o.sel === S.scope ? "selected" : ""}>${esc(o.label)} · ${o.n}개 — ${esc(o.sel.length > 46 ? o.sel.slice(0, 46) + "…" : o.sel)}</option>`).join("")}</select>
        <details class="rules"><summary>CSS 에서 걸린 규칙 ${matchedRules(el).length}개</summary><code>${matchedRules(el).map(esc).join("<br>")}</code></details>
      </section>
      <section><h4>글자</h4>
        ${color("color", "색")}
        ${range("font-size", "크기", 8, 48)}
        ${select("font-weight", "굵기", [["보통 400", "400"], ["중간 500", "500"], ["약간 굵게 600", "600"], ["굵게 700", "700"], ["아주 굵게 800", "800"]])}
        ${select("text-align", "정렬", [["왼쪽", "left"], ["가운데", "center"], ["오른쪽", "right"], ["처음(기본)", "start"]])}
        ${range("letter-spacing", "자간", -2, 4, 0.1)}
        ${range("line-height", "줄 간격", 10, 40)}
      </section>
      <section><h4>상자</h4>
        ${color("background-color", "배경")}
        ${color("border-color", "테두리 색")}
        ${range("border-width", "테두리 굵기", 0, 6)}
        ${range("border-radius", "모서리", 0, 40)}
        ${select("box-shadow", "그림자", SHADOWS.map(([l, v]) => [l, v]))}
        ${range("opacity", "불투명도", 0, 1, 0.05, "")}
      </section>
      <section><h4>간격·크기</h4>
        ${range("padding-block", "안쪽 위아래", 0, 48)}
        ${range("padding-inline", "안쪽 좌우", 0, 48)}
        ${range("margin-block", "바깥 위아래", 0, 48)}
        ${isFlex ? range("gap", "칸 사이", 0, 48) : ""}
        <div class="ctl size"><span>너비·높이</span>
          <input type="number" data-size="width" placeholder="자동" value="${has("width") ? px(cs.width) : ""}">×
          <input type="number" data-size="height" placeholder="자동" value="${has("height") ? px(cs.height) : ""}">px
          ${reset("width")}${has("height") ? `<button class="mini" data-style-reset="height">↺</button>` : ""}</div>
      </section>
      ${flowHtml(el)}
      <section class="acts">
        <button data-act="move-prev">↑ 앞으로</button>
        <button data-act="move-next">↓ 뒤로</button>
        <button data-act="hide">${has("display") ? "다시 보이기" : "숨기기"}</button>
        <button data-act="edit-text">글자 고치기</button>
        <button data-act="comment-here">여기에 댓글</button>
      </section>
      ${n ? `<p class="small">이 범위에 바꾼 것 ${n}개 · 같은 모양 ${countOf(S.scope)}곳에 함께 보여요</p>` : ""}`;
  }

  function commentsHtml() {
    if (!S.comments.length) {
      return `<div class="empty"><p><b>댓글(C)</b>을 켜고 화면을 누르면 그 자리에, 끌면 그 영역에 댓글을 달아요.</p>
        <p>"여기 너무 빽빽해", "이 버튼은 위로" 처럼 말로 적어도 Claude 가 어느 요소인지 정확히 알아요.</p>
        <button class="primary" data-mode="comment">댓글 달기 시작</button></div>`;
    }
    return S.comments.map((c) => `
      <div class="cmt ${c.done ? "done" : ""}">
        <div class="chead"><span class="num">${c.n}</span><span class="kind k-${c.kind}">${esc(kindLabel(c.kind))}</span>
          <span class="where">${esc(viewLabel(c.anchor.view))} · ${esc(c.anchor.label)}${c.region ? " · 영역" : ""}</span></div>
        <div class="ctext">${esc(c.text)}</div>
        <div class="cacts"><button data-cmt-go="${c.id}">보기</button><button data-cmt-edit="${c.id}">고치기</button><button data-cmt-del="${c.id}">지우기</button></div>
      </div>`).join("");
  }
  const kindLabel = (k) => (KINDS.find((x) => x[0] === k) || KINDS[0])[1];

  function changesHtml() {
    const v = cur();
    const line = (c) => {
      let what = "";
      if (c.type === "token") what = `<b>${esc(c.name)}</b> <small>${esc(themeLabel(c.theme))} 테마</small>`;
      if (c.type === "style") what = `<b>${esc(c.prop === "translate" ? "위치 옮김" : c.prop)}</b> <small>${esc(c.selector)} · ${c.count || "?"}곳${c.by === "ai" ? " · AI 추천" : ""}</small>`;
      if (c.type === "flow") what = `<b>동작 흐름</b> <small>${esc(c.target.label)} · ${c.steps.length}단계</small>`;
      if (c.type === "text") what = `<b>글자</b> <small>${esc(c.target.label)}</small>`;
      if (c.type === "move") what = `<b>순서</b> <small>${esc(c.target.label)} → ${esc(c.ref.label)} ${c.where === "before" ? "앞" : "뒤"}</small>`;
      const val = c.type === "move" || c.type === "flow" ? "" : `<span class="from">${esc(String(c.from).slice(0, 40))}</span> → <span class="to">${esc(String(c.to).slice(0, 40))}</span>`;
      const sw = /^#|^rgb|^var\(/.test(c.to) && c.type !== "text" ? `<i class="dot" style="--c:${esc(resolveColor(c.to))}"></i>` : "";
      return `<div class="chg">${sw}<div><div>${what}</div><div class="vals">${val}</div></div><button class="mini" data-chg-del="${c.id}" title="이것만 빼기">✕</button></div>`;
    };
    return `
      <section>
        <h4>조합 <small>조합마다 따로 바꿔 보고 아래 단추·숫자 키로 비교해요</small></h4>
        <div class="vrow"><input class="wide" data-variant-name value="${esc(v.name)}">
          <button data-act="variant-dup" title="복사해서 새 조합">복사</button>
          <button data-act="variant-new" title="아무것도 안 바꾼 새 조합">새로</button>
          ${S.variants.length > 1 ? `<button data-act="variant-del" title="이 조합 지우기">지우기</button>` : ""}</div>
      </section>
      <section><h4>바뀐 것 <i data-count>${v.changes.length}</i></h4>
        ${v.changes.length ? v.changes.map(line).join("") : `<p class="small">아직 없어요. 색·테마 탭이나 고르기로 바꿔 보세요.</p>`}
        ${v.changes.length ? `<button class="danger" data-act="variant-clear">이 조합 모두 비우기</button>` : ""}
      </section>
      <section><h4>저장본 불러오기</h4><div class="saved" data-saved>불러오는 중…</div></section>`;
  }
  async function fillSaved() {
    const box = root.querySelector("[data-saved]");
    if (!box) return;
    try {
      const res = await fetch("/__studio/requests").then((r) => r.json());
      box.innerHTML = res.items.length
        ? res.items.slice(0, 12).map((it) => `<button class="srow" data-load="${esc(it.name)}">
            <b>${esc(it.title || it.name)}</b><small>${esc(it.name.slice(0, 15))} · 댓글 ${it.comments} · 바꾼 것 ${it.changes}${it.applied ? " · 반영됨" : ""}</small></button>`).join("")
        : `<p class="small">아직 저장한 것이 없어요.</p>`;
    } catch {
      box.textContent = "목록을 못 불러왔어요.";
    }
  }

  /* ---------- 겹쳐 그리기 (골라진 상자·댓글 핀) ---------- */
  let drawQueued = false;
  function scheduleDraw() {
    if (drawQueued) return;
    drawQueued = true;
    requestAnimationFrame(() => {
      drawQueued = false;
      draw();
    });
  }
  function place(node, r) {
    node.style.transform = `translate(${r.left}px, ${r.top}px)`;
    node.style.width = `${r.width}px`;
    node.style.height = `${r.height}px`;
  }
  function draw() {
    const showHover = S.mode !== "browse" && S.hover && S.hover.isConnected && !S.dragging && S.hover !== (S.sel && S.sel.el);
    ov.hover.hidden = !showHover;
    if (showHover) {
      const r = S.hover.getBoundingClientRect();
      place(ov.hover, r);
      ov.hover.querySelector(".tag").textContent = `${shortLabel(S.hover)}  ${Math.round(r.width)}×${Math.round(r.height)}`;
    }
    if (S.sel && !S.sel.el.isConnected) {
      // 앱이 그 부분을 다시 그렸다. 같은 자리의 새 요소를 다시 잡는다.
      const again = resolve({ path: S.sel.path });
      if (again) S.sel.el = again;
    }
    const showSel = S.mode === "select" && S.sel && S.sel.el.isConnected && !S.clean && !S.demoing;
    ov.sel.hidden = !showSel;
    if (showSel) {
      const r = S.sel.el.getBoundingClientRect();
      place(ov.sel, r);
      ov.sel.querySelector(".tag").textContent = S.drag && S.drag.moved
        ? `${S.drag.label}`
        : `${shortLabel(S.sel.el)}  ${Math.round(r.width)}×${Math.round(r.height)}`;
      // 화면 끝까지 닿는 요소는 모서리 손잡이가 화면 밖(패널 밑)으로 나간다. 보이는 안쪽으로 당겨 둔다.
      const handle = ov.sel.querySelector(".resize");
      handle.style.right = `${Math.max(-7, r.right - innerWidth + 10)}px`;
      handle.style.bottom = `${Math.max(-7, r.bottom - innerHeight + 10)}px`;
      const only = S.scope === cssPath(S.sel.el);
      ov.sel.querySelector(".scopechip").textContent = only ? "이것만" : `같은 모양 ${countOf(S.scope)}곳 함께`;
    }
    const view = viewKey();
    if (view !== S.lastView) {
      S.lastView = view;
      aiAutoSoon("view");
    }
    drawPins();
  }
  function drawPins() {
    const view = viewKey();
    const html = [];
    if (!S.clean || PARAMS.get("pins") === "1") {
      for (const c of S.comments) {
        const el = resolve(c.anchor, c._el);
        c._el = el;
        if (!el || c.anchor.view !== view) continue;
        const r = el.getBoundingClientRect();
        if (!r.width && !r.height) continue;
        if (c.region) {
          const x = r.left + c.region.x * r.width, y = r.top + c.region.y * r.height;
          html.push(`<div class="region ${c.done ? "done" : ""}" style="transform:translate(${x}px,${y}px);width:${c.region.w * r.width}px;height:${c.region.h * r.height}px"></div>`);
          html.push(`<button class="pin ${c.done ? "done" : ""}" data-pin="${c.id}" style="transform:translate(${x - 11}px,${y - 11}px)">${c.n}</button>`);
        } else {
          const x = r.left + c.at.x * r.width, y = r.top + c.at.y * r.height;
          html.push(`<button class="pin ${c.done ? "done" : ""}" data-pin="${c.id}" style="transform:translate(${x - 11}px,${y - 22}px)">${c.n}</button>`);
        }
      }
    }
    const next = html.join("");
    if (ov.pins.innerHTML !== next) ov.pins.innerHTML = next;
  }
  window.addEventListener("scroll", scheduleDraw, true);
  window.addEventListener("resize", () => {
    renderPanel();
    scheduleDraw();
  });
  setInterval(scheduleDraw, 400); // 앱이 화면을 다시 그리거나 화면을 옮긴 것을 따라간다

  /* ---------- 고르기·댓글: 앱 대신 누르기를 받는다 ---------- */
  const fromStudio = (e) => {
    const path = e.composedPath();
    return path.includes(host) || path.includes(ovHost);
  };
  function appTarget(e) {
    let t = e.target;
    if (!(t instanceof Element) || t === document.documentElement) return null;
    if (t.closest("svg") && t.closest("svg").parentElement) t = t.closest("svg").parentElement; // 아이콘 안쪽 선 대신 아이콘 통째로
    return t;
  }
  let pressStart = null;
  function onPointerEvent(e) {
    if (S.pickInApp && !fromStudio(e)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (e.type === "click" && e.target instanceof Element) {
        const done = S.pickInApp;
        S.pickInApp = null;
        done(colorAt(e.target));
      }
      return;
    }
    if (S.demoing || fromStudio(e) || e.altKey) return;
    if (S.mode === "browse") {
      // 동작 흐름을 바꿔 둔 단추는 둘러보기에서 누르면 바꾼 흐름대로 시연한다 (앱의 원래 동작 대신)
      if (e.type === "click") {
        const f = flowFor(e.target);
        if (f) {
          e.preventDefault();
          e.stopImmediatePropagation();
          playFlow(f.steps);
        }
      }
      return;
    }
    if (S.editing && S.editing.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    if (S.editing) finishTextEdit(true);
    const t = appTarget(e);
    if (!t) return;
    if (S.mode === "select") {
      // 고른 요소를 누른 채 끌면 그 자리에서 자유롭게 옮긴다 (CSS translate → 저장본에서는 '이만큼 옮기고 싶다')
      if (e.type === "pointerdown" && S.sel && S.sel.el.contains(t)) {
        const [bx, by] = parseTranslate(S.sel.el);
        S.drag = { x: e.clientX, y: e.clientY, bx, by, moved: false, key: uid("k"), label: "" };
      }
      if (e.type === "pointerup" && S.drag) {
        S.justDragged = S.drag.moved;
        S.drag = null;
        if (S.justDragged) renderPanel();
        scheduleDraw();
      }
      if (e.type === "click") {
        if (S.justDragged) {
          S.justDragged = false;
          return;
        }
        selectEl(t);
      }
      if (e.type === "dblclick") startTextEdit(t);
    } else if (S.mode === "comment") {
      if (e.type === "pointerdown") pressStart = { x: e.clientX, y: e.clientY, t };
      if (e.type === "pointerup" && pressStart) {
        const dx = e.clientX - pressStart.x, dy = e.clientY - pressStart.y;
        const start = pressStart;
        pressStart = null;
        ov.rect.hidden = true;
        if (Math.hypot(dx, dy) > 8) startRegionComment(start, e);
        else startPointComment(start.t, e.clientX, e.clientY);
      }
    }
  }
  ["pointerdown", "pointerup", "mousedown", "mouseup", "click", "dblclick", "contextmenu", "auxclick", "submit"].forEach((t) =>
    window.addEventListener(t, onPointerEvent, true));
  window.addEventListener("pointermove", (e) => {
    if (S.mode === "browse" || fromStudio(e) || S.demoing) return;
    if (S.drag && S.sel) {
      let dx = e.clientX - S.drag.x, dy = e.clientY - S.drag.y;
      if (!S.drag.moved && Math.hypot(dx, dy) < 4) return;
      if (e.shiftKey) (Math.abs(dx) > Math.abs(dy) ? (dy = 0) : (dx = 0)); // Shift: 가로나 세로로만
      if (!S.drag.moved) ensureMovable(S.sel.el);
      S.drag.moved = true;
      S.editKey = S.drag.key;
      const tx = Math.round(S.drag.bx + dx), ty = Math.round(S.drag.by + dy);
      S.drag.label = `→ ${tx}, ${ty}px`;
      setStyle("translate", `${tx}px ${ty}px`);
      return;
    }
    if (pressStart && S.mode === "comment") {
      const x = Math.min(pressStart.x, e.clientX), y = Math.min(pressStart.y, e.clientY);
      const w = Math.abs(e.clientX - pressStart.x), h = Math.abs(e.clientY - pressStart.y);
      if (w + h > 8) {
        ov.rect.hidden = false;
        place(ov.rect, { left: x, top: y, width: w, height: h });
      }
    }
    const t = appTarget(e);
    if (t !== S.hover) {
      S.hover = t;
      scheduleDraw();
    }
  }, true);

  // 글자 조각(<span> 같은 인라인 요소)은 CSS 이동(translate)이 먹지 않는다. 옮길 때 inline-block 으로 함께 바꾼다.
  function ensureMovable(el) {
    if (getComputedStyle(el).display !== "inline") return;
    S.editKey = null;
    setStyle("display", "inline-block");
  }
  function parseTranslate(el) {
    const t = getComputedStyle(el).translate;
    if (!t || t === "none") return [0, 0];
    const [x, y] = t.split(" ").map((v) => parseFloat(v) || 0);
    return [x || 0, y || 0];
  }
  function selectEl(el) {
    S.sel = { el, path: cssPath(el) };
    S.scope = (scopeOptions(el)[0] || {}).sel;
    S.flow = null;
    aiAutoSoon("select");
    S.tab = "element";
    S.editKey = null;
    S.collapsed = false;
    render();
  }
  function setMode(m) {
    if (S.editing) finishTextEdit(true);
    S.mode = m;
    S.hover = null;
    document.documentElement.classList.toggle("__studio-picking", m !== "browse");
    if (m === "comment" && S.tab !== "comments") S.tab = "comments";
    render();
  }

  /* ----- 글자 고치기 ----- */
  function startTextEdit(el) {
    if (!el || el === document.body) return;
    if (!S.sel || S.sel.el !== el) selectEl(el);
    S.editing = el;
    el._studioBefore = { text: el.innerText, html: el.innerHTML, target: describe(el, cssPath(el)) };
    el.contentEditable = "true";
    el.classList.add("__studio-editing");
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const s = getSelection();
    s.removeAllRanges();
    s.addRange(range);
    toast("글자를 고치고 Enter(줄바꿈은 Shift+Enter), 그만두려면 Esc");
  }
  function finishTextEdit(keep) {
    const el = S.editing;
    if (!el) return;
    S.editing = null;
    el.contentEditable = "false";
    el.removeAttribute("contenteditable");
    el.classList.remove("__studio-editing");
    const before = el._studioBefore;
    delete el._studioBefore;
    if (!keep) {
      el.innerHTML = before.html;
      return;
    }
    const after = el.innerText;
    if (after.trim() === before.text.trim()) return;
    S.editKey = null;
    commit({ type: "text", target: before.target, from: before.text, to: after, _el: el, _html: before.html, _live: true });
  }

  /* ----- 옮기기 (⠿ 끌기) ----- */
  function siblingsOf(el) {
    return [...el.parentElement.children].filter((x) => x !== el && !x.hidden && x.getClientRects().length);
  }
  function rowAxis(parent) {
    const cs = getComputedStyle(parent);
    if (cs.display.includes("flex")) return cs.flexDirection.startsWith("row");
    return cs.display.includes("grid") && cs.gridTemplateColumns.split(" ").length > 1;
  }
  function moveTo(el, ref, where) {
    const from = [...el.parentElement.children].indexOf(el);
    const c = { type: "move", target: describe(el, cssPath(el)), ref: describe(ref, cssPath(ref)), where,
      parent: describe(el.parentElement, cssPath(el.parentElement)), fromIndex: from, _el: el, _ref: ref };
    S.editKey = null;
    commit(c);
    c.toIndex = [...el.parentElement.children].indexOf(el);
    // 저장본의 target.path 는 '옮기기 전' 자리 그대로 둔다(다시 열 때 그 자리에서 찾아 옮긴다). 고른 표시만 새 자리로.
    S.sel.path = cssPath(el);
    saveDraftSoon();
  }
  function nudge(dir) {
    if (!S.sel) return;
    const el = S.sel.el;
    const sib = dir < 0 ? el.previousElementSibling : el.nextElementSibling;
    if (!sib) return toast(dir < 0 ? "맨 앞이에요" : "맨 뒤예요");
    moveTo(el, sib, dir < 0 ? "before" : "after");
  }
  $o(".grip").addEventListener("pointerdown", (e) => {
    if (!S.sel) return;
    e.preventDefault();
    const el = S.sel.el;
    const parent = el.parentElement;
    const row = rowAxis(parent);
    const sibs = siblingsOf(el);
    if (!sibs.length) return toast("함께 옮길 형제 요소가 없어요. 바깥 상자(↑)를 골라 보세요.");
    S.dragging = true;
    el.classList.add("__studio-dragging");
    const grip = e.currentTarget;
    grip.setPointerCapture(e.pointerId);
    let drop = null;
    const move = (ev) => {
      let best = null;
      for (const s of sibs) {
        const r = s.getBoundingClientRect();
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const d = Math.hypot(ev.clientX - cx, ev.clientY - cy);
        if (!best || d < best.d) best = { s, r, d, after: row ? ev.clientX > cx : ev.clientY > cy };
      }
      drop = best;
      const r = best.r;
      ov.drop.hidden = false;
      if (row) place(ov.drop, { left: (best.after ? r.right : r.left) - 2, top: r.top, width: 4, height: r.height });
      else place(ov.drop, { left: r.left, top: (best.after ? r.bottom : r.top) - 2, width: r.width, height: 4 });
    };
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      ov.drop.hidden = true;
      S.dragging = false;
      el.classList.remove("__studio-dragging");
      if (drop) moveTo(el, drop.s, drop.after ? "after" : "before");
      scheduleDraw();
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  });

  /* ----- 크기 (모서리 끌기) -----
     글자는 글자 크기를, 아이콘·그림은 비율 그대로 크기를, 상자는 너비·높이를 바꾼다. Ctrl 을 누르면 무엇이든 상자처럼. */
  function sizeKind(el) {
    if (el.matches("svg, img, .icon, [data-icon]") || (el.children.length === 1 && el.firstElementChild.matches("svg, img") && !textOf(el))) return "icon";
    // 아이콘·그림 자식은 빼고 본다 ('로고 + 날짜' 같은 제목 줄은 글자로 다뤄야 한다)
    const blockKid = [...el.children].some((c) => !c.matches("svg, img, .icon, [data-icon]") &&
      ["block", "flex", "grid", "table", "list-item"].includes(getComputedStyle(c).display));
    // 플렉스 줄 안의 자식은 모두 block 으로 계산된다. '아이콘 + 글자 하나' 처럼 글자 자식이 하나뿐이면 글자로 본다.
    const kids = [...el.children].filter((c) => !c.matches("svg, img, .icon, [data-icon], br"));
    const oneText = kids.length <= 1 && kids.every((c) => [...c.children].every((g) => g.matches("svg, img, .icon, br, b, i, em, strong, span")));
    if (textOf(el) && (!blockKid || oneText)) return "text";
    return "box";
  }
  $o(".resize").addEventListener("pointerdown", (e) => {
    if (!S.sel) return;
    e.preventDefault();
    const el = S.sel.el;
    const r0 = el.getBoundingClientRect();
    const fs0 = parseFloat(getComputedStyle(el).fontSize) || 14;
    const sx = e.clientX, sy = e.clientY;
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const keys = { w: uid("k"), h: uid("k"), f: uid("k") };
    const kind0 = sizeKind(el);
    const move = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      const kind = ev.ctrlKey ? "box" : kind0;
      if (kind === "text") {
        S.editKey = keys.f;
        const ratio = Math.max(0.3, (r0.height + dy) / Math.max(1, r0.height));
        setStyle("font-size", `${Math.max(8, Math.round(fs0 * ratio))}px`);
      } else if (kind === "icon") {
        const size = Math.max(8, Math.round(Math.max(r0.width + dx, r0.height + dy)));
        S.editKey = keys.w;
        setStyle("width", `${size}px`);
        S.editKey = keys.h;
        setStyle("height", `${size}px`);
      } else {
        // 너비만 바꾸려면 Shift, 높이만 바꾸려면 Alt
        if (!ev.altKey) {
          S.editKey = keys.w;
          setStyle("width", `${Math.max(16, Math.round(r0.width + dx))}px`);
        }
        if (!ev.shiftKey) {
          S.editKey = keys.h;
          setStyle("height", `${Math.max(12, Math.round(r0.height + dy))}px`);
        }
      }
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      S.editKey = null;
      renderPanel();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
  $o(".scopechip").addEventListener("click", () => {
    if (!S.sel) return;
    const path = cssPath(S.sel.el);
    S.scope = S.scope === path ? (scopeOptions(S.sel.el)[0] || {}).sel : path;
    S.editKey = null;
    renderPanel();
    scheduleDraw();
  });

  /* ----- 댓글 ----- */
  function containerOf(x, y, w, h) {
    // 영역을 통째로 품는 가장 작은 요소에 붙인다. 그래야 그 부분이 스크롤돼도 댓글이 따라간다.
    let el = document.elementFromPoint(x + w / 2, y + h / 2);
    while (el && el !== document.body) {
      const r = el.getBoundingClientRect();
      if (r.left <= x + 1 && r.top <= y + 1 && r.right >= x + w - 1 && r.bottom >= y + h - 1 && el !== ovHost) return el;
      el = el.parentElement;
    }
    return document.querySelector(".app-shell") || document.body;
  }
  function insideOf(anchor, x, y, w, h) {
    // 영역 안에 든 요소 이름 몇 개 (Claude 가 어디인지 알아보게)
    const out = [];
    anchor.querySelectorAll("*").forEach((n) => {
      if (out.length >= 8) return;
      const r = n.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) return;
      if (r.left >= x - 2 && r.top >= y - 2 && r.right <= x + w + 2 && r.bottom <= y + h + 2) {
        if (out.some((o) => o.el.contains(n))) return;
        out.push({ el: n, label: shortLabel(n), text: textOf(n).slice(0, 40) });
      }
    });
    return out.map(({ label, text }) => ({ label, text }));
  }
  function startPointComment(el, x, y) {
    const r = el.getBoundingClientRect();
    openCommentPop({
      anchor: describe(el), _el: el,
      at: { x: r.width ? (x - r.left) / r.width : 0, y: r.height ? (y - r.top) / r.height : 0 },
    }, x, y);
  }
  function startRegionComment(start, e) {
    const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
    const w = Math.abs(e.clientX - start.x), h = Math.abs(e.clientY - start.y);
    const anchor = containerOf(x, y, w, h);
    const r = anchor.getBoundingClientRect();
    openCommentPop({
      anchor: describe(anchor, cssPath(anchor)), _el: anchor,
      region: { x: (x - r.left) / r.width, y: (y - r.top) / r.height, w: w / r.width, h: h / r.height },
      regionPx: { w: Math.round(w), h: Math.round(h) },
      inside: insideOf(anchor, x, y, w, h),
    }, x + w, y);
  }
  let popDraft = null;
  function openCommentPop(draft, x, y) {
    popDraft = draft;
    const pop = $(".pop");
    const editing = !!draft.id;
    pop.innerHTML = `
      <div class="phead">${editing ? `${draft.n}번 댓글 고치기` : "댓글"} <small>${esc(viewLabel(draft.anchor.view))} · ${esc(draft.anchor.label)}</small></div>
      <div class="kinds">${KINDS.map(([k, l]) => `<button data-kind="${k}" class="${(draft.kind || "fix") === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <textarea rows="4" placeholder="무엇을 어떻게 바꾸면 좋을까요? (예: 여기 글자가 너무 작아, 카드 사이를 넓게)">${esc(draft.text || "")}</textarea>
      <div class="pacts">${editing ? `<label class="chk"><input type="checkbox" data-done ${draft.done ? "checked" : ""}> 해결됨</label>` : ""}
        <span class="sp"></span><button data-pop="cancel">그만두기</button><button class="primary" data-pop="ok">달기 (Ctrl+Enter)</button></div>`;
    pop.hidden = false;
    ({ x, y } = toTop(x, y));
    const W = TOP.innerWidth, H = TOP.innerHeight;
    const pw = 320, ph = 230;
    pop.style.left = `${Math.max(8, Math.min(W - pw - 8, x + 12))}px`;
    pop.style.top = `${Math.max(8, Math.min(H - ph - 8, y - 20))}px`;
    pop.querySelector("textarea").focus();
  }
  function closePop(save) {
    const pop = $(".pop");
    if (save && popDraft) {
      const text = pop.querySelector("textarea").value.trim();
      const kind = (pop.querySelector("[data-kind].on") || {}).dataset?.kind || "fix";
      const done = !!pop.querySelector("[data-done]")?.checked;
      if (!text) return toast("댓글 내용을 적어 주세요");
      if (popDraft.id) {
        Object.assign(S.comments.find((c) => c.id === popDraft.id), { text, kind, done });
      } else {
        const n = S.comments.reduce((m, c) => Math.max(m, c.n), 0) + 1;
        S.comments.push({ ...popDraft, id: uid("m"), n, text, kind, done: false, theme: themeKey(), variant: cur().name, createdAt: new Date().toISOString() });
      }
      saveDraftSoon();
    }
    popDraft = null;
    pop.hidden = true;
    render();
  }

  /* ---------- 색 고르기: 그라데이션 판 + 스포이트 ----------
     단색 견본은 두지 않는다(사용자 결정). 판에서 끌어 고르고, 스포이트로 화면 어디서든(앱 밖 다른 창·그림도) 색을 따온다.
     스포이트는 브라우저의 EyeDropper(크롬·엣지). 없는 브라우저는 앱 안에서 누른 곳의 색을 가져온다. */
  function hexToHsv(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
    let h = 0;
    if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [(h * 60 + 360) % 360, max ? d / max : 0, max];
  }
  function hsvToHex(h, s, v) {
    const f = (n) => {
      const k = (n + h / 60) % 6;
      return Math.round(255 * (v - v * s * Math.max(0, Math.min(k, 4 - k, 1)))).toString(16).padStart(2, "0");
    };
    return `#${f(5)}${f(3)}${f(1)}`;
  }
  let picker = null; // { kind, key, h, s, v, from }
  function currentColorOf(kind, key) {
    if (kind === "style" && S.sel) return getComputedStyle(S.sel.el).getPropertyValue(key);
    return rootVar(key);
  }
  function openPicker(btn, kind, key) {
    const from = toHex(currentColorOf(kind, key));
    const [h, s, v] = hexToHsv(from);
    picker = { kind, key, h, s, v, from };
    S.editKey = uid("k"); // 판을 끄는 동안 바뀐 값은 한 줄로 합친다
    const box = $(".picker");
    const r = btn.getBoundingClientRect();
    box.hidden = false;
    box.style.left = `${Math.max(8, Math.min(TOP.innerWidth - 248, r.left - 200))}px`;
    box.style.top = `${Math.max(8, Math.min(TOP.innerHeight - box.offsetHeight - 8, r.bottom + 6))}px`;
    box.querySelector(".ptitle").textContent = kind === "accent" ? "강조색 (진한·옅은 강조 함께)" : kind === "token" ? key : `${key} · ${shortLabel(S.sel.el)}`;
    paintPicker();
  }
  function closePicker() {
    picker = null;
    $(".picker").hidden = true;
    S.editKey = null;
    renderPanel();
  }
  function paintPicker() {
    const box = $(".picker");
    const hex = hsvToHex(picker.h, picker.s, picker.v);
    box.querySelector(".sv").style.setProperty("--hue", `hsl(${picker.h} 100% 50%)`);
    const k1 = box.querySelector(".sv .knob");
    k1.style.left = `${picker.s * 100}%`;
    k1.style.top = `${(1 - picker.v) * 100}%`;
    box.querySelector(".hue .knob").style.left = `${(picker.h / 360) * 100}%`;
    box.querySelector(".pv").style.background = hex;
    box.querySelector(".pfrom").style.background = picker.from;
    const input = box.querySelector(".phex");
    if (root.activeElement !== input) input.value = hex;
  }
  function pickColor(hex) {
    if (!picker) return;
    if (picker.kind === "token") setToken(picker.key, hex);
    else if (picker.kind === "accent") setAccent(hex);
    else setStyle(picker.key, hex);
  }
  function setFromHex(hex) {
    if (!/^#[0-9a-f]{6}$/i.test(hex)) return;
    [picker.h, picker.s, picker.v] = hexToHsv(hex.toLowerCase());
    paintPicker();
    pickColor(hex.toLowerCase());
  }
  async function eyedrop() {
    const ED = TOP.EyeDropper || window.EyeDropper;
    if (ED) {
      try {
        return toHex((await new ED().open()).sRGBHex);
      } catch {
        return null; // Esc 로 그만둠
      }
    }
    toast("이 브라우저는 앱 밖 색 따기를 못 해요 (크롬·엣지는 돼요). 앱에서 색을 딸 곳을 누르세요");
    return new Promise((resolve) => (S.pickInApp = resolve));
  }
  function colorAt(el) {
    // 누른 곳의 '보이는' 바탕색: 투명이면 바깥 상자로 올라간다
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      if (!isClear(bg)) return toHex(bg);
    }
    return toHex(getComputedStyle(document.body).backgroundColor);
  }
  function wirePicker() {
    const box = $(".picker");
    const drag = (area, fn) => area.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      area.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const r = area.getBoundingClientRect();
        fn(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)));
        paintPicker();
        pickColor(hsvToHex(picker.h, picker.s, picker.v));
      };
      move(e);
      area.addEventListener("pointermove", move);
      area.addEventListener("pointerup", () => area.removeEventListener("pointermove", move), { once: true });
    });
    drag(box.querySelector(".sv"), (x, y) => { picker.s = x; picker.v = 1 - y; });
    drag(box.querySelector(".hue"), (x) => { picker.h = x * 360; });
    box.querySelector(".phex").addEventListener("input", (e) => setFromHex(e.target.value.trim()));
    box.querySelector("[data-pick-eye]").addEventListener("click", async () => {
      const hex = await eyedrop();
      if (hex && picker) setFromHex(hex);
    });
    box.querySelector("[data-pick-from]").addEventListener("click", () => picker && setFromHex(picker.from));
    box.querySelector("[data-pick-close]").addEventListener("click", closePicker);
  }

  /* ---------- 동작 흐름: 단추를 누르면 무엇을 하는지 단계로 짜고, 복제 앱에서 시연한다 ---------- */
  const FLOW_KINDS = {
    nav: { label: "화면 이동", ph: "" },
    confirm: { label: "확인 창", ph: "예: 지금 동기화할까요?" },
    toast: { label: "알림", ph: "예: 동기화를 시작했어요" },
    loading: { label: "진행 표시", ph: "예: 자료 받는 중… (2초)" },
    run: { label: "작업 실행", ph: "예: 데이터 새로 받기" },
    open: { label: "창 열기", ph: "예: 설정 창" },
    note: { label: "메모", ph: "자유롭게 적기" },
  };
  const CLICKABLE = "button, a[href], [role=button], [data-view], [data-act], [data-action], summary, label, input[type=checkbox], input[type=radio], select";
  function flowTarget(el) {
    const t = el.closest(CLICKABLE);
    return t && !t.closest("#__studio-ov") ? t : null;
  }
  function guessFlow(btn) {
    if (btn.dataset.view) return { summary: `'${viewLabel(btn.dataset.view)}' 화면으로 이동`, steps: [{ kind: "nav", view: btn.dataset.view }] };
    if (btn.tagName === "A") return { summary: `링크 열기 (${btn.getAttribute("href")})`, steps: [{ kind: "open", text: btn.getAttribute("href") }] };
    return { summary: "", steps: [] };
  }
  function flowFor(node) {
    if (!(node instanceof Element)) return null;
    return [...cur().changes].reverse().find((c) => {
      if (c.type !== "flow") return false;
      const el = resolve(c.target, c._el);
      c._el = el;
      return el && el.contains(node);
    }) || null;
  }
  function ensureFlow(btn) {
    const path = cssPath(btn);
    if (S.flow && S.flow.path === path) return S.flow;
    const saved = [...cur().changes].reverse().find((c) => c.type === "flow" && c.target.path === path);
    const guess = guessFlow(btn);
    S.flow = saved
      ? { path, steps: clean(saved.steps), before: saved.before || [], summary: saved.summary || "", where: saved.where || "", job: null }
      : { path, steps: clean(guess.steps), before: clean(guess.steps), summary: guess.summary, where: "", job: null };
    return S.flow;
  }
  function flowHtml(el) {
    const btn = flowTarget(el);
    if (!btn) return "";
    const f = ensureFlow(btn);
    const viewOpts = (v) => Object.entries(VIEW_LABEL).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${l}</option>`).join("");
    const step = (st, i) => `<li class="step" draggable="true" data-step="${i}">
        <span class="sgrip" title="끌어서 순서 바꾸기">⠿</span><b>${i + 1}</b>
        <select data-step-kind="${i}">${Object.entries(FLOW_KINDS).map(([k, v]) => `<option value="${k}" ${k === st.kind ? "selected" : ""}>${v.label}</option>`).join("")}</select>
        <button class="mini" data-flow-del="${i}" title="빼기">✕</button>
        ${st.kind === "nav" ? `<select data-step-view="${i}">${viewOpts(st.view)}</select>` : `<input data-step-text="${i}" value="${esc(st.text || "")}" placeholder="${esc(FLOW_KINDS[st.kind]?.ph || "")}">`}</li>`;
    const aiBusy = f.job && f.job.status === "running";
    const saved = cur().changes.some((c) => c.type === "flow" && c.target.path === f.path);
    return `<section class="flowbox"><h4>동작 <small>누르면 일어나는 일 · ${esc(shortLabel(btn))}</small></h4>
      <div class="flowsrc">${f.summary ? `지금: ${esc(f.summary)}` : "지금 하는 일은 코드에서 알아봐야 해요"}
        ${INFO.claude ? `<button data-flow-ai ${aiBusy ? "disabled" : ""}>${aiBusy ? "알아보는 중…" : "AI 에게 알아보기"}</button>` : ""}
        ${f.where ? `<div class="small">코드: <code>${esc(f.where)}</code></div>` : ""}</div>
      ${f.job && f.job.status === "failed" ? `<p class="err">${esc(f.job.error || "못 알아냈어요")}</p>` : ""}
      <ol class="flow">${f.steps.map(step).join("") || `<li class="small">단계가 없어요. 아래에서 더해 흐름을 짜 보세요.</li>`}</ol>
      <div class="flowadd">${Object.entries(FLOW_KINDS).map(([k, v]) => `<button data-flow-add="${k}">＋${v.label}</button>`).join("")}</div>
      <div class="pacts2"><button class="primary" data-flow-play>▶ 시연</button>
        ${f.before.length ? `<button data-flow-play-before>지금 동작 시연</button><button data-flow-reset>처음대로</button>` : ""}
        <button data-flow-save>${saved ? "흐름 다시 담기" : "이 흐름으로 바꾸기"}</button></div>
      <p class="small">담아 두면 둘러보기(V)에서 이 단추를 눌렀을 때 바꾼 흐름대로 시연돼요.</p></section>`;
  }
  function showAppToast(text) {
    if (APP.toast) APP.toast(text);
    else toast(text);
  }
  async function showBusy(text, ms) {
    const b = $o(".busy");
    b.querySelector(".busytext").textContent = text || "처리하는 중…";
    b.hidden = false;
    await sleep(ms);
    b.hidden = true;
  }
  async function playFlow(steps) {
    if (S.demoing) return;
    S.demoing = true;
    scheduleDraw();
    try {
      for (const st of steps) {
        const text = (st.text || "").trim();
        if (st.kind === "nav" && APP.switchView) {
          APP.switchView(st.view || Object.keys(VIEW_LABEL)[0] || "page");
          await sleep(800);
        } else if (st.kind === "confirm") {
          const ok = APP.dialog
            ? await APP.dialog({ title: "확인", icon: "help", message: text || "계속할까요?" })
            : confirm(text || "계속할까요?");
          if (ok !== true) {
            showAppToast("취소하면 여기서 멈춰요");
            break;
          }
        } else if (st.kind === "loading") {
          const sec = parseFloat((text.match(/(\d+(?:\.\d+)?)\s*초/) || [])[1]) || 1.6;
          await showBusy(text.replace(/\(?\d+(?:\.\d+)?\s*초\)?/, "").trim(), sec * 1000);
        } else if (st.kind === "run") {
          showAppToast(`▶ ${text || "작업"} (시연이라 실제로는 하지 않아요)`);
          await sleep(1500);
        } else if (st.kind === "open") {
          if (APP.dialog) await APP.dialog({ title: text || "창", message: "(시연) 여기에 이 창이 열려요." });
          else await sleep(800);
        } else {
          showAppToast(text || "…");
          await sleep(1500);
        }
      }
    } finally {
      S.demoing = false;
      scheduleDraw();
    }
  }
  async function askFlowAI() {
    const btn = S.sel && flowTarget(S.sel.el);
    if (!btn) return;
    const f = ensureFlow(btn);
    const target = {
      label: shortLabel(btn), text: textOf(btn), id: btn.id, classes: [...btn.classList], data: { ...btn.dataset },
      html: btn.outerHTML.slice(0, 700), view: viewKey(), parent: shortLabel(btn.parentElement || btn),
      views: Object.keys(VIEW_LABEL),
    };
    const res = await fetch("/__studio/ai/flow", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }),
    }).then((r) => r.json()).catch(() => ({ ok: false }));
    if (!res.ok) return toast(res.message || "AI 를 부르지 못했어요");
    f.job = { id: res.id, status: "running" };
    renderPanel();
    for (let i = 0; i < 200 && f.job.status === "running"; i++) {
      await sleep(1500);
      const j = await fetch(`/__studio/ai-job?id=${res.id}`).then((r) => r.json()).catch(() => null);
      if (!j) continue;
      f.job = { id: res.id, status: j.status, error: j.error };
      if (j.status === "done" && j.result) {
        f.before = (j.result.steps || []).map((x) => ({ kind: FLOW_KINDS[x.kind] ? x.kind : "note", text: x.text || "", view: x.view }));
        f.summary = j.result.summary || f.summary;
        f.where = j.result.where || "";
        // 아직 손대지 않았으면 알아낸 흐름을 편집본으로 깔아 준다
        if (!cur().changes.some((c) => c.type === "flow" && c.target.path === f.path)) f.steps = clean(f.before);
      }
    }
    if (S.flow === f) renderPanel();
  }
  function saveFlow() {
    const btn = S.sel && flowTarget(S.sel.el);
    if (!btn || !S.flow) return;
    const f = S.flow;
    cur().changes.filter((c) => c.type === "flow" && c.target.path === f.path).forEach((c) => removeChange(c.id));
    S.editKey = null;
    commit({ type: "flow", target: describe(btn, f.path), before: clean(f.before), summary: f.summary, where: f.where,
      steps: clean(f.steps), _el: btn });
    toast("흐름을 담았어요. 둘러보기(V)에서 그 단추를 눌러 보세요");
  }

  /* ---------- AI 추천: 왼쪽 아래 작은 카드가 "이건 어때요?" 하며 바로 미리 보여 준다 ---------- */
  const previewStyle = document.createElement("style");
  previewStyle.id = "__studio-preview";
  document.head.appendChild(previewStyle);
  function screenOutline() {
    const main = document.querySelector("main, .main, .content, .app-shell") || document.body;
    const out = [];
    const walk = (node, depth) => {
      for (const c of node.children) {
        if (out.length >= 45 || c === ovHost) continue;
        const r = c.getBoundingClientRect();
        if (r.width < 60 || r.height < 14 || r.bottom < 0 || r.top > innerHeight) continue;
        if (goodClasses(c).length || c.id) out.push({ el: shortLabel(c), text: textOf(c).slice(0, 36), size: `${Math.round(r.width)}×${Math.round(r.height)}`, depth });
        if (depth < 3) walk(c, depth + 1);
      }
    };
    walk(main, 0);
    return out;
  }
  function elemInfo(el, sel) {
    const cs = getComputedStyle(el);
    const keys = ["display", "font-size", "font-weight", "color", "background-color", "padding", "margin", "gap",
      "border-radius", "box-shadow", "line-height", "letter-spacing", "width", "height"];
    return {
      selector: sel, path: cssPath(el), label: shortLabel(el), text: textOf(el), size: describe(el).size,
      styles: Object.fromEntries(keys.map((k) => [k, cs.getPropertyValue(k)])),
      rules: matchedRuleTexts(el),
      children: [...el.children].slice(0, 10).map((c) => `${shortLabel(c)} “${textOf(c).slice(0, 24)}”`),
      parent: el.parentElement ? shortLabel(el.parentElement) : "",
    };
  }
  function aiContext(focusSelected) {
    const ctx = {
      view: viewKey(), viewLabel: viewLabel(viewKey()), theme: themeLabel(themeKey()),
      viewport: { w: innerWidth, h: innerHeight }, ask: S.ai.ask || "",
      tokens: Object.fromEntries(tokenGroups().flatMap((g) => g[1]).map(([n]) => [n, rootVar(n)])),
      screen: screenOutline(),
      userChanges: cur().changes.slice(-12).map((c) => ({ type: c.type, where: c.selector || c.name || (c.target && c.target.label), prop: c.prop, to: c.to })),
      comments: S.comments.slice(-8).map((c) => ({ kind: kindLabel(c.kind), text: c.text, where: c.anchor.label })),
    };
    if (focusSelected && S.sel && S.sel.el.isConnected) ctx.selected = elemInfo(S.sel.el, S.scope);
    return ctx;
  }
  let aiTimer = 0;
  function aiAutoSoon(why) {
    if (!INFO.claude || !S.ai.auto || S.clean) return;
    clearTimeout(aiTimer);
    aiTimer = setTimeout(() => {
      // 너무 자주 부르지 않는다: 30초에 한 번, 제안을 보고 있거나 댓글을 쓰는 중이면 쉬기
      if (S.ai.status === "thinking" || S.ai.status === "show" || !$(".pop").hidden || !$(".modal").hidden) return;
      if (Date.now() - S.ai.lastAt < 30000) return;
      askAI(why === "select");
    }, why === "select" ? 1600 : 2600);
  }
  async function askAI(focusSelected) {
    clearPreview();
    S.ai = { ...S.ai, status: "thinking", items: [], idx: 0, error: "", lastAt: Date.now(), focus: !!focusSelected };
    renderAi();
    const res = await fetch("/__studio/ai/suggest", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ context: aiContext(focusSelected) }),
    }).then((r) => r.json()).catch(() => ({ ok: false }));
    if (!res.ok) {
      S.ai.status = "error";
      S.ai.error = res.message || "AI 를 부르지 못했어요";
      return renderAi();
    }
    const id = (S.ai.job = res.id);
    while (S.ai.job === id) {
      await sleep(700);
      const j = await fetch(`/__studio/ai-job?id=${id}`).then((r) => r.json()).catch(() => null);
      if (!j || S.ai.job !== id) break;
      const fresh = j.items.length > S.ai.items.length;
      S.ai.items = j.items;
      S.ai.jobStatus = j.status;
      if (fresh && S.ai.status === "thinking") {
        S.ai.status = "show";
        S.ai.idx = 0;
        renderAi(true);
        demoSuggestion(S.ai.items[0]);
      } else if (fresh) {
        renderAi();
      }
      if (j.status !== "running") {
        if (!S.ai.items.length) {
          S.ai.status = "error";
          S.ai.error = j.error || "이번엔 제안할 것을 못 찾았어요";
        }
        renderAi();
        break;
      }
    }
  }
  function suggestionCss(item) {
    const blocks = [];
    for (const c of item.changes || []) {
      if (c.type === "token" && /^--[\w-]+$/.test(c.name || "")) blocks.push(`${themeSelector(themeKey())} { ${c.name}: ${c.to} !important; }`);
      if (c.type === "style" && countOf(c.selector) && /^[a-z-]+$/.test(c.prop || "")) blocks.push(`${c.selector} { ${c.prop}: ${c.to} !important; }`);
    }
    return blocks.join("\n");
  }
  function clearPreview() {
    previewStyle.textContent = "";
    document.querySelectorAll(".__studio-sparkle").forEach((n) => n.classList.remove("__studio-sparkle"));
  }
  async function demoSuggestion(item) {
    if (!item) return;
    const css = suggestionCss(item);
    const sel = item.focus && countOf(item.focus) ? item.focus : ((item.changes || []).find((c) => c.selector && countOf(c.selector)) || {}).selector;
    let targets = [];
    try { targets = sel ? [...document.querySelectorAll(sel)].slice(0, 6) : []; } catch { targets = []; }
    if (targets[0]) {
      const r = targets[0].getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) targets[0].scrollIntoView({ block: "center", behavior: "smooth" });
    }
    const token = (S.ai.demoToken = uid("d"));
    // 뾰로롱: 바뀔 곳이 반짝이고, 바뀐 모습 → 원래 → 바뀐 모습으로 한 번 보여 준 뒤 바뀐 채로 둔다
    targets.forEach((t) => t.classList.add("__studio-sparkle"));
    previewStyle.textContent = css;
    await sleep(1400);
    if (S.ai.demoToken !== token) return;
    previewStyle.textContent = "";
    await sleep(650);
    if (S.ai.demoToken !== token) return;
    previewStyle.textContent = css;
    await sleep(900);
    targets.forEach((t) => t.classList.remove("__studio-sparkle"));
  }
  function acceptSuggestion(item) {
    clearPreview();
    S.group = uid("g");
    for (const c of item.changes || []) {
      S.editKey = null;
      if (c.type === "token") {
        const prev = cur().changes.find((x) => x.type === "token" && x.theme === themeKey() && x.name === c.name);
        commit({ type: "token", theme: themeKey(), name: c.name, from: prev ? prev.from : rootVar(c.name), to: c.to, by: "ai" });
      } else if (c.type === "style" && countOf(c.selector)) {
        const el = document.querySelector(c.selector);
        const prev = cur().changes.find((x) => x.type === "style" && x.selector === c.selector && x.prop === c.prop);
        commit({ type: "style", selector: c.selector, prop: c.prop, from: prev ? prev.from : getComputedStyle(el).getPropertyValue(c.prop).trim(),
          to: c.to, target: describe(el, c.selector), count: countOf(c.selector), by: "ai", why: item.title });
      }
    }
    S.group = null;
    toast(`담았어요: ${item.title} (Ctrl+Z 로 되돌리기)`);
    nextSuggestion();
  }
  function nextSuggestion() {
    clearPreview();
    S.ai.idx += 1;
    if (S.ai.idx < S.ai.items.length) {
      renderAi(true);
      demoSuggestion(S.ai.items[S.ai.idx]);
    } else {
      S.ai.status = S.ai.jobStatus === "running" ? "thinking" : "done";
      renderAi();
    }
  }
  function closeAi() {
    clearPreview();
    S.ai.demoToken = null;
    if (S.ai.job && S.ai.status === "thinking") {
      fetch("/__studio/ai/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: S.ai.job }) });
    }
    S.ai.job = null;
    S.ai.status = "idle";
    S.ai.open = false;
    renderAi();
  }
  function renderAi(pop = false) {
    const box = $(".ai");
    if (!box) return;
    box.hidden = S.clean || !INFO.claude;
    if (box.hidden) return;
    const o = toTop(0, 0);
    box.style.left = `${o.x + 14}px`;
    const a = S.ai;
    let inner = "";
    if (a.status === "thinking") {
      inner = `<div class="ai-head"><span class="spark">✨</span><b>생각하는 중</b><span class="dots"><i></i><i></i><i></i></span>
        <button class="mini" data-ai="close" title="그만">✕</button></div>
        <p class="small">${a.focus ? "고른 요소" : `${esc(viewLabel(viewKey()))} 화면`}을 보고 있어요</p>`;
    } else if (a.status === "show" && a.items[a.idx]) {
      const it = a.items[a.idx];
      inner = `<div class="ai-head"><span class="spark">✨</span><b>이건 어때요?</b><span class="cnt">${a.idx + 1}/${a.items.length}${a.jobStatus === "running" ? "+" : ""}</span>
          <button class="mini" data-ai="close" title="닫기">✕</button></div>
        <div class="ai-title">${esc(it.title)}</div>
        <div class="ai-why">${esc(it.why || "")}</div>
        <div class="ai-chg">${(it.changes || []).map((c) => `<code>${esc(c.type === "token" ? c.name : `${c.selector} ${c.prop}`)}</code> → ${esc(String(c.to).slice(0, 28))}`).join("<br>")}</div>
        <div class="pacts2"><button class="primary" data-ai="accept">담기</button><button data-ai="replay">▶ 다시 시연</button><button data-ai="next">다음</button></div>`;
    } else if (a.status === "error" || a.status === "done") {
      inner = `<div class="ai-head"><span class="spark">✨</span><b>${a.status === "done" ? "추천을 다 봤어요" : "추천을 못 받았어요"}</b><button class="mini" data-ai="close">✕</button></div>
        ${a.error ? `<p class="small">${esc(a.error)}</p>` : ""}
        <div class="pacts2"><button data-ai="ask-screen">이 화면 다시</button>${S.sel ? `<button data-ai="ask-sel">고른 것</button>` : ""}</div>`;
    } else if (a.open) {
      inner = `<div class="ai-head"><span class="spark">✨</span><b>AI 추천</b><button class="mini" data-ai="close">✕</button></div>
        <input class="wide" data-ai-ask value="${esc(a.ask)}" placeholder="바라는 느낌 (예: 더 차분하게, 카드 정리)">
        <div class="pacts2"><button class="primary" data-ai="ask-screen">이 화면 추천</button>${S.sel ? `<button data-ai="ask-sel">고른 것 추천</button>` : ""}</div>
        <label class="chk"><input type="checkbox" data-ai-auto ${a.auto ? "checked" : ""}> 고르거나 화면을 옮기면 알아서 추천 (30초에 한 번)</label>`;
    } else {
      box.classList.remove("open");
      box.innerHTML = `<button class="ai-pill" data-ai="open" title="AI 추천">✨ <span>AI 추천</span>${a.auto ? `<i class="on"></i>` : ""}</button>`;
      return;
    }
    box.classList.add("open"); // 펼친 카드는 아래 도구 막대 위로 올린다 (겹치지 않게)
    box.innerHTML = `<div class="ai-card ${pop ? "pop" : ""}">${pop ? `<span class="burst">${"<i>✦</i>".repeat(7)}</span>` : ""}${inner}</div>`;
  }

  /* ---------- 저장 ---------- */
  const clean = (o) => JSON.parse(JSON.stringify(o, (k, v) => (k.startsWith("_") ? undefined : v)));
  function snapshot() {
    return clean({
      kind: "design-studio", app: INFO.app || "",
      schema: 1,
      title: S.title,
      note: S.note,
      freedom: S.freedom,
      app: { version: INFO.version, data: INFO.mode },
      proposal: INFO.ctx || null, // 시안 위에서 만든 요청이면 그 시안 이름 (선택자·규칙이 시안 기준)
      // 앱이 실제로 그려진 크기 (패널을 붙이면 iframe 이 좁아져 이 값도 줄어든다 — 그 너비의 진짜 배치다)
      viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio },
      theme: themeKey(),
      view: viewKey(),
      chosen: S.active,
      variants: S.variants.map((v) => ({ ...v, css: compileCss(v.changes) })),
      comments: S.comments,
    });
  }
  function markdown(data) {
    const L = [];
    const v = data.variants[data.chosen];
    L.push(`# 디자인 요청: ${data.title || "(제목 없음)"}`, "");
    L.push(`- 저장: ${new Date().toLocaleString("ko-KR")} · 앱 v${data.app.version} · ${data.app.data === "real" ? "내 데이터" : "연습용 데이터"}`);
    L.push(`- 창 크기 ${data.viewport.w}×${data.viewport.h} · 테마 ${themeLabel(data.theme)} · 마지막 화면 ${viewLabel(data.view)}`);
    L.push(`- 고른 조합: **${v.name}** (조합 ${data.variants.length}개)`);
    L.push(`- 재량: ${data.freedom === "exact" ? "적은 그대로만 옮겨 주세요" : "뜻을 살려 더 다듬어도 좋아요 (어울리게 조정·주변 정리 허용)"}`);
    L.push(`- 원본 데이터: \`${INFO.requests || ".design-studio/requests"}/<이 파일 이름>.json\``, "");
    if (data.note) L.push("## 전체 메모", "", data.note, "");
    if (data.comments.length) {
      L.push(`## 댓글 ${data.comments.length}개`, "");
      for (const c of data.comments) {
        L.push(`${c.n}. **[${kindLabel(c.kind)}]** ${c.text}${c.done ? " _(해결됨)_" : ""}`);
        L.push(`   - 화면: ${viewLabel(c.anchor.view)} · 요소 \`${c.anchor.label}\`${c.anchor.text ? ` “${c.anchor.text.slice(0, 50)}”` : ""} · ${c.anchor.size}`);
        L.push(`   - 선택자: \`${c.anchor.path}\` (같은 모양: \`${c.anchor.selector}\`)`);
        if (c.region) L.push(`   - 영역: 그 요소 안 약 ${c.regionPx.w}×${c.regionPx.h}px. 안에 든 것: ${c.inside.map((i) => `\`${i.label}\`${i.text ? ` “${i.text}”` : ""}`).join(", ") || "-"}`);
        if (c.anchor.rules.length) L.push(`   - 걸린 CSS 규칙: ${c.anchor.rules.map((r) => `\`${r}\``).join(", ")}`);
        if (c.variant !== v.name) L.push(`   - (조합 '${c.variant}'를 보며 단 댓글)`);
      }
      L.push("");
    }
    const section = (variant, chosen) => {
      const ch = variant.changes;
      L.push(`## ${chosen ? "고른 조합" : "다른 조합"}: ${variant.name} — 바꾼 것 ${ch.length}개`, "");
      if (!ch.length) return L.push("(바꾼 것 없음)", "");
      const tokens = ch.filter((c) => c.type === "token");
      if (tokens.length) {
        L.push("### 색·모양 토큰", "", "| 테마 | 토큰 | 원래 | 새 값 |", "|---|---|---|---|");
        const last = new Map();
        tokens.forEach((c) => last.set(`${c.theme}|${c.name}`, c));
        last.forEach((c) => L.push(`| ${themeLabel(c.theme)} | \`${c.name}\` | \`${c.from}\` | \`${c.to}\` |`));
        L.push("");
      }
      const styles = ch.filter((c) => c.type === "style");
      if (styles.length) {
        L.push("### 요소 모양", "");
        const last = new Map();
        styles.forEach((c) => last.set(`${c.selector}|${c.prop}`, c));
        last.forEach((c) => {
          L.push(`- \`${c.selector}\` (${c.count}곳 · 예: ${viewLabel(c.target.view)}의 \`${c.target.label}\`${c.target.text ? ` “${c.target.text.slice(0, 40)}”` : ""}) — **${c.prop}**: \`${c.from}\` → \`${c.to}\``);
          if (c.target.rules.length) L.push(`  - 지금 걸린 규칙: ${c.target.rules.slice(-4).map((r) => `\`${r}\``).join(", ")}`);
        });
        L.push("");
      }
      if (styles.some((c) => c.prop === "translate")) {
        L.push("> `translate` 는 '이만큼 옮기고 싶다' 는 뜻이다. 소스에서는 translate 대신 margin·gap·정렬·배치(grid/flex 순서)로 자연스럽게 옮긴다.", "");
      }
      const flows = ch.filter((c) => c.type === "flow");
      if (flows.length) {
        L.push("### 동작 흐름 (단추를 누르면)", "");
        const stepLine = (st, i) => `${i + 1}. [${(FLOW_KINDS[st.kind] || {}).label || st.kind}] ${st.kind === "nav" ? `'${viewLabel(st.view)}' 화면으로` : st.text || ""}`;
        flows.forEach((c) => {
          L.push(`- ${viewLabel(c.target.view)} \`${c.target.label}\`${c.target.text ? ` “${c.target.text.slice(0, 30)}”` : ""} — 선택자 \`${c.target.path}\``);
          if (c.before && c.before.length) L.push(`  - 지금${c.where ? ` (${c.where})` : ""}:`, ...c.before.map((st, i) => `    ${stepLine(st, i)}`));
          else if (c.summary) L.push(`  - 지금: ${c.summary}`);
          L.push("  - 바라는 흐름:", ...c.steps.map((st, i) => `    ${stepLine(st, i)}`));
        });
        L.push("");
      }
      const texts = ch.filter((c) => c.type === "text");
      if (texts.length) {
        L.push("### 글자", "");
        texts.forEach((c) => L.push(`- ${viewLabel(c.target.view)} \`${c.target.path}\`: “${c.from.trim()}” → “${c.to.trim()}”`));
        L.push("");
      }
      const moves = ch.filter((c) => c.type === "move");
      if (moves.length) {
        L.push("### 순서·위치", "");
        moves.forEach((c) => L.push(`- ${viewLabel(c.target.view)} \`${c.parent.label}\` 안에서 \`${c.target.label}\`${c.target.text ? ` “${c.target.text.slice(0, 30)}”` : ""} 을(를) \`${c.ref.label}\`${c.ref.text ? ` “${c.ref.text.slice(0, 30)}”` : ""} ${c.where === "before" ? "앞" : "뒤"}으로 (${c.fromIndex + 1}번째 → ${(c.toIndex ?? 0) + 1}번째)`));
        L.push("");
      }
      if (variant.css) L.push("### 화면에서 쓴 CSS (덮어쓰기 규칙 — 그대로 붙이지 말고 원래 규칙을 고치는 데 참고)", "", "```css", variant.css, "```", "");
    };
    section(v, true);
    data.variants.forEach((x, i) => i !== data.chosen && x.changes.length && section(x, false));
    return L.join("\n");
  }
  function openSaveModal() {
    if (S.editing) finishTextEdit(true);
    const m = $(".modal");
    const total = S.variants.reduce((n, v) => n + v.changes.length, 0);
    m.innerHTML = `<div class="card">
      <h3>${INFO.ctx ? "이 시안을 더 고쳐 달라고 하기" : "저장해서 Claude 에게 넘기기"}</h3>
      <p class="small">댓글 ${S.comments.length}개 · 바꾼 것 ${total}개 (조합 ${S.variants.length}개)</p>
      <label>한 줄 제목<input data-f="title" value="${esc(S.title)}" placeholder="예: 첫 화면 카드 정리, 강조색 남색으로"></label>
      <label>전체 메모<textarea data-f="note" rows="3" placeholder="전체적으로 바라는 느낌이 있으면 적어 주세요">${esc(S.note)}</textarea></label>
      <label>반영할 조합<select data-f="chosen">${S.variants.map((v, i) => `<option value="${i}" ${i === S.active ? "selected" : ""}>${esc(v.name)} · 바꾼 것 ${v.changes.length}</option>`).join("")}</select></label>
      <div class="seg two">
        <button data-freedom="refine" class="${S.freedom === "refine" ? "on" : ""}">뜻을 살려 더 다듬어 줘</button>
        <button data-freedom="exact" class="${S.freedom === "exact" ? "on" : ""}">적은 그대로만</button>
      </div>
      <div class="macts"><button data-modal="close">닫기</button>${
        !INFO.claude ? `<button class="primary" data-modal="save">저장</button>`
        : INFO.ctx ? `<button class="primary" data-modal="save-revise">저장하고 다시 고치기</button>`
        : `<button data-modal="save">저장만</button><button class="primary" data-modal="save-propose">저장하고 시안 만들기</button>`}</div>
      ${INFO.claude && !INFO.ctx ? `<p class="small">시안: Claude 가 진짜 화면 파일은 그대로 두고 복사본에 고쳐요. 다 되면 원래·시안을 오가며 보고 반영할지 정해요.</p>` : ""}
      <div class="result" hidden></div></div>`;
    m.hidden = false;
    m.querySelector("[data-f=title]").focus();
  }
  async function doSave(next = "") {
    const m = $(".modal");
    S.title = m.querySelector("[data-f=title]").value.trim();
    S.note = m.querySelector("[data-f=note]").value.trim();
    const chosen = +m.querySelector("[data-f=chosen]").value;
    if (chosen !== S.active) switchVariant(chosen);
    const data = snapshot();
    const md = markdown(data);
    const out = m.querySelector(".result");
    out.hidden = false;
    try {
      const res = await fetch("/__studio/save", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data, markdown: md }),
      }).then((r) => r.json());
      if (!res.ok) throw new Error(res.message || "저장하지 못했어요");
      S.savedAs = res.name;
      S.dirty = false;
      clearTimeout(draftTimer);
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* 없어도 된다 */ }
      if (next) {
        const body = next === "revise" ? { name: INFO.ctx, request: res.name } : { request: res.name, title: S.title };
        const started = await fetch(`/__studio/proposal/${next === "revise" ? "revise" : "start"}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        }).then((r) => r.json());
        if (!started.ok) throw new Error(started.message || "시안을 시작하지 못했어요");
        // 이번 요청은 Claude 에게 넘어갔다. 화면에 얹어 둔 변경·댓글은 비우고 시안 탭에서 진행을 본다.
        [...cur().changes].reverse().filter(isDom).forEach(revertDom);
        S.variants = [newVariant("조합 A")];
        S.active = 0;
        S.comments = [];
        S.title = "";
        S.note = "";
        S.undo = [];
        S.redo = [];
        applyCss();
        $(".modal").hidden = true;
        S.mode = "browse";
        document.documentElement.classList.remove("__studio-picking");
        S.tab = "proposals";
        S.collapsed = false;
        await refreshProposals();
        render();
        toast(next === "revise" ? "Claude 가 시안을 다시 고치기 시작했어요" : "Claude 가 시안을 만들기 시작했어요. 몇 분 걸려요");
        return;
      }
      const say = `디자인 스튜디오 저장본 ${res.name} 반영해 줘`;
      out.innerHTML = `<p>저장했어요: <code>${esc(INFO.requests || ".design-studio/requests")}/${esc(res.name)}.md</code></p>
        <p>Claude Code 에 이렇게 말하세요:</p><div class="say"><code>${esc(say)}</code><button data-copy="${esc(say)}">복사</button></div>
        <p class="small">웹(claude.ai)에서 쓰면 파일이 안 보이니 아래 '내용 복사'로 붙여 넣으세요.</p>
        <button data-copy-md>내용 복사 (마크다운)</button>`;
      out._md = md;
    } catch (err) {
      out.innerHTML = `<p>${S.savedAs && next ? "저장은 했는데 시안을 시작하지 못했어요" : "서버에 저장하지 못했어요"} (${esc(err.message)}). 내용을 복사해 Claude 에게 붙여 넣으세요.</p><button data-copy-md>내용 복사 (마크다운)</button>`;
      out._md = md;
    }
  }
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("복사했어요");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("복사했어요");
    }
  }

  /* ---------- 불러오기·임시 저장 ---------- */
  /* 저장본·임시본은 파일에서 온다. 화면에 innerHTML 로 그리는 번호·id·종류와 <style> 에 들어가는 값을 여기서 한 번 거른다.
     처음엔 그대로 믿어서, 저장본의 댓글 번호에 <img onerror> 를 넣으면 핀을 그리는 순간 실행됐다(검토에서 재현). */
  const CSS_BAD = /[{};<\\]|\/\*|url\(|@import|expression\(/i;
  const SEL_BAD = /[{};<]|\/\*/;
  const safeId = (v, p) => (/^[\w-]{1,64}$/.test(v) ? v : uid(p));
  const num = (v) => (Number.isFinite(+v) ? +v : 0);
  function cleanChange(c) {
    if (!c || typeof c !== "object") return null;
    c.id = safeId(c.id, "c");
    if ("count" in c) c.count = num(c.count);
    if (c.type === "token") {
      if (!/^--[\w-]+$/.test(c.name || "") || !/^[\w-]+$/.test(c.theme || "") || CSS_BAD.test(String(c.to ?? ""))) return null;
    } else if (c.type === "style") {
      if (!c.selector || SEL_BAD.test(c.selector) || !/^[a-z-]+$/.test(c.prop || "") || CSS_BAD.test(String(c.to ?? ""))) return null;
    } else if (!["text", "move", "flow"].includes(c.type)) return null;
    if (c.type !== "token") {
      if (!c.target || typeof c.target !== "object") return null;
      if (!Array.isArray(c.target.rules)) c.target.rules = [];
    }
    if (c.type === "move" && !(c.ref && typeof c.ref === "object" && c.parent && typeof c.parent === "object")) return null;
    if (c.type === "flow" && !Array.isArray(c.steps)) c.steps = [];
    return c;
  }
  function cleanComment(c) {
    if (!c || typeof c !== "object" || !c.anchor || typeof c.anchor !== "object") return null;
    c.id = safeId(c.id, "m");
    c.n = Math.round(num(c.n));
    if (!KINDS.some((k) => k[0] === c.kind)) c.kind = KINDS[0][0];
    if (c.region) c.region = { x: num(c.region.x), y: num(c.region.y), w: num(c.region.w), h: num(c.region.h) };
    c.at = { x: num(c.at?.x), y: num(c.at?.y) };
    return c;
  }
  function hydrate(data) {
    [...cur().changes].reverse().filter(isDom).forEach(revertDom);
    S.variants = (Array.isArray(data.variants) ? data.variants : []).map((v) => ({
      id: safeId(v?.id, "v"), name: String(v?.name || ""),
      changes: (Array.isArray(v?.changes) ? v.changes : []).map(cleanChange).filter(Boolean),
    }));
    if (!S.variants.length) S.variants = [newVariant("조합 A")];
    S.active = Math.max(0, Math.min(Math.round(num(data.chosen)), S.variants.length - 1));
    S.comments = (Array.isArray(data.comments) ? data.comments : []).map(cleanComment).filter(Boolean);
    S.title = data.title || "";
    S.note = data.note || "";
    S.freedom = data.freedom || "refine";
    S.undo = [];
    S.redo = [];
    cur().changes.filter(isDom).forEach(applyDom);
    applyCss();
    render();
  }
  /* 브라우저에 남기는 임시본: 저장하기 전에 창을 닫거나 새로 고쳐도 이어 하게.
     저장에 성공하면 지운다 — 남겨 두면 Claude 가 반영한 뒤 다시 열었을 때 같은 변경이 한 번 더 얹힌다
     (사이드바 단추를 두 번 옮기는 식). 저장한 것을 이어 하려면 '저장본 불러오기' 를 쓴다. */
  let draftTimer = 0;
  function saveDraftSoon(changed = true) {
    if (changed) S.dirty = true;
    if (!S.dirty) return;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => {
      try { localStorage.setItem(DRAFT_KEY, JSON.stringify(snapshot())); } catch { /* 저장소를 못 쓰면 이어 하기만 안 된다 */ }
    }, 400);
  }
  async function loadSaved(name) {
    const data = await fetch(`/__studio/request?name=${encodeURIComponent(name)}`).then((r) => r.json());
    if (data.ok === false) return toast(data.message || "못 불러왔어요");
    hydrate(data);
    S.dirty = false; // 저장본 그대로다. 손대기 전까지는 임시본을 만들지 않는다
    if (data.theme) applyAppTheme(data.theme);
    if (data.view && APP.switchView && !PARAMS.get("view")) APP.switchView(data.view);
    toast(`불러왔어요: ${data.title || name}`);
  }

  /* ---------- 패널·막대 누르기 ---------- */
  function onStudioClick(e) {
    const b = e.target.closest("button, [data-tab]");
    if (!b) return;
    const d = b.dataset;
    if (d.mode) return setMode(d.mode);
    if (d.tab) {
      S.tab = d.tab;
      renderPanel();
      return;
    }
    if (d.variant) return switchVariant(+d.variant);
    if (d.themeSet) {
      applyAppTheme(d.themeSet);
      return setTimeout(renderPanel, 30);
    }
    if (d.pick) return openPicker(b, d.pick, d.key);
    if (b.hasAttribute("data-eyecopy")) {
      return eyedrop().then((hex) => hex && copy(hex).then(() => toast(`${hex} 를 복사했어요`)));
    }
    if (d.tokenReset) {
      cur().changes.filter((c) => c.type === "token" && c.theme === themeKey() && c.name === d.tokenReset).forEach((c) => removeChange(c.id));
      return;
    }
    if (d.styleReset) return resetStyle(d.styleReset);
    if (d.crumb) {
      let el = S.sel.el;
      for (let i = 0; i < +d.crumb; i++) el = el.parentElement;
      return selectEl(el);
    }
    if (d.chgDel) return removeChange(d.chgDel);
    if (b.hasAttribute("data-flow-ai")) return askFlowAI();
    if (d.flowAdd && S.flow) {
      S.flow.steps.push(d.flowAdd === "nav" ? { kind: "nav", view: viewKey() } : { kind: d.flowAdd, text: "" });
      return renderPanel();
    }
    if (d.flowDel && S.flow) {
      S.flow.steps.splice(+d.flowDel, 1);
      return renderPanel();
    }
    if (b.hasAttribute("data-flow-play") && S.flow) return playFlow(S.flow.steps);
    if (b.hasAttribute("data-flow-play-before") && S.flow) return playFlow(S.flow.before);
    if (b.hasAttribute("data-flow-reset") && S.flow) {
      S.flow.steps = clean(S.flow.before);
      return renderPanel();
    }
    if (b.hasAttribute("data-flow-save")) return saveFlow();
    if (d.ai) {
      const a = d.ai;
      if (a === "open") {
        S.ai.open = true;
        return renderAi();
      }
      if (a === "close") return closeAi();
      if (a === "ask-screen") return askAI(false);
      if (a === "ask-sel") return askAI(true);
      if (a === "accept") return acceptSuggestion(S.ai.items[S.ai.idx]);
      if (a === "next") return nextSuggestion();
      if (a === "replay") return demoSuggestion(S.ai.items[S.ai.idx]);
    }
    if (d.cmtGo) {
      const c = S.comments.find((x) => x.id === d.cmtGo);
      if (c.anchor.view !== viewKey() && APP.switchView) APP.switchView(c.anchor.view);
      setTimeout(() => {
        const el = resolve(c.anchor, c._el);
        if (!el) return toast("그 요소가 지금 화면에 없어요");
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        el.classList.add("__studio-flash");
        setTimeout(() => el.classList.remove("__studio-flash"), 1400);
      }, 250);
      return;
    }
    if (d.cmtEdit || d.pin) {
      const c = S.comments.find((x) => x.id === (d.cmtEdit || d.pin));
      const r = b.getBoundingClientRect();
      if (b.getRootNode() === ovRoot) return openCommentPop({ ...c }, r.right, r.top);
      const o = toTop(0, 0);
      return openCommentPop({ ...c }, r.left - o.x - 340, r.top - o.y);
    }
    if (d.cmtDel) {
      S.comments = S.comments.filter((x) => x.id !== d.cmtDel);
      saveDraftSoon();
      return render();
    }
    if (d.kind) {
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      return;
    }
    if (d.pop) return closePop(d.pop === "ok");
    if (d.modal === "close") return ($(".modal").hidden = true);
    if (d.modal === "save") return doSave();
    if (d.modal === "save-propose") return doSave("propose");
    if (d.modal === "save-revise") return doSave("revise");
    if (d.propAct) return proposalAction(d.propAct, d.name);
    if (d.tabGo) {
      S.tab = d.tabGo;
      S.collapsed = false;
      return render();
    }
    if (d.freedom) {
      S.freedom = d.freedom;
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      return;
    }
    if (d.copy) return copy(d.copy);
    if (b.hasAttribute("data-copy-md")) return copy(root.querySelector(".result")._md || "");
    if (d.load) return loadSaved(d.load);
    const act = d.act;
    if (act === "undo") return undo();
    if (act === "redo") return redo();
    if (act === "save") return openSaveModal();
    if (act === "toggle-panel") {
      S.collapsed = !S.collapsed;
      return render();
    }
    if (act === "swap-side") {
      S.side = S.side === "right" ? "left" : "right";
      return renderPanel();
    }
    if (act === "variant-dup" || act === "variant-new") {
      const letter = String.fromCharCode(65 + S.variants.length);
      const changes = act === "variant-dup" ? clean(cur().changes) : [];
      S.variants.push(newVariant(`조합 ${letter}`, changes));
      switchVariant(S.variants.length - 1);
      toast(act === "variant-dup" ? `조합 ${letter}: 지금 것을 복사했어요. 여기서 다르게 바꿔 보세요` : `조합 ${letter}: 처음 모습에서 시작해요`);
      return;
    }
    if (act === "variant-del") {
      if (!confirm(`'${cur().name}' 조합을 지울까요?`)) return;
      [...cur().changes].reverse().filter(isDom).forEach(revertDom);
      S.variants.splice(S.active, 1);
      S.active = Math.max(0, S.active - 1);
      cur().changes.filter(isDom).forEach(applyDom);
      applyCss();
      saveDraftSoon();
      return render();
    }
    if (act === "variant-clear") {
      if (!confirm("이 조합에서 바꾼 것을 모두 비울까요? (댓글은 남아요)")) return;
      [...cur().changes].reverse().filter(isDom).forEach(revertDom);
      cur().changes = [];
      applyCss();
      saveDraftSoon();
      return render();
    }
    if (act === "move-prev") return nudge(-1);
    if (act === "move-next") return nudge(1);
    if (act === "hide") {
      S.editKey = null;
      const hidden = cur().changes.some((c) => c.type === "style" && c.selector === S.scope && c.prop === "display");
      return hidden ? resetStyle("display") : setStyle("display", "none");
    }
    if (act === "edit-text") return S.sel && startTextEdit(S.sel.el);
    if (act === "comment-here" && S.sel) {
      const r = S.sel.el.getBoundingClientRect();
      return startPointComment(S.sel.el, r.left + r.width / 2, r.top + Math.min(20, r.height / 2));
    }
  }
  root.addEventListener("click", onStudioClick);
  ovRoot.addEventListener("click", onStudioClick);
  let stepDrag = -1;
  root.addEventListener("dragstart", (e) => {
    const li = e.target.closest && e.target.closest("li.step");
    if (!li) return;
    stepDrag = +li.dataset.step;
    e.dataTransfer.effectAllowed = "move";
    li.classList.add("dragging");
  });
  root.addEventListener("dragover", (e) => {
    const li = e.target.closest && e.target.closest("li.step");
    if (stepDrag < 0 || !li) return;
    e.preventDefault();
    root.querySelectorAll("li.step").forEach((n) => n.classList.toggle("over", n === li));
  });
  root.addEventListener("drop", (e) => {
    const li = e.target.closest && e.target.closest("li.step");
    if (stepDrag < 0 || !li || !S.flow) return;
    e.preventDefault();
    const to = +li.dataset.step;
    const [moved] = S.flow.steps.splice(stepDrag, 1);
    S.flow.steps.splice(to, 0, moved);
    stepDrag = -1;
    renderPanel();
  });
  root.addEventListener("dragend", () => {
    stepDrag = -1;
    root.querySelectorAll("li.step").forEach((n) => n.classList.remove("over", "dragging"));
  });
  // 조절 막대·색 고르기: 누르기 시작할 때 새 '편집 묶음' 을 연다 (끄는 동안 바뀐 값은 한 줄로 합친다)
  // 색 판 안의 칸은 판을 연 순간의 묶음을 그대로 쓴다 (끌기·16진수 입력이 한 줄로 합쳐지게)
  root.addEventListener("pointerdown", (e) => {
    if (e.target.matches("input, select") && !e.target.closest(".picker")) S.editKey = uid("k");
  });
  root.addEventListener("focusin", (e) => {
    if (e.target.matches("input, select") && !e.target.closest(".picker")) S.editKey = uid("k");
  });
  root.addEventListener("input", (e) => {
    const t = e.target;
    const d = t.dataset;
    if (d.tokenPx) {
      t.nextElementSibling.textContent = `${t.value}px`;
      return setToken(d.tokenPx, `${t.value}px`);
    }
    if (d.styleRange) {
      const val = d.unit ? `${t.value}${d.unit}` : t.value;
      t.nextElementSibling.textContent = val;
      return setStyle(d.styleRange, val);
    }
    if (d.size) return t.value ? setStyle(d.size, `${t.value}px`) : resetStyle(d.size);
    if (d.stepText != null && S.flow) {
      S.flow.steps[+d.stepText].text = t.value;
      return;
    }
    if (t.hasAttribute("data-ai-ask")) {
      S.ai.ask = t.value;
      return;
    }
    if (t.hasAttribute("data-variant-name")) {
      cur().name = t.value.trim() || cur().name;
      renderBar();
      return saveDraftSoon();
    }
  });
  root.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.stepKind != null && S.flow) {
      const st = S.flow.steps[+t.dataset.stepKind];
      st.kind = t.value;
      if (st.kind === "nav" && !st.view) st.view = viewKey();
      return renderPanel();
    }
    if (t.dataset.stepView != null && S.flow) {
      S.flow.steps[+t.dataset.stepView].view = t.value;
      return;
    }
    if (t.hasAttribute("data-ai-auto")) {
      S.ai.auto = t.checked;
      savePref("ai-auto", S.ai.auto);
      return renderAi();
    }
    if (t.hasAttribute("data-scope")) {
      S.scope = t.value;
      S.editKey = null;
      return renderPanel();
    }
    if (t.dataset.styleSelect) {
      S.editKey = uid("k");
      if (t.value) setStyle(t.dataset.styleSelect, t.value);
      else resetStyle(t.dataset.styleSelect);
    }
    S.editKey = null;
    // 조절을 마쳤다(색 고르는 창 닫힘·막대 놓음). 이제 '바뀜' 표시를 다시 그려도 된다.
    // 글 입력칸(흐름 단계·조합 이름)은 다시 그리지 않는다: 칸을 떠나며 다음 단추를 누르는 순간 패널이 바뀌어 그 누르기가 사라졌다.
    const d = t.dataset;
    if (d.styleRange || d.styleSelect || d.tokenPx || d.size) renderPanel();
  });

  /* ---------- 단축키 ---------- */
  function onKey(e) {
    const t = e.composedPath()[0];
    if (S.editing) {
      if (S.editing.contains(e.target)) {
        e.stopPropagation(); // 앱 단축키(검색 Ctrl+K 등)가 글자 입력을 가로채지 않게
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          finishTextEdit(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finishTextEdit(false);
        }
      }
      return;
    }
    if (fromStudio(e) && t && t.matches && t.matches("textarea") && e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!$(".pop").hidden) closePop(true);
      return;
    }
    const typing = t && t.matches && (t.matches("input, textarea, select") || t.isContentEditable);
    if (typing) return;
    const handled = () => {
      e.preventDefault();
      e.stopPropagation();
    };
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === "z") return handled(), e.shiftKey ? redo() : undo();
    if ((e.ctrlKey || e.metaKey) && k === "y") return handled(), redo();
    if (e.ctrlKey || e.metaKey || e.altKey) {
      if (!(S.mode === "select" && S.sel && e.shiftKey && /^arrow/.test(k))) return;
    }
    if (!e.shiftKey) S.nudgeKey = null;
    if (k === "escape" && picker) return handled(), closePicker();
    if (k === "escape") {
      if (!$(".pop").hidden) return handled(), closePop(false);
      if (!$(".modal").hidden) return handled(), ($(".modal").hidden = true);
      if (S.sel) {
        S.sel = null;
        return handled(), render();
      }
      if (S.mode !== "browse") return handled(), setMode("browse");
      return;
    }
    if (k === "v") return handled(), setMode("browse");
    if (k === "s") return handled(), setMode("select");
    if (k === "c") return handled(), setMode("comment");
    if (k === "\\") {
      S.clean = !S.clean;
      return handled(), render();
    }
    if (/^[1-9]$/.test(k) && S.variants[+k - 1]) return handled(), switchVariant(+k - 1);
    if (S.mode === "select" && S.sel && e.shiftKey && /^arrow/.test(k)) {
      const step = e.ctrlKey || e.metaKey ? 10 : 1;
      const [bx, by] = parseTranslate(S.sel.el);
      const dx = k === "arrowleft" ? -step : k === "arrowright" ? step : 0;
      const dy = k === "arrowup" ? -step : k === "arrowdown" ? step : 0;
      if (!S.nudgeKey) ensureMovable(S.sel.el);
      S.editKey = S.nudgeKey || (S.nudgeKey = uid("k"));
      return handled(), setStyle("translate", `${bx + dx}px ${by + dy}px`);
    }
    if (S.mode === "select" && S.sel) {
      if (k === "arrowup" && S.sel.el.parentElement && S.sel.el.parentElement !== document.body) return handled(), selectEl(S.sel.el.parentElement);
      if (k === "arrowdown" && S.sel.el.firstElementChild) return handled(), selectEl(S.sel.el.firstElementChild);
      if (k === "enter") return handled(), startTextEdit(S.sel.el);
    }
  }
  window.addEventListener("keydown", onKey, true);
  // 시안·원래를 오가면 iframe(앱)만 새로 뜬다. 바깥 틀에 건 처리기는 예전 앱 것이 남으니, 앱이 사라졌으면 스스로 뗀다.
  function onTopKey(e) {
    if (!ovHost.isConnected) return TOP.removeEventListener("keydown", onTopKey, true);
    onKey(e);
  }
  function onTopResize() {
    if (!ovHost.isConnected) return TOP.removeEventListener("resize", onTopResize);
    setBarHeight();
    renderPanel();
    renderAi();
  }
  if (IN_SHELL) TOP.addEventListener("keydown", onTopKey, true);

  /* ---------- 알림 ---------- */
  let toastTimer = 0;
  function toast(text) {
    const t = $(".toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 2600);
  }

  /* ---------- 시작 ---------- */
  document.body.appendChild(ovHost);
  wirePicker();
  TOP.document.querySelectorAll("#__studio").forEach((n) => n.remove());
  TOP.document.body.appendChild(host);
  if (IN_SHELL) TOP.addEventListener("resize", onTopResize);
  refreshProposals();
  setInterval(refreshProposals, 2500);
  try {
    const hint = sessionStorage.getItem("studio-hint");
    if (hint) {
      sessionStorage.removeItem("studio-hint");
      setTimeout(() => toast(hint), 1200);
    }
  } catch { /* 안내만 못 보인다 */ }
  if (INFO.ctx) S.tab = "proposals";
  render();
  (async () => {
    // 앱이 첫 화면을 다 그린 뒤에 불러와야 글자·순서 변경이 제자리를 찾는다
    if (APP.ready) { try { await APP.ready(); } catch { /* 기다리기만 못 한다 */ } } else await sleep(600);
    await new Promise((r) => setTimeout(r, 400));
    const load = PARAMS.get("load");
    if (load) {
      await loadSaved(load);
    } else {
      try {
        const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
        if (draft && (draft.comments?.length || draft.variants?.some((v) => v.changes.length))) {
          hydrate(draft);
          S.dirty = true;
          toast("저장하지 않은 지난 작업을 이어서 열었어요 (바뀐 것 탭에서 비울 수 있어요)");
        }
      } catch { /* 이어 하기만 안 된다 */ }
    }
    if (PARAMS.get("variant")) switchVariant(+PARAMS.get("variant") - 1);
    if (PARAMS.get("theme")) applyAppTheme(PARAMS.get("theme"));
    if (PARAMS.get("view") && APP.switchView) APP.switchView(PARAMS.get("view"));
    render();
  })();

  /* ---------- 도구 화면 스타일 (Shadow DOM 안) ---------- */
  function STUDIO_CSS() {
    return `
      :host { all: initial; }
      * { box-sizing: border-box; }
      [hidden] { display: none !important; }
      button, input, select, textarea { font: inherit; color: inherit; }
      .ov, .bar, .panel, .pop, .modal, .toast, .picker, .ai {
        /* Anthropic 브랜드: Dark #141413 · Light #faf9f5 · Mid Gray #b0aea5 · Light Gray #e8e6dc
           강조 Orange #d97757(주) · Blue #6a9bcc · Green #788c5d. 제목 Poppins, 본문 Lora (한글은 이어지는 대체 글꼴).
           bg2·bg3·line 은 Dark 에 Light 를 6·11·18% 섞은 층. 글자 대비는 모두 4.5:1 이상으로 맞췄다
           (Green 만 bg3 위 작은 글자에서 3.95:1 이라 --s-ok-hi 로 밝힌 판을 쓴다). 강조색 위 글자는 Dark(5.0~6.3:1). */
        /* 'Studio …' 이름으로 따로 선언한다: 앱이 Lora·Poppins 를 쓰면 같은 이름으로 덮었을 때 앱 글자까지 바뀐다 */
        --s-head: "Studio Poppins", "Poppins", Arial, "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
        --s-body: "Studio Lora", "Lora", Georgia, "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", serif;
        font: 12.5px/1.5 var(--s-body);
        --s-bg: #141413; --s-bg2: #1e1e1c; --s-bg3: #2a2926; --s-line: #393834; --s-text: #faf9f5; --s-soft: #b0aea5;
        --s-acc: #d97757; --s-acc-hi: #e8957a; --s-on-acc: #141413; --s-acc2: #6a9bcc; --s-warn: #6a9bcc;
        --s-ok: #788c5d; --s-ok-hi: #9aae7c; --s-gray: #e8e6dc; --s-well: #0e0e0d;
        color: var(--s-text);
      }
      .ov { position: fixed; inset: 0; pointer-events: none; z-index: 2147483000; }
      .hover, .selbox, .dropline, .drag-rect { position: fixed; left: 0; top: 0; }
      .hover { outline: 1.5px solid var(--s-acc); background: rgba(217,119,87,.08); }
      .selbox { outline: 2px solid var(--s-acc); }
      .tag { position: absolute; left: -2px; top: -20px; background: var(--s-acc); color: var(--s-on-acc); padding: 1px 6px; border-radius: 4px 4px 4px 0;
             font: 11px/18px ui-monospace, Consolas, monospace; white-space: nowrap; max-width: 420px; overflow: hidden; text-overflow: ellipsis; }
      .selbox .tag { left: 74px; }
      .grip { pointer-events: auto; position: absolute; left: -2px; top: -22px; height: 20px; border: 0; border-radius: 4px; background: var(--s-text); color: var(--s-bg);
              font-size: 11px; padding: 0 6px; cursor: grab; box-shadow: 0 1px 4px rgba(0,0,0,.3); }
      .grip:active { cursor: grabbing; }
      /* 범위 칩은 아래 왼쪽: 좁은 요소(접힌 사이드바 단추 60px)에서 위쪽 '⠿ 순서' 손잡이를 덮었다 */
      .scopechip { pointer-events: auto; position: absolute; left: -2px; bottom: -22px; height: 20px; border: 0; border-radius: 4px; background: var(--s-text); color: var(--s-bg);
              font-size: 11px; padding: 0 7px; cursor: pointer; box-shadow: 0 1px 4px rgba(0,0,0,.3); white-space: nowrap; }
      .busy { position: fixed; left: 50%; top: 42%; transform: translate(-50%, -50%); display: flex; gap: 10px; align-items: center; padding: 14px 18px;
              background: rgba(20,20,19,.92); color: var(--s-text); border-radius: 12px; font: 13px var(--s-body); box-shadow: 0 10px 30px rgba(0,0,0,.3); }
      .spin2 { width: 16px; height: 16px; border: 2px solid #fff4; border-top-color: #fff; border-radius: 50%; animation: s-spin 0.8s linear infinite; }
      .resize { pointer-events: auto; position: absolute; right: -7px; bottom: -7px; width: 14px; height: 14px; background: var(--s-text); border: 2px solid var(--s-acc);
                border-radius: 3px; cursor: nwse-resize; }
      .dropline { background: var(--s-acc); border-radius: 2px; box-shadow: 0 0 0 2px rgba(255,255,255,.8); }
      .drag-rect { border: 1.5px dashed var(--s-warn); background: rgba(106,155,204,.08); }
      .pins { position: fixed; inset: 0; }
      .pin { pointer-events: auto; position: fixed; left: 0; top: 0; width: 22px; height: 22px; border-radius: 11px 11px 11px 2px; border: 2px solid var(--s-text);
             background: var(--s-warn); color: var(--s-on-acc); font-weight: 700; font-size: 11px; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,.3); padding: 0; }
      .pin.done { background: var(--s-soft); }
      .region { position: fixed; left: 0; top: 0; border: 1.5px dashed var(--s-warn); background: rgba(106,155,204,.08); border-radius: 4px; }
      .region.done { border-color: var(--s-soft); background: transparent; }

      .bar { position: fixed; left: 50%; bottom: 14px; transform: translateX(-50%); z-index: 2147483002; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
             width: max-content;
             justify-content: center; max-width: calc(100vw - 24px); padding: 6px; background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 14px;
             box-shadow: 0 10px 30px rgba(0,0,0,.35); }
      .grp { display: flex; gap: 2px; padding: 2px; background: var(--s-bg2); border-radius: 10px; }
      .bar button { border: 0; background: transparent; padding: 6px 10px; border-radius: 8px; cursor: pointer; color: var(--s-soft); white-space: nowrap; }
      .bar button:hover { background: var(--s-bg3); color: var(--s-text); }
      .bar .mode b { font-weight: 400; margin-right: 5px; }
      .bar kbd { margin-left: 6px; font: 10px ui-monospace, monospace; opacity: .55; }
      .bar .on { background: var(--s-acc) !important; color: var(--s-on-acc) !important; }
      .bar .icon { min-width: 30px; padding: 6px 8px; }
      .bar .vpill { min-width: 28px; font-weight: 700; }
      .bar .save { background: var(--s-acc); color: var(--s-on-acc); font-weight: 600; }
      .bar .save:hover { background: var(--s-acc-hi); }
      .bar.dock-right { left: calc(50% - 177px); max-width: calc(100vw - 378px); }
      .bar.dock-left { left: calc(50% + 177px); max-width: calc(100vw - 378px); }
      /* 안내 글은 막대 너비를 늘리지 않는다 (단추 줄 너비에 맞춰 줄바꿈) */
      .hint { contain: inline-size; flex-basis: 100%; text-align: center; color: var(--s-soft); font-size: 11px; padding: 0 4px 2px; }

      .panel { position: fixed; top: 12px; right: 12px; bottom: 12px; width: 330px; z-index: 2147483001; display: flex; flex-direction: column;
               background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 14px; box-shadow: 0 12px 40px rgba(0,0,0,.4); overflow: hidden; }
      .panel.left { right: auto; left: 12px; }
      @media (max-width: 760px) { .panel { left: 8px; right: 8px; width: auto; top: auto; height: 46vh; bottom: calc(var(--barh, 76px) + 20px); } }
      /* 좁은 창: AI 는 떠 있는 알약 대신 아래 막대의 ✨ 단추로. 펼친 카드는 막대 위에 */
      .ai-btn { display: none; }
      @media (max-width: 760px) {
        .ai-btn { display: inline-block; }
        .ai:not(.open) { display: none; }
        .ai.open { bottom: calc(var(--barh, 76px) + 24px); left: 12px !important; }
        .ai-card { width: min(290px, calc(100vw - 24px)); }
      }
      header { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px 6px; }
      .brand { font: 600 14px/1.3 var(--s-head); letter-spacing: -0.01em; }
      .brand small { display: block; font-weight: 400; color: var(--s-soft); font-size: 11px; }
      nav { display: flex; gap: 2px; padding: 0 8px 8px; border-bottom: 1px solid var(--s-line); }
      .tab { flex: 1; border: 0; background: transparent; color: var(--s-soft); padding: 6px 2px; border-radius: 7px; cursor: pointer; white-space: nowrap; font-size: 12px; }
      .tab.on { background: var(--s-bg3); color: var(--s-text); font-weight: 600; }
      .tab i, h4 i { font-style: normal; font-size: 10px; background: var(--s-acc); color: var(--s-on-acc); border-radius: 8px; padding: 0 5px; }
      .body { flex: 1; overflow: auto; padding: 4px 12px 16px; }
      section { padding: 10px 0; border-bottom: 1px solid var(--s-bg3); }
      section:last-child { border-bottom: 0; }
      h4 { margin: 0 0 8px; font: 600 12px/1.4 var(--s-head); }
      h4 small { font-weight: 400; color: var(--s-soft); margin-left: 4px; }
      code { font: 11px ui-monospace, Consolas, monospace; color: var(--s-acc2); }
      .small { color: var(--s-soft); font-size: 11.5px; margin: 6px 0; }
      .empty { padding: 14px 2px; color: var(--s-soft); }
      .empty b { color: var(--s-text); }
      /* :where 로 감싸 우선순위를 0 으로 둔다. 그래야 .tab·.mini 같은 개별 단추 모양이 이긴다. */
      :where(.panel, .pop, .modal, .picker, .ai) button { cursor: pointer; border: 1px solid var(--s-line); background: var(--s-bg2); border-radius: 7px; padding: 5px 9px; }
      :where(.panel, .pop, .modal, .picker, .ai) button:hover { border-color: #55534e; }
      button.primary { background: var(--s-acc) !important; border-color: var(--s-acc) !important; color: var(--s-on-acc); font-weight: 600; }
      button.danger { color: var(--s-warn); margin-top: 8px; }
      .icon { border: 0; background: transparent; color: var(--s-soft); cursor: pointer; font-size: 14px; }
      .mini { border: 0; background: transparent; color: var(--s-acc2); cursor: pointer; font-size: 13px; padding: 0 4px; }
      .seg { display: flex; gap: 3px; background: var(--s-bg2); padding: 3px; border-radius: 9px; }
      .seg button { flex: 1; border: 0 !important; background: transparent !important; color: var(--s-soft); padding: 5px 4px !important; border-radius: 7px !important; }
      .seg button.on { background: var(--s-bg3) !important; color: var(--s-text); font-weight: 600; }
      .swatch { width: 26px; height: 22px; border: 1px solid var(--s-line) !important; border-radius: 5px !important; padding: 0 !important;
                background: var(--c) !important; cursor: pointer; }
      .swatch.big { width: 42px; height: 30px; }
      .swatch.clear { background: repeating-conic-gradient(#888 0 25%, #ccc 0 50%) 0 0 / 8px 8px !important; }
      .accentrow { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
      .hexv { color: var(--s-soft); }
      .picker { position: fixed; z-index: 2147483006; width: 240px; background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 12px;
                padding: 10px; box-shadow: 0 14px 40px rgba(0,0,0,.5); display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }
      .ptitle { font: 11px ui-monospace, monospace; color: var(--s-soft); }
      .sv { position: relative; height: 150px; border-radius: 8px; cursor: crosshair; touch-action: none;
            background: linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, var(--hue)); }
      .hue { position: relative; height: 14px; border-radius: 7px; cursor: ew-resize; touch-action: none;
             background: linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00); }
      .sv .knob, .hue .knob { position: absolute; width: 14px; height: 14px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px #0008;
                              transform: translate(-50%, -50%); pointer-events: none; }
      .hue .knob { top: 50%; }
      .prow { display: flex; gap: 6px; align-items: center; } .prow.end { justify-content: flex-end; }
      .pfrom, .pv { width: 22px; height: 22px; border-radius: 6px; border: 1px solid var(--s-line); flex: none; }
      .pfrom { cursor: pointer; }
      .phex { flex: 1; width: 0; min-width: 0; background: var(--s-bg2); border: 1px solid var(--s-line); border-radius: 6px; padding: 4px 6px; font: 12px ui-monospace, monospace; }
      .tok { display: grid; grid-template-columns: 26px 1fr auto auto; gap: 8px; align-items: center; padding: 3px 4px; border-radius: 7px; }
      .tok.changed, .ctl.changed { background: rgba(217,119,87,.14); }
      .tname code { display: block; color: var(--s-soft); font-size: 10px; }
      .tval { font: 10.5px ui-monospace, monospace; color: var(--s-soft); }
      .ctl { display: grid; grid-template-columns: 74px 1fr auto auto; gap: 6px; align-items: center; padding: 3px 4px; border-radius: 7px; min-height: 30px; }
      .ctl.color { grid-template-columns: 74px 26px 1fr auto; }
      .ctl > span:first-child { color: var(--s-soft); }
      .ctl > span code { display: block; font-size: 10px; }
      .ctl input[type=range] { width: 100%; accent-color: var(--s-acc); }
      .ctl output { font: 11px ui-monospace, monospace; color: var(--s-soft); min-width: 40px; text-align: right; }
      .ctl select, select.wide, input.wide, .size input { background: var(--s-bg2); border: 1px solid var(--s-line); border-radius: 6px; padding: 4px 6px; }
      .ctl.size { grid-template-columns: 74px auto auto auto auto auto auto; justify-content: start; }
      .size input { width: 64px; }
      select.wide, input.wide { width: 100%; }
      .crumbs { display: flex; flex-wrap: wrap; gap: 2px; align-items: center; padding: 8px 0 4px; }
      .crumbs button { border: 0 !important; background: transparent; color: var(--s-soft); padding: 2px 4px !important; font: 11px ui-monospace, monospace; border-radius: 4px; }
      .crumbs button.on { background: var(--s-acc) !important; color: var(--s-on-acc); }
      .crumbs i { color: #6b6a65; font-style: normal; }
      .selinfo { padding: 4px 0 8px; }
      .selinfo b { font: 600 12px ui-monospace, monospace; }
      .selinfo span { color: var(--s-soft); margin-left: 6px; }
      .selinfo .txt { color: var(--s-soft); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .rules { margin-top: 6px; color: var(--s-soft); }
      .rules code { display: block; margin-top: 4px; line-height: 1.6; word-break: break-all; }
      .acts { display: flex; flex-wrap: wrap; gap: 5px; }
      .cmt { padding: 9px 4px; border-bottom: 1px solid var(--s-bg3); }
      .cmt.done { opacity: .55; }
      .chead { display: flex; gap: 6px; align-items: center; }
      .num { width: 20px; height: 20px; border-radius: 10px; background: var(--s-warn); color: var(--s-on-acc); font-weight: 700; display: grid; place-items: center; font-size: 11px; flex: none; }
      .kind { font-size: 10.5px; padding: 1px 6px; border-radius: 6px; background: var(--s-bg3); }
      .k-fix { color: var(--s-acc-hi); } .k-idea { color: var(--s-gray); } .k-keep { color: var(--s-ok-hi); } .k-question { color: var(--s-acc2); }
      .where { color: var(--s-soft); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .ctext { margin: 6px 0; white-space: pre-wrap; }
      .cacts { display: flex; gap: 4px; }
      .cacts button { padding: 2px 8px !important; font-size: 11px; }
      .chg { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; padding: 6px 2px; border-bottom: 1px solid var(--s-bg3); }
      .chg small { color: var(--s-soft); word-break: break-all; }
      .vals { font: 11px ui-monospace, monospace; color: var(--s-soft); word-break: break-all; }
      .vals .to { color: var(--s-text); }
      .dot { width: 14px; height: 14px; border-radius: 4px; background: var(--c); border: 1px solid #fff3; display: inline-block; }
      .vrow { display: flex; gap: 4px; }
      .saved { display: grid; gap: 4px; }
      .srow { text-align: left; display: grid; }
      .srow small { color: var(--s-soft); }

      .pop { position: fixed; z-index: 2147483003; width: 320px; background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 12px; padding: 10px;
             box-shadow: 0 12px 40px rgba(0,0,0,.45); }
      .phead { font: 600 13px/1.4 var(--s-head); margin-bottom: 8px; }
      .phead small { font-weight: 400; color: var(--s-soft); margin-left: 4px; }
      .kinds { display: flex; gap: 4px; margin-bottom: 8px; }
      .kinds button { padding: 3px 8px !important; font-size: 11.5px; }
      .kinds button.on { background: var(--s-warn) !important; border-color: var(--s-warn) !important; color: var(--s-on-acc); }
      textarea, .modal input { width: 100%; background: var(--s-bg2); border: 1px solid var(--s-line); border-radius: 8px; padding: 7px 8px; resize: vertical; }
      textarea:focus, input:focus, select:focus { outline: 2px solid var(--s-acc); outline-offset: -1px; }
      .pacts, .macts { display: flex; gap: 6px; align-items: center; margin-top: 8px; }
      .sp { flex: 1; }
      .chk { display: flex; gap: 4px; align-items: center; color: var(--s-soft); }
      .modal { position: fixed; inset: 0; z-index: 2147483004; background: rgba(0,0,0,.45); display: grid; place-items: center; }
      .modal .card { width: min(460px, calc(100vw - 32px)); background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 14px; padding: 18px; display: grid; gap: 10px; }
      .modal h3 { margin: 0; font: 600 16px/1.3 var(--s-head); }
      .modal label { display: grid; gap: 4px; color: var(--s-soft); }
      .modal select { background: var(--s-bg2); border: 1px solid var(--s-line); border-radius: 8px; padding: 6px; }
      .seg.two button { padding: 7px !important; }
      .macts { justify-content: flex-end; }
      .result { border-top: 1px solid var(--s-line); padding-top: 10px; }
      .result p { margin: 4px 0; }
      .say { display: flex; gap: 6px; align-items: center; background: var(--s-bg2); border-radius: 8px; padding: 6px 8px; margin: 4px 0; }
      .say code { flex: 1; color: var(--s-text); font-size: 12px; }
      .flowbox .flowsrc { color: var(--s-soft); display: grid; gap: 6px; margin-bottom: 6px; }
      .flowbox .flowsrc button { justify-self: start; }
      ol.flow { list-style: none; margin: 6px 0; padding: 0; display: grid; gap: 4px; }
      /* 단계 글이 길어 잘리지 않게: 위 줄은 [끌기·번호·종류·빼기], 아래 줄은 글칸을 통째로 */
      li.step > input, li.step > select[data-step-view] { grid-column: 1 / -1; }
      li.step { display: grid; grid-template-columns: 14px 16px 1fr auto; gap: 4px 6px; align-items: center; background: var(--s-bg2); border: 1px solid var(--s-line);
                border-radius: 8px; padding: 4px 6px; }
      li.step.over { border-color: var(--s-acc); } li.step.dragging { opacity: .4; }
      li.step b { color: var(--s-acc2); font-size: 11px; } .sgrip { cursor: grab; color: var(--s-soft); }
      li.step select, li.step input { background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 6px; padding: 3px 5px; min-width: 0; }
      .flowadd { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
      .flowadd button { padding: 2px 7px !important; font-size: 11px; }
      .ai { position: fixed; bottom: 16px; z-index: 2147483002; }
      .ai.open { bottom: 104px; }
      .ai-pill { border: 1px solid var(--s-line); background: var(--s-bg); color: var(--s-text); border-radius: 999px; padding: 7px 12px; cursor: pointer;
                 box-shadow: 0 6px 20px rgba(0,0,0,.3); display: flex; gap: 6px; align-items: center; font-weight: 600; }
      .ai-pill i.on { width: 7px; height: 7px; border-radius: 50%; background: var(--s-ok); box-shadow: 0 0 6px var(--s-ok); }
      .ai-card { position: relative; width: 290px; background: var(--s-bg); border: 1px solid var(--s-line); border-radius: 14px; padding: 10px 12px;
                 box-shadow: 0 12px 34px rgba(0,0,0,.4); display: grid; gap: 6px; }
      .ai-card.pop { animation: ai-pop .45s cubic-bezier(.2,1.6,.4,1); }
      @keyframes ai-pop { 0% { transform: scale(.6) translateY(16px); opacity: 0; } 100% { transform: none; opacity: 1; } }
      .ai-head { display: flex; align-items: center; gap: 6px; }
      .ai-head b { flex: 1; } .ai-head .cnt { color: var(--s-soft); font-size: 11px; }
      .spark { display: inline-block; animation: twinkle 1.6s ease-in-out infinite; }
      @keyframes twinkle { 50% { transform: scale(1.25) rotate(12deg); filter: brightness(1.4); } }
      .dots { display: inline-flex; gap: 3px; } .dots i { width: 4px; height: 4px; border-radius: 50%; background: var(--s-acc2); animation: dot 1s infinite; }
      .dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
      @keyframes dot { 50% { transform: translateY(-4px); opacity: .4; } }
      .ai-title { font: 600 14px/1.35 var(--s-head); } .ai-why { color: var(--s-soft); }
      .ai-chg { font-size: 11px; color: var(--s-soft); background: var(--s-well); border-radius: 6px; padding: 6px 8px; max-height: 92px; overflow: auto; }
      .burst { position: absolute; left: 22px; top: 18px; pointer-events: none; }
      .burst i { position: absolute; font-style: normal; color: var(--s-acc); font-size: 12px; opacity: 0; animation: burst .9s ease-out forwards; }
      .burst i:nth-child(1) { --dx: -34px; --dy: -30px; } .burst i:nth-child(2) { --dx: 0px; --dy: -42px; animation-delay: .05s; }
      .burst i:nth-child(3) { --dx: 36px; --dy: -28px; animation-delay: .1s; } .burst i:nth-child(4) { --dx: 46px; --dy: 4px; animation-delay: .04s; }
      .burst i:nth-child(5) { --dx: -44px; --dy: 6px; animation-delay: .08s; } .burst i:nth-child(6) { --dx: 20px; --dy: -50px; color: var(--s-acc2); animation-delay: .12s; }
      .burst i:nth-child(7) { --dx: -18px; --dy: -46px; color: var(--s-ok-hi); animation-delay: .02s; }
      @keyframes burst { 0% { transform: translate(0,0) scale(.4); opacity: 1; } 100% { transform: translate(var(--dx), var(--dy)) scale(1.1) rotate(90deg); opacity: 0; } }
      .ctx { align-items: center; }
      .ctxlabel { color: var(--s-soft); font-size: 11px; padding: 0 6px; }
      .ctx button[disabled] { cursor: default; }
      .spin { display: inline-block; width: 10px; height: 10px; margin-right: 6px; border: 2px solid #fff4; border-top-color: #fff; border-radius: 50%; animation: s-spin 0.8s linear infinite; vertical-align: -1px; }
      @keyframes s-spin { to { transform: rotate(360deg); } }
      .prop { border: 1px solid var(--s-line); border-radius: 10px; padding: 10px; margin: 10px 0; background: var(--s-bg2); }
      .prop.viewing { border-color: var(--s-acc); }
      .phead2 { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
      .st { font-size: 10.5px; padding: 1px 7px; border-radius: 6px; background: var(--s-bg3); white-space: nowrap; }
      .st-run { color: var(--s-acc-hi); } .st-ok { color: var(--s-ok-hi); } .st-bad { color: var(--s-acc-hi); } .st-done { color: var(--s-soft); }
      .prop .meta { color: var(--s-soft); font-size: 11px; margin: 3px 0 6px; }
      .act { font: 11px/1.5 ui-monospace, Consolas, monospace; color: var(--s-soft); background: var(--s-well); border-radius: 6px; padding: 6px 8px; max-height: 160px; overflow: auto; }
      .act div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .res { white-space: pre-wrap; background: var(--s-well); border-radius: 6px; padding: 8px; margin: 6px 0; max-height: 220px; overflow: auto; }
      .files { display: flex; flex-wrap: wrap; gap: 4px 10px; margin: 6px 0; font-size: 11px; }
      .files i { font-style: normal; } .plus { color: var(--s-ok-hi); } .minus { color: var(--s-acc-hi); }
      .pacts2 { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
      .pacts2 button.danger { margin-top: 0; }
      button.good { background: var(--s-ok) !important; border-color: var(--s-ok) !important; color: var(--s-on-acc); font-weight: 600; }
      .err { color: var(--s-acc-hi); margin: 6px 0; }
      .modal .card.wide { width: min(900px, calc(100vw - 32px)); max-height: calc(100vh - 48px); }
      pre.diff { margin: 0; overflow: auto; max-height: calc(100vh - 180px); background: var(--s-well); border-radius: 8px; padding: 10px; font: 11.5px/1.5 ui-monospace, Consolas, monospace; white-space: pre; }
      pre.diff .a { color: var(--s-ok-hi); } pre.diff .d { color: var(--s-acc-hi); } pre.diff .h { color: var(--s-acc2); }
      .toast { position: fixed; left: 50%; bottom: 96px; transform: translateX(-50%); z-index: 2147483005; background: var(--s-gray); color: var(--s-bg); padding: 8px 14px;
               border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.3); max-width: calc(100vw - 32px); }
    `;
  }
})();
