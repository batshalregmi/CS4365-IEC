"""
pipeline.py - Consolidated data cleaning and analysis pipeline.

Replaces the functionality of:
  - census_education_parser.py
  - fed_scraper.py
  - college_scorecard_parser.py

Ingests raw data, cleans it, renames columns to human-friendly names,
stores everything in DuckDB, exports to PostgreSQL for Metabase, and
prints 18 ready-to-use SQL queries (PostgreSQL syntax) for analysis.

Usage:
    python pipeline.py
"""

import csv
import glob
import os
import re
from datetime import datetime, timezone

import duckdb
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = "data.duckdb"
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

PG_HOST = "localhost"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = "test"
PG_DATABASE = "postgres"

# Scorecard columns we keep, mapped to human-friendly names.
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
SCORECARD_NA_VALUES = ("NULL", "PrivacySuppressed", "NA", "PS", "")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Census Education Attainment Parser
# ═══════════════════════════════════════════════════════════════════════════


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


def ingest_census(
    con: duckdb.DuckDBPyConnection, table: str = "census_education_attainment_2024"
):
    """Parse the ACS S1501 CSV into a normalized DuckDB table."""
    if not os.path.exists(CENSUS_CSV):
        print(f"  Census CSV not found: {CENSUS_CSV}")
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

            # Section headers have no data.
            if all((v or "").strip() == "" for v in data_cells):
                current_section = label
                continue

            rows.append(
                (
                    row_num,
                    current_section,
                    level,
                    label,
                    _parse_census_number(row.get("United States!!Total!!Estimate")),
                    _parse_census_number(
                        row.get("United States!!Total!!Margin of Error")
                    ),
                    _parse_census_number(row.get("United States!!Percent!!Estimate")),
                    _parse_census_number(
                        row.get("United States!!Percent!!Margin of Error")
                    ),
                    _parse_census_number(row.get("United States!!Male!!Estimate")),
                    _parse_census_number(
                        row.get("United States!!Male!!Margin of Error")
                    ),
                    _parse_census_number(
                        row.get("United States!!Percent Male!!Estimate")
                    ),
                    _parse_census_number(
                        row.get("United States!!Percent Male!!Margin of Error")
                    ),
                    _parse_census_number(row.get("United States!!Female!!Estimate")),
                    _parse_census_number(
                        row.get("United States!!Female!!Margin of Error")
                    ),
                    _parse_census_number(
                        row.get("United States!!Percent Female!!Estimate")
                    ),
                    _parse_census_number(
                        row.get("United States!!Percent Female!!Margin of Error")
                    ),
                    os.path.basename(CENSUS_CSV),
                )
            )

    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"""
        CREATE TABLE {table} (
            row_order                    INTEGER,
            section                      VARCHAR,
            label_level                  INTEGER,
            label                        VARCHAR,
            total_estimate               BIGINT,
            total_margin_of_error        BIGINT,
            total_percent_estimate       DOUBLE,
            total_percent_margin_of_error DOUBLE,
            male_estimate                BIGINT,
            male_margin_of_error         BIGINT,
            male_percent_estimate        DOUBLE,
            male_percent_margin_of_error DOUBLE,
            female_estimate              BIGINT,
            female_margin_of_error       BIGINT,
            female_percent_estimate      DOUBLE,
            female_percent_margin_of_error DOUBLE,
            source_file                  VARCHAR
        )
    """)
    if rows:
        con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * 17)})", rows)

    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  census_education_attainment_2024: {count} rows")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Federal Reserve SHED Scraper
# ═══════════════════════════════════════════════════════════════════════════


def _clean_text(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\xa0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")  # en-dash, em-dash
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
    """Scrape a single Fed HTML table into a list of row tuples."""
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
                (
                    "fed_shed_2024",
                    source_page,
                    source_url,
                    table_id,
                    table_title,
                    current_group,
                    stub_text,
                    metric,
                    value,
                    "percent",
                    note,
                    fetched_at,
                )
            )
    return rows


def ingest_fed(con: duckdb.DuckDBPyConnection, table: str = "fed_higher_ed_shed_2024"):
    """Scrape Fed SHED higher-education tables and store in DuckDB."""
    print("  Fetching Federal Reserve SHED pages...")
    main_soup = _fetch_soup(FED_MAIN_URL)
    accessible_soup = _fetch_soup(FED_ACCESSIBLE_URL)

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
    for spec in specs:
        all_rows.extend(_extract_fed_table(**spec))

    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"""
        CREATE TABLE {table} (
            source_name         VARCHAR,
            source_page         VARCHAR,
            source_url          VARCHAR,
            source_table_id     VARCHAR,
            source_table_title  VARCHAR,
            section_group       VARCHAR,
            category            VARCHAR,
            metric              VARCHAR,
            value_pct           DOUBLE,
            unit                VARCHAR,
            note                VARCHAR,
            fetched_at          TIMESTAMP
        )
    """)
    if all_rows:
        con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * 12)})", all_rows)

    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  fed_higher_ed_shed_2024: {count} rows")


# ═══════════════════════════════════════════════════════════════════════════
# 3. College Scorecard Ingestion (filtered + renamed)
# ═══════════════════════════════════════════════════════════════════════════


def ingest_scorecard(con: duckdb.DuckDBPyConnection, table: str = "scorecard_clean"):
    """Load MERGED2023_24 CSV, keep only needed columns, rename to friendly names."""
    pattern = os.path.join(SCORECARD_DIR, "MERGED2023_24_PP.csv")
    files = glob.glob(pattern)
    if not files:
        print(f"  Scorecard CSV not found: {pattern}")
        return

    filepath = files[0]
    print(f"  Reading {os.path.basename(filepath)}...")

    # Load full CSV into a temporary table.
    con.execute("DROP TABLE IF EXISTS _scorecard_raw")
    con.execute(
        f"CREATE TABLE _scorecard_raw AS SELECT * FROM read_csv_auto('{filepath}')"
    )

    # Build SELECT with renames, keeping only the columns we need.
    select_parts = []
    for original, friendly in SCORECARD_COLUMN_MAP.items():
        select_parts.append(f'"{original}" AS {friendly}')

    cols_sql = ",\n        ".join(select_parts)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(
        f"CREATE TABLE {table} AS SELECT\n        {cols_sql}\n    FROM _scorecard_raw"
    )
    con.execute("DROP TABLE IF EXISTS _scorecard_raw")

    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    col_count = len(con.execute(f"DESCRIBE {table}").fetchall())
    print(f"  scorecard_clean: {count} rows, {col_count} columns")


# ═══════════════════════════════════════════════════════════════════════════
# 4. PostgreSQL Export
# ═══════════════════════════════════════════════════════════════════════════

EXPORT_TABLES = [
    "scorecard_clean",
    "census_education_attainment_2024",
    "fed_higher_ed_shed_2024",
]


def export_to_postgres(con: duckdb.DuckDBPyConnection, tables=None):
    """Push DuckDB tables to PostgreSQL for Metabase consumption."""
    if tables is None:
        tables = EXPORT_TABLES

    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")

    pg_conn = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    con.execute(f"ATTACH '{pg_conn}' AS pg (TYPE POSTGRES)")

    for table in tables:
        try:
            con.execute(f"DROP TABLE IF EXISTS pg.{table}")
            con.execute(f"CREATE TABLE pg.{table} AS SELECT * FROM {table}")
            count = con.execute(f"SELECT COUNT(*) FROM pg.{table}").fetchone()[0]
            print(f"  -> pg.{table}: {count} rows")
        except Exception as exc:
            print(f"  -> pg.{table}: ERROR - {exc}")



# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("Pipeline: ingest, clean, rename, export")
    print("=" * 60)

    con = duckdb.connect(DB_PATH)

    # --- Ingest ---
    print("\n[1/3] Ingesting data sources...")
    ingest_scorecard(con)
    ingest_census(con)
    ingest_fed(con)

    # --- Summary ---
    print("\n[2/3] Database tables:")
    for row in con.execute("SHOW TABLES").fetchall():
        t = row[0]
        cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols = len(con.execute(f"DESCRIBE {t}").fetchall())
        print(f"  {t}: {cnt} rows, {cols} columns")

    # --- Export ---
    print("\n[3/3] Exporting to PostgreSQL...")
    try:
        export_to_postgres(con)
    except Exception as exc:
        print(f"  PostgreSQL export skipped: {exc}")

    con.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
