from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass

import requests

from . import repository
from .utils import chapter_key, sanitize_filename


@dataclass(frozen=True)
class KomgaSettings:
    url: str
    username: str
    password: str
    books_root_docker: str


class KomgaClient:
    def __init__(self, settings: KomgaSettings) -> None:
        self.settings = settings
        self.session = requests.Session()
        if settings.username or settings.password:
            self.session.auth = (settings.username, settings.password)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.url)

    @property
    def libraries_url(self) -> str:
        return f"{self.settings.url}/api/v1/libraries"

    def list_libraries(self) -> list[dict]:
        response = self.session.get(self.libraries_url, timeout=30)
        response.raise_for_status()
        return response.json()

    def list_libraries_by_root(self) -> dict[str, dict]:
        """Single API call → dict keyed by docker root path (rstripped)."""
        return {(lib.get("root") or "").rstrip("/"): lib for lib in self.list_libraries()}

    def find_library_for_book(self, book_title: str) -> dict | None:
        docker_root = self.docker_root_for_book(book_title)
        for library in self.list_libraries():
            if library.get("root") == docker_root:
                return library
        return None

    def ensure_library_for_book(self, book_title: str) -> tuple[dict, bool]:
        existing = self.find_library_for_book(book_title)
        if existing:
            return existing, False
        docker_root = self.docker_root_for_book(book_title)
        payload = {
            "name": self.sanitize_name(book_title),
            "root": docker_root,
            "importComicInfoBook": True,
            "importComicInfoSeries": True,
            "importComicInfoCollection": True,
            "importEpubBook": True,
            "importEpubSeries": True,
            "scanForceModifiedTime": True,
            "repairExtensions": True,
            "convertToCbz": True,
            "emptyTrashAfterScan": True,
            "scanOnStartup": False,
        }
        response = self.session.post(self.libraries_url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json(), True

    def quick_scan_library(self, library_id: str) -> None:
        response = self.session.post(f"{self.libraries_url}/{library_id}/scan?deep=false", timeout=30)
        response.raise_for_status()

    def get_tasks(self) -> list[dict]:
        """Return active Komga background tasks proxied for the frontend."""
        try:
            resp = self.session.get(f"{self.settings.url}/api/v1/tasks", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tasks = data if isinstance(data, list) else data.get("content", [])
            return [
                {
                    "name": t.get("type") or t.get("name") or "Task",
                    "progress": t.get("progress"),
                }
                for t in tasks
            ]
        except Exception:
            return []

    def quick_scan_book(self, book_title: str) -> dict:
        library, _created = self.ensure_library_for_book(book_title)
        self.quick_scan_library(str(library["id"]))
        return library

    def import_book(self, book_title: str) -> dict:
        library, _created = self.ensure_library_for_book(book_title)
        return library

    def delete_library_for_book(self, book_title: str) -> bool:
        library = self.find_library_for_book(book_title)
        if not library:
            return False
        response = self.session.delete(f"{self.libraries_url}/{library['id']}", timeout=30)
        response.raise_for_status()
        return True

    def list_series_for_library(self, library_id: str) -> list[dict]:
        payload = {"condition": {"libraryId": {"value": library_id}}}
        response = self.session.post(
            f"{self.settings.url}/api/v1/series/list?unpaged=true",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("content", data if isinstance(data, list) else [])

    def find_series_for_book(self, book_title: str) -> dict | None:
        library = self.find_library_for_book(book_title)
        if not library:
            return None
        series_list = self.list_series_for_library(str(library["id"]))
        if not series_list:
            return None
        if len(series_list) == 1:
            return series_list[0]
        sanitized = self.sanitize_name(book_title).lower()
        for series in series_list:
            if str(series.get("name") or "").lower() == sanitized:
                return series
            metadata = series.get("metadata") or {}
            if str(metadata.get("title") or "").lower() == sanitized:
                return series
        return None

    def find_series_by_title(self, title: str) -> dict | None:
        """Search for a series across all Komga libraries by title (handles range libraries)."""
        sanitized = self.sanitize_name(title).lower()
        try:
            response = self.session.get(
                f"{self.settings.url}/api/v1/series",
                params={"search": title, "unpaged": "true"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", data if isinstance(data, list) else [])
            for series in content:
                name = str(series.get("name") or "").lower()
                meta = series.get("metadata") or {}
                meta_title = str(meta.get("title") or "").lower()
                if name == sanitized or meta_title == sanitized:
                    return series
            return None
        except Exception:
            return None

    def update_series_metadata(self, series_id: str, payload: dict) -> None:
        response = self.session.patch(
            f"{self.settings.url}/api/v1/series/{series_id}/metadata",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def mark_series_unread(self, series_id: str) -> None:
        response = self.session.delete(
            f"{self.settings.url}/api/v1/series/{series_id}/read-progress",
            timeout=30,
        )
        response.raise_for_status()

    def mark_book_read(self, book_id: str) -> None:
        response = self.session.patch(
            f"{self.settings.url}/api/v1/books/{book_id}/read-progress",
            json={"completed": True, "page": 0},
            timeout=30,
        )
        response.raise_for_status()

    def mark_books_read_through_chapter(self, books: list[dict], chapter_number: float) -> int:
        marked = 0
        for book in sorted(books, key=_book_number):
            book_id = book.get("id")
            if not book_id or _book_number(book) > chapter_number:
                continue
            self.mark_book_read(str(book_id))
            marked += 1
        return marked

    def mark_low_progress_series_unread(self, minimum_read_or_reading: int = 30) -> dict:
        libraries = self.list_libraries()
        series_checked = 0
        series_marked = 0
        errors: list[str] = []
        for library in libraries:
            library_id = str(library.get("id") or "")
            if not library_id:
                continue
            try:
                series_list = self.list_series_for_library(library_id)
            except Exception as exc:
                errors.append(f"library {library_id}: {exc}")
                continue
            for series in sorted(series_list, key=lambda item: str(item.get("id") or "")):
                series_id = str(series.get("id") or "")
                if not series_id:
                    continue
                series_checked += 1
                try:
                    books = self.list_books_for_series(series_id)
                    active_count = sum(1 for book in books if _has_read_progress(book))
                    if active_count < minimum_read_or_reading:
                        self.mark_series_unread(series_id)
                        series_marked += 1
                except Exception as exc:
                    errors.append(f"series {series_id}: {exc}")
        return {
            "libraries": len(libraries),
            "seriesChecked": series_checked,
            "seriesMarkedUnread": series_marked,
            "errors": errors,
        }

    def list_books_for_series(self, series_id: str) -> list[dict]:
        payload = {"condition": {"seriesId": {"value": series_id}}}
        try:
            response = self.session.post(
                f"{self.settings.url}/api/v1/books/list",
                params={"unpaged": "true"},
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("content", data if isinstance(data, list) else [])
        except Exception:
            response = self.session.get(
                f"{self.settings.url}/api/v1/series/{series_id}/books",
                params={"unpaged": "true"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("content", data if isinstance(data, list) else [])

    def quick_scan_all(self) -> int:
        libraries = self.list_libraries()
        for library in libraries:
            self.quick_scan_library(str(library["id"]))
        return len(libraries)

    def range_libs_scan_status(self, range_names: set[str], since_iso: str) -> tuple[int, int]:
        """Return (done, total) where done = range libraries whose lastScanned > since_iso."""
        try:
            libraries = self.list_libraries()
            relevant = [lib for lib in libraries if lib.get("name") in range_names]
            done = sum(
                1 for lib in relevant
                if (lib.get("lastScanned") or "") > since_iso
            )
            return done, len(relevant)
        except Exception:
            return 0, 0

    def import_all_books(self, library_root, scan: bool = True) -> dict:
        import time
        from pathlib import Path
        root = Path(library_root)
        if not root.exists():
            return {"scanned": 0, "created": 0, "errors": [f"Library root not found: {root}"]}
        folders = sorted(f for f in root.iterdir() if f.is_dir())
        created_count = 0
        scanned_count = 0
        errors: list[str] = []
        for folder in folders:
            try:
                library, created = self.ensure_library_for_book(folder.name)
                if created:
                    time.sleep(2)
                if scan:
                    self.quick_scan_library(str(library["id"]))
                if created:
                    created_count += 1
                scanned_count += 1
            except Exception as exc:
                errors.append(f"{folder.name}: {exc}")
        return {"scanned": scanned_count, "created": created_count, "errors": errors}

    def docker_root_for_book(self, book_title: str) -> str:
        return f"{self.settings.books_root_docker}/{sanitize_filename(book_title)}"

    def sanitize_name(self, value: str) -> str:
        return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode() or value


def _book_number(book: dict) -> float:
    metadata = book.get("metadata") or {}
    for value in (
        metadata.get("numberSort"),
        metadata.get("number"),
        book.get("number"),
        book.get("name"),
    ):
        key = chapter_key(str(value or ""))
        if key:
            return float(key)
    return 0.0


def _book_label(book: dict, chapter: str) -> str:
    metadata = book.get("metadata") or {}
    return str(metadata.get("title") or book.get("name") or f"Chapter {chapter}")


def komga_book_url(komga_public_url: str, book_id: str) -> str:
    return f"{komga_public_url.rstrip('/')}/book/{book_id}"


def _has_read_progress(book: dict) -> bool:
    progress = book.get("readProgress") or {}
    status = str(book.get("readStatus") or "").upper()
    return (
        status in {"READ", "IN_PROGRESS"}
        or bool(progress.get("completed"))
        or int(progress.get("page") or 0) > 0
    )


def latest_read_book(books: list[dict], komga_public_url: str, series_id: str) -> dict | None:
    read_books = [book for book in books if book.get("id") and _has_read_progress(book)]
    if not read_books:
        return None
    selected = max(read_books, key=_book_number)
    chapter_number = _book_number(selected)
    chapter = chapter_key(str(chapter_number))
    progress = selected.get("readProgress") or {}
    book_id = str(selected["id"])
    return {
        "book_id": book_id,
        "chapter_key": chapter,
        "label": _book_label(selected, chapter),
        "page": int(progress.get("page") or 0),
        "completed": bool(progress.get("completed")),
        "komga_url": komga_book_url(komga_public_url, book_id),
    }


def run_post_download_komga_action(
    conn: sqlite3.Connection,
    client: KomgaClient,
    manga: dict,
    existed_before_download: bool,
) -> None:
    if not client.enabled:
        return
    try:
        library, created = client.ensure_library_for_book(manga["title"])
        client.quick_scan_library(str(library["id"]))
        repository.update_komga_status(conn, int(manga["id"]), str(library["id"]), created, True, None)
        action = "quick-scanned existing library" if existed_before_download else "created/synced new library"
        repository.log(conn, "info", f"Komga {action} for {manga['title']} with deep=false")
    except Exception as exc:
        repository.update_komga_status(conn, int(manga["id"]), None, False, False, str(exc))
        repository.log(conn, "error", f"Komga post-download action failed for {manga['title']}: {exc}")
