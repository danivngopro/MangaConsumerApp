from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from . import repository
from .downloader import download_chapter
from .komga import KomgaClient, run_post_download_komga_action


class DownloadQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        library_root: Path,
        temp_root: Path,
        komga_client: KomgaClient,
        concurrency: int = 1,
    ) -> None:
        self.conn = conn
        self.library_root = library_root
        self.temp_root = temp_root
        self.komga_client = komga_client
        self._concurrency = max(1, concurrency)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._worker_jobs: dict[int, dict] = {}

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._ensure_worker_count()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads = []

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def set_concurrency(self, value: int) -> None:
        self._concurrency = max(1, min(6, int(value)))
        self._ensure_worker_count()

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
                existed_before_download = bool(manga.get("local_folder"))
                file_path = download_chapter(self.conn, self.library_root, self.temp_root, manga, chapter)
                repository.set_job_status(self.conn, job["id"], "done")
                repository.log(self.conn, "info", f"Downloaded {manga['title']} {chapter['label']} to {file_path}")
                repository.maybe_resume_auto_paused(self.conn)
                if not repository.has_pending_download_jobs_for_manga(self.conn, int(manga["id"])):
                    run_post_download_komga_action(
                        self.conn,
                        self.komga_client,
                        manga,
                        existed_before_download,
                    )
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
            "workers": threads,
        }
