import os
import re
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def parse_spreadsheet_id(value: str) -> str:
    """Extract the spreadsheet ID from a Google Sheets link or ID."""
    if not value:
        return ""

    value = value.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    if match:
        return match.group(1)

    return value


# Google Sheets Configuration
# Accepts either a full link or a bare spreadsheet ID.
SHEET_LINK: str = os.getenv("GOOGLE_SHEET_LINK", "").strip()
SPREADSHEET_ID: str = parse_spreadsheet_id(
    SHEET_LINK or os.getenv("SPREADSHEET_ID", "")
)
SHEET_NAMES: List[str] = [
    name.strip() for name in os.getenv("SHEET_NAMES", "").split(",") if name.strip()
]

# Google Auth Files
TOKEN_FILE: str = os.getenv("TOKEN_FILE", "token.pickle")
CREDENTIALS_FILE: str = os.getenv("CREDENTIALS_FILE", "credentials.json")
SCOPES: List[str] = ["https://www.googleapis.com/auth/spreadsheets"]

# Performance Thresholds
# Fallback threshold used for any sheet without its own threshold.
GLOBAL_THRESHOLD: float = float(os.getenv("GLOBAL_THRESHOLD", "8"))

# Scraper Settings
RUN_SCRAPER: bool = os.getenv("RUN_SCRAPER", "True").lower() == "true"
# Include unofficial (practice-mode) participants from the standings.
INCLUDE_UNOFFICIAL: bool = (
    os.getenv("INCLUDE_UNOFFICIAL", "True").lower() == "true"
)
# Optional Chrome major version override (e.g. 154). 0 = auto-detect.
CHROME_VERSION: int = int(os.getenv("CHROME_VERSION", "0") or 0)
# Persistent Chrome profile used to keep the Codeforces login session.
CHROME_PROFILE_DIR: str = os.getenv("CHROME_PROFILE_DIR", "chrome_profile")
# Seconds to wait for manual login in login.py.
LOGIN_TIMEOUT: int = int(os.getenv("LOGIN_TIMEOUT", "300") or 300)

# Output Files
COMBINED_CSV: str = os.getenv("COMBINED_CSV", "combined_results.csv")

# Number of contests (optional). When set, it must match the configured contests.
CONTEST_COUNT: int = int(os.getenv("CONTEST_COUNT", "0") or 0)

# Contest Configuration
# Format: (contest_name, contest_standings_url, weight, participation_bonus)
# Example in .env:
#   CONTESTS=Contest1|https://.../standings|1|0;Contest2|https://.../standings|2|3
# The participation bonus is awarded to official participants who appeared in
# the live standings, but not out-of-competition/virtual/practice participants.
DEFAULT_CONTESTS: List[Tuple[str, str, float, float]] = [
    (
        "Contest1",
        "https://codeforces.com/group/3MTZPM7hsC/contest/651191/standings",
        1.0,
        0.0,
    ),
    (
        "Contest2",
        "https://codeforces.com/group/3MTZPM7hsC/contest/652764/standings",
        1.0,
        0.0,
    ),
]


def _parse_contests(raw: str) -> List[Tuple[str, str, float, float]]:
    """
    Parse contests from a ';' separated list of
    name|url|weight|participation_bonus entries.
    """
    contests: List[Tuple[str, str, float, float]] = []

    for index, chunk in enumerate(raw.split(";"), start=1):
        chunk = chunk.strip()
        if not chunk:
            continue

        parts = [part.strip() for part in chunk.split("|")]
        if len(parts) < 2 or not parts[1]:
            continue

        name = parts[0] or f"Contest{index}"
        url = parts[1]
        weight = float(parts[2]) if len(parts) > 2 and parts[2] else 1.0
        bonus = float(parts[3]) if len(parts) > 3 and parts[3] else 0.0
        contests.append((name, url, weight, bonus))

    return contests


CONTESTS: List[Tuple[str, str, float, float]] = (
    _parse_contests(os.getenv("CONTESTS", "")) or DEFAULT_CONTESTS
)


def _parse_sheet_thresholds(
    raw: str, sheet_names: List[str], fallback: float
) -> Dict[str, float]:
    """
    Parse per-sheet thresholds from a ';' separated list of sheet=threshold entries.
    Any sheet without an explicit threshold uses the fallback value.
    """
    thresholds: Dict[str, float] = {}

    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue

        name, value = chunk.rsplit("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue

        thresholds[name] = float(value)

    for name in sheet_names:
        thresholds.setdefault(name, fallback)

    return thresholds


# Per-day (per-sheet) thresholds, e.g.:
#   SHEET_THRESHOLDS=Sat 4 -> 8=8;Sun 10 -> 2=10;Sun 4 -> 8=8;Mon 4 -> 8=8
SHEET_THRESHOLDS: Dict[str, float] = _parse_sheet_thresholds(
    os.getenv("SHEET_THRESHOLDS", ""), SHEET_NAMES, GLOBAL_THRESHOLD
)


def _parse_subset_thresholds(raw: str) -> Dict[str, float]:
    """
    Parse semicolon-separated 'name_prefix=threshold' pairs for subset rules.

    Example:
        SUBSET_THRESHOLDS=Week 3=21
    A participant must also score at least the threshold across every contest
    whose name starts with the given prefix.
    """
    subset_thresholds: Dict[str, float] = {}

    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue

        name, value = chunk.rsplit("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue

        subset_thresholds[name] = float(value)

    return subset_thresholds


# Subset (local) thresholds over groups of contests, e.g.:
#   SUBSET_THRESHOLDS=Week 3=21
# Validity then requires the global/sheet threshold AND every subset threshold.
SUBSET_THRESHOLDS: Dict[str, float] = _parse_subset_thresholds(
    os.getenv("SUBSET_THRESHOLDS", "")
)


def get_subset_contests(
    name_prefix: str,
    contests: Optional[List[Tuple[str, str, float, float]]] = None,
) -> List[Tuple[str, str, float, float]]:
    """Return contests whose name starts with the given prefix (case-insensitive)."""
    if contests is None:
        contests = CONTESTS

    prefix = name_prefix.strip().casefold()
    return [
        contest
        for contest in contests
        if contest[0].strip().casefold().startswith(prefix)
    ]


# Scraper Delays (in seconds)
MIN_PAGE_DELAY: float = 1.0
MAX_PAGE_DELAY: float = 2.0
MIN_CLICK_DELAY: float = 0.5
MAX_CLICK_DELAY: float = 1.0
CLOUDFLARE_WAIT: int = int(os.getenv("CLOUDFLARE_WAIT", "30") or 30)

MAX_PAGES: int = 100


def get_sheet_threshold(sheet_name: str) -> float:
    """Return the threshold configured for a sheet."""
    return SHEET_THRESHOLDS.get(sheet_name, GLOBAL_THRESHOLD)


def validate_config() -> bool:
    """Validate that all required configuration is present"""
    if not SPREADSHEET_ID:
        print(
            "❌ ERROR: GOOGLE_SHEET_LINK (or SPREADSHEET_ID) not set in .env file"
        )
        return False

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ ERROR: {CREDENTIALS_FILE} not found")
        return False

    if not CONTESTS:
        print("❌ ERROR: No contests configured")
        return False

    if CONTEST_COUNT and CONTEST_COUNT != len(CONTESTS):
        print(
            f"❌ ERROR: CONTEST_COUNT is {CONTEST_COUNT}, "
            f"but {len(CONTESTS)} contests are configured"
        )
        return False

    for name, url, weight, bonus in CONTESTS:
        if not name or not url:
            print("❌ ERROR: Every contest needs a name and a standings link")
            return False
        if weight <= 0:
            print(f"❌ ERROR: Contest '{name}' has a non-positive weight")
            return False
        if bonus < 0:
            print(f"❌ ERROR: Contest '{name}' has a negative participation bonus")
            return False

    if not SHEET_NAMES:
        print("❌ ERROR: SHEET_NAMES not set in .env file")
        return False

    for name, threshold in SUBSET_THRESHOLDS.items():
        if threshold < 0:
            print(f"❌ ERROR: SUBSET_THRESHOLDS '{name}' is negative")
            return False
        if not get_subset_contests(name):
            print(
                f"❌ ERROR: SUBSET_THRESHOLDS prefix '{name}' matches no contest"
            )
            return False

    return True
