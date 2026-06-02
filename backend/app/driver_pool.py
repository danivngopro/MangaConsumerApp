from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from shutil import which
from webdriver_manager.chrome import ChromeDriverManager

from .asura import USER_AGENT

logger = logging.getLogger(__name__)


class DriverPool:
    """Thread-safe pool of reusable Selenium Chrome drivers."""

    def __init__(self, pool_size: int = 3) -> None:
        self.pool_size = max(1, min(pool_size, 6))
        self.drivers: queue.Queue[webdriver.Chrome] = queue.Queue(maxsize=self.pool_size)
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Initialize all drivers in the pool."""
        for _ in range(self.pool_size):
            driver = self._create_driver()
            self.drivers.put(driver)

    def stop(self) -> None:
        """Quit all drivers and clear the pool."""
        self._stop.set()
        while not self.drivers.empty():
            try:
                driver = self.drivers.get_nowait()
                driver.quit()
            except queue.Empty:
                break

    def acquire(self, timeout: float = 30.0) -> webdriver.Chrome | None:
        """Get a driver from the pool. Blocks until one is available."""
        try:
            driver = self.drivers.get(timeout=timeout)
            if driver and not self._is_driver_alive(driver):
                driver.quit()
                driver = self._create_driver()
            return driver
        except queue.Empty:
            logger.warning(f"Timeout waiting for available driver (timeout={timeout}s)")
            return None

    def release(self, driver: webdriver.Chrome) -> None:
        """Return a driver to the pool."""
        if driver and self._is_driver_alive(driver):
            self.drivers.put(driver)
        else:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if not self._stop.is_set():
                try:
                    driver = self._create_driver()
                    self.drivers.put(driver)
                except Exception as e:
                    logger.error(f"Failed to create replacement driver: {e}")

    @staticmethod
    def _is_driver_alive(driver: webdriver.Chrome) -> bool:
        """Check if a driver is still responsive."""
        try:
            driver.current_url
            return True
        except Exception:
            return False

    @staticmethod
    def _create_driver() -> webdriver.Chrome:
        """Create a new Chrome driver instance."""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1400,2200")
        options.add_argument(f"--user-agent={USER_AGENT}")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-sync")
        options.add_argument("--no-first-run")
        options.add_argument("--mute-audio")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        chromium_binary = which("chromium") or which("chromium-browser") or which("google-chrome")
        if chromium_binary:
            options.binary_location = chromium_binary
        chromedriver_binary = which("chromedriver")
        service = Service(chromedriver_binary or ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(90)
        return driver

    def set_pool_size(self, new_size: int) -> None:
        """Adjust pool size dynamically."""
        new_size = max(1, min(new_size, 6))
        with self._lock:
            old_size = self.pool_size
            if new_size > old_size:
                for _ in range(new_size - old_size):
                    driver = self._create_driver()
                    self.drivers.put(driver)
            elif new_size < old_size:
                excess = old_size - new_size
                for _ in range(excess):
                    try:
                        driver = self.drivers.get_nowait()
                        driver.quit()
                    except queue.Empty:
                        break
            self.pool_size = new_size
