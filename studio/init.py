r"""앱을 읽어 스튜디오 개인화 설정의 '초안' 을 만든다.

    python -m studio init --project <앱 저장소>          초안 만들기 (이미 있으면 analysis.md 만 새로 쓴다)
    python -m studio init --project <앱 저장소> --force  있는 설정을 초안으로 덮어쓴다 (예전 것은 *.bak)

만드는 것 (<앱 저장소>/.claude/design-studio/)
    studio.app.json   띄우는 법·화면 폴더·요청 규칙·확인 명령
    studio.app.js     화면 이름·테마·색 토큰·화면 바꾸기 (window.__STUDIO_APP__)
    context.md        Claude 에게 줄 앱 규칙 (찾은 사실 + Claude 가 채울 칸)
    analysis.md       무엇을 찾았고 무엇이 불확실한지 — Claude 가 이걸 보고 앱 코드를 읽어 다듬는다

이 스크립트는 '확실한 것' 만 채운다. 앱마다 다른 판단(어떤 쓰기 요청을 진짜로 넘길지, 가짜 데이터가 필요한지,
화면 이동을 어떻게 하는지)은 analysis.md 의 '확인할 것' 으로 남기고, 스킬 안내(GUIDE.md)에 따라 Claude 가 정한다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from .config import ADAPTER_DIR, STUDIO_HOME, STUDIO_VERSION

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".design-studio", ".claude", "dist", "build", "out",
        ".next", ".nuxt", "coverage", "site-packages", ".idea", ".vscode", "tools", "tests", "test", "docs"}
WEB_NAMES = {"web": 5, "public": 4, "static": 4, "www": 4, "site": 3, "frontend": 3, "client": 3, "app": 2, "src": 1, "ui": 3}
BUNDLERS = ("vite", "webpack", "next", "react-scripts", "parcel", "@angular/cli", "nuxt", "svelte-kit", "@sveltejs/kit", "astro")
COLOR = re.compile(r"^(#[0-9a-f]{3,8}|rgba?\(|hsla?\(|oklch\(|oklab\(|color\(|lab\(|lch\()", re.I)
IGNORE_HOSTS = ("localhost", "127.0.0.1", "www.w3.org", "schema.org", "json-schema.org", "example.com", "fonts.googleapis.com",
                "fonts.gstatic.com", "github.com/", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com")


def walk(root: Path, exts: tuple[str, ...], limit: int = 4000):
    n = 0
    for p in root.rglob("*"):
        rel = p.relative_to(root).parts
        if any(part in SKIP or part.startswith(".") and part not in (".",) for part in rel[:-1]):
            continue
        if p.is_file() and p.suffix.lower() in exts:
            yield p
            n += 1
            if n >= limit:
                return


def read(p: Path, limit: int = 2_000_000) -> str:
    try:
        if p.stat().st_size > limit:
            return ""
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------- 찾기 ----------
def find_web_root(proj: Path) -> tuple[Path | None, list[str]]:
    notes = []
    cands = []
    for idx in walk(proj, (".html",)):
        if idx.name != "index.html":
            continue
        d = idx.parent
        depth = len(d.relative_to(proj).parts)
        if depth > 3:
            continue
        assets = sum(1 for _ in walk(d, (".css", ".js"), 200))
        score = WEB_NAMES.get(d.name.lower(), 0) * 10 + min(assets, 30) - depth * 2
        cands.append((score, d))
    cands.sort(key=lambda x: -x[0])
    if not cands:
        notes.append("index.html 을 못 찾았어요. 화면 폴더(webRoot)를 직접 정해 주세요.")
        return None, notes
    best = cands[0][1]
    if best == proj:
        notes.append("index.html 이 저장소 맨 위에 있어요. 스튜디오는 화면 폴더가 하위 폴더여야 시안 권한을 좁힐 수 있어요 "
                     "(시안은 끄고 쓰거나, 화면 파일을 web/ 같은 폴더로 옮기는 것을 사용자와 상의).")
        sub = [d for _, d in cands if d != proj]
        return (sub[0] if sub else None), notes
    if len(cands) > 1:
        notes.append("index.html 후보가 여럿이에요: " + ", ".join(d.relative_to(proj).as_posix() or "." for _, d in cands[:5]))
    return best, notes


def detect_stack(proj: Path) -> dict:
    info: dict = {"kind": "static", "launch": None, "notes": [], "bundler": None, "python_server": None}
    pkg = proj / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(read(pkg))
        except json.JSONDecodeError:
            data = {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        info["name"] = data.get("name")
        bundler = next((b for b in BUNDLERS if b in deps), None)
        scripts = data.get("scripts") or {}
        script = next((s for s in ("dev", "start", "serve") if s in scripts), None)
        if bundler:
            info.update(kind="bundler", bundler=bundler)
            info["notes"].append(f"번들러({bundler})를 써요. 화면 열기·만지기·댓글·저장은 되지만, URL 과 소스 파일이 1:1 이 아니라 "
                                 "시안(복사본 고치기)은 꺼 두고(\"proposals\": false) 저장본을 Claude Code 로 반영해요.")
        if script:
            info["launch"] = ["npm", "run", script, "--", "--port", "{port}"]
            info["kind"] = info["kind"] if bundler else "node"
            info["notes"].append(f"`npm run {script}` 이 `--port` 를 받는지 확인해 주세요: {scripts[script]}")
    py_hits = []
    for f in walk(proj, (".py",), 600):
        t = read(f, 600_000)
        rel = f.relative_to(proj).as_posix()
        if re.search(r"\bFastAPI\(", t):
            py_hits.append(("fastapi", rel, t))
        elif re.search(r"\bFlask\(__name__", t):
            py_hits.append(("flask", rel, t))
        elif re.search(r"(ThreadingHTTPServer|HTTPServer|BaseHTTPRequestHandler|SimpleHTTPRequestHandler)", t) and "def do_GET" in t:
            py_hits.append(("http.server", rel, t))
    if py_hits and info["kind"] in ("static",):
        kind, rel, t = py_hits[0]
        mod = rel[:-3].replace("/", ".")
        info["python_server"] = {"kind": kind, "file": rel}
        if kind == "fastapi":
            var = (re.search(r"^(\w+)\s*=\s*FastAPI\(", t, re.M) or [None, "app"])[1]
            info.update(kind="python", launch=["{venv_python}", "-m", "uvicorn", f"{mod}:{var}", "--host", "127.0.0.1", "--port", "{port}"])
        elif kind == "flask":
            info.update(kind="python", launch=["{venv_python}", "-m", "flask", "--app", mod, "run", "--port", "{port}"])
        else:
            info.update(kind="python-custom")
            handler = (re.search(r"class\s+(\w+)\((?:[\w.]*)(?:BaseHTTPRequestHandler|SimpleHTTPRequestHandler)\)", t) or [None, None])[1]
            info["python_server"]["handler"] = handler
            info["notes"].append(f"직접 만든 파이썬 HTTP 서버예요({rel}{', ' + handler if handler else ''}). "
                                 "포트를 정해 띄우는 런처가 필요해요: templates/launcher_python.py 를 .claude/design-studio/run_demo.py 로 "
                                 "복사해 그 서버를 띄우게 고쳐 주세요.")
    return info


def css_files(web: Path) -> list[Path]:
    return sorted(walk(web, (".css",), 200), key=lambda p: (len(p.parts), p.name))


def parse_themes_tokens(web: Path) -> tuple[list[dict], OrderedDict, list[str]]:
    """테마(선택자)와 :root 토큰(이름→값)."""
    themes: OrderedDict[str, dict] = OrderedDict()
    tokens: OrderedDict[str, str] = OrderedDict()
    notes = []
    attr_names = Counter()
    for f in css_files(web):
        text = re.sub(r"/\*.*?\*/", "", read(f), flags=re.S)
        for m in re.finditer(r"([^{}@;]+)\{([^{}]*)\}", text):
            sel, body = m.group(1).strip(), m.group(2)
            props = re.findall(r"(--[\w-]+)\s*:\s*([^;]+);?", body)
            if not props:
                continue
            for part in [x.strip() for x in sel.split(",")]:
                base = re.fullmatch(r"(:root|html)", part)
                attr = re.fullmatch(r"(?::root|html)?\[(data-[\w-]+)=[\"']?([\w-]+)[\"']?\]", part)
                cls = re.fullmatch(r"(?::root|html)?\.([\w-]+)", part)
                if base:
                    for k, v in props:
                        tokens.setdefault(k, v.strip())
                elif attr:
                    attr_names[attr.group(1)] += 1
                    themes.setdefault(attr.group(2), {"key": attr.group(2), "attr": attr.group(1), "value": attr.group(2)})
                elif cls and re.search(r"(^|-)(dark|light|night|day|theme|contrast|dim)($|-)", cls.group(1)):
                    themes.setdefault(cls.group(1), {"key": cls.group(1), "class": cls.group(1)})
        if re.search(r"prefers-color-scheme\s*:\s*dark", text):
            notes.append(f"{f.relative_to(web).as_posix()} 에 prefers-color-scheme: dark 가 있어요. 스튜디오의 테마 단추로는 못 바꿔요(브라우저 설정을 따름).")
    out = []
    attr = attr_names.most_common(1)[0][0] if attr_names else None
    if themes:
        if attr:
            out.append({"key": "default", "label": "기본", "selector": f":root:not([{attr}])"})
        else:
            classes = ",".join(f".{t['class']}" for t in themes.values() if "class" in t)
            out.append({"key": "default", "label": "기본", "selector": f":root:not({classes})"})
        for t in themes.values():
            if "attr" in t:
                out.append({"key": t["key"], "label": t["key"], "selector": f':root[{t["attr"]}="{t["value"]}"]'})
            else:
                out.append({"key": t["key"], "label": t["key"], "selector": f":root.{t['class']}"})
    return out, tokens, notes


def group_tokens(tokens: OrderedDict) -> tuple[list, list]:
    groups: OrderedDict[str, list] = OrderedDict((g, []) for g in ("바탕", "선", "글자", "강조", "상태", "기타"))
    sizes = []
    rules = [("바탕", r"bg|background|surface|canvas|panel|card"), ("선", r"border|line|divider|outline|stroke"),
             ("글자", r"text|fg|ink|foreground|muted"), ("강조", r"accent|primary|brand|highlight|link"),
             ("상태", r"red|green|amber|yellow|blue|violet|purple|danger|success|warn|error|info")]
    for name, value in tokens.items():
        v = value.strip()
        if COLOR.match(v) or (v.startswith("var(") and not re.search(r"radius|space|gap|size|shadow|font|width", name)):
            g = next((g for g, pat in rules if re.search(pat, name, re.I)), "기타")
            groups[g].append([name, name[2:]])
        elif re.fullmatch(r"-?[\d.]+px", v) and re.search(r"radius|space|gap|pad|round", name, re.I):
            sizes.append([name, name[2:], 0, max(48, int(float(v[:-2]) * 2))])
    return [[g, rows[:30]] for g, rows in groups.items() if rows], sizes[:10]


def find_views(web: Path) -> tuple[str | None, OrderedDict]:
    """화면 이동 단추의 속성(data-view 등)과 화면 키. 이름표는 HTML 의 단추 글자에서만 (JS 에서 뽑으면 코드 조각이 섞인다)."""
    attrs = ("data-view", "data-page", "data-screen", "data-route", "data-tab")
    counts = Counter()
    keys: dict[str, OrderedDict] = {a: OrderedDict() for a in attrs}
    files = sorted(walk(web, (".html", ".js", ".jsx", ".tsx", ".vue", ".svelte"), 400), key=lambda f: f.suffix != ".html")
    for f in files:
        t = read(f, 3_000_000)
        for attr in attrs:
            for m in re.finditer(attr + r"=[\"']([\w-]+)[\"']", t):
                counts[attr] += 1
                label = ""
                if f.suffix == ".html":
                    tail = re.sub(r"<[^>]+>", " ", t[m.end():m.end() + 400].split("</button>")[0].split("</a>")[0])
                    words = re.sub(r"(\s+\d+)+$", "", re.sub(r"\s+", " ", tail.split(">", 1)[-1]).strip())  # 뒤의 배지 숫자 빼기
                    if words and len(words) <= 16 and not re.search(r"[(){};=$]", words):
                        label = words
                if label or m.group(1) not in keys[attr]:
                    keys[attr][m.group(1)] = label or keys[attr].get(m.group(1)) or m.group(1)
    if not counts:
        return None, OrderedDict()
    attr = counts.most_common(1)[0][0]
    return attr, OrderedDict(list(keys[attr].items())[:20])


def find_writes(proj: Path, web: Path) -> list[str]:
    out = OrderedDict()
    for f in walk(web, (".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte"), 400):
        t = read(f, 3_000_000)
        # fetch("/x", {method: "POST"}) 와 앱의 감싼 함수 api("/x", { ... method: "POST" }) 둘 다
        for m in re.finditer(r"\b\w+\(\s*[`'\"](/[^`'\"?$]*)[`'\"]\s*,\s*\{[^{}]{0,400}?method\s*:\s*[\"'](POST|PUT|PATCH|DELETE)", t, re.S):
            out[f"{m.group(2)} {m.group(1)}"] = 1
        for m in re.finditer(r"\b(?:axios|api|http)\.(post|put|patch|delete)\(\s*[`'\"](/[^`'\"?$]*)", t):
            out[f"{m.group(1).upper()} {m.group(2)}"] = 1
        for m in re.finditer(r"\b(?:post|postJson|apiPost|sendJson)\(\s*[`'\"](/api/[^`'\"?$]*)", t):
            out[f"POST {m.group(1)}"] = 1
    return list(out)[:80]


def find_external(proj: Path, web: Path) -> list[str]:
    hosts = Counter()
    for f in walk(proj, (".py", ".js", ".ts", ".go", ".rb"), 1500):
        if web in f.parents:
            continue
        for m in re.finditer(r"https?://([\w.-]+\.[a-z]{2,})(/[\w./-]*)?", read(f, 1_000_000)):
            host = m.group(1)
            if not any(host.startswith(h.split("/")[0]) for h in IGNORE_HOSTS):
                hosts[host] += 1
    return [h for h, _ in hosts.most_common(15)]


def find_user_data(proj: Path) -> list[str]:
    hits = []
    pat = re.compile(r"(expanduser\(|APPDATA|LOCALAPPDATA|Path\.home\(\)|os\.homedir\(\)|getenv\([\"'][A-Z_]*(ROOT|DATA|DIR)[\"'])")
    for f in walk(proj, (".py", ".js", ".ts"), 1500):
        t = read(f, 1_000_000)
        if pat.search(t):
            hits.append(f.relative_to(proj).as_posix())
    return hits[:10]


def app_name(proj: Path, web: Path | None, stack: dict) -> str:
    if stack.get("name"):
        return str(stack["name"])
    if web and (web / "index.html").is_file():
        m = re.search(r"<title>([^<]{1,60})</title>", read(web / "index.html"))
        if m and m.group(1).strip():
            return m.group(1).strip()
    return proj.name


# ---------- 쓰기 ----------
def client_js(views_attr: str | None, views: OrderedDict, themes: list, groups: list, sizes: list, accent: dict | None) -> str:
    cfg = {"views": dict(views) or None, "themes": themes or None, "tokens": groups or None, "sizeTokens": sizes or None,
           "accent": accent}
    cfg = {k: v for k, v in cfg.items() if v}
    parts = []
    for key, value in cfg.items():
        if isinstance(value, list):  # 한 항목에 한 줄
            inner = ",\n".join("    " + json.dumps(v, ensure_ascii=False) for v in value)
            parts.append(f"  {key}: [\n{inner},\n  ]")
        else:
            parts.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    body = "\n" + ",\n".join(parts)
    if views_attr:
        nav = f'''
  // 화면 이동: init 이 [{views_attr}] 요소를 찾아 그것을 누르게 했다. 앱에 화면 바꾸는 함수가 있으면 그걸 부르게 고친다.
  currentView() {{
    const on = document.querySelector('[{views_attr}].active, [{views_attr}][aria-current="page"], [{views_attr}][aria-selected="true"], [{views_attr}].is-active');
    return (on && on.getAttribute("{views_attr}")) || {json.dumps(next(iter(views), "page"))};
  }},
  switchView(view) {{
    const el = document.querySelector(`[{views_attr}="${{CSS.escape(view)}}"]`);
    if (el) el.click();
  }},'''
    else:
        nav = '''
  // 화면이 하나뿐이거나 이동 방식을 못 찾았다. 여러 화면이면 views·currentView·switchView 를 채운다.
  currentView() {
    return "page";
  },'''
    return f"""/* 디자인 스튜디오가 이 앱을 아는 방법 (studio init 이 만든 초안 — Claude 가 앱 코드를 읽고 다듬는다).
   앱 화면 안에서 스튜디오보다 먼저 돈다. 함수는 스튜디오가 필요할 때 부르므로 앱 전역이 아직 없어도 된다. */
window.__STUDIO_APP__ = {{{body},{nav}
  // 첫 화면을 다 그린 뒤에 저장본을 불러와야 글자·순서 변경이 제자리를 찾는다. 앱이 늦게 그리면 기다릴 표시를 정한다.
  async ready() {{
    await new Promise((r) => setTimeout(r, 600));
  }},
}};
"""


def context_md(name: str, stack: dict, web_rel: str, themes: list, tokens: OrderedDict, views: OrderedDict,
               writes: list, claude_md: list[str]) -> str:
    lines = [f"# {name} 앱 규칙 (디자인 스튜디오용)", "",
             "> `studio init` 이 만든 초안이다. Claude 가 앱 코드와 아래 '채울 것' 을 보고 다듬는다. 짧게 유지한다(AI 추천에 그대로 들어간다).", "",
             "## 구조",
             f"- 화면 파일: `{web_rel}/`" + (f" · 서버: `{stack['python_server']['file']}`" if stack.get("python_server") else ""),
             f"- 종류: {stack['kind']}" + (f" ({stack['bundler']})" if stack.get("bundler") else "")]
    if views:
        lines.append("- 화면 키: " + ", ".join(views))
    lines += ["", "## 테마·토큰"]
    if themes:
        lines.append("- 테마: " + " · ".join(f"{t['key']}=`{t['selector']}`" for t in themes))
    if tokens:
        lines.append("- 토큰: " + ", ".join(list(tokens)[:24]) + (" …" if len(tokens) > 24 else ""))
    lines += ["- 색은 토큰을 먼저 쓴다. 새 색이 필요하면 토큰을 만들고 모든 테마에 값을 정한다.", "",
              "## 디자인 (채울 것)", "- (앱의 색감·글꼴·모서리·여백·문구 말투를 한두 줄로. 지켜야 할 것과 피할 것)", "",
              "## 화면 코드 (채울 것)", "- (단추 동작을 찾는 법, 확인 창·알림·화면 이동 함수, 숨기기 규칙, 다시 그리기 규칙 등)", ""]
    if writes:
        lines += ["## 쓰기 요청", "- 스튜디오에서는 기본으로 '했다 치고' 답한다. 진짜로 넘겨도 되는 것만 studio.app.json 의 pass 에: "
                  + ", ".join(writes[:12]), ""]
    lines += ["## 반영한 뒤 (시안 모드에서는 하지 않는다)", "- (문법 검사·빌드·번역·설치본 등 이 앱에서 '고쳤다' 고 하기 전에 해야 할 것)"]
    if claude_md:
        lines += ["", "> 참고: 저장소에 " + ", ".join(claude_md) + " 가 있다. 화면·디자인 규칙을 골라 위 칸으로 옮긴다."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="studio init")
    ap.add_argument("--project", default=".")
    ap.add_argument("--force", action="store_true", help="있는 설정을 덮어쓴다 (예전 것은 .bak)")
    args = ap.parse_args(argv)
    proj = Path(args.project).resolve()
    out = proj / ADAPTER_DIR
    exists = (out / "studio.app.json").is_file()

    web, web_notes = find_web_root(proj)
    stack = detect_stack(proj)
    themes, tokens, theme_notes = parse_themes_tokens(web) if web else ([], OrderedDict(), [])
    groups, sizes = group_tokens(tokens)
    views_attr, views = find_views(web) if web else (None, OrderedDict())
    writes = find_writes(proj, web) if web else []
    external = find_external(proj, web) if web else []
    user_data = find_user_data(proj)
    name = app_name(proj, web, stack)
    web_rel = web.relative_to(proj).as_posix() if web else "web"
    claude_md = [p for p in ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "FEATURES.md", "DESIGN.md") if (proj / p).is_file()]
    accent = None
    for main_name in ("--accent", "--primary", "--brand", "--color-primary"):
        if main_name in tokens:
            stem = main_name
            accent = {"main": stem, "strong": f"{stem}-strong" if f"{stem}-strong" in tokens else None,
                      "soft": f"{stem}-soft" if f"{stem}-soft" in tokens else None,
                      "surface": next((t for t in ("--surface", "--bg", "--background") if t in tokens), None)}
            accent = {k: v for k, v in accent.items() if v}
            break

    config: dict = {"name": name, "project": "../..", "studioVersion": STUDIO_VERSION, "webRoot": web_rel,
                    "workDir": ".design-studio", "context": "context.md", "client": "studio.app.js"}
    if stack["kind"] == "bundler":
        config["proposals"] = False
    js_files = sorted(p.relative_to(web).as_posix() for p in web.glob("*.js")) if web else []
    if js_files and stack["kind"] != "bundler":
        config["checks"] = [f"node --check {{web}}/{j}" for j in js_files[:3]]
    if stack["launch"]:
        config["launch"] = stack["launch"]
    elif stack["kind"] == "python-custom":
        config["launch"] = ["{venv_python}", "-X", "utf8", "{config_dir}/run_demo.py", "--project", "{project}", "--port", "{port}"]
    else:
        config["serve"] = "static"
    config["requests"] = {"pass": [], "mock": {}, "deny": []}

    todo = []
    if stack["kind"] == "python-custom":
        todo.append("런처 만들기: `templates/launcher_python.py` → `.claude/design-studio/run_demo.py`, 앱 서버를 그 포트로 띄우게.")
    if external:
        todo.append("바깥 서버에 닿는 코드가 있어요(" + ", ".join(external[:6]) + "). 연습 모드에서 막으려면 런처에서 네트워크 차단을 켜고, "
                    "그 응답을 쓰는 GET 은 mock 에 그럴듯한 빈 답을 넣어요.")
    if user_data:
        todo.append("사용자 데이터 폴더를 읽는 코드가 있어요(" + ", ".join(user_data[:4]) + "). 연습 모드는 임시 폴더 + 지어낸 데이터로 "
                    "띄우고(런처), 내 데이터로 보는 real 모드는 쓰기를 모두 막아요(modes).")
    if writes:
        todo.append(f"쓰기 요청 {len(writes)}개를 찾았어요. 기본은 모두 가짜 답이에요. 임시 데이터 안에서만 끝나는 것(설정·정렬·선택 저장 등)만 pass 에.")
    if views_attr:
        todo.append(f"화면 이동은 [{views_attr}] 요소를 누르는 방식으로 초안을 만들었어요. 앱에 화면 바꾸는 함수가 있으면 그걸로.")
    elif web:
        todo.append("화면(뷰) 구분을 못 찾았어요. 여러 화면이면 studio.app.js 의 views·currentView·switchView 를 채워요.")
    todo += ["context.md 의 '채울 것' 을 앱 코드·CLAUDE.md 를 보고 채워요.", "`python -m studio doctor --project <앱>` 이 모두 통과할 때까지 다듬어요."]

    report = ["# 디자인 스튜디오 개인화 분석", "", f"- 앱: **{name}** · 종류: {stack['kind']}" + (f" ({stack['bundler']})" if stack.get("bundler") else ""),
              f"- 화면 폴더: `{web_rel}`" + ("" if web else " (못 찾음)"),
              f"- 띄우기: `{' '.join(config.get('launch') or ['(스튜디오가 정적으로)'])}`",
              f"- 테마 {len(themes)}개 · 토큰 {len(tokens)}개 · 크기 토큰 {len(sizes)}개 · 화면 {len(views)}개" + (f" ([{views_attr}])" if views_attr else ""),
              f"- 쓰기 요청 {len(writes)}개 · 바깥 서버 {len(external)}곳 · 사용자 데이터 경로 {len(user_data)}곳", ""]
    for title, items in (("알아 둘 것", web_notes + stack["notes"] + theme_notes), ("확인할 것 (Claude)", todo),
                         ("쓰기 요청", writes), ("바깥 서버", external)):
        if items:
            report += [f"## {title}", *[f"- {i}" for i in items], ""]

    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.md").write_text("\n".join(report), encoding="utf-8")
    if exists and not args.force:
        print("\n".join(report))
        print(f"\n이미 개인화 설정이 있어서 analysis.md 만 새로 썼어요: {out}\n덮어쓰려면 --force (예전 것은 .bak 로 남겨요).")
        return
    files = {
        "studio.app.json": json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        "studio.app.js": client_js(views_attr, views, themes, groups, sizes, accent),
        "context.md": context_md(name, stack, web_rel, themes, tokens, views, writes, claude_md),
    }
    for fname, text in files.items():
        target = out / fname
        if target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
        target.write_text(text, encoding="utf-8")
    if stack["kind"] == "python-custom" and not (out / "run_demo.py").exists():
        shutil.copy2(STUDIO_HOME / "templates" / "launcher_python.py", out / "run_demo.py")
    print("\n".join(report))
    print(f"\n초안을 만들었어요: {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
