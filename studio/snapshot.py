r"""저장본을 '지금 화면' 과 '요청한 화면' 으로 찍어 나란히 비교한다.

    (앱 저장소 폴더에서) python <스튜디오>/studio/snapshot.py <저장본 이름>            (반영 전: now + target)
    ... snapshot.py <이름> --tag after                                              (반영 뒤: 지금 소스로 다시)
    ... snapshot.py <이름> --web .design-studio/proposals/<이름>/web --tag proposal  (시안 폴더로 찍기)
    옵션: --views dashboard,emails  --theme dark  --width 1440 --height 900

- now    : 지금 소스 그대로 (스튜디오 도구는 감춤)
- target : 지금 소스 + 저장본의 고른 조합을 덮어쓴 모습 = 사용자가 본 그 화면 (처음 한 번만 찍는다)
- after  : 반영한 뒤의 지금 소스. target 과 같아 보이면 잘 옮긴 것이다.

앱 설정·프로젝트는 인자로 받지 않는다. 이 폴더(앱 저장소)에서 스튜디오를 띄울 때 남긴 세션 파일에서 읽는다.
Claude 가 시안을 확인하려고 이 명령을 쓰는데, --app 을 받으면 지어낸 설정으로 아무 명령이나 띄울 수 있기 때문이다.
사진은 <workDir>/requests/shots/<이름>/ 에 남는다. 스튜디오 서버는 이 스크립트가 따로 띄웠다 끈다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 바로 부를 때
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.config import STUDIO_HOME, load, session_file  # noqa: E402

# 화면 이름·태그·테마는 파일 이름·주소가 된다. 경로나 다른 인자가 되지 못하게 모양을 정해 둔다.
SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")
REQUEST_NAME = re.compile(r"[\w가-힣-]{1,100}")


def find_request(requests: Path, name: str) -> Path:
    if not REQUEST_NAME.fullmatch(name):
        sys.exit("저장본 이름이 이상해요.")
    for sub in (requests, requests / "applied"):
        exact = sub / f"{name}.json"
        if exact.is_file():
            return exact
        hits = sorted(sub.glob(f"{name}*.json"))
        if hits:
            return hits[-1]
    sys.exit(f"저장본을 못 찾았어요: {name}")


def start_server(session: dict, port: int, web: str = "") -> tuple[subprocess.Popen, str]:
    extra = ["--web", web] if web else []
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "studio", "--app", session["app"], "--project", session["project"],
         "--mode", session["mode"], "--no-open", "--snapshot", "--port", str(port), *extra],
        cwd=STUDIO_HOME, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )
    deadline = time.time() + 90
    lines = []
    while time.time() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        lines.append(line)
        if line.startswith("디자인 스튜디오") and "http://" in line:
            return proc, line[line.index("http://"):].strip()
        if proc.poll() is not None:
            break
    proc.kill()
    sys.exit("스튜디오 서버를 띄우지 못했어요.\n" + "".join(lines[-20:]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--tag", default="", help="now(기본, 반영 전)·after(반영 뒤)·proposal(시안)")
    ap.add_argument("--views", default="", help="찍을 화면 (쉼표). 비우면 저장본에 나온 화면 전부")
    ap.add_argument("--theme", default="", help="테마 키 (비우면 저장본 테마)")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--web", default="", help="시안 폴더로 찍기 (<workDir>/proposals/<이름>/web)")
    args = ap.parse_args()

    sf = session_file(Path.cwd())
    if not sf.is_file():
        sys.exit("이 폴더에서 스튜디오를 띄운 기록이 없어요. 앱 저장소 폴더에서, 스튜디오를 한 번 띄운 뒤 다시 해 주세요.")
    session = json.loads(sf.read_text(encoding="utf-8"))
    cfg = load(session["app"], session["project"], session["mode"])

    tag = args.tag or "now"
    if not SAFE_NAME.fullmatch(tag) or (args.theme and not SAFE_NAME.fullmatch(args.theme)):
        sys.exit("--tag·--theme 는 영문·숫자·-·_ 만 써요.")
    web = ""
    if args.web:
        # 시안 폴더나 진짜 화면 폴더만 찍는다. 다른 폴더를 화면으로 띄우지 않게
        w = (cfg.project / args.web).resolve()
        allowed = (cfg.proposals_dir.resolve(), cfg.web_root.resolve())
        if not any(w == a or a in w.parents for a in allowed):
            sys.exit("--web 은 시안 폴더(<workDir>/proposals/<이름>/web)나 화면 폴더만 돼요.")
        web = str(w)

    path = find_request(cfg.requests_dir, args.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    stem = path.stem
    variants = data.get("variants") or [{}]
    chosen = min(max(int(data.get("chosen") or 0), 0), len(variants) - 1)
    variant = variants[chosen]
    views = [v for v in args.views.split(",") if v]
    if not views:
        seen: list[str] = []
        for c in data.get("comments") or []:
            seen.append(str((c.get("anchor") or {}).get("view", "")))
        for c in variant.get("changes") or []:
            seen.append(str((c.get("target") or {}).get("view", "")))
        seen.append(str(data.get("view") or ""))
        views = [v for i, v in enumerate(seen) if v and v not in seen[:i]] or ["page"]
    views = [v for v in views if SAFE_NAME.fullmatch(v)]
    if not views:
        sys.exit("찍을 화면 이름이 없어요 (영문·숫자·-·_ 만 써요).")
    theme = args.theme or str(data.get("theme") or "")
    if theme and not SAFE_NAME.fullmatch(theme):
        theme = ""
    vp = data.get("viewport") or {}
    width = args.width or int(vp.get("w") or 1440)
    height = args.height or int(vp.get("h") or 900)

    out = cfg.requests_dir / "shots" / stem
    out.mkdir(parents=True, exist_ok=True)
    need_target = not any(out.glob("*-target.png"))

    from playwright.sync_api import sync_playwright

    proc, base = start_server(session, args.port, web)
    saved, errors = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")
            # 시안 화면의 스크립트는 Claude 가 고친 것이다. 이 스튜디오 서버 말고는 어디에도 요청을 못 보내게 막는다.
            ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            th = f"&theme={theme}" if theme else ""
            for view in views:
                shots = [(tag, f"?clean=1&view={view}{th}")]
                if need_target:
                    shots.append(("target", f"?clean=1&pins=1&view={view}{th}&load={stem}&variant={chosen + 1}"))
                for label, query in shots:
                    page.goto(base + query)
                    page.wait_for_timeout(3200)  # 앱 첫 그리기 + 저장본 불러오기 + 화면 전환
                    file = out / f"{view}-{label}.png"
                    page.screenshot(path=str(file))
                    saved.append(str(file))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("\n".join(saved))
    if errors:
        print("화면 오류:", *errors[:10], sep="\n  ")


if __name__ == "__main__":
    main()
