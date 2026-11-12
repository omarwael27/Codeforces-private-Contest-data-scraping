import os
import sys
import pandas as pd
from typing import Dict, Tuple
import config
from scraper.codeforces import CodeforcesScraper, clean_handle
from sheets.operations import clean_google_sheets
from utils.logger import logger


def normalize_handles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean legacy CSV handles such as "Name  →to practice" and flag them.

    Older scraped CSVs stored the practice marker inside the Handle column,
    which prevented those handles from matching the Google Sheet.
    """
    if "Handle" not in df.columns:
        return df

    df = df.copy()
    parsed = df["Handle"].fillna("").map(clean_handle)
    df["Handle"] = [handle for handle, _ in parsed]
    flagged = pd.Series(
        [is_unofficial for _, is_unofficial in parsed], index=df.index
    )

    if "Unofficial" in df.columns:
        df["Unofficial"] = df["Unofficial"].astype(bool) | flagged
    else:
        df["Unofficial"] = flagged

    df = df[df["Handle"] != ""]

    if df["Handle"].duplicated().any():
        unofficial_map = df.groupby("Handle")["Unofficial"].any()
        df = (
            df.sort_values("Total_Solved", ascending=False)
            .drop_duplicates(subset="Handle", keep="first")
            .set_index("Handle")
        )
        df["Unofficial"] = unofficial_map
        df = df.reset_index()

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
    solving m problems is worth m * weight.
    """
    total_score = 0.0
    total_solved = 0

    for contest_name, _url, weight in config.CONTESTS:
        df = dfs[contest_name]
        match = df[df["Handle"] == handle]

        solved = int(match.iloc[0]["Total_Solved"]) if not match.empty else 0
        total_solved += solved
        total_score += solved * weight

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

    # Collect all unique handles
    all_handles = set()
    unofficial_handles = set()
    for df in dfs.values():
        all_handles.update(df["Handle"].tolist())

        if "Unofficial" in df.columns:
            mask = (
                df["Unofficial"]
                .astype(str)
                .str.lower()
                .isin(["true", "1", "yes"])
            )
            unofficial_handles.update(df.loc[mask, "Handle"])

    combined_data = []

    for handle in sorted(all_handles):
        row = {"Handle": handle, "Unofficial": handle in unofficial_handles}
        weighted_total = 0.0
        total_solved = 0

        for contest_name, _url, weight in config.CONTESTS:
            df = dfs[contest_name]
            match = df[df["Handle"] == handle]

            solved = int(match.iloc[0]["Total_Solved"]) if not match.empty else 0

            row[f"{contest_name}_Solved"] = solved
            row[f"{contest_name}_Weight"] = weight
            row[f"{contest_name}_Weighted"] = solved * weight

            total_solved += solved
            weighted_total += solved * weight

        row["Total_Solved_All_Contests"] = total_solved
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
        logger.info(f"  - {name} (weight: {weight})")

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
