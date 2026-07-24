"""Document ingestion: read files, chunk, store (and embed when enabled).

Markdown/plain text work out of the box. PDF and Word are supported when
the optional libraries are installed (pip install pypdf python-docx) —
kept optional so the core runs with zero dependencies.
"""

from pathlib import Path

from . import db, embeddings
from .chunker import chunk_text, doc_title

TEXT_EXTS = {".md", ".txt"}


def read_file(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return path.read_text(encoding="utf-8")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print(f"  ⚠ {path.name} をスキップ（PDF対応: pip install pypdf）")
            return None
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if ext == ".docx":
        try:
            import docx
        except ImportError:
            print(f"  ⚠ {path.name} をスキップ（Word対応: pip install python-docx）")
            return None
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return None


def ingest_path(target: Path, tenant: str = "demo", reset: bool = False) -> tuple[int, int]:
    con = db.connect()
    if reset:
        db.reset_tenant(con, tenant)

    files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else [target]
    n_docs = n_chunks = 0
    for path in files:
        text = read_file(path)
        if text is None or not text.strip():
            continue
        title = doc_title(text, path.stem)
        chunks = chunk_text(text)
        if not chunks:
            continue

        vectors: list[bytes | None] = [None] * len(chunks)
        if embeddings.available():
            try:
                vecs = embeddings.embed([c["content"] for c in chunks])
                vectors = [embeddings.pack(v) for v in vecs]
            except Exception as e:  # vectors are optional — never block ingestion
                print(f"  ⚠ 埋め込み生成に失敗（キーワード検索のみで動作します）: {e}")

        document_id = db.add_document(con, tenant, title, str(path))
        for chunk, vec in zip(chunks, vectors):
            db.add_chunk(con, tenant, document_id, chunk["section"], chunk["content"], vec)
        con.commit()
        n_docs += 1
        n_chunks += len(chunks)
        print(f"  ✓ {title} — {len(chunks)} チャンク")

    con.close()
    return n_docs, n_chunks
