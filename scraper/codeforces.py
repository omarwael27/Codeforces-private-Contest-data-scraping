import time
import random
import re
import pandas as pd
from typing import List, Dict, Set, Tuple, Optional
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from scraper.driver import DriverManager
from utils.logger import logger
import config


class CodeforcesScraperError(Exception):
    """Custom exception for scraper errors"""

    pass


def clean_handle(raw_handle: str) -> Tuple[str, bool]:
    """
    Normalize a handle cell and detect unofficial/practice participants.

    Codeforces renders practice-mode rows as "handle  →to practice" and
    out-of-competition rows with a "*". Both should map to the bare handle,
    with the row flagged as unofficial.

    Returns:
        (clean_handle, is_unofficial)
    """
    raw = (raw_handle or "").strip()
    lowered = raw.lower()
    is_unofficial = "*" in raw or "→" in raw or "to practice" in lowered

    cleaned = raw.replace("*", "").strip()
    cleaned = re.split(r"[\s→]+", cleaned)[0] if cleaned else ""
    return cleaned, is_unofficial


class CodeforcesScraper:

    def __init__(self):
        self.participants: Dict[str, Set[str]] = {}
        self.unofficial: Set[str] = set()

    def extract_page_data(self, driver: DriverManager) -> List[Dict[str, any]]:
        """
        Extract participant data from current standings page

        Args:
            driver: DriverManager instance

        Returns:
            List of dictionaries containing handle and solved problems
        """
        try:
            WebDriverWait(driver.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.standings"))
            )
            time.sleep(0.5)

            rows = driver.driver.find_elements(
                By.CSS_SELECTOR, "table.standings tbody tr"
            )
            data = []

            for row in rows:
                try:
                    row_class = row.get_attribute("class") or ""
                    if "header" in row_class:
                        continue

                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 5:
                        continue

                    handle, is_unofficial = clean_handle(cells[1].text)
                    if not handle:
                        continue

                    solved = []
                    for i in range(4, len(cells)):
                        cell = cells[i]
                        cell_class = cell.get_attribute("class") or ""

                        if "accepted" in cell_class.lower() or "+" in cell.text:
                            problem_letter = chr(65 + i - 4)
                            solved.append(problem_letter)

                    data.append(
                        {
                            "Handle": handle,
                            "Solved": solved,
                            "Unofficial": is_unofficial,
                        }
                    )

                except Exception as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue

            return data

        except Exception as e:
            logger.error(f"Failed to extract page data: {e}")
            raise CodeforcesScraperError(f"Data extraction failed: {e}")

    def scrape_page(
        self, url: str, page_num: int, driver: DriverManager
    ) -> Optional[List[Dict[str, any]]]:
        """
        Scrape a single page of contest standings

        Args:
            url: Contest standings URL
            page_num: Page number to scrape
            driver: Shared DriverManager instance

        Returns:
            List of participant data or None if failed
        """
        try:
            page_url = url if page_num == 1 else f"{url}/page/{page_num}"

            logger.info(f"[PAGE {page_num}] Loading...")
            driver.driver.get(page_url)

            time.sleep(random.uniform(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY))

            driver.wait_for_cloudflare()

            page_source = driver.driver.page_source.lower()
            if "standings are not available" in page_source:
                if not driver.is_logged_in():
                    raise CodeforcesScraperError(
                        "Codeforces says 'Standings are not available' because "
                        "the scraper is not logged in. Run `python login.py` "
                        "once, then run `python main.py` again."
                    )
                raise CodeforcesScraperError(
                    "Codeforces says 'Standings are not available'. Check that "
                    "the contest link is correct and your account can view it."
                )

            if "/enter" in driver.driver.current_url:
                raise CodeforcesScraperError(
                    "Codeforces login required. Run `python login.py` once, "
                    "then run `python main.py` again."
                )

            if config.INCLUDE_UNOFFICIAL:
                driver.click_unofficial_checkbox()
            else:
                logger.info(
                    "Skipping unofficial participants (INCLUDE_UNOFFICIAL=False)"
                )

            if driver.check_access_denied():
                raise CodeforcesScraperError("Access denied by Cloudflare")

            page_data = self.extract_page_data(driver)
            logger.info(
                f"[PAGE {page_num}] Extracted {len(page_data)} participants"
            )

            return page_data

        except CodeforcesScraperError:
            raise

        except Exception as e:
            logger.error(f"[PAGE {page_num}] Error: {e}")
            return None

    def scrape_contest(
        self,
        contest_name: str,
        contest_url: str,
        driver: DriverManager,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Scrape entire contest standings (all pages)

        Args:
            contest_name: Name of the contest
            contest_url: Contest standings URL
            driver: Shared DriverManager instance

        Returns:
            Tuple of (DataFrame with results, CSV filename)
        """
        logger.info("=" * 60)
        logger.info(f"SCRAPING: {contest_name}")
        logger.info("=" * 60)

        self.participants = {}
        self.unofficial = set()
        page = 1

        while page <= config.MAX_PAGES:
            page_data = self.scrape_page(contest_url, page, driver)

            if not page_data:
                break

            # Update participants dictionary and track if any new data was found
            new_count = 0
            any_new_data = False

            for entry in page_data:
                handle = entry["Handle"]
                solved = set(entry["Solved"])

                if entry.get("Unofficial"):
                    self.unofficial.add(handle)

                if handle in self.participants:
                    old_solved = self.participants[handle]
                    new_solved = old_solved.union(solved)

                    # Check if there are any new problems solved
                    if len(new_solved) > len(old_solved):
                        self.participants[handle] = new_solved
                        any_new_data = True
                    else:
                        self.participants[handle] = new_solved
                else:
                    self.participants[handle] = solved
                    new_count += 1
                    any_new_data = True

            logger.info(f"[INFO] New: {new_count} | Total: {len(self.participants)}")

            # Stop if no new data (no new handles AND no additional problems solved)
            if not any_new_data:
                logger.info("[INFO] No new data found. Stopping scrape.")
                break

            time.sleep(random.uniform(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY))
            page += 1

        if not self.participants:
            raise CodeforcesScraperError(
                f"No standings data found for {contest_name}. "
                "Make sure you are logged in (run `python login.py` once) and "
                "that the contest link is correct."
            )

        df = pd.DataFrame(
            [
                {
                    "Handle": handle,
                    "Solved_Problems": ",".join(sorted(problems)),
                    "Total_Solved": len(problems),
                    "Unofficial": handle in self.unofficial,
                }
                for handle, problems in self.participants.items()
            ]
        )

        df = df.sort_values("Total_Solved", ascending=False).reset_index(drop=True)

        csv_file = f"{contest_name}_standings.csv"
        df.to_csv(csv_file, index=False, encoding="utf-8-sig")

        logger.info(
            f"\n✅ Scraped {len(df)} participants "
            f"({len(self.unofficial)} unofficial/practice)"
        )
        logger.info(f"✅ Saved to: {csv_file}\n")

        return df, csv_file

    @staticmethod
    def scrape_all_contests() -> Dict[str, Tuple[pd.DataFrame, str]]:
        """
        Scrape all configured contests

        Returns:
            Dictionary mapping contest_name -> (DataFrame, CSV filename)
        """
        logger.info("\n" + "=" * 60)
        logger.info("STEP 1: SCRAPING ALL CONTESTS")
        logger.info("=" * 60)

        results = {}
        scraper = CodeforcesScraper()

        with DriverManager() as driver:
            for contest_name, contest_url, _weight in config.CONTESTS:
                df, csv_file = scraper.scrape_contest(
                    contest_name, contest_url, driver
                )
                results[contest_name] = (df, csv_file)

        return results
