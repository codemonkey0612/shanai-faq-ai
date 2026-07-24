"""SQLite storage. Every table carries tenant_id so the same schema
scales to multiple customers (and maps 1:1 onto Postgres later)."""

import json
import sqlite3

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'demo',
  title TEXT NOT NULL,
  path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'demo',
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  section TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
CREATE TABLE IF NOT EXISTS tenant_meta(
  tenant_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  questions TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'demo',
  question TEXT NOT NULL,
  answer TEXT NOT NULL DEFAULT '',
  answered INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL DEFAULT '',
  sources TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def reset_tenant(con: sqlite3.Connection, tenant: str) -> None:
    con.execute("DELETE FROM chunks WHERE tenant_id = ?", (tenant,))
    con.execute("DELETE FROM documents WHERE tenant_id = ?", (tenant,))
    con.commit()


def add_document(con: sqlite3.Connection, tenant: str, title: str, path: str) -> int:
    cur = con.execute(
        "INSERT INTO documents(tenant_id, title, path) VALUES (?, ?, ?)",
        (tenant, title, path),
    )
    return cur.lastrowid


def add_chunk(
    con: sqlite3.Connection,
    tenant: str,
    document_id: int,
    section: str,
    content: str,
    embedding: bytes | None = None,
) -> None:
    con.execute(
        "INSERT INTO chunks(tenant_id, document_id, section, content, embedding)"
        " VALUES (?, ?, ?, ?, ?)",
        (tenant, document_id, section, content, embedding),
    )


def load_chunks(con: sqlite3.Connection, tenant: str) -> list[dict]:
    rows = con.execute(
        "SELECT c.id, c.document_id, c.section, c.content, c.embedding,"
        "       d.title AS doc_title"
        " FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.tenant_id = ? ORDER BY c.id",
        (tenant,),
    ).fetchall()
    return [dict(r) for r in rows]


def log_message(
    con: sqlite3.Connection,
    tenant: str,
    question: str,
    answer: str,
    answered: bool,
    mode: str,
    sources: list[dict],
) -> None:
    con.execute(
        "INSERT INTO messages(tenant_id, question, answer, answered, mode, sources)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (tenant, question, answer, int(answered), mode, json.dumps(sources, ensure_ascii=False)),
    )
    con.commit()


def recent_messages(con: sqlite3.Connection, tenant: str, limit: int = 50) -> list[dict]:
    rows = con.execute(
        "SELECT question, answer, answered, mode, sources, created_at"
        " FROM messages WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
        (tenant, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        out.append(d)
    return out


def set_tenant_meta(con: sqlite3.Connection, tenant: str, name: str, questions: list[str]) -> None:
    con.execute(
        "INSERT INTO tenant_meta(tenant_id, name, questions) VALUES (?, ?, ?)"
        " ON CONFLICT(tenant_id) DO UPDATE SET name = excluded.name, questions = excluded.questions",
        (tenant, name, json.dumps(questions, ensure_ascii=False)),
    )
    con.commit()


def get_tenant_meta(con: sqlite3.Connection, tenant: str) -> dict:
    row = con.execute(
        "SELECT name, questions FROM tenant_meta WHERE tenant_id = ?", (tenant,)
    ).fetchone()
    if not row:
        return {"name": "", "questions": []}
    return {"name": row["name"], "questions": json.loads(row["questions"])}


def stats(con: sqlite3.Connection, tenant: str, month: str | None = None) -> dict:
    """month: 'YYYY-MM' filters messages by created_at (UTC)."""
    where = "tenant_id = ?"
    params: list = [tenant]
    if month:
        where += " AND created_at LIKE ?"
        params.append(f"{month}%")
    row = con.execute(
        f"SELECT COUNT(*) AS total, COALESCE(SUM(answered), 0) AS answered"
        f" FROM messages WHERE {where}",
        params,
    ).fetchone()
    top = con.execute(
        f"SELECT question, COUNT(*) AS n FROM messages WHERE {where}"
        f" GROUP BY question ORDER BY n DESC, MAX(id) DESC LIMIT 10",
        params,
    ).fetchall()
    docs = con.execute(
        "SELECT d.title, COUNT(c.id) AS chunks FROM documents d"
        " LEFT JOIN chunks c ON c.document_id = d.id"
        " WHERE d.tenant_id = ? GROUP BY d.id ORDER BY d.id",
        (tenant,),
    ).fetchall()
    return {
        "total": row["total"],
        "answered": row["answered"],
        "unanswered": row["total"] - row["answered"],
        "top_questions": [{"question": r["question"], "count": r["n"]} for r in top],
        "documents": [{"title": r["title"], "chunks": r["chunks"]} for r in docs],
    }


def unanswered(con: sqlite3.Connection, tenant: str, limit: int = 100) -> list[dict]:
    rows = con.execute(
        "SELECT question, created_at FROM messages"
        " WHERE tenant_id = ? AND answered = 0 ORDER BY id DESC LIMIT ?",
        (tenant, limit),
    ).fetchall()
    return [dict(r) for r in rows]
