# CityMemory prototype data and workflow

- Historical source: the supplied `citizen-grievances.csv.gz` file.
- First-start import: `server.py` runs the streaming ETL importer if the grievance table is empty.
- Historical records are grouped by ward and category; no GPS coordinates, physical asset IDs or repairs are invented.
- Citizens register/sign in and see only their own complaints.
- Authenticated authority accounts can view and update complaints assigned to their department; Administrator can view all.
- Rejections require a reason. Every submission and status change is recorded in the status history.
- Exact asset matching and maintenance history require a verified physical asset register, which is not included in the supplied CSV.
