#!/usr/bin/env python3
"""Stream a CSV or CSV.GZ civic grievance file into CityMemory's SQLite database.

Usage:
  python tools/etl/import_civic_grievances.py
  python tools/etl/import_civic_grievances.py path/to/another-file.csv.gz

The raw source file is never modified. Complaint IDs are unique; rerunning the
import skips records already present. Historical rows without GPS remain ward-level.
"""
from __future__ import annotations
import csv, gzip, json, sqlite3, sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "datasets" / "imports" / "citizen-grievances.csv.gz"
DB_PATH = ROOT / "citymemory.db"
BATCH_SIZE = 10000

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS civic_grievances (
    complaint_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    sub_category TEXT NOT NULL,
    grievance_date_raw TEXT NOT NULL,
    grievance_date_valid INTEGER NOT NULL DEFAULT 0,
    zone_name TEXT,
    ward_name TEXT NOT NULL,
    grievance_mode TEXT,
    grievance_status TEXT NOT NULL,
    staff_remarks TEXT,
    staff_designation TEXT,
    rating REAL,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL
)
"""

def clean(value):
    value = (value or "").strip()
    return value if value and value.lower() not in {"nan", "none", "null", "-select-"} else None

def date_is_plausible(raw):
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return int(2010 <= dt.year <= 2035)
    except (ValueError, TypeError):
        return 0

def open_text(path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")

def main():
    source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_file():
        raise SystemExit(f"Dataset not found: {source}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(CREATE_SQL)
    con.commit()
    inserted = skipped = 0
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    sql = """INSERT OR IGNORE INTO civic_grievances
      (complaint_id,category,sub_category,grievance_date_raw,grievance_date_valid,
       zone_name,ward_name,grievance_mode,grievance_status,staff_remarks,
       staff_designation,rating,source_file,imported_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    batch = []
    try:
        with open_text(source) as handle:
            reader = csv.DictReader(handle)
            required = {"Complaint ID","Category","Sub Category","Grievance Date","Ward Name","Grievance Status"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise SystemExit("Missing required source columns: " + ", ".join(sorted(missing)))
            for row in reader:
                complaint_id = clean(row.get("Complaint ID"))
                if not complaint_id:
                    skipped += 1
                    continue
                raw_date = clean(row.get("Grievance Date")) or ""
                rating_text = clean(row.get("Rating"))
                try:
                    rating = float(rating_text) if rating_text is not None else None
                except ValueError:
                    rating = None
                batch.append((
                    complaint_id, clean(row.get("Category")) or "Uncategorised",
                    clean(row.get("Sub Category")) or "Unspecified",
                    raw_date, date_is_plausible(raw_date),
                    clean(row.get("Zone Name")), clean(row.get("Ward Name")) or "Unknown ward",
                    clean(row.get("Grievance Mode")), clean(row.get("Grievance Status")) or "Unknown",
                    clean(row.get("Staff Remarks")), clean(row.get("Staff Designation")),
                    rating, source.name, stamp
                ))
                if len(batch) >= BATCH_SIZE:
                    before = con.total_changes
                    con.executemany(sql, batch)
                    inserted += con.total_changes - before
                    skipped += len(batch) - (con.total_changes - before)
                    con.commit()
                    batch.clear()
            if batch:
                before = con.total_changes
                con.executemany(sql, batch)
                inserted += con.total_changes - before
                skipped += len(batch) - (con.total_changes - before)
                con.commit()
        con.executescript("""
          CREATE INDEX IF NOT EXISTS idx_civic_ward ON civic_grievances(ward_name);
          CREATE INDEX IF NOT EXISTS idx_civic_category ON civic_grievances(category);
          CREATE INDEX IF NOT EXISTS idx_civic_subcategory ON civic_grievances(sub_category);
          CREATE INDEX IF NOT EXISTS idx_civic_date ON civic_grievances(grievance_date_raw);
          CREATE INDEX IF NOT EXISTS idx_civic_status ON civic_grievances(grievance_status);
        """)
        total = con.execute("SELECT COUNT(*) FROM civic_grievances").fetchone()[0]
        valid_dates = con.execute("SELECT COUNT(*) FROM civic_grievances WHERE grievance_date_valid=1").fetchone()[0]
        wards = con.execute("SELECT COUNT(DISTINCT ward_name) FROM civic_grievances").fetchone()[0]
        print(f"Import complete. Newly inserted: {inserted:,}; skipped/already present: {skipped:,}")
        print(f"Database total: {total:,}; plausible dates (2010–2035): {valid_dates:,}; wards: {wards:,}")
        print(f"Database: {DB_PATH}")
    finally:
        con.close()

if __name__ == "__main__":
    main()
