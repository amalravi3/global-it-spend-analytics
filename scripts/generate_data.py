"""
Synthetic data generator for the Global IT Spend Analytics model.

Creates 24 months of data (UK fiscal years FY2024/25 and FY2025/26, April-March)
for a fictional global organisation with 7 legal entities, 5 local currencies and
7 business departments. All amounts are generated in LOCAL currency; translation
to consolidated GBP (cGBP) happens in the semantic model using month-end rates.

The data deliberately contains a few business "stories" so the report has
something real to find:
  1. Cloud overrun in Americas (no FinOps guard-rails on the data platform migration)
  2. Contractor overspend that mirrors an IT-employee underspend (vacancy backfill)
  3. Licence shelfware: Zoom (overlap with Teams), Adobe, Tableau, Salesforce in Europe
  4. A project with the best cost per story point but the worst cost performance (CPI)
  5. GBP strengthening vs USD / INR / JPY, flattering the reported cGBP variance

Deterministic: fixed random seed, so re-running produces identical files.
Usage:  python scripts/generate_data.py   (writes CSVs to ./data and ./validation)
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
VALID = os.path.join(ROOT, "validation")
rng = np.random.default_rng(20250401)

# --------------------------------------------------------------------------------------
# Calendar: Apr-2024 .. Mar-2026 (two UK fiscal years)
# --------------------------------------------------------------------------------------
MONTHS = [date(2024 + (3 + i) // 12, (3 + i) % 12 + 1, 1) for i in range(24)]


def fiscal_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY{start}/{str(start + 1)[2:]}"


FY1, FY2 = "FY2024/25", "FY2025/26"

# --------------------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------------------
ENTITIES = [
    # key, entity, country, region, currency, starting FTE, monthly FTE growth, cost level vs UK
    ("UK01", "UK - London (Group HQ)", "United Kingdom", "UK & Ireland", "GBP", 1800, 0.0030, 1.00),
    ("DE01", "Germany - Frankfurt", "Germany", "Europe", "EUR", 700, 0.0025, 1.05),
    ("FR01", "France - Paris", "France", "Europe", "EUR", 500, 0.0015, 1.00),
    ("US01", "United States - New York", "United States", "Americas", "USD", 1500, 0.0035, 1.25),
    ("IN01", "India - Bengaluru", "India", "APAC", "INR", 1300, 0.0080, 0.45),
    ("SG01", "Singapore", "Singapore", "APAC", "SGD", 350, 0.0030, 0.95),
    ("JP01", "Japan - Tokyo", "Japan", "APAC", "JPY", 300, 0.0000, 1.00),
]
ENT = {e[0]: e for e in ENTITIES}

CURRENCIES = {
    "GBP": ("Pound sterling", "£"),
    "EUR": ("Euro", "€"),
    "USD": ("US dollar", "$"),
    "INR": ("Indian rupee", "₹"),
    "SGD": ("Singapore dollar", "S$"),
    "JPY": ("Japanese yen", "¥"),
}

DEPARTMENTS = [
    # key, name, group, default headcount mix
    ("D01", "Finance", "Corporate functions", 0.10),
    ("D02", "Human Resources", "Corporate functions", 0.05),
    ("D03", "Legal & Compliance", "Corporate functions", 0.04),
    ("D04", "Sales & Marketing", "Customer-facing", 0.22),
    ("D05", "Customer Service", "Customer-facing", 0.14),
    ("D06", "Operations", "Operations & Technology", 0.25),
    ("D07", "Product & Technology", "Operations & Technology", 0.20),
]
# Budget holder (a role, not a named person) accountable for each department's IT spend
BUDGET_HOLDER = {"D01": "Finance Director", "D02": "HR Director", "D03": "General Counsel",
                 "D04": "Chief Commercial Officer", "D05": "Head of Customer Service",
                 "D06": "Operations Director", "D07": "Chief Product Officer"}
DEPT_NAME = {d[0]: d[1] for d in DEPARTMENTS}

# Entity-specific tilt of the department mix (multipliers, re-normalised)
MIX_TILT = {
    "US01": {"D04": 1.35, "D06": 0.85},
    "IN01": {"D07": 1.6, "D05": 1.5, "D04": 0.4, "D06": 1.1},
    "SG01": {"D06": 1.3, "D04": 1.1},
    "JP01": {"D04": 1.3, "D07": 0.6},
    "DE01": {"D06": 1.2},
    "UK01": {"D01": 1.4, "D02": 1.3, "D03": 1.5},
}

CATEGORIES = [
    # key, name, group, sort
    ("C01", "Software Subscriptions", "Run - Technology", 1),
    ("C02", "Cloud Services", "Run - Technology", 2),
    ("C03", "Applications & Maintenance", "Run - Technology", 3),
    ("C04", "IT Employees", "Run - People", 4),
    ("C05", "IT Contractors", "Run - People", 5),
    ("C06", "Technology Projects", "Change", 6),
]

VENDORS = [
    ("V01", "Microsoft", "Software & Cloud"),
    ("V02", "Salesforce", "Software (SaaS)"),
    ("V03", "ServiceNow", "Software (SaaS)"),
    ("V04", "Atlassian", "Software (SaaS)"),
    ("V05", "Adobe", "Software (SaaS)"),
    ("V06", "Zoom", "Software (SaaS)"),
    ("V07", "GitHub", "Software (SaaS)"),
    ("V08", "Amazon Web Services", "Cloud"),
    ("V09", "SAP", "Enterprise application"),
    ("V10", "Workday", "Enterprise application"),
    ("V11", "Internal - IT payroll", "Internal"),
    ("V12", "Apex Technical Resourcing", "Contractor agency"),
    ("V13", "Meridian Talent Partners", "Contractor agency"),
    ("V14", "Kaveri IT Services", "Contractor agency"),
    ("V15", "Northbridge Consulting", "Delivery partner"),
    ("V16", "Bluefield Digital", "Delivery partner"),
]

# Licence products: key, product, vendor key, GBP list price per seat per month,
# seat ratio per department (seats per FTE), renewal month, base utilisation
PRODUCTS = [
    ("PR01", "Microsoft 365 E3", "V01", 30.0, {d[0]: 1.0 for d in DEPARTMENTS}, date(2026, 6, 1), 0.96),
    ("PR02", "Salesforce Sales Cloud", "V02", 120.0, {"D04": 0.90, "D05": 0.50}, date(2026, 9, 1), 0.86),
    ("PR03", "ServiceNow ITSM", "V03", 85.0, {"D07": 0.30, "D06": 0.15}, date(2027, 1, 1), 0.84),
    ("PR04", "Atlassian Jira & Confluence", "V04", 12.0, {"D07": 1.00, "D06": 0.30}, date(2026, 10, 1), 0.91),
    ("PR05", "Adobe Creative Cloud", "V05", 70.0, {"D04": 0.25}, date(2026, 8, 1), 0.47),
    ("PR06", "Zoom Workplace", "V06", 15.0, {d[0]: 0.35 for d in DEPARTMENTS}, date(2026, 7, 1), 0.55),
    ("PR07", "Tableau Creator", "V02", 60.0, {"D01": 0.40, "D06": 0.10}, date(2026, 11, 1), 0.53),
    ("PR08", "GitHub Enterprise", "V07", 17.0, {"D07": 0.90}, date(2027, 2, 1), 0.93),
]

PROJECTS = [
    # key, name, entity, sponsor dept, delivery partner, start, end, BAC (GBP),
    # target SPI, target CPI, story points per month at start, monthly velocity drift
    ("P001", "Customer Portal Rebuild", "US01", "D05", "V16", date(2024, 7, 1), date(2026, 6, 1), 4_000_000, 0.93, 0.78, 110, 0.025),
    ("P002", "S/4HANA Finance Upgrade", "UK01", "D01", "V15", date(2024, 4, 1), date(2025, 12, 1), 3_500_000, 0.98, 1.02, 28, 0.000),
    ("P003", "Data Platform Modernisation", "IN01", "D07", "V15", date(2024, 10, 1), date(2026, 9, 1), 2_500_000, 0.95, 0.90, 60, 0.005),
    ("P004", "Workday HR Rollout - Europe", "DE01", "D02", "V15", date(2024, 4, 1), date(2025, 3, 1), 1_200_000, 0.99, 0.97, 24, 0.000),
    ("P005", "Zero Trust Security Programme", "UK01", "D07", "V16", date(2025, 1, 1), date(2026, 3, 1), 1_800_000, 1.00, 1.05, 34, 0.000),
    ("P006", "Warehouse Automation", "SG01", "D06", "V16", date(2025, 6, 1), date(2026, 5, 1), 1_500_000, 0.85, 0.95, 40, 0.000),
]

# --------------------------------------------------------------------------------------
# Exchange rates: local currency units per 1 GBP (market convention), month-end.
# Anchors are interpolated monthly with small noise; budget rates fixed per fiscal year.
# --------------------------------------------------------------------------------------
FX_ANCHORS = {  # (month index, rate)
    "USD": [(0, 1.250), (5, 1.270), (11, 1.290), (17, 1.350), (23, 1.360)],
    "EUR": [(0, 1.170), (5, 1.185), (11, 1.190), (17, 1.150), (23, 1.140)],
    "INR": [(0, 104.0), (5, 106.0), (11, 110.5), (17, 118.0), (23, 121.5)],
    "SGD": [(0, 1.700), (5, 1.705), (11, 1.720), (17, 1.740), (23, 1.750)],
    "JPY": [(0, 190.0), (5, 193.0), (11, 192.0), (17, 199.0), (23, 205.0)],
}
BUDGET_RATES = {
    FY1: {"GBP": 1.0, "USD": 1.26, "EUR": 1.16, "INR": 104.0, "SGD": 1.70, "JPY": 185.0},
    FY2: {"GBP": 1.0, "USD": 1.27, "EUR": 1.18, "INR": 108.0, "SGD": 1.71, "JPY": 192.0},
}


def build_fx() -> dict[tuple[str, date], float]:
    fx = {}
    for cur, anchors in FX_ANCHORS.items():
        xs, ys = zip(*anchors)
        path = np.interp(range(24), xs, ys)
        noise = rng.normal(0, 0.006, 24)
        for i, m in enumerate(MONTHS):
            dp = 2 if cur in ("INR", "JPY") else 4
            fx[(cur, m)] = round(float(path[i] * (1 + noise[i])), dp)
    for m in MONTHS:
        fx[("GBP", m)] = 1.0
    return fx


FX = build_fx()


def local_price(gbp_amount: float, cur: str) -> float:
    """Convert a UK-level GBP cost into a local-currency price (set at FY24/25 budget rate)."""
    return gbp_amount * BUDGET_RATES[FY1][cur]


# --------------------------------------------------------------------------------------
# Headcount (FTE, month-end snapshot)
# --------------------------------------------------------------------------------------
def dept_mix(ek: str) -> dict[str, float]:
    tilt = MIX_TILT.get(ek, {})
    raw = {d[0]: d[3] * tilt.get(d[0], 1.0) for d in DEPARTMENTS}
    tot = sum(raw.values())
    return {k: v / tot for k, v in raw.items()}


HC: dict[tuple[date, str, str], float] = {}
for ek, *_rest in ENTITIES:
    start_fte, growth = ENT[ek][5], ENT[ek][6]
    mix = dept_mix(ek)
    for i, m in enumerate(MONTHS):
        total = start_fte * (1 + growth) ** i
        for dk, share in mix.items():
            HC[(m, ek, dk)] = round(total * share * (1 + rng.normal(0, 0.004)), 1)

# --------------------------------------------------------------------------------------
# Spend generation helpers
# --------------------------------------------------------------------------------------
spend = defaultdict(float)   # (month, entity, dept, category, vendor, project) -> LC
budget = defaultdict(float)  # (month, entity, dept, category, project) -> LC


def add_spend(m, ek, dk, ck, vk, pk, amt):
    spend[(m, ek, dk, ck, vk, pk)] += amt


def add_budget(m, ek, dk, ck, pk, amt):
    budget[(m, ek, dk, ck, pk)] += amt


def noise(sd=0.03):
    return float(1 + rng.normal(0, sd))


# Annual GBP cost per FTE at UK cost level, by category, and department intensity
CLOUD_PER_FTE, APPS_PER_FTE, STAFF_PER_FTE, CONTRACT_PER_FTE = 1500.0, 1200.0, 3000.0, 800.0
CLOUD_INT = {"D07": 3.0, "D06": 1.2, "D05": 0.8, "D04": 0.5, "D01": 0.4, "D02": 0.3, "D03": 0.3}
APPS_INT = {"D01": 2.2, "D02": 1.8, "D06": 1.3, "D04": 0.9, "D05": 0.7, "D03": 0.8, "D07": 0.6}
CONTRACT_INT = {"D07": 2.6, "D06": 1.1, "D05": 0.6, "D01": 0.6, "D04": 0.4, "D02": 0.3, "D03": 0.3}
CLOUD_VENDOR = {"US01": "V08", "IN01": "V08"}  # others on Microsoft Azure (V01)
AGENCY = {"UK01": "V12", "DE01": "V12", "FR01": "V12", "US01": "V13", "IN01": "V14", "SG01": "V14", "JP01": "V14"}

# FY2025/26 budget uplifts agreed in the plan (vs FY2024/25 run-rate)
PLAN_FY2 = {"C02": 1.08, "C03": 1.03, "C04": 1.045, "C05": 0.90}


def cloud_story(ek, dk, i):
    """Actual/plan multiplier for cloud: Americas data-platform migration with no FinOps."""
    if i < 12:
        return 1.0
    k = i - 12  # 0..11 within FY2025/26
    if ek == "US01" and dk in ("D07", "D06"):
        return 1.0 + min(0.60, 0.075 * max(0, k - 2))  # ramps from Jul-25 to +60%
    if ek == "IN01" and dk == "D07":
        return 1.12
    return 0.99


def staff_story(ek, i):
    """IT employees: vacancies in FY2025/26 (UK, India, US) -> underspend vs budget."""
    if i < 12:
        return 1.0
    return {"UK01": 0.90, "IN01": 0.88, "US01": 0.95}.get(ek, 0.99)


def contractor_story(ek, i):
    """Contractors backfill vacancies at a premium -> overspend where staff underspend."""
    if i < 12:
        return 1.0
    return {"UK01": 1.45, "IN01": 1.50, "US01": 1.20}.get(ek, 0.98)


# --------------------------------------------------------------------------------------
# Run costs: cloud, applications, IT employees, contractors
# --------------------------------------------------------------------------------------
for i, m in enumerate(MONTHS):
    fy = fiscal_year(m)
    for ek, _n, _c, _r, cur, _s, _g, level in ENTITIES:
        for dk, *_d in DEPARTMENTS:
            fte = HC[(m, ek, dk)]
            fte_plan = HC[(MONTHS[0 if i < 12 else 12], ek, dk)] * (1 + ENT[ek][6]) ** (i % 12)
            base = lambda per_fte, intensity: local_price(per_fte * intensity * level / 12.0, cur)

            # Cloud: organic growth 0.6%/month on top of headcount
            cloud_trend = 1.006 ** i
            plan_cloud = base(CLOUD_PER_FTE, CLOUD_INT[dk]) * fte_plan * (1.006 ** (i % 12)) * (1.0 if fy == FY1 else PLAN_FY2["C02"])
            act_cloud = base(CLOUD_PER_FTE, CLOUD_INT[dk]) * fte * cloud_trend * cloud_story(ek, dk, i) * noise(0.04)
            add_budget(m, ek, dk, "C02", "P000", plan_cloud)
            add_spend(m, ek, dk, "C02", CLOUD_VENDOR.get(ek, "V01"), "P000", act_cloud)

            # Applications & maintenance: SAP for Finance/Operations/others, Workday for HR-related usage
            apps_total = base(APPS_PER_FTE, APPS_INT[dk]) * fte
            plan_apps = base(APPS_PER_FTE, APPS_INT[dk]) * fte_plan * (1.0 if fy == FY1 else PLAN_FY2["C03"])
            uplift = 1.0 if fy == FY1 else 1.035
            sap_share = 0.25 if dk == "D02" else 0.75
            add_budget(m, ek, dk, "C03", "P000", plan_apps)
            add_spend(m, ek, dk, "C03", "V09", "P000", apps_total * uplift * sap_share * noise(0.015))
            add_spend(m, ek, dk, "C03", "V10", "P000", apps_total * uplift * (1 - sap_share) * noise(0.015))

            # IT employees (internal IT staff cost allocated to departments on headcount)
            pay = 1.0 if fy == FY1 else 1.045
            plan_staff = base(STAFF_PER_FTE, 1.0) * fte_plan * (1.0 if fy == FY1 else PLAN_FY2["C04"])
            act_staff = base(STAFF_PER_FTE, 1.0) * fte * pay * staff_story(ek, i) * noise(0.015)
            add_budget(m, ek, dk, "C04", "P000", plan_staff)
            add_spend(m, ek, dk, "C04", "V11", "P000", act_staff)

            # IT contractors
            plan_con = base(CONTRACT_PER_FTE, CONTRACT_INT[dk]) * fte_plan * (1.0 if fy == FY1 else PLAN_FY2["C05"])
            act_con = base(CONTRACT_PER_FTE, CONTRACT_INT[dk]) * fte * contractor_story(ek, i) * noise(0.06)
            add_budget(m, ek, dk, "C05", "P000", plan_con)
            add_spend(m, ek, dk, "C05", AGENCY[ek], "P000", act_con)

# --------------------------------------------------------------------------------------
# Software subscriptions (licence fact drives subscription spend)
# --------------------------------------------------------------------------------------
licence_rows = []
for pk, pname, vk, price_gbp, ratios, _renew, base_util in PRODUCTS:
    for ek, _n, _c, region, cur, *_x in ENTITIES:
        for dk, ratio in ratios.items():
            for fy_start in (0, 12):
                # Seats are contracted for the fiscal year at start-of-year FTE x ratio + 5% buffer
                seats = int(round(HC[(MONTHS[fy_start], ek, dk)] * ratio * 1.05))
                if seats == 0:
                    continue
                price_lc = local_price(price_gbp, cur) * (1.0 if fy_start == 0 else 1.04)  # 4% price rise
                plan_price = local_price(price_gbp, cur) * (1.0 if fy_start == 0 else 1.04)
                for i in range(fy_start, fy_start + 12):
                    m = MONTHS[i]
                    util = base_util
                    if pk == "PR02" and region == "Europe":
                        util = 0.60
                    if pk == "PR06":
                        util = max(0.22, 0.55 - 0.014 * i)  # Teams adoption erodes Zoom usage
                    eligible = HC[(m, ek, dk)] * ratio
                    active = int(min(seats, round(eligible * util * noise(0.03))))
                    cost = seats * price_lc
                    licence_rows.append((m, ek, dk, pk, cur, seats, active, round(cost, 2)))
                    add_spend(m, ek, dk, "C01", vk, "P000", cost)
                    add_budget(m, ek, dk, "C01", "P000", seats * plan_price)

# --------------------------------------------------------------------------------------
# Technology projects: plan (PV = budget), earned value, actual cost, story points
# --------------------------------------------------------------------------------------
delivery_rows = []
for (pk, pname, ek, dk, vk, start, end, bac_gbp, spi, cpi, sp0, drift) in PROJECTS:
    cur = ENT[ek][4]
    months = [m for m in MONTHS if start <= m <= end]
    duration = (end.year - start.year) * 12 + end.month - start.month + 1
    bac_lc = local_price(bac_gbp, cur)
    # S-curve-ish planned value profile over the full project duration
    weights = np.sin(np.linspace(0.15, np.pi - 0.15, duration)) + 0.35
    weights = weights / weights.sum()
    for j in range(duration):
        m = date(start.year + (start.month - 1 + j) // 12, (start.month - 1 + j) % 12 + 1, 1)
        if m not in MONTHS:
            continue
        pv = bac_lc * weights[j]
        ev = pv * spi * noise(0.05)
        ac = ev / cpi * noise(0.04)
        k = MONTHS.index(m) - MONTHS.index(start) if start in MONTHS else j
        points = int(round(sp0 * (1 + drift) ** k * noise(0.08)))
        delivery_rows.append((m, pk, ek, dk, cur, round(pv, 2), round(ev, 2), points))
        add_budget(m, ek, dk, "C06", pk, pv)
        add_spend(m, ek, dk, "C06", vk, pk, ac)

# --------------------------------------------------------------------------------------
# Write CSVs
# short names for chart labels
PROJECT_SHORT = {"P001": "Customer Portal", "P002": "S/4HANA", "P003": "Data Platform", "P004": "Workday HR",
                 "P005": "Zero Trust", "P006": "Warehouse"}

# --------------------------------------------------------------------------------------
os.makedirs(DATA, exist_ok=True)
os.makedirs(VALID, exist_ok=True)


def write(name, header, rows):
    with open(os.path.join(DATA, name), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"{name:32s} {len(rows):6d} rows")


iso = lambda d: d.isoformat()

write("dim_entity.csv", ["EntityKey", "Entity", "Country", "Region", "Currency", "CurrencyName", "CurrencySymbol"],
      [(e[0], e[1], e[2], e[3], e[4], CURRENCIES[e[4]][0], CURRENCIES[e[4]][1]) for e in ENTITIES])
write("dim_department.csv", ["DepartmentKey", "Department", "DepartmentGroup", "SortOrder", "BudgetHolder"],
      [(d[0], d[1], d[2], i + 1, BUDGET_HOLDER[d[0]]) for i, d in enumerate(DEPARTMENTS)])
write("dim_cost_category.csv", ["CategoryKey", "Category", "CategoryGroup", "SortOrder"], CATEGORIES)
write("dim_vendor.csv", ["VendorKey", "Vendor", "VendorType"], VENDORS)
vname = {v[0]: v[1] for v in VENDORS}
write("dim_product.csv", ["ProductKey", "Product", "Vendor", "ListPriceGBPPerSeatMonth", "NextRenewalDate"],
      [(p[0], p[1], vname[p[2]], p[3], iso(p[5])) for p in PRODUCTS])
write("dim_project.csv", ["ProjectKey", "Project", "ProjectEntity", "SponsorDepartment", "DeliveryPartner",
                          "StartMonth", "PlannedEndMonth", "Status", "BudgetAtCompletionGBP", "ProjectShort"],
      [("P000", "Run costs (no project)", "", "", "", "", "", "n/a", "", "Run costs")] +
      [(p[0], p[1], ENT[p[2]][1], DEPT_NAME[p[3]], vname[p[4]], iso(p[5]), iso(p[6]),
        "Closed" if p[6] < date(2026, 4, 1) else "In flight", p[7], PROJECT_SHORT[p[0]]) for p in PROJECTS])
# Row-level security: which budget holder (user principal name) may see which department(s)
write("security_map.csv", ["UserPrincipalName", "Department"],
      [("finance.budgetholder@example.com", "Finance"),
       ("ops.director@example.com", "Operations"),
       ("cto.office@example.com", "Product & Technology"),
       ("cto.office@example.com", "Operations")])
# Row-level security by region: which regional manager may see which region(s)
write("region_security_map.csv", ["UserPrincipalName", "Region"],
      [("americas.head@example.com", "Americas"),
       ("apac.head@example.com", "APAC"),
       ("europe.head@example.com", "Europe"),
       ("europe.head@example.com", "UK & Ireland"),
       ("uk.finance@example.com", "UK & Ireland")])

write("fx_rates.csv", ["Currency", "Month", "LCPerGBP", "BudgetLCPerGBP"],
      [(c, iso(m), FX[(c, m)], BUDGET_RATES[fiscal_year(m)][c]) for c in CURRENCIES for m in MONTHS])
write("fact_headcount.csv", ["Month", "EntityKey", "DepartmentKey", "FTE"],
      [(iso(m), e, d, v) for (m, e, d), v in sorted(HC.items())])
cur_of = {e[0]: e[4] for e in ENTITIES}
write("fact_it_spend.csv", ["Month", "EntityKey", "DepartmentKey", "CategoryKey", "VendorKey", "ProjectKey", "Currency", "AmountLC"],
      [(iso(k[0]), k[1], k[2], k[3], k[4], k[5], cur_of[k[1]], round(v, 2)) for k, v in sorted(spend.items())])
write("fact_it_budget.csv", ["Month", "EntityKey", "DepartmentKey", "CategoryKey", "ProjectKey", "Currency", "BudgetLC"],
      [(iso(k[0]), k[1], k[2], k[3], k[4], cur_of[k[1]], round(v, 2)) for k, v in sorted(budget.items())])
write("fact_licence.csv", ["Month", "EntityKey", "DepartmentKey", "ProductKey", "Currency", "SeatsPurchased", "ActiveUsers", "CostLC"],
      [(iso(r[0]),) + r[1:] for r in sorted(licence_rows)])
write("fact_project_delivery.csv", ["Month", "ProjectKey", "EntityKey", "DepartmentKey", "Currency",
                                    "PlannedValueLC", "EarnedValueLC", "StoryPointsDelivered"],
      [(iso(r[0]),) + r[1:] for r in sorted(delivery_rows)])

# --------------------------------------------------------------------------------------
# Independent reconciliation totals (computed here, outside Power BI) for validation
# --------------------------------------------------------------------------------------
rows = []
for fy in (FY1, FY2):
    for cur in CURRENCIES:
        act_lc = sum(v for k, v in spend.items() if fiscal_year(k[0]) == fy and cur_of[k[1]] == cur)
        act_gbp = sum(round(v, 2) / FX[(cur, k[0])] for k, v in spend.items() if fiscal_year(k[0]) == fy and cur_of[k[1]] == cur)
        act_bud_rate = sum(round(v, 2) / BUDGET_RATES[fy][cur] for k, v in spend.items() if fiscal_year(k[0]) == fy and cur_of[k[1]] == cur)
        bud_lc = sum(v for k, v in budget.items() if fiscal_year(k[0]) == fy and cur_of[k[1]] == cur)
        bud_gbp = sum(round(v, 2) / BUDGET_RATES[fy][cur] for k, v in budget.items() if fiscal_year(k[0]) == fy and cur_of[k[1]] == cur)
        rows.append((fy, cur, round(act_lc, 2), round(act_gbp, 2), round(act_bud_rate, 2), round(bud_lc, 2), round(bud_gbp, 2)))
with open(os.path.join(VALID, "expected_totals.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["FiscalYear", "Currency", "ActualLC", "ActualCGBP_MonthEndRate", "ActualCGBP_BudgetRate", "BudgetLC", "BudgetCGBP_BudgetRate"])
    w.writerows(rows)
    for fy in (FY1, FY2):
        w.writerow([fy, "ALL (cGBP only)", "", round(sum(r[3] for r in rows if r[0] == fy), 2),
                    round(sum(r[4] for r in rows if r[0] == fy), 2), "", round(sum(r[6] for r in rows if r[0] == fy), 2)])
print("validation/expected_totals.csv written")
