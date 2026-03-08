import csv
import os

import duckdb


def parse_census_number(value):
    """Convert Census numeric strings like 31,270,959, 11.6%, or ±48,363 into numbers."""
    if value is None:
        return None

    cleaned = value.strip().replace(',', '').replace('%', '').replace('±', '')
    if not cleaned or cleaned == '(X)':
        return None

    try:
        if '.' in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None


def normalize_census_label(label):
    """Extract indentation level and cleaned label text from the ACS grouping label."""
    normalized = label.replace('\xa0', ' ')
    indent = len(normalized) - len(normalized.lstrip())
    level = indent // 4
    return level, normalized.strip()


def parse_and_insert_census_education_csv(
    db_path="data.duckdb",
    csv_path="ACSST1Y2024.S1501-2026-03-07T044644.csv",
    table_name="census_education_attainment_2024",
):
    """Parse the ACS S1501 education attainment CSV into a normalized DuckDB table."""
    if not os.path.exists(csv_path):
        print(f"Census CSV not found: {csv_path}")
        return

    rows = []
    current_section = None

    with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)

        for row_number, row in enumerate(reader, start=1):
            raw_label = row.get("Label (Grouping)", "")
            if not raw_label:
                continue

            level, label = normalize_census_label(raw_label)
            data_cells = [value for key, value in row.items() if key != "Label (Grouping)"]

            if all((value or "").strip() == "" for value in data_cells):
                current_section = label
                continue

            rows.append((
                row_number,
                current_section,
                level,
                label,
                parse_census_number(row.get("United States!!Total!!Estimate")),
                parse_census_number(row.get("United States!!Total!!Margin of Error")),
                parse_census_number(row.get("United States!!Percent!!Estimate")),
                parse_census_number(row.get("United States!!Percent!!Margin of Error")),
                parse_census_number(row.get("United States!!Male!!Estimate")),
                parse_census_number(row.get("United States!!Male!!Margin of Error")),
                parse_census_number(row.get("United States!!Percent Male!!Estimate")),
                parse_census_number(row.get("United States!!Percent Male!!Margin of Error")),
                parse_census_number(row.get("United States!!Female!!Estimate")),
                parse_census_number(row.get("United States!!Female!!Margin of Error")),
                parse_census_number(row.get("United States!!Percent Female!!Estimate")),
                parse_census_number(row.get("United States!!Percent Female!!Margin of Error")),
                os.path.basename(csv_path),
            ))

    con = duckdb.connect(db_path)
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.execute(
        f"""
        CREATE TABLE {table_name} (
            row_order INTEGER,
            section VARCHAR,
            label_level INTEGER,
            label VARCHAR,
            total_estimate BIGINT,
            total_margin_of_error BIGINT,
            total_percent_estimate DOUBLE,
            total_percent_margin_of_error DOUBLE,
            male_estimate BIGINT,
            male_margin_of_error BIGINT,
            male_percent_estimate DOUBLE,
            male_percent_margin_of_error DOUBLE,
            female_estimate BIGINT,
            female_margin_of_error BIGINT,
            female_percent_estimate DOUBLE,
            female_percent_margin_of_error DOUBLE,
            source_file VARCHAR
        )
        """
    )

    if rows:
        con.executemany(
            f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    inserted_rows = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    con.close()
    print(f"Inserted {inserted_rows} rows into '{table_name}'")