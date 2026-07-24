"""The 24-hour pilot machine (「PDF3つで、24時間で御社専用AIをデモ」).

One command turns a prospect's document folder into their own working demo:

  python3 -m app pilot ./client_docs --name "株式会社◯◯"

It ingests the documents into a fresh tenant, auto-generates demo questions
from THEIR content (via the LLM when a key exists), smoke-tests three of
them through the real engine, saves everything, and writes a pilot report
you can send back the same day.
"""

import hashlib
import json
import re
from pathlib import Path

from . import db, llm
from .config import DATA_DIR


def _slug(name: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    ascii_part = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_part[:20]}-{digest}" if ascii_part else f"pilot-{digest}"


FALLBACK_TEMPLATES = ["{}について教えてください"]


def _generate_questions(chunks: list[dict], n: int = 5) -> list[str]:
    """Ask the LLM for typical employee questions grounded in the ingested
    docs; fall back to section-title templates when no key is set."""
    sections = []
    seen = set()
    for ch in chunks:
        title = f"{ch['doc_title']}：{ch['section']}" if ch["section"] else ch["doc_title"]
        if title not in seen:
            seen.add(title)
            sections.append(title)
    if llm.provider() != "mock":
        outline = "\n".join(f"- {s}" for s in sections[:40])
        prompt = (
            "以下は、ある会社の社内資料の目次です。社員がこの資料の内容について実際に聞きそうな質問を"
            f"{n}個、日本語で作成してください。具体的で短い質問にしてください。\n"
            "JSON配列のみを出力してください。例: [\"質問1\", \"質問2\"]\n\n" + outline
        )
        try:
            text, _ = llm.generate_raw(prompt)
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                questions = json.loads(match.group(0))
                if isinstance(questions, list) and questions:
                    return [str(q) for q in questions[:n]]
        except (llm.LLMError, json.JSONDecodeError):
            pass
    # Fallback: derive from section titles
    questions = []
    for s in sections:
        core = s.split("：")[-1]
        core = re.sub(r"^第[0-9０-９]+条[（(]?|[）)]$", "", core).strip("（）() ")
        if core and len(core) >= 2:
            questions.append(FALLBACK_TEMPLATES[0].format(core))
        if len(questions) >= n:
            break
    return questions


def run_pilot(folder: Path, name: str, tenant: str | None = None) -> str:
    from .answer import Engine
    from .ingest import ingest_path

    slug = _slug(name, tenant)
    print(f"◆ パイロット開始: {name}  (tenant: {slug})\n")

    print("① ドキュメント取り込み")
    n_docs, n_chunks = ingest_path(folder, slug, reset=True)
    if n_chunks == 0:
        print("  取り込める文書がありませんでした（.md/.txt、pypdf導入済みなら.pdfに対応）")
        return slug

    engine = Engine(slug)

    print("\n② デモ用の質問を自動生成")
    questions = _generate_questions(engine.chunks, n=6)
    for q in questions:
        print(f"  ・{q}")

    print("\n③ スモークテスト（実際にエンジンで回答）")
    samples: list[tuple[str, dict]] = []
    gaps: list[str] = []
    for q in questions:
        result = engine.ask(q, log=False)
        status = "✓" if result["answered"] else "✗ 資料に記載なし"
        print(f"  {status} {q}")
        if result["answered"]:
            samples.append((q, result))
        else:
            gaps.append(q)

    # Only questions that actually succeed become UI suggestions;
    # unanswerable ones go in the report as document gaps.
    con = db.connect()
    db.set_tenant_meta(con, slug, name, [q for q, _ in samples][:5])
    con.close()

    report_dir = DATA_DIR / "pilots"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{slug}-report.md"
    lines = [
        f"# 社内FAQ AI パイロットレポート — {name}",
        "",
        f"- 取り込み文書: {n_docs} 件 / {n_chunks} チャンク",
        f"- 回答モード: {'AI回答' if llm.provider() != 'mock' else '抜粋モード'}",
        f"- デモ起動: `python3 -m app serve --tenant {slug}`",
        "",
        "## デモ用の質問（チャット画面に表示されます）",
        *[f"- {q}" for q, _ in samples],
        "",
        "## サンプル回答",
    ]
    for q, result in samples[:3]:
        lines += [f"### Q. {q}", "", result["answer"], ""]
    if gaps:
        lines += [
            "## 現在の資料では回答できなかった質問（追加資料のご提案）",
            *[f"- {q}" for q in gaps],
            "",
        ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n④ レポート出力: {report_path}")
    print(f"\nデモ起動コマンド:\n  python3 -m app serve --tenant {slug}")
    return slug
