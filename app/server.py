"""Local web server (stdlib only): chat UI + JSON API.

Endpoints:
  GET  /                → chat UI
  POST /api/ask         → {"question": "..."} → answer with citations
  POST /api/reload      → re-read chunks after a new ingest
  GET  /api/history     → recent Q&A log
  GET  /api/unanswered  → questions the bot declined (improvement queue)
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, llm
from .answer import Engine
from .config import WEB_DIR


def serve(port: int = 8000, host: str = "127.0.0.1", tenant: str = "demo") -> None:
    engine = Engine(tenant)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(
                json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
                status,
            )

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send((WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path in ("/admin", "/admin.html"):
                self._send((WEB_DIR / "admin.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/meta":
                con = db.connect()
                meta = db.get_tenant_meta(con, tenant)
                con.close()
                meta.update({"mode": llm.provider(), "chunks": len(engine.chunks), "tenant": tenant})
                self._json(meta)
            elif self.path == "/api/admin/stats":
                con = db.connect()
                data = db.stats(con, tenant)
                data["unanswered_list"] = db.unanswered(con, tenant)
                data["recent"] = db.recent_messages(con, tenant, limit=20)
                con.close()
                self._json(data)
            elif self.path == "/api/history":
                con = db.connect()
                self._json(db.recent_messages(con, tenant))
                con.close()
            elif self.path == "/api/unanswered":
                con = db.connect()
                self._json(db.unanswered(con, tenant))
                con.close()
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            if self.path == "/api/ask":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self._json({"error": "invalid JSON"}, 400)
                    return
                self._json(engine.ask(str(payload.get("question", ""))))
            elif self.path == "/api/reload":
                engine.reload()
                self._json({"ok": True, "chunks": len(engine.chunks)})
            else:
                self._json({"error": "not found"}, 404)

        def log_message(self, *args) -> None:
            pass  # keep the console clean

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"社内FAQ AI デモ起動: http://localhost:{port}")
    print(f"  回答モード: {llm.provider()}  /  チャンク数: {len(engine.chunks)}  (Ctrl+C で停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
