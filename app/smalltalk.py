"""Small-talk detection — greetings, thanks, jokes.

Handled before retrieval so replies are instant, free (no LLM call),
and warm even in extract mode. Deliberately conservative: the WHOLE
message (minus trailing punctuation) must match a known phrase, so a
real question that happens to start with a greeting ("こんにちは、有給
について教えて") still falls through to normal retrieval.
"""

import re
import unicodedata

MAX_LEN = 24  # longer messages are assumed to carry real content
_TAIL = r"[!!。.\s〜~ー？?]*"

_PATTERNS = [
    ("hello", re.compile(
        rf"(こんにちは|こんばんは|おはよう(ございます)?|はじめまして|やあ|どうも|hi|hello|hey|yo){_TAIL}",
        re.IGNORECASE)),
    ("thanks", re.compile(
        rf"(ありがとう(ございます)?|thanks|thank\s*you|thx|さんくす|助かりました?){_TAIL}",
        re.IGNORECASE)),
    ("howareyou", re.compile(
        rf"(元気|調子(は)?どう|お疲れ(様)?(です)?|おつかれ){_TAIL}", re.IGNORECASE)),
    ("playful", re.compile(
        rf"(テスト|test|kidding|冗談|じょうだん|www+|草){_TAIL}", re.IGNORECASE)),
    ("bye", re.compile(
        rf"(さようなら|バイバイ|bye|またね|じゃあね){_TAIL}", re.IGNORECASE)),
]

REPLIES = {
    "hello": "こんにちは！就業規則や経費精算、社内のルールなど、気になることがあれば何でも聞いてくださいね。",
    "thanks": "どういたしまして！他にも気になることがあれば、いつでも聞いてくださいね。",
    "howareyou": "元気に稼働中です！何か調べたいことがあれば教えてくださいね。",
    "playful": "うふふ、ちゃんと動いていますよ〜。就業規則や経費精算など、気になることがあれば聞いてくださいね。",
    "bye": "またいつでも聞いてくださいね。良い一日を！",
}


def classify(text: str) -> str | None:
    if not text or len(text) > MAX_LEN:
        return None
    normalized = unicodedata.normalize("NFKC", text).strip()
    for category, pattern in _PATTERNS:
        if pattern.fullmatch(normalized):
            return category
    return None


def reply(category: str) -> str:
    return REPLIES[category]
