from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from shutil import which

from selenium.webdriver.support.ui import WebDriverWait

from .asura import USER_AGENT
from .downloader import get_loaded_images
from .driver_pool import DriverPool

logger = logging.getLogger(__name__)


class PlaywrightUnavailableError(RuntimeError):
    pass


class PlaywrightReaderPool:
    def __init__(self, browser_concurrency: int) -> None:
        self.browser_concurrency = max(1, min(4, int(browser_concurrency)))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._playwright = None
        self._browser = None
        self._semaphore: asyncio.Semaphore | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._started.clear()
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run_loop, name="playwright-reader", daemon=True)
        self._thread.start()
        self._started.wait(timeout=30)
        if not self._loop or self._stopped.is_set():
            raise PlaywrightUnavailableError("Playwright reader loop failed to start")

    def stop(self) -> None:
        if not self._loop:
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            logger.warning("Playwright shutdown failed: %s", exc)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        self._loop = None
        self._thread = None

    def extract(self, chapter_url: str) -> list[str]:
        if not self._loop:
            raise PlaywrightUnavailableError("Playwright reader pool is not running")
        future: Future[list[str]] = asyncio.run_coroutine_threadsafe(
            self._extract(chapter_url),
            self._loop,
        )
        return future.result(timeout=120)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._startup())
            self._started.set()
            self._loop.run_forever()
        except Exception as exc:
            logger.error("Playwright reader startup failed: %s", exc)
            self._stopped.set()
            self._started.set()
        finally:
            try:
                self._loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            self._loop.close()

    async def _startup(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise PlaywrightUnavailableError("Playwright is not installed") from exc
        self._playwright = await async_playwright().start()
        chromium_binary = which("chromium") or which("chromium-browser") or which("google-chrome")
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            executable_path=chromium_binary,
            args=[
                "--no-sandbox",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )
        self._semaphore = asyncio.Semaphore(self.browser_concurrency)

    async def _shutdown(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _extract(self, chapter_url: str) -> list[str]:
        if not self._browser or not self._semaphore:
            raise PlaywrightUnavailableError("Playwright reader pool is not initialized")
        async with self._semaphore:
            context = await self._browser.new_context(
                viewport={"width": 1400, "height": 2200},
                user_agent=USER_AGENT,
            )
            page = await context.new_page()
            try:
                await page.goto(chapter_url, wait_until="domcontentloaded", timeout=90_000)
                try:
                    await page.wait_for_selector("div[data-page] img", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)
                urls = await page.eval_on_selector_all(
                    "div[data-page] img",
                    """(images) => images
                        .map((img) => img.getAttribute("src") || "")
                        .filter((src) => src.includes("asura-images"))""",
                )
                return list(dict.fromkeys(urls))
            finally:
                await context.close()


class ReaderExtractionPool:
    def __init__(self, browser_concurrency: int = 2, reader_engine: str = "playwright") -> None:
        self.browser_concurrency = max(1, min(4, int(browser_concurrency)))
        self.reader_engine = reader_engine if reader_engine in {"playwright", "selenium"} else "playwright"
        self._playwright_pool: PlaywrightReaderPool | None = None
        self._selenium_pool = DriverPool(pool_size=self.browser_concurrency)
        self._selenium_started = False
        self._selenium_lock = threading.Lock()

    def start(self) -> None:
        if self.reader_engine == "playwright":
            try:
                self._playwright_pool = PlaywrightReaderPool(self.browser_concurrency)
                self._playwright_pool.start()
            except Exception as exc:
                self._playwright_pool = None
                logger.warning("Playwright reader unavailable; Selenium fallback will be used: %s", exc)
        else:
            self._ensure_selenium_started()

    def stop(self) -> None:
        if self._playwright_pool:
            self._playwright_pool.stop()
            self._playwright_pool = None
        if self._selenium_started:
            self._selenium_pool.stop()
            self._selenium_started = False

    def set_options(self, browser_concurrency: int, reader_engine: str) -> None:
        browser_concurrency = max(1, min(4, int(browser_concurrency)))
        reader_engine = reader_engine if reader_engine in {"playwright", "selenium"} else "playwright"
        if browser_concurrency == self.browser_concurrency and reader_engine == self.reader_engine:
            return
        self.stop()
        self.browser_concurrency = browser_concurrency
        self.reader_engine = reader_engine
        self._selenium_pool = DriverPool(pool_size=self.browser_concurrency)
        self._selenium_started = False
        self._selenium_lock = threading.Lock()
        self.start()

    def extract(self, chapter_url: str) -> list[str]:
        if self.reader_engine == "playwright" and self._playwright_pool:
            try:
                return self._playwright_pool.extract(chapter_url)
            except Exception as exc:
                logger.warning("Playwright reader failed for %s; falling back to Selenium: %s", chapter_url, exc)
        return self._extract_with_selenium(chapter_url)

    def _extract_with_selenium(self, chapter_url: str) -> list[str]:
        self._ensure_selenium_started()
        driver = self._selenium_pool.acquire(timeout=30)
        if driver is None:
            raise RuntimeError("Timeout waiting for available Selenium reader")
        try:
            driver.get(chapter_url)
            WebDriverWait(driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return get_loaded_images(driver)
        finally:
            self._selenium_pool.release(driver)

    def _ensure_selenium_started(self) -> None:
        with self._selenium_lock:
            if not self._selenium_started:
                self._selenium_pool.start()
                self._selenium_started = True

    def debug_state(self) -> dict:
        return {
            "browserConcurrency": self.browser_concurrency,
            "readerEngine": self.reader_engine,
            "playwrightActive": self._playwright_pool is not None,
            "seleniumActive": self._selenium_started,
        }
