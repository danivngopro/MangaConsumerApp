from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException, Response
from pydantic import BaseModel

from . import repository
from .utils import utc_now


SESSION_COOKIE = "manga_recoverer_session"
SESSION_DAYS = 30


class AuthRequest(BaseModel):
    username: str
    password: str


def user_count(conn: sqlite3.Connection) -> int:
    with repository.DB_LOCK:
        return int(conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"])


def registration_open(conn: sqlite3.Connection) -> bool:
    return user_count(conn) == 0


def register_first_user(conn: sqlite3.Connection, username: str, password: str, response: Response) -> dict:
    username = username.strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")
    with repository.DB_LOCK:
        if user_count(conn) > 0:
            raise HTTPException(status_code=403, detail="registration is disabled")
        conn.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), utc_now()),
        )
        conn.commit()
    return login(conn, username, password, response)


def login(conn: sqlite3.Connection, username: str, password: str, response: Response) -> dict:
    with repository.DB_LOCK:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")

    token = secrets.token_urlsafe(48)
    token_hash = hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with repository.DB_LOCK:
        conn.execute(
            "INSERT INTO sessions(user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (row["id"], token_hash, utc_now(), expires_at.isoformat()),
        )
        conn.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=SESSION_DAYS * 24 * 60 * 60,
    )
    return {"authenticated": True, "username": row["username"], "registrationOpen": False}


def logout(conn: sqlite3.Connection, token: str | None, response: Response) -> dict:
    if token:
        with repository.DB_LOCK:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            conn.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False, "registrationOpen": registration_open(conn)}


def current_user(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    with repository.DB_LOCK:
        row = conn.execute(
            """
            SELECT u.id, u.username, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (hash_token(token),),
        ).fetchone()
    if row is None:
        return None
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return None
    if expires_at <= datetime.now(timezone.utc):
        with repository.DB_LOCK:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            conn.commit()
        return None
    return {"id": row["id"], "username": row["username"]}


def require_user(conn: sqlite3.Connection, token: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict:
    user = current_user(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def auth_status(conn: sqlite3.Connection, token: str | None) -> dict:
    user = current_user(conn, token)
    return {
        "authenticated": user is not None,
        "username": user["username"] if user else None,
        "registrationOpen": registration_open(conn),
    }


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 200_000)
    return f"pbkdf2_sha256$200000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
