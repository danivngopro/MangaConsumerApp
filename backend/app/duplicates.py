from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from .utils import normalize_title

STOP_WORDS = {"a", "an", "the", "of", "to", "and", "or"}


def duplicate_key(value: str) -> str:
    words = [word for word in normalize_title(value).split() if word not in STOP_WORDS]
    return " ".join(words)


def _tokens(value: str) -> set[str]:
    return {word for word in duplicate_key(value).split() if word}


def title_similarity(left: str, right: str) -> tuple[float, str]:
    left_key = duplicate_key(left)
    right_key = duplicate_key(right)
    if not left_key or not right_key:
        return 0.0, "empty normalized title"
    if left_key == right_key:
        return 1.0, "same normalized title"

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    compact_left = re.sub(r"\s+", "", left_key)
    compact_right = re.sub(r"\s+", "", right_key)
    char_score = SequenceMatcher(None, compact_left, compact_right).ratio()

    ordered_score = SequenceMatcher(None, left_key, right_key).ratio()
    score = max(token_score, char_score * 0.95, ordered_score * 0.9)
    reason = f"token={token_score:.2f}, chars={char_score:.2f}, ordered={ordered_score:.2f}"
    return round(score, 3), reason


def best_title_match(remote_title: str, inventory_items: Iterable[dict], threshold: float = 0.72) -> dict | None:
    best: dict | None = None
    for item in inventory_items:
        score, reason = title_similarity(remote_title, item["title"])
        if score < threshold:
            continue
        candidate = {**item, "score": score, "reason": reason}
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best
