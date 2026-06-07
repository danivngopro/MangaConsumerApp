from __future__ import annotations

import os
from pathlib import Path

_env = Path(__file__).parent.parent.parent / ".env.bot"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

ALLOWED_USERS: set[int] = {
    int(u.strip())
    for u in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if u.strip().isdigit()
}

# Manga app backend — port 8816 is the default dev/prod port
API_URL: str = os.environ.get("MANGA_API_URL", "http://localhost:8816")
API_USERNAME: str = os.environ.get("MANGA_API_USERNAME", "")
API_PASSWORD: str = os.environ.get("MANGA_API_PASSWORD", "")

# Ollama
OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
OLLAMA_TIMEOUT: int = int(os.environ.get("OLLAMA_TIMEOUT", "45"))

# Keep last N user+assistant turn pairs in conversation memory
HISTORY_MAX_TURNS: int = int(os.environ.get("HISTORY_MAX_TURNS", "10"))
