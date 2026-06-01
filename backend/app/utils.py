from __future__ import annotations

import re
import unicodedata
import html
from datetime import datetime, timezone


WINDOWS_FORBIDDEN = r'<>:"/\|?*'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fix_mojibake(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = html.unescape(value)
    if any(marker in cleaned for marker in ("â", "Ã", "ð")):
        try:
            cleaned = cleaned.encode("latin1").decode("utf-8")
        except UnicodeError:
            pass
    return cleaned


def slugify(value: str) -> str:
    normalized = normalize_title(value)
    return normalized.replace(" ", "-") or "untitled"


def sanitize_filename(value: str) -> str:
    cleaned = "".join("_" if ch in WINDOWS_FORBIDDEN else ch for ch in value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Untitled"


def chapter_key(value: str | int | float) -> str:
    raw = str(value).strip()
    raw = raw.lower().replace("chapter", "").replace("ch.", "").replace("ch", "")
    raw = re.sub(r"[^0-9.]+", "", raw)
    if not raw:
        return ""
    try:
        number = float(raw)
    except ValueError:
        return raw
    if number.is_integer():
        return str(int(number))
    return str(number).rstrip("0").rstrip(".")


def chapter_sort_value(key: str) -> float:
    try:
        return float(key)
    except ValueError:
        return -1.0
