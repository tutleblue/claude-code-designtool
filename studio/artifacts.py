"""작업물 모드: 웹 앱이 아닌 것(AI 가 만든 글·코드·표·그림·PDF·문서·발표 자료·소리·영상, 그 묶음 폴더)을 스튜디오에 올린다.

    python run_studio.py open <파일 또는 폴더>        # 형식을 알아서 보고 댓글·캡처·수정 화면으로
    python run_studio.py open                          # 받은 편지함: 파일을 끌어 놓아 첨부

어떻게 '모든 형식' 에 같은 도구를 쓰나
  스튜디오 도구(studio.js)는 HTML 위에서만 돈다. 그래서 형식마다 '보기 화면'(HTML)을 만들어 주고,
  화면의 덩어리마다 원본 위치(data-ref: 몇째 줄, 몇째 문단, 몇 쪽, 어느 칸, 몇 초)를 붙인다.
  댓글·캡처·글자 고치기는 그 위치를 함께 저장하므로, Claude 는 '원본 어디' 를 고칠지 안다.

고치기
  글로 된 형식(md·코드·json·csv·svg·html)은 웹 앱과 똑같이 시안(복사본)을 Claude 가 고치고, 보고, 반영한다.
  docx·pptx·xlsx·pdf·그림·소리·영상은 Claude CLI 가 바로 고칠 수 없다. 모은 요청을 복사해 그것을 만든 AI 에게 준다.

작업 폴더(저장본·시안·캡처)는 원본 옆이 아니라 ~/.claude/design-studio/work/<이름-해시>/ 에 둔다.
남의 폴더(다운로드 폴더 등)에 .design-studio 를 흩뿌리지 않기 위해서다.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from . import config as appconfig

# ---------- 형식 ----------
CODE_EXT = {
    ".txt", ".log", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".java", ".kt", ".c", ".h", ".cc",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".dart", ".lua", ".r", ".sh", ".bash", ".ps1", ".bat",
    ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example", ".xml", ".tex", ".bib", ".rst", ".mmd", ".vue",
    ".svelte", ".graphql", ".proto", ".gradle", ".m", ".ipynb",
}
KIND_BY_EXT = {
    **{e: "code" for e in CODE_EXT},
    ".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown", ".json": "json",
    ".csv": "csv", ".tsv": "csv", ".svg": "svg",
    **{e: "image" for e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")},
    ".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx",
    **{e: "audio" for e in (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")},
    **{e: "video" for e in (".mp4", ".webm", ".mov", ".m4v")},
}
KIND_LABEL = {
    "html": "웹 페이지", "markdown": "글(마크다운)", "code": "코드·글", "json": "JSON", "csv": "표(CSV)", "svg": "SVG 그림",
    "image": "그림", "pdf": "PDF", "docx": "Word 문서", "pptx": "발표 자료", "xlsx": "엑셀 표", "audio": "소리", "video": "영상",
    "folder": "폴더", "other": "파일",
}
# Claude CLI 가 시안 폴더에서 바로 고칠 수 있는 형식 (글자 파일)
EDITABLE = {"html", "markdown", "code", "json", "csv", "svg"}
SKIP_DIRS = {".git", "node_modules", ".design-studio", "__pycache__", ".venv", "venv", ".claude"}
MAX_TEXT = 2_000_000  # 이보다 큰 글 파일은 앞부분만 보여 준다 (보기 화면이 멈추지 않게)


def kind_of(path: Path) -> str:
    if path.is_dir():
        return "folder"
    name = path.name.lower()
    for ext, kind in KIND_BY_EXT.items():
        if name.endswith(ext):
            return kind
    try:
        head = path.read_bytes()[:2048]
    except OSError:
        return "other"
    if b"\0" not in head:  # 확장자가 낯설어도 글자 파일이면 글로 본다
        try:
            head.decode("utf-8")
            return "code"
        except UnicodeDecodeError:
            pass
    return "other"


def work_root() -> Path:
    return Path(os.environ.get("STUDIO_WORK") or Path.home() / ".claude" / "design-studio" / "work")


def list_files(root: Path, limit: int = 400) -> list[dict]:
    out: list[dict] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if p.is_file():
            out.append({"file": rel.as_posix(), "kind": kind_of(p), "size": p.stat().st_size})
            if len(out) >= limit:
                break
    return out


# ---------- 설정 만들기 ----------
CONTEXT = """# 작업물 규칙 (디자인 스튜디오 작업물 모드)

사용자가 AI 가 만든 작업물을 스튜디오에서 보며 댓글·캡처·글자 고치기를 남겼다.

- 각 댓글·고친 글자에는 '위치'(몇째 줄·몇째 문단·몇 쪽·어느 칸·몇 초)가 붙어 있다. 그 위치의 원본을 고친다.
- 원본 형식을 지킨다: 마크다운은 마크다운으로, CSV 는 같은 구분자·열 수로, JSON 은 올바른 JSON 으로, 코드는 돌아가게.
- 요청과 상관없는 곳은 건드리지 않는다. 글투·형식은 원래 작업물의 것을 따른다.
- 캡처 그림이 있으면 Read 로 열어 사용자가 가리킨 곳을 확인한다.
"""


def make_config(target: str | Path | None) -> appconfig.AppConfig:
    """파일·폴더(없으면 받은 편지함)로 작업물 모드 설정을 만든다. 설정 파일(artifact.json)도 남겨
    snapshot·doctor 가 같은 설정을 다시 읽게 한다."""
    inbox = target is None
    if inbox:
        root = work_root() / "inbox" / "files"
        root.mkdir(parents=True, exist_ok=True)
        t = root
    else:
        t = Path(target).expanduser().resolve()
        if not t.exists():
            raise SystemExit(f"그런 파일·폴더가 없어요: {t}")
        root = t if t.is_dir() else t.parent
    key = hashlib.sha1(str(t).lower().encode("utf-8")).hexdigest()[:8]
    ws = work_root() / ("inbox" if inbox else f"{re.sub(r'[^A-Za-z0-9가-힣_-]+', '-', t.stem)[:30]}-{key}")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "context.md").write_text(CONTEXT, encoding="utf-8")
    cfg_path = ws / "artifact.json"
    cfg_path.write_text(json.dumps({"artifact": str(t), "inbox": inbox}, ensure_ascii=False, indent=1), encoding="utf-8")
    single = t.is_file()
    return appconfig.AppConfig(
        path=cfg_path, project=ws, mode="artifact", modes=["artifact"],
        name=t.name if not inbox else "받은 작업물",
        web_root=root, work_dir=ws, context_path=ws / "context.md",
        artifact=True, inbox=inbox, entry=t.name if single else "",
        files=[t.name] if single else None,
    )


# ---------- 보기 화면 ----------
VIEW_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f4f3ee; color: #1f1e1c; font: 15px/1.65 "Pretendard", "Segoe UI", "Malgun Gothic", -apple-system, "Apple SD Gothic Neo", system-ui, sans-serif; }
.av-head { position: sticky; top: 0; z-index: 2; display: flex; gap: 10px; align-items: baseline; padding: 10px 24px; background: #fffdf8ee;
  border-bottom: 1px solid #e3e0d6; backdrop-filter: blur(6px); }
.av-head b { font-size: 14px; } .av-head span { font-size: 12px; color: #6b675e; } .av-head a { font-size: 12px; color: #2f5fae; margin-left: auto; }
.av-doc { max-width: 860px; margin: 24px auto 80px; padding: 34px 44px; background: #fff; border: 1px solid #e3e0d6; border-radius: 10px; }
.av-wide { max-width: none; margin: 18px 24px 80px; }
[data-ref] { border-radius: 4px; }
.av-doc h1, .av-doc h2, .av-doc h3, .av-doc h4 { line-height: 1.3; margin: 1.2em 0 .5em; }
.av-doc pre { background: #f6f5f0; padding: 12px 14px; border-radius: 8px; overflow: auto; font: 13px/1.5 Consolas, "SF Mono", Menlo, monospace; }
.av-doc code { font: 13px Consolas, "SF Mono", Menlo, monospace; background: #f1efe8; padding: 1px 4px; border-radius: 4px; }
.av-doc pre code { background: none; padding: 0; }
.av-doc blockquote { margin: 0; padding: 4px 14px; border-left: 3px solid #d8d4c8; color: #55524b; }
.av-doc table { border-collapse: collapse; margin: 10px 0; font-size: 14px; }
.av-doc th, .av-doc td { border: 1px solid #e3e0d6; padding: 5px 9px; text-align: left; vertical-align: top; }
.av-doc img { max-width: 100%; }
.av-lines { font: 13px/1.6 Consolas, "SF Mono", Menlo, monospace; white-space: pre-wrap; word-break: break-word; }
.av-line { display: flex; } .av-line i { flex: none; width: 4.2em; padding-right: 1em; text-align: right; color: #a19d92; font-style: normal; user-select: none; }
.av-line span { flex: 1; min-width: 0; min-height: 1.6em; }
.av-grid { border-collapse: collapse; font-size: 13px; background: #fff; }
.av-grid th { position: sticky; top: 45px; background: #f1efe8; color: #6b675e; font-weight: 600; }
.av-grid th, .av-grid td { border: 1px solid #e3e0d6; padding: 4px 8px; max-width: 360px; vertical-align: top; }
.av-grid td.rh { background: #f6f5f0; color: #8a867c; text-align: right; }
.av-media { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 24px; }
.av-media img, .av-media video { max-width: 100%; max-height: 82vh; background: #fff; box-shadow: 0 1px 4px #0001; }
.av-page { margin: 0 auto 18px; max-width: 980px; } .av-page img { width: 100%; display: block; background: #fff; box-shadow: 0 1px 4px #0002; }
.av-page figcaption { font-size: 12px; color: #6b675e; margin: 4px 2px; }
.av-slide { aspect-ratio: 16 / 9; background: #fff; border: 1px solid #e3e0d6; border-radius: 10px; margin: 0 auto 18px; max-width: 900px; padding: 26px 34px; overflow: hidden; }
.av-slide h2 { margin: 0 0 12px; font-size: 26px; } .av-slide p { margin: 6px 0; } .av-slide .no { float: right; font-size: 12px; color: #a19d92; }
.av-files { list-style: none; padding: 0; margin: 0; } .av-files li { border-bottom: 1px solid #efede6; }
.av-files a { display: flex; gap: 10px; padding: 9px 4px; color: inherit; text-decoration: none; } .av-files a:hover { background: #f6f5f0; }
.av-files em { font-style: normal; color: #6b675e; font-size: 12px; margin-left: auto; }
.av-note { color: #6b675e; font-size: 13px; }
.av-drop { border: 2px dashed #cfcab9; border-radius: 12px; padding: 34px; text-align: center; color: #6b675e; margin-bottom: 18px; }
"""


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def _ref(ref: str, label: str) -> str:
    return f'data-ref="{esc(ref)}" data-ref-label="{esc(label)}"'


def _read_text(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    cut = len(raw) > MAX_TEXT
    raw = raw[:MAX_TEXT]
    for enc in ("utf-8-sig", "cp949", "latin-1"):
        try:
            return raw.decode(enc), cut
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), cut


def page(title: str, body: str, *, wide: bool = False) -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{VIEW_CSS}</style></head>
<body>{body}</body></html>"""


def head_bar(rel: str, kind: str, extra: str = "", back: bool = False) -> str:
    link = '<a href="/?frame=1">← 목록</a>' if back else ""
    return f'<div class="av-head"><b>{esc(rel or "작업물")}</b><span>{esc(KIND_LABEL.get(kind, kind))}</span>{extra}{link}</div>'


# --- 마크다운: 덩어리마다 원본 줄 번호를 붙인다 (외부 라이브러리 없이, 글자는 모두 이스케이프) ---
_INLINE = [
    (re.compile(r"`([^`]+)`"), lambda m: f"<code>{m.group(1)}</code>"),
    (re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)"), lambda m: f'<img alt="{m.group(1)}" src="{_safe_url(m.group(2))}">'),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), lambda m: f'<a href="{_safe_url(m.group(2))}">{m.group(1)}</a>'),
    (re.compile(r"\*\*([^*]+)\*\*"), lambda m: f"<b>{m.group(1)}</b>"),
    (re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)"), lambda m: f"<i>{m.group(1)}</i>"),
]


def _safe_url(u: str) -> str:
    # javascript: 같은 것은 막는다. 이미 이스케이프된 글이라 따옴표는 들어올 수 없다
    return u if re.match(r"^(https?:|mailto:|#|/|\.|[\w-]+[/.])", u) and not u.lower().startswith("javascript") else "#"


def _inline(text: str) -> str:
    out = esc(text)
    for pat, fn in _INLINE:
        out = pat.sub(fn, out)
    return out


def render_markdown(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    def block(tag: str, start: int, end: int, inner: str, attrs: str = "") -> None:
        lab = f"{start + 1}번째 줄" if start == end else f"{start + 1}~{end + 1}번째 줄"
        out.append(f"<{tag} {_ref(f'L{start + 1}-{end + 1}', lab)}{attrs}>{inner}</{tag}>")

    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence, start = s[:3], i
            i += 1
            body = []
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            block("pre", start, min(i, n - 1), f"<code>{esc(chr(10).join(body))}</code>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            block(f"h{len(m.group(1))}", i, i, _inline(m.group(2)))
            i += 1
            continue
        if re.match(r"^([-*_])\1{2,}$", s):
            out.append(f"<hr {_ref(f'L{i + 1}-{i + 1}', f'{i + 1}번째 줄')}>")
            i += 1
            continue
        if s.startswith(">"):
            start = i
            body = []
            while i < n and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].strip())
                i += 1
            block("blockquote", start, i - 1, "<br>".join(_inline(b) for b in body))
            continue
        if "|" in s and i + 1 < n and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            start = i
            rows = []
            while i < n and "|" in lines[i]:
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[2:]
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
            block("table", start, i - 1, f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody>")
            continue
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            ordered = lm.group(2)[0].isdigit()
            items = []
            while i < n:
                mm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if not mm:
                    break
                items.append(f"<li {_ref(f'L{i + 1}-{i + 1}', f'{i + 1}번째 줄')}>{_inline(mm.group(3))}</li>")
                i += 1
            out.append(f"<{'ol' if ordered else 'ul'}>{''.join(items)}</{'ol' if ordered else 'ul'}>")
            continue
        start = i
        body = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|~~~|>|\s*([-*+]|\d+[.)])\s)", lines[i]):
            body.append(lines[i].strip())
            i += 1
        block("p", start, i - 1, "<br>".join(_inline(b) for b in body))
    return "\n".join(out)


def render_lines(text: str) -> str:
    rows = [f'<div class="av-line" {_ref(f"L{k}-{k}", f"{k}번째 줄")}><i>{k}</i><span>{esc(t)}</span></div>'
            for k, t in enumerate(text.split("\n"), 1)]
    return f'<div class="av-lines">{"".join(rows)}</div>'


def _col(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def render_csv(text: str, delim: str) -> str:
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))[:3000]
    width = max((len(r) for r in rows), default=0)
    head = "<tr><th></th>" + "".join(f"<th>{_col(c)}</th>" for c in range(width)) + "</tr>"
    body = []
    for r, row in enumerate(rows):
        cells = "".join(f'<td {_ref(f"{_col(c)}{r + 1}", f"{_col(c)}{r + 1} 칸 ({r + 1}행 {c + 1}열)")}>{esc(v)}</td>'
                        for c, v in enumerate(row))
        body.append(f'<tr {_ref(f"R{r + 1}", f"{r + 1}행")}><td class="rh">{r + 1}</td>{cells}</tr>')
    return f'<table class="av-grid"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


# --- Office 문서: zip 안의 XML 을 읽어 글 구조만 보여 준다 (설치할 것 없이). 모양은 '쪽 그림으로' 에서 ---
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(z.read(name))
    except (KeyError, ET.ParseError):
        return None


def render_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        doc = _xml(z, "word/document.xml")
    if doc is None:
        return '<p class="av-note">문서를 읽지 못했어요.</p>'
    body = doc.find(f"{W}body")
    out, para = [], 0
    for el in list(body if body is not None else []):
        if el.tag == f"{W}p":
            para += 1
            text = "".join(t.text or "" for t in el.iter(f"{W}t"))
            style = el.find(f"{W}pPr/{W}pStyle")
            sv = (style.get(f"{W}val") if style is not None else "") or ""
            hm = re.search(r"(\d)", sv) if sv.lower().startswith(("heading", "title")) or "제목" in sv else None
            tag = f"h{min(int(hm.group(1)) + 1, 4)}" if hm else ("h1" if sv.lower() == "title" else "p")
            if text.strip() or tag != "p":
                out.append(f"<{tag} {_ref(f'P{para}', f'{para}번째 문단')}>{esc(text)}</{tag}>")
        elif el.tag == f"{W}tbl":
            rows = []
            for r, tr in enumerate(el.iter(f"{W}tr"), 1):
                cells = "".join(
                    f'<td {_ref(f"T{para}R{r}C{c}", f"{para}번째 문단 뒤 표 {r}행 {c}열")}>'
                    f'{esc(" ".join("".join(t.text or "" for t in p.iter(f"{W}t")) for p in tc.iter(f"{W}p")))}</td>'
                    for c, tc in enumerate(tr.iter(f"{W}tc"), 1))
                rows.append(f"<tr>{cells}</tr>")
            out.append(f"<table>{''.join(rows)}</table>")
    return "\n".join(out) or '<p class="av-note">글이 없어요.</p>'


def render_pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        slides = [(_xml(z, n), int(re.search(r"(\d+)\.xml$", n).group(1))) for n in names]
    out = []
    for root, no in slides:
        if root is None:
            continue
        boxes = []
        for b, sp in enumerate(root.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sp"), 1):
            paras = ["".join(t.text or "" for t in p.iter(f"{A}t")) for p in sp.iter(f"{A}p")]
            paras = [p for p in paras if p.strip()]
            if not paras:
                continue
            is_title = any((ph.get("type") or "") in ("title", "ctrTitle") for ph in sp.iter(
                "{http://schemas.openxmlformats.org/presentationml/2006/main}ph"))
            tag = "h2" if is_title else "div"
            inner = "".join(f"<p>{esc(p)}</p>" for p in paras) if tag == "div" else esc(" ".join(paras))
            boxes.append(f"<{tag} {_ref(f'S{no}B{b}', f'{no}번 슬라이드 {b}번째 상자')}>{inner}</{tag}>")
        out.append(f'<section class="av-slide" {_ref(f"S{no}", f"{no}번 슬라이드")}><span class="no">{no}</span>{"".join(boxes)}</section>')
    return "\n".join(out) or '<p class="av-note">슬라이드를 읽지 못했어요.</p>'


def render_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        shared = []
        sst = _xml(z, "xl/sharedStrings.xml")
        if sst is not None:
            shared = ["".join(t.text or "" for t in si.iter(f"{S}t")) for si in sst.iter(f"{S}si")]
        wb = _xml(z, "xl/workbook.xml")
        names = [s.get("name") for s in wb.iter(f"{S}sheet")] if wb is not None else []
        sheets = sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        out = []
        for k, sheet in enumerate(sheets):
            ws = _xml(z, sheet)
            if ws is None:
                continue
            title = names[k] if k < len(names) else f"시트{k + 1}"
            grid: dict[tuple[int, int], str] = {}
            for c in ws.iter(f"{S}c"):
                ref = c.get("r") or ""
                m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
                if not m:
                    continue
                col = 0
                for ch in m.group(1):
                    col = col * 26 + ord(ch) - 64
                v = c.find(f"{S}v")
                val = v.text if v is not None and v.text else "".join(t.text or "" for t in c.iter(f"{S}t"))
                if c.get("t") == "s" and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
                grid[(int(m.group(2)), col - 1)] = val
            if not grid:
                continue
            rows = min(max(r for r, _ in grid), 2000)
            cols = min(max(c for _, c in grid) + 1, 60)
            head = "<tr><th></th>" + "".join(f"<th>{_col(c)}</th>" for c in range(cols)) + "</tr>"
            body = "".join(
                f'<tr><td class="rh">{r}</td>' + "".join(
                    f'<td {_ref(f"{title}!{_col(c)}{r}", f"{title} 시트 {_col(c)}{r} 칸")}>{esc(grid.get((r, c), ""))}</td>'
                    for c in range(cols)) + "</tr>" for r in range(1, rows + 1))
            out.append(f'<h3 {_ref(f"{title}!", f"{title} 시트")}>{esc(title)}</h3><table class="av-grid"><thead>{head}</thead><tbody>{body}</tbody></table>')
    return "\n".join(out) or '<p class="av-note">표를 읽지 못했어요.</p>'


# --- PDF·Office 를 쪽 그림으로 (있는 도구로: pdftoppm → PyMuPDF, Office 는 LibreOffice 로 PDF 를 거쳐) ---
def tools() -> dict[str, str | None]:
    return {"pdftoppm": shutil.which("pdftoppm"), "soffice": shutil.which("soffice") or shutil.which("libreoffice"),
            "fitz": _has_fitz()}


def _has_fitz() -> str | None:
    try:
        import fitz  # noqa: F401
        return "PyMuPDF"
    except ImportError:
        return None


def page_images(cfg: appconfig.AppConfig, src: Path) -> list[Path]:
    """쪽마다 PNG (작업 폴더에 캐시). 만들 도구가 없으면 []."""
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:12]
    out_dir = cfg.work_dir / "cache" / key
    done = sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    if done:
        return done
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = src
    t = tools()
    if src.suffix.lower() != ".pdf":
        if not t["soffice"]:
            return []
        # 사용자 프로필을 따로 써야 이미 열린 LibreOffice 와 부딪치지 않는다
        subprocess.run([t["soffice"], f"-env:UserInstallation=file:///{(out_dir / 'lo').as_posix().lstrip('/')}",
                        "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
                       capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        pdf = out_dir / (src.stem + ".pdf")
        if not pdf.is_file():
            return []
    if t["pdftoppm"]:
        subprocess.run([t["pdftoppm"], "-r", "110", "-png", "-l", "200", str(pdf), str(out_dir / "page")],
                       capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    elif t["fitz"]:
        import fitz
        with fitz.open(pdf) as d:
            for i, pg in enumerate(d, 1):
                if i > 200:
                    break
                pg.get_pixmap(dpi=110).save(str(out_dir / f"page-{i}.png"))
    return sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))


def render_pages(cfg: appconfig.AppConfig, rel: str, pages: list[Path]) -> str:
    return "\n".join(
        f'<figure class="av-page" {_ref(f"p{k}", f"{k}쪽")}><img src="/__studio/page?file={esc(rel)}&n={k}" '
        f'data-natural="1" alt="{k}쪽"><figcaption>{k}쪽</figcaption></figure>' for k, _ in enumerate(pages, 1))


def view(cfg: appconfig.AppConfig, base: Path, rel: str, mode: str = "") -> str:
    """보기 화면 HTML. rel 이 비면 폴더 목록(받은 편지함이면 끌어 놓기 칸 포함)."""
    if not rel:
        files = list_files(base)
        drop = ('<div class="av-drop" id="avDrop">여기에 파일을 끌어 놓거나 <b>패널의 ＋ 첨부</b>를 누르세요.<br>'
                '글·코드·표·그림·PDF·Word·PowerPoint·Excel·소리·영상 모두 돼요.</div>') if cfg.inbox else ""
        items = "".join(
            f'<li {_ref("file:" + f["file"], f["file"])}><a href="/?frame=1&file={esc(f["file"])}">{esc(f["file"])}'
            f'<em>{esc(KIND_LABEL.get(f["kind"], f["kind"]))} · {f["size"] // 1024 + 1} KB</em></a></li>' for f in files)
        body = f'{head_bar(cfg.name, "folder")}<div class="av-doc">{drop}<ul class="av-files">{items}</ul>' \
               f'{"" if files else "<p class=av-note>아직 파일이 없어요.</p>"}</div>'
        return page(cfg.name, body)
    path = (base / rel).resolve()
    if not path.is_file() and base != cfg.web_root:  # 시안에는 글자 파일만 복사된다. 그림 등은 원본에서
        path = (cfg.web_root / rel).resolve()
    kind = kind_of(path)
    back = not cfg.files
    url = "/" + "/".join(esc(p) for p in rel.split("/"))
    if kind == "markdown":
        text, cut = _read_text(path)
        body = f'<article class="av-doc">{render_markdown(text)}</article>'
    elif kind in ("code", "json"):
        text, cut = _read_text(path)
        if kind == "json":
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2) if len(text) < 300_000 and "\n" not in text.strip() else text
            except ValueError:
                pass
        body = f'<div class="av-doc av-wide">{render_lines(text)}</div>'
    elif kind == "csv":
        text, cut = _read_text(path)
        body = f'<div class="av-doc av-wide">{render_csv(text, chr(9) if path.suffix.lower() == ".tsv" else ",")}</div>'
    elif kind in ("image", "svg"):
        # SVG 도 <img> 로: AI 가 만든 SVG 안의 스크립트가 스튜디오 화면에서 돌지 않게
        body = f'<div class="av-media"><img {_ref("image", "그림")} data-natural="1" src="{url}" alt="{esc(rel)}"></div>'
    elif kind in ("audio", "video"):
        tag = "video" if kind == "video" else "audio"
        body = (f'<div class="av-media"><{tag} {_ref("media", "재생 위치")} data-media="1" controls src="{url}"></{tag}>'
                '<p class="av-note">댓글을 달면 지금 재생 위치(초)가 함께 적혀요. 멈추고 화면을 눌러 달아도 돼요.</p></div>')
    elif kind == "pdf" or (kind in ("docx", "pptx", "xlsx") and mode == "pages"):
        pages = page_images(cfg, path)
        if pages:
            body = f'<div class="av-wide">{render_pages(cfg, rel, pages)}</div>'
        else:
            body = ('<div class="av-doc"><p class="av-note">쪽 그림을 만들 도구가 없어요 (pdftoppm·PyMuPDF·LibreOffice). '
                    '파일 전체에 댓글을 달 수 있어요.</p>'
                    f'<p {_ref("file", "파일 전체")}><b>{esc(rel)}</b></p></div>')
    elif kind == "docx":
        body = f'<article class="av-doc">{render_docx(path)}</article>'
    elif kind == "pptx":
        body = f'<div class="av-wide">{render_pptx(path)}</div>'
    elif kind == "xlsx":
        body = f'<div class="av-doc av-wide">{render_xlsx(path)}</div>'
    else:
        body = f'<div class="av-doc"><p {_ref("file", "파일 전체")}><b>{esc(rel)}</b></p><p class="av-note">이 형식은 미리 볼 수 없어요. 파일 전체에 댓글을 달 수 있어요.</p></div>'
    extra = ""
    if kind in ("docx", "pptx", "xlsx"):
        other = "" if mode == "pages" else "&mode=pages"
        extra = f'<a href="/?frame=1&file={esc(rel)}{other}" style="margin-left:12px">{"글로 보기" if mode == "pages" else "쪽 모양으로 보기"}</a>'
    if kind in ("markdown", "code", "json", "csv") and locals().get("cut"):
        extra += '<span>너무 길어 앞부분만 보여요</span>'
    return page(rel, head_bar(rel, kind, extra, back) + body)
