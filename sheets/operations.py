import re
import time
import pandas as pd
from typing import Dict, List, Optional, Tuple

from sheets.auth import SheetsAuthenticator
from utils.handles import handle_key, live_mask
from utils.logger import logger
import config


def _a1_quote(sheet_name: str) -> str:
    """Quote a sheet name for use in A1 notation."""
    return "'" + sheet_name.replace("'", "''") + "'"


def _normalize_sheet_name(name: str) -> str:
    """
    Normalize a sheet name so spacing/arrow differences don't matter.

    For example "Sat 4->8", "Sat 4 -> 8" and "sat 4 → 8" all normalize to
    the same value.
    """
    name = (name or "").replace("→", "->").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", name).casefold()


def compute_weighted_score(
    handle: str,
    contest_configs: List[Tuple[str, str, float, float]],
    dfs: Dict[str, pd.DataFrame],
) -> Tuple[float, Dict]:
    """
    Compute the weighted score for a handle across all contests.

    Solving one problem in a contest is worth that contest's weight, so
    solving m problems is worth m * weight. Live participants also receive
    that contest's participation bonus.
    """
    key = handle_key(handle)
    total_score = 0.0
    details = {}

    for contest_name, _url, weight, bonus in contest_configs:
        df = dfs[contest_name]
        match = df[df["Handle"].map(handle_key) == key]

        solved = int(match.iloc[0]["Total_Solved"]) if not match.empty else 0
        is_live = bool(live_mask(match).iloc[0]) if not match.empty else False
        weighted = solved * weight
        applied_bonus = bonus if (bonus and is_live) else 0.0
        total_score += weighted + applied_bonus

        details[contest_name] = {
            "solved": solved,
            "weight": weight,
            "weighted": weighted,
            "live": is_live,
            "bonus": applied_bonus,
        }

    return total_score, details


def build_weighted_scores(
    contest_configs: List[Tuple[str, str, float, float]],
    dfs: Dict[str, pd.DataFrame],
) -> Dict[str, float]:
    """
    Precompute weighted scores for every handle across all contests.

    Keys are case-insensitive cleaned handles so sheets can use different
    casing from Codeforces.
    """
    scores: Dict[str, float] = {}

    for contest_name, _url, weight, bonus in contest_configs:
        df = dfs[contest_name]
        live = live_mask(df)

        for handle, solved, is_live in zip(
            df["Handle"], df["Total_Solved"], live
        ):
            key = handle_key(handle)
            if not key:
                continue

            scores[key] = scores.get(key, 0.0) + int(solved) * weight
            if bonus and bool(is_live):
                scores[key] += bonus

    return scores


class SheetsOperations:

    def __init__(self):
        self.auth = SheetsAuthenticator()
        self.service = None
        self.sheet_ids: Dict[str, int] = {}
        self.sheet_properties: Dict[str, Dict] = {}
        self.resolved_names: Dict[str, str] = {}

    def initialize(self):
        self.service = self.auth.authenticate()
        self._load_sheet_metadata()

    def _load_sheet_metadata(self) -> None:
        """
        Load sheet metadata and resolve configured names to actual tab titles.

        The names in .env may differ from the real tab titles only by spacing
        around an arrow (e.g. "Sat 4->8" vs "Sat 4 -> 8"), so match on a
        normalized form instead of requiring an exact string.
        """
        metadata = (
            self.service.spreadsheets()
            .get(spreadsheetId=config.SPREADSHEET_ID)
            .execute()
        )

        titles: Dict[str, Dict] = {}
        by_normalized: Dict[str, str] = {}
        for sheet in metadata["sheets"]:
            properties = sheet["properties"]
            title = properties["title"]
            titles[title] = properties
            by_normalized[_normalize_sheet_name(title)] = title

        resolved = {}
        for name in config.SHEET_NAMES:
            actual = name if name in titles else by_normalized.get(
                _normalize_sheet_name(name)
            )
            if actual:
                resolved[name] = actual
                if actual != name:
                    logger.info(f"  🔗 Sheet '{name}' matched to '{actual}'")
            else:
                logger.error(
                    f"Sheet '{name}' not found. Available tabs: "
                    f"{', '.join(titles)}"
                )

        self.resolved_names = resolved
        self.sheet_ids = {
            actual: titles[actual]["sheetId"] for actual in resolved.values()
        }
        self.sheet_properties = {
            actual: titles[actual] for actual in resolved.values()
        }

    def resolve_sheet_name(self, sheet_name: str) -> Optional[str]:
        """Return the real tab title for a configured sheet name."""
        return self.resolved_names.get(sheet_name)

    def ensure_capacity(
        self, sheet_name: str, min_columns: int = 5, min_rows: int = 0
    ) -> None:
        """
        Grow a sheet's grid so it has at least the requested columns/rows.

        Google Sheets rejects writes to ranges outside the current grid (for
        example writing column D on a sheet that only has A:C).
        """
        actual = self.resolve_sheet_name(sheet_name)
        if actual is None:
            return

        sheet_id = self.sheet_ids.get(actual)
        if sheet_id is None:
            return

        properties = self.sheet_properties.get(actual, {})
        grid = properties.get("gridProperties", {})
        current_columns = int(grid.get("columnCount", 0))
        current_rows = int(grid.get("rowCount", 0))

        requests = []
        if current_columns < min_columns:
            requests.append(
                {
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "length": min_columns - current_columns,
                    }
                }
            )
        if min_rows and current_rows < min_rows:
            requests.append(
                {
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "length": min_rows - current_rows,
                    }
                }
            )

        if not requests:
            return

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=config.SPREADSHEET_ID, body={"requests": requests}
        ).execute()

        grid["columnCount"] = max(current_columns, min_columns)
        if min_rows:
            grid["rowCount"] = max(current_rows, min_rows)
        properties["gridProperties"] = grid
        self.sheet_properties[actual] = properties

        logger.info(
            f"  ✅ Expanded '{actual}' to "
            f"{grid['columnCount']} columns x {grid.get('rowCount', current_rows)} rows"
        )

    def get_sheet_data(self, sheet_name: str) -> List[List[str]]:
        """
        Get all data from a sheet

        Args:
            sheet_name: Name of the sheet

        Returns:
            2D list of cell values
        """
        actual = self.resolve_sheet_name(sheet_name) or sheet_name
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=config.SPREADSHEET_ID,
                range=f"{_a1_quote(actual)}!A:E",
            )
            .execute()
        )
        return result.get("values", [])

    def update_cells(self, updates: List[Dict]) -> None:
        """
        Write values to cells in bulk.

        Args:
            updates: List of {"range": A1 range, "values": [[value]]} entries
        """
        if not updates:
            return

        for i in range(0, len(updates), 500):
            batch = updates[i : i + 500]
            body = {
                "valueInputOption": "RAW",
                "data": batch,
            }
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=config.SPREADSHEET_ID, body=body
            ).execute()
            time.sleep(1)

    def format_columns(self, sheet_name: str) -> None:
        """
        Format columns B:E with borders. Names are left aligned and the
        verdict/score columns are centered.

        Args:
            sheet_name: Name of the sheet
        """
        actual = self.resolve_sheet_name(sheet_name) or sheet_name
        sheet_id = self.sheet_ids.get(actual)
        if sheet_id is None:
            logger.error(f"Sheet '{sheet_name}' not found")
            return

        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=config.SPREADSHEET_ID,
                range=f"{_a1_quote(actual)}!B:E",
            )
            .execute()
        )
        values = result.get("values", [])

        if not values:
            return

        requests = []

        for row_idx, row in enumerate(values):
            for col_idx in range(min(4, len(row))):
                cell_value = row[col_idx].strip() if col_idx < len(row) else ""

                if not cell_value:
                    continue

                alignment = "LEFT" if col_idx < 2 else "CENTER"

                requests.append(
                    {
                        "updateCells": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row_idx,
                                "endRowIndex": row_idx + 1,
                                "startColumnIndex": col_idx + 1,
                                "endColumnIndex": col_idx + 2,
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,borders)",
                            "rows": [
                                {
                                    "values": [
                                        {
                                            "userEnteredFormat": {
                                                "horizontalAlignment": alignment,
                                                "borders": {
                                                    "left": {
                                                        "style": "SOLID",
                                                        "color": {
                                                            "red": 0,
                                                            "green": 0,
                                                            "blue": 0,
                                                        },
                                                    },
                                                    "right": {
                                                        "style": "SOLID",
                                                        "color": {
                                                            "red": 0,
                                                            "green": 0,
                                                            "blue": 0,
                                                        },
                                                    },
                                                    "top": {
                                                        "style": "SOLID",
                                                        "color": {
                                                            "red": 0,
                                                            "green": 0,
                                                            "blue": 0,
                                                        },
                                                    },
                                                    "bottom": {
                                                        "style": "SOLID",
                                                        "color": {
                                                            "red": 0,
                                                            "green": 0,
                                                            "blue": 0,
                                                        },
                                                    },
                                                },
                                            }
                                        }
                                    ]
                                }
                            ],
                        }
                    }
                )

        if requests:
            for i in range(0, len(requests), 50):
                batch = requests[i : i + 50]
                body = {"requests": batch}
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=config.SPREADSHEET_ID, body=body
                ).execute()
                time.sleep(1)

            logger.info(f"  ✅ Formatted {len(requests)} cells")


def clean_google_sheets(dfs: Dict[str, pd.DataFrame]) -> None:
    """
    Mark participants in columns D (verdict) and E (score) of every sheet.

    A participant is valid for a sheet when their weighted score across all
    contests is greater than or equal to that sheet's threshold. Rows are
    never deleted.
    """
    logger.info("\n" + "=" * 60)
    logger.info("STEP 2: MARKING PARTICIPANTS IN GOOGLE SHEETS")
    logger.info("=" * 60)

    sheets = SheetsOperations()
    sheets.initialize()

    logger.info("✅ Authenticated\n")

    scores = build_weighted_scores(config.CONTESTS, dfs)
    total_marked = 0

    # Data starts at row 3 (index 2): row 1 is the header, row 2 is a section row.
    for sheet_name in config.SHEET_NAMES:
        threshold = config.get_sheet_threshold(sheet_name)
        actual_name = sheets.resolve_sheet_name(sheet_name)

        logger.info("\n" + "=" * 60)
        logger.info(f"Processing Sheet: '{sheet_name}' (threshold: {threshold})")
        logger.info("=" * 60)

        if actual_name is None:
            logger.error("  ⚠️  Skipping: sheet not found in spreadsheet")
            continue

        sheets.ensure_capacity(sheet_name, min_columns=5)

        data = sheets.get_sheet_data(sheet_name)

        if not data or len(data) < 3:
            logger.warning("  ⚠️  No data rows")
            continue

        header_updates = []
        updates = []
        valid_count = 0
        invalid_count = 0

        if len(data[0]) < 5 or not str(data[0][4]).strip():
            header_updates.append(
                {
                    "range": f"{_a1_quote(actual_name)}!E1",
                    "values": [["Score"]],
                }
            )

        for row_idx in range(2, len(data)):
            row = data[row_idx]
            raw_handle = row[2].strip() if len(row) > 2 else ""

            if not raw_handle:
                continue

            key = handle_key(raw_handle)
            if not key:
                continue

            score = scores.get(key, 0.0)
            is_valid = score >= threshold
            status = "Yes" if is_valid else "No"
            score_value = (
                int(score) if float(score).is_integer() else round(float(score), 2)
            )

            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1

            updates.append(
                {
                    "range": (
                        f"{_a1_quote(actual_name)}!"
                        f"D{row_idx + 1}:E{row_idx + 1}"
                    ),
                    "values": [[status, score_value]],
                }
            )

        if header_updates or updates:
            sheets.update_cells(header_updates + updates)
            total_marked += len(updates)
            logger.info(
                f"  ✅ Marked {len(updates)} rows "
                f"(Yes: {valid_count}, No: {invalid_count})"
            )
        else:
            logger.info("  ✅ No rows to mark")

    logger.info(f"\n✅ Total marked: {total_marked} rows\n")

    logger.info("=" * 60)
    logger.info("STEP 3: FORMATTING COLUMNS")
    logger.info("=" * 60)

    for sheet_name in config.SHEET_NAMES:
        logger.info(f"\n📋 Formatting '{sheet_name}'...")
        sheets.format_columns(sheet_name)

    logger.info("✅ Formatting complete!")
