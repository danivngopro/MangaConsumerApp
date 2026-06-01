from __future__ import annotations

import threading
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from . import repository
from .asura import AsuraClient
from .config import load_settings
from .database import connect, init_db
from .komga import KomgaClient, KomgaSettings
from .library import scan_library
from .queue import DownloadQueue
from .scanner import scan_specific, scan_priority_books
from .scheduler import ScanScheduler
from .utils import normalize_title


class SpecificScanRequest(BaseModel):
    query: str


class FullScanRequest(BaseModel):
    limit: int | None = None


class SettingsRequest(BaseModel):
    autoScanEveryDays: int
    downloadConcurrency: int


class BrowseSearchRequest(BaseModel):
    search: str = ""
    genres: list[str] = Field(default_factory=list)
    author: str = ""
    artist: str = ""
    status: str = "all"
    type: str = "all"
    sort: str = "latest"
    order: str = "desc"
    minChapters: int = 0
    maxChapters: int = 0
    limit: int = 24
    offset: int = 0


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
    interrupted = repository.requeue_interrupted_downloads(conn)
    if interrupted:
        repository.log(conn, "info", f"Requeued {interrupted} interrupted downloads after startup")
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


@app.get("/api/asura/filters")
def asura_filters(_user: dict = Depends(authenticated_user)) -> dict:
    return asura_client.browse_filters()


@app.post("/api/asura/search")
def asura_search(payload: BrowseSearchRequest, _user: dict = Depends(authenticated_user)) -> dict:
    result = asura_client.search_series(
        search=payload.search.strip(),
        genres=",".join(payload.genres),
        author=payload.author.strip(),
        artist=payload.artist.strip(),
        status=payload.status,
        series_type=payload.type,
        sort=payload.sort,
        order=payload.order,
        min_chapters=max(0, int(payload.minChapters)),
        max_chapters=max(0, int(payload.maxChapters)),
        limit=max(1, min(100, int(payload.limit))),
        offset=max(0, int(payload.offset)),
    )
    inventory = repository.get_inventory_map(conn)
    tracked = {row["normalized_title"]: dict(row) for row in conn.execute("SELECT * FROM manga").fetchall()}
    for item in result["items"]:
        normalized = normalize_title(item["title"])
        local = inventory.get(normalized)
        tracked_item = tracked.get(normalized)
        item["is_existing"] = bool(local)
        item["is_tracked"] = bool(tracked_item)
        item["local_chapter_count"] = int(local["chapter_count"]) if local else (int(tracked_item["local_chapter_count"]) if tracked_item else 0)
        item["missing_count"] = max(0, int(item["chapter_count"] or 0) - int(item["local_chapter_count"] or 0))
        item["local_folder"] = local["folder_path"] if local else (tracked_item["local_folder"] if tracked_item else None)
    return result


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


@app.post("/api/scan/specific-priority")
def start_specific_priority_scan(payload: SpecificScanRequest, _user: dict = Depends(authenticated_user)) -> dict:
    """Scan a single book at priority=2. Auto-pauses other queued jobs first."""
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    paused = repository.auto_pause_queued_jobs(conn)
    repository.log(conn, "info", f"Priority add: auto-paused {paused} queued jobs for '{query}'")

    def worker() -> None:
        try:
            scan_specific(conn, asura_client, settings.library_root, query, priority=2)
        except Exception as exc:
            repository.log(conn, "error", f"Priority-add scan failed for {query}: {exc}")
            repository.maybe_resume_auto_paused(conn)

    threading.Thread(target=worker, name="priority-add-scan", daemon=True).start()
    return {"started": True, "query": query}


@app.post("/api/books/{manga_id}/download-now")
def download_now(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    """Pause other books and download this one next."""
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    paused = repository.auto_pause_other_queued_jobs(conn, manga_id)
    upgraded = repository.set_manga_download_priority(conn, manga_id, priority=2)
    repository.log(conn, "info", f"Download now: {row['title']} — upgraded {upgraded} jobs to priority=2, paused {paused} others")
    return {"paused": paused, "upgraded": upgraded, "mangaId": manga_id}


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


@app.post("/api/jobs/retry-failed")
def retry_failed_jobs(_user: dict = Depends(authenticated_user)) -> dict:
    count = repository.retry_failed_downloads(conn)
    repository.log(conn, "info", f"Requeued {count} failed download jobs")
    return {"requeued": count}


@app.post("/api/books/{manga_id}/downloads/retry-failed")
def retry_failed_book_downloads(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    count = repository.retry_failed_downloads(conn, manga_id)
    repository.log(conn, "info", f"Requeued {count} failed downloads for {row['title']}")
    return {"requeued": count, "mangaId": manga_id}


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


@app.post("/api/komga/books/{manga_id}/import")
def import_book_to_komga(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    try:
        library = komga_client.import_book(row["title"])
        repository.update_komga_status(conn, manga_id, str(library["id"]), True, False, None)
        repository.log(conn, "info", f"Manual Komga import for {row['title']}")
        return {"imported": True, "libraryId": library["id"], "title": row["title"]}
    except Exception as exc:
        repository.update_komga_status(conn, manga_id, None, False, False, str(exc))
        repository.log(conn, "error", f"Manual Komga import failed for {row['title']}: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/komga/import-all")
def import_all_books(_user: dict = Depends(authenticated_user)) -> dict:
    def worker() -> None:
        try:
            result = komga_client.import_all_books(settings.library_root)
            repository.log(conn, "info", f"Import all complete: {result['created']} created, {result['scanned']} scanned")
        except Exception as exc:
            repository.log(conn, "error", f"Import all failed: {exc}")

    threading.Thread(target=worker, name="import-all", daemon=True).start()
    return {"started": True}


@app.post("/api/scan/priority")
def start_priority_scan(payload: BrowseSearchRequest, _user: dict = Depends(authenticated_user)) -> dict:
    search_kwargs = {
        "search": payload.search.strip(),
        "genres": ",".join(payload.genres),
        "author": payload.author.strip(),
        "artist": payload.artist.strip(),
        "status": payload.status,
        "series_type": payload.type,
        "sort": payload.sort,
        "order": payload.order,
        "min_chapters": max(0, int(payload.minChapters)),
        "max_chapters": max(0, int(payload.maxChapters)),
    }

    def worker() -> None:
        try:
            scan_priority_books(conn, asura_client, settings.library_root, search_kwargs)
        except Exception as exc:
            repository.log(conn, "error", f"Priority scan failed: {exc}")

    threading.Thread(target=worker, name="priority-scan", daemon=True).start()
    return {"started": True}


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
