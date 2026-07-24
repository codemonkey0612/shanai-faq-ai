"""Configuration: paths and environment (.env supported, no dependencies)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
WEB_DIR = ROOT / "web"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# LLM provider: "anthropic" | "openai" | "mock" | "" (auto-detect from keys)
LLM_PROVIDER = env("LLM_PROVIDER")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")

# Optional vector search (needs an OpenAI-compatible embeddings API)
EMBEDDINGS_ENABLED = env("EMBEDDINGS_ENABLED", "0") == "1"
EMBEDDING_MODEL = env("EMBEDDING_MODEL", "text-embedding-3-small")

# Access control (all optional; unset = open, for local demos)
ACCESS_CODE = env("ACCESS_CODE")          # shared code for the chat UI
ADMIN_PASSWORD = env("ADMIN_PASSWORD")    # password for /admin
IP_ALLOWLIST = env("IP_ALLOWLIST")        # comma-separated IP prefixes
