from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from . import repository
from .asura import USER_AGENT
from .utils import sanitize_filename


def _download_images_parallel(
    image_urls: list[str],
    temp_dir: Path,
    chapter_url: str,
    max_workers: int = 5,
) -> list[Path]:
    """Download images in parallel using ThreadPoolExecutor."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Referer": chapter_url})

    def download_single_image(index: int, url: str) -> Path | None:
        try:
            extension_match = re.search(r"\.(\w+)(?:[?&].*)?$", url)
            extension = f".{extension_match.group(1).lower()}" if extension_match else ".jpg"
            image_path = temp_dir / f"{index:03d}{extension}"
            response = session.get(url, stream=True, timeout=60)
            response.raise_for_status()
            with image_path.open("wb") as file:
                for chunk in response.iter_content(8192):
                    if chunk:
                        file.write(chunk)
            return image_path
        except Exception as e:
            raise RuntimeError(f"Failed to download image {index}: {e}")

    image_paths = [None] * len(image_urls)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_single_image, index, url): index
            for index, url in enumerate(image_urls, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            image_paths[index - 1] = future.result()

    return [p for p in image_paths if p is not None]


def get_loaded_images(driver: webdriver.Chrome) -> list[str]:
    """Wait for images to load using a smart condition instead of polling."""
    try:
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-page] img")))
    except Exception:
        pass

    time.sleep(0.5)

    urls = []
    page_divs = driver.find_elements(By.CSS_SELECTOR, "div[data-page]")
    for div in page_divs:
        try:
            img = div.find_element(By.TAG_NAME, "img")
            src = img.get_attribute("src")
            if src and "asura-images" in src:
                urls.append(src)
        except Exception:
            continue

    return list(dict.fromkeys(urls))


def download_chapter(
    conn: sqlite3.Connection,
    library_root: Path,
    temp_root: Path,
    manga: dict,
    chapter: dict,
    extract_image_urls: Callable[[str], list[str]],
    image_download_workers: int = 4,
) -> str:
    manga_folder = library_root / sanitize_filename(manga["title"])
    manga_folder.mkdir(parents=True, exist_ok=True)
    chapter_label = chapter["chapter_key"]
    cbz_path = manga_folder / f"{sanitize_filename(manga['title'])} - Chapter {chapter_label}.cbz"

    if cbz_path.exists():
        repository.mark_downloaded(conn, chapter["id"], str(cbz_path))
        return str(cbz_path)

    temp_dir = temp_root / f"job-{chapter['id']}-{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        chapter_url = chapter["url"]
        if chapter_url.startswith("/"):
            chapter_url = urljoin(manga["url"], chapter_url)
        image_urls = extract_image_urls(chapter_url)
        if len(image_urls) < 3:
            raise RuntimeError(f"Too few page images found at {chapter_url}: {len(image_urls)}")
        if not all("asura-images" in url for url in image_urls):
            raise RuntimeError("Reader returned non-Asura page images")

        image_paths = _download_images_parallel(
            image_urls,
            temp_dir,
            chapter_url,
            max_workers=max(1, min(8, int(image_download_workers))),
        )

        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as archive:
            for image_path in image_paths:
                archive.write(image_path, image_path.name)

        repository.mark_downloaded(conn, chapter["id"], str(cbz_path))
        return str(cbz_path)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
