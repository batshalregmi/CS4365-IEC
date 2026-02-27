import duckdb
import glob
import os
import re


def extract_year_from_filename(filename):
    """Extract the year from a MERGED filename like MERGED2023_24_PP.csv -> 2023_24"""
    match = re.search(r'MERGED(\d{4}_\d{2})_PP\.csv', filename)
    if match:
        return match.group(1)
    return None


def parse_and_insert_merged_files(db_path="data.duckdb", data_dir="datasets/college_scorecard"):
    """Parse all MERGED*.csv files and insert into database with separate tables per year"""
    
    con = duckdb.connect(db_path)
    
    # Find all MERGED CSV files
    pattern = os.path.join(data_dir, "MERGED*_PP.csv")
    merged_files = sorted(glob.glob(pattern))
    
    print(f"Found {len(merged_files)} MERGED files to process")
    
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


if __name__ == "__main__":
    parse_and_insert_merged_files()