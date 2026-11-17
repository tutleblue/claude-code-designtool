#!/usr/bin/env python3
"""시험용 가짜 Gemini·Codex CLI: 받은 인자와 요청 글을 남기고, 지금 폴더(시안 폴더)의 파일을 고친다.

- 고치는 파일: FAKE_CLAUDE_FILE (기본 styles.css). 회차마다 .title 색을 rgb(7, 8, N) 으로 (N = 지금까지 부른 횟수)
- codex 처럼 -o <파일> 을 받으면 마지막 답을 거기에 쓴다. 아니면 마지막 줄을 출력한다(gemini 처럼).
"""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
log = Path(os.environ.get("FAKE_AGENT_LOG", "agent.log"))
n = len(log.read_text(encoding="utf-8").splitlines()) + 1 if log.is_file() else 1
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": args, "cwd": os.getcwd(), "prompt": prompt}, ensure_ascii=False) + "\n")
print("요청을 읽었어요", flush=True)
time.sleep(float(os.environ.get("FAKE_CLAUDE_DELAY", "0.3")))
target = Path(os.environ.get("FAKE_CLAUDE_FILE", "styles.css"))
with target.open("a", encoding="utf-8") as fh:
    fh.write(f"\n.title {{ color: rgb(7, 8, {n}); }}\n")
said = f"{n}회차: 제목 색을 rgb(7, 8, {n}) 으로 바꿨어요."
if "-o" in args:
    Path(args[args.index("-o") + 1]).write_text(said, encoding="utf-8")
print(said, flush=True)
