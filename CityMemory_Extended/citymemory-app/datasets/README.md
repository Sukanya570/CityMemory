# CityMemory datasets

## Supplied source: citizen-grievances.csv.gz

This compressed CSV is the original user-provided source. Do not edit it in place.
The inspection profile is in `imports/citizen-grievances-profile.json`.

Observed schema:
- Complaint ID
- Category
- Sub Category
- Grievance Date
- Zone Name
- Ward Name
- Grievance Mode
- Grievance Status
- Staff Remarks
- Staff Name
- Staff Designation
- Rating

Important constraints:
- The source contains ward and zone names but no latitude/longitude, photographs,
  road/asset IDs, or verified maintenance work-order IDs.
- Historical rows are therefore displayed at ward level. Do not invent map pins.
- The source has date anomalies. The importer retains raw dates and sets
  `grievance_date_valid=0` outside 2010–2035 or when parsing fails.
- Staff names are retained in the source data but are not returned by the public API.

## Import

From the `citymemory-app` folder:

```powershell
python tools/etl/import_civic_grievances.py
```

The script reads `.csv.gz` directly, streams in batches, and inserts records into
`citymemory.db` table `civic_grievances`. It is safe to run again; existing complaint
IDs are skipped. You may also pass another `.csv` or `.csv.gz` path.

The source CSV can be replaced with a new compatible dataset without changing
frontend code. If column names differ, update the mapping in the ETL script only.
