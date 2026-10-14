r"""개인화 설정이 이 앱에 잘 맞는지 점검한다. Claude 가 개인화를 다듬을 때마다 돌려 모두 통과(또는 이유 있는 주의)가 되게 한다.

    python -m studio doctor --project <앱 저장소> [--mode demo] [--screenshot]

보는 것
  설정    파일·화면 폴더·앱 규칙·client 스크립트가 있는지, 시안 권한을 좁힐 수 있는 구조인지
  띄우기  스튜디오가 앱을 띄우고 첫 화면에 도구를 끼워 넣는지
  화면    (Playwright 가 있으면) 콘솔 오류, 도구 막대, 토큰 수, 테마마다 바꾸기, 화면마다 이동, 바깥으로 나가는 요청
  막기    앱의 쓰기 요청이 가짜 답을 받는지
  확인 명령  설정의 checks 가 지금 소스에서 통과하는지
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import config as appconfig

rows: list[tuple[str, str, str]] = []


def row(level: str, name: str, detail: str = "") -> None:
    rows.append((level, name, detail))
    print(f"[{level}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def start(args, app: Path, port: int) -> tuple[subprocess.Popen, str]:
    cmd = [sys.executable, "-X", "utf8", "-m", "studio", "open", "--app", str(app), "--project", args.project,
           "--no-open", "--snapshot", "--port", str(port)]
    if args.mode:
        cmd += ["--mode", args.mode]
    proc = subprocess.Popen(cmd, cwd=appconfig.STUDIO_HOME, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines = []
    deadline = time.time() + 120
    while time.time() < deadline:
        line = proc.stdout.readline()
        lines.append(line)
        if line.startswith("디자인 스튜디오") and "http://" in line:
            return proc, line[line.index("http://"):].strip()
        if proc.poll() is not None:
            break
    proc.kill()
    return proc, "\n".join(x.rstrip() for x in lines[-25:] if x.strip())


def browser(url: str, cfg: appconfig.AppConfig, shot: Path | None) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        row("주의", "화면 점검 건너뜀", "Playwright 가 없어요 (pip install playwright)")
        return
    host = "document.querySelector('#__studio').shadowRoot"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
        app_err, studio_err, outside = [], [], []
        def on_err(text: str) -> None:
            (studio_err if "/__studio/" in text or "studio" in text.lower() else app_err).append(text[:200])
        pg.on("pageerror", lambda e: on_err(f"{e}\n{getattr(e, 'stack', '') or ''}"))
        pg.on("console", lambda m: on_err(m.text + " " + str(m.location.get("url", ""))) if m.type == "error" else None)
        pg.on("request", lambda r: outside.append(r.url) if not r.url.startswith(url) and r.url.startswith("http") else None)
        pg.add_init_script("try { localStorage.setItem('studio-ai-auto', 'false') } catch (e) {}")
        pg.goto(url)
        pg.wait_for_timeout(3500)
        frames = pg.main_frame.child_frames
        if not frames:
            row("실패", "앱 iframe 이 없어요")
            return
        fr = frames[0]
        if shot:
            pg.screenshot(path=str(shot))
        bar = pg.evaluate(f"() => !!{host}.querySelector('.bar')")
        row("통과" if bar else "실패", "도구 막대가 뜸")
        has_app = fr.evaluate("() => !!window.__STUDIO_APP__")
        if cfg.client_path:
            row("통과" if has_app else "실패", "client 스크립트(window.__STUDIO_APP__) 읽힘")
        tokens = pg.evaluate(f"() => {host}.querySelectorAll('[data-pick=\"token\"]').length")
        row("통과" if tokens else "주의", "색 토큰", f"{tokens}개" + ("" if tokens else " — CSS 변수가 없으면 요소별 색 바꾸기만 돼요"))

        themes = pg.evaluate(f"() => [...{host}.querySelectorAll('[data-theme-set]')].map(b => b.dataset.themeSet)")
        if len(themes) > 1:
            bad = []
            for key in themes:
                pg.evaluate(f"(k) => {host}.querySelector(`[data-theme-set=\"${{k}}\"]`).click()", key)
                pg.wait_for_timeout(250)
                ok = fr.evaluate("""(k) => { const t = (window.__STUDIO_APP__?.themes || []).find(x => x.key === k);
                  if (!t || !t.selector) return true; try { return document.documentElement.matches(t.selector); } catch { return false; } }""", key)
                if not ok:
                    bad.append(key)
            pg.evaluate(f"(k) => {host}.querySelector(`[data-theme-set=\"${{k}}\"]`).click()", themes[0])
            row("통과" if not bad else "실패", f"테마 {len(themes)}개 바꾸기", "안 맞음: " + ", ".join(bad) if bad else ", ".join(themes))
        views = fr.evaluate("() => Object.keys(window.__STUDIO_APP__?.views || {})")
        if views:
            if not fr.evaluate("() => !!window.__STUDIO_APP__?.switchView"):
                row("실패", "화면 이동", "views 는 있는데 switchView 가 없어요")
            else:
                bad = []
                for v in views[:12]:
                    fr.evaluate("(v) => window.__STUDIO_APP__.switchView(v)", v)
                    pg.wait_for_timeout(450)
                    now = fr.evaluate("() => window.__STUDIO_APP__.currentView?.()")
                    if now != v:
                        bad.append(f"{v}→{now}")
                fr.evaluate("(v) => window.__STUDIO_APP__.switchView(v)", views[0])
                row("통과" if not bad else "실패", f"화면 {min(len(views), 12)}개 이동", "; ".join(bad) if bad else ", ".join(views[:12]))
        probe = fr.evaluate("""async () => { try { const r = await fetch('/__studio-doctor-probe', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: '{}'}); return await r.json(); } catch (e) { return {error: String(e)}; } }""")
        row("통과" if probe.get("studio") else "실패", "앱의 쓰기 요청은 가짜 답", json.dumps(probe, ensure_ascii=False)[:120])
        pg.wait_for_timeout(500)
        row("통과" if not app_err else "주의", "앱 콘솔 오류", f"{len(app_err)}개 " + " | ".join(app_err[:3]) if app_err else "0")
        row("통과" if not studio_err else "실패", "스튜디오 콘솔 오류", " | ".join(studio_err[:3]) if studio_err else "0")
        hosts = sorted({u.split("/")[2] for u in outside})
        row("통과" if not hosts else "주의", "브라우저가 바깥으로 보낸 요청",
            ", ".join(hosts[:8]) + (" — 글꼴·CDN 이면 괜찮아요. 앱 데이터면 mock 이나 런처 차단을 생각해요" if hosts else "") if hosts else "없음")
        b.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="studio doctor")
    ap.add_argument("--project", default=".")
    ap.add_argument("--app", default="")
    ap.add_argument("--mode", default="")
    ap.add_argument("--port", type=int, default=8970)
    ap.add_argument("--screenshot", action="store_true", help="화면 사진을 .design-studio/doctor.png 로")
    args = ap.parse_args(argv)
    args.project = str(Path(args.project).resolve())

    app = Path(args.app) if args.app else appconfig.find_app_config(args.project)
    if not app or not app.is_file():
        sys.exit("개인화 설정이 없어요. 먼저 `python -m studio init --project <앱 저장소>`.")
    cfg = appconfig.load(app, args.project, args.mode or None)
    row("통과", "설정 읽힘", f"{cfg.name} · 모드 {cfg.mode} ({', '.join(cfg.modes)}) · {app}")
    row("통과" if (cfg.web_root / "index.html").is_file() else "주의", "화면 폴더", cfg.rel(cfg.web_root))
    if cfg.context_path:
        text = cfg.context_text()
        todo = "(채울 것)" in text or "(앱의 색감" in text
        row("통과" if text and not todo else "주의", "앱 규칙(context)", "아직 채울 칸이 남았어요" if todo else f"{len(text)}자")
    else:
        row("주의", "앱 규칙(context) 없음", "Claude 가 시안·추천에서 앱 규칙을 모르고 일해요")
    if cfg.client_path and not cfg.client_path.is_file():
        row("실패", "client 스크립트 없음", str(cfg.client_path))
    gi = Path(args.project) / ".gitignore"
    ignored = gi.is_file() and any(l.strip().rstrip("/") in (".design-studio", "/.design-studio") for l in gi.read_text(encoding="utf-8", errors="replace").splitlines())
    row("통과" if ignored else "주의", ".gitignore 에 .design-studio/", "" if ignored else "저장본·시안이 git 에 올라갈 수 있어요")

    for check in cfg.checks:
        cmd = appconfig.fill_check(cfg, check, cfg.rel(cfg.web_root))
        try:
            res = subprocess.run(shlex.split(cmd), cwd=cfg.project, capture_output=True, text=True, timeout=60)
            row("통과" if res.returncode == 0 else "실패", f"확인 명령 `{cmd}`", (res.stderr or res.stdout).strip()[-160:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            row("주의", f"확인 명령 `{cmd}`", f"못 돌림: {exc}")

    proc, url = start(args, app, args.port)
    if not url.startswith("http"):
        row("실패", "스튜디오·앱 띄우기", url[-800:])
    else:
        try:
            with urllib.request.urlopen(url + "?frame=1", timeout=30) as r:
                html = r.read().decode("utf-8", "replace")
            row("통과" if "/__studio/studio.js" in html else "실패", "첫 화면에 도구가 끼워짐")
            shot = None
            if args.screenshot:
                cfg.work_dir.mkdir(parents=True, exist_ok=True)
                shot = cfg.work_dir / "doctor.png"
            browser(url, cfg, shot)
            if shot:
                row("통과", "사진", str(shot))
        finally:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
    fails = [r for r in rows if r[0] == "실패"]
    warns = [r for r in rows if r[0] == "주의"]
    print(f"\n통과 {len(rows) - len(fails) - len(warns)} · 주의 {len(warns)} · 실패 {len(fails)}")
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    (cfg.work_dir / "doctor.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
