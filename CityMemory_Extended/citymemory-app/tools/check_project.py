#!/usr/bin/env python3
"""Lightweight structural checks for the CityMemory project (stdlib only)."""
from pathlib import Path
import json, re, sys

ROOT = Path(__file__).resolve().parents[1]
required = [
    "server.py", "web/index.html", "web/js/app.js", "web/js/data.js",
    "web/js/core/extension-api.js", "web/js/features/feature-config.js",
    "web/js/features/feature-loader.js", "datasets/schemas/asset-record.schema.json",
    "backend_extensions/__init__.py", "requirements.txt"
]
missing = [p for p in required if not (ROOT / p).is_file()]
if missing:
    print("Missing required files:", ", ".join(missing))
    sys.exit(1)

schema = json.loads((ROOT / "datasets/schemas/asset-record.schema.json").read_text(encoding="utf-8"))
assert schema["type"] == "object"
assert set(["id", "type", "name", "lat", "lng", "complaints", "repairs"]).issubset(schema["required"])

html = (ROOT / "web/index.html").read_text(encoding="utf-8")
for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
    if src.startswith(("http://", "https://")):
        continue
    if not (ROOT / "web" / src).is_file():
        raise SystemExit("Missing local script referenced by index.html: " + src)

app_js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
for event in ["assets:refreshed", "complaint:created", "field-record:created", "civic-dataset:imported"]:
    assert event in app_js, "Missing extension event: " + event

print("CityMemory structure, data schema and local script references: OK")
print("Reminder: this checker does not replace a live Flask/browser regression test.")
