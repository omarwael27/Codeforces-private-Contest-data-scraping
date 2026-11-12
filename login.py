import config
from scraper.driver import DriverManager
from utils.logger import logger


HOME_URL = "https://codeforces.com/"
LOGIN_URL = "https://codeforces.com/enter"


def access_check_url() -> str:
    """Use the first contest page to verify login and group access."""
    if config.CONTESTS:
        return config.CONTESTS[0][1]
    return HOME_URL


def has_access(driver: DriverManager) -> bool:
    """Return True when logged in and standings are visible."""
    if not driver.is_logged_in():
        return False

    page_source = driver.driver.page_source.lower()
    return "standings are not available" not in page_source


def main():
    logger.info("=" * 60)
    logger.info("CODEFORCES LOGIN")
    logger.info("=" * 60)

    with DriverManager() as driver:
        url = access_check_url()

        logger.info("Checking existing Codeforces session...")
        driver.driver.get(url)
        driver.wait_for_cloudflare(timeout=120)

        if has_access(driver):
            logger.info("✅ Already logged in with access to the standings.")
            logger.info("You can now run: python main.py\n")
            return

        logger.info("Opening the login page...")
        driver.driver.get(LOGIN_URL)
        driver.wait_for_cloudflare(timeout=120)

        logger.info(
            "Log in in the browser window. If Cloudflare shows a challenge, "
            "solve it there too."
        )
        logger.info(
            "After you are logged in, come back to this terminal and press Enter."
        )

        try:
            input()
        except EOFError:
            logger.error("No terminal input available.")
            raise SystemExit(1)

        logger.info("Checking access...")
        driver.driver.get(url)
        driver.wait_for_cloudflare(timeout=60)

        if has_access(driver):
            logger.info("✅ Login confirmed. Session saved to the Chrome profile.")
        else:
            logger.warning(
                "⚠️  Still cannot access the standings. Make sure this account "
                "is a member/manager of the group, then run login.py again."
            )

        logger.info("You can now run: python main.py\n")


if __name__ == "__main__":
    main()
