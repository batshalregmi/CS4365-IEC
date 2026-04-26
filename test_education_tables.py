"""
Local end-to-end test for education IEC tables.
Creates tables, inserts CSVs, then validates row counts, decimal precision,
empty-cell counts, and value ranges against the source CSVs.
"""

import csv
import re
import sys
import mysql.connector

# ── connection ──────────────────────────────────────────────────────────────
DB = dict(user='norpuser', password='testpass', host='127.0.0.1',
          port=3307, database='norp', auth_plugin='mysql_native_password')

SQL_FILE   = r'norp-data-integration\sql_scripts\create_tables\create_scorecard_fed_census.sql'
CSV_SCORECARD = r'csv\scorecard_clean.csv'
CSV_CENSUS    = r'csv\census_education_attainment_2024.csv'
CSV_FED       = r'csv\fed_higher_ed_shed_2024.csv'

TABLES = {
    'education_scorecard':            CSV_SCORECARD,
    'census_education_attainment_2024': CSV_CENSUS,
    'fed_higher_ed_shed_2024':         CSV_FED,
}

# columns that should be DECIMAL in education_scorecard
DECIMAL_COLS = {
    'overall_completion_rate','white_completion_rate','black_completion_rate',
    'hispanic_completion_rate','asian_completion_rate',
    'native_american_completion_rate','pacific_islander_completion_rate',
    'two_or_more_races_completion_rate','nonresident_alien_completion_rate',
    'unknown_race_completion_rate','pell_completion_rate',
    'nonpell_loan_completion_rate','nonpell_noloan_completion_rate',
    'pell_share','undergrad_share_men','undergrad_share_women',
    'admission_rate','retention_rate_fulltime','retention_rate_parttime',
    'federal_loan_share','first_time_fulltime_pell_share',
}

INT_COLS = {
    'pell_cohort_count','nonpell_loan_cohort_count','nonpell_noloan_cohort_count',
    'in_state_tuition','student_faculty_ratio','undergrad_enrollment',
    'sat_verbal_midpoint','sat_math_midpoint','act_composite_midpoint',
    'avg_books_supplies_cost','avg_room_board_on_campus',
}

PASS = '\033[92mPASS\033[0m'
FAIL = '\033[91mFAIL\033[0m'
failures = []

def check(label, condition, detail=''):
    if condition:
        print(f'  {PASS}  {label}')
    else:
        print(f'  {FAIL}  {label}' + (f'  →  {detail}' if detail else ''))
        failures.append(label)

# ── helpers ──────────────────────────────────────────────────────────────────
def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)

def coerce(val, col):
    """Return (ok, coerced_value) — ok=False means the value can't fit the declared type."""
    if val == '':
        return True, None          # NULL — always fine
    if col in DECIMAL_COLS:
        try:
            float(val)
            return True, float(val)
        except ValueError:
            return False, val
    if col in INT_COLS:
        try:
            int(float(val))
            return True, int(float(val))
        except ValueError:
            return False, val
    return True, val               # VARCHAR — always fine

def create_tables(conn):
    cursor = conn.cursor()
    with open(SQL_FILE, encoding='utf-8') as f:
        sql = f.read()
    for stmt in sql.split(';'):
        stmt = stmt.strip()
        if stmt:
            cursor.execute(stmt)
    conn.commit()
    cursor.close()

def insert_csv(conn, csv_path, table_name):
    rows = read_csv(csv_path)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ', '.join(['%s'] * len(cols))
    col_list     = ', '.join(f'`{c}`' for c in cols)
    sql = f'INSERT INTO `{table_name}` ({col_list}) VALUES ({placeholders})'
    cursor = conn.cursor()
    inserted = 0
    for row in rows:
        values = []
        for col in cols:
            raw = row[col]
            ok, val = coerce(raw, col)
            values.append(val)
        cursor.execute(sql, values)
        inserted += 1
    conn.commit()
    cursor.close()
    return inserted

# ── main ─────────────────────────────────────────────────────────────────────
print('\nConnecting to local MySQL …')
conn = mysql.connector.connect(**DB)
print('Connected.\n')

# 1. create tables
print('=== CREATE TABLES ===')
try:
    create_tables(conn)
    check('create_tables ran without error', True)
except Exception as e:
    check('create_tables ran without error', False, str(e))
    sys.exit(1)

# 2. insert & validate each table
for table, csv_path in TABLES.items():
    print(f'\n=== {table} ===')

    # load source CSV
    source_rows = read_csv(csv_path)
    source_count = len(source_rows)

    # insert
    try:
        inserted = insert_csv(conn, csv_path, table)
        check(f'insert completed ({inserted} rows)', True)
    except Exception as e:
        check('insert completed', False, str(e))
        continue

    # 2a. row count matches source
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM `{table}`')
    db_count = cur.fetchone()[0]
    cur.close()
    check(f'row count: CSV={source_count} DB={db_count}',
          db_count == source_count,
          f'mismatch: {db_count} in DB vs {source_count} in CSV')

    # 2b. no unexpected NULLs — flag any column where DB NULLs > CSV empty cells
    cur = conn.cursor()
    cur.execute(f'SHOW COLUMNS FROM `{table}`')
    db_cols = [row[0] for row in cur.fetchall()]
    cur.close()

    null_issues = []
    for col in db_cols:
        # count empty strings in CSV
        csv_empty = sum(1 for r in source_rows if r.get(col, '') == '')
        # count NULLs in DB
        cur = conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM `{table}` WHERE `{col}` IS NULL')
        db_nulls = cur.fetchone()[0]
        cur.close()
        if db_nulls != csv_empty:
            null_issues.append(f'{col}: csv_empty={csv_empty} db_null={db_nulls}')
    check('NULL counts match empty cells in source CSV',
          len(null_issues) == 0,
          '; '.join(null_issues) if null_issues else '')

    # 2c. decimal type-coercion check (scorecard only)
    if table == 'education_scorecard':
        bad_vals = []
        for col in DECIMAL_COLS | INT_COLS:
            for row in source_rows:
                raw = row.get(col, '')
                ok, _ = coerce(raw, col)
                if not ok:
                    bad_vals.append(f'{col}="{raw}"')
        check('all numeric CSV values are valid numbers (or empty)',
              len(bad_vals) == 0,
              f'{len(bad_vals)} bad value(s): ' + ', '.join(bad_vals[:5]))

        # 2d. decimal range check — rates/shares should be 0–1 (ignoring NULLs)
        out_of_range = []
        for col in DECIMAL_COLS:
            cur = conn.cursor()
            cur.execute(f'SELECT MIN(`{col}`), MAX(`{col}`) FROM `{table}`')
            mn, mx = cur.fetchone()
            cur.close()
            if mn is not None and (float(mn) < 0 or float(mx) > 1):
                out_of_range.append(f'{col}: [{mn}, {mx}]')
        check('all rate/share columns in [0, 1]',
              len(out_of_range) == 0,
              '; '.join(out_of_range) if out_of_range else '')

        # 2e. spot-check a single known row from CSV vs DB
        sample = source_rows[0]
        sid = sample['institution_id']
        cur = conn.cursor(dictionary=True)
        cur.execute(f'SELECT * FROM `{table}` WHERE institution_id = %s', (sid,))
        db_row = cur.fetchone()
        cur.close()
        mismatches = []
        for col in db_cols:
            raw = sample.get(col, '')
            db_val = db_row.get(col)
            ok, expected = coerce(raw, col)
            # compare as strings for NULLs and numbers
            csv_repr = str(expected) if expected is not None else None
            db_repr  = str(db_val)   if db_val  is not None else None
            if col in DECIMAL_COLS and expected is not None and db_val is not None:
                if abs(float(expected) - float(db_val)) > 1e-6:
                    mismatches.append(f'{col}: csv={expected} db={db_val}')
            elif col in INT_COLS and expected is not None and db_val is not None:
                if int(expected) != int(db_val):
                    mismatches.append(f'{col}: csv={expected} db={db_val}')
            elif csv_repr != db_repr:
                mismatches.append(f'{col}: csv={csv_repr!r} db={db_repr!r}')
        check(f'spot-check first row (institution_id={sid}) matches DB',
              len(mismatches) == 0,
              '; '.join(mismatches) if mismatches else '')

conn.close()

print('\n' + '='*50)
if failures:
    print(f'\033[91m{len(failures)} check(s) FAILED:\033[0m')
    for f in failures:
        print(f'  - {f}')
    sys.exit(1)
else:
    print('\033[92mAll checks passed.\033[0m')
