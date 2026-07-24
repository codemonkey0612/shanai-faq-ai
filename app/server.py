"""Local web server (stdlib only): chat UI + JSON API.

Endpoints:
  GET  /                → chat UI
  POST /api/ask         → {"question": "..."} → answer with citations
  POST /api/reload      → re-read chunks after a new ingest
  GET  /api/history     → recent Q&A log
  GET  /api/unanswered  → questions the bot declined (improvement queue)
"""

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db, llm
from .answer import Engine
from .config import DATA_DIR, WEB_DIR

MAX_UPLOAD = 20 * 1024 * 1024  # 20MB
ALLOWED_UPLOAD_EXTS = {".md", ".txt", ".pdf", ".docx"}


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

        def _read_json(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json({"error": "invalid JSON"}, 400)
                return None

        def do_POST(self) -> None:
            path = urllib.parse.urlparse(self.path)
            if path.path == "/api/ask":
                payload = self._read_json()
                if payload is None:
                    return
                history = payload.get("history") or []
                if not isinstance(history, list):
                    history = []
                self._json(engine.ask(str(payload.get("question", "")), history=history))
            elif path.path == "/api/feedback":
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    message_id = int(payload.get("message_id"))
                    rating = int(payload.get("rating"))
                except (TypeError, ValueError):
                    self._json({"error": "message_id and rating (1 or -1) required"}, 400)
                    return
                con = db.connect()
                ok = db.set_feedback(con, tenant, message_id, rating)
                con.close()
                self._json({"ok": ok})
            elif path.path == "/api/admin/upload":
                query = urllib.parse.parse_qs(path.query)
                raw_name = (query.get("filename") or [""])[0]
                filename = Path(urllib.parse.unquote(raw_name)).name  # strip any path parts
                filename = re.sub(r'[\\/:*?"<>|]', "_", filename)
                ext = Path(filename).suffix.lower()
                if not filename or ext not in ALLOWED_UPLOAD_EXTS:
                    self._json({"error": f"対応形式: {', '.join(sorted(ALLOWED_UPLOAD_EXTS))}"}, 400)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_UPLOAD:
                    self._json({"error": "ファイルサイズは20MBまでです"}, 400)
                    return
                body = self.rfile.read(length)
                upload_dir = DATA_DIR / "uploads" / tenant
                upload_dir.mkdir(parents=True, exist_ok=True)
                dest = upload_dir / filename
                dest.write_bytes(body)
                from .ingest import ingest_file

                try:
                    result = ingest_file(dest, tenant, replace=True)
                except Exception as e:
                    self._json({"error": f"取り込みに失敗しました: {e}"}, 500)
                    return
                if result is None:
                    self._json({"error": "このファイルを読み取れませんでした（PDF/Wordは .venv の Python で起動してください）"}, 422)
                    return
                engine.reload()
                self._json({"ok": True, **result, "chunks_total": len(engine.chunks)})
            elif path.path == "/api/admin/delete_doc":
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    doc_id = int(payload.get("id"))
                except (TypeError, ValueError):
                    self._json({"error": "id required"}, 400)
                    return
                con = db.connect()
                ok = db.delete_document(con, tenant, doc_id)
                con.close()
                engine.reload()
                self._json({"ok": ok, "chunks_total": len(engine.chunks)})
            elif path.path == "/api/reload":
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
