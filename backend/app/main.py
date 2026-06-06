from __future__ import annotations

import threading
from pathlib import Path

import shutil

import psutil
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from . import repository
from .asura import AsuraClient
from .config import load_settings
from .database import connect, init_db
from .komga import KomgaClient, KomgaSettings, komga_book_url, latest_read_book
from .library import scan_library, transfer_chapters
from .metadata_discovery import discover_unmatched_local_metadata, unmatched_local_books
from .metadata_sync import sync_manga_metadata_to_komga
from .queue import DownloadQueue
from .scanner import scan_specific, scan_priority_books
from .scheduler import ScanScheduler
from .utils import normalize_title
from .utils import chapter_key


class SpecificScanRequest(BaseModel):
    query: str


class FullScanRequest(BaseModel):
    limit: int | None = None


class TopUpThresholdRequest(BaseModel):
    threshold: int


class DuplicateResolveRequest(BaseModel):
    status: str


class DuplicateGroupResolveRequest(BaseModel):
    remote_manga_id: int
    main_folder: str


class LocalDupMainRequest(BaseModel):
    main_folder: str


class MetadataSyncRequest(BaseModel):
    mangaIds: list[int] | None = None


class MetadataDiscoverRequest(BaseModel):
    limit: int | None = None


class SettingsRequest(BaseModel):
    autoScanEveryDays: int
    downloadConcurrency: int
    browserConcurrency: int = 2
    imageDownloadWorkers: int = 4
    readerEngine: str = "playwright"
    komgaAutoEnabled: bool = False
    reorganizeOnDrain: bool = False


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


class LocalBrowseRequest(BaseModel):
    search: str = ""
    genres: list[str] = Field(default_factory=list)
    status: str = "all"
    type: str = "all"
    sort: str = "title"
    order: str = "asc"
    minChapters: int = 0
    maxChapters: int = 0
    limit: int = 36
    offset: int = 0


class ReadThroughChapterRequest(BaseModel):
    chapterNumber: float


class LowProgressUnreadRequest(BaseModel):
    minimumReadOrReading: int = 30


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
repository.set_setting(
    conn,
    "browser_concurrency",
    repository.get_setting(conn, "browser_concurrency", str(settings.browser_concurrency)),
)
repository.set_setting(
    conn,
    "image_download_workers",
    repository.get_setting(conn, "image_download_workers", str(settings.image_download_workers)),
)
repository.set_setting(
    conn,
    "reader_engine",
    repository.get_setting(conn, "reader_engine", settings.reader_engine),
)
repository.set_setting(
    conn,
    "komga_auto_enabled",
    repository.get_setting(conn, "komga_auto_enabled", "0"),
)


def bounded_setting_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(repository.get_setting(conn, key, str(default)) or str(default))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def reader_engine_setting(default: str = "playwright") -> str:
    value = repository.get_setting(conn, "reader_engine", default)
    return value if value in {"playwright", "selenium"} else default


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
    bounded_setting_int("download_concurrency", settings.download_concurrency, 1, 6),
    bounded_setting_int("browser_concurrency", settings.browser_concurrency, 1, 4),
    bounded_setting_int("image_download_workers", settings.image_download_workers, 1, 8),
    reader_engine_setting(settings.reader_engine),
)
scan_scheduler = ScanScheduler(conn, asura_client, settings.library_root)
scan_stop_event = threading.Event()

_reorg_stop = threading.Event()
_reorg_thread: threading.Thread | None = None
_reorg_last_result: dict | None = None
_reorg_lock = threading.Lock()


def _reorg_running() -> bool:
    return _reorg_thread is not None and _reorg_thread.is_alive()


from .flush import SystemFlusher  # noqa: E402  (after module-level vars are defined)
_flusher = SystemFlusher()

app = FastAPI(title="Manga Crawler")
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
    repository.set_setting(conn, "limited_scan_batch_running", "0")
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
        "komgaPublicUrl": settings.komga_public_url,
        "komgaBooksRootDocker": settings.komga_books_root_docker,
        "database": str(db_path),
        "queuePaused": download_queue.paused,
        "downloadConcurrency": download_queue.concurrency,
        "browserConcurrency": download_queue.browser_concurrency,
        "imageDownloadWorkers": download_queue.image_download_workers,
        "readerEngine": download_queue.reader_engine,
        "komgaAutoEnabled": repository.get_setting(conn, "komga_auto_enabled", "0") == "1",
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
    data["cpuPercent"] = psutil.cpu_percent(interval=None)
    try:
        du = shutil.disk_usage(str(settings.library_root))
        data["diskTotal"] = du.total
        data["diskFree"] = du.free
        data["diskUsed"] = du.used
    except Exception:
        data["diskTotal"] = 0
        data["diskFree"] = 0
        data["diskUsed"] = 0
    data["queuePaused"] = download_queue.paused
    data["libraryRoot"] = str(settings.library_root)
    data["komgaUrl"] = settings.komga_url
    data["komgaPublicUrl"] = settings.komga_public_url
    data["komgaAutoEnabled"] = repository.get_setting(conn, "komga_auto_enabled", "0") == "1"
    data["reorganizeOnDrain"] = repository.get_setting(conn, "reorganize_on_drain", "0") == "1"
    data["autoScanEveryDays"] = int(repository.get_setting(conn, "auto_scan_every_days", "0") or "0")
    data["downloadConcurrency"] = download_queue.concurrency
    data["browserConcurrency"] = download_queue.browser_concurrency
    data["imageDownloadWorkers"] = download_queue.image_download_workers
    data["readerEngine"] = download_queue.reader_engine
    data["limitedScanActive"] = repository.get_setting(conn, "limited_scan_active", "0") == "1"
    data["scanRunning"] = scan_scheduler.scan_running
    data["reorganizeRunning"] = _reorg_running()
    data["flushRunning"] = _flusher.running
    data["limitedScanActiveThreshold"] = int(repository.get_setting(conn, "limited_scan_active_threshold", "300") or "300")
    return data


@app.get("/api/books")
def books(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_manga(conn)


@app.get("/api/books/{manga_id}")
def book_detail(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    detail = repository.get_manga_detail(conn, manga_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="manga not found")
    if settings.komga_url and detail.get("komga_series_id"):
        try:
            books = komga_client.list_books_for_series(str(detail["komga_series_id"]))
            komga_by_chapter = {}
            for book in books:
                metadata = book.get("metadata") or {}
                number = (
                    metadata.get("number")
                    or metadata.get("numberSort")
                    or book.get("number")
                    or book.get("name")
                    or ""
                )
                key = chapter_key(str(number))
                if key and book.get("id"):
                    komga_by_chapter[key] = komga_book_url(settings.komga_public_url, str(book["id"]))
            for chapter in detail.get("chapters", []):
                chapter["komga_url"] = komga_by_chapter.get(chapter.get("chapter_key"))
            detail["latest_read"] = latest_read_book(books, settings.komga_public_url, str(detail["komga_series_id"]))
        except Exception as exc:
            repository.log(conn, "warning", f"Could not load Komga chapter links for {detail['title']}: {exc}")
    return detail


@app.get("/api/jobs")
def jobs(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_jobs(conn)


@app.get("/api/logs")
def recent_logs(limit: int = 100, _user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_recent_logs(conn, limit)


@app.get("/api/jobs/failed")
def failed_jobs(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_failed_download_jobs(conn)


@app.get("/api/duplicates")
def duplicate_candidates(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.list_duplicate_candidates(conn)


@app.get("/api/metadata/candidates")
def metadata_candidates(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return repository.metadata_sync_candidates(conn)


@app.get("/api/metadata/unmatched")
def metadata_unmatched(_user: dict = Depends(authenticated_user)) -> list[dict]:
    return unmatched_local_books(conn)


@app.post("/api/metadata/discover")
def discover_metadata(payload: MetadataDiscoverRequest | None = None, _user: dict = Depends(authenticated_user)) -> dict:
    result = discover_unmatched_local_metadata(conn, asura_client, payload.limit if payload else None)
    repository.log(
        conn,
        "info",
        f"Metadata discovery complete: {result['autoLinked']} auto-linked, "
        f"{result['reviewNeeded']} review, {result['skipped']} skipped, {len(result['errors'])} errors",
    )
    return result


@app.post("/api/metadata/sync")
def sync_metadata(payload: MetadataSyncRequest | None = None, _user: dict = Depends(authenticated_user)) -> dict:
    candidates = repository.metadata_sync_candidates(conn)
    requested = set(int(item) for item in (payload.mangaIds if payload and payload.mangaIds else []))
    if requested:
        candidates = [item for item in candidates if int(item["id"]) in requested]
    synced = 0
    needs_review = 0
    errors: list[str] = []
    for item in candidates:
        try:
            result = sync_manga_metadata_to_komga(conn, komga_client, int(item["id"]), asura_client)
            if result.get("synced"):
                synced += 1
            if result.get("needsReview"):
                needs_review += 1
        except Exception as exc:
            errors.append(f"{item['title']}: {exc}")
    repository.log(conn, "info", f"Metadata sync complete: {synced} synced, {needs_review} need review, {len(errors)} errors")
    return {"synced": synced, "needsReview": needs_review, "errors": errors}


@app.post("/api/duplicates/{candidate_id}/resolve")
def resolve_duplicate(candidate_id: int, payload: DuplicateResolveRequest, _user: dict = Depends(authenticated_user)) -> dict:
    try:
        result = repository.resolve_duplicate_candidate(conn, candidate_id, payload.status)
        repository.log(conn, "info", f"Duplicate candidate {candidate_id} resolved as {payload.status}; enqueued {result['enqueued']}")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/duplicates/{candidate_id}/local")
def delete_duplicate_local(candidate_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT * FROM duplicate_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="duplicate candidate not found")
    folder = Path(row["local_folder"])
    root = settings.library_root.resolve()
    try:
        target = folder.resolve()
    except FileNotFoundError:
        target = folder
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="duplicate folder is outside the configured library root")
    try:
        komga_deleted = komga_client.delete_library_for_book(row["local_title"])
        if folder.exists():
            shutil.rmtree(folder)
        now = repository.utc_now()
        conn.execute(
            "UPDATE duplicate_candidates SET status = 'ignored', resolved_at = ?, updated_at = ? WHERE id = ?",
            (now, now, candidate_id),
        )
        conn.commit()
        repository.log(conn, "info", f"Deleted duplicate local folder {folder}; Komga library deleted={komga_deleted}")
        return {"deleted": True, "folder": str(folder), "komgaDeleted": komga_deleted}
    except Exception as exc:
        repository.log(conn, "error", f"Duplicate local delete failed for {folder}: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/duplicates/{candidate_id}/resolve-local-main")
def resolve_local_dup_main(candidate_id: int, payload: LocalDupMainRequest, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT * FROM duplicate_candidates WHERE id = ? AND candidate_kind = 'local_local'", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="local_local candidate not found")

    keep_folder = Path(row["remote_folder"]) if row["remote_folder"] else None
    delete_folder = Path(row["local_folder"])
    main_is_keep = payload.main_folder == row["remote_folder"]
    main_is_delete = payload.main_folder == row["local_folder"]

    if not main_is_keep and not main_is_delete:
        raise HTTPException(status_code=400, detail="main_folder does not match either candidate folder")

    root = settings.library_root.resolve()
    main_folder = Path(payload.main_folder)
    try:
        target = main_folder.resolve()
    except FileNotFoundError:
        target = main_folder
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="main folder is outside the configured library root")

    # Transfer chapters from the richer folder to main if main has fewer
    transferred = 0
    if main_is_delete:
        # User picked the "delete" folder as main; "keep" folder is the dup
        main_folder_path = delete_folder
        dup_folder_path = keep_folder
        main_count = int(row["local_chapter_count"] or 0)
        dup_count = int(row["remote_chapter_count"] or 0)
    else:
        main_folder_path = keep_folder
        dup_folder_path = delete_folder
        main_count = int(row["remote_chapter_count"] or 0)
        dup_count = int(row["local_chapter_count"] or 0)

    if dup_folder_path and dup_count > main_count and main_folder_path and main_folder_path.exists() and dup_folder_path.exists():
        try:
            transferred = transfer_chapters(dup_folder_path, main_folder_path)
        except Exception as exc:
            repository.log(conn, "warning", f"Chapter transfer failed for local dup {candidate_id}: {exc}")

    deleted_folder = None
    if dup_folder_path and dup_folder_path.exists():
        try:
            komga_client.delete_library_for_book(dup_folder_path.name)
        except Exception:
            pass
        try:
            shutil.rmtree(dup_folder_path)
            deleted_folder = str(dup_folder_path)
        except Exception as exc:
            repository.log(conn, "warning", f"Could not delete dup folder {dup_folder_path}: {exc}")

    now = repository.utc_now()
    conn.execute(
        "UPDATE duplicate_candidates SET status = 'confirmed_exists', resolved_at = ?, updated_at = ? WHERE id = ?",
        (now, now, candidate_id),
    )
    conn.commit()
    repository.log(
        conn, "info",
        f"Local dup {candidate_id} resolved: main={main_folder_path}, deleted={deleted_folder}, transferred={transferred}",
    )
    return {"deleted": deleted_folder, "transferred": transferred, "mainFolder": str(main_folder_path)}


@app.post("/api/duplicates/group/resolve-main")
def resolve_duplicate_group(payload: DuplicateGroupResolveRequest, _user: dict = Depends(authenticated_user)) -> dict:
    remote_manga_id = payload.remote_manga_id
    main_folder_path = Path(payload.main_folder)
    root = settings.library_root.resolve()
    try:
        target = main_folder_path.resolve()
    except FileNotFoundError:
        target = main_folder_path
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="main folder is outside the configured library root")

    candidates = conn.execute(
        """
        SELECT * FROM duplicate_candidates
        WHERE candidate_kind = 'remote_local'
          AND remote_manga_id = ?
          AND status NOT IN ('ignored', 'confirmed_new')
        """,
        (remote_manga_id,),
    ).fetchall()

    main_candidate = next((c for c in candidates if c["local_folder"] == payload.main_folder), None)
    if main_candidate is None:
        raise HTTPException(status_code=404, detail="no matching candidate found for the given folder")

    other_candidates = [c for c in candidates if c["local_folder"] != payload.main_folder]

    transferred = 0
    if other_candidates and main_folder_path.exists():
        richest = max(other_candidates, key=lambda c: int(c["local_chapter_count"] or 0))
        if int(richest["local_chapter_count"] or 0) > int(main_candidate["local_chapter_count"] or 0):
            dup_path = Path(richest["local_folder"])
            if dup_path.exists():
                try:
                    transferred = transfer_chapters(dup_path, main_folder_path)
                except Exception as exc:
                    repository.log(conn, "warning", f"Chapter transfer from {dup_path} failed: {exc}")

    now = repository.utc_now()
    deleted_folders: list[str] = []

    for dup in other_candidates:
        folder = Path(dup["local_folder"])
        try:
            komga_client.delete_library_for_book(dup["local_title"])
        except Exception:
            pass
        try:
            if folder.exists():
                shutil.rmtree(folder)
                deleted_folders.append(str(folder))
        except Exception as exc:
            repository.log(conn, "warning", f"Could not delete dup folder {folder}: {exc}")
        conn.execute(
            "UPDATE duplicate_candidates SET status = 'ignored', resolved_at = ?, updated_at = ? WHERE id = ?",
            (now, now, dup["id"]),
        )

    conn.execute(
        "UPDATE duplicate_candidates SET status = 'confirmed_exists', resolved_at = ?, updated_at = ? WHERE id = ?",
        (now, now, main_candidate["id"]),
    )
    conn.execute(
        """
        UPDATE manga
        SET download_folder_override = ?,
            download_title_override = ?,
            local_folder = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (payload.main_folder, main_candidate["local_title"], payload.main_folder, now, remote_manga_id),
    )
    conn.commit()

    enqueued = 0
    try:
        inventory = repository.get_inventory_map(conn)
        local = inventory.get(normalize_title(main_candidate["local_title"]))
        local_keys: set[str] = local["chapters"] if local else set()
        missing = repository.find_missing_chapters(conn, remote_manga_id, local_keys)
        for chapter in missing:
            repository.enqueue_download(conn, remote_manga_id, int(chapter["id"]))
            enqueued += 1
    except Exception as exc:
        repository.log(conn, "warning", f"Could not enqueue missing chapters for manga {remote_manga_id}: {exc}")

    repository.log(
        conn,
        "info",
        f"Duplicate group resolved: manga {remote_manga_id}, main={payload.main_folder}, "
        f"deleted {len(deleted_folders)} folders, transferred {transferred} chapters, enqueued {enqueued}",
    )
    return {"confirmed": 1, "deleted": len(deleted_folders), "transferred": transferred, "enqueued": enqueued}


@app.get("/api/debug/threads")
def debug_threads(_user: dict = Depends(authenticated_user)) -> dict:
    threads = []
    for thread in threading.enumerate():
        threads.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            }
        )
    return {
        "threads": threads,
        "scanStopRequested": scan_stop_event.is_set(),
        "scheduler": scan_scheduler.debug_state(),
        "downloadQueue": download_queue.debug_state(),
        "settings": {
            "limitedScanActive": repository.get_setting(conn, "limited_scan_active", "0") == "1",
            "limitedScanBatchRunning": repository.get_setting(conn, "limited_scan_batch_running", "0") == "1",
            "limitedScanActiveThreshold": int(repository.get_setting(conn, "limited_scan_active_threshold", "300") or "300"),
            "autoScanEveryDays": int(repository.get_setting(conn, "auto_scan_every_days", "0") or "0"),
            "komgaAutoEnabled": repository.get_setting(conn, "komga_auto_enabled", "0") == "1",
            "browserConcurrency": download_queue.browser_concurrency,
            "imageDownloadWorkers": download_queue.image_download_workers,
            "readerEngine": download_queue.reader_engine,
        },
    }


@app.post("/api/debug/threads/{thread_ident}/stop")
def stop_thread(thread_ident: int, _user: dict = Depends(authenticated_user)) -> dict:
    thread = next((item for item in threading.enumerate() if item.ident == thread_ident), None)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")

    if thread.name.startswith("download-queue-"):
        result = download_queue.retire_worker(thread_ident)
        repository.log(conn, "info", f"Requested download worker stop for {thread.name}: {result['reason']}")
        return {
            "thread": thread.name,
            "action": "retire-download-worker",
            **result,
        }

    if any(part in thread.name for part in ("scan", "scheduler")):
        scan_stop_event.set()
        result = scan_scheduler.cancel_current_scan()
        repository.log(conn, "info", f"Requested scan thread stop for {thread.name}")
        return {
            "thread": thread.name,
            "action": "cancel-scan-work",
            "stopped": True,
            "reason": "scan cancellation requested; thread exits at next cancellation checkpoint",
            **result,
        }

    raise HTTPException(
        status_code=400,
        detail="This thread is not managed by the app. Arbitrary Python threads cannot be safely killed.",
    )


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


@app.post("/api/browse/books")
def browse_books(payload: LocalBrowseRequest, _user: dict = Depends(authenticated_user)) -> dict:
    return repository.list_browse_books(
        conn,
        search=payload.search,
        genres=payload.genres,
        status=payload.status,
        series_type=payload.type,
        sort=payload.sort,
        order=payload.order,
        min_chapters=payload.minChapters,
        max_chapters=payload.maxChapters,
        limit=payload.limit,
        offset=payload.offset,
        komga_url=settings.komga_public_url,
    )


@app.get("/api/settings")
def get_settings(_user: dict = Depends(authenticated_user)) -> dict:
    return {
        "libraryRoot": str(settings.library_root),
        "komgaUrl": settings.komga_url,
        "komgaPublicUrl": settings.komga_public_url,
        "komgaBooksRootDocker": settings.komga_books_root_docker,
        "komgaAutoEnabled": repository.get_setting(conn, "komga_auto_enabled", "0") == "1",
        "reorganizeOnDrain": repository.get_setting(conn, "reorganize_on_drain", "0") == "1",
        "autoScanEveryDays": int(repository.get_setting(conn, "auto_scan_every_days", "0") or "0"),
        "downloadConcurrency": download_queue.concurrency,
        "browserConcurrency": download_queue.browser_concurrency,
        "imageDownloadWorkers": download_queue.image_download_workers,
        "readerEngine": download_queue.reader_engine,
        "queuePaused": download_queue.paused,
        "limitedScanActive": repository.get_setting(conn, "limited_scan_active", "0") == "1",
        "scanRunning": scan_scheduler.scan_running,
        "reorganizeRunning": _reorg_running(),
        "limitedScanActiveThreshold": int(repository.get_setting(conn, "limited_scan_active_threshold", "300") or "300"),
    }


@app.post("/api/settings")
def update_settings(payload: SettingsRequest, _user: dict = Depends(authenticated_user)) -> dict:
    days = max(0, int(payload.autoScanEveryDays))
    concurrency = max(1, min(6, int(payload.downloadConcurrency)))
    browser_concurrency = max(1, min(4, int(payload.browserConcurrency)))
    image_download_workers = max(1, min(8, int(payload.imageDownloadWorkers)))
    reader_engine = payload.readerEngine if payload.readerEngine in {"playwright", "selenium"} else "playwright"
    komga_auto_enabled = bool(payload.komgaAutoEnabled)
    reorganize_on_drain = bool(payload.reorganizeOnDrain)
    repository.set_setting(conn, "auto_scan_every_days", str(days))
    repository.set_setting(conn, "download_concurrency", str(concurrency))
    repository.set_setting(conn, "browser_concurrency", str(browser_concurrency))
    repository.set_setting(conn, "image_download_workers", str(image_download_workers))
    repository.set_setting(conn, "reader_engine", reader_engine)
    repository.set_setting(conn, "komga_auto_enabled", "1" if komga_auto_enabled else "0")
    repository.set_setting(conn, "reorganize_on_drain", "1" if reorganize_on_drain else "0")
    download_queue.set_concurrency(concurrency)
    download_queue.set_reader_options(browser_concurrency, image_download_workers, reader_engine)
    repository.log(conn, "info", f"Auto full scan interval set to {days} days")
    repository.log(conn, "info", f"Download concurrency set to {concurrency}")
    repository.log(conn, "info", f"Reader engine set to {reader_engine}; browser concurrency {browser_concurrency}; image workers {image_download_workers}")
    repository.log(conn, "info", f"Auto Komga import/scan set to {'enabled' if komga_auto_enabled else 'disabled'}")
    repository.log(conn, "info", f"Auto reorganize by chapters set to {'enabled' if reorganize_on_drain else 'disabled'}")
    return get_settings(_user)


@app.post("/api/scan/library")
def scan_local_library(_user: dict = Depends(authenticated_user)) -> dict:
    return scan_library(conn, settings.library_root)


@app.post("/api/library/reorganize")
def reorganize_library_endpoint(_user: dict = Depends(authenticated_user)) -> dict:
    global _reorg_thread, _reorg_last_result
    from .library_organizer import reorganize_library
    with _reorg_lock:
        if _reorg_running():
            raise HTTPException(status_code=409, detail="reorganize already running")
        _reorg_stop.clear()
        _reorg_last_result = None

        def _run() -> None:
            global _reorg_last_result
            try:
                _reorg_last_result = reorganize_library(conn, settings.library_root, komga_client, _reorg_stop)
                repository.log(
                    conn, "info",
                    f"Reorganize finished: {_reorg_last_result.get('moved', 0)} moved, "
                    f"{_reorg_last_result.get('skippedActive', 0)} skipped (active)",
                )
            except Exception as exc:
                _reorg_last_result = {"error": str(exc)}
                repository.log(conn, "error", f"Reorganize failed: {exc}")

        _reorg_thread = threading.Thread(target=_run, name="library-reorganize", daemon=True)
        _reorg_thread.start()
    return {"started": True, "running": True}


@app.post("/api/library/reorganize/stop")
def stop_reorganize(_user: dict = Depends(authenticated_user)) -> dict:
    _reorg_stop.set()
    repository.log(conn, "info", "Reorganize stop requested")
    return {"stopped": True}


@app.get("/api/library/reorganize/status")
def reorganize_status(_user: dict = Depends(authenticated_user)) -> dict:
    return {"running": _reorg_running(), "result": _reorg_last_result}


@app.post("/api/library/komga-cleanup")
def komga_cleanup_endpoint(_user: dict = Depends(authenticated_user)) -> dict:
    from .library_organizer import cleanup_per_book_libraries
    result = cleanup_per_book_libraries(conn, settings.library_root, komga_client)
    repository.log(
        conn, "info",
        f"Komga cleanup: {result.get('deleted', 0)} per-book libraries deleted, "
        f"{result.get('komgaScanned', 0)} range libraries scanned",
    )
    return result


@app.post("/api/system/flush")
def start_system_flush(_user: dict = Depends(authenticated_user)) -> dict:
    started = _flusher.start(
        conn=conn,
        settings=settings,
        download_queue=download_queue,
        komga_client=komga_client,
        asura_client=asura_client,
        scan_scheduler=scan_scheduler,
        scan_stop_event=scan_stop_event,
    )
    if not started:
        raise HTTPException(status_code=409, detail="System flush already running")
    repository.log(conn, "info", "System flush started")
    return {"started": True}


@app.post("/api/system/flush/stop")
def stop_system_flush(_user: dict = Depends(authenticated_user)) -> dict:
    _flusher.stop()
    repository.log(conn, "info", "System flush stop requested")
    return {"stopped": True}


@app.get("/api/system/flush/status")
def system_flush_status(_user: dict = Depends(authenticated_user)) -> dict:
    return _flusher.status()


@app.post("/api/scan/full")
def start_full_scan(payload: FullScanRequest | None = None, _user: dict = Depends(authenticated_user)) -> dict:
    scan_stop_event.clear()
    scan_scheduler.run_full_scan_async(None)
    return {"started": True, "limit": None}


@app.post("/api/scan/top-up")
def start_top_up(payload: FullScanRequest, _user: dict = Depends(authenticated_user)) -> dict:
    threshold = max(1, min(5000, int(payload.limit or 300)))
    scan_stop_event.clear()
    return scan_scheduler.start_limited_scan_async(threshold)


@app.post("/api/scan/top-up-threshold")
def update_top_up_threshold(payload: TopUpThresholdRequest, _user: dict = Depends(authenticated_user)) -> dict:
    threshold = repository.set_limited_scan_threshold(conn, max(1, min(5000, int(payload.threshold))))
    repository.log(conn, "info", f"Top-up threshold default set to {threshold} active chapters")
    return {"threshold": threshold}


@app.post("/api/scan/stop")
def stop_scan(_user: dict = Depends(authenticated_user)) -> dict:
    scan_stop_event.set()
    return scan_scheduler.cancel_current_scan()


@app.post("/api/scan/stop-all")
def stop_all_scans(_user: dict = Depends(authenticated_user)) -> dict:
    scan_stop_event.set()
    return scan_scheduler.stop_all_scan_work()


@app.post("/api/scan/specific")
def start_specific_scan(payload: SpecificScanRequest, _user: dict = Depends(authenticated_user)) -> dict:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    def worker() -> None:
        try:
            if scan_stop_event.is_set():
                repository.log(conn, "info", f"Specific scan skipped after stop request: {query}")
                return
            scan_specific(conn, asura_client, settings.library_root, query, should_stop=scan_stop_event.is_set)
        except Exception as exc:
            repository.log(conn, "error", f"Specific scan failed for {query}: {exc}")

    scan_stop_event.clear()
    threading.Thread(target=worker, name="specific-scan", daemon=True).start()
    return {"started": True, "query": query}


@app.post("/api/scan/specific-priority")
def start_specific_priority_scan(payload: SpecificScanRequest, _user: dict = Depends(authenticated_user)) -> dict:
    """Scan a single book at priority=2. Other books keep running but this one is downloaded first."""
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    def worker() -> None:
        try:
            if scan_stop_event.is_set():
                repository.log(conn, "info", f"Priority-add scan skipped after stop request: {query}")
                return
            result = scan_specific(conn, asura_client, settings.library_root, query, priority=2, should_stop=scan_stop_event.is_set)
            if result.get("stopped") or int(result.get("mangaId") or 0) <= 0:
                repository.log(conn, "info", f"Priority-add scan stopped before enqueueing: {query}")
                return
            repository.stop_limited_scan_state(conn)
            paused = repository.pause_downloads_except_manga_ids(conn, [int(result["mangaId"])])
            repository.log(conn, "info", f"Asura search add is exclusive: paused {paused} other queued downloads")
        except Exception as exc:
            repository.log(conn, "error", f"Priority-add scan failed for {query}: {exc}")

    scan_stop_event.clear()
    threading.Thread(target=worker, name="priority-add-scan", daemon=True).start()
    return {"started": True, "query": query}


@app.post("/api/books/{manga_id}/download-now")
def download_now(manga_id: int, _user: dict = Depends(authenticated_user)) -> dict:
    """Atomically pause other books' queued downloads and elevate this book to priority=2."""
    row = conn.execute("SELECT title, url FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    paused, upgraded = repository.download_now_atomic(conn, manga_id)
    repository.log(conn, "info", f"Download now: {row['title']} — {upgraded} jobs → priority=2, {paused} others paused")
    if upgraded == 0:
        # No queued jobs exist yet — trigger a fresh scan to enqueue missing chapters at priority=2
        query = row["url"] or row["title"]
        def scan_worker() -> None:
            try:
                if scan_stop_event.is_set():
                    repository.log(conn, "info", f"Download now scan skipped after stop request: {row['title']}")
                    return
                scan_specific(conn, asura_client, settings.library_root, query, priority=2, should_stop=scan_stop_event.is_set)
            except Exception as exc:
                repository.log(conn, "error", f"Download now scan failed for {row['title']}: {exc}")
                repository.maybe_resume_auto_paused(conn)
        scan_stop_event.clear()
        threading.Thread(target=scan_worker, name="download-now-scan", daemon=True).start()
    return {"paused": paused, "upgraded": upgraded, "mangaId": manga_id}


@app.post("/api/queue/pause")
def pause_queue(_user: dict = Depends(authenticated_user)) -> dict:
    download_queue.pause()
    return {"queuePaused": True}


@app.post("/api/queue/resume")
def resume_queue(_user: dict = Depends(authenticated_user)) -> dict:
    download_queue.resume()
    return {"queuePaused": False}


@app.post("/api/queue/enqueue-missing")
def enqueue_missing(_user: dict = Depends(authenticated_user)) -> dict:
    count = repository.enqueue_all_missing(conn)
    repository.log(conn, "info", f"Re-enqueued {count} missing chapters from known catalog")
    return {"enqueued": count}


@app.post("/api/scan/reset-missing")
def reset_missing(_user: dict = Depends(authenticated_user)) -> dict:
    result = repository.reset_missing_chapters(conn)
    repository.log(
        conn,
        "info",
        f"Reset missing chapter state: {result['mangaReset']} titles, {result['chaptersReset']} chapters, {result['jobsRemoved']} old jobs removed",
    )
    return result


@app.delete("/api/queue/queued")
def delete_queued_downloads(_user: dict = Depends(authenticated_user)) -> dict:
    count = repository.delete_queued_downloads(conn)
    repository.log(conn, "info", f"Removed {count} queued download jobs")
    return {"removed": count}


@app.delete("/api/queue/queued-zero-percent")
def delete_zero_percent_queued_downloads(_user: dict = Depends(authenticated_user)) -> dict:
    count = repository.delete_queued_downloads(conn, zero_percent_only=True)
    repository.log(conn, "info", f"Removed {count} zero-percent queued download jobs")
    return {"removed": count}


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


@app.post("/api/komga/books/{manga_id}/read-through")
def mark_book_read_through(manga_id: int, payload: ReadThroughChapterRequest, _user: dict = Depends(authenticated_user)) -> dict:
    row = conn.execute("SELECT title, komga_series_id FROM manga WHERE id = ?", (manga_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="manga not found")
    series_id = str(row["komga_series_id"] or "").strip()
    if not series_id:
        raise HTTPException(status_code=400, detail="book is not linked to a Komga series")
    try:
        books = komga_client.list_books_for_series(series_id)
        marked = komga_client.mark_books_read_through_chapter(books, float(payload.chapterNumber))
        repository.log(conn, "info", f"Marked {marked} Komga chapters read for {row['title']} through chapter {payload.chapterNumber:g}")
        return {"marked": marked, "mangaId": manga_id, "chapterNumber": payload.chapterNumber}
    except Exception as exc:
        repository.log(conn, "error", f"Komga read-through failed for {row['title']}: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/komga/read-progress/unread-all")
def mark_all_komga_unread(_user: dict = Depends(authenticated_user)) -> dict:
    if not komga_client.enabled:
        raise HTTPException(status_code=400, detail="Komga is not configured")
    series_ids = repository.list_komga_series_ids(conn)
    marked = 0
    errors: list[str] = []
    for series_id in series_ids:
        try:
            komga_client.mark_series_unread(series_id)
            marked += 1
        except Exception as exc:
            errors.append(f"{series_id}: {exc}")
    repository.log(conn, "info", f"Marked {marked}/{len(series_ids)} Komga series unread")
    if errors:
        raise HTTPException(status_code=502, detail={"markedSeries": marked, "errors": errors})
    return {"markedSeries": marked, "totalSeries": len(series_ids)}


@app.post("/api/komga/read-progress/unread-low-progress")
def mark_low_progress_komga_unread(payload: LowProgressUnreadRequest | None = None, _user: dict = Depends(authenticated_user)) -> dict:
    if not komga_client.enabled:
        raise HTTPException(status_code=400, detail="Komga is not configured")
    minimum = max(1, int(payload.minimumReadOrReading if payload else 30))
    try:
        result = komga_client.mark_low_progress_series_unread(minimum)
        repository.log(
            conn,
            "info",
            f"Marked {result['seriesMarkedUnread']}/{result['seriesChecked']} Komga series unread with fewer than {minimum} read/reading chapters",
        )
        if result["errors"]:
            raise HTTPException(status_code=502, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        repository.log(conn, "error", f"Komga low-progress unread failed: {exc}")
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
        "limit": max(1, min(100, int(payload.limit))),
        "offset": max(0, int(payload.offset)),
    }

    def worker() -> None:
        try:
            if scan_stop_event.is_set():
                repository.log(conn, "info", "Priority scan skipped after stop request")
                return
            result = scan_priority_books(conn, asura_client, settings.library_root, search_kwargs, should_stop=scan_stop_event.is_set)
            repository.stop_limited_scan_state(conn)
            manga_ids = [int(manga_id) for manga_id in result.get("mangaIds", [])]
            paused = repository.pause_downloads_except_manga_ids(conn, manga_ids) if manga_ids else 0
            repository.log(conn, "info", f"Asura search page add is exclusive: paused {paused} other queued downloads")
        except Exception as exc:
            repository.log(conn, "error", f"Priority scan failed: {exc}")

    scan_stop_event.clear()
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
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catchall(_request: Request, full_path: str) -> FileResponse:
        candidate = frontend_dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
