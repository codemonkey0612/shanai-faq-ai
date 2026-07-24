"""The answer engine: search → (optional vector merge) → generate → log.

Refusal-first design: when retrieval coverage is weak the engine says
「確認できませんでした」and logs the question as unanswered instead of
letting the LLM guess. Unanswered questions are the monthly improvement
report shown to the customer.
"""

from . import db, embeddings, llm, smalltalk
from .search import SearchIndex, rrf_merge

REFUSAL = "すみません、その内容については今の社内資料からは確認できませんでした。詳しいことは総務部に聞いてみてくださいね。"
# Two-stage refusal gate:
#  - below HARD_FLOOR: refuse without calling the LLM (obvious junk, saves tokens)
#  - between the two: only the LLM may answer — its prompt requires refusal when
#    the retrieved passages lack the answer. Synonym-heavy paraphrases (上司 vs
#    所属長) score low on keyword coverage yet retrieve the right chunk, so a
#    strict keyword gate would refuse answerable questions.
#  - extract mode (no API key) keeps the strict gate: it cannot judge relevance.
HARD_FLOOR = 0.05
COVERAGE_THRESHOLD = 0.28
TOP_CONTEXTS = 5
EXCERPT_LEN = 220


def _excerpt(chunk: dict) -> str:
    """Short preview of the source passage, for the citation popover."""
    text = chunk["content"]
    if chunk["section"] and text.startswith(chunk["section"]):
        text = text[len(chunk["section"]):].strip()
    return text[:EXCERPT_LEN] + ("…" if len(text) > EXCERPT_LEN else "")


class Engine:
    def __init__(self, tenant: str = "demo"):
        self.tenant = tenant
        self.reload()

    def reload(self) -> None:
        con = db.connect()
        self.chunks = db.load_chunks(con, self.tenant)
        con.close()
        self.index = SearchIndex(self.chunks)
        self.has_vectors = embeddings.available() and any(c.get("embedding") for c in self.chunks)

    def _retrieve(self, question: str) -> tuple[list[tuple[dict, float]], float]:
        hits, coverage = self.index.search(question, k=8)
        if self.has_vectors and hits:
            try:
                qvec = embeddings.embed([question])[0]
                vhits = embeddings.vector_hits(self.chunks, qvec, k=8)
                hits = rrf_merge(hits, vhits, k=8)
            except Exception:
                pass  # vectors are an enhancement; keyword results stand alone
        return hits, coverage

    def ask(self, question: str, log: bool = True, history: list[dict] | None = None) -> dict:
        question = (question or "").strip()
        if not question:
            return {"answer": "質問を入力してください。", "sources": [], "mode": "none", "answered": False}

        category = smalltalk.classify(question)
        if category:
            result = {"answer": smalltalk.reply(category), "sources": [], "mode": "smalltalk", "answered": True}
            if log:
                con = db.connect()
                result["message_id"] = db.log_message(
                    con, self.tenant, question, result["answer"], True, "smalltalk", []
                )
                con.close()
            return result

        history = [h for h in (history or []) if isinstance(h, dict) and h.get("q")][-3:]

        hits, coverage = self._retrieve(question)
        # Follow-up questions (「それは誰に申請するの？」) carry little vocabulary
        # of their own — retry retrieval with the previous question prepended.
        if history and coverage < COVERAGE_THRESHOLD:
            combined = f"{history[-1]['q']}。{question}"
            hits2, coverage2 = self._retrieve(combined)
            if coverage2 > coverage:
                hits, coverage = hits2, coverage2

        gate = COVERAGE_THRESHOLD if llm.provider() == "mock" else HARD_FLOOR
        if not hits or coverage < gate:
            result = {"answer": REFUSAL, "sources": [], "mode": "refusal", "answered": False}
        else:
            contexts = [h[0] for h in hits[:TOP_CONTEXTS]]
            try:
                text, mode = llm.generate(question, contexts, history)
            except llm.LLMError as e:
                text = f"（AI呼び出しに失敗したため、関連箇所の抜粋を表示します。エラー: {e}）\n\n" + llm.mock_answer(contexts)
                mode = "extract"
            if "確認できませんでした" in text:  # the LLM declined per its instructions
                result = {"answer": REFUSAL, "sources": [], "mode": "refusal", "answered": False}
            else:
                sources = [
                    {"doc": c["doc_title"], "section": c["section"], "excerpt": _excerpt(c)}
                    for c in contexts[:3]
                ]
                result = {"answer": text, "sources": sources, "mode": mode, "answered": True}

        if log:
            con = db.connect()
            result["message_id"] = db.log_message(
                con, self.tenant, question,
                result["answer"], result["answered"], result["mode"], result["sources"],
            )
            con.close()
        return result
