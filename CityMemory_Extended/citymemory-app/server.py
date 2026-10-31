"""
CityMemory API — Flask + SQLite centralized demo backend.
Demo credentials are listed in README. Change them before any real deployment.
"""
from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, json, os
from contextlib import contextmanager
from datetime import datetime
from functools import wraps

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "citymemory.db")
app = Flask(__name__, static_folder="web", static_url_path="")
app.secret_key = os.environ.get("CITYMEMORY_SECRET", "change-this-demo-secret-before-deployment")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # local HTTP prototype
    SESSION_COOKIE_PATH="/"
)

DEPARTMENTS = ["Roads", "Storm Water Drainage", "Electrical", "Footpaths", "Public Health"]
DEMO_USERS = {
    "admin": ("admin123", "Administrator"),
    "roads": ("roads123", "Roads"),
    "drainage": ("drain123", "Storm Water Drainage"),
    "electrical": ("electric123", "Electrical"),
    "footpaths": ("footpaths123", "Footpaths"),
    "health": ("health123", "Public Health"),
}

@contextmanager
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS app_state
                     (id INTEGER PRIMARY KEY CHECK(id=1), assets_json TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, created_at TEXT)""")
        # Clear any legacy synthetic asset seed from an earlier CityMemory prototype.
        c.execute("""INSERT INTO app_state(id,assets_json,updated_at) VALUES(1,'[]',?)
                     ON CONFLICT(id) DO UPDATE SET assets_json='[]', updated_at=excluded.updated_at""",
                  (datetime.utcnow().isoformat(),))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            return jsonify(error="Please sign in first."), 401
        return fn(*args, **kwargs)
    return wrapped

def audit(action):
    with db() as c:
        c.execute("INSERT INTO audit_log(username,action,created_at) VALUES(?,?,?)",
                  (session.get("username"), action, datetime.utcnow().isoformat()))

@app.get("/")
def home():
    return app.send_static_file("portal.html")

@app.get("/api/session")
def current_session():
    if not session.get("username"):
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, username=session["username"],
                   department=session.get("department"), role=session.get("role"))

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    if username not in DEMO_USERS or DEMO_USERS[username][0] != password:
        return jsonify(error="Invalid username or password."), 401
    department = DEMO_USERS[username][1]
    requested_role = str(data.get("role") or department).strip()
    if requested_role != department:
        return jsonify(error="The selected role does not match this username."), 401
    session.clear()
    session["username"] = username
    session["department"] = department
    session["role"] = "admin" if department == "Administrator" else "department"
    audit("login")
    return jsonify(ok=True, username=username, department=department, role=session["role"])

@app.post("/api/logout")
@login_required
def logout():
    audit("logout")
    session.clear()
    return jsonify(ok=True)

@app.get("/api/assets")
@login_required
def get_assets():
    with db() as c:
        row = c.execute("SELECT assets_json,updated_at FROM app_state WHERE id=1").fetchone()
    if not row:
        return jsonify(assets=None, updated_at=None)
    return jsonify(assets=json.loads(row["assets_json"]), updated_at=row["updated_at"])

@app.put("/api/assets")
@login_required
def put_assets():
    payload = request.get_json(silent=True) or {}
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return jsonify(error="Expected an assets array."), 400
    # Department users may update only their department's assets; preserve other departments.
    if session.get("role") != "admin":
        dept = session.get("department")
        with db() as c:
            row = c.execute("SELECT assets_json FROM app_state WHERE id=1").fetchone()
        if row:
            existing = json.loads(row["assets_json"])
            incoming = {a.get("id"): a for a in assets if isinstance(a, dict)}
            merged = []
            seen = set()
            type_department = {"road":"Roads","drain":"Storm Water Drainage","streetlight":"Electrical","footpath":"Footpaths","toilet":"Public Health"}
            for old in existing:
                aid = old.get("id")
                old_department = old.get("department") or type_department.get(old.get("type"))
                if old_department == dept and aid in incoming:
                    merged.append(incoming[aid]); seen.add(aid)
                else:
                    merged.append(old)
            merged.extend(a for a in assets if isinstance(a, dict) and (a.get("department") or type_department.get(a.get("type"))) == dept and a.get("id") not in seen)
            assets = merged
        else:
            assets = [a for a in assets if a.get("department") == dept]
    stamp = datetime.utcnow().isoformat()
    with db() as c:
        c.execute("""INSERT INTO app_state(id,assets_json,updated_at) VALUES(1,?,?)
                     ON CONFLICT(id) DO UPDATE SET assets_json=excluded.assets_json, updated_at=excluded.updated_at""",
                  (json.dumps(assets, separators=(",", ":")), stamp))
    audit("save_assets")
    return jsonify(ok=True, count=len(assets), updated_at=stamp)

@app.get("/api/audit")
@login_required
def audit_log():
    if session.get("role") != "admin":
        return jsonify(error="Administrator access required."),403
    with db() as c:
        rows=c.execute("SELECT username,action,created_at FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify(events=[dict(r) for r in rows])

@app.get("/health")
def health():
    return jsonify(ok=True, service="CityMemory API")

# Optional backend features are registered from backend_extensions/__init__.py.
# Keep the list empty until a separately developed feature is ready.
try:
    from backend_extensions import register_all as register_optional_extensions
    register_optional_extensions(app)
except Exception as extension_error:
    app.logger.exception("Optional CityMemory extension registration failed: %s", extension_error)

init_db()

# Import the exact supplied grievance CSV.GZ once into the shared SQLite database.
try:
    import runpy
    etl_path = os.path.join(BASE, "tools", "etl", "import_civic_grievances.py")
    if os.path.exists(etl_path):
        ns = runpy.run_path(etl_path)
        with db() as c:
            has_rows = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='civic_grievances'").fetchone()
            count = c.execute("SELECT COUNT(*) FROM civic_grievances").fetchone()[0] if has_rows else 0
        if count == 0:
            ns["main"]()
except Exception as import_error:
    app.logger.exception("Automatic historical CSV import failed: %s", import_error)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
