"""스튜디오 시험: 예제 앱(examples/hello)으로 띄워 화면·저장·불러오기·막기·시안 반영·사진을 확인한다.

    python tests/run.py            (Playwright·Chromium 필요. claude 는 없어도 된다)

실패한 항목이 있으면 끝 코드 1.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELLO = ROOT / "examples" / "hello"
WORK = HELLO / ".design-studio"
sys.path.insert(0, str(ROOT))

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def post(url: str, body: bytes, ctype: str = "application/json", host: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ctype})
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start(port: int) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "studio", "--app", str(HELLO / "studio.app.json"),
                             "--no-open", "--port", str(port)], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line.startswith("디자인 스튜디오") and "http://" in line:
            return proc, line[line.index("http://"):].strip()
        if proc.poll() is not None:
            break
    proc.kill()
    sys.exit("스튜디오를 띄우지 못했어요")


def browser_checks(url: str) -> None:
    from playwright.sync_api import sync_playwright

    host = "document.querySelector('#__studio').shadowRoot"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
        pg.on("console", lambda m: errors.append("console: " + m.text[:160]) if m.type == "error" else None)
        pg.add_init_script("try { localStorage.setItem('studio-ai-auto', 'false') } catch (e) {}")
        pg.goto(url)
        pg.wait_for_timeout(2500)
        app = pg.frame_locator("#app")
        fr = pg.main_frame.child_frames[0]
        check("편집 도구가 앱 위에 뜸", pg.evaluate(f"() => !!{host}.querySelector('.bar')"))
        tokens = pg.evaluate(f"() => [...{host}.querySelectorAll('[data-pick=\"token\"]')].map(b => b.dataset.key)")
        check("CSS 변수를 토큰으로 자동으로 찾음", "--accent" in tokens and "--bg" in tokens, ", ".join(tokens))

        # 고르기 → 글자 크기
        pg.keyboard.press("s")
        box = app.locator(".title").bounding_box()
        pg.mouse.click(box["x"] + 10, box["y"] + 8)
        pg.wait_for_timeout(300)
        pg.evaluate(f"""() => {{ const r = {host}.querySelector('[data-style-range="font-size"]');
          r.dispatchEvent(new PointerEvent('pointerdown', {{bubbles:true, composed:true}})); r.value = 30;
          r.dispatchEvent(new Event('input', {{bubbles:true, composed:true}})); r.dispatchEvent(new Event('change', {{bubbles:true, composed:true}})); }}""")
        pg.wait_for_timeout(300)
        size = fr.evaluate("() => getComputedStyle(document.querySelector('.title')).fontSize")
        check("고른 요소의 글자 크기 바꾸기", size == "30px", size)

        # 오른쪽 단추 메뉴 → 글자 크게 (+2px), 메뉴 밖 누르기는 메뉴만 닫음
        pg.mouse.click(box["x"] + 10, box["y"] + 8, button="right")
        pg.wait_for_timeout(200)
        items = pg.evaluate(f"() => [...{host}.querySelectorAll('.cmenu:not([hidden]) [data-cm]')].map(b => b.dataset.cm)")
        pg.evaluate(f"() => {host}.querySelector('[data-cm=bigger]').click()")
        pg.wait_for_timeout(300)
        size_m = fr.evaluate("() => getComputedStyle(document.querySelector('.title')).fontSize")
        check("오른쪽 단추 메뉴: 뜸·글자 크게", {"select", "comment", "bigger", "revert"} <= set(items) and size_m == "32px", f"{len(items)}개, {size_m}")
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(200)
        # 댓글
        pg.keyboard.press("c")
        hb = app.locator(".hint").bounding_box()
        pg.mouse.click(hb["x"] + 20, hb["y"] + 6)
        pg.wait_for_timeout(300)
        pg.locator(".pop textarea").fill("안내 문구를 더 짧게")
        pg.keyboard.press("Control+Enter")
        pg.wait_for_timeout(300)
        pins = fr.evaluate("() => document.querySelector('#__studio-ov').shadowRoot.querySelectorAll('.pin').length")
        check("댓글 핀", pins == 1, f"{pins}개")

        # 앱의 쓰기 요청은 가짜 답
        pg.keyboard.press("v")
        app.locator("#addBtn").click()
        pg.wait_for_timeout(500)
        hint = fr.evaluate("() => document.querySelector('.hint').textContent")
        check("앱의 POST 는 실제로 보내지 않음", "스튜디오라" in hint and not (HELLO / "posted.log").exists(), hint)

        # 저장
        pg.locator('.bar [data-act="save"]').click()
        pg.locator('[data-f="title"]').fill("시험 저장")
        pg.locator('[data-modal="save"]').click()
        pg.wait_for_timeout(800)
        saved = sorted((WORK / "requests").glob("*.json"))
        check("저장본이 앱 저장소의 .design-studio/requests 에 생김", bool(saved), saved[-1].name if saved else "")
        name = saved[-1].stem if saved else ""
        data = json.loads(saved[-1].read_text(encoding="utf-8")) if saved else {}
        check("저장본에 앱 이름·바꾼 것·댓글", data.get("app") == "Hello" and data.get("comments") and data["variants"][0]["changes"])
        md = (WORK / "requests" / f"{name}.md").read_text(encoding="utf-8") if name else ""
        check("저장본 글(.md)에 CSS 와 댓글", "font-size" in md and "안내 문구를 더 짧게" in md)

        # 다시 열기
        pg2 = b.new_page(viewport={"width": 1440, "height": 900})
        pg2.on("pageerror", lambda e: errors.append(str(e)[:160]))
        pg2.goto(f"{url}?load={name}")
        pg2.wait_for_timeout(2500)
        f2 = pg2.main_frame.child_frames[0]
        size2 = f2.evaluate("() => getComputedStyle(document.querySelector('.title')).fontSize")
        pins2 = f2.evaluate("() => document.querySelector('#__studio-ov').shadowRoot.querySelectorAll('.pin').length")
        check("?load= 로 다시 열면 바꾼 것·댓글이 돌아옴", size2 == "30px" and pins2 == 1, f"{size2}, 핀 {pins2}")
        check("콘솔 오류 0", not errors, "; ".join(errors[:3]))
        b.close()
    return name


def xss_check(url: str) -> None:
    from playwright.sync_api import sync_playwright

    bad = {"data": {"title": "xss", "variants": [{"id": "v1", "name": "A", "changes": [
        {"type": "style", "id": "c1", "selector": ".title", "prop": "color", "to": "red} * {background:url(https://example.com/x)",
         "target": {"label": "x", "view": "page", "rules": []}, "count": "<img src=x onerror=window.__pwn3=1>"}]}],
        "comments": [{"id": "m1\"><img src=x onerror=window.__pwn4=1>", "n": "<img src=x onerror=window.__pwn=1>",
                      "kind": "fix\"><img src=x onerror=window.__pwn5=1>", "text": "t",
                      "anchor": {"path": "body", "view": "page", "label": "body"}, "at": {"x": 0.5, "y": 0.5}}]},
        "markdown": "x"}
    status, res = post(url + "__studio/save", json.dumps(bad).encode())
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        outside = []
        pg.on("request", lambda r: outside.append(r.url) if "example.com" in r.url else None)
        pg.goto(f"{url}?load={res.get('name')}")
        pg.wait_for_timeout(2500)
        pg.evaluate("() => { const h = document.querySelector('#__studio').shadowRoot; for (const t of ['comments','changes']) { const e = h.querySelector(`[data-tab=\"${t}\"]`); e && e.click(); } }")
        pg.wait_for_timeout(400)
        fr = pg.main_frame.child_frames[0]
        pwn = fr.evaluate("() => [window.__pwn, window.__pwn3, window.__pwn4, window.__pwn5].some(Boolean)") or \
            pg.evaluate("() => [window.__pwn, window.__pwn3, window.__pwn4, window.__pwn5].some(Boolean)")
        check("저장본에 심은 스크립트·CSS 가 실행되지 않음", not pwn and not outside, f"바깥 요청 {len(outside)}")
        b.close()


def server_checks(url: str, port: int) -> None:
    s, _ = post(url + "__studio/save", b'{"data":{"title":"x"}}', ctype="text/plain")
    check("다른 사이트식 요청(text/plain) 403", s == 403, str(s))
    s, _ = post(url + "__studio/proposal/start", b'{"request":"x"}', ctype="application/x-www-form-urlencoded")
    check("폼 요청으로 시안 시작 403", s == 403, str(s))
    s, _ = post(url + "__studio/save", b'{"data":{"title":"x"}}', host=f"evil.example:{port}")
    check("다른 호스트 이름 403 (DNS 리바인딩)", s == 403, str(s))
    with urllib.request.urlopen(url) as r:
        check("X-Frame-Options SAMEORIGIN", r.headers.get("X-Frame-Options") == "SAMEORIGIN")
    try:
        urllib.request.urlopen(url + "__studio/request?name=../../studio.app")
        ok = False
    except urllib.error.HTTPError as e:
        ok = e.code == 404
    check("저장본 이름으로 폴더 밖 못 읽음", ok)


def apply_checks() -> None:
    from studio.config import load
    from studio.proposals import ProposalManager

    tmp = Path(tempfile.mkdtemp(prefix="studio-test-"))
    try:
        shutil.copytree(HELLO / "web", tmp / "web")
        cfg_path = tmp / "studio.app.json"
        cfg_path.write_text(json.dumps({"name": "T", "webRoot": "web", "upstream": "http://127.0.0.1:1"}), encoding="utf-8")
        cfg = load(cfg_path, tmp, None)
        pm = ProposalManager(cfg, manage=False)
        d = cfg.proposals_dir / "p1"
        for sub in ("web", "base"):
            shutil.copytree(tmp / "web", d / sub)
        pm.save({"name": "p1", "status": "ready", "rounds": [{"request": "r1"}], "activity": []})
        css = (tmp / "web/styles.css").read_bytes().replace(b"\n", b"\r\n")
        for sub in ("web", "base"):
            (d / sub / "styles.css").write_bytes(css)
        (tmp / "web/styles.css").write_bytes(css.replace(b"--radius: 14px", b"--radius: 16px"))  # 진짜도 바뀜
        (d / "web/styles.css").write_bytes(css.replace(b"--accent: #c0674a", b"--accent: #2c8c8c"))
        (d / "web/app.js").write_text((tmp / "web/app.js").read_text(encoding="utf-8") + "\n// 시안\n", encoding="utf-8")
        # 충돌 만들기: app.js 끝을 진짜에서도 다르게
        (tmp / "web/app.js").write_text((tmp / "web/app.js").read_text(encoding="utf-8") + "\n// 진짜\n", encoding="utf-8")
        before = (tmp / "web/styles.css").read_bytes()
        r = pm.apply("p1")
        check("충돌이 있으면 아무 파일도 안 씀", r["conflicts"] == ["app.js"] and (tmp / "web/styles.css").read_bytes() == before, str(r["conflicts"]))
        (d / "web/app.js").write_text((tmp / "web/app.js").read_text(encoding="utf-8"), encoding="utf-8")
        r = pm.apply("p1")
        out = (tmp / "web/styles.css").read_bytes()
        check("3-way 병합: 양쪽 변경이 다 남고 CRLF 유지", b"#2c8c8c" in out and b"16px" in out and b"\r\r\n" not in out, str(r))
        check("before-apply 에 첫 원본", (d / "before-apply/styles.css").read_bytes() == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def snapshot_check(name: str) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    bad = subprocess.run([sys.executable, str(ROOT / "studio/snapshot.py"), name, "--views", "../x"], cwd=HELLO,
                         capture_output=True, text=True, env=env)
    check("사진: 경로 같은 화면 이름 거절", bad.returncode != 0, bad.stderr.strip()[-60:] or bad.stdout.strip()[-60:])
    bad = subprocess.run([sys.executable, str(ROOT / "studio/snapshot.py"), name, "--web", "/etc"], cwd=HELLO,
                         capture_output=True, text=True, env=env)
    check("사진: 시안·화면 폴더 밖 --web 거절", bad.returncode != 0)
    ok = subprocess.run([sys.executable, str(ROOT / "studio/snapshot.py"), name], cwd=HELLO,
                        capture_output=True, text=True, env=env, timeout=180)
    shots = sorted((WORK / "requests/shots" / name).glob("*.png")) if name else []
    check("사진: now·target 찍힘", len(shots) >= 2, ", ".join(s.name for s in shots) or ok.stdout[-200:] + ok.stderr[-200:])


def init_doctor_check() -> None:
    """화면 폴더만 있는 새 앱에 init → doctor 가 실패 없이 도는지 (개인화 흐름의 뼈대)."""
    tmp = Path(tempfile.mkdtemp(prefix="studio-init-"))
    try:
        shutil.copytree(HELLO / "web", tmp / "web")
        (tmp / ".gitignore").write_text(".design-studio/\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "run_studio.py"), "init", "--project", str(tmp)],
                           capture_output=True, text=True, encoding="utf-8")
        cfg = tmp / ".claude/design-studio/studio.app.json"
        data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.is_file() else {}
        check("init: 정적 앱 초안 (serve static·webRoot·테마 2개)", r.returncode == 0 and data.get("serve") == "static"
              and data.get("webRoot") == "web" and "dark" in (tmp / ".claude/design-studio/studio.app.js").read_text(encoding="utf-8"),
              r.stderr[-200:])
        r = subprocess.run([sys.executable, str(ROOT / "run_studio.py"), "doctor", "--project", str(tmp), "--port", "8981"],
                           capture_output=True, text=True, encoding="utf-8", timeout=240)
        check("doctor: 실패 0", r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def capture_ask_checks() -> None:
    """캡처 → 메모 → '바로 말하기' 로 보내기 → (가짜) claude 가 시안을 고치는 대로 화면이 새로 보임 → 이어 말하기 → 반영.
    진짜 예제 앱 파일을 반영으로 바꾸지 않게 임시 복사본으로 띄운다."""
    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp(prefix="studio-ask-"))
    proc = None
    try:
        for name in ("serve.py", "studio.app.json"):
            shutil.copy2(HELLO / name, tmp / name)
        shutil.copytree(HELLO / "web", tmp / "web")
        log = tmp / "prompts.log"
        env = {**os.environ, "STUDIO_CLAUDE": str(ROOT / "tests" / "fake_claude.py"), "FAKE_CLAUDE_LOG": str(log),
               "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "studio", "--app", str(tmp / "studio.app.json"),
                                 "--project", str(tmp), "--no-open", "--port", "8931"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        url = ""
        deadline = time.time() + 30
        while time.time() < deadline and not url:
            line = proc.stdout.readline()
            if line.startswith("디자인 스튜디오") and "http://" in line:
                url = line[line.index("http://"):].strip()
        if not url:
            return check("캡처·바로 말하기: 스튜디오 띄우기", False)

        s, res = post(url + "__studio/capture", json.dumps({"data": "data:image/png;base64,QUJD"}).encode())
        check("캡처: 그림이 아닌 것은 거절", s == 400, str(res.get("message")))
        try:
            urllib.request.urlopen(url + "__studio/capture?id=../../studio.app")
            ok = False
        except urllib.error.HTTPError as e:
            ok = e.code == 404
        check("캡처: 이름으로 폴더 밖 못 읽음", ok)

        host = "document.querySelector('#__studio').shadowRoot"
        with sync_playwright() as p:
            # 탭 화면 공유 허락 창을 자동으로 넘긴다 (사람은 한 번 '이 탭 공유' 를 누른다)
            b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--auto-select-desktop-capture-source=Entire screen"])
            pg = b.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
            pg.on("console", lambda m: errors.append("console: " + m.text[:160]) if m.type == "error" else None)
            pg.on("dialog", lambda d: d.accept())
            pg.add_init_script("try { localStorage.setItem('studio-ai-auto', 'false') } catch (e) {}")
            pg.goto(url)
            pg.wait_for_timeout(2500)
            fr = pg.main_frame.child_frames[0]
            app = pg.frame_locator("#app")

            pg.keyboard.press("x")
            pg.wait_for_timeout(800)
            tb = app.locator(".title").bounding_box()
            pg.mouse.move(tb["x"] - 6, tb["y"] - 6)
            pg.mouse.down()
            pg.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2, steps=4)
            pg.mouse.move(tb["x"] + tb["width"] + 6, tb["y"] + tb["height"] + 6, steps=4)
            pg.mouse.up()
            pg.wait_for_timeout(1800)
            img = pg.evaluate(f"""() => {{ const i = {host}.querySelector('.pop:not([hidden]) img.shotimg');
              return i ? {{ w: i.naturalWidth, h: i.naturalHeight, src: i.getAttribute('src') }} : null; }}""")
            # 찍힌 그림에 제목 글자(진한 픽셀)가 실제로 들어 있는지
            dark = pg.evaluate(f"""() => {{ const i = {host}.querySelector('.pop:not([hidden]) img.shotimg'); if (!i) return 0;
              const c = document.createElement('canvas'); c.width = i.naturalWidth; c.height = i.naturalHeight;
              const x = c.getContext('2d'); x.drawImage(i, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data;
              let n = 0; for (let k = 0; k < d.length; k += 4) if (d[k] + d[k+1] + d[k+2] < 200) n++; return n; }}""")
            shots = sorted((tmp / ".design-studio" / "captures").glob("*.png"))
            check("캡처: 끌어서 찍은 그림이 메모 창에 뜨고 파일로 저장", bool(img) and len(shots) == 1 and dark > 20,
                  f"{img and (img['w'], img['h'])} · 진한 픽셀 {dark} · 파일 {len(shots)}")
            pg.locator(".pop textarea").fill("제목이 너무 흐려요")
            pg.keyboard.press("Control+Enter")
            pg.wait_for_timeout(400)
            cmts = pg.evaluate(f"() => {host}.querySelectorAll('.cmt img.shotimg').length")
            check("캡처: 댓글 목록에 그림과 메모", cmts == 1, f"{cmts}개")

            pg.evaluate(f"() => {host}.querySelector('[data-ask]').focus()")
            pg.keyboard.type("제목 색을 진하게")
            pg.keyboard.press("Enter")
            ctx = ""
            for _ in range(40):
                pg.wait_for_timeout(500)
                try:
                    ctx = fr.evaluate("() => (window.__STUDIO__ || {}).ctx || ''")
                except Exception:  # noqa: BLE001 — 새로 뜨는 중
                    continue
                if ctx:
                    break
            reqs = sorted((tmp / ".design-studio" / "requests").glob("*.md"))
            md = reqs[-1].read_text(encoding="utf-8") if reqs else ""
            check("바로 말하기: 보내면 저장본이 생기고 시안 화면으로 옮김", bool(ctx) and "## 사용자가 한 말" in md
                  and "제목 색을 진하게" in md and "captures/" in md and "제목이 너무 흐려요" in md, ctx)

            def wait_color(want: str) -> str:
                got = ""
                for _ in range(50):
                    pg.wait_for_timeout(500)
                    try:
                        got = fr.evaluate("() => getComputedStyle(document.querySelector('.title')).color")
                    except Exception:  # noqa: BLE001
                        continue
                    if got == want:
                        break
                return got

            got = wait_color("rgb(1, 2, 3)")
            check("바로 말하기: Claude 가 고치는 대로 화면이 새로 보임", got == "rgb(1, 2, 3)", got)
            ready = False
            for _ in range(30):
                pg.wait_for_timeout(500)
                try:
                    ready = pg.evaluate(f"() => !!{host}.querySelector('.askst.ok')")
                except Exception:  # noqa: BLE001
                    continue
                if ready:
                    break
            check("바로 말하기: 다 되면 반영·원래·버리기", ready)

            pg.evaluate(f"() => {host}.querySelector('[data-ask]').focus()")
            pg.keyboard.type("조금 더")
            pg.keyboard.press("Enter")
            got = wait_color("rgb(4, 5, 6)")
            entries = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
            check("바로 말하기: 이어 말하면 같은 대화(--resume)로 고침", got == "rgb(4, 5, 6)" and [e["resume"] for e in entries] == [False, True],
                  f"{got} · {[e['resume'] for e in entries]}")
            check("바로 말하기: Claude 에게 캡처 그림을 열어 보라고 알림", bool(entries) and "캡처" in entries[0]["prompt"])

            for _ in range(30):
                pg.wait_for_timeout(500)
                try:
                    if pg.evaluate(f"() => !!{host}.querySelector('.askst.ok [data-prop-act=apply]')"):
                        break
                except Exception:  # noqa: BLE001
                    continue
            pg.evaluate(f"() => {host}.querySelector('.askst.ok [data-prop-act=apply]').click()")
            pg.wait_for_timeout(3000)
            real = (tmp / "web" / "styles.css").read_text(encoding="utf-8")
            back = fr.evaluate("() => (window.__STUDIO__ || {}).ctx || ''")
            check("바로 말하기: 반영하면 진짜 화면 파일에 들어가고 원래 화면으로", "rgb(4, 5, 6)" in real and back == "", f"ctx={back!r}")
            check("캡처·바로 말하기: 콘솔 오류 0", not errors, "; ".join(errors[:3]))
            b.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def artifact_checks() -> None:
    """작업물 모드: 웹 앱이 아닌 파일(글·코드·표·그림·PDF·Word·PowerPoint·Excel)을 자동으로 알아보고
    위치가 붙은 댓글·글자 고치기 → 보낼 목록에 담기 → 한 번에 보내기(차례로 같은 대화) → 첨부."""
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT / "tests"))
    from fixtures import make_all

    tmp = Path(tempfile.mkdtemp(prefix="studio-art-"))
    procs: list[subprocess.Popen] = []
    try:
        art = tmp / "art"
        make_all(art)
        log = tmp / "prompts.log"
        env = {**os.environ, "STUDIO_WORK": str(tmp / "work"), "STUDIO_CLAUDE": str(ROOT / "tests" / "fake_claude.py"),
               "FAKE_CLAUDE_LOG": str(log), "FAKE_CLAUDE_FILE": "notes.md", "FAKE_CLAUDE_DELAY": "0.5", "PYTHONIOENCODING": "utf-8"}

        def launch(args: list[str], port: int) -> str:
            proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "studio", "open", *args, "--no-open", "--port", str(port)],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
            procs.append(proc)
            deadline = time.time() + 30
            while time.time() < deadline:
                line = proc.stdout.readline()
                if line.startswith("디자인 스튜디오") and "http://" in line:
                    return line[line.index("http://"):].strip()
            return ""

        url = launch([str(art)], 8941)
        if not url:
            return check("작업물: 스튜디오 띄우기", False)

        def frame(q: str) -> str:
            with urllib.request.urlopen(url + "?frame=1&" + q) as r:
                return r.read().decode("utf-8")
        refs = {f: frame("file=" + urllib.parse.quote(f)).count("data-ref=") for f in
                ("notes.md", "calc.py", "scores.csv", "picture.png", "report.docx", "slides.pptx", "table.xlsx")}
        check("작업물: 형식마다 위치가 붙은 보기 화면 (md·코드·csv·그림·docx·pptx·xlsx)", all(v >= 1 for v in refs.values())
              and refs["scores.csv"] >= 6 and refs["slides.pptx"] >= 4, json.dumps(refs, ensure_ascii=False))
        check("작업물: 폴더 밖 파일은 못 엶", "root:" not in frame("file=../../../../etc/passwd"))
        has_pages = bool(shutil.which("pdftoppm"))
        if has_pages:
            try:
                with urllib.request.urlopen(url + "__studio/page?file=paper.pdf&n=1") as r:
                    ok = r.headers.get("Content-Type") == "image/png" and r.read(8).startswith(b"\x89PNG")
            except urllib.error.HTTPError:
                ok = False
            check("작업물: PDF 쪽을 그림으로", ok)

        host = "document.querySelector('#__studio').shadowRoot"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)[:160]))
            pg.on("console", lambda m: errors.append("console: " + m.text[:160]) if m.type == "error" else None)
            pg.on("dialog", lambda d: d.accept())
            pg.goto(url + "?file=notes.md")
            pg.wait_for_timeout(2000)
            fr = pg.main_frame.child_frames[0]
            app = pg.frame_locator("#app")
            info = fr.evaluate("() => window.__STUDIO__.artifact")
            tabs = pg.evaluate(f"() => [...{host}.querySelectorAll('[data-tab]')].map(b => b.dataset.tab)")
            check("작업물: 마크다운을 알아보고 작업물 탭", info and info["kind"] == "markdown" and tabs[0] == "files", f"{info and info['kind']} {tabs[:2]}")

            # 댓글: 둘째 문단(3~4번째 줄)
            pg.keyboard.press("c")
            box = app.locator("p", has_text="첫 문단").bounding_box()
            pg.mouse.click(box["x"] + 10, box["y"] + 6)
            pg.wait_for_timeout(300)
            pg.locator(".pop textarea").fill("이 문단을 한 줄로")
            pg.keyboard.press("Control+Enter")
            pg.wait_for_timeout(300)
            # 글자 고치기: 목록 첫 줄(6번째 줄)
            pg.keyboard.press("s")
            li = app.locator("li", has_text="할 일 하나").bounding_box()
            pg.mouse.dblclick(li["x"] + 10, li["y"] + 6)
            pg.wait_for_timeout(200)
            pg.keyboard.press("End")
            pg.keyboard.type(" (급함)")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            # 보낼 목록에 담기(Ctrl+Enter) → 둘째 요청을 쓰고 보내기(Enter): 두 요청이 차례로 같은 대화에서
            pg.evaluate(f"() => {host}.querySelector('[data-ask]').focus()")
            pg.keyboard.type("표는 그대로 둬")
            pg.keyboard.press("Control+Enter")
            pg.wait_for_timeout(300)
            queued = pg.evaluate(f"() => {host}.querySelectorAll('.aqi').length")
            check("보낼 목록: 담으면 목록에 쌓이고 화면은 비워짐", queued == 1 and fr.evaluate("() => 1") == 1, f"{queued}개")
            pg.evaluate(f"() => {host}.querySelector('[data-ask]').focus()")
            pg.keyboard.type("제목에 날짜를 붙여")
            pg.keyboard.press("Enter")
            entries = []
            for _ in range(60):
                pg.wait_for_timeout(500)
                entries = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
                if len(entries) >= 2:
                    break
            check("보낼 목록: 한 번에 보내면 차례로 같은 대화(--resume)에서", [e["resume"] for e in entries] == [False, True],
                  str([e["resume"] for e in entries]))
            # 두 요청이 같은 초에 저장되어 이름 순서로는 고를 수 없다. 담아 둔 첫 요청을 글로 찾는다
            texts = [r.read_text(encoding="utf-8") for r in (tmp / "work").glob("art-*/requests/*.md")]
            first = next((x for x in texts if "표는 그대로 둬" in x), "")
            check("작업물 요청 글에 원본 위치 (몇째 줄)", "3~4번째 줄" in first and "6번째 줄" in first and "(급함)" in first
                  and "작업물 수정 요청" in first and len(texts) == 2, f"저장본 {len(texts)}개")
            check("작업물: Claude 에게 원본 위치를 알려 줌", bool(entries) and "작업물 수정 요청" in entries[0]["prompt"])
            text = ""
            for _ in range(30):
                pg.wait_for_timeout(500)
                try:
                    text = fr.evaluate("() => document.body.innerText")
                except Exception:  # noqa: BLE001 — 새로 뜨는 중
                    continue
                if "rgb(4, 5, 6)" in text:
                    break
            check("작업물: Claude 가 고치는 대로 보기 화면이 새로 보임", "고친 줄 rgb(1, 2, 3)" in text and "고친 줄 rgb(4, 5, 6)" in text)

            # 그림: 끌어서 영역 댓글 → 원본 픽셀 좌표 / 글자 파일이 아니면 '복사' 로
            pg.goto(url + "?file=picture.png")
            pg.wait_for_timeout(1500)
            fr = pg.main_frame.child_frames[0]
            img = pg.frame_locator("#app").locator("img").bounding_box()
            pg.keyboard.press("c")
            pg.mouse.move(img["x"] + img["width"] * 0.25, img["y"] + img["height"] * 0.25)
            pg.mouse.down()
            pg.mouse.move(img["x"] + img["width"] * 0.6, img["y"] + img["height"] * 0.6, steps=4)
            pg.mouse.move(img["x"] + img["width"] * 0.75, img["y"] + img["height"] * 0.75, steps=4)
            pg.mouse.up()
            pg.wait_for_timeout(300)
            pg.locator(".pop textarea").fill("여기를 밝게")
            pg.keyboard.press("Control+Enter")
            pg.wait_for_timeout(300)
            label = pg.evaluate(f"() => {host}.querySelector('[data-act=ask-send]').textContent.trim()")
            check("작업물: 그림은 Claude 가 바로 못 고쳐 '복사' 로 보냄", label.startswith("복사"), label)
            pg.evaluate(f"() => {host}.querySelector('[data-act=ask-send]').click()")
            pg.wait_for_timeout(1200)
            reqs = sorted((tmp / "work").glob("art-*/requests/*.md"))
            last = reqs[-1].read_text(encoding="utf-8") if reqs else ""
            check("작업물: 그림 영역을 원본 픽셀로 적음 (120×80 그림)", "그림 안 영역: x 30~90px, y 20~60px (원본 120×80)" in last,
                  next((l for l in last.splitlines() if "그림 안" in l), "")[:80])
            check("작업물: 콘솔 오류 0", not errors, "; ".join(errors[:3]))
            b.close()

        # 받은 편지함: 파일 없이 열고 끌어 놓듯 첨부
        inbox = launch([], 8951)
        import base64
        payload = json.dumps({"name": "../메모.csv", "data": "data:text/csv;base64," + base64.b64encode("a,b\n1,2\n".encode()).decode()}).encode()
        s, res = post(inbox + "__studio/attach", payload)
        saved = tmp / "work" / "inbox" / "files" / "메모.csv"
        with urllib.request.urlopen(inbox + "?frame=1&file=" + urllib.parse.quote("메모.csv")) as r:
            shown = r.read().decode("utf-8").count('data-ref="B2"')
        check("받은 편지함: 첨부하면 저장되고(경로 문자는 지움) 바로 표로 보임", s == 200 and saved.is_file() and shown == 1, str(res))
        s, _ = post(url + "__studio/attach", payload)
        check("첨부는 받은 편지함에서만 (남의 폴더에 쓰지 않음)", s == 400)
    finally:
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def agent_checks() -> None:
    """Gemini·Codex CLI 로도 시안을 고친다: 시안 폴더 안에서만(작업 폴더·샌드박스), 캡처는 폴더 안으로 복사해 넘기고,
    이어 말하기는 지난 회차 설명을 넣어 새로 띄우고, 보낼 목록도 차례로."""
    import base64
    sys.path.insert(0, str(ROOT / "tests"))
    from fixtures import png

    tmp = Path(tempfile.mkdtemp(prefix="studio-agent-"))
    proc = None
    try:
        for name in ("serve.py", "studio.app.json"):
            shutil.copy2(HELLO / name, tmp / name)
        shutil.copytree(HELLO / "web", tmp / "web")
        log = tmp / "agent.log"
        fake = str(ROOT / "tests" / "fake_agent.py")
        env = {**os.environ, "STUDIO_GEMINI": fake, "STUDIO_CODEX": fake, "FAKE_AGENT_LOG": str(log), "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "studio", "--app", str(tmp / "studio.app.json"),
                                 "--project", str(tmp), "--no-open", "--port", "8961"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        url = ""
        deadline = time.time() + 30
        while time.time() < deadline and not url:
            line = proc.stdout.readline()
            if line.startswith("디자인 스튜디오") and "http://" in line:
                url = line[line.index("http://"):].strip()
        if not url:
            return check("다른 AI: 스튜디오 띄우기", False)
        with urllib.request.urlopen(url + "?frame=1") as r:
            html = r.read().decode("utf-8")
        check("다른 AI: 이 컴퓨터의 Gemini·Codex 를 보낼 곳으로 알림", '"gemini": true' in html and '"codex": true' in html)

        _, shot = post(url + "__studio/capture", json.dumps({"data": "data:image/png;base64," + base64.b64encode(png(20, 10)).decode()}).encode())

        def save(text: str) -> str:
            data = {"title": text, "variants": [], "comments": [{"id": "m1", "n": 1, "kind": "fix", "text": text, "shot": {"id": shot.get("id"), "w": 20, "h": 10},
                                                                 "anchor": {"path": "h1", "view": "page", "label": "h1"}, "at": {"x": 0, "y": 0}}]}
            return post(url + "__studio/save", json.dumps({"data": data, "markdown": f"# 요청\n\n{text}\n"}).encode())[1]["name"]

        def wait(name: str, rounds: int) -> dict:
            for _ in range(60):
                time.sleep(0.5)
                with urllib.request.urlopen(url + "__studio/proposals") as r:
                    items = json.loads(r.read())["items"]
                p = next((x for x in items if x["name"] == name), {})
                if p.get("status") in ("ready", "failed") and len(p.get("rounds") or []) >= rounds:
                    return p
            return p

        s, res = post(url + "__studio/proposal/start", json.dumps({"request": save("요청 A"), "agent": "없는AI"}).encode())
        check("다른 AI: 없는 AI 이름은 거절", s == 400, str(res.get("message")))
        _, res = post(url + "__studio/proposal/start", json.dumps({"request": save("요청 A"), "agent": "codex"}).encode())
        p = wait(res["name"], 1)
        web = tmp / ".design-studio" / "proposals" / res["name"] / "web"
        runs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
        first = runs[0] if runs else {"args": [], "cwd": "", "prompt": ""}
        a = first["args"]
        check("Codex: 시안 폴더 안에서만 쓰게 (exec --sandbox workspace-write -C 시안 폴더)",
              a[:3] == ["exec", "--sandbox", "workspace-write"] and a[a.index("-C") + 1] == str(web) and Path(first["cwd"]) == web, " ".join(a[:8]))
        check("Codex: 캡처를 시안 폴더에 복사해 그림으로 붙임 (-i)", "-i" in a and ".studio-captures" in a[a.index("-i") + 1]
              and (web / ".studio-captures").is_dir() and "요청 A" in first["prompt"])
        check("Codex: 시안을 고치고 마지막 답(-o)을 화면에", p.get("status") == "ready" and "rgb(7, 8, 1)" in (web / "styles.css").read_text(encoding="utf-8")
              and "1회차" in ((p.get("rounds") or [{}])[-1].get("result") or ""), str(p.get("status")))
        post(url + "__studio/proposal/revise", json.dumps({"name": res["name"], "request": save("요청 B")}).encode())
        wait(res["name"], 2)
        runs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        check("Codex: 이어 말하면 지난 회차 설명을 넣어 다시", len(runs) == 2 and "지난 1회차" in runs[1]["prompt"] and "요청 B" in runs[1]["prompt"])

        _, res = post(url + "__studio/proposal/start", json.dumps({"request": save("요청 C"), "queue": [save("요청 D")], "agent": "gemini"}).encode())
        p = wait(res["name"], 2)
        runs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        g = runs[2]["args"] if len(runs) > 2 else []
        check("Gemini: 폴더 믿기·고치기만 허락으로 띄움 (--skip-trust --approval-mode auto_edit)",
              g[:3] == ["--skip-trust", "--approval-mode", "auto_edit"] and "-p" in g, " ".join(g[:5]))
        check("Gemini: 보낼 목록 2개를 차례로", len(runs) == 4 and "요청 D" in runs[3]["prompt"] and p.get("status") == "ready"
              and len(p.get("rounds") or []) == 2, f"{len(runs)}번 · {p.get('status')}")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    (HELLO / "posted.log").unlink(missing_ok=True)
    port = 8911
    proc, url = start(port)
    port = int(url.rsplit(":", 1)[1].strip("/"))
    try:
        name = browser_checks(url)
        server_checks(url, port)
        xss_check(url)
    finally:
        proc.terminate()
        proc.wait(10)
    capture_ask_checks()
    artifact_checks()
    agent_checks()
    apply_checks()
    if name:
        snapshot_check(name)
    init_doctor_check()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
