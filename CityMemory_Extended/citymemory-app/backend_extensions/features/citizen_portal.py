"""Public citizen portal and civic-memory API.

This add-on is intentionally separate from server.py. It exposes public, read-only
historical grievance summaries plus citizen-submitted reports. Historical grievance
records are not assigned invented coordinates; map pins are only shown for reports
where a citizen explicitly shares GPS coordinates.
"""
from __future__ import annotations
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
import sqlite3, uuid, re, os
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session

bp = Blueprint("citizen_portal", __name__, url_prefix="/api/public")
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "citymemory.db"
UPLOAD_DIR = ROOT / "uploads" / "public"
MAX_PHOTO_BYTES = 4 * 1024 * 1024

CATEGORY_SOURCE_MAP = {
    "Road / Pothole": ("Road Maintenance(Engg)", "Road Infrastructure"),
    "Drainage / Waterlogging": ("Storm  Water Drain(SWD)",),
    "Garbage / Waste": ("Solid Waste (Garbage) Related",),
    "Streetlight / Electrical": ("Electrical",),
    "Footpath / Encroachment": ("Road Maintenance(Engg)",),
    "Other civic issue": ()
}
ALLOWED_CATEGORIES = tuple(CATEGORY_SOURCE_MAP)

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def ensure_tables():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS public_reports (
          report_id TEXT PRIMARY KEY, category TEXT NOT NULL, description TEXT NOT NULL,
          ward_name TEXT NOT NULL, zone_name TEXT, landmark TEXT, latitude REAL, longitude REAL,
          photo_filename TEXT, status TEXT NOT NULL DEFAULT 'Submitted',
          potential_duplicate_of TEXT, similarity_score REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_public_ward ON public_reports(ward_name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_public_category ON public_reports(category)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_public_created ON public_reports(created_at)")
        con.execute("""CREATE TABLE IF NOT EXISTS citizen_users (
          email TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS report_status_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL, status TEXT NOT NULL,
          note TEXT, updated_by TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        columns = {r[1] for r in con.execute("PRAGMA table_info(public_reports)")}
        if "citizen_email" not in columns:
            con.execute("ALTER TABLE public_reports ADD COLUMN citizen_email TEXT")
        if "rejection_reason" not in columns:
            con.execute("ALTER TABLE public_reports ADD COLUMN rejection_reason TEXT")
        if "severity" not in columns:
            con.execute("ALTER TABLE public_reports ADD COLUMN severity TEXT NOT NULL DEFAULT 'Medium'")
        con.execute("CREATE INDEX IF NOT EXISTS idx_public_owner ON public_reports(citizen_email)")
        con.execute("""CREATE TABLE IF NOT EXISTS report_field_records (
          record_id TEXT PRIMARY KEY,
          report_id TEXT NOT NULL,
          record_type TEXT NOT NULL,
          department TEXT NOT NULL,
          findings TEXT NOT NULL,
          cost REAL NOT NULL DEFAULT 0,
          condition TEXT,
          photo_filename TEXT,
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_field_records_report ON report_field_records(report_id)")

def clean_text(value, limit=1000):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

def classify_description(text):
    t = text.lower()
    rules = [
      ("Road / Pothole", ("pothole","road broken","road damage","crater","road surface")),
      ("Drainage / Waterlogging", ("drain","waterlogging","water logging","sewage","overflow","blocked water")),
      ("Garbage / Waste", ("garbage","waste","rubbish","dump","litter")),
      ("Streetlight / Electrical", ("streetlight","street light","lamp","electric pole","light not working")),
      ("Footpath / Encroachment", ("footpath","pavement","sidewalk","encroachment"))
    ]
    for category, words in rules:
        if any(word in t for word in words):
            return category
    return "Other civic issue"

def similarity(a, b):
    a_words = set(re.findall(r"[a-z0-9]{3,}", a.lower()))
    b_words = set(re.findall(r"[a-z0-9]{3,}", b.lower()))
    jaccard = len(a_words & b_words) / max(1, len(a_words | b_words))
    sequence = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(0.65 * jaccard + 0.35 * sequence, 3)

def source_categories(category):
    return CATEGORY_SOURCE_MAP.get(category, ())

@bp.post("/auth/register")
def citizen_register():
    data = request.get_json(silent=True) or {}
    email = clean_text(data.get("email"), 180).lower()
    password = str(data.get("password") or "")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(password) < 8:
        return jsonify(error="Enter a valid email and a password with at least 8 characters."), 400
    with connect() as con:
        try:
            con.execute("INSERT INTO citizen_users(email,password_hash,created_at) VALUES(?,?,?)",
                        (email, generate_password_hash(password), datetime.utcnow().isoformat()))
        except sqlite3.IntegrityError:
            return jsonify(error="An account with this email already exists. Please sign in."), 409
    session.clear(); session["citizen_email"] = email
    return jsonify(ok=True, email=email)

@bp.post("/auth/login")
def citizen_login():
    data = request.get_json(silent=True) or {}
    email = clean_text(data.get("email"), 180).lower()
    password = str(data.get("password") or "")
    with connect() as con:
        row = con.execute("SELECT password_hash FROM citizen_users WHERE email=?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify(error="Invalid email or password."), 401
    session.clear(); session["citizen_email"] = email
    return jsonify(ok=True, email=email)

@bp.get("/auth/me")
def citizen_me():
    return jsonify(authenticated=bool(session.get("citizen_email")), email=session.get("citizen_email"))

@bp.post("/auth/logout")
def citizen_logout():
    session.clear()
    return jsonify(ok=True)

def require_citizen():
    if not session.get("citizen_email"):
        return jsonify(error="Please sign in to your citizen account first."), 401
    return None

@bp.get("/health")
def health():
    return jsonify(ok=True, feature="public-citizen-portal")

@bp.get("/summary")
def summary():
    with connect() as con:
        civic_exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        public_total = con.execute("SELECT COUNT(*) FROM public_reports").fetchone()[0]
        if not civic_exists:
            return jsonify(historical_records=0, wards=0, categories=0, public_reports=public_total,
                           dataset_imported=False, note="Import the supplied CSV.GZ dataset to activate historical analytics.")
        total = con.execute("SELECT COUNT(*) FROM civic_grievances").fetchone()[0]
        wards = con.execute("SELECT COUNT(DISTINCT ward_name) FROM civic_grievances").fetchone()[0]
        categories = con.execute("SELECT COUNT(DISTINCT category) FROM civic_grievances").fetchone()[0]
        status_rows = con.execute("SELECT grievance_status, COUNT(*) n FROM civic_grievances GROUP BY grievance_status ORDER BY n DESC LIMIT 8").fetchall()
        top_wards = con.execute("SELECT ward_name, COUNT(*) n FROM civic_grievances GROUP BY ward_name ORDER BY n DESC LIMIT 8").fetchall()
        valid_dates = con.execute("SELECT COUNT(*) FROM civic_grievances WHERE grievance_date_valid=1").fetchone()[0]
    return jsonify(historical_records=total, wards=wards, categories=categories, public_reports=public_total,
                   valid_date_records=valid_dates, dataset_imported=True,
                   statuses=[dict(r) for r in status_rows], top_wards=[dict(r) for r in top_wards],
                   geographic_granularity="ward-level historical records; no GPS coordinates in supplied source")

@bp.get("/wards")
def wards():
    with connect() as con:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        if not exists:
            return jsonify(wards=[])
        rows = con.execute("SELECT ward_name, COUNT(*) AS records FROM civic_grievances GROUP BY ward_name ORDER BY ward_name").fetchall()
    return jsonify(wards=[dict(r) for r in rows])

@bp.get("/history")
def history():
    ward = clean_text(request.args.get("ward"), 120)
    category = clean_text(request.args.get("category"), 80)
    if not ward:
        return jsonify(error="Select a ward to view historical records."), 400
    with connect() as con:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        if not exists:
            return jsonify(records=[], note="Historical dataset has not been imported yet.")
        params = [ward]
        where = "ward_name = ?"
        source = source_categories(category)
        if source:
            where += " AND category IN (" + ",".join("?" for _ in source) + ")"
            params.extend(source)
        rows = con.execute(f"""SELECT complaint_id,category,sub_category,grievance_date_raw,
                    grievance_date_valid,zone_name,ward_name,grievance_status,staff_remarks
                    FROM civic_grievances WHERE {where}
                    ORDER BY CASE WHEN grievance_date_valid=1 THEN 0 ELSE 1 END,
                    grievance_date_raw DESC LIMIT 100""", params).fetchall()
        total = con.execute(f"SELECT COUNT(*) FROM civic_grievances WHERE {where}", params).fetchone()[0]
    return jsonify(ward=ward, category=category or "All categories", total_matches=total,
                   records=[dict(r) for r in rows],
                   note="These are ward-level historical grievance records, not verified exact-road matches.")

@bp.get("/recurrence")
def recurrence():
    ward = clean_text(request.args.get("ward"), 120)
    with connect() as con:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        if not exists:
            return jsonify(patterns=[], note="Import the historical dataset first.")
        if ward:
            rows = con.execute("""SELECT ward_name,category,sub_category,COUNT(*) AS incident_count,
                    MIN(grievance_date_raw) AS first_record, MAX(grievance_date_raw) AS latest_record
                    FROM civic_grievances WHERE ward_name=?
                    GROUP BY ward_name,category,sub_category HAVING COUNT(*) >= 2
                    ORDER BY incident_count DESC LIMIT 30""", (ward,)).fetchall()
        else:
            rows = con.execute("""SELECT ward_name,category,sub_category,COUNT(*) AS incident_count,
                    MIN(grievance_date_raw) AS first_record, MAX(grievance_date_raw) AS latest_record
                    FROM civic_grievances GROUP BY ward_name,category,sub_category
                    HAVING COUNT(*) >= 2 ORDER BY incident_count DESC LIMIT 50""").fetchall()
    return jsonify(patterns=[dict(r) for r in rows],
                   interpretation="Ward/category recurrence signal only; it does not prove repeated failure of the same physical asset.")

@bp.get("/authority/analytics")
def authority_analytics():
    if not session.get("username"):
        return jsonify(error="Authority login required."), 403
    with connect() as con:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        if not exists:
            return jsonify(total=0, categories=[], wards=[], statuses=[])
        total = con.execute("SELECT COUNT(*) FROM civic_grievances").fetchone()[0]
        categories = con.execute("SELECT category,COUNT(*) n FROM civic_grievances GROUP BY category ORDER BY n DESC LIMIT 12").fetchall()
        wards = con.execute("SELECT ward_name,COUNT(*) n FROM civic_grievances GROUP BY ward_name ORDER BY n DESC LIMIT 12").fetchall()
        statuses = con.execute("SELECT grievance_status status,COUNT(*) n FROM civic_grievances GROUP BY grievance_status ORDER BY n DESC").fetchall()
    return jsonify(total=total,categories=[dict(x) for x in categories],wards=[dict(x) for x in wards],statuses=[dict(x) for x in statuses])

@bp.get("/reports")
def reports():
    # Private by default: citizens see only their own reports; authenticated authorities see all.
    if session.get("username"):
        sql = """SELECT report_id,category,description,ward_name,zone_name,landmark,latitude,longitude,
                 status,potential_duplicate_of,similarity_score,created_at,photo_filename,
                 rejection_reason,citizen_email,severity FROM public_reports ORDER BY created_at DESC LIMIT 250"""
        params = ()
    elif session.get("citizen_email"):
        sql = """SELECT report_id,category,description,ward_name,zone_name,landmark,latitude,longitude,
                 status,potential_duplicate_of,similarity_score,created_at,photo_filename,
                 rejection_reason,severity FROM public_reports WHERE citizen_email=? ORDER BY created_at DESC LIMIT 100"""
        params = (session["citizen_email"],)
    else:
        return jsonify(error="Sign in to view complaint records."), 401
    with connect() as con:
        rows = con.execute(sql, params).fetchall()
    reports_out = [dict(r) for r in rows]
    if session.get("username") and session.get("role") != "admin":
        dept = session.get("department")
        allowed = {
          "Roads": {"Road / Pothole"},
          "Storm Water Drainage": {"Drainage / Waterlogging"},
          "Electrical": {"Streetlight / Electrical"},
          "Footpaths": {"Footpath / Encroachment"},
          "Public Health": {"Garbage / Waste", "Other civic issue"}
        }.get(dept, set())
        reports_out = [r for r in reports_out if r.get("category") in allowed]
    return jsonify(reports=reports_out)

@bp.get("/reports/<report_id>/tracker")
def report_tracker(report_id):
    owner = session.get("citizen_email")
    authority = bool(session.get("username"))
    if not owner and not authority:
        return jsonify(error="Please sign in first."), 401
    with connect() as con:
        report = con.execute("SELECT report_id,status,rejection_reason,citizen_email,category FROM public_reports WHERE report_id=?", (report_id,)).fetchone()
        if not report or (not authority and report["citizen_email"] != owner):
            return jsonify(error="Complaint not found."), 404
        if authority and session.get("role") != "admin":
            allowed = {"Roads":{"Road / Pothole"},"Storm Water Drainage":{"Drainage / Waterlogging"},
                       "Electrical":{"Streetlight / Electrical"},"Footpaths":{"Footpath / Encroachment"},
                       "Public Health":{"Garbage / Waste","Other civic issue"}}.get(session.get("department"),set())
            if report["category"] not in allowed: return jsonify(error="Complaint not found."), 404
        events = con.execute("SELECT status,note,updated_by,created_at FROM report_status_history WHERE report_id=? ORDER BY id", (report_id,)).fetchall()
    return jsonify(report=dict(report), history=[dict(x) for x in events])

@bp.post("/reports/<report_id>/status")
def update_report_status(report_id):
    if not session.get("username"):
        return jsonify(error="Authority login required."), 403
    data = request.get_json(silent=True) or {}
    status = clean_text(data.get("status"), 40)
    note = clean_text(data.get("reason") or data.get("note"), 500)
    allowed = {"Acknowledged","Assigned","Inspection Scheduled","In Progress","Resolved","Verified","Rejected"}
    if status not in allowed:
        return jsonify(error="Choose a valid complaint status."), 400
    if status == "Rejected" and len(note) < 8:
        return jsonify(error="A specific rejection reason is required."), 400
    with connect() as con:
        row = con.execute("SELECT report_id,category FROM public_reports WHERE report_id=?", (report_id,)).fetchone()
        if not row: return jsonify(error="Complaint not found."), 404
        if session.get("role") != "admin":
            allowed = {"Roads":{"Road / Pothole"},"Storm Water Drainage":{"Drainage / Waterlogging"},
                       "Electrical":{"Streetlight / Electrical"},"Footpaths":{"Footpath / Encroachment"},
                       "Public Health":{"Garbage / Waste","Other civic issue"}}.get(session.get("department"),set())
            if row["category"] not in allowed: return jsonify(error="This complaint is assigned to another department."), 403
        con.execute("UPDATE public_reports SET status=?, rejection_reason=? WHERE report_id=?",
                    (status, note if status=="Rejected" else None, report_id))
        con.execute("INSERT INTO report_status_history(report_id,status,note,updated_by,created_at) VALUES(?,?,?,?,?)",
                    (report_id,status,note,session.get("username"),datetime.utcnow().isoformat()))
    return jsonify(ok=True, report_id=report_id, status=status)

@bp.post("/reports")
def create_report():
    auth_error = require_citizen()
    if auth_error: return auth_error
    description = clean_text(request.form.get("description"), 1500)
    ward = clean_text(request.form.get("ward_name"), 120)
    zone = clean_text(request.form.get("zone_name"), 80) or None
    landmark = clean_text(request.form.get("landmark"), 180) or None
    category = clean_text(request.form.get("category"), 80)
    severity = clean_text(request.form.get("severity"), 20)
    if severity not in {"Low","Medium","High","Critical"}: severity = "Medium"
    if category == "Auto detect" or category not in ALLOWED_CATEGORIES:
        category = classify_description(description)
    if len(description) < 8 or not ward:
        return jsonify(error="Description (at least 8 characters) and ward are required."), 400
    lat = request.form.get("latitude")
    lng = request.form.get("longitude")
    try:
        lat = float(lat) if lat else None
        lng = float(lng) if lng else None
        if lat is not None and not (-90 <= lat <= 90): raise ValueError()
        if lng is not None and not (-180 <= lng <= 180): raise ValueError()
    except ValueError:
        return jsonify(error="Invalid latitude or longitude."), 400
    photo = request.files.get("photo")
    photo_filename = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in {".jpg",".jpeg",".png",".webp"}:
            return jsonify(error="Photo must be JPG, JPEG, PNG or WEBP."), 400
        content = photo.read(MAX_PHOTO_BYTES + 1)
        if len(content) > MAX_PHOTO_BYTES:
            return jsonify(error="Photo must be 4 MB or smaller."), 400
        photo_filename = uuid.uuid4().hex + ext
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOAD_DIR / photo_filename).write_bytes(content)
    report_id = "CM-" + uuid.uuid4().hex[:10].upper()
    possible_match = None
    best_score = 0.0
    with connect() as con:
        candidates = con.execute("""SELECT report_id,description FROM public_reports
              WHERE ward_name=? AND category=? ORDER BY created_at DESC LIMIT 250""",
              (ward, category)).fetchall()
        for candidate in candidates:
            score = similarity(description, candidate["description"])
            if score > best_score:
                best_score, possible_match = score, candidate["report_id"]
        duplicate = possible_match if best_score >= 0.72 else None
        stamp = datetime.utcnow().isoformat(timespec="seconds")
        con.execute("""INSERT INTO public_reports
          (report_id,category,description,ward_name,zone_name,landmark,latitude,longitude,
           photo_filename,status,potential_duplicate_of,similarity_score,created_at,citizen_email,severity)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (report_id,category,description,ward,zone,landmark,lat,lng,photo_filename,
           "Submitted",duplicate,best_score,stamp,session.get("citizen_email"),severity))
        con.execute("INSERT INTO report_status_history(report_id,status,note,updated_by,created_at) VALUES(?,?,?,?,?)",
                    (report_id,"Submitted","Complaint received by CityMemory.",session.get("citizen_email"),stamp))
    return jsonify(ok=True, report_id=report_id, category=category,
                   potential_duplicate_of=duplicate, similarity_score=best_score,
                   message=("A similar citizen-submitted report may already exist. Your report was still saved."
                            if duplicate else "Your report has been submitted to the CityMemory prototype."),
                   status="Submitted"), 201

@bp.get("/uploads/<path:filename>")
def uploaded_photo(filename):
    owner = session.get("citizen_email")
    authority = bool(session.get("username"))
    if not owner and not authority:
        return jsonify(error="Sign in to view evidence photographs."), 401
    with connect() as con:
        report = con.execute("SELECT citizen_email,category FROM public_reports WHERE photo_filename=?", (filename,)).fetchone()
        field_report = con.execute("""SELECT p.citizen_email,p.category
            FROM report_field_records f JOIN public_reports p ON p.report_id=f.report_id
            WHERE f.photo_filename=?""", (filename,)).fetchone()
    report = report or field_report
    if not report: return jsonify(error="Photograph not found."), 404
    if owner and report["citizen_email"] != owner: return jsonify(error="Photograph not found."), 404
    if authority and session.get("role") != "admin":
        allowed = {"Roads":{"Road / Pothole"},"Storm Water Drainage":{"Drainage / Waterlogging"},
                   "Electrical":{"Streetlight / Electrical"},"Footpaths":{"Footpath / Encroachment"},
                   "Public Health":{"Garbage / Waste","Other civic issue"}}.get(session.get("department"),set())
        if report["category"] not in allowed: return jsonify(error="Photograph not found."), 404
    return send_from_directory(UPLOAD_DIR, filename)


def _authority_can_view_report(row):
    if not row:
        return False
    if session.get("role") == "admin":
        return True
    allowed = {
        "Roads": {"Road / Pothole"},
        "Storm Water Drainage": {"Drainage / Waterlogging"},
        "Electrical": {"Streetlight / Electrical"},
        "Footpaths": {"Footpath / Encroachment"},
        "Public Health": {"Garbage / Waste", "Other civic issue"}
    }.get(session.get("department"), set())
    return row["category"] in allowed

@bp.get("/authority/live-insights")
def authority_live_insights():
    if not session.get("username"):
        return jsonify(error="Authority login required."), 403
    # Respect department access: department accounts see only their own category set.
    with connect() as con:
        rows = con.execute("""SELECT report_id,category,description,ward_name,zone_name,landmark,
            latitude,longitude,status,created_at,severity,citizen_email,photo_filename,rejection_reason
            FROM public_reports ORDER BY created_at DESC""").fetchall()
        historical_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
        historical_total = con.execute("SELECT COUNT(*) FROM civic_grievances").fetchone()[0] if historical_exists else 0
        historical_wards = con.execute("SELECT COUNT(DISTINCT ward_name) FROM civic_grievances").fetchone()[0] if historical_exists else 0
        historical_categories = con.execute("SELECT COUNT(DISTINCT category) FROM civic_grievances").fetchone()[0] if historical_exists else 0
        hist_rows = con.execute("""SELECT ward_name,category,sub_category,COUNT(*) AS incident_count
            FROM civic_grievances GROUP BY ward_name,category,sub_category
            HAVING COUNT(*) >= 2 ORDER BY incident_count DESC LIMIT 30""").fetchall() if historical_exists else []
        resolved_rows = con.execute("""SELECT p.report_id, p.created_at AS started,
            MIN(h.created_at) AS finished
            FROM public_reports p JOIN report_status_history h ON h.report_id=p.report_id
            WHERE h.status IN ('Resolved','Verified') GROUP BY p.report_id""").fetchall()
    reports_out = [dict(r) for r in rows if _authority_can_view_report(r)]
    for report in reports_out:
        related = 1
        for candidate in reports_out:
            if candidate["report_id"] == report["report_id"]:
                continue
            if candidate["ward_name"] == report["ward_name"] and candidate["category"] == report["category"]:
                if similarity(report["description"], candidate["description"]) >= 0.25:
                    related += 1
        report["recurrence_count"] = related
    severity_counts = {s: sum(1 for r in reports_out if (r.get("severity") or "Medium") == s)
                       for s in ("Critical", "High", "Medium", "Low")}
    status_counts = {}
    department_counts = {}
    month_counts = {}
    for r in reports_out:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        dept = {"Road / Pothole":"Roads","Drainage / Waterlogging":"Storm Water Drainage",
                "Streetlight / Electrical":"Electrical","Footpath / Encroachment":"Footpaths",
                "Garbage / Waste":"Public Health","Other civic issue":"Public Health"}.get(r["category"], "Unassigned")
        department_counts[dept] = department_counts.get(dept, 0) + 1
        month = (r.get("created_at") or "")[:7] or "Unknown"
        month_counts[month] = month_counts.get(month, 0) + 1
    unresolved = [r for r in reports_out if r["status"] not in ("Resolved", "Verified", "Rejected")]
    gps_reports = [r for r in reports_out if r["latitude"] is not None and r["longitude"] is not None]
    durations = []
    for item in resolved_rows:
        if item["started"] and item["finished"]:
            try:
                durations.append(max(0, (datetime.fromisoformat(item["finished"]) -
                                         datetime.fromisoformat(item["started"])).total_seconds() / 86400))
            except Exception:
                pass
    return jsonify(
        live_total=len(reports_out), severity=severity_counts, statuses=status_counts,
        departments=department_counts, monthly=dict(sorted(month_counts.items())),
        unresolved=len(unresolved), gps_count=len(gps_reports),
        average_resolution_days=round(sum(durations)/len(durations), 1) if durations else None,
        historical={"records": historical_total, "wards": historical_wards,
                    "categories": historical_categories, "recurrence_patterns":[dict(x) for x in hist_rows]},
        reports=reports_out
    )

@bp.get("/reports/<report_id>/matches")
def report_matches(report_id):
    owner = session.get("citizen_email")
    authority = bool(session.get("username"))
    if not owner and not authority:
        return jsonify(error="Please sign in first."), 401
    with connect() as con:
        target = con.execute("""SELECT report_id,category,description,ward_name,zone_name,landmark,
            latitude,longitude,created_at,severity,status,citizen_email FROM public_reports WHERE report_id=?""",
            (report_id,)).fetchone()
        if not target or (not authority and target["citizen_email"] != owner):
            return jsonify(error="Complaint not found."), 404
        if authority and not _authority_can_view_report(target):
            return jsonify(error="Complaint not found."), 404
        candidates = con.execute("""SELECT report_id,category,description,ward_name,zone_name,landmark,
            latitude,longitude,created_at,severity,status FROM public_reports
            WHERE report_id<>? AND ward_name=? AND category=? ORDER BY created_at DESC LIMIT 300""",
            (report_id, target["ward_name"], target["category"])).fetchall()
        source = source_categories(target["category"])
        hist_total = 0
        hist_rows = []
        if source and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone():
            marks = ",".join("?" for _ in source)
            hist_total = con.execute(
                f"SELECT COUNT(*) FROM civic_grievances WHERE ward_name=? AND category IN ({marks})",
                [target["ward_name"], *source]).fetchone()[0]
            hist_rows = con.execute(
                f"""SELECT complaint_id,category,sub_category,grievance_date_raw,grievance_status
                    FROM civic_grievances WHERE ward_name=? AND category IN ({marks})
                    ORDER BY CASE WHEN grievance_date_valid=1 THEN 0 ELSE 1 END,
                    grievance_date_raw DESC LIMIT 12""",
                [target["ward_name"], *source]).fetchall()
    matches = []
    for c in candidates:
        text_score = similarity(target["description"], c["description"])
        landmark_a = clean_text(target["landmark"], 180).lower()
        landmark_b = clean_text(c["landmark"], 180).lower()
        landmark_score = 1.0 if landmark_a and landmark_b and landmark_a == landmark_b else 0.0
        distance_score = 0.0
        if target["latitude"] is not None and target["longitude"] is not None and c["latitude"] is not None and c["longitude"] is not None:
            from math import radians, sin, cos, sqrt, atan2
            lat1, lon1, lat2, lon2 = map(radians, [target["latitude"], target["longitude"], c["latitude"], c["longitude"]])
            dlat, dlon = lat2-lat1, lon2-lon1
            h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
            distance = 6371000 * 2 * atan2(sqrt(h), sqrt(max(0, 1-h)))
            distance_score = max(0.0, 1.0-distance/500.0)
        combined = min(1.0, 0.75*text_score + 0.15*landmark_score + 0.10*distance_score)
        if combined >= 0.25:
            matches.append({**dict(c), "similarity_percent": round(combined*100)})
    matches.sort(key=lambda x: x["similarity_percent"], reverse=True)
    return jsonify(
        complaint=dict(target), matches=matches[:12],
        recurrence_count=1+len(matches),
        historical_ward_category_count=hist_total,
        historical_records=[dict(x) for x in hist_rows],
        interpretation="Similarity is a review aid based on description, same ward/category, optional landmark and optional GPS proximity. Historical records are ward/category patterns, not verified same-asset matches."
    )


@bp.get("/reports/<report_id>/field-records")
def get_report_field_records(report_id):
    if not session.get("username"):
        return jsonify(error="Authority login required."), 403
    with connect() as con:
        report = con.execute(
            "SELECT report_id,category FROM public_reports WHERE report_id=?",
            (report_id,)
        ).fetchone()
        if not report or not _authority_can_view_report(report):
            return jsonify(error="Complaint not found or assigned to another department."), 404
        rows = con.execute("""SELECT record_id,report_id,record_type,department,findings,
            cost,condition,photo_filename,created_by,created_at
            FROM report_field_records WHERE report_id=? ORDER BY created_at DESC""",
            (report_id,)
        ).fetchall()
    return jsonify(records=[dict(row) for row in rows])


@bp.post("/reports/<report_id>/field-records")
def create_report_field_record(report_id):
    if not session.get("username"):
        return jsonify(error="Authority login required."), 403

    with connect() as con:
        report = con.execute(
            "SELECT report_id,category FROM public_reports WHERE report_id=?",
            (report_id,)
        ).fetchone()

    if not report or not _authority_can_view_report(report):
        return jsonify(error="Complaint not found or assigned to another department."), 404

    record_type = clean_text(request.form.get("record_type"), 20).lower()
    findings = clean_text(request.form.get("findings"), 1500)
    condition = clean_text(request.form.get("condition"), 40) or None

    if record_type not in {"inspection", "repair"}:
        return jsonify(error="Choose Inspection or Maintenance / repair."), 400
    if len(findings) < 5:
        return jsonify(error="Enter at least 5 characters describing the field activity."), 400

    expected_department = {
        "Road / Pothole": "Roads",
        "Drainage / Waterlogging": "Storm Water Drainage",
        "Streetlight / Electrical": "Electrical",
        "Footpath / Encroachment": "Footpaths",
        "Garbage / Waste": "Public Health",
        "Other civic issue": "Public Health"
    }.get(report["category"], "Unassigned")

    department = session.get("department") if session.get("role") != "admin" else clean_text(
        request.form.get("department"), 80
    )
    if session.get("role") == "admin" and department not in {
        "Roads", "Storm Water Drainage", "Electrical", "Footpaths", "Public Health"
    }:
        department = expected_department

    if department != expected_department:
        return jsonify(error="The field activity department must match the complaint category."), 403

    try:
        cost = float(request.form.get("cost") or 0)
        if cost < 0:
            raise ValueError()
    except ValueError:
        return jsonify(error="Cost must be a non-negative number."), 400

    photo = request.files.get("photo")
    photo_filename = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            return jsonify(error="Evidence photo must be JPG, JPEG, PNG or WEBP."), 400
        content = photo.read(MAX_PHOTO_BYTES + 1)
        if len(content) > MAX_PHOTO_BYTES:
            return jsonify(error="Evidence photo must be 4 MB or smaller."), 400
        photo_filename = "field-" + uuid.uuid4().hex + ext
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOAD_DIR / photo_filename).write_bytes(content)

    record_id = "FR-" + uuid.uuid4().hex[:10].upper()
    created_at = datetime.utcnow().isoformat(timespec="seconds")
    new_status = "Inspection Scheduled" if record_type == "inspection" else "In Progress"

    with connect() as con:
        con.execute("""INSERT INTO report_field_records
            (record_id,report_id,record_type,department,findings,cost,condition,
             photo_filename,created_by,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (record_id, report_id, record_type, department, findings, cost,
             condition, photo_filename, session.get("username"), created_at)
        )
        con.execute("""INSERT INTO report_status_history
            (report_id,status,note,updated_by,created_at)
            VALUES (?,?,?,?,?)""",
            (report_id, new_status,
             f"{record_type.title()} field record {record_id}: {findings}",
             session.get("username"), created_at)
        )
        con.execute("UPDATE public_reports SET status=? WHERE report_id=?",
                    (new_status, report_id))

    return jsonify(
        ok=True,
        record_id=record_id,
        report_id=report_id,
        status=new_status,
        message="Field activity saved and linked to the citizen complaint."
    ), 201


def register(app):
    app.config.setdefault("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    ensure_tables()
