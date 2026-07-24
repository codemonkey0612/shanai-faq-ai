# 社内FAQ AI (Shanai FAQ AI)

**An internal-knowledge AI chatbot for Japanese SMEs.** It ingests a company's internal documents (就業規則, 経費精算規程, manuals, FAQs), and answers employees' questions in Japanese — always with a citation (出典), and with an honest 「わかりません」 when the answer isn't in the documents.

日本の中小企業向け「社内FAQ AI」。社内規程・マニュアルを読み込み、社員の質問に出典付きで回答します。資料にないことは推測せず「確認できませんでした」と答えます。

## Quickstart（30秒で起動・APIキー不要）

Requires Python 3.10+. **Zero dependencies** — standard library only.

```bash
cd shanai-faq-ai
python3 -m app ingest sample_docs --reset   # デモ用の架空企業の規程を取り込む
python3 -m app serve                        # → http://localhost:8000 を開く
```

Try: 「有給休暇は何日前までに申請？」「経費精算の締め切りは？」「今日の天気は？」(→ 拒否されます)

Other commands:

```bash
python3 -m app ask "リモートワークは週何日まで？"   # CLIで質問
python3 -m app eval                                # 検索精度の測定（現在 17/17 = 100%）
python3 -m app unanswered                          # 回答できなかった質問（資料追加の候補）

# 24時間パイロット: 顧客のドキュメントフォルダ → 専用デモ + レポート
python3 -m app pilot ./client_docs --name "株式会社◯◯"
python3 -m app serve --tenant <表示されたID>        # 顧客名・専用質問入りのデモ画面

# 月次レポート（未回答質問 = 改善提案。顧客に送る資産）
python3 -m app report --tenant demo --month 2026-07
```

**管理画面**: サーバー起動中に http://localhost:8000/admin — 質問数・回答率・👍/👎評価・未回答キュー・**ドキュメントのアップロード（ドラッグ&ドロップ、同名は上書き）・削除・インデックス再構築**・最近のログ。

**チャット画面の機能**: 出典チップ・回答への👍/👎フィードバック・会話の文脈を踏まえたフォローアップ質問（「それは誰に申請するの？」が通じます）・「＋新しい会話」ボタン。

**PDF/Word対応**: プロジェクト内の仮想環境で起動してください:

```bash
.venv/bin/python3 -m app serve        # PDF/Word取り込み対応（pypdf + python-docx導入済み）
# .venvを作り直す場合: python3 -m venv .venv && .venv/bin/pip install pypdf python-docx
```

## Answer modes

| Mode | When | What happens |
|---|---|---|
| **抜粋モード (extract)** | No API key (default) | Shows the best-matching passage verbatim with its citation — fully offline demo |
| **AI回答 (ai)** | `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set (see `.env.example`) | LLM writes a concise answer grounded ONLY in retrieved passages, with 出典 |
| **拒否 (refusal)** | Retrieval coverage below threshold | 「社内資料からは確認できませんでした」+ question logged for the improvement report |

Copy `.env.example` → `.env` and set one key to switch modes. No code changes.

## How it works

```
documents → chunker → SQLite ─┬─ bigram BM25 (Japanese-friendly, pg_bigm style)
                              └─ vectors (optional, OpenAI-compatible API)
question → hybrid search → coverage check ──low──→ refuse + log
                                   │high
                                   ▼
                        LLM (or extract mode) → cited answer → log
```

- **Chunking** splits on Japanese legal structure (第◯条…) and markdown headings, so every answer cites a real section like 「就業規則 第6条（年次有給休暇）」.
- **Search** is BM25 over character bigrams — no tokenizer needed, works for Japanese out of the box. Conversational noise (できますか etc.) is stripped from queries. Optional vector search merges via RRF when embeddings are enabled.
- **Refusal** uses IDF-weighted query coverage: out-of-domain questions score low and get declined instead of hallucinated.
- **Multi-tenant ready**: every table and query carries `tenant_id` (`--tenant` flag on all commands).
- **PDF/Word**: `pip install pypdf python-docx` to enable (optional; .md/.txt work without).

## Project layout

```
app/
  chunker.py     # 第◯条 / heading-aware Japanese chunking
  search.py      # bigram BM25 + coverage + RRF merge
  embeddings.py  # optional vectors (OpenAI-compatible)
  llm.py         # Anthropic / OpenAI-compatible / extract-mode providers
  answer.py      # engine: retrieve → refuse-or-answer → log
  ingest.py      # file readers (.md/.txt, optional .pdf/.docx)
  server.py      # stdlib HTTP server: chat UI + JSON API
  evalrun.py     # retrieval accuracy harness
  db.py          # SQLite, tenant-scoped schema
web/index.html   # chat UI (Japanese, self-contained)
sample_docs/     # 架空の会社「株式会社サンプル商事」の規程一式
eval/questions.jsonl  # 17 test questions incl. refusal cases
```

## Access control（公開時は必須）

`.env` で設定。両方未設定なら認証なしのローカルデモモードで動作します。

```
ACCESS_CODE=社員に配る共有コード       # チャット画面のログインに必要
ADMIN_PASSWORD=管理者パスワード        # /admin のログインに必要
IP_ALLOWLIST=203.0.113.,198.51.100.7  # 任意: 許可IPプレフィックス
```

- ログインは `/login`（署名付きHttpOnlyクッキー、30日有効。`data/secret.key` が署名鍵）
- `ACCESS_CODE` だけ設定した場合、管理画面は安全側に倒してロックされます（`ADMIN_PASSWORD` も設定してください）
- リバースプロキシ（nginx等）の背後では TLS 終端とアクセスログをプロキシ側で

## Deploy

```bash
docker build -t shanai-faq-ai .
docker run -d -p 8000:8000 -v faqai-data:/srv/data --env-file .env shanai-faq-ai
# 初回のみ: ドキュメント取り込み
docker exec -it <container> python3 -m app ingest sample_docs --reset
```

Azure Container Apps（Japan East、国内データ保存の営業トークに合致）へは:
ACR に push → Container Apps 作成 → `data` 用に Azure Files ボリュームをマウント → 環境変数を設定。
どの VPS でも `docker run` 一発で動きます。

## Production roadmap (in order)

1. ~~LLM key / admin console / monthly report / PDF・Word / feedback / follow-up conversations / auth / Dockerfile~~ ✓
2. **Embeddings on** (`EMBEDDINGS_ENABLED=1`) → better recall on paraphrased questions
3. **OCR for scanned PDFs** (Azure Document Intelligence) — many SME documents are scans
4. **Postgres migration** — schema maps 1:1; pgvector for vectors, PGroonga for keyword search
5. **Chat-tool integrations** — LINE WORKS / Chatwork / Teams webhook delivery
6. **HTTPS + domain** — reverse proxy or Container Apps ingress; then invite the first pilot customer

## Notes

- Sample documents are fictional (株式会社サンプル商事) — for demos only.
- `eval` should be run after every retrieval change; the score is also your honest 「初期精度」 number for sales conversations.
