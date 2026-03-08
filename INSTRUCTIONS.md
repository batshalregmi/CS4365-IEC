# Project Setup

## Overview

This project loads College Scorecard data and a Census education CSV into DuckDB, then exports queryable tables to PostgreSQL for use in Metabase.

Main files:

- `college_scorecard_parser.py`: main pipeline entry point
- `census_education_parser.py`: Census CSV parser
- `data.duckdb`: local DuckDB database created by the pipeline
- `docker-compose.yml`: PostgreSQL and Metabase services

## Requirements

- Python 3.10+ recommended
- Docker Desktop running
- The dataset files already present in the repository

Python dependency:

- `duckdb`

Install it with:

```bash
pip install -r requirements.txt
```

## Fresh Start

If you want to reset the local database and containers:

```bash
docker compose down
rm -rf timescale_data
rm -f data.duckdb
```

## Start PostgreSQL and Metabase

Run:

```bash
docker compose up -d
```

Services:

- PostgreSQL: `localhost:5432`
- Metabase: `http://localhost:3001`

If Metabase has trouble starting on a fresh reset, create its metadata database manually:

```bash
docker exec timescale psql -U postgres -c "CREATE DATABASE metabase;"
```

## Run the Data Pipeline

Run:

```bash
python college_scorecard_parser.py
```

What this does:

1. Loads the `MERGED2023_24_PP.csv` College Scorecard file into DuckDB as `scorecard_2023_24`
2. Loads the Census CSV into DuckDB as `census_education_attainment_2024`
3. Creates a filtered table `scorecard_2023_24_clean`
4. Force-keeps analysis columns such as race, Pell, and selected gender-related fields
5. Exports `scorecard_2023_24_clean` and `census_education_attainment_2024` to PostgreSQL

## Verify the Export

Check available PostgreSQL tables:

```bash
docker exec timescale psql -U postgres -d postgres -c "\dt"
```

Expected tables:

- `scorecard_2023_24_clean`
- `census_education_attainment_2024`

## Connect Metabase

Open `http://localhost:3001` and add a PostgreSQL connection with:

- Host: `timescale`
- Port: `5432`
- Database: `postgres`
- Username: `postgres`
- Password: `test`

Important:

- Metabase stores its own metadata in the separate `metabase` database
- Your queryable project data is in the `postgres` database

## Common Issues

`docker compose up -d` fails with a mount error:

- Make sure `docker-compose.yml` does not try to mount `data.duckdb` into the container

Parser runs but Metabase cannot find tables:

- Confirm the tables exist with `\dt` in PostgreSQL
- Confirm Metabase is connected to database `postgres`, not `metabase`

Query returns no rows for a metric:

- Some Scorecard columns exist but contain only `NA` in the 2023-24 file
- In that case, the table schema is correct but the source data does not contain usable numeric values
