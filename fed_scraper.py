from datetime import datetime, timezone

import duckdb
import requests
from bs4 import BeautifulSoup


MAIN_URL = "https://www.federalreserve.gov/publications/2025-economic-well-being-of-us-households-in-2024-higher-education-and-student-loans.htm"
ACCESSIBLE_URL = "https://www.federalreserve.gov/publications/2025-economic-well-being-of-us-households-in-2024-accessibility-tables.htm"


def _clean_text(text):
	if text is None:
		return ""
	return " ".join(text.replace("\xa0", " ").split())


def _to_float(value):
	cleaned = _clean_text(value).replace("%", "")
	if not cleaned or cleaned in {"-", "N/A"}:
		return None
	try:
		return float(cleaned)
	except ValueError:
		return None


def _fetch_soup(url):
	response = requests.get(url, timeout=60)
	response.raise_for_status()
	return BeautifulSoup(response.text, "html.parser")


def _extract_table_rows(soup, table_id, table_title, source_url, source_page, note):
	table = soup.find("table", id=table_id)
	if table is None:
		raise ValueError(f"Table with id '{table_id}' not found")

	header_cells = table.select("thead th")
	headers = [_clean_text(cell.get_text()) for cell in header_cells]

	rows = []
	current_group = None
	fetched_at = datetime.now(timezone.utc).isoformat()

	for row in table.select("tbody tr"):
		stub = row.find("th")
		if stub is None:
			continue

		stub_text = _clean_text(stub.get_text())
		data_cells = row.find_all("td")

		# Section rows in these Fed tables have no numeric cells.
		if len(data_cells) == 0:
			current_group = stub_text
			continue

		for idx, cell in enumerate(data_cells):
			metric = headers[idx + 1] if idx + 1 < len(headers) else f"series_{idx + 1}"
			value = _to_float(cell.get_text())
			if value is None:
				continue

			rows.append((
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
			))

	return rows


def parse_fed_higher_ed_datapoints(
	db_path="data.duckdb",
	table_name="fed_higher_ed_shed_2024",
):
	"""Scrape Fed SHED higher-education tables/figures and store them in DuckDB."""
	main_soup = _fetch_soup(MAIN_URL)
	accessible_soup = _fetch_soup(ACCESSIBLE_URL)

	dataset_specs = [
		{
			"soup": main_soup,
			"table_id": "xa6270",
			"table_title": "Table 43. Educational attainment",
			"source_page": "higher_education_and_student_loans",
			"source_url": MAIN_URL,
			"note": "Among all adults",
		},
		{
			"soup": main_soup,
			"table_id": "xd7256",
			"table_title": "Table 44. Behind on student loan payments",
			"source_page": "higher_education_and_student_loans",
			"source_url": MAIN_URL,
			"note": "Among adults with outstanding student loans for own education",
		},
		{
			"soup": accessible_soup,
			"table_id": "03e312fa",
			"table_title": "Figure 34. Acquired student loans for own education",
			"source_page": "higher_education_and_student_loans",
			"source_url": ACCESSIBLE_URL,
			"note": "Among adults who attended an educational program beyond high school",
		},
		{
			"soup": accessible_soup,
			"table_id": "359fc80b",
			"table_title": "Figure 35. Share with at least $25,000 student loan debt",
			"source_page": "higher_education_and_student_loans",
			"source_url": ACCESSIBLE_URL,
			"note": "Among adults with outstanding student loans for own education",
		},
	]

	all_rows = []
	for spec in dataset_specs:
		rows = _extract_table_rows(
			spec["soup"],
			spec["table_id"],
			spec["table_title"],
			spec["source_url"],
			spec["source_page"],
			spec["note"],
		)
		all_rows.extend(rows)

	con = duckdb.connect(db_path)
	con.execute(f"DROP TABLE IF EXISTS {table_name}")
	con.execute(
		f"""
		CREATE TABLE {table_name} (
			source_name VARCHAR,
			source_page VARCHAR,
			source_url VARCHAR,
			source_table_id VARCHAR,
			source_table_title VARCHAR,
			section_group VARCHAR,
			category VARCHAR,
			metric VARCHAR,
			value_pct DOUBLE,
			unit VARCHAR,
			note VARCHAR,
			fetched_at TIMESTAMP
		)
		"""
	)

	if all_rows:
		con.executemany(
			f"""
			INSERT INTO {table_name} VALUES
			(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""",
			all_rows,
		)

	count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
	con.close()
	print(f"Inserted {count} rows into '{table_name}'")


if __name__ == "__main__":
	parse_fed_higher_ed_datapoints()
