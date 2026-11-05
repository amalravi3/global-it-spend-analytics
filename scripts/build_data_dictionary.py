"""
Builds docs/IT Spend Analytics - Data Dictionary.xlsx from the PBIP project itself, so the dictionary always matches the model and report.

Reads the TMDL semantic model (table, column and measure descriptions, DAX, display folders, relationships,
roles) and the PBIR report (pages, visual titles, slicers), and adds a short glossary of the business terms.

Usage:  python scripts/build_data_dictionary.py
"""
from __future__ import annotations

import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "IT Spend Analytics.SemanticModel", "definition")
PAGES = os.path.join(ROOT, "IT Spend Analytics.Report", "definition", "pages")

GLOSSARY = [
    ("cGBP", "Consolidated GBP: every local-currency amount translated to pounds sterling, row by row, then summed."),
    ("Local currency (LC)", "The entity's own currency (GBP, EUR, USD, INR, SGD, JPY). Only shown when one currency is in the selection."),
    ("Month-end rate", "Closing exchange rate for a currency and month (local currency per 1 GBP). Translates actuals in the default view."),
    ("Plan rate", "Budget exchange rate, fixed for each fiscal year. Budget is always translated at it."),
    ("Rate scenario", "Which rate translates actuals: Actual (month-end), Plan, Prior year (same month last year) or Estimate (latest month-end rate held flat). Budget stays at plan."),
    ("Reported variance", "Actual minus budget, both in cGBP as reported. Positive = overspend."),
    ("Underlying variance", "Actual minus budget with both at plan rates: the part managers control. Positive = overspend."),
    ("FX translation impact", "Actual at the selected rate minus actual at plan rate. Reported variance = underlying variance + FX impact."),
    ("Constant FX (YoY)", "Year-on-year growth with this year's actuals at last year's rates, so currency moves do not distort growth."),
    ("Spend per FTE", "IT spend divided by average business FTE (all employees), annualised so any period compares with a full year."),
    ("Run vs Change", "Run - Technology (subscriptions, cloud, applications), Run - People (IT staff, contractors) and Change (technology projects)."),
    ("Shelfware / unused licence cost", "Licence cost of seats with no active user in the month: (seats - active users) / seats x cost."),
    ("Value at stake", "Money the four recommended actions could recover in the period (unused licences, cloud overspend, contractor premium, project overruns)."),
    ("Outturn", "Year-end forecast as at a month: actual year to date plus budget for the remaining months."),
    ("Run-rate outturn", "Alternative year-end forecast: actual year to date / months elapsed x 12. Shown next to the budget-based outturn."),
    ("Recoverable value", "Value at stake x the assumed recovery % of each action (licences 60%, cloud 50%, contractors 30%, project overruns 25%)."),
    ("Realisable in 12 months", "Recoverable value landing within 12 months: licences only where the renewal falls in the window; other actions use an assumed timing share."),
    ("Materiality (variance flag)", "A variance is coloured red/green only when it breaches BOTH a % of budget and a cGBP amount (default over 2% and £50K; selectable on page 1)."),
    ("Benchmark (illustrative)", "Peer range for IT spend per FTE (£7,000-£11,000) and a 30% change-share target: planning assumptions, not sourced industry data."),
    ("Capitalised project spend", "Technology project spend x an assumed 60% capitalisation rate; the rest, and all run spend, is the opex (P&L) impact."),
    ("Budget holder", "Role accountable for a department's IT spend (e.g. Finance Director), shown on the hover detail."),
    ("Earned value (EV)", "Budgeted cost of the work actually completed, supplied by project controls."),
    ("CPI", "Cost performance index = EV / actual cost. Above 1 = more work done than money spent."),
    ("SPI", "Schedule performance index = EV / planned value. Below 1 = behind plan."),
    ("BAC / EAC", "Budget at completion (approved total project budget) and estimate at completion (BAC / CPI for in-flight projects; actual cost once past the planned end)."),
    ("Cost per story point", "Project cost / story points delivered. Shown to explain why it misleads: points are team-relative estimates and inflate when targeted."),
    ("Budget holder (RLS)", "Users in the 'Department Budget Holder' role see only the departments mapped to their sign-in."),
]


# Dynamic titles/subtitles are measures; describe what they show
DYNAMIC_TEXT = {
    "Title Matrix": "Spend vs budget by *(Analyse by selection)*",
    "Title Explorer": "*(Show selection)* by *(Analyse by selection)*",
    "Subtitle Context": "Selected fiscal year (adds local currency or the FX scenario when not the default)",
    "Subtitle Matrix": "Selected fiscal year · at budget FX · coloured when the selected materiality is breached (default over 2% and £50K)",
    "Subtitle Explorer": "Selected fiscal year, plus a note when the combination is empty or easy to misread "
                         "(no variance by vendor; per FTE divides by all employees; change % is 0 or 100% by category)",
}


def tmdl_objects(text: str, keyword: str):
    """Yield (name, description, body) for each `keyword` object (table/column/measure) in a TMDL file."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(rf"^(\t*){keyword} (.+?)(?: =(.*))?$", line)
        if not m:
            continue
        indent = m.group(1)
        name = m.group(2).strip().strip("'")
        doc, j = [], i - 1
        while j >= 0 and lines[j].strip().startswith("///"):
            doc.insert(0, lines[j].strip()[3:].strip())
            j -= 1
        body = [m.group(3) or ""]
        k = i + 1
        while k < len(lines) and (lines[k].startswith(indent + "\t") or not lines[k].strip()):
            if lines[k].strip().startswith("///") and lines[k].startswith(indent + "\t") and not lines[k].startswith(indent + "\t\t"):
                break
            body.append(lines[k])
            k += 1
        yield name, " ".join(doc), "\n".join(body)


def prop(body: str, key: str) -> str | None:
    m = re.search(rf"^\t+{key}: (.+)$", body, re.M)
    return m.group(1).strip() if m else None


def measure_dax(body: str) -> str:
    """The DAX expression: the first line plus the deeper-indented continuation lines, before the properties."""
    first, *rest = body.split("\n")
    expr = [first.strip()] if first.strip() else []
    for line in rest:
        if re.match(r"^\t\t[a-zA-Z]", line) or line.strip().startswith("formatStringDefinition"):
            break
        if line.strip():
            expr.append(line[3:] if line.startswith("\t\t\t") else line.strip())
    return "\n".join(expr).strip()


_scale = open(os.path.join(MODEL, "tables", "Scale.tmdl"), encoding="utf-8").read()
_lists = re.findall(r"IN \{([^}]*)\}", _scale.split("calculationItem Thousands")[0])
SCALED = set(re.findall(r'"([^"]+)"', _lists[0])) if _lists else set()
SMALL = set()  # licence costs now follow Units like every other total


def fmt_kind(body: str, name: str = "") -> str:
    """Describe a measure's format, using the Scale calculation group's measure lists for scaling."""
    if name in SMALL:
        return "Money (selected currency; thousands under Millions in cGBP)"
    if name in SCALED:
        return "Money in cGBP, scaled by Units" if "Currency View" not in body else "Money (selected currency), scaled by Units"
    if "formatStringDefinition" in body and "Currency View" in body:
        return "Money per unit (selected currency, never scaled)"
    f = prop(body, "formatString") or ""
    if "%" in f:
        return "Percentage"
    if f in ("0.00",):
        return "Ratio"
    if "£" in f:
        return "Money in cGBP"
    return "Number" if f else "Text"


# ---------------------------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------------------------
tables = {}
for path in sorted(glob.glob(os.path.join(MODEL, "tables", "*.tmdl"))):
    text = open(path, encoding="utf-8").read()
    tname, tdesc, tbody = next(tmdl_objects(text, "table"))
    cols = [(n, d, prop(b, "dataType"), "isHidden" in b.split("\n\t\t")[0:12].__str__() or bool(re.search(r"^\t\tisHidden", b, re.M)))
            for n, d, b in tmdl_objects(text, "\tcolumn")]
    meas = [(n, d, b) for n, d, b in tmdl_objects(text, "\tmeasure")]
    tables[tname] = {"desc": tdesc, "cols": cols, "measures": meas,
                     "hidden": bool(re.search(r"^\tisHidden", tbody, re.M)),
                     "calculated": "= calculated" in text}

rels = re.findall(r"fromColumn: (.+?)\n\ttoColumn: (.+?)\n", open(os.path.join(MODEL, "relationships.tmdl"), encoding="utf-8").read() + "\n")
roles = []
for path in glob.glob(os.path.join(MODEL, "roles", "*.tmdl")):
    text = open(path, encoding="utf-8").read()
    rname, rdesc, _ = next(tmdl_objects(text, "role"))
    perms = re.findall(r"tablePermission (.+?) = (.+)", text)
    roles.append((rname, rdesc, perms))

# ---------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------
def lit(o):
    e = (o or {}).get("expr", {})
    if "Literal" in e:
        return e["Literal"]["Value"].strip("'").replace("''", "'")
    if "Measure" in e:
        return DYNAMIC_TEXT.get(e["Measure"]["Property"], f"(from [{e['Measure']['Property']}])")
    return ""


pages = []
for pdir in sorted(glob.glob(os.path.join(PAGES, "*", ""))):
    page = json.load(open(os.path.join(pdir, "page.json"), encoding="utf-8"))
    visuals = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(pdir, "visuals", "*", "visual.json"))]
    visuals.sort(key=lambda v: (v["position"]["y"], v["position"]["x"]))
    header = next((v for v in visuals if v["name"] == "hdrTitle"), None)
    paras = header["visual"]["objects"]["general"][0]["properties"]["paragraphs"] if header else []
    question = paras[0]["textRuns"][0]["value"] if paras else ""
    sub = paras[1]["textRuns"][0]["value"] if len(paras) > 1 else ""
    rows, slicers = [], []
    for v in visuals:
        vis, vco = v["visual"], v["visual"].get("visualContainerObjects", {})
        vt = vis["visualType"]
        if vt in ("slicer", "listSlicer"):
            proj = vis["query"]["queryState"]["Values"]["projections"]
            fields = " › ".join(p["queryRef"].replace(".", "[", 1) + "]" for p in proj)
            label = lit(vis.get("objects", {}).get("header", [{}])[0].get("properties", {}).get("text")) or proj[0].get("displayName", "")
            single = "strictSingleSelect" in json.dumps(vis.get("objects", {}).get("selection", [])) and '"true"' in json.dumps(vis.get("objects", {}).get("selection", []))
            slicers.append((label, fields, "single" if single else "multi"))
            continue
        t = vco.get("title", [{}])[0].get("properties", {})
        if lit(t.get("show")) != "true" or "text" not in t:
            continue
        st = lit(vco.get("subTitle", [{}])[0].get("properties", {}).get("text"))
        q = vis.get("query", {}).get("queryState", {})
        fields = []
        for role in q.values():
            names = [p.get("displayName") or p["queryRef"].split(".", 1)[1] for p in role.get("projections", [])]
            if role.get("fieldParameters"):  # one field at a time, chosen by the parameter's slicer
                param = role["fieldParameters"][0]["parameterExpr"]["Column"]["Property"]
                names = [f"*{param}* selection"]
            fields += names
        rows.append((lit(t.get("text")), st, vt, ", ".join(dict.fromkeys(fields))))
    kpis = [v["visual"]["query"]["queryState"]["Data"]["projections"][0].get("displayName")
            for v in visuals if v["name"].startswith("kpi")]
    pages.append((page["displayName"], question, sub, kpis, rows, slicers))

# ---------------------------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------------------------
out = ["# Data dictionary: Global IT Spend Analytics", "",
       "Generated by `scripts/build_data_dictionary.py` from the PBIP model and report. Re-run it after changing",
       "either, so this file always matches what is published..", "",
       "**Contents:** 1. Report guide · 2. Filters · 3. Metrics · 4. Tables and columns · 5. Relationships and security · 6. Glossary", ""]

out += ["## 1. Report guide", ""]
for name, question, sub, kpis, rows, _ in pages:
    out += [f"### {name}: {question}", "", f"*{sub}*", ""]
    if kpis:
        out += ["**KPI tiles:** " + " · ".join(kpis), ""]
    out += ["| Visual | How to read it | Type | Fields |", "|---|---|---|---|"]
    for t, st, vt, fields in rows:
        out.append(f"| {t} | {st or '-'} | {vt} | {fields} |")
    out.append("")
out += ["Every page also has a headline sentence (a DAX text measure) under the title, written in cGBP.", ""]

out += ["## 2. Filters", "", "The top-bar slicers are synced across all three pages.", "",
        "| Slicer | Field(s) | Selection |", "|---|---|---|"]
for label, fields, sel in pages[0][5]:
    out.append(f"| {label} | `{fields}` | {sel} |")
out += ["", "Page 1 *Analyse spend by* and page 2 *Analyse by* / *Show* are field parameters (`Analyse By`, `Show`): they",
        "switch the dimension or measure that a visual uses, rather than filtering data.", ""]

out += ["## 3. Metrics", "",
        "Visible measures, grouped by display folder. Money measures follow the *Currency* slicer (cGBP or local) and the",
        "*Units* slicer, unless stated. Hidden building blocks are listed after them.", ""]
measures = tables["_Measures"]["measures"]
visible = [(n, d, b) for n, d, b in measures if not re.search(r"^\t\tisHidden", b, re.M)]
hidden = [(n, d, b) for n, d, b in measures if re.search(r"^\t\tisHidden", b, re.M)]
folders = sorted({prop(b, "displayFolder") or "" for _, _, b in visible})
for folder in folders:
    out += [f"### {folder}", "", "| Measure | Definition | Format | Logic (DAX) |", "|---|---|---|---|"]
    for n, d, b in visible:
        if (prop(b, "displayFolder") or "") != folder:
            continue
        dax = measure_dax(b).replace("|", "\\|").replace("\n", " ")
        dax = re.sub(r"\s+", " ", dax)
        if len(dax) > 160:
            dax = dax[:157] + "..."
        out.append(f"| **{n}** | {d} | {fmt_kind(b, n)} | `{dax}` |")
    out.append("")
out += ["### Hidden building blocks", "", "| Measure | Purpose |", "|---|---|"]
for n, d, b in hidden:
    out.append(f"| {n} | {d or '-'} |")
out.append("")

out += ["## 4. Tables and columns", ""]
order = ["IT Spend", "IT Budget", "Headcount", "Licence", "Project Delivery", "Date", "Entity", "Department", "Cost Category",
         "Vendor", "Product", "Project", "FX Rate", "Reporting Currency", "Rate Scenario", "Scale", "Analyse By", "Show",
         "Bridge Step", "Recommended Action", "Security Map"]
for tname in order + [t for t in tables if t not in order and t != "_Measures"]:
    if tname not in tables:
        continue
    tb = tables[tname]
    kind = "calculated table" if tb["calculated"] else ("hidden table" if tb["hidden"] else "table")
    out += [f"### {tname} ({kind})", "", tb["desc"] or "", ""]
    vis_cols = [(n, d, dt) for n, d, dt, h in tb["cols"] if not h]
    if vis_cols:
        out += ["| Column | Type | Description |", "|---|---|---|"]
        out += [f"| {n} | {dt} | {d or '-'} |" for n, d, dt in vis_cols]
        out.append("")
    hidden_cols = [n for n, d, dt, h in tb["cols"] if h]
    if hidden_cols:
        out += ["Hidden columns (used by measures, keys and sorting): " + ", ".join(hidden_cols), ""]

out += ["## 5. Relationships and security", "",
        "All relationships are many-to-one, single direction (dimension filters fact).", "",
        "| From (many) | To (one) |", "|---|---|"]
out += [f"| {a} | {b_} |" for a, b_ in rels]
out += ["", "**Row-level security**", ""]
for rname, rdesc, perms in roles:
    out += [f"- **{rname}**: {rdesc}"]
    out += [f"  - `{tbl}`: `{expr.strip()}`" for tbl, expr in perms]
out.append("")

out += ["## 6. Glossary", "", "| Term | Meaning |", "|---|---|"]
out += [f"| {k} | {v} |" for k, v in GLOSSARY]
out.append("")

os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
print(f"Dictionary: {len(visible)} visible measures, {len(hidden)} helpers, {len(tables) - 1} tables, {len(pages)} pages")


# ---------------------------------------------------------------------------------------------
# Excel version: one sheet per section, same content
# ---------------------------------------------------------------------------------------------
def write_xlsx(path: str):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    head_font, body_font = Font(name="Arial", bold=True, color="FFFFFF", size=10), Font(name="Arial", size=10)
    head_fill = PatternFill("solid", fgColor="1F2933")
    group_fill = PatternFill("solid", fgColor="EAF2FB")
    thin = Border(bottom=Side(style="thin", color="DDE3EA"))
    wrap = Alignment(wrap_text=True, vertical="top")

    def plain(text: str) -> str:
        text = (text or "").replace("*", "").replace("`", "").replace("\t", "    ")
        return " " + text if text.startswith("=") else text  # never let Excel read text as a formula

    def sheet(wb, name, headers, rows, widths, intro=None, group_col=None):
        ws = wb.create_sheet(name)
        r = 1
        if intro:
            ws.cell(r, 1, intro).font = Font(name="Arial", italic=True, size=10, color="52514E")
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
            ws.row_dimensions[r].height = 30
            ws.cell(r, 1).alignment = wrap
            r += 2
        for c, h in enumerate(headers, 1):
            cell = ws.cell(r, c, h)
            cell.font, cell.fill, cell.alignment = head_font, head_fill, wrap
        top = r
        last_group = None
        for row in rows:
            r += 1
            for c, v in enumerate(row, 1):
                cell = ws.cell(r, c, plain(v) if isinstance(v, str) else v)
                cell.font, cell.alignment, cell.border = body_font, wrap, thin
            if group_col is not None and row[group_col] != last_group:
                for c in range(1, len(headers) + 1):
                    ws.cell(r, c).fill = group_fill
                last_group = row[group_col]
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w
        ws.freeze_panes = ws.cell(top + 1, 1)
        ws.auto_filter.ref = f"A{top}:{get_column_letter(len(headers))}{r}"
        return ws

    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    lines = [("Data dictionary: Global IT Spend Analytics", Font(name="Arial", bold=True, size=14)),
             ("Generated by scripts/build_data_dictionary.py from the PBIP model and report; re-run after changes.", body_font),
             
             ("Sheets", Font(name="Arial", bold=True, size=10)),
             ("Report guide: every page, its question, KPI tiles and each visual (what it shows, how to read it, fields)", body_font),
             ("Filters: the slicers, the fields they use and single/multi selection", body_font),
             ("Metrics: every visible measure with its definition, format and DAX logic; then hidden helper measures", body_font),
             ("Tables & columns: every table and column with type and description", body_font),
             ("Relationships & security: model relationships and the row-level security role", body_font),
             ("Glossary: the business terms used on the report", body_font)]
    for i, (text, font) in enumerate(lines, 1):
        ws.cell(i, 1, text).font = font
    ws.column_dimensions["A"].width = 110

    guide = []
    for name, question, sub_, kpis, rows, _ in pages:
        guide.append((name, question, "KPI tiles", "Headline sentence + KPI row", "cardVisual", " · ".join(kpis)))
        guide += [(name, question, t, st or "-", vt, fields) for t, st, vt, fields in rows]
    sheet(wb, "Report guide", ["Page", "Question it answers", "Visual", "How to read it", "Visual type", "Fields"],
          guide, [18, 26, 38, 52, 16, 60], group_col=0,
          intro="Each page opens with a headline sentence (DAX text measure, in cGBP). Dynamic titles follow the slicer and field-parameter selections.")
    sheet(wb, "Filters", ["Slicer", "Field(s)", "Selection", "Pages"],
          [(l, f, s_, "All (synced)") for l, f, s_ in pages[0][5]]
          + [("Analyse spend by / Analyse by", "Analyse By field parameter", "single", "1. Overview, 2. Spend & savings"),
             ("Show", "Show field parameter", "single", "2. Spend & savings")],
          [30, 60, 12, 30],
          intro="Field parameters (Analyse By, Show) switch the dimension or measure a visual uses; they do not filter data.")
    metric_rows = []
    for folder in folders:
        for n, d, b in visible:
            if (prop(b, "displayFolder") or "") == folder:
                metric_rows.append((folder, n, d, fmt_kind(b, n), measure_dax(b)))
    metric_rows += [("Hidden helpers", n, d or "-", fmt_kind(b, n), measure_dax(b)) for n, d, b in hidden]
    sheet(wb, "Metrics", ["Display folder", "Measure", "Definition", "Format", "Logic (DAX)"],
          metric_rows, [20, 32, 60, 26, 80], group_col=0,
          intro="Money measures follow the Currency slicer (cGBP or local currency) and the Units slicer unless the format says otherwise.")
    col_rows = []
    for tname in order + [t for t in tables if t not in order and t != "_Measures"]:
        if tname not in tables:
            continue
        tb = tables[tname]
        kind = "Calculated table" if tb["calculated"] else ("Hidden table" if tb["hidden"] else "Table")
        col_rows.append((tname, "(table)", kind, "", tb["desc"]))
        col_rows += [(tname, n, dt, "Hidden" if h else "Visible", d or "-") for n, d, dt, h in tb["cols"]]
    sheet(wb, "Tables & columns", ["Table", "Column", "Data type", "Visibility", "Description"],
          col_rows, [22, 28, 16, 12, 90], group_col=0)
    sec = [("Relationship", a, b_, "Many-to-one, single direction") for a, b_ in rels]
    for rname, rdesc, perms in roles:
        sec += [("Row-level security: " + rname, tbl, expr.strip(), rdesc) for tbl, expr in perms]
    sheet(wb, "Relationships & security", ["Type", "From (many) / table", "To (one) / filter", "Notes"],
          sec, [36, 36, 70, 60], group_col=0)
    sheet(wb, "Glossary", ["Term", "Meaning"], GLOSSARY, [32, 110])
    wb.save(path)


XLSX = os.path.join(ROOT, "docs", "IT Spend Analytics - Data Dictionary.xlsx")
try:
    write_xlsx(XLSX)
    print(f"Wrote {os.path.relpath(XLSX, ROOT)}")
except ImportError:
    print("openpyxl not installed: skipped the Excel version (pip install openpyxl)")
