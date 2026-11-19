import re
from dataclasses import dataclass
from typing import Tuple

import pandas as pd

_TIME_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
_PRACTICE_RE = re.compile(r"\bto\s+practice\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class HandleInfo:
    handle: str
    unofficial: bool
    live: bool
    virtual: bool
    practice: bool
    out_of_competition: bool


def parse_handle(raw_handle: str) -> HandleInfo:
    """
    Normalize a standings/sheet handle and classify how the participant joined.

    Codeforces marks unofficial rows inside the handle cell:
      *            out-of-competition (unofficial)
      #            virtual participant (joined after the contest)
      ->to practice  practice participant (joined after the contest)

    Only plain official participants count as live. Out-of-competition,
    virtual, and practice participants do not.

    Some pages also append the virtual start time directly to the handle
    (for example ``romanysameh9:04:07``). Any time-looking suffix is treated
    as a virtual marker and removed.
    """
    if raw_handle is None:
        raw = ""
    elif isinstance(raw_handle, float) and pd.isna(raw_handle):
        raw = ""
    else:
        raw = str(raw_handle).strip()

    lowered = raw.lower()

    has_time = bool(_TIME_RE.search(raw))
    virtual = "#" in raw or has_time
    practice = "→" in raw or "to practice" in lowered
    out_of_competition = "*" in raw
    unofficial = virtual or practice or out_of_competition

    cleaned = _TAG_RE.sub(" ", raw)
    cleaned = cleaned.replace("*", " ").replace("#", " ").replace("→", " ")
    cleaned = _PRACTICE_RE.sub(" ", cleaned)
    cleaned = _TIME_RE.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    handle = cleaned.split()[0] if cleaned else ""

    live = bool(handle) and not unofficial

    return HandleInfo(
        handle=handle,
        unofficial=unofficial,
        live=live,
        virtual=virtual,
        practice=practice,
        out_of_competition=out_of_competition,
    )


def clean_handle(raw_handle: str) -> Tuple[str, bool]:
    """Return the bare handle and whether the row is unofficial."""
    info = parse_handle(raw_handle)
    return info.handle, info.unofficial


def handle_key(raw_handle: str) -> str:
    """Return a case-insensitive key for matching handles across sources."""
    return parse_handle(raw_handle).handle.casefold()


def as_bool_series(series: pd.Series) -> pd.Series:
    """Convert a possibly-string boolean column to real booleans."""
    if series.dtype == bool:
        return series.fillna(False).astype(bool)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes"])
    )


def live_mask(df: pd.DataFrame) -> pd.Series:
    """
    Return a mask of participants who appeared in the live standings.

    A ``Live`` column is authoritative when present. Otherwise fall back to
    ``Unofficial`` (legacy CSVs), and finally assume everyone is live.
    """
    if "Live" in df.columns:
        return as_bool_series(df["Live"])
    if "Unofficial" in df.columns:
        return ~as_bool_series(df["Unofficial"])
    return pd.Series(True, index=df.index)
