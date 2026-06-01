from __future__ import annotations

import threading
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth
from . import repository
from .asura import AsuraClient
from .config import load_settings
from .database import connect, init_db
from .komga import KomgaClient, KomgaSettings
from .library import scan_library
from .queue import DownloadQueue
from .scanner import scan_specific
from .scheduler import ScanScheduler


class SpecificScanRequest(BaseModel):
    query: str


class FullScanRequest(BaseModel):
    limit: int | None = None


class SettingsRequest(BaseModel):
    autoScanEveryDays: int
    downloadConcurrency: int


settings = load_settings()
settings.app_data_dir.mkdir(parents=True, exist_ok=True)
db_path = settings.app_data_dir / "manga-recoverer.sqlite3"
conn = connect(db_path)
init_db(conn)

repository.set_setting(
    conn,
    "auto_scan_every_days",
    repository.get_setting(conn, "auto_scan_every_days", str(settings.auto_scan_every_days)),
)
repository.set_setting(
    conn,
    "download_concurrency",
    repository.get_setting(conn, "download_concurrency", str(settings.download_concurrency)),
)

asura_client = AsuraClient(settings.asura_base_url, settings.request_delay_seconds)
komga_client = KomgaClient(
    KomgaSettings(
        url=settings.komga_url,
        username=settings.komga_username,
        password=settings.komga_password,
        books_root_docker=settings.komga_books_root_docker,
    )
)
download_queue = DownloadQueue(
    conn,
    settings.library_root,
    settings.app_data_dir / "tmp",
    komga_client,
    int(repository.get_setting(conn, "download_concurrency", str(settings.download_concurrency))),
)
scan_scheduler = ScanScheduler(conn, asura_client, settings.library_root)

app = FastAPI(title="Asura Komga Manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def authenticated_user(
    token: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE),
) -> dict:
    return auth.require_user(conn, token)


@app.on_event("startup")
def on_startup() -> None:
    download_queue.start()
    scan_scheduler.start()
    repository.log(conn, "info", f"Backend started with library root: {settings.library_root}")


@app.on_event("shutdown")
def on_shutdown() -> None:
    scan_scheduler.stop()
    download_queue.stop()
    conn.close()


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "libraryRoot": str(settings.library_root),
        "komgaUrl": settings.komga_url,
        "komgaBooksRootDocker": settings.komga_books_root_docker,
        "database": str(db_path),
        "queuePaused": download_queue.paused,
        "downloadConcurrency": download_queue.concurrency,
    }


@app.get("/api/auth/status")
def auth_status(token: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return auth.auth_status(conn, token)


@app.post("/api/auth/register")
def register(payload: auth.AuthRequest, response: Response) -> dict:
    return auth.register_first_user(conn, payload.username, payload.password, response)


@app.post("/api/auth/login")
def login(payload: auth.AuthRequest, response: Response) -> dict:
    return auth.login(conn, payload.username, payload.password, response)


@app.post("/api/auth/logout")
def logout(response: Response, token: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return auth.logout(conn, token, response)


@app.get("/api/summary")
def summary(_user: dict = Depends(authenticated_user)) -> dict:
    data = repository.summary(conn)
    data["queuePaused"] = download_queue.paused
    data["libraryRoot"] = str(settings.library_root)
    data["komgaUrl"] = settings.komga_url
    data["autoScanEveryDays"] = int(repository.get_setting(conn, "auto_scan_every_days", "0") or "0")
    data["downloadConcurrency"] = download_queue.concurrency
    return data


@app.get("/api/books")
def books(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_manga(conn)


@app.get("/api/books/{manga_id}")
def book_detail(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    detail = repository.get_manga_detail(conn, manga_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="manga not found")
    return detail


@app.get("/api/jobs")
def jobs(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_jobs(conn)


@app.get("/api/progress")
def progress(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.download_progress(conn)


@app.get("/api/settings")
def get_settings(_user: dict = Depends(authenticated_user)) -> dict:
    return {
        "libraryRoot": str(settings.library_root),
        "komgaUrl": settings.komga_url,
        "komgaBooksRootDocker": settings.komga_books_root_docker,
        "autoScanEveryDays": int(repository.get_setting(conn, "auto_scan_every_days", "0") or "0"),
        "downloadConcurrency": download_queue.concurrency,
        "queuePaused": download_queue.paused,
    }


@app.post("/api/settings")
def update_settings(payload: SettingsRequest, _user: dict = Depends(authenticated_user)) -> dict:
    days = max(0, int(payload.autoScanEveryDays))
    concurrency = max(1, min(6, int(payload.downloadConcurrency)))
    repository.set_setting(conn, "auto_scan_every_days", str(days))
    repository.set_setting(conn, "download_concurrency", str(concurrency))
    download_queue.set_concurrency(concurrency)
    repository.log(conn, "info", f"Auto full scan interval set to {days} days")
    repository.log(conn, "info", f"Download concurrency set to {concurrency}")
    return get_settings(_user)


@app.post("/api/scan/library")
def scan_local_library(_user: dict = Depends(authenticated_user)) -> dict:
    return scan_library(conn, settings.library_root)


@app.post("/api/scan/full")
def start_full_scan(payload: FullScanRequest | None = None, _user: dict = Depends(authenticated_user)) -> dict:
    limit = None
    if payload and payload.limit is not None:
        limit = max(1, min(500, int(payload.limit)))
    scan_scheduler.run_full_scan_async(limit)
    return {"started": True, "limit": limit}


@app.post("/api/scan/specific")
def start_specific_scan(payload: SpecificScanRequest, _user: dict = Depends(authenticated_user)) -> dict:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    def worker() -> None:
        try:
            scan_specific(conn, asura_client, settings.library_root, query)
        except Exception as exc:
            repository.log(conn, "error", f"Specific scan failed for {query}: {exc}")

    threading.Thread(target=worker, name="specific-scan", daemon=True).start()
    return {"started": True, "query": query}


@app.post("/api/queue/pause")
def pause_queue(_user: dict = Depends(authenticated_user)) -> dict:
    download_queue.pause()
    return {"queuePaused": True}


@app.post("/api/queue/resume")
def resume_queue(_user: dict = Depends(authenticated_user)) -> dict:
    download_queue.resume()
    return {"queuePaused": False}


@app.post("/api/books/{manga_id}/downloads/pause")
def pause_book_downloads(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    count = repository.pause_downloads_for_manga(conn, manga_id)
    repository.log(conn, "info", f"Paused {count} queued downloads for {row['title']}")
    return {"paused": count, "mangaId": manga_id}


@app.post("/api/books/{manga_id}/downloads/resume")
def resume_book_downloads(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    count = repository.resume_downloads_for_manga(conn, manga_id)
    repository.log(conn, "info", f"Resumed {count} paused downloads for {row['title']}")
    return {"resumed": count, "mangaId": manga_id}


@app.post("/api/komga/books/{manga_id}/quick-scan")
def quick_scan_book(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    try:
        library = komga_client.quick_scan_book(row["title"])
        repository.update_komga_status(conn, manga_id, str(library["id"]), False, True, None)
        repository.log(conn, "info", f"Manual Komga quick scan for {row['title']} with deep=false")
        return {"scanned": True, "libraryId": library["id"], "title": row["title"], "deep": False}
    except Exception as exc:
        repository.update_komga_status(conn, manga_id, None, False, False, str(exc))
        repository.log(conn, "error", f"Manual Komga quick scan failed for {row['title']}: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/komga/quick-scan-all")
def quick_scan_all_books(_user: dict = Depends(authenticated_user)) -> dict:
    try:
        count = komga_client.quick_scan_all()
        repository.log(conn, "info", f"Manual Komga quick scan for all libraries with deep=false: {count}")
        return {"scanned": True, "libraryCount": count, "deep": False}
    except Exception as exc:
        repository.log(conn, "error", f"Manual Komga quick scan all failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
