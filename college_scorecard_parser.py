import duckdb
import glob
import os
import re

from census_education_parser import parse_and_insert_census_education_csv
from fed_scraper import parse_fed_higher_ed_datapoints


def extract_year_from_filename(filename):
    """Extract the year from a MERGED filename like MERGED2023_24_PP.csv -> 2023_24"""
    match = re.search(r'MERGED(\d{4}_\d{2})_PP\.csv', filename)
    if match:
        return match.group(1)
    return None


def parse_and_insert_merged_files(db_path="data.duckdb", data_dir="datasets/college_scorecard"):
    """Parse MERGED*.csv files from 2020-2023 and insert into database with separate tables per year"""
    
    con = duckdb.connect(db_path)
    
    # Find all MERGED CSV files
    pattern = os.path.join(data_dir, "MERGED*_PP.csv")
    all_files = sorted(glob.glob(pattern))
    
    # Filter to only include years 2020-2023
    merged_files = [f for f in all_files if any(f"MERGED{year}" in f for year in ["2023_24"])]
    
    print(f"Found {len(merged_files)} MERGED files to process (2023-2024 only)")
    
    for filepath in merged_files:
        filename = os.path.basename(filepath)
        year = extract_year_from_filename(filename)
        
        if not year:
            print(f"Skipping {filename} - couldn't extract year")
            continue
        
        table_name = f"scorecard_{year}"
        print(f"Processing {filename} -> table '{table_name}'...")
        
        try:
            # DuckDB can read CSV directly and handles many columns easily
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
            con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{filepath}')")
            
            result = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            print(f"  Inserted {result[0]} rows")
            
        except Exception as e:
            print(f"  Error processing {filename}: {e}")
    
    con.close()
    print("\nDone! Database saved to", db_path)


def filter_na_columns(db_path="data.duckdb", table_name="scorecard_2023_24", 
                      na_threshold=0.5, output_table=None, keep_columns=None):
    """
    Filter out columns that have more than na_threshold proportion of NA values.
    
    Args:
        db_path: Path to the DuckDB database
        table_name: Name of the table to analyze
        na_threshold: Maximum proportion of NA values allowed (default 0.5 = 50%)
        output_table: Name for the filtered table (default: {table_name}_clean)
        keep_columns: List of column names to always keep regardless of NA ratio
    
    Returns:
        List of columns that were kept
    """
    con = duckdb.connect(db_path)
    
    if output_table is None:
        output_table = f"{table_name}_clean"
    
    if keep_columns is None:
        keep_columns = []
    
    # Get total row count
    total_rows = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"Table '{table_name}' has {total_rows} rows")
    
    # Get all column names
    columns = con.execute(f"DESCRIBE {table_name}").fetchall()
    column_names = [col[0] for col in columns]
    print(f"Total columns: {len(column_names)}")
    
    # Calculate NA percentage for each column
    kept_columns = []
    dropped_columns = []
    force_kept = []
    
    print(f"\nAnalyzing columns (threshold: {na_threshold*100:.0f}% NA)...")
    
    for col in column_names:
        # Count NULLs and empty strings
        query = f"""
            SELECT COUNT(*) as null_count 
            FROM {table_name} 
            WHERE "{col}" IS NULL 
               OR CAST("{col}" AS VARCHAR) IN ('NULL', 'PrivacySuppressed', 'NA', 'PS', '')
        """
        null_count = con.execute(query).fetchone()[0]
        na_ratio = null_count / total_rows
        
        if na_ratio <= na_threshold:
            kept_columns.append(col)
        elif col in keep_columns:
            kept_columns.append(col)
            force_kept.append((col, na_ratio))
        else:
            dropped_columns.append((col, na_ratio))
    
    if force_kept:
        print(f"\nForce-kept {len(force_kept)} columns despite high NA:")
        for col, ratio in force_kept:
            print(f"  {col}: {ratio*100:.1f}% NA")
    
    print(f"\nKept {len(kept_columns)} columns, dropped {len(dropped_columns)} columns")
    
    # Show some dropped columns with highest NA ratios
    if dropped_columns:
        dropped_columns.sort(key=lambda x: x[1], reverse=True)
        print("\nTop 10 dropped columns (by NA %):")
        for col, ratio in dropped_columns[:10]:
            print(f"  {col}: {ratio*100:.1f}% NA")
    
    # Create filtered table
    cols_sql = ', '.join([f'"{c}"' for c in kept_columns])
    con.execute(f"DROP TABLE IF EXISTS {output_table}")
    con.execute(f"CREATE TABLE {output_table} AS SELECT {cols_sql} FROM {table_name}")
    
    print(f"\nCreated filtered table '{output_table}' with {len(kept_columns)} columns")
    
    con.close()
    return kept_columns


def analyze_na_distribution(db_path="data.duckdb", table_name="scorecard_2023_24"):
    """Show distribution of NA percentages across all columns"""
    con = duckdb.connect(db_path)
    
    total_rows = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    columns = con.execute(f"DESCRIBE {table_name}").fetchall()
    column_names = [col[0] for col in columns]
    
    na_ratios = []
    for col in column_names:
        query = f"""
            SELECT COUNT(*) FROM {table_name} 
            WHERE "{col}" IS NULL 
               OR CAST("{col}" AS VARCHAR) IN ('NULL', 'PrivacySuppressed', 'NA', 'PS', '')
        """
        null_count = con.execute(query).fetchone()[0]
        na_ratios.append(null_count / total_rows)
    
    con.close()
    
    # Distribution buckets
    buckets = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    print(f"\nNA Distribution for '{table_name}':")
    print("-" * 40)
    for i in range(len(buckets) - 1):
        count = sum(1 for r in na_ratios if buckets[i] <= r < buckets[i+1])
        print(f"  {buckets[i]*100:3.0f}% - {buckets[i+1]*100:3.0f}% NA: {count} columns")
    count_100 = sum(1 for r in na_ratios if r == 1.0)
    print(f"  100% NA (all null): {count_100} columns")
    
    return na_ratios


def export_to_postgres(db_path="data.duckdb", 
                       pg_host="localhost", pg_port=5432,
                       pg_user="postgres", pg_password="test", 
                       pg_database="postgres",
                       tables=None):
    """
    Export tables from DuckDB to PostgreSQL for use with Metabase.
    
    Args:
        db_path: Path to DuckDB database
        pg_host: PostgreSQL host
        pg_port: PostgreSQL port  
        pg_user: PostgreSQL username
        pg_password: PostgreSQL password
        pg_database: PostgreSQL database name
        tables: List of table names to export (None = all tables)
    """
    con = duckdb.connect(db_path)
    
    # Install and load postgres extension
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    
    # Create connection string
    pg_conn = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
    
    # Attach PostgreSQL database
    con.execute(f"ATTACH '{pg_conn}' AS pg (TYPE POSTGRES)")
    
    # Get list of tables to export
    if tables is None:
        result = con.execute("SHOW TABLES").fetchall()
        tables = [row[0] for row in result]
    
    print(f"Exporting {len(tables)} tables to PostgreSQL...")
    
    for table in tables:
        print(f"  Exporting '{table}'...")
        try:
            # Drop if exists and create new
            con.execute(f"DROP TABLE IF EXISTS pg.{table}")
            con.execute(f"CREATE TABLE pg.{table} AS SELECT * FROM {table}")
            
            # Verify row count
            count = con.execute(f"SELECT COUNT(*) FROM pg.{table}").fetchone()[0]
            print(f"    -> {count} rows exported")
        except Exception as e:
            print(f"    Error: {e}")
    
    con.close()
    print("\nDone! Data exported to PostgreSQL")


if __name__ == "__main__":
    # Columns to always keep for graduation by race analysis
    GRADUATION_COLUMNS = [
        "C150_4", "C150_4_WHITE", "C150_4_BLACK", "C150_4_HISP", 
        "C150_4_ASIAN", "C150_4_AIAN", "C150_4_NHPI", "C150_4_2MOR",
        "C150_4_NRA", "C150_4_UNKN",
        "C150_4_PELL", "D150_4_PELL",
        "C150_4_LOANNOPELL", "D150_4_LOANNOPELL",
        "C150_4_NOLOANNOPELL", "D150_4_NOLOANNOPELL",
        "FEMALE_COMP_ORIG_YR6_RT", "FEMALE_COMP_4YR_TRANS_YR6_RT", "FEMALE_COMP_2YR_TRANS_YR6_RT",
        "MALE_COMP_ORIG_YR6_RT", "MALE_COMP_4YR_TRANS_YR6_RT", "MALE_COMP_2YR_TRANS_YR6_RT",
        "FEMALE_YR6_N", "MALE_YR6_N"
    ]
    
    parse_and_insert_merged_files()
    parse_and_insert_census_education_csv()
    parse_fed_higher_ed_datapoints()
    
    # Analyze NA distribution
    analyze_na_distribution()
    
    # Filter columns with >50% NA values, but keep graduation columns
    filter_na_columns(na_threshold=0.5, keep_columns=GRADUATION_COLUMNS)
    
    # Export cleaned data to PostgreSQL for Metabase
    export_to_postgres(tables=["scorecard_2023_24_clean", "census_education_attainment_2024", "fed_higher_ed_shed_2024"])