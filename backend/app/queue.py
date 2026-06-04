from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from . import repository
from .downloader import download_chapter
from .komga import KomgaClient
from .reader_extractor import ReaderExtractionPool


class DownloadQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        library_root: Path,
        temp_root: Path,
        komga_client: KomgaClient,
        concurrency: int = 1,
        browser_concurrency: int = 2,
        image_download_workers: int = 4,
        reader_engine: str = "playwright",
        komga_post_download_delay_seconds: int = 3600,
    ) -> None:
        self.conn = conn
        self.library_root = library_root
        self.temp_root = temp_root
        self.komga_client = komga_client
        self._concurrency = max(1, concurrency)
        self._browser_concurrency = max(1, min(4, int(browser_concurrency)))
        self._image_download_workers = max(1, min(8, int(image_download_workers)))
        self._reader_engine = reader_engine if reader_engine in {"playwright", "selenium"} else "playwright"
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._worker_jobs: dict[int, dict] = {}
        self._reader_pool = ReaderExtractionPool(self._browser_concurrency, self._reader_engine)
        self._komga_post_download_delay_seconds = max(0, int(komga_post_download_delay_seconds))
        self._komga_batch_lock = threading.Lock()
        self._komga_batch_thread: threading.Thread | None = None

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._reader_pool.start()
        self._ensure_worker_count()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads = []
        self._reader_pool.stop()

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def set_concurrency(self, value: int) -> None:
        self._concurrency = max(1, min(6, int(value)))
        self._ensure_worker_count()

    @property
    def browser_concurrency(self) -> int:
        return self._browser_concurrency

    @property
    def image_download_workers(self) -> int:
        return self._image_download_workers

    @property
    def reader_engine(self) -> str:
        return self._reader_engine

    def set_reader_options(
        self,
        browser_concurrency: int,
        image_download_workers: int,
        reader_engine: str,
    ) -> None:
        self._browser_concurrency = max(1, min(4, int(browser_concurrency)))
        self._image_download_workers = max(1, min(8, int(image_download_workers)))
        self._reader_engine = reader_engine if reader_engine in {"playwright", "selenium"} else "playwright"
        self._reader_pool.set_options(self._browser_concurrency, self._reader_engine)

    def retire_worker(self, ident: int) -> dict:
        with self._threads_lock:
            target_index = next(
                (
                    index
                    for index, thread in enumerate(self._threads)
                    if thread.ident == ident and thread.is_alive()
                ),
                None,
            )
            if target_index is None:
                return {"stopped": False, "reason": "worker not found"}
            self._concurrency = max(0, min(self._concurrency, len(self._threads)) - 1)
            if target_index < self._concurrency and self._threads:
                self._threads.append(self._threads.pop(target_index))
            return {
                "stopped": True,
                "reason": "worker will exit after current chapter or idle loop",
                "concurrency": self._concurrency,
            }

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._current_worker_should_exit():
                break
            if self._paused.is_set():
                time.sleep(1)
                continue

            job = repository.claim_next_download_job(self.conn)
            if not job:
                time.sleep(2)
                continue
            self._worker_jobs[threading.get_ident()] = {
                "jobId": job["id"],
                "status": "claimed",
                "startedAt": time.time(),
            }

            try:
                manga, chapter = repository.get_download_target(self.conn, job["id"])
                self._worker_jobs[threading.get_ident()] = {
                    "jobId": job["id"],
                    "status": "downloading",
                    "manga": manga["title"],
                    "chapter": chapter["label"],
                    "startedAt": time.time(),
                }
                repository.log(self.conn, "info", f"[{threading.current_thread().name}] Starting download: {manga['title']} — {chapter['label']}")
                file_path = download_chapter(
                    self.conn,
                    self.library_root,
                    self.temp_root,
                    manga,
                    chapter,
                    extract_image_urls=self._reader_pool.extract,
                    image_download_workers=self._image_download_workers,
                )
                repository.set_job_status(self.conn, job["id"], "done")
                repository.log(self.conn, "info", f"[{threading.current_thread().name}] Done: {manga['title']} — {chapter['label']} → {file_path}")
                repository.maybe_resume_auto_paused(self.conn)
                repository.maybe_enqueue_next_pending_chapter(self.conn)
                komga_auto_enabled = repository.get_setting(self.conn, "komga_auto_enabled", "0") == "1"
                if komga_auto_enabled:
                    self.schedule_post_queue_komga_batch_if_drained()
            except Exception as exc:
                attempts = int(job["attempts"])
                if attempts < 3:
                    repository.set_job_status(self.conn, job["id"], "queued", str(exc))
                else:
                    repository.set_job_status(self.conn, job["id"], "failed", str(exc))
                    repository.log(self.conn, "error", f"Download failed for job {job['id']}: {exc}")
                    repository.maybe_resume_auto_paused(self.conn)
            finally:
                self._worker_jobs.pop(threading.get_ident(), None)

    def schedule_post_queue_komga_batch_if_drained(self) -> bool:
        if not self.komga_client.enabled:
            return False
        if repository.unresolved_download_job_count(self.conn) > 0:
            return False
        with self._komga_batch_lock:
            if self._komga_batch_thread and self._komga_batch_thread.is_alive():
                return False
            self._komga_batch_thread = threading.Thread(
                target=self.run_post_queue_komga_batch,
                name="komga-post-queue-batch",
                daemon=True,
            )
            self._komga_batch_thread.start()
            return True

    def run_post_queue_komga_batch(self) -> None:
        if not self.komga_client.enabled:
            return
        try:
            result = self.komga_client.import_all_books(self.library_root, scan=False)
            repository.log(
                self.conn,
                "info",
                f"Auto Komga import after queue drain: {result['created']} created, {result['scanned']} folders checked",
            )
            if self._komga_post_download_delay_seconds > 0:
                repository.log(
                    self.conn,
                    "info",
                    f"Waiting {self._komga_post_download_delay_seconds // 60} minutes before Komga quick scan all",
                )
                time.sleep(self._komga_post_download_delay_seconds)
            count = self.komga_client.quick_scan_all()
            repository.log(self.conn, "info", f"Auto Komga quick scan all complete with deep=false: {count}")

            reorganize_enabled = repository.get_setting(self.conn, "reorganize_on_drain", "0") == "1"
            if reorganize_enabled:
                from .library_organizer import reorganize_library
                reorg = reorganize_library(self.conn, self.library_root, self.komga_client)
                repository.log(
                    self.conn,
                    "info",
                    f"Auto reorganize by chapters: {reorg['moved']} moved, {reorg['skipped']} skipped",
                )
        except Exception as exc:
            repository.log(self.conn, "error", f"Auto Komga post-queue batch failed: {exc}")

    def _ensure_worker_count(self) -> None:
        with self._threads_lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            while len(self._threads) < self._concurrency:
                worker_number = len(self._threads) + 1
                thread = threading.Thread(target=self._run, name=f"download-queue-{worker_number}", daemon=True)
                self._threads.append(thread)
                thread.start()

    def _current_worker_should_exit(self) -> bool:
        current = threading.current_thread()
        with self._threads_lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            try:
                index = self._threads.index(current)
            except ValueError:
                return False
            return index >= self._concurrency

    def debug_state(self) -> dict:
        with self._threads_lock:
            threads = [
                {
                    "name": thread.name,
                    "ident": thread.ident,
                    "alive": thread.is_alive(),
                    "job": self._worker_jobs.get(thread.ident or -1),
                }
                for thread in self._threads
            ]
        return {
            "paused": self.paused,
            "concurrency": self.concurrency,
            "reader": self._reader_pool.debug_state(),
            "imageDownloadWorkers": self._image_download_workers,
            "workers": threads,
        }
