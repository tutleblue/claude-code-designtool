r"""디자인 스튜디오 서버 — 아무 웹 앱이나 그 앞에 서서 '연습용 복제 앱' 으로 만든다.

    python -m studio --app <앱 설정 studio.app.json> [--project <앱 저장소>] [--mode demo|real]

어떻게 '똑같이' 생겼나
  앱을 따로 베끼지 않는다. 진짜 앱 서버를 띄우고(설정의 launch) 그 앞에서 프록시로 선다.
  첫 화면 HTML 에만 편집 도구(studio.js)를 끼워 넣고, 나머지 요청은 앱이 그대로 답한다.
  그래서 앱이 바뀌어도 스튜디오는 고칠 것이 없다.

어떻게 '실제로는 아무것도 안 하게' 했나
  - GET 은 앱에 넘기고, 쓰기 요청(POST·PUT·PATCH·DELETE)은 기본으로 '했다 치고' 가짜 답을 준다.
    설정의 pass 에 적은 것만 진짜로 넘긴다 (예: 임시 폴더 안에서만 끝나는 시간표 저장).
  - 바깥 연결 차단·가짜 데이터는 앱 쪽 런처(어댑터)가 한다. 앱 프로세스 안에서 막아야 확실하기 때문이다.

화면이 앱과 같은 출처(127.0.0.1:<스튜디오 포트>)에서 뜨므로, 바깥 틀(패널)과 앱 iframe 이 서로 만질 수 있다.
시안을 볼 때는 쿠키(studio_web=<시안 이름>)로 화면 글자 파일만 시안 폴더 것으로 바꿔 준다.
"""
from __future__ import annotations

import argparse
import atexit
import base64
import binascii
import http.client
import json
import mimetypes
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

from . import artifacts
from . import config as appconfig
from .ai import AIRunner
from .claude_cli import AGENTS, find_agent, kill_tree
from .proposals import ProposalManager

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
STATIC = {"studio.js": "application/javascript", "studio.css": "text/css", "studio-fonts.css": "text/css"}
try:
    VERSION = (HERE.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = ""

NO_CACHE = {"cache-control", "expires", "etag", "last-modified", "age", "pragma"}
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "content-length", "x-frame-options"}

SHELL_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>디자인 스튜디오 · {NAME}</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23141413'/%3E%3Cpath d='M9 22 L16 8 L23 22 M12 17 H20' stroke='%23d97757' stroke-width='3' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E" />
  <link rel="stylesheet" href="/__studio/studio-fonts.css" />
  <style>
    html, body { margin: 0; height: 100%; overflow: hidden; background: #141413; }
    #app { position: fixed; top: 0; left: 0; width: 100%; height: 100%; border: 0; background: #faf9f5; }
    /* 패널(330px + 여백)을 붙이면 앱 칸이 그만큼 좁아진다 → 앱이 그 너비의 진짜 배치(미디어 쿼리)로 그려진다 */
    html.dock-right #app { width: calc(100% - 354px); }
    html.dock-left #app { left: 354px; width: calc(100% - 354px); }
  </style>
</head>
<body>
  <script>window.__STUDIO_SHELL__ = true;</script>
  <!-- display-capture: 캡처(탭 화면 찍기)를 iframe 안 도구에서도 부를 수 있게 -->
  <iframe id="app" title="{NAME}" src="{SRC}" allow="display-capture; clipboard-write"></iframe>
</body>
</html>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="studio open", description="디자인 스튜디오 띄우기")
    ap.add_argument("target", nargs="?", default="",
                    help="작업물 파일·폴더 (AI 가 만든 글·코드·표·그림·PDF·문서 등). 비우면 앱 설정을, 그것도 없으면 받은 편지함을 연다")
    ap.add_argument("--project", default="", help="앱 저장소 폴더 (기본: 지금 폴더). 그 안의 .claude/design-studio/studio.app.json 을 쓴다")
    ap.add_argument("--app", default="", help="앱 설정 파일을 따로 줄 때")
    ap.add_argument("--mode", default="", help="설정의 modes 중 하나 (기본: 첫 번째)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_PORT", "8796")))
    ap.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않음")
    ap.add_argument("--web", default="", help="화면 글자 파일을 이 폴더 것으로 (시안 사진 찍을 때)")
    ap.add_argument("--snapshot", action="store_true", help="snapshot 이 사진 찍으려고 띄운 서버 (시안·저장·AI 는 다루지 않는다)")
    return ap.parse_args(argv)


# ---------- 앱 띄우기 ----------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, proc: subprocess.Popen | None, seconds: float = 60) -> bool:
    u = urlparse(url)
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=2)
            conn.request("GET", "/")
            status = conn.getresponse().status
            conn.close()
            if status < 500:
                return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


def start_app(cfg: appconfig.AppConfig) -> tuple[str, subprocess.Popen | None, Path | None]:
    if cfg.artifact:  # 작업물 모드는 띄울 앱이 없다. 보기 화면은 스튜디오가 직접 만든다
        return "", None, None
    if not cfg.launch:
        upstream = appconfig.fill_upstream(cfg, 0)
        if not wait_http(upstream, None, 10):
            sys.exit(f"앱 주소({upstream})에서 답이 없어요. 앱을 먼저 띄워 주세요.")
        return upstream, None, None
    port = free_port()
    cmd = appconfig.fill_launch(cfg, port)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    log = cfg.work_dir / "app.log"
    out = log.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=cfg.project, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    atexit.register(kill_tree, proc)
    upstream = appconfig.fill_upstream(cfg, port)
    if not wait_http(upstream, proc):
        kill_tree(proc)
        out.close()
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        sys.exit("앱을 띄우지 못했어요.\n  명령: " + " ".join(cmd) + "\n  마지막 기록:\n    " + "\n    ".join(tail))
    return upstream, proc, log


# ---------- 요청 처리 ----------
class Studio:
    """서버 전체가 함께 쓰는 것 (핸들러는 요청마다 새로 생긴다)."""

    def __init__(self, args: argparse.Namespace, cfg: appconfig.AppConfig, upstream: str):
        self.args = args
        self.cfg = cfg
        self.upstream = urlparse(upstream) if upstream else None
        self.override = Path(args.web).resolve() if args.web else None
        self.proposals = ProposalManager(cfg, manage=not args.snapshot)
        self.claude_ok = bool(self.proposals.claude_path())
        # 시안을 고칠 수 있는 AI CLI (보낼 곳 단추). 화면이 뜰 때 한 번 본다
        self.agents = {a: bool(find_agent(a)) for a in AGENTS}
        self.ai = AIRunner(cfg)
        self.port = 0


def build_handler(st: Studio):
    cfg = st.cfg

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "DesignStudio"

        def log_message(self, fmt: str, *a) -> None:  # noqa: D401 — 조용히
            return

        # ----- 공통 -----
        def end_headers(self) -> None:
            # 남의 페이지가 스튜디오를 iframe 으로 감싸지 못하게 (바깥 틀이 같은 출처의 앱을 싣는 것만 된다)
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            super().end_headers()

        def _host_ok(self) -> bool:
            # DNS 리바인딩 막기: 이 컴퓨터 주소로 온 요청만
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{st.port}", f"localhost:{st.port}")

        def _send(self, body: bytes, ctype: str, status: int = 200, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, data, status: int = 200) -> None:
            self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n > 0 else b""

        def _json_body(self) -> dict:
            try:
                data = json.loads(self._body().decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}

        def _context(self) -> str:
            """지금 보는 시안 이름 (없으면 '' = 진짜 화면)."""
            for part in (self.headers.get("Cookie") or "").split(";"):
                key, _, value = part.strip().partition("=")
                if key == "studio_web" and value and st.proposals.web_dir(value).exists():
                    return Path(value).name
            return ""

        def _web_override(self) -> Path | None:
            if st.override:
                return st.override
            ctx = self._context()
            return st.proposals.web_dir(ctx) if ctx else None

        # ----- GET -----
        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self.send_json({"ok": False, "message": "허용되지 않은 호스트예요."}, 403)
            parsed = urlparse(self.path)
            route, params = parsed.path, parse_qs(parsed.query)
            if route.startswith("/__studio/"):
                return self._studio_get(route[len("/__studio/"):], params)
            entry = route in ("/", "/index.html")
            if entry and not ({"frame", "clean"} & set(params)):
                src = "/?frame=1" + (f"&{parsed.query}" if parsed.query else "")
                html = SHELL_HTML.replace("{SRC}", src.replace('"', "&quot;")).replace("{NAME}", _esc(cfg.name))
                return self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            if entry:
                return self._frame(parsed)
            local = self._local_file(route)
            if local:
                ctype = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                return self._send(local.read_bytes(), ctype)
            self._dispatch()

        def _local_file(self, route: str) -> Path | None:
            """시안 폴더에 있는 글자 파일은 그것을 준다 (그림 등은 시안에 없으니 앱이 준다).
            작업물 모드는 앱이 없으니 시안에 없으면 원본 폴더에서 준다."""
            bases = [self._web_override()]
            if cfg.artifact:
                bases.append(cfg.web_root)
            rel = unquote(route).lstrip("/")
            for base in bases:
                if not base:
                    continue
                cand = (base / rel).resolve()
                if cand != base and base in cand.parents and cand.is_file():
                    return cand
            return None

        def _artifact_rel(self, params: dict) -> str:
            """보기 화면에 띄울 파일 (원본 폴더 기준). 폴더 밖·숨김 경로는 받지 않는다."""
            rel = (params.get("file", [""])[0] or cfg.entry).replace("\\", "/").strip("/")
            if not rel:
                return ""
            parts = rel.split("/")
            if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
                return cfg.entry
            if cfg.files is not None and rel not in cfg.files:  # 파일 하나만 연 경우: 옆 파일은 안 보여 준다
                return cfg.entry
            cand = (cfg.web_root / rel).resolve()
            return rel if cfg.web_root in cand.parents and cand.is_file() else cfg.entry

        def _frame(self, parsed) -> None:
            base = self._web_override()
            html = None
            art = None
            if cfg.artifact:
                params = parse_qs(parsed.query)
                rel = self._artifact_rel(params)
                kind = artifacts.kind_of(cfg.web_root / rel) if rel else "folder"
                src = (base or cfg.web_root) / rel if rel else None
                if kind == "html":
                    if not (src and src.is_file()):
                        src = cfg.web_root / rel
                    html = src.read_text(encoding="utf-8", errors="replace")
                else:
                    html = artifacts.view(cfg, base or cfg.web_root, rel, params.get("mode", [""])[0])
                art = {"kind": kind, "label": artifacts.KIND_LABEL.get(kind, kind), "file": rel, "inbox": cfg.inbox,
                       "single": cfg.files is not None, "editable": kind in artifacts.EDITABLE,
                       "root": str(cfg.web_root)}
            elif base and (base / "index.html").is_file():
                html = (base / "index.html").read_text(encoding="utf-8")
            else:
                status, headers, body = self._upstream("GET", parsed.path + (f"?{parsed.query}" if parsed.query else ""),
                                                       b"", identity=True)
                if status >= 400 or "html" not in headers.get("content-type", ""):
                    return self._send(body, headers.get("content-type", "text/plain"), status)
                html = body.decode("utf-8", errors="replace")
            info = {"mode": cfg.mode, "modes": cfg.modes, "app": cfg.name, "version": VERSION, "requests": cfg.rel(cfg.requests_dir),
                    "ctx": "" if st.override else self._context(), "claude": st.claude_ok, "proposals": cfg.proposals, "snapshot": st.args.snapshot,
                    "captures": cfg.rel(captures_dir(cfg)), "artifact": art, "agents": st.agents}
            head = ('<link rel="stylesheet" href="/__studio/studio-fonts.css" />\n'
                    '<link rel="stylesheet" href="/__studio/studio.css" />\n')
            # 앱 스크립트가 다 돈 뒤 붙도록 body 끝에, defer 로 (defer 끼리는 문서 순서대로 돈다)
            tail = (f"<script>window.__STUDIO__ = {json.dumps(info, ensure_ascii=False)};</script>\n"
                    + ('<script src="/__studio/app-client.js" defer></script>\n' if cfg.client_path else "")
                    + '<script src="/__studio/studio.js" defer></script>\n')
            html = _insert_before(html, "</head>", head)
            html = _insert_before(html, "</body>", tail)
            self._send(html.encode("utf-8"), "text/html; charset=utf-8")

        def _studio_get(self, name: str, params: dict) -> None:
            if name in STATIC:
                return self._send((ASSETS / name).read_bytes(), STATIC[name] + "; charset=utf-8")
            if name == "app-client.js" and cfg.client_path and cfg.client_path.is_file():
                return self._send(cfg.client_path.read_bytes(), "application/javascript; charset=utf-8")
            if name.startswith("fonts/") and name.endswith(".woff2"):
                font = ASSETS / "fonts" / Path(name).name
                if font.is_file():
                    return self._send(font.read_bytes(), "font/woff2", extra={"Cache-Control": "max-age=86400"})
            if name == "proposals":
                return self.send_json({"ok": True, "items": st.proposals.list(), "claude": st.claude_ok})
            if name == "files" and cfg.artifact:
                return self.send_json({"ok": True, "items": [] if cfg.files is not None else artifacts.list_files(cfg.web_root),
                                       "root": str(cfg.web_root)})
            if name == "page" and cfg.artifact:
                rel = self._artifact_rel(params)
                pages = artifacts.page_images(cfg, cfg.web_root / rel) if rel else []
                try:
                    n = int(params.get("n", ["0"])[0])
                except ValueError:
                    n = 0
                if 1 <= n <= len(pages):
                    return self._send(pages[n - 1].read_bytes(), "image/png")
                return self.send_json({"ok": False}, 404)
            if name == "proposal-diff":
                return self.send_json({"ok": True, "diff": st.proposals.diff(params.get("name", [""])[0])})
            if name == "capture":
                path = capture_path(cfg, params.get("id", [""])[0])
                if path and path.is_file():
                    return self._send(path.read_bytes(), "image/png" if path.suffix == ".png" else "image/jpeg")
                return self.send_json({"ok": False, "message": "그런 캡처가 없어요."}, 404)
            if name == "ai-job":
                return self.send_json(st.ai.public(params.get("id", [""])[0]) or {"ok": False, "status": "gone"})
            if name == "requests":
                return self.send_json({"ok": True, "items": list_requests(cfg), "dir": str(cfg.requests_dir)})
            if name == "request":
                stem = Path(params.get("name", [""])[0]).name
                for sub in (cfg.requests_dir, cfg.requests_dir / "applied"):
                    path = sub / f"{stem}.json"
                    if stem and path.is_file():
                        return self.send_json(json.loads(path.read_text(encoding="utf-8")))
                return self.send_json({"ok": False, "message": "그런 저장본이 없어요."}, 404)
            self.send_json({"ok": False}, 404)

        # ----- 쓰기 요청 -----
        def do_POST(self) -> None:  # noqa: N802
            self._write_request()

        def do_PUT(self) -> None:  # noqa: N802
            self._write_request()

        def do_PATCH(self) -> None:  # noqa: N802
            self._write_request()

        def do_DELETE(self) -> None:  # noqa: N802
            self._write_request()

        def _write_request(self) -> None:
            if not self._host_ok():
                self._body()
                return self.send_json({"ok": False, "message": "허용되지 않은 호스트예요."}, 403)
            route = urlparse(self.path).path
            if route.startswith("/__studio/"):
                # CSRF: 브라우저가 다른 사이트에서 몰래 보낼 수 있는 요청은 application/json 을 못 붙인다.
                # (Daling 안에 있던 시절 이 검사가 빠져, 아무 웹사이트나 Claude 에게 일을 시킬 수 있었다.)
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if self.command != "POST" or ctype != "application/json":
                    self._body()
                    return self.send_json({"ok": False, "message": "잘못된 요청이에요."}, 403)
                if st.args.snapshot:
                    # 사진용 서버는 Claude 가 고친 시안 화면을 띄운다. 그 화면의 스크립트가 저장·반영·AI 를 부르지 못하게
                    self._body()
                    return self.send_json({"ok": False, "message": "사진용 서버에서는 하지 않아요."}, 403)
                return self._studio_post(route[len("/__studio/"):])
            self._dispatch()

        def _studio_post(self, name: str) -> None:
            if int(self.headers.get("Content-Length") or 0) > MAX_POST:
                self._body()
                return self.send_json({"ok": False, "message": "너무 커요."}, 413)
            payload = self._json_body()
            if name == "capture":
                return self._save_capture(payload)
            if name == "attach":
                return self._attach(payload)
            if name == "save":
                return self._save_request(payload)
            if name.startswith("ai/"):
                action = name[3:]
                if not st.claude_ok:
                    return self.send_json({"ok": False, "message": "이 컴퓨터에서 claude 명령을 못 찾았어요."}, 400)
                if action == "suggest":
                    return self.send_json({"ok": True, "id": st.ai.suggest(payload.get("context") or {})["id"]})
                if action == "flow":
                    return self.send_json({"ok": True, "id": st.ai.flow(payload.get("target") or {})["id"]})
                if action == "cancel":
                    st.ai.cancel(str(payload.get("id") or ""))
                    return self.send_json({"ok": True})
            if name.startswith("proposal/"):
                return self._proposal_action(name.split("/", 1)[1], payload)
            self.send_json({"ok": False}, 404)

        def _save_request(self, payload: dict) -> None:
            data = payload.get("data")
            if not isinstance(data, dict):
                return self.send_json({"ok": False, "message": "저장할 내용이 비었어요."}, 400)
            cfg.requests_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            stem = stamp + (("-" + _slug(str(data.get("title") or ""))) if data.get("title") else "")
            n = 2
            while (cfg.requests_dir / f"{stem}.json").exists():
                stem, n = f"{stamp}-{n}", n + 1
            data["savedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
            data["app"] = cfg.name
            data["file"] = f"{cfg.rel(cfg.requests_dir)}/{stem}.json"
            (cfg.requests_dir / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            (cfg.requests_dir / f"{stem}.md").write_text(str(payload.get("markdown") or ""), encoding="utf-8")
            self.send_json({"ok": True, "name": stem, "path": str(cfg.requests_dir / f"{stem}.md")})

        def _save_capture(self, payload: dict) -> None:
            """캡처(탭 화면에서 잘라 낸 그림)를 <workDir>/captures/ 에 둔다. 저장본에는 이름만 들어간다.
            그림을 저장본 JSON·브라우저 임시본에 통째로 넣으면 localStorage 한도(약 5MB)를 몇 장 만에 넘었다."""
            data = str(payload.get("data") or "")
            m = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)", data)
            if not m:
                return self.send_json({"ok": False, "message": "그림이 아니에요."}, 400)
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except (ValueError, binascii.Error):
                return self.send_json({"ok": False, "message": "그림을 읽지 못했어요."}, 400)
            ext = "png" if m.group(1) == "png" else "jpg"
            magic = b"\x89PNG\r\n\x1a\n" if ext == "png" else b"\xff\xd8\xff"
            if not raw.startswith(magic):
                return self.send_json({"ok": False, "message": "그림이 아니에요."}, 400)
            folder = captures_dir(cfg)
            folder.mkdir(parents=True, exist_ok=True)
            cid = datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()
            (folder / f"{cid}.{ext}").write_bytes(raw)
            self.send_json({"ok": True, "id": cid, "file": f"{cfg.rel(folder)}/{cid}.{ext}"})

        def _attach(self, payload: dict) -> None:
            """받은 편지함에 파일을 첨부한다 (끌어 놓기·＋ 첨부). 남의 폴더에는 쓰지 않으려고 받은 편지함에서만 받는다."""
            if not cfg.inbox:
                return self.send_json({"ok": False, "message": "첨부는 받은 편지함에서만 돼요."}, 400)
            name = Path(str(payload.get("name") or "")).name.strip()
            name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)[:120].lstrip(".")
            data = str(payload.get("data") or "")
            m = re.fullmatch(r"data:[^;,]*(;base64)?,(.*)", data, re.S)
            if not name or not m or not m.group(1):
                return self.send_json({"ok": False, "message": "파일을 읽지 못했어요."}, 400)
            try:
                raw = base64.b64decode(m.group(2))
            except (ValueError, binascii.Error):
                return self.send_json({"ok": False, "message": "파일을 읽지 못했어요."}, 400)
            target = cfg.web_root / name
            stem, suffix, k = target.stem, target.suffix, 2
            while target.exists():  # 같은 이름이 있으면 덮지 않고 (2) 를 붙인다
                target = cfg.web_root / f"{stem} ({k}){suffix}"
                k += 1
            target.write_bytes(raw)
            self.send_json({"ok": True, "file": target.name, "kind": artifacts.kind_of(target)})

        def _proposal_action(self, action: str, payload: dict) -> None:
            name = Path(str(payload.get("name") or "")).name
            request = Path(str(payload.get("request") or "")).name
            pm = st.proposals
            try:
                if action in ("start", "revise") and not cfg.proposals:
                    raise ValueError("이 앱은 시안을 만들지 않게 설정돼 있어요. 저장본을 Claude Code 에 넘겨 주세요.")
                if action in ("start", "revise") and not (request and (cfg.requests_dir / f"{request}.json").is_file()):
                    raise ValueError("저장본을 못 찾았어요.")
                queue = [Path(str(q)).name for q in (payload.get("queue") or [])][:30]
                if any(not (cfg.requests_dir / f"{q}.json").is_file() for q in queue):
                    raise ValueError("목록의 저장본을 못 찾았어요.")
                agent = str(payload.get("agent") or "claude")
                if action == "start" and not st.agents.get(agent):
                    raise ValueError("그 AI 명령을 이 컴퓨터에서 못 찾았어요.")
                if action == "start":
                    meta = pm.create(request, str(payload.get("title") or ""), queue, agent)
                    return self.send_json({"ok": True, "name": meta["name"]})
                if action == "revise":
                    pm.revise(name, request, queue)
                    return self.send_json({"ok": True, "name": name})
                if action == "cancel":
                    pm.cancel(name)
                    return self.send_json({"ok": True})
                if action == "apply":
                    return self.send_json({"ok": True, "report": pm.apply(name)})
                if action == "discard":
                    pm.discard(name)
                    return self.send_json({"ok": True})
                self.send_json({"ok": False, "message": "모르는 요청이에요."}, 404)
            except ValueError as exc:
                self.send_json({"ok": False, "message": str(exc)}, 400)
            except OSError as exc:
                self.send_json({"ok": False, "message": f"파일을 다루지 못했어요 ({exc.strerror or exc})."}, 500)

        # ----- 앱으로 넘기기 -----
        def _dispatch(self) -> None:
            route = urlparse(self.path).path
            kind, value = cfg.decide(self.command, route)
            body = self._body() if self.command not in ("GET", "HEAD") else b""
            if st.upstream is None:  # 작업물 모드: 앱이 없다. 없는 파일은 404, 쓰기는 했다 치고
                if kind == "pass":
                    return self.send_json({"ok": False, "message": "없는 파일이에요."}, 404)
                kind = "fake"
            if kind == "deny":
                return self.send_json({"ok": False, "studio": True, "message": "디자인 스튜디오에서는 하지 않아요."}, 400)
            if kind == "mock":
                return self.send_json(value)
            if kind == "fake":
                return self.send_json({"ok": True, "studio": True, "message": "디자인 스튜디오라 실제로는 하지 않았어요."})
            try:
                status, headers, data = self._upstream(self.command, self.path, body)
            except OSError as exc:
                return self.send_json({"ok": False, "message": f"앱 서버에 닿지 못했어요 ({exc})."}, 502)
            self.send_response(status)
            # 앱이 준 캐시 머리글은 버리고 늘 새로 받게 한다. 앱 서버가 캐시 머리글 없이 Last-Modified 만 주면 브라우저가
            # 스스로 '아직 신선' 하다고 보고, 시안으로 바꿔 다시 띄워도 예전 styles.css 를 그대로 썼다(시험에서 재현).
            self.send_header("Cache-Control", "no-store")
            for k, v in headers.items():
                if k not in HOP and k not in NO_CACHE:
                    if k == "location" and v.startswith(f"http://{st.upstream.netloc}"):
                        v = v[len(f"http://{st.upstream.netloc}"):] or "/"
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _upstream(self, method: str, path: str, body: bytes, identity: bool = False) -> tuple[int, dict, bytes]:
            conn = http.client.HTTPConnection(st.upstream.hostname, st.upstream.port or 80, timeout=120)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}
            headers["Host"] = st.upstream.netloc
            if identity:
                headers["Accept-Encoding"] = "identity"
            if body:
                headers["Content-Length"] = str(len(body))
            try:
                conn.request(method, path, body=body or None, headers=headers)
                res = conn.getresponse()
                data = res.read()
                # 같은 이름 머리글(Set-Cookie 등)은 합치지 않고 마지막 것만 남는다. 앱이 쿠키를 여러 개 굽는다면 여기를 고친다.
                return res.status, {k.lower(): v for k, v in res.getheaders()}, data
            finally:
                conn.close()

    return Handler


MAX_POST = 16 * 1024 * 1024  # 캡처 한 장(큰 화면 PNG)이 들어갈 만큼만
CAPTURE_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")


def captures_dir(cfg: appconfig.AppConfig) -> Path:
    return cfg.work_dir / "captures"


def capture_path(cfg: appconfig.AppConfig, cid: str) -> Path | None:
    # 이름 모양을 정해 두고 그 모양만 받는다 (경로 문자로 다른 파일을 읽지 못하게)
    if not CAPTURE_ID.fullmatch(cid or ""):
        return None
    for ext in ("png", "jpg"):
        path = captures_dir(cfg) / f"{cid}.{ext}"
        if path.is_file():
            return path
    return None


def _insert_before(html: str, tag: str, text: str) -> str:
    i = html.lower().rfind(tag)
    return html[:i] + text + html[i:] if i >= 0 else html + text


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _slug(text: str) -> str:
    return re.sub(r"[^\w가-힣-]+", "-", text).strip("-")[:40]


def list_requests(cfg: appconfig.AppConfig) -> list[dict]:
    out = []
    for sub, applied in ((cfg.requests_dir, False), (cfg.requests_dir / "applied", True)):
        if not sub.exists():
            continue
        for path in sub.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({
                "name": path.stem, "applied": applied, "title": data.get("title", ""), "savedAt": data.get("savedAt", ""),
                "comments": len(data.get("comments") or []),
                "changes": sum(len(v.get("changes") or []) for v in data.get("variants") or []),
            })
    out.sort(key=lambda r: r["name"], reverse=True)
    return out


class ExclusiveServer(ThreadingHTTPServer):
    # Windows 는 SO_REUSEADDR 로 남이 쓰는 포트를 겹쳐 잡을 수 있다. 혼자 잡는다.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = None
    if args.target:
        t = Path(args.target).expanduser()
        found = appconfig.find_app_config(t) if t.is_dir() else None
        if found:  # 개인화한 앱 저장소를 가리켰으면 앱 모드
            args.project = str(t)
            cfg = appconfig.load(found, t, args.mode or None)
        else:
            cfg = artifacts.make_config(t)
    else:
        app = Path(args.app) if args.app else appconfig.find_app_config(args.project or ".")
        if app and app.is_file():
            cfg = appconfig.load(app, args.project or None, args.mode or None)
        elif args.project or args.app:
            sys.exit("이 앱의 스튜디오 설정이 없어요. 먼저 `python -m studio init --project <앱 저장소>` 로 만들고 다듬어 주세요.")
        else:
            print("앱 설정이 없어 받은 편지함으로 열어요 (파일을 끌어 놓아 첨부). 웹 앱이면 먼저 `init`.", flush=True)
            cfg = artifacts.make_config(None)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # 끌 때도 앱 서버를 함께 끄게 (atexit)
    if not args.snapshot:
        appconfig.write_session(cfg)
    upstream, _proc, _log = start_app(cfg)
    st = Studio(args, cfg, upstream)
    server = None
    for port in range(args.port, args.port + 20):
        try:
            server = ExclusiveServer(("127.0.0.1", port), build_handler(st))
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"{args.port}~{args.port + 19} 포트가 모두 쓰이고 있어요.")
    st.port = server.server_address[1]
    url = f"http://127.0.0.1:{st.port}/"
    print(f"디자인 스튜디오 · {cfg.name} ({cfg.mode}) : {url}", flush=True)
    print(f"앱 서버: {upstream}" if upstream else f"작업물: {cfg.web_root}" + (f" / {cfg.entry}" if cfg.entry else ""), flush=True)
    print(f"저장 위치: {cfg.requests_dir}", flush=True)
    print(f"시안 만들기(claude): {st.proposals.claude_path() or '없음 — 저장본을 직접 Claude Code 에 넘겨 주세요'}", flush=True)
    others = [a for a in ("gemini", "codex") if st.agents.get(a)]
    if others:
        print(f"다른 AI 로 고치기: {', '.join(others)}", flush=True)
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
