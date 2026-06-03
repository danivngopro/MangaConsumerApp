from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass

import requests

from . import repository
from .utils import sanitize_filename


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

    def quick_scan_book(self, book_title: str) -> dict:
        library, _created = self.ensure_library_for_book(book_title)
        self.quick_scan_library(str(library["id"]))
        return library

    def import_book(self, book_title: str) -> dict:
        library, _created = self.ensure_library_for_book(book_title)
        return library

    def quick_scan_all(self) -> int:
        libraries = self.list_libraries()
        for library in libraries:
            self.quick_scan_library(str(library["id"]))
        return len(libraries)

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
