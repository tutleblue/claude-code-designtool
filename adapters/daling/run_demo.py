r"""Daling 앱 서버를 디자인 스튜디오용으로 띄운다 (스튜디오가 이 스크립트를 자식 프로세스로 부른다).

    <Daling 저장소>\.venv\Scripts\python.exe run_demo.py --project <Daling 저장소> --port 0
    --real 을 붙이면 사용자 데이터 폴더(C:\lms-autosaver)를 읽기만 한다.

demo (기본)
  - 데이터 폴더를 임시 폴더로 바꾸고 지어낸 학생 데이터(demo_data)를 채운다. 끝나면 지운다.
  - 바깥 연결을 소켓에서 막는다(LMS·메일·학교 서버에 절대 안 닿는다). 이 프로세스 안에서 막아야 확실하다.
  - 이 컴퓨터의 프록시(127.0.0.1 에서 도는 VPN·보안 도구)를 거쳐 나가지 않게 프록시 설정도 끈다.
real
  - 데이터는 그대로 읽고, 쓰기 요청은 모두 '했다 치고' 답한다(스튜디오도 막지만 한 번 더).

스튜디오 쪽(프록시)에서도 쓰기 요청은 설정의 pass 에 적은 것만 넘어온다.
"""
from __future__ import annotations

import argparse
import atexit
import os
import secrets
import shutil
import socket
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True, help="Daling 저장소 폴더")
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--real", action="store_true", help="내 데이터 폴더를 읽기만")
args = ap.parse_args()

PROJ = Path(args.project).resolve()
if not (PROJ / "web_ui.py").is_file():
    sys.exit(f"Daling 저장소가 아니에요 (web_ui.py 없음): {PROJ}")
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)
os.environ["AUTOSAVER_OPEN_BROWSER"] = "0"


def _sweep_old_temp() -> None:
    # 강제로 꺼지면(Windows 의 프로세스 끝내기) 정리할 틈이 없다. 띄울 때마다 이틀 넘은 것을 치운다.
    cutoff = time.time() - 2 * 86400
    for d in Path(tempfile.gettempdir()).glob("design-studio-daling-*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


DEMO_ROOT: Path | None = None
if not args.real:
    _sweep_old_temp()
    DEMO_ROOT = Path(tempfile.mkdtemp(prefix="design-studio-daling-"))
    atexit.register(shutil.rmtree, DEMO_ROOT, ignore_errors=True)
    # web_ui 는 AUTOSAVER_ROOT, 작업 프로세스 쪽(runtime_config)은 AUTOSAVER_DATA_ROOT 를 본다. 둘 다 임시 폴더로.
    os.environ["AUTOSAVER_ROOT"] = str(DEMO_ROOT)
    os.environ["AUTOSAVER_DATA_ROOT"] = str(DEMO_ROOT)
    os.environ["AUTOSAVER_CONFIG_PATH"] = str(DEMO_ROOT / "config.json")
    os.environ["AUTOSAVER_GOOGLE_CLIENT_SECRETS"] = str(DEMO_ROOT / "credentials.json")

    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    _real_connect = socket.socket.connect
    _real_getaddrinfo = socket.getaddrinfo

    def _guard_connect(self, address):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(host, str) and host not in _LOOPBACK:
            raise OSError(f"디자인 스튜디오(demo)는 바깥 연결을 막습니다: {host}")
        return _real_connect(self, address)

    def _guard_getaddrinfo(host, *a, **kw):  # type: ignore[no-untyped-def]
        if host not in _LOOPBACK and host is not None:
            raise socket.gaierror(f"디자인 스튜디오(demo)는 바깥 연결을 막습니다: {host}")
        return _real_getaddrinfo(host, *a, **kw)

    socket.socket.connect = _guard_connect  # type: ignore[method-assign]
    socket.getaddrinfo = _guard_getaddrinfo  # type: ignore[assignment]
    # 루프백 프록시를 거치면 '루프백 연결' 로 통과해 바깥으로 나간다(실제로 학교 서버에 요청이 나갔다). 프록시를 아예 끈다.
    import urllib.request

    for _key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_key, None)
    os.environ["NO_PROXY"] = "*"
    urllib.request.getproxies = lambda: {}  # type: ignore[assignment]

import web_ui  # noqa: E402  (데이터 경로를 잡은 뒤에 불러야 한다)

try:
    VERSION = (PROJ / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = ""

if DEMO_ROOT is not None:
    sys.path.insert(0, str(HERE))
    import demo_data  # noqa: E402

    demo_data.build(DEMO_ROOT, VERSION)

    # 화면이 'LMS·메일 연결됨' 으로 보이게 비밀번호 칸을 채운다. 실행마다 새로 만드는 무작위 값이고
    # 파일에도 코드에도 남지 않는다. demo 는 바깥 연결이 막혀 있어 어디에도 쓰이지 않는다.
    _FILLER = secrets.token_hex(8)
    _real_read_config = web_ui.read_config

    def _demo_read_config(workspace):  # type: ignore[no-untyped-def]
        cfg = _real_read_config(workspace)
        for _k in ("LMS_PASSWORD", "EMAIL_PASSWORD"):
            cfg.setdefault(_k, _FILLER)
        return cfg

    web_ui.read_config = _demo_read_config


class Handler(web_ui.DashboardHandler):
    def _do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/update/check":
            # 업데이트 확인은 GitHub 에 나간다. 스튜디오에서는 늘 '최신' 으로
            self.send_json({"ok": True, "available": False, "current": VERSION, "latest": VERSION})
            return
        super()._do_GET()

    def _do_POST(self) -> None:  # noqa: N802
        if args.real:
            # 사용자 데이터 폴더에 쓰지 않는다 (스튜디오도 막지만 설정을 잘못 적어도 안전하게)
            self.read_body_json()
            self.send_json({"ok": True, "studio": True, "message": "디자인 스튜디오라 실제로는 하지 않았어요."})
            return
        super()._do_POST()


def main() -> None:
    import signal

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # 스튜디오가 끌 때도 임시 폴더를 치우게
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Daling ({'real' if args.real else 'demo'}) : http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
