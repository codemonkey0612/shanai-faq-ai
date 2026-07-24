"""Japanese-aware chunking.

Documents are split on structural boundaries — markdown headings and
Japanese legal-style article lines (第◯条…) — so every chunk maps to a
citable section like 「就業規則 第6条（年次有給休暇）」.
"""

import re

MAX_CHARS = 900
SPLIT_TARGET = 700

_HEADING = re.compile(r"^(?:#{1,6}\s+.+|第[0-9０-９〇一二三四五六七八九十百]+条.*)$")
_H1 = re.compile(r"^#\s+(.+)$")


def doc_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = _H1.match(line.strip())
        if m:
            return m.group(1).strip()
    return fallback


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return (section_title, body) pairs; sections with empty bodies are dropped."""
    sections: list[tuple[str, str]] = []
    title = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append((title, body))

    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING.match(stripped):
            flush()
            title = stripped.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


def _split_long(body: str) -> list[str]:
    """Split an over-long body at sentence boundaries (。) near SPLIT_TARGET."""
    sentences = re.split(r"(?<=。)", body)
    parts: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) > SPLIT_TARGET:
            parts.append(current.strip())
            current = s
        else:
            current += s
    if current.strip():
        parts.append(current.strip())
    return parts or [body]


def chunk_text(text: str) -> list[dict]:
    """Return [{"section": ..., "content": ...}]. Content includes the
    section title so keyword search matches heading terms too."""
    chunks: list[dict] = []
    for title, body in split_sections(text):
        if len(title) + len(body) <= MAX_CHARS:
            content = f"{title}\n{body}".strip() if title else body
            chunks.append({"section": title, "content": content})
            continue
        for i, part in enumerate(_split_long(body)):
            label = title if i == 0 else f"{title}（続き{i}）" if title else f"（続き{i}）"
            content = f"{label}\n{part}".strip() if label else part
            chunks.append({"section": label, "content": content})
    return chunks
