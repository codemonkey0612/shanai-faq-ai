"""Answer generation. Three providers:

- anthropic : Claude via the Anthropic API (ANTHROPIC_API_KEY)
- openai    : any OpenAI-compatible endpoint (OPENAI_API_KEY / OPENAI_BASE_URL)
- mock      : extractive mode, zero dependencies — shows the best-matching
              passage verbatim with its citation. The demo works without
              any API key; answers upgrade automatically when a key exists.

All HTTP via urllib — no SDK dependencies.
"""

import json
import urllib.error
import urllib.request

from . import config


class LLMError(Exception):
    pass


def provider() -> str:
    if config.LLM_PROVIDER:
        return config.LLM_PROVIDER
    if config.ANTHROPIC_API_KEY:
        return "anthropic"
    if config.OPENAI_API_KEY:
        return "openai"
    return "mock"


SYSTEM_PROMPT = (
    "あなたは社内規程・マニュアルに基づいて社員の質問に答える社内アシスタントです。\n"
    "ルール:\n"
    "1. 提供された社内資料の抜粋のみに基づいて回答してください。一般知識や推測で補完しないでください。\n"
    "2. 資料に答えがない場合は「社内資料からは確認できませんでした。総務部までお問い合わせください。」とだけ答えてください。\n"
    "3. 回答は簡潔な日本語で。手順や条件は箇条書きを活用してください。\n"
    "4. 回答の最後に必ず「出典: 【文書名 条項】」の形式で根拠を記載してください。\n"
)


def build_prompt(question: str, contexts: list[dict], history: list[dict] | None = None) -> str:
    parts = []
    if history:
        parts.append("## 直前の会話（文脈の参考）\n")
        for h in history[-3:]:
            answer = h.get("a", "")
            if len(answer) > 200:
                answer = answer[:200] + "…"
            parts.append(f"Q: {h.get('q', '')}\nA: {answer}\n")
    parts.append("## 社内資料の抜粋\n")
    for i, c in enumerate(contexts, 1):
        parts.append(f"[{i}]【{c['doc_title']}　{c['section']}】\n{c['content']}\n")
    parts.append(f"\n## 質問\n{question}")
    if history:
        parts.append("（直前の会話の続きの質問である可能性があります。文脈を考慮して回答してください。）")
    return "\n".join(parts)


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"API error {e.code}: {detail}") from e
    except Exception as e:
        raise LLMError(str(e)) from e


def mock_answer(contexts: list[dict]) -> str:
    best = contexts[0]
    text = best["content"]
    if best["section"] and text.startswith(best["section"]):
        text = text[len(best["section"]) :].strip()
    if len(text) > 500:
        text = text[:500] + "…"
    heading = f"■ {best['doc_title']}" + (f"　{best['section']}" if best["section"] else "")
    return (
        "【抜粋モード】APIキー未設定のため、AI生成の代わりに関連する社内資料の該当箇所を表示しています。\n\n"
        f"{heading}\n{text}\n\n"
        f"出典: 【{best['doc_title']} {best['section']}】"
    )


def generate_raw(prompt: str, system: str = "") -> tuple[str, str]:
    """One-off generation without the grounded-answer system prompt
    (used for demo-question generation and report suggestions)."""
    p = provider()
    if p == "anthropic":
        payload = {
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        )
        return "".join(b.get("text", "") for b in data.get("content", [])).strip(), "ai"
    if p == "openai":
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        data = _post_json(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            {"model": config.OPENAI_MODEL, "messages": messages},
            {"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        )
        return data["choices"][0]["message"]["content"].strip(), "ai"
    raise LLMError("no API key configured (mock mode)")


def generate(
    question: str, contexts: list[dict], history: list[dict] | None = None
) -> tuple[str, str]:
    """Return (answer_text, mode) where mode is 'ai' or 'extract'."""
    p = provider()
    if p == "anthropic":
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "model": config.ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": build_prompt(question, contexts, history)}],
            },
            {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        )
        text = "".join(b.get("text", "") for b in data.get("content", [])).strip()
        if not text:
            raise LLMError("empty response from Anthropic API")
        return text, "ai"
    if p == "openai":
        data = _post_json(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            {
                "model": config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(question, contexts, history)},
                ],
            },
            {"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        )
        try:
            return data["choices"][0]["message"]["content"].strip(), "ai"
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected response shape: {e}") from e
    return mock_answer(contexts), "extract"
