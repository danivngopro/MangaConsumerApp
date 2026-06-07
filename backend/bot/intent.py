from __future__ import annotations

import re

import httpx

from .config import HISTORY_MAX_TURNS, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL

# System prompt injected at the start of every AI conversation.
# "No limitations" means no topic or content restrictions beyond the model's defaults.
_SYSTEM = {
    "role": "system",
    "content": "You are a helpful AI assistant. Answer naturally and directly.",
}

# Intent → regex patterns.
# More specific patterns must appear BEFORE more general ones so they match first.
# Each pattern is matched case-insensitively against the full user message.
_PATTERNS: dict[str, list[str]] = {
    # AUTO RUN — specific variants first
    "auto_run_status": [r"\bauto.?run.{0,20}status\b", r"\bauto.?run.{0,20}progress\b",
                        r"\bstatus.{0,20}auto.?run\b"],
    "auto_run_stop":   [r"\bstop.{0,20}auto.?run\b", r"\bcancel.{0,20}auto.?run\b",
                        r"\bauto.?run.{0,20}stop\b"],
    "auto_run":        [r"\bauto.?run\b", r"\brun.{0,10}pipeline\b", r"\brun.{0,10}everything\b"],

    # System Flush
    "flush_stop":      [r"\bstop.{0,20}flush\b", r"\bcancel.{0,20}flush\b"],
    "flush":           [r"\bflush\b"],

    # Library Organize
    "organize_stop":   [r"\bstop.{0,20}organiz\b", r"\bcancel.{0,20}organiz\b"],
    "organize":        [r"\bfull.{0,10}organiz\b", r"\borganiz.{0,10}library\b",
                        r"\blibrary.{0,10}organiz\b", r"\bstart.{0,10}organiz\b"],

    # Scans
    "reindex":         [r"\breindex\b", r"\bscan.{0,10}library\b", r"\blibrary.{0,10}scan\b",
                        r"\brun.{0,10}reindex\b"],
    "full_scan":       [r"\bfull.{0,10}scan\b", r"\bscan.{0,10}everything\b", r"\bscan.{0,10}all\b"],
    "scan_stop_all":   [r"\bstop.{0,10}all\b", r"\bstop.{0,10}scan.{0,10}all\b"],
    "scan_stop":       [r"\bstop.{0,10}scan\b", r"\bcancel.{0,10}scan\b"],

    # Queue
    "enqueue_missing": [r"\benqueue.{0,10}missing\b", r"\badd.{0,10}missing\b",
                        r"\bqueue.{0,10}missing\b", r"\bmissing.{0,10}chapters\b"],
    "reset_missing":   [r"\breset.{0,10}missing\b"],
    "retry_failed":    [r"\bretry.{0,10}failed\b", r"\brequeue.{0,10}failed\b",
                        r"\bfailed.{0,10}downloads?\b"],
    "pause_queue":     [r"\bpause.{0,15}queue\b", r"\bpause.{0,15}downloads?\b"],
    "resume_queue":    [r"\bresume.{0,15}queue\b", r"\bresume.{0,15}downloads?\b"],

    # Komga
    "komga_scan":      [r"\bkomga.{0,10}scan\b", r"\bscan.{0,10}komga\b", r"\bquick.?scan\b"],
    "import_all":      [r"\bimport.{0,10}all\b", r"\bimport.{0,10}books?\b"],

    # Library maintenance
    "reorganize":      [r"\breorganize\b", r"\breorg\b"],
    "deduplicate":     [r"\bdeduplicate\b", r"\bdedup\b"],

    # Metadata
    "discover":        [r"\bdiscover.{0,10}metadata\b", r"\bdiscover.{0,10}unmatched\b",
                        r"\bunmatched.{0,10}books?\b"],
    "sync":            [r"\bsync.{0,10}metadata\b", r"\bmetadata.{0,10}sync\b"],

    # Info
    "status":          [r"\bstatus\b", r"\bsummary\b", r"\bhow.{0,10}doing\b",
                        r"\bwhat.{0,10}running\b"],
    "progress":        [r"\bdownload.{0,10}progress\b", r"\bshow.{0,10}progress\b"],
    "logs":            [r"\bshow.{0,10}logs?\b", r"\brecent.{0,10}logs?\b", r"\bget.{0,10}logs?\b",
                        r"^logs?$"],
}


def match_intent(text: str) -> str | None:
    """Return the first matching intent ID, or None if no pattern matches."""
    lower = text.lower().strip()
    for action, patterns in _PATTERNS.items():
        for pat in patterns:
            if re.search(pat, lower):
                return action
    return None


async def ollama_chat(message: str, history: list[dict]) -> str:
    """Send a message to Ollama and return the assistant reply.

    History is the full conversation so far (list of {role, content} dicts).
    The system prompt is always prepended; history is capped to HISTORY_MAX_TURNS.
    """
    messages = [_SYSTEM] + history[-(HISTORY_MAX_TURNS * 2):] + [{"role": "user", "content": message}]
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as http:
        resp = await http.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
