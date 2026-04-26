"""
education_to_csv.py - Export all education data sources directly to CSV files.

Reads the same data sources as education_pipeline.py but skips DuckDB and
PostgreSQL entirely, writing each dataset straight to a CSV file in the
csv/ output folder.

Output files:
    csv/scorecard_clean.csv
    csv/census_education_attainment_2024.csv
    csv/fed_higher_ed_shed_2024.csv  (skipped with warning if network unavailable)

Usage:
    python education_to_csv.py
"""

import csv
import glob
import os
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = "csv"
SCORECARD_DIR = "datasets/college_scorecard"
CENSUS_CSV = "ACSST1Y2024.S1501-2026-03-07T044644.csv"

FED_MAIN_URL = (
    "https://www.federalreserve.gov/publications/"
    "2025-economic-well-being-of-us-households-in-2024-"
    "higher-education-and-student-loans.htm"
)
FED_ACCESSIBLE_URL = (
    "https://www.federalreserve.gov/publications/"
    "2025-economic-well-being-of-us-households-in-2024-"
    "accessibility-tables.htm"
)

# Scorecard columns to keep, mapped to human-friendly names.
SCORECARD_COLUMN_MAP = {
    "UNITID": "institution_id",
    "INSTNM": "institution_name",
    "CITY": "city",
    "STABBR": "state",
    "CONTROL": "institution_type",
    # Overall completion
    "C150_4": "overall_completion_rate",
    # Completion by race
    "C150_4_WHITE": "white_completion_rate",
    "C150_4_BLACK": "black_completion_rate",
    "C150_4_HISP": "hispanic_completion_rate",
    "C150_4_ASIAN": "asian_completion_rate",
    "C150_4_AIAN": "native_american_completion_rate",
    "C150_4_NHPI": "pacific_islander_completion_rate",
    "C150_4_2MOR": "two_or_more_races_completion_rate",
    "C150_4_NRA": "nonresident_alien_completion_rate",
    "C150_4_UNKN": "unknown_race_completion_rate",
    # Pell / loan completion
    "C150_4_PELL": "pell_completion_rate",
    "D150_4_PELL": "pell_cohort_count",
    "C150_4_LOANNOPELL": "nonpell_loan_completion_rate",
    "D150_4_LOANNOPELL": "nonpell_loan_cohort_count",
    "C150_4_NOLOANNOPELL": "nonpell_noloan_completion_rate",
    "D150_4_NOLOANNOPELL": "nonpell_noloan_cohort_count",
    # Financial context
    "PCTPELL": "pell_share",
    "TUITIONFEE_IN": "in_state_tuition",
    # Institution info
    "ADDR": "address",
    "ICLEVEL": "institution_level",
    "STUFACR": "student_faculty_ratio",
    "OPENADMP": "open_admissions",
    # Enrollment
    "UG12MN": "undergrad_enrollment",
    "UGDS_MEN": "undergrad_share_men",
    "UGDS_WOMEN": "undergrad_share_women",
    # Admissions & test scores
    "ADM_RATE_SUPP": "admission_rate",
    "SATVR50": "sat_verbal_midpoint",
    "SATMT50": "sat_math_midpoint",
    "ACTCM50": "act_composite_midpoint",
    # Retention
    "RET_FT4_POOLED": "retention_rate_fulltime",
    "RET_PT4_POOLED": "retention_rate_parttime",
    # Costs & aid
    "BOOKSUPPLY": "avg_books_supplies_cost",
    "ROOMBOARD_ON": "avg_room_board_on_campus",
    "PCTFLOAN_DCS": "federal_loan_share",
    "FTFTPCTPELL": "first_time_fulltime_pell_share",
}

# Sentinel strings the Scorecard uses instead of real NULLs.
SCORECARD_NA_VALUES = {"NULL", "PrivacySuppressed", "NA", "PS", ""}


# ===========================================================================
# Shared helpers
# ===========================================================================


def _parse_census_number(value: str):
    """Convert Census strings like '31,270,959' or '±48,363' to a number."""
    if value is None:
        return None
    cleaned = value.strip().replace(",", "").replace("%", "").replace("±", "")
    if not cleaned or cleaned == "(X)":
        return None
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None


def _normalize_census_label(label: str):
    """Return (indent_level, stripped_label) from an ACS grouping label."""
    normalized = label.replace("\xa0", " ")
    indent = len(normalized) - len(normalized.lstrip())
    return indent // 4, normalized.strip()


def _clean_text(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\xa0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(text.split())


def _to_float(value: str):
    cleaned = _clean_text(value).replace("%", "")
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return BeautifulSoup(resp.content.decode("utf-8"), "html.parser")


def _extract_fed_table(soup, table_id, table_title, source_url, source_page, note):
    """Scrape a single Fed HTML table into a list of row dicts."""
    table = soup.find("table", id=table_id)
    if table is None:
        raise ValueError(f"Table '{table_id}' not found at {source_url}")

    headers = [_clean_text(th.get_text()) for th in table.select("thead th")]
    rows = []
    current_group = None
    fetched_at = datetime.now(timezone.utc).isoformat()

    for tr in table.select("tbody tr"):
        stub = tr.find("th")
        if stub is None:
            continue
        stub_text = _clean_text(stub.get_text())
        cells = tr.find_all("td")

        if len(cells) == 0:
            current_group = stub_text
            continue

        for idx, cell in enumerate(cells):
            metric = headers[idx + 1] if idx + 1 < len(headers) else f"series_{idx + 1}"
            value = _to_float(cell.get_text())
            if value is None:
                continue
            rows.append(
                {
                    "source_name": "fed_shed_2024",
                    "source_page": source_page,
                    "source_url": source_url,
                    "source_table_id": table_id,
                    "source_table_title": table_title,
                    "section_group": current_group,
                    "category": stub_text,
                    "metric": metric,
                    "value_pct": value,
                    "unit": "percent",
                    "note": note,
                    "fetched_at": fetched_at,
                }
            )
    return rows


# ===========================================================================
# 1. College Scorecard → csv/scorecard_clean.csv
# ===========================================================================


def export_scorecard_to_csv():
    out_path = os.path.join(OUTPUT_DIR, "scorecard_clean.csv")
    pattern = os.path.join(SCORECARD_DIR, "MERGED2023_24_PP.csv")
    files = glob.glob(pattern)

    if not files:
        print(f"  [SKIP] Scorecard CSV not found: {pattern}")
        return

    filepath = files[0]
    print(f"  Reading {os.path.basename(filepath)}...")

    friendly_headers = list(SCORECARD_COLUMN_MAP.values())
    row_count = 0

    with open(filepath, newline="", encoding="utf-8-sig") as in_fh, \
         open(out_path, "w", newline="", encoding="utf-8") as out_fh:

        reader = csv.DictReader(in_fh)
        writer = csv.DictWriter(out_fh, fieldnames=friendly_headers)
        writer.writeheader()

        for raw_row in reader:
            out_row = {}
            for original, friendly in SCORECARD_COLUMN_MAP.items():
                raw_val = raw_row.get(original, "")
                out_row[friendly] = "" if raw_val in SCORECARD_NA_VALUES else raw_val
            writer.writerow(out_row)
            row_count += 1

    print(f"  -> {out_path}: {row_count} rows")


# ===========================================================================
# 2. Census ACS S1501 → csv/census_education_attainment_2024.csv
# ===========================================================================


CENSUS_HEADERS = [
    "row_order",
    "section",
    "label_level",
    "label",
    "total_estimate",
    "total_margin_of_error",
    "total_percent_estimate",
    "total_percent_margin_of_error",
    "male_estimate",
    "male_margin_of_error",
    "male_percent_estimate",
    "male_percent_margin_of_error",
    "female_estimate",
    "female_margin_of_error",
    "female_percent_estimate",
    "female_percent_margin_of_error",
    "source_file",
]


def export_census_to_csv():
    out_path = os.path.join(OUTPUT_DIR, "census_education_attainment_2024.csv")

    if not os.path.exists(CENSUS_CSV):
        print(f"  [SKIP] Census CSV not found: {CENSUS_CSV}")
        return

    rows = []
    current_section = None

    with open(CENSUS_CSV, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=1):
            raw_label = row.get("Label (Grouping)", "")
            if not raw_label:
                continue

            level, label = _normalize_census_label(raw_label)
            data_cells = [v for k, v in row.items() if k != "Label (Grouping)"]

            if all((v or "").strip() == "" for v in data_cells):
                current_section = label
                continue

            rows.append(
                {
                    "row_order": row_num,
                    "section": current_section,
                    "label_level": level,
                    "label": label,
                    "total_estimate": _parse_census_number(
                        row.get("United States!!Total!!Estimate")
                    ),
                    "total_margin_of_error": _parse_census_number(
                        row.get("United States!!Total!!Margin of Error")
                    ),
                    "total_percent_estimate": _parse_census_number(
                        row.get("United States!!Percent!!Estimate")
                    ),
                    "total_percent_margin_of_error": _parse_census_number(
                        row.get("United States!!Percent!!Margin of Error")
                    ),
                    "male_estimate": _parse_census_number(
                        row.get("United States!!Male!!Estimate")
                    ),
                    "male_margin_of_error": _parse_census_number(
                        row.get("United States!!Male!!Margin of Error")
                    ),
                    "male_percent_estimate": _parse_census_number(
                        row.get("United States!!Percent Male!!Estimate")
                    ),
                    "male_percent_margin_of_error": _parse_census_number(
                        row.get("United States!!Percent Male!!Margin of Error")
                    ),
                    "female_estimate": _parse_census_number(
                        row.get("United States!!Female!!Estimate")
                    ),
                    "female_margin_of_error": _parse_census_number(
                        row.get("United States!!Female!!Margin of Error")
                    ),
                    "female_percent_estimate": _parse_census_number(
                        row.get("United States!!Percent Female!!Estimate")
                    ),
                    "female_percent_margin_of_error": _parse_census_number(
                        row.get("United States!!Percent Female!!Margin of Error")
                    ),
                    "source_file": os.path.basename(CENSUS_CSV),
                }
            )

    with open(out_path, "w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=CENSUS_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  -> {out_path}: {len(rows)} rows")


# ===========================================================================
# 3. Federal Reserve SHED → csv/fed_higher_ed_shed_2024.csv
# ===========================================================================


FED_HEADERS = [
    "source_name",
    "source_page",
    "source_url",
    "source_table_id",
    "source_table_title",
    "section_group",
    "category",
    "metric",
    "value_pct",
    "unit",
    "note",
    "fetched_at",
]


def export_fed_to_csv():
    out_path = os.path.join(OUTPUT_DIR, "fed_higher_ed_shed_2024.csv")

    print("  Fetching Federal Reserve SHED pages...")
    try:
        main_soup = _fetch_soup(FED_MAIN_URL)
        accessible_soup = _fetch_soup(FED_ACCESSIBLE_URL)
    except Exception as exc:
        print(f"  [SKIP] Federal Reserve data unavailable: {exc}")
        return

    specs = [
        dict(
            soup=main_soup,
            table_id="xa6270",
            table_title="Table 43. Educational attainment",
            source_page="higher_education_and_student_loans",
            source_url=FED_MAIN_URL,
            note="Among all adults",
        ),
        dict(
            soup=main_soup,
            table_id="xd7256",
            table_title="Table 44. Behind on student loan payments",
            source_page="higher_education_and_student_loans",
            source_url=FED_MAIN_URL,
            note="Among adults with outstanding student loans for own education",
        ),
        dict(
            soup=accessible_soup,
            table_id="03e312fa",
            table_title="Figure 34. Acquired student loans for own education",
            source_page="higher_education_and_student_loans",
            source_url=FED_ACCESSIBLE_URL,
            note="Among adults who attended an educational program beyond high school",
        ),
        dict(
            soup=accessible_soup,
            table_id="359fc80b",
            table_title="Figure 35. Share with at least $25,000 student loan debt",
            source_page="higher_education_and_student_loans",
            source_url=FED_ACCESSIBLE_URL,
            note="Among adults with outstanding student loans for own education",
        ),
    ]

    all_rows = []
    try:
        for spec in specs:
            all_rows.extend(_extract_fed_table(**spec))
    except Exception as exc:
        print(f"  [SKIP] Failed to extract Federal Reserve tables: {exc}")
        return

    with open(out_path, "w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=FED_HEADERS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  -> {out_path}: {len(all_rows)} rows")


# ===========================================================================
# Main
# ===========================================================================


def main():
    print("=" * 60)
    print("education_to_csv: exporting data sources to CSV")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\nOutput folder: {os.path.abspath(OUTPUT_DIR)}\n")

    print("[1/3] College Scorecard")
    export_scorecard_to_csv()

    print("\n[2/3] Census ACS S1501")
    export_census_to_csv()

    print("\n[3/3] Federal Reserve SHED")
    export_fed_to_csv()

    print("\nDone.")


if __name__ == "__main__":
    main()
