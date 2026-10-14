"""디자인 스튜디오의 실시간 AI: Claude Code CLI(`claude -p`)로

1) 추천(suggest): 지금 화면·고른 요소·사용자가 바꾼 것을 보고 "이건 어때요?" 제안을 줄마다 JSON 으로 받는다.
   스튜디오가 받는 대로 바로 미리 보여 준다(시연). 빨리 와야 하니
     - 도구를 하나도 주지 않고(`--tools ""`) 한 번에 답하게 한다. 필요한 CSS 규칙 글은 화면이 직접 모아 넘긴다.
     - 저장소 밖 빈 폴더에서 띄운다. 저장소 안에서 띄우면 CLAUDE.md·스킬을 읽느라 매번 수천 토큰이 더 든다.
     - 앱의 디자인 규칙은 설정의 context 파일을 그대로 붙여 넘긴다.
     - 모델은 STUDIO_AI_MODEL (기본 haiku).
2) 동작 알아보기(flow): 고른 단추가 지금 누르면 무엇을 하는지 앱 코드를 읽어 단계로 정리한다(읽기 도구만).

작업은 메모리에만 둔다(서버를 끄면 사라져도 되는 것들). 추천은 한 번에 하나만 돈다 — 새로 부르면 앞의 것을 멈춘다.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .claude_cli import kill_tree, spawn
from .config import AppConfig

SUGGEST_MODEL = os.environ.get("STUDIO_AI_MODEL", "haiku")
FLOW_MODEL = os.environ.get("STUDIO_FLOW_MODEL", "sonnet")

SUGGEST_RULES = """너는 웹 앱 '{app}' 의 디자인 도우미다. 사용자가 디자인 스튜디오에서 이 앱 화면을 만지고 있다.
아래 '지금 상황' 을 보고, 바로 미리 보여 줄 수 있는 작은 개선 제안을 서로 다른 방향으로 3개 낸다(예: 글자 위계 / 간격·여백 / 색·강조). 사용자가 'ask' 로 바란 것이 있으면 그쪽을 먼저.

공통 규칙
- 색은 앱의 토큰(CSS 변수)을 먼저 쓴다. 새 색이 꼭 필요할 때만 hex.
- 사용자가 이미 바꾼 것·단 댓글의 방향을 존중한다. 그걸 되돌리는 제안은 하지 않는다.
- '좋아요·유지' 댓글이 달린 곳은 건드리지 않는다.
{context}
출력 형식 — 반드시 지킨다
- 제안 하나를 JSON 한 줄로. 설명 글·마크다운·코드 울타리 없이 줄만 낸다. 가장 좋은 제안을 먼저.
- {{"title": "12자 안팎 제목", "why": "왜 좋은지 한 문장", "focus": "시연 때 반짝일 CSS 선택자",
   "changes": [ {{"type": "style", "selector": "CSS 선택자", "prop": "CSS 속성", "to": "값"}},
                {{"type": "token", "name": "--토큰", "to": "값"}} ]}}
- changes 는 1~6개. selector 는 '지금 상황' 에 나온 클래스·id 로 만든다(없는 이름을 지어내지 않는다).
- prop 은 일반 CSS 속성만(font-size, font-weight, color, background-color, border-radius, padding, gap, margin, box-shadow,
  letter-spacing, line-height, width, max-width, opacity, translate 등). 값은 실제로 쓸 수 있는 CSS 값. url() 은 쓰지 않는다.
"""

FLOW_RULES = """너는 이 저장소(웹 앱 '{app}')의 코드를 읽어, 화면의 단추 하나가 '눌렀을 때 지금 무엇을 하는지' 알아낸다.
화면 파일은 `{web}/` 아래에 있다. Grep 으로 id·class·data-* 속성·단추 글자를 찾아 처리 함수를 따라간다. 고치지 않는다(읽기만).
{context}
마지막 답은 JSON 하나만 (설명·코드 울타리 없이):
{{"summary": "한 문장 요약", "where": "파일 이름과 함수 이름(줄 번호)",
 "steps": [ {{"kind": "nav|confirm|toast|loading|run|open|note", "text": "사용자에게 보이는 일을 짧은 한국어로", "view": "nav 일 때 화면 키 {views}"}} ]}}
steps 는 사용자 눈에 보이는 순서대로 2~8개. 서버 호출은 run, 확인 창은 confirm, 알림은 toast, 화면 전환은 nav.
"""


# 추천 값은 <style> 에 그대로 들어간다. '}' 로 규칙을 닫고 새 규칙을 열거나 url() 로 바깥에 요청을 보내지 못하게
# 이름·속성은 모양을, 값·선택자는 위험한 글자를 본다 (검토에서 지적: 'red} * {background:url(...)' 가 그대로 들어갔다).
_CSS_BAD = re.compile(r"[{};<\\]|/\*|url\(|@import|expression\(", re.I)
_SEL_BAD = re.compile(r"[{};<]|/\*")  # 선택자는 '>'(자식)·'\'(이스케이프)를 쓸 수 있다


def _safe_css_change(c: dict) -> bool:
    to = str(c.get("to") or "")
    if not to or _CSS_BAD.search(to):
        return False
    if c.get("type") == "token":
        return bool(re.fullmatch(r"--[\w-]+", str(c.get("name") or "")))
    sel = str(c.get("selector") or "")
    return bool(sel) and not _SEL_BAD.search(sel) and bool(re.fullmatch(r"[a-z-]+", str(c.get("prop") or "")))


class AIRunner:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.proj = cfg.project
        self.proxy_env: dict = {}
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._scratch: Path | None = None  # 처음 추천할 때 만든다 (사진용 서버마다 빈 폴더가 쌓이지 않게)
        self.current_suggest: str | None = None

    # ---------- 공통 ----------
    def _new_job(self, kind: str) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "running", "items": [], "result": None,
               "error": "", "cost": 0.0, "startedAt": time.time(), "proc": None}
        with self.lock:
            self.jobs[job["id"]] = job
            # 오래된 작업은 치운다 (메모리만 차지한다)
            for jid in [j for j, v in self.jobs.items() if time.time() - v["startedAt"] > 3600]:
                self.jobs.pop(jid, None)
        return job

    def public(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return {k: v for k, v in job.items() if k != "proc"} | {"elapsed": round(time.time() - job["startedAt"], 1)}

    def cancel(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job and job["status"] == "running":
            job["status"] = "cancelled"
            proc = job.get("proc")
            if proc and proc.poll() is None:
                kill_tree(proc)

    def _start(self, job: dict, args: list[str], prompt: str, cwd: Path) -> bool:
        """claude 를 띄운다. 못 띄우면 작업을 '실패' 로 두고 이유를 남긴다 (화면이 그 이유를 보여 준다)."""
        try:
            job["proc"] = spawn(args, prompt, cwd, self.proxy_env)
            return True
        except OSError as exc:
            job["status"] = "failed"
            job["error"] = f"claude 를 실행하지 못했어요 ({exc.strerror or exc})"
            return False

    # ---------- 추천 ----------
    def suggest(self, context: dict) -> dict:
        if self.current_suggest:
            self.cancel(self.current_suggest)
        job = self._new_job("suggest")
        self.current_suggest = job["id"]
        ctx = self.cfg.context_text()
        rules = SUGGEST_RULES.format(app=self.cfg.name, context=f"\n이 앱의 규칙\n{ctx}\n" if ctx else "")
        prompt = rules + "\n지금 상황 (JSON):\n" + json.dumps(context, ensure_ascii=False, indent=1)[:24000]
        args = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--model", SUGGEST_MODEL, "--tools", "", "--max-turns", "1", "--permission-mode", "dontAsk"]
        if self._scratch is None:
            self._scratch = Path(tempfile.mkdtemp(prefix="design-studio-ai-"))
        if not self._start(job, args, prompt, self._scratch):
            return job
        threading.Thread(target=self._pump_suggest, args=(job,), daemon=True).start()
        return job

    def _take_line(self, job: dict, line: str) -> None:
        line = line.strip().strip("`")
        if not line.startswith("{"):
            return
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return
        changes = [c for c in item.get("changes") or [] if isinstance(c, dict) and c.get("type") in ("style", "token")
                   and _safe_css_change(c)]
        if not changes or not item.get("title"):
            return
        item["changes"] = changes[:6]
        item["id"] = f"{job['id']}-{len(job['items'])}"
        job["items"].append(item)

    def _pump_suggest(self, job: dict) -> None:
        buf, seen = "", 0
        proc = job["proc"]
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "stream_event":
                delta = (ev.get("event") or {}).get("delta") or {}
                if delta.get("type") == "text_delta":
                    buf += delta.get("text", "")
                    # 한 줄이 끝날 때마다 바로 꺼낸다 → 첫 제안이 다른 제안을 기다리지 않고 화면에 뜬다
                    while "\n" in buf[seen:]:
                        end = buf.index("\n", seen)
                        self._take_line(job, buf[seen:end])
                        seen = end + 1
            elif ev.get("type") == "result":
                job["cost"] = float(ev.get("total_cost_usd") or 0)
                if not buf:  # 부분 메시지를 못 받았으면 마지막 결과로
                    buf = str(ev.get("result") or "")
                    seen = 0
                if ev.get("is_error"):
                    job["error"] = str(ev.get("result") or ev.get("subtype") or "실패")[:300]
        proc.wait()
        for line in buf[seen:].splitlines():
            self._take_line(job, line)
        if job["status"] == "running":
            job["status"] = "done" if job["items"] or not job["error"] else "failed"
            if not job["items"] and not job["error"]:
                job["error"] = "이번엔 제안할 것을 못 찾았어요."

    # ---------- 동작 알아보기 ----------
    def flow(self, target: dict) -> dict:
        job = self._new_job("flow")
        ctx = self.cfg.context_text()
        views = target.get("views") if isinstance(target.get("views"), list) else []
        rules = FLOW_RULES.format(app=self.cfg.name, web=self.cfg.rel(self.cfg.web_root),
                                  context=f"\n이 앱에 대해\n{ctx}\n" if ctx else "",
                                  views="(" + ", ".join(map(str, views[:20])) + ")" if views else "")
        prompt = rules + "\n알아볼 단추 (스튜디오가 모은 정보):\n" + json.dumps(target, ensure_ascii=False, indent=1)[:8000]
        args = ["-p", "--output-format", "json", "--model", FLOW_MODEL, "--max-turns", "14",
                "--permission-mode", "dontAsk", "--allowedTools", "Read", "Grep", "Glob"]
        if not self._start(job, args, prompt, self.proj):
            return job
        threading.Thread(target=self._pump_flow, args=(job,), daemon=True).start()
        return job

    def _pump_flow(self, job: dict) -> None:
        proc = job["proc"]
        out = proc.stdout.read()
        proc.wait()
        if job["status"] != "running":
            return
        try:
            res = json.loads(out.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            job.update(status="failed", error="Claude 답을 읽지 못했어요.")
            return
        job["cost"] = float(res.get("total_cost_usd") or 0)
        text = str(res.get("result") or "")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            data = None
        if not data or not isinstance(data.get("steps"), list):
            job.update(status="failed", error=("알아내지 못했어요. " + text[:200]).strip())
            return
        job["result"] = data
        job["status"] = "done"
