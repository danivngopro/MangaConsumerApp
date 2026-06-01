import os
import zipfile
import argparse
import re
import shutil
import time
import concurrent.futures

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

import requests


# =============================
# Setup Driver
# =============================
def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1400,2200')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


# =============================
# Load only REAL manga images
# =============================
def get_loaded_images(driver):
    last_count = 0
    stable_rounds = 0

    for _ in range(60):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        # 🔥 ONLY manga pages
        page_divs = driver.find_elements(By.CSS_SELECTOR, "div[data-page]")

        urls = []

        for div in page_divs:
            try:
                img = div.find_element(By.TAG_NAME, "img")
                src = img.get_attribute("src")

                if src and "asura-images" in src:
                    urls.append(src)
            except:
                continue

        urls = list(dict.fromkeys(urls))

        print(f"[DEBUG] Chapter pages loaded: {len(urls)}")

        if len(urls) == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = len(urls)

        if stable_rounds >= 3:
            return urls

    return urls


# =============================
# Download Chapter
# =============================
def download_single_chapter(driver, chapter_number, base_url_prefix, book_id, download_dir):
    chapter_url = f"{base_url_prefix}{chapter_number}"
    chapter_folder = os.path.join(download_dir, f"Chapter_{chapter_number}")

    os.makedirs(chapter_folder, exist_ok=True)

    print(f"\n[Chapter {chapter_number}] Starting...")

    try:
        driver.get(chapter_url)

        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        image_urls = get_loaded_images(driver)

        # 🔒 Strict validation
        if len(image_urls) < 5:
            print(f"[Chapter {chapter_number}] ❌ Too few images → FAIL")
            return False

        if not all("asura-images" in url for url in image_urls):
            print(f"[Chapter {chapter_number}] ❌ Non-manga images detected → FAIL")
            return False

        print(f"[Chapter {chapter_number}] Found {len(image_urls)} pages")

        image_paths = []

        for i, url in enumerate(image_urls):
            ext_match = re.search(r'\.(\w+)(?:[?&].*)?$', url)
            ext = f".{ext_match.group(1).lower()}" if ext_match else ".jpg"

            filename = f"{i+1:03d}{ext}"
            filepath = os.path.join(chapter_folder, filename)

            print(f"[Chapter {chapter_number}] Downloading {i+1}/{len(image_urls)}")

            r = requests.get(url, stream=True)
            r.raise_for_status()

            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            image_paths.append(filepath)

        # Create CBZ
        cbz_path = os.path.join(download_dir, f"{book_id}_Chapter_{chapter_number:03d}.cbz")

        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path in image_paths:
                zf.write(path, os.path.basename(path))

        print(f"[Chapter {chapter_number}] ✅ Success")
        return True

    except Exception as e:
        print(f"[Chapter {chapter_number}] ❌ ERROR: {e}")
        return False

    finally:
        if os.path.exists(chapter_folder):
            shutil.rmtree(chapter_folder)


# =============================
# Retry logic
# =============================
def download_with_retry(driver, chapter, base_url_prefix, book_id, download_dir):
    for attempt in range(1, 4):
        print(f"[Chapter {chapter}] Attempt {attempt}/3")

        success = download_single_chapter(
            driver, chapter, base_url_prefix, book_id, download_dir
        )

        if success:
            return True

        time.sleep(2)

    return False


# =============================
# Threaded execution
# =============================
def download_threaded(base_url_prefix, book_id, start_chapter, end_chapter, num_threads):
    base_output_dir = "books"
    download_dir = os.path.join(base_output_dir, book_id)
    os.makedirs(download_dir, exist_ok=True)

    chapters = list(range(start_chapter, end_chapter + 1))
    chunks = [chapters[i::num_threads] for i in range(num_threads)]

    print(f"\nStarting download with {num_threads} threads")

    start_time = time.time()

    def worker(chunk):
        driver = setup_driver()
        results = []

        try:
            for ch in chunk:
                result = download_with_retry(
                    driver, ch, base_url_prefix, book_id, download_dir
                )
                results.append((ch, result))
        finally:
            driver.quit()

        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, chunk) for chunk in chunks if chunk]

        all_results = []
        for f in concurrent.futures.as_completed(futures):
            all_results.extend(f.result())

    success = sum(1 for _, r in all_results if r)
    total = len(all_results)

    print("\n--- DONE ---")
    print(f"Success: {success}/{total}")
    print(f"Time: {time.time() - start_time:.2f}s")


# =============================
# CLI
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("base_url_prefix")
    parser.add_argument("book_id")
    parser.add_argument("start_chapter", type=int)
    parser.add_argument("end_chapter", type=int)
    parser.add_argument("-t", "--num_threads", type=int, default=2)

    args = parser.parse_args()

    if not args.base_url_prefix.endswith("/"):
        args.base_url_prefix += "/"

    download_threaded(
        args.base_url_prefix,
        args.book_id,
        args.start_chapter,
        args.end_chapter,
        args.num_threads
    )