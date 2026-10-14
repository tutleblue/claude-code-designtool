"""앱 설정(studio.app.json) 읽기.

스튜디오 본체는 어떤 앱인지 모른다. 앱마다 다른 것(어떻게 띄우는지, 화면 파일이 어디 있는지, 어떤 요청을 통과시키는지,
Claude 에게 알려 줄 앱 규칙)은 전부 이 설정 하나에 적는다.

    {
      "name": "Hello",                       # 화면 맨 위·요청 글에 쓰는 앱 이름
      "webRoot": "web",                      # 프로젝트 기준 화면 파일 폴더 (시안은 이 폴더의 글자 파일을 복사해 고친다)
      "workDir": ".design-studio",           # 프로젝트 기준 저장본·시안 폴더 (대상 저장소의 .gitignore 에 넣는다)
      "context": "studio/context.md",        # 설정 파일 기준. Claude 에게 줄 앱 규칙 (짧게)
      "client": "studio/studio.app.js",      # 설정 파일 기준. 화면 이름·테마·토큰을 알려 주는 스크립트 (없어도 된다)
      "checks": ["node --check {web}/app.js"],   # 시안에서 Claude 가 돌려도 되는 확인 명령 (정확히 이 글자만 허락)
      "modes": {
        "demo": {
          "launch": ["{python}", "{config_dir}/run_demo.py", "--project", "{project}", "--port", "{port}"],
          "requests": {"pass": ["POST /api/timetable/*"]}
        },
        "real": {"launch": ["..."], "requests": {"pass": []}}
      },
      "requests": {
        "mock": {"GET /api/notices": {"ok": true, "items": []}},
        "deny": ["GET /api/mail/eml"]
      }
    }

자리표: {python} 스튜디오를 띄운 파이썬, {venv_python} 앱 저장소의 .venv 파이썬(없으면 {python}), {project} 프로젝트 폴더, {config_dir} 설정 파일 폴더, {port} 앱에 줄 빈 포트,
{studio} 스튜디오 저장소 폴더. launch 대신 "upstream": "http://127.0.0.1:5173" 처럼 이미 떠 있는 앱 주소를 적어도 된다.

요청 규칙 (메서드 경로, 경로는 * 와일드카드):
  deny  → 403 (그 모드에서 절대 앱에 닿으면 안 되는 것)
  mock  → 적어 둔 JSON 을 그대로 답 (바깥 서버에서 받아 오는 GET 을 그럴듯한 빈 답으로)
  pass  → 앱에 그대로 넘김
  기본  → GET·HEAD 는 넘기고, 나머지(POST·PUT·PATCH·DELETE)는 '했다 치고' 가짜 답. 실제로는 아무것도 하지 않는다.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

STUDIO_HOME = Path(__file__).resolve().parent.parent


@dataclass
class AppConfig:
    path: Path
    project: Path
    mode: str
    name: str = "앱"
    web_root: Path = field(default_factory=Path)
    work_dir: Path = field(default_factory=Path)
    context_path: Path | None = None
    client_path: Path | None = None
    checks: list[str] = field(default_factory=list)
    launch: list[str] = field(default_factory=list)
    upstream: str = ""
    passes: list[str] = field(default_factory=list)
    mocks: dict[str, object] = field(default_factory=dict)
    denies: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)

    @property
    def requests_dir(self) -> Path:
        return self.work_dir / "requests"

    @property
    def proposals_dir(self) -> Path:
        return self.work_dir / "proposals"

    def rel(self, path: Path) -> str:
        """프로젝트 기준 경로 (Claude 권한 규칙·안내 글에 쓴다). 프로젝트 밖이면 절대 경로."""
        try:
            return path.resolve().relative_to(self.project.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def context_text(self, limit: int = 6000) -> str:
        if not self.context_path or not self.context_path.exists():
            return ""
        return self.context_path.read_text(encoding="utf-8")[:limit]

    # ---------- 요청 규칙 ----------
    @staticmethod
    def _match(rule: str, method: str, path: str) -> bool:
        m, _, pattern = rule.strip().partition(" ")
        if not pattern:  # 메서드를 안 적으면 모든 메서드
            m, pattern = "*", m
        return (m == "*" or m.upper() == method) and fnmatch.fnmatchcase(path, pattern)

    def decide(self, method: str, path: str) -> tuple[str, object]:
        """('deny'|'mock'|'pass'|'fake', mock 값)."""
        method = method.upper()
        if any(self._match(r, method, path) for r in self.denies):
            return "deny", None
        for rule, value in self.mocks.items():
            if self._match(rule, method, path):
                return "mock", value
        if any(self._match(r, method, path) for r in self.passes):
            return "pass", None
        if method in ("GET", "HEAD"):
            return "pass", None
        return "fake", None


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def load(config_path: str | Path, project: str | Path | None, mode: str | None) -> AppConfig:
    path = Path(config_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    proj = Path(project).resolve() if project else Path(_fill(str(data.get("project") or "."), {})).expanduser()
    if not proj.is_absolute():
        proj = (base / proj).resolve()
    modes = data.get("modes") or {}
    names = list(modes) or ["default"]
    mode = mode or names[0]
    if modes and mode not in modes:
        sys.exit(f"설정에 없는 모드예요: {mode} (있는 것: {', '.join(names)})")
    m = modes.get(mode) or {}
    shared = data.get("requests") or {}
    own = m.get("requests") or {}

    cfg = AppConfig(
        path=path, project=proj, mode=mode, modes=names,
        name=str(data.get("name") or proj.name),
        web_root=(proj / str(data.get("webRoot") or "web")).resolve(),
        work_dir=(proj / str(data.get("workDir") or ".design-studio")).resolve(),
        context_path=(base / data["context"]).resolve() if data.get("context") else None,
        client_path=(base / data["client"]).resolve() if data.get("client") else None,
        checks=list(data.get("checks") or []),
        launch=list(m.get("launch") or data.get("launch") or []),
        upstream=str(m.get("upstream") or data.get("upstream") or ""),
        passes=list(shared.get("pass") or []) + list(own.get("pass") or []),
        mocks={**(shared.get("mock") or {}), **(own.get("mock") or {})},
        denies=list(shared.get("deny") or []) + list(own.get("deny") or []),
    )
    if cfg.web_root == cfg.project or cfg.project not in cfg.web_root.parents:
        sys.exit("webRoot 는 프로젝트 안의 하위 폴더여야 해요 (예: \"web\", \"public\"). 시안 권한을 그 폴더로만 좁히기 때문이에요.")
    if cfg.project not in cfg.work_dir.parents or cfg.web_root in cfg.work_dir.parents or cfg.work_dir == cfg.web_root:
        sys.exit("workDir 는 프로젝트 안, 화면 폴더 밖이어야 해요 (기본 .design-studio).")
    if not cfg.launch and not cfg.upstream:
        sys.exit("설정에 launch(앱을 띄우는 명령)나 upstream(이미 떠 있는 앱 주소) 중 하나는 있어야 해요.")
    return cfg


def venv_python(project: Path) -> str:
    """앱 저장소의 가상환경 파이썬 (앱 의존성이 거기 있다). 없으면 스튜디오의 파이썬."""
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python", "venv/Scripts/python.exe", "venv/bin/python"):
        if (project / rel).is_file():
            return str(project / rel)
    return sys.executable


def fill_launch(cfg: AppConfig, port: int) -> list[str]:
    values = {"python": sys.executable, "venv_python": venv_python(cfg.project), "project": str(cfg.project),
              "config_dir": str(cfg.path.parent), "port": str(port), "studio": str(STUDIO_HOME)}
    return [_fill(part, values) for part in cfg.launch]


def fill_upstream(cfg: AppConfig, port: int) -> str:
    return _fill(cfg.upstream or "http://127.0.0.1:{port}", {"port": str(port)}).rstrip("/")


def fill_check(cfg: AppConfig, check: str, web_rel: str) -> str:
    return _fill(check, {"web": web_rel, "python": sys.executable})


def session_file(project: Path) -> Path:
    """스튜디오가 이 프로젝트로 떴다는 기록 (snapshot 이 앱 설정을 찾는 곳). 스튜디오 저장소 안이라 시안의 Claude 는 못 고친다."""
    key = hashlib.sha1(str(Path(project).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return STUDIO_HOME / ".sessions" / f"{key}.json"


def write_session(cfg: AppConfig) -> None:
    sf = session_file(cfg.project)
    sf.parent.mkdir(parents=True, exist_ok=True)
    # 사진은 첫 모드(보통 demo, 가짜 데이터)로 찍는다
    sf.write_text(json.dumps({"app": str(cfg.path), "project": str(cfg.project), "mode": cfg.modes[0]},
                             ensure_ascii=False, indent=1), encoding="utf-8")
