"""Local web server (stdlib only): chat UI + JSON API.

Endpoints:
  GET  /                → chat UI
  POST /api/ask         → {"question": "..."} → answer with citations
  POST /api/reload      → re-read chunks after a new ingest
  GET  /api/history     → recent Q&A log
  GET  /api/unanswered  → questions the bot declined (improvement queue)
"""

import hashlib
import hmac
import json
import re
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, db, llm
from .answer import Engine
from .config import DATA_DIR, WEB_DIR

MAX_UPLOAD = 20 * 1024 * 1024  # 20MB
ALLOWED_UPLOAD_EXTS = {".md", ".txt", ".pdf", ".docx"}
SECRET_FILE = DATA_DIR / "secret.key"
COOKIE_NAME = "sfa_session"


def _secret() -> bytes:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(key)
    return key


def _sign(role: str, key: bytes) -> str:
    return hmac.new(key, role.encode(), hashlib.sha256).hexdigest()


def serve(port: int = 8000, host: str = "127.0.0.1", tenant: str = "demo") -> None:
    engine = Engine(tenant)
    secret_key = _secret()

    class Handler(BaseHTTPRequestHandler):
        def _send(
            self, body: bytes, content_type: str, status: int = 200, headers: dict | None = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200, headers: dict | None = None) -> None:
            self._send(
                json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
                status,
                headers,
            )

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ---- access control -------------------------------------------
        def _ip_ok(self) -> bool:
            if not config.IP_ALLOWLIST:
                return True
            ip = self.client_address[0]
            prefixes = [p.strip() for p in config.IP_ALLOWLIST.split(",") if p.strip()]
            return any(ip.startswith(p) for p in prefixes) or ip == "127.0.0.1"

        def _role(self) -> str | None:
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE_NAME:
                    role, _, sig = value.partition(":")
                    if role in ("chat", "admin") and hmac.compare_digest(
                        sig, _sign(role, secret_key)
                    ):
                        return role
            return None

        def _can_chat(self) -> bool:
            if not config.ACCESS_CODE and not config.ADMIN_PASSWORD:
                return True  # open mode (local demo)
            if not config.ACCESS_CODE:
                return True  # only admin is protected
            return self._role() in ("chat", "admin")

        def _can_admin(self) -> bool:
            if not config.ACCESS_CODE and not config.ADMIN_PASSWORD:
                return True  # open mode (local demo)
            # once any code is configured, admin always requires the admin role
            return bool(config.ADMIN_PASSWORD) and self._role() == "admin"

        def do_GET(self) -> None:
            if not self._ip_ok():
                self._json({"error": "forbidden"}, 403)
                return
            if self.path == "/login":
                self._send((WEB_DIR / "login.html").read_bytes(), "text/html; charset=utf-8")
                return
            if self.path in ("/", "/index.html") and not self._can_chat():
                self._redirect("/login")
                return
            if self.path in ("/admin", "/admin.html") and not self._can_admin():
                self._redirect("/login")
                return
            if self.path.startswith("/api/admin") or self.path in ("/api/history", "/api/unanswered"):
                if not self._can_admin():
                    self._json({"error": "unauthorized"}, 401)
                    return
            elif self.path.startswith("/api/") and not self._can_chat():
                self._json({"error": "unauthorized"}, 401)
                return
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
            if not self._ip_ok():
                self._json({"error": "forbidden"}, 403)
                return
            path = urllib.parse.urlparse(self.path)
            if path.path == "/api/login":
                payload = self._read_json()
                if payload is None:
                    return
                code = str(payload.get("code", ""))
                role = None
                if config.ADMIN_PASSWORD and hmac.compare_digest(code, config.ADMIN_PASSWORD):
                    role = "admin"
                elif config.ACCESS_CODE and hmac.compare_digest(code, config.ACCESS_CODE):
                    role = "chat"
                if not role:
                    self._json({"error": "コードが正しくありません"}, 403)
                    return
                cookie = (
                    f"{COOKIE_NAME}={role}:{_sign(role, secret_key)};"
                    " Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                )
                self._json({"ok": True, "role": role}, headers={"Set-Cookie": cookie})
                return
            if path.path == "/api/logout":
                cookie = f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
                self._json({"ok": True}, headers={"Set-Cookie": cookie})
                return
            if path.path.startswith("/api/admin") or path.path == "/api/reload":
                if not self._can_admin():
                    self._json({"error": "unauthorized"}, 401)
                    return
            elif not self._can_chat():
                self._json({"error": "unauthorized"}, 401)
                return
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
    if config.ACCESS_CODE or config.ADMIN_PASSWORD:
        auth = "チャット=" + ("コード必須" if config.ACCESS_CODE else "公開")
        auth += " / 管理画面=" + ("パスワード必須" if config.ADMIN_PASSWORD else "ロック中(ADMIN_PASSWORD未設定)")
    else:
        auth = "なし（ローカルデモ用。公開時は ACCESS_CODE と ADMIN_PASSWORD を設定してください）"
    print(f"社内FAQ AI 起動: http://localhost:{port}")
    print(f"  回答モード: {llm.provider()}  /  チャンク数: {len(engine.chunks)}  /  認証: {auth}")
    print("  (Ctrl+C で停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
