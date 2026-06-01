from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from . import repository
from .asura import USER_AGENT
from .utils import sanitize_filename


def setup_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,2200")
    options.add_argument(f"--user-agent={USER_AGENT}")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(90)
    return driver


def get_loaded_images(driver: webdriver.Chrome) -> list[str]:
    last_count = 0
    stable_rounds = 0

    for _ in range(60):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
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

        urls = list(dict.fromkeys(urls))
        if len(urls) == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = len(urls)
        if stable_rounds >= 3:
            return urls

    return list(dict.fromkeys(urls))


def download_chapter(
    conn: sqlite3.Connection,
    library_root: Path,
    temp_root: Path,
    manga: dict,
    chapter: dict,
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
    driver = setup_driver()

    try:
        chapter_url = chapter["url"]
        if chapter_url.startswith("/"):
            chapter_url = urljoin(manga["url"], chapter_url)
        driver.get(chapter_url)
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        image_urls = get_loaded_images(driver)
        if len(image_urls) < 3:
            raise RuntimeError(f"Too few page images found at {chapter_url}: {len(image_urls)}")
        if not all("asura-images" in url for url in image_urls):
            raise RuntimeError("Reader returned non-Asura page images")

        image_paths = []
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Referer": chapter_url})
        for index, url in enumerate(image_urls, start=1):
            extension_match = re.search(r"\.(\w+)(?:[?&].*)?$", url)
            extension = f".{extension_match.group(1).lower()}" if extension_match else ".jpg"
            image_path = temp_dir / f"{index:03d}{extension}"
            response = session.get(url, stream=True, timeout=60)
            response.raise_for_status()
            with image_path.open("wb") as file:
                for chunk in response.iter_content(8192):
                    if chunk:
                        file.write(chunk)
            image_paths.append(image_path)

        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for image_path in image_paths:
                archive.write(image_path, image_path.name)

        repository.mark_downloaded(conn, chapter["id"], str(cbz_path))
        return str(cbz_path)
    finally:
        driver.quit()
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
