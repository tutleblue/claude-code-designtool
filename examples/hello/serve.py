"""스튜디오 예제 앱 서버. GET /api/items, POST /api/items(실제로 파일에 쓴다 — 스튜디오가 막는지 보려고)."""
import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS = [{"name": "보고서 마무리", "when": "오늘 18:00"}, {"name": "장보기", "when": "내일"}, {"name": "운동", "when": "매일"}]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/items"):
            return self._json({"ok": True, "items": ITEMS})
        super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        (HERE / "posted.log").open("ab").write(body + b"\n")  # 스튜디오가 막았다면 이 파일이 생기지 않는다
        self._json({"ok": True})

    def _json(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), partial(Handler, directory=str(HERE / "web"))).serve_forever()
