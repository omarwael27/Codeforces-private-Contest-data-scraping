import os
import re
import shutil
import subprocess
import time
import random
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from typing import Optional

from utils.logger import logger
import config


def detect_chrome_major_version() -> Optional[int]:
    """Detect the installed Chrome/Chromium major version."""
    candidates = [
        os.getenv("CHROME_BINARY"),
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/opt/google/chrome/chrome",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if not path:
            continue

        try:
            output = subprocess.check_output(
                [path, "--version"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            match = re.search(r"(\d+)\.", output)
            if match:
                return int(match.group(1))
        except Exception:
            continue

    return None


class DriverManager:

    def __init__(self):
        self.driver: Optional[uc.Chrome] = None

    def _build_options(self) -> uc.ChromeOptions:
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        return options

    def _create_driver(self, version_main: Optional[int]) -> uc.Chrome:
        return uc.Chrome(
            options=self._build_options(),
            version_main=version_main,
            use_subprocess=True,
            user_data_dir=os.path.abspath(config.CHROME_PROFILE_DIR),
        )

    def _profile_in_use(self) -> bool:
        """Return True if a Chrome process is currently using our profile."""
        profile = os.path.abspath(config.CHROME_PROFILE_DIR)

        try:
            result = subprocess.run(
                ["pgrep", "-f", f"user-data-dir={profile}"],
                capture_output=True,
                text=True,
            )
        except Exception:
            return False

        for value in result.stdout.split():
            if value.isdigit() and int(value) not in (
                os.getpid(),
                os.getppid(),
            ):
                return True

        return False

    def _clean_profile_locks(self) -> None:
        """Remove stale Chrome Singleton lock files left by a crashed run."""
        if self._profile_in_use():
            return

        profile = os.path.abspath(config.CHROME_PROFILE_DIR)
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            path = os.path.join(profile, name)
            try:
                if os.path.islink(path) or os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass

    def _kill_profile_processes(self) -> None:
        """Kill stale Chrome processes that are using our profile directory."""
        profile = os.path.abspath(config.CHROME_PROFILE_DIR)

        try:
            result = subprocess.run(
                ["pgrep", "-f", f"user-data-dir={profile}"],
                capture_output=True,
                text=True,
            )
        except Exception:
            return

        for value in result.stdout.split():
            if not value.isdigit():
                continue

            pid = int(value)
            if pid in (os.getpid(), os.getppid()):
                continue

            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def init_driver(self) -> uc.Chrome:
        version_main = config.CHROME_VERSION or detect_chrome_major_version()
        if version_main:
            logger.info(f"Using ChromeDriver for Chrome {version_main}")
        else:
            logger.warning(
                "Could not detect Chrome version; letting ChromeDriver auto-detect"
            )

        self._clean_profile_locks()

        try:
            self.driver = self._create_driver(version_main or None)
        except Exception as e:
            logger.warning(
                f"Chrome failed to start ({e}). Cleaning stale profile processes "
                "and retrying..."
            )
            self._kill_profile_processes()
            time.sleep(2)
            self._clean_profile_locks()
            self.driver = self._create_driver(version_main or None)

        return self.driver

    def is_logged_in(self) -> bool:
        """Check whether the current browser session is logged in to Codeforces."""
        if not self.driver:
            return False

        page_source = self.driver.page_source.lower()
        return (
            'href="/logout"' in page_source
            or "href='/logout'" in page_source
            or ">logout<" in page_source
        )

    def is_cloudflare_challenge(self) -> bool:
        """Check whether the current page is a Cloudflare challenge page."""
        if not self.driver:
            return False

        page_source = self.driver.page_source.lower()
        return (
            "just a moment" in page_source
            or "verify you are human" in page_source
            or "cf-challenge" in page_source
            or "challenge-platform" in page_source
        )

    def click_unofficial_checkbox(self) -> bool:
        """
        Click the 'Show unofficial' checkbox on Codeforces standings page
        Uses human-like scrolling and timing to avoid detection
        """
        if not self.driver:
            raise RuntimeError("Driver not initialized")

        try:
            time.sleep(random.uniform(config.MIN_CLICK_DELAY, config.MAX_CLICK_DELAY))

            self.driver.execute_script("window.scrollTo(0, 200);")
            time.sleep(0.2)
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.2)

            checkbox = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.NAME, "showUnofficial"))
            )

            if not checkbox.is_selected():
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", checkbox
                )
                time.sleep(0.3)

                actions = ActionChains(self.driver)
                actions.move_to_element(checkbox).pause(0.1).click().perform()

                time.sleep(
                    random.uniform(config.MIN_CLICK_DELAY, config.MAX_CLICK_DELAY)
                )
                logger.info("✓ Clicked 'Show unofficial' checkbox")
                return True

            return True

        except TimeoutException:
            logger.warning(
                "'Show unofficial' checkbox not found; no unofficial participants"
            )
            return False

        except Exception as e:
            logger.error(f"Failed to click checkbox: {e}")
            raise

    def wait_for_cloudflare(self, timeout: Optional[float] = None) -> None:
        """Wait while a Cloudflare challenge is displayed."""
        if not self.driver:
            return

        wait_seconds = config.CLOUDFLARE_WAIT if timeout is None else timeout
        deadline = time.time() + wait_seconds
        warned = False

        while time.time() < deadline:
            if not self.is_cloudflare_challenge():
                return

            if not warned:
                logger.warning("⚠️  Cloudflare challenge detected, waiting...")
                warned = True

            time.sleep(1)

        if warned:
            logger.warning(
                "⚠️  Cloudflare challenge still present after waiting "
                f"{int(wait_seconds)}s"
            )

    def check_access_denied(self) -> bool:
        """
        Check if access was denied by Cloudflare

        Returns:
            True if access denied, False otherwise
        """
        if not self.driver:
            return False

        return "access denied" in self.driver.page_source.lower()

    def quit(self) -> None:
        """Close the driver safely"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error closing driver: {e}")

    def __enter__(self):
        """Context manager entry"""
        self.init_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.quit()
