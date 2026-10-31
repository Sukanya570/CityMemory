# CityMemory — Civic Complaint Portal & Infrastructure Memory

A single Flask website with two role-separated interfaces:
- Citizen Portal: `http://127.0.0.1:5000/citizen.html`
- Authority Dashboard: `http://127.0.0.1:5000/index.html`

Both interfaces use the same Flask server and SQLite database.

## Run on Windows

1. Extract the ZIP.
2. Open the `citymemory-app` folder in VS Code.
3. Run `run_windows.bat`, or use:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

4. Open `http://127.0.0.1:5000` to choose Citizen or Authority access.

The supplied `datasets/imports/citizen-grievances.csv.gz` file is imported automatically into SQLite on first startup. No separate CSV upload is needed.

## Authority demo accounts

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `admin123` |
| Roads | `roads` | `roads123` |
| Storm Water Drainage | `drainage` | `drain123` |
| Electrical | `electrical` | `electric123` |
| Footpaths | `footpaths` | `footpaths123` |
| Public Health | `health` | `health123` |

The selected role must match the username's configured department. These credentials are for local prototype demonstration only; change them and configure production authentication before deployment.

## Citizen workflow

- Register using email and a password of at least 8 characters, or sign in.
- Explore ward-level historical grievances by ward and category.
- Submit a complaint with ward, category, description, optional landmark, photograph and optional GPS.
- Receive a unique `CM-...` complaint ID and submission acknowledgement.
- View only the signed-in citizen's own complaints and status history.

Google sign-in is displayed as a UI option but requires Google OAuth client credentials and redirect configuration; it is not active in this local prototype.

## Authority workflow

- Sign in using the role, username and password above.
- View complaints submitted through the Citizen Portal.
- Update complaint status: Acknowledged, Assigned, Inspection Scheduled, In Progress, Resolved, Verified or Rejected.
- A rejection requires a specific reason, which is visible to the complaint owner.
- Open the status history for each complaint.
- Explore historical dataset analytics.

## Actual historical dataset

The bundled source is the user-provided `citizen-grievances.csv.gz`:
- 1,230,890 complaint records
- 485 distinct wards
- 32 historical categories
- 187 historical subcategories
- 12 source columns

Historical rows remain ward-level. The source does not provide verified GPS coordinates or a stable physical asset identifier. The application therefore does not fabricate 42 assets, asset coordinates, repairs, repair expenditure, or exact map locations. The map shows only citizen reports for which a citizen voluntarily shared GPS coordinates.

Ward/category recurrence is a historical pattern signal, not proof that complaints refer to the same physical asset. Asset matching and asset history require a verified physical asset register; this CSV alone cannot provide that.

## Privacy and prototype security

- Citizen report listings are private: citizens can retrieve only reports associated with their signed-in email.
- Authority sessions can access the operational complaint register.
- Passwords are stored as password hashes, not plain text.
- GPS sharing is optional.
- This is a local demonstration prototype, not a production-ready civic service. Before public deployment, configure HTTPS, a strong `CITYMEMORY_SECRET`, CSRF protection, rate limiting, secure account recovery, verified municipal authority accounts, managed database backups and an approved privacy/security review.

## Main files

- `server.py` — Flask server, authority authentication and automatic CSV import.
- `backend_extensions/features/citizen_portal.py` — citizen accounts, private reports, status history and ward-level history APIs.
- `datasets/imports/citizen-grievances.csv.gz` — exact supplied historical source.
- `web/citizen.html` — citizen interface.
- `web/index.html` — authority interface.
- `citymemory.db` — generated SQLite database.


## Live complaint intelligence update

The Authority Priority tab now reads citizen-submitted complaints from the shared SQLite `public_reports` table and groups them by Critical, High, Medium and Low severity. Complaint triage score is a transparent prototype score based on severity, age and similarity recurrence; it is not a validated safety assessment.

The Asset History tab can be opened from a complaint card and displays similarity matches from the same ward/category, optional landmark/GPS proximity, related complaint IDs, and historical ward/category counts. Historical rows are not claimed as matches to the same physical asset.

The map plots only citizen reports with GPS coordinates voluntarily shared by the citizen. Reports without GPS remain available in the complaint list with their ward/landmark. The supplied historical CSV remains ward-level only.

Analytics now separates live citizen complaint statistics from historical CSV statistics and includes priority, status, department, monthly, GPS and resolution-time summaries. Dashboard data refreshes every 15 seconds while the page is visible and after status updates.


## Additive authority dashboard improvements

The existing architecture and original verified-asset workflow are retained.

- The Priority department filter is now populated from the configured departments (Roads, Storm Water Drainage, Electrical, Footpaths, Public Health), independently of whether verified physical assets exist. Counts are calculated from live citizen reports.
- Citizen Reports and Priority cards include a **Show on map** action. It pans to the exact GPS point when the citizen voluntarily shared coordinates. When no GPS was shared, the interface explains why an exact pin cannot be drawn and retains ward/landmark context.
- The existing physical asset field-record form remains intact. A separate complaint-linked field activity panel allows an authority to record an inspection/repair against a real citizen complaint ID without pretending that a ward-level grievance is a verified physical asset.
- Complaint-linked field records are stored in `report_field_records`, linked to `public_reports`, visible in complaint history, and included in status history. Evidence photos use the existing protected upload directory and access checks.
- The citizen portal JavaScript and existing citizen workflows are not replaced by this update.
