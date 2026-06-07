from __future__ import annotations

from typing import Any

import httpx

from .config import API_PASSWORD, API_URL, API_USERNAME


class MangaClient:
    """Async HTTP client for the manga-recoverer FastAPI backend."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=API_URL,
            timeout=30.0,
            follow_redirects=True,
        )
        self._authed = False

    async def _login(self) -> None:
        resp = await self._http.post(
            "/api/auth/login",
            json={"username": API_USERNAME, "password": API_PASSWORD},
        )
        resp.raise_for_status()
        self._authed = True

    async def _req(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._authed:
            await self._login()
        resp = await self._http.request(method, path, **kwargs)
        if resp.status_code == 401:
            self._authed = False
            await self._login()
            resp = await self._http.request(method, path, **kwargs)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {}

    # ── Info ──────────────────────────────────────────────────────────────────

    async def summary(self) -> dict:
        return await self._req("GET", "/api/summary")

    async def progress(self) -> list:
        return await self._req("GET", "/api/progress")

    async def logs(self, limit: int = 20) -> list:
        return await self._req("GET", f"/api/logs?limit={limit}")

    # ── AUTO RUN ──────────────────────────────────────────────────────────────

    async def auto_run_start(self) -> dict:
        return await self._req("POST", "/api/system/auto-run")

    async def auto_run_stop(self) -> dict:
        return await self._req("POST", "/api/system/auto-run/stop")

    async def auto_run_status(self) -> dict:
        return await self._req("GET", "/api/system/auto-run/status")

    # ── System Flush ──────────────────────────────────────────────────────────

    async def flush_start(self) -> dict:
        return await self._req("POST", "/api/system/flush")

    async def flush_stop(self) -> dict:
        return await self._req("POST", "/api/system/flush/stop")

    async def flush_status(self) -> dict:
        return await self._req("GET", "/api/system/flush/status")

    # ── Library Organize ──────────────────────────────────────────────────────

    async def organize_start(self) -> dict:
        return await self._req("POST", "/api/library/full-organize")

    async def organize_stop(self) -> dict:
        return await self._req("POST", "/api/library/full-organize/stop")

    async def organize_status(self) -> dict:
        return await self._req("GET", "/api/library/full-organize/status")

    # ── Reorganize / Deduplicate ───────────────────────────────────────────────

    async def reorganize(self) -> dict:
        return await self._req("POST", "/api/library/reorganize")

    async def deduplicate(self) -> dict:
        return await self._req("POST", "/api/library/deduplicate")

    # ── Scans ─────────────────────────────────────────────────────────────────

    async def reindex(self) -> dict:
        return await self._req("POST", "/api/scan/library")

    async def full_scan(self) -> dict:
        return await self._req("POST", "/api/scan/full", json={"limit": None})

    async def scan_stop(self) -> dict:
        return await self._req("POST", "/api/scan/stop")

    async def scan_stop_all(self) -> dict:
        return await self._req("POST", "/api/scan/stop-all")

    # ── Queue ─────────────────────────────────────────────────────────────────

    async def enqueue_missing(self) -> dict:
        return await self._req("POST", "/api/queue/enqueue-missing")

    async def reset_missing(self) -> dict:
        return await self._req("POST", "/api/scan/reset-missing")

    async def retry_failed(self) -> dict:
        return await self._req("POST", "/api/jobs/retry-failed")

    async def pause_queue(self) -> dict:
        return await self._req("POST", "/api/queue/pause")

    async def resume_queue(self) -> dict:
        return await self._req("POST", "/api/queue/resume")

    # ── Komga ─────────────────────────────────────────────────────────────────

    async def komga_scan_all(self) -> dict:
        return await self._req("POST", "/api/komga/quick-scan-all")

    async def import_all(self) -> dict:
        return await self._req("POST", "/api/komga/import-all")

    # ── Metadata ──────────────────────────────────────────────────────────────

    async def metadata_discover(self) -> dict:
        return await self._req("POST", "/api/metadata/discover", json={"limit": None})

    async def metadata_sync(self) -> dict:
        return await self._req("POST", "/api/metadata/sync", json={"mangaIds": None})
