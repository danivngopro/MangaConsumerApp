from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    library_root: Path
    app_data_dir: Path
    asura_base_url: str
    download_concurrency: int
    request_delay_seconds: float
    auto_scan_every_days: int
    komga_url: str
    komga_username: str
    komga_password: str
    komga_books_root_docker: str


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_settings() -> Settings:
    return Settings(
        library_root=Path(
            os.getenv(
                "MANGA_LIBRARY_ROOT",
                r"\\192.168.1.139\Ext3TDrive3\komga\books",
            )
        ),
        app_data_dir=Path(os.getenv("APP_DATA_DIR", ".manga-recoverer")),
        asura_base_url=os.getenv("ASURA_BASE_URL", "https://asurascans.com").rstrip("/"),
        download_concurrency=max(1, _int_env("DOWNLOAD_CONCURRENCY", 1)),
        request_delay_seconds=max(0.0, _float_env("REQUEST_DELAY_SECONDS", 1.0)),
        auto_scan_every_days=max(0, _int_env("AUTO_SCAN_EVERY_DAYS", 0)),
        komga_url=os.getenv("KOMGA_URL", "http://localhost:25600").rstrip("/"),
        komga_username=os.getenv("KOMGA_USERNAME", ""),
        komga_password=os.getenv("KOMGA_PASSWORD", ""),
        komga_books_root_docker=os.getenv("KOMGA_BOOKS_ROOT_DOCKER", "/books").rstrip("/"),
    )
