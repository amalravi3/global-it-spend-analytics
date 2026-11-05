"""
Release check for the saved report (run after every edit in Desktop or by script):
  1. layout lock  - every visual's x, y, width, height equals validation/layout_lock.json
  2. references   - every measure / column a visual uses exists in the semantic model
  3. bounds       - no visual sits outside its page

The report folder is the source of truth: it is edited in Power BI Desktop. To move a visual on purpose,
move it in Desktop, save, then refresh the lock:  python scripts/check_report.py --update-lock

Usage:  python scripts/check_report.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "IT Spend Analytics.Report", "definition", "pages")
TABLES = os.path.join(ROOT, "IT Spend Analytics.SemanticModel", "definition", "tables")
LOCK = os.path.join(ROOT, "validation", "layout_lock.json")

cols, meas = set(), set()
for f in glob.glob(os.path.join(TABLES, "*.tmdl")):
    s = open(f, encoding="utf-8").read()
    tbl = re.search(r"^table '?(.+?)'?\s*$", s, re.M).group(1)
    for m in re.finditer(r"^\t(column|measure|calculationItem) '?(.+?)'?\s*(=|$)", s, re.M):
        (meas if m.group(1) == "measure" else cols).add((tbl, m.group(2)))

positions, problems = {}, []
for page_dir in sorted(glob.glob(os.path.join(PAGES, "*", ""))):
    page = os.path.basename(os.path.dirname(page_dir))
    meta = json.load(open(os.path.join(page_dir, "page.json"), encoding="utf-8"))
    for vf in sorted(glob.glob(os.path.join(page_dir, "visuals", "*", "visual.json"))):
        j = json.load(open(vf, encoding="utf-8"))
        p = j["position"]
        positions[f"{page}/{j['name']}"] = {k: p[k] for k in ("x", "y", "width", "height")}
        if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > meta["width"] + 0.5 or p["y"] + p["height"] > meta["height"] + 0.5:
            problems.append(f"out of page: {page}/{j['name']}")
        txt = json.dumps(j)
        for m in re.finditer(r'"(Measure|Column)": \{"Expression": \{"SourceRef": \{"Entity": "([^"]+)"\}\}, "Property": "([^"]+)"', txt):
            key = (m.group(2), m.group(3))
            if (m.group(1) == "Measure" and key not in meas) or (m.group(1) == "Column" and key not in cols):
                problems.append(f"missing {m.group(1).lower()} {key} in {page}/{j['name']}")

if "--update-lock" in sys.argv:
    json.dump(dict(sorted(positions.items())), open(LOCK, "w", encoding="utf-8", newline="\n"), indent=1)
    print(f"lock updated: {len(positions)} visuals")
else:
    lock = json.load(open(LOCK, encoding="utf-8"))
    for k in sorted(set(lock) | set(positions)):
        if k not in positions:
            problems.append(f"visual removed: {k}")
        elif k not in lock:
            problems.append(f"visual added (not in lock): {k}")
        elif any(abs(lock[k][a] - positions[k][a]) > 0.01 for a in ("x", "y", "width", "height")):
            problems.append(f"moved/resized: {k} {lock[k]} -> {positions[k]}")
print("\n".join(problems) if problems else f"OK: {len(positions)} visuals match the layout lock; all field references resolve")
sys.exit(1 if problems else 0)
