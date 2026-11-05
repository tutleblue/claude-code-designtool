#!/usr/bin/env python3
"""시험용 가짜 `claude -p`: 진짜처럼 stream-json 을 내며 시안 폴더의 styles.css 를 고친다.

- 허락 목록(--allowedTools 의 Edit(<시안>/web/**))에서 시안 폴더를 알아낸다. 그 밖은 건드리지 않는다.
- 첫 회차는 .title 을 rgb(1, 2, 3), --resume 회차는 rgb(4, 5, 6) 으로. 받은 요청 글은 prompts.log 에 남긴다.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
web = next((m.group(1) for a in args if (m := re.fullmatch(r"Edit\((.+)/\*\*\)", a))), "")
resume = "--resume" in args
log = Path(os.environ.get("FAKE_CLAUDE_LOG", "prompts.log"))
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"resume": resume, "prompt": prompt}, ensure_ascii=False) + "\n")


def emit(ev):
    print(json.dumps(ev, ensure_ascii=False), flush=True)


emit({"type": "system", "subtype": "init"})
target = Path(web) / "styles.css"
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": str(target)}}]}})
time.sleep(float(os.environ.get("FAKE_CLAUDE_DELAY", "1")))
color = "rgb(4, 5, 6)" if resume else "rgb(1, 2, 3)"
with target.open("a", encoding="utf-8") as fh:
    fh.write(f"\n.title {{ color: {color}; }}\n")
time.sleep(float(os.environ.get("FAKE_CLAUDE_DELAY", "1")))
emit({"type": "result", "subtype": "success", "is_error": False, "result": f"제목 색을 {color} 로 바꿨어요.", "total_cost_usd": 0})
