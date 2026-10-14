"""스튜디오가 Claude Code CLI(`claude -p`)를 띄울 때 쓰는 공통 도구.

- 요청 글은 표준 입력으로 넘긴다. Windows 의 claude.cmd 는 cmd.exe 를 거쳐 한글·줄바꿈·따옴표가 든 인자가 깨질 수 있다.
- 이 서버를 Claude Code 안에서 띄웠으면 그 세션 표시(CLAUDECODE 등)가 물려 내려온다. 새 세션으로 시작하게 지운다.
- 앱 쪽 런처가 바깥 연결을 막더라도 그것은 앱 프로세스 안의 일이다. claude 는 이 서버의 환경 그대로 바깥(Anthropic API)에 나간다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_claude() -> str | None:
    # STUDIO_CLAUDE 가 없는 파일을 가리키면 쓰지 않는다. 처음엔 그대로 믿어서, 시안이 '만드는 중' 에서 영영 멈췄다(검증 중 실측).
    explicit = os.environ.get("STUDIO_CLAUDE")
    if explicit:
        return explicit if Path(explicit).is_file() else shutil.which(explicit)
    return shutil.which("claude")


def child_env(proxy_env: dict | None) -> dict:
    env = os.environ.copy()
    for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "NO_PROXY", "no_proxy"):
        env.pop(key, None)
    env.update(proxy_env or {})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def spawn(args: list[str], prompt: str, cwd: Path, proxy_env: dict | None = None) -> subprocess.Popen:
    proc = subprocess.Popen(
        [find_claude() or "claude", *args], cwd=cwd, env=child_env(proxy_env),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # Windows 에서 검은 창이 뜨지 않게
    )
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass
    return proc


def kill_tree(proc: subprocess.Popen) -> None:
    """claude 를 멈춘다. Windows 의 npm claude.cmd 는 cmd.exe → node 로 뜨므로 terminate() 는 cmd.exe 만 끄고
    node 는 계속 고치고 돈을 쓴다(검토에서 지적). 자식까지 함께 끈다."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()
