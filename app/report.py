"""Monthly customer report (月次レポート) — the recurring proof of value
that justifies the flat monthly fee.

  python3 -m app report --month 2026-07 --tenant demo

Contents: usage stats, unanswered questions (= documents worth adding),
and, when an LLM key exists, grouped improvement suggestions.
"""

import json
from pathlib import Path

from . import db, llm
from .config import DATA_DIR


def _suggestions(unanswered: list[dict]) -> str:
    if not unanswered:
        return "未回答の質問はありませんでした。現在の資料でカバーできています。"
    fallback = "上記の未回答質問に対応する資料（規程・マニュアル・FAQ）の追加をご検討ください。"
    if llm.provider() == "mock":
        return fallback
    questions = "\n".join(f"- {u['question']}" for u in unanswered[:30])
    prompt = (
        "以下は、社内FAQ AIが「社内資料に記載がない」ため回答できなかった社員からの質問です。\n"
        "これらをテーマごとにグループ化し、どのような資料（規程・マニュアル・FAQ）を追加すれば"
        "回答できるようになるか、簡潔な箇条書きで提案してください。日本語で、3〜5項目にまとめてください。\n\n"
        + questions
    )
    try:
        text, _ = llm.generate_raw(prompt)
        return text
    except llm.LLMError:
        return fallback


def run_report(tenant: str, month: str | None) -> Path:
    con = db.connect()
    stats = db.stats(con, tenant, month)
    unanswered = db.unanswered(con, tenant)
    meta = db.get_tenant_meta(con, tenant)
    con.close()

    if month:
        unanswered = [u for u in unanswered if u["created_at"].startswith(month)]

    name = meta["name"] or tenant
    period = month or "全期間"
    rate = (100.0 * stats["answered"] / stats["total"]) if stats["total"] else 0.0

    lines = [
        f"# 社内FAQ AI 月次レポート — {name}（{period}）",
        "",
        "## 利用状況",
        f"- 質問数: {stats['total']} 件",
        f"- 回答済み: {stats['answered']} 件（回答率 {rate:.0f}%）",
        f"- 未回答: {stats['unanswered']} 件",
        "",
        "## よくある質問 TOP",
        *(
            [f"{i}. {q['question']}（{q['count']}回）" for i, q in enumerate(stats["top_questions"], 1)]
            or ["- （データなし）"]
        ),
        "",
        "## 未回答の質問（資料追加の候補）",
        *(
            [f"- {u['question']}（{u['created_at']}）" for u in unanswered]
            or ["- なし"]
        ),
        "",
        "## 改善のご提案",
        _suggestions(unanswered),
        "",
        "## 登録済みドキュメント",
        *[f"- {d['title']}（{d['chunks']} チャンク）" for d in stats["documents"]],
    ]

    out_dir = DATA_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tenant}-{month or 'all'}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
