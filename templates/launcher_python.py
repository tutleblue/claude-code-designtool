r"""<앱 이름> 을 디자인 스튜디오용으로 띄우는 런처 (스튜디오가 자식 프로세스로 부른다).

    {venv_python} run_demo.py --project <앱 저장소> --port <포트> [--real]

`studio init` 이 이 틀을 .claude/design-studio/run_demo.py 로 복사했다. Claude 가 '고칠 곳' 세 군데를 앱에 맞게 채운다.
(실제 예: Daling 저장소의 .claude/design-studio/run_demo.py)

demo (기본)
  - 데이터 폴더를 임시 폴더로 바꾸고 지어낸 데이터를 채운다. 끝나면 지운다.
  - 바깥 연결을 소켓에서 막는다. 앱 프로세스 안에서 막아야 확실하다.
  - 루프백 프록시(VPN·보안 도구)를 거쳐 나가지 않게 프록시 설정도 끈다.
real
  - 사용자 데이터를 그대로 읽는다. 쓰기 요청은 스튜디오가 가짜 답으로 막는다(설정의 modes.real 에 pass 를 두지 않는다).
"""
from __future__ import annotations

import argparse
import atexit
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True)
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--real", action="store_true")
args = ap.parse_args()

PROJ = Path(args.project).resolve()
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

# ---------- 고칠 곳 1: 데이터 폴더를 가리키는 환경 변수 (앱이 읽는 이름으로) ----------
DATA_ENV_VARS: list[str] = []  # 예: ["APP_DATA_ROOT", "APP_CONFIG_PATH"]
TEMP_PREFIX = "design-studio-app-"


def fill_demo_data(root: Path) -> None:
    """---------- 고칠 곳 2: 지어낸 데이터를 root 에 만든다 (실제 사람 이름·주소·비밀값은 넣지 않는다) ----------"""


def start_server(port: int) -> None:
    """---------- 고칠 곳 3: 앱 서버를 127.0.0.1:port 에 띄우고 끝날 때까지 돈다 ----------
    예) import web_server; web_server.serve(host="127.0.0.1", port=port)
    예) from http.server import ThreadingHTTPServer; ThreadingHTTPServer(("127.0.0.1", port), app.Handler).serve_forever()
    """
    raise SystemExit("run_demo.py 의 start_server 를 앱에 맞게 채워 주세요.")


# ---------- 여기부터는 보통 그대로 둔다 ----------
def _sweep_old_temp() -> None:
    # 강제로 꺼지면(Windows 의 프로세스 끝내기) 정리할 틈이 없다. 띄울 때마다 이틀 넘은 것을 치운다.
    cutoff = time.time() - 2 * 86400
    for d in Path(tempfile.gettempdir()).glob(TEMP_PREFIX + "*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _block_network() -> None:
    loopback = {"127.0.0.1", "::1", "localhost"}
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def guard_connect(self, address):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(host, str) and host not in loopback:
            raise OSError(f"디자인 스튜디오(demo)는 바깥 연결을 막습니다: {host}")
        return real_connect(self, address)

    def guard_getaddrinfo(host, *a, **kw):  # type: ignore[no-untyped-def]
        if host not in loopback and host is not None:
            raise socket.gaierror(f"디자인 스튜디오(demo)는 바깥 연결을 막습니다: {host}")
        return real_getaddrinfo(host, *a, **kw)

    socket.socket.connect = guard_connect  # type: ignore[method-assign]
    socket.getaddrinfo = guard_getaddrinfo  # type: ignore[assignment]
    import urllib.request

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    urllib.request.getproxies = lambda: {}  # type: ignore[assignment]


def main() -> None:
    import signal

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # 스튜디오가 끌 때도 임시 폴더를 치우게
    if not args.real:
        _sweep_old_temp()
        root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        for name in DATA_ENV_VARS:
            os.environ[name] = str(root)
        _block_network()
        fill_demo_data(root)
    start_server(args.port)


if __name__ == "__main__":
    main()
