import os
import sys
import pandas as pd
from typing import Dict, Tuple
import config
from scraper.codeforces import CodeforcesScraper
from sheets.operations import clean_google_sheets
from utils.handles import as_bool_series, handle_key, live_mask, parse_handle
from utils.logger import logger


def normalize_handles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean legacy CSV handles such as "Name  →to practice", virtual markers,
    and appended virtual times, then deduplicate case-insensitively.
    """
    if "Handle" not in df.columns:
        return df

    df = df.copy()
    parsed = df["Handle"].fillna("").map(parse_handle)
    df["Handle"] = [info.handle for info in parsed]
    flagged_unofficial = pd.Series(
        [info.unofficial for info in parsed], index=df.index
    )
    flagged_live = pd.Series([info.live for info in parsed], index=df.index)

    if "Unofficial" in df.columns:
        df["Unofficial"] = (
            as_bool_series(df["Unofficial"]) | flagged_unofficial
        )
    else:
        df["Unofficial"] = flagged_unofficial

    if "Live" in df.columns:
        # An explicit Live column is authoritative. Markers can only
        # downgrade a row (virtual/practice), never upgrade a cleaned handle.
        df["Live"] = as_bool_series(df["Live"]) & flagged_live
    else:
        df["Live"] = flagged_live

    df = df[df["Handle"] != ""]

    if df["Handle"].str.casefold().duplicated().any():
        df["_key"] = df["Handle"].str.casefold()
        merged = df.groupby("_key")[["Unofficial", "Live"]].any()
        df = (
            df.sort_values("Total_Solved", ascending=False)
            .drop_duplicates(subset="_key", keep="first")
            .set_index("_key")
        )
        df["Unofficial"] = merged["Unofficial"]
        df["Live"] = merged["Live"]
        df = df.reset_index(drop=True)

    return df.reset_index(drop=True)


def load_existing_csvs() -> Dict[str, pd.DataFrame]:
    """
    Load existing CSV files instead of scraping

    Returns:
        Dictionary mapping contest name to DataFrame
    """
    dfs = {}

    for contest_config in config.CONTESTS:
        contest_name = contest_config[0]
        csv_file = f"{contest_name}_standings.csv"

        if not os.path.exists(csv_file):
            logger.error(
                f"❌ ERROR: {csv_file} not found. Set RUN_SCRAPER=True in .env"
            )
            sys.exit(1)

        logger.info(f"📂 Loading existing CSV: {csv_file}")
        df = normalize_handles(pd.read_csv(csv_file))
        dfs[contest_name] = df
        logger.info(f"✅ Loaded {len(df)} participants\n")

    return dfs


def weighted_score(handle: str, dfs: Dict[str, pd.DataFrame]) -> Tuple[float, int]:
    """
    Compute the weighted score for a handle across all contests.

    Solving one problem in a contest is worth that contest's weight, so
    solving m problems is worth m * weight. Live participants also receive
    each contest's participation bonus.
    """
    key = handle_key(handle)
    total_score = 0.0
    total_solved = 0

    for contest_name, _url, weight, bonus in config.CONTESTS:
        df = dfs[contest_name]
        match = df[df["Handle"].map(handle_key) == key]

        solved = int(match.iloc[0]["Total_Solved"]) if not match.empty else 0
        is_live = bool(live_mask(match).iloc[0]) if not match.empty else False
        total_solved += solved
        total_score += solved * weight
        if bonus and is_live:
            total_score += bonus

    return total_score, total_solved


def generate_combined_csv(dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Generate combined CSV with weighted totals across all contests

    Args:
        dfs: Dictionary mapping contest name to DataFrame

    Returns:
        Combined DataFrame
    """
    logger.info("\n" + "=" * 60)
    logger.info("STEP 4: GENERATING COMBINED RESULTS")
    logger.info("=" * 60)

    # Collect all unique handles, keyed case-insensitively.
    display_handles = {}
    unofficial_keys = set()
    contest_rows = {}

    for contest_name, _url, _weight, _bonus in config.CONTESTS:
        df = dfs[contest_name]
        live = live_mask(df)
        unofficial = (
            as_bool_series(df["Unofficial"])
            if "Unofficial" in df.columns
            else pd.Series(False, index=df.index)
        )

        rows = {}
        for handle, solved, is_live, is_unofficial in zip(
            df["Handle"], df["Total_Solved"], live, unofficial
        ):
            key = handle_key(handle)
            if not key:
                continue

            display_handles.setdefault(key, parse_handle(handle).handle)
            rows[key] = (int(solved), bool(is_live))
            if is_unofficial:
                unofficial_keys.add(key)

        contest_rows[contest_name] = rows

    combined_data = []

    for key in display_handles:
        row = {"Handle": display_handles[key], "Unofficial": key in unofficial_keys}
        weighted_total = 0.0
        total_solved = 0
        total_bonus = 0.0

        for contest_name, _url, weight, bonus in config.CONTESTS:
            solved, is_live = contest_rows[contest_name].get(key, (0, False))
            applied_bonus = bonus if (bonus and is_live) else 0.0

            row[f"{contest_name}_Solved"] = solved
            row[f"{contest_name}_Weight"] = weight
            row[f"{contest_name}_Weighted"] = solved * weight
            row[f"{contest_name}_Live"] = is_live
            row[f"{contest_name}_Bonus"] = applied_bonus

            total_solved += solved
            total_bonus += applied_bonus
            weighted_total += solved * weight + applied_bonus

        row["Total_Solved_All_Contests"] = total_solved
        row["Total_Bonus"] = total_bonus
        row["Weighted_Total"] = weighted_total

        for sheet_name in config.SHEET_NAMES:
            threshold = config.get_sheet_threshold(sheet_name)
            row[f"Valid_{sheet_name}"] = (
                "Yes" if weighted_total >= threshold else "No"
            )

        combined_data.append(row)

    # Create DataFrame and sort
    combined_df = pd.DataFrame(combined_data)
    combined_df = combined_df.sort_values(
        "Weighted_Total", ascending=False
    ).reset_index(drop=True)

    # Save to CSV
    combined_df.to_csv(config.COMBINED_CSV, index=False, encoding="utf-8-sig")

    logger.info(f"\n✅ Generated combined results CSV: {config.COMBINED_CSV}")
    logger.info(f"✅ Total unique participants: {len(combined_df)}\n")

    return combined_df


def print_summary():
    """Print automation summary"""
    logger.info("\n" + "=" * 60)
    logger.info("ACM AUTOMATION (Multi-Contest, Weighted)")
    logger.info("=" * 60)
    logger.info(f"Number of contests: {len(config.CONTESTS)}")

    for contest_config in config.CONTESTS:
        name = contest_config[0]
        weight = contest_config[2]
        bonus = contest_config[3]
        logger.info(f"  - {name} (weight: {weight}, participation bonus: {bonus})")

    logger.info("\nSheet thresholds:")
    for sheet_name in config.SHEET_NAMES:
        logger.info(
            f"  - {sheet_name}: {config.get_sheet_threshold(sheet_name)}"
        )

    logger.info("=" * 60 + "\n")


def main():
    """Main execution function"""
    try:
        if not config.validate_config():
            logger.error(
                "Configuration validation failed. Please check your .env file."
            )
            sys.exit(1)

        print_summary()

        if config.RUN_SCRAPER:
            results = CodeforcesScraper.scrape_all_contests()
            dfs = {contest_name: df for contest_name, (df, _) in results.items()}
        else:
            dfs = load_existing_csvs()

        clean_google_sheets(dfs)

        generate_combined_csv(dfs)

        logger.info("\n" + "=" * 60)
        logger.info("🎉 AUTOMATION COMPLETE!")
        logger.info("=" * 60)
        logger.info(f"Check {config.COMBINED_CSV} for full results.\n")

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Process interrupted by user")
        sys.exit(0)

    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
