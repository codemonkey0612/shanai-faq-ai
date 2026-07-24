"""CLI entry point.

  python3 -m app ingest sample_docs --reset   # load documents
  python3 -m app ask "有給休暇は何日前までに申請？"
  python3 -m app serve --port 8000            # web chat UI
  python3 -m app eval                         # retrieval accuracy
  python3 -m app unanswered                   # improvement queue
"""

import argparse
import json
from pathlib import Path

from . import db
from .config import ROOT


def main() -> int:
    parser = argparse.ArgumentParser(prog="app", description="社内FAQ AI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ドキュメントを取り込む")
    p_ingest.add_argument("path", type=Path)
    p_ingest.add_argument("--tenant", default="demo")
    p_ingest.add_argument("--reset", action="store_true", help="既存データを削除してから取り込む")

    p_ask = sub.add_parser("ask", help="質問する（CLI）")
    p_ask.add_argument("question")
    p_ask.add_argument("--tenant", default="demo")

    p_serve = sub.add_parser("serve", help="WebチャットUIを起動")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--tenant", default="demo")

    p_eval = sub.add_parser("eval", help="検索精度を評価")
    p_eval.add_argument("--file", type=Path, default=ROOT / "eval" / "questions.jsonl")
    p_eval.add_argument("--tenant", default="demo")

    p_un = sub.add_parser("unanswered", help="回答できなかった質問の一覧")
    p_un.add_argument("--tenant", default="demo")

    p_pilot = sub.add_parser("pilot", help="顧客ドキュメントから24時間パイロットを作成")
    p_pilot.add_argument("path", type=Path, help="顧客ドキュメントのフォルダ")
    p_pilot.add_argument("--name", required=True, help="顧客企業名（例: 株式会社◯◯）")
    p_pilot.add_argument("--tenant", default=None, help="テナントIDを明示指定（省略時は自動生成）")

    p_report = sub.add_parser("report", help="月次レポートを出力")
    p_report.add_argument("--tenant", default="demo")
    p_report.add_argument("--month", default=None, help="対象月 YYYY-MM（省略時は全期間）")

    args = parser.parse_args()

    if args.command == "ingest":
        from .ingest import ingest_path

        n_docs, n_chunks = ingest_path(args.path, args.tenant, args.reset)
        print(f"\n取り込み完了: {n_docs} 文書 / {n_chunks} チャンク")
        return 0

    if args.command == "ask":
        from .answer import Engine

        result = Engine(args.tenant).ask(args.question)
        print(result["answer"])
        if result["sources"]:
            refs = ", ".join(f"{s['doc']} {s['section']}" for s in result["sources"])
            print(f"\n[参照: {refs}]")
        return 0

    if args.command == "serve":
        from .server import serve

        serve(port=args.port, host=args.host, tenant=args.tenant)
        return 0

    if args.command == "eval":
        from .evalrun import run

        return run(args.file, args.tenant)

    if args.command == "pilot":
        from .pilot import run_pilot

        run_pilot(args.path, args.name, args.tenant)
        return 0

    if args.command == "report":
        from .report import run_report

        path = run_report(args.tenant, args.month)
        print(f"レポート出力: {path}")
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "unanswered":
        con = db.connect()
        rows = db.unanswered(con, args.tenant)
        con.close()
        if not rows:
            print("未回答の質問はありません。")
        else:
            print(f"未回答の質問 ({len(rows)}件) — 資料追加の候補:")
            for r in rows:
                print(f"  ・{r['question']}  ({r['created_at']})")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
