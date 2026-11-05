"""
Independent reconciliation of the key report numbers, computed straight from the CSVs
with pandas (no Power BI). Run the matching DAX query in validation/validation_queries.dax
in Power BI Desktop (DAX query view) and compare: the results should agree to the penny
(rounding aside).

Usage:  python scripts/reconcile.py   -> writes validation/expected_kpis.csv and prints it
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda f: os.path.join(ROOT, "data", f)

fx = pd.read_csv(D("fx_rates.csv"), parse_dates=["Month"])
# Scenario rates, built the same way as the FX Rate query: prior year = same month 12 months earlier
# (own month-end rate when there is none), estimate = latest month-end rate per currency
py = fx[["Currency", "Month", "LCPerGBP"]].assign(Month=lambda t: t.Month + pd.DateOffset(years=1)).rename(columns={"LCPerGBP": "PYLCPerGBP"})
fx = fx.merge(py, on=["Currency", "Month"], how="left")
fx["PYLCPerGBP"] = fx.PYLCPerGBP.fillna(fx.LCPerGBP)
fx["EstimateLCPerGBP"] = fx.Currency.map(fx[fx.Month == fx.Month.max()].set_index("Currency").LCPerGBP)
SCENARIOS = {"Actual": "LCPerGBP", "Plan": "BudgetLCPerGBP", "Prior year": "PYLCPerGBP", "Estimate": "EstimateLCPerGBP"}
cat = pd.read_csv(D("dim_cost_category.csv"))
prod = pd.read_csv(D("dim_product.csv"))
proj = pd.read_csv(D("dim_project.csv"))


def load(f):
    df = pd.read_csv(D(f), parse_dates=["Month"])
    df["FY"] = df.Month.apply(lambda m: f"FY{m.year if m.month >= 4 else m.year - 1}/{str((m.year if m.month >= 4 else m.year - 1) + 1)[2:]}")
    return df.merge(fx, on=["Currency", "Month"], how="left") if "Currency" in df else df


spend, budget, lic, deliv, hc = (load(f) for f in ("fact_it_spend.csv", "fact_it_budget.csv", "fact_licence.csv",
                                                     "fact_project_delivery.csv", "fact_headcount.csv"))
assert spend.LCPerGBP.notna().all() and budget.BudgetLCPerGBP.notna().all(), "every fact row must find an FX rate"

rows = []
for fy in ("FY2024/25", "FY2025/26"):
    s, bu, l, dv, h = (t[t.FY == fy] for t in (spend, budget, lic, deliv, hc))
    act = (s.AmountLC / s.LCPerGBP).sum()
    act_br = (s.AmountLC / s.BudgetLCPerGBP).sum()
    bud = (bu.BudgetLC / bu.BudgetLCPerGBP).sum()
    avg_fte = h.groupby("Month").FTE.sum().mean()
    unused = ((l.SeatsPurchased - l.ActiveUsers) / l.SeatsPurchased * l.CostLC / l.LCPerGBP).sum()
    proj_ac = (s[s.CategoryKey == "C06"].AmountLC / s[s.CategoryKey == "C06"].LCPerGBP).sum()
    ev = (dv.EarnedValueLC / dv.LCPerGBP).sum()
    pv = (dv.PlannedValueLC / dv.LCPerGBP).sum()
    kv = {
        "Actual (cGBP)": act, "Budget (cGBP)": bud, "Variance vs Budget (cGBP)": act - bud,
        "Underlying Variance (cGBP)": act_br - bud, "FX Translation Impact (cGBP)": act - act_br,
        "Average FTE": avg_fte, "IT Spend per FTE (cGBP, annualised)": act / avg_fte * 12 / s.Month.nunique(),
        "Licence Cost (cGBP)": (l.CostLC / l.LCPerGBP).sum(), "Unused Licence Cost (cGBP)": unused,
        "Licence Utilisation %": l.ActiveUsers.sum() / l.SeatsPurchased.sum(),
        "Project Actual Cost (cGBP)": proj_ac, "Earned Value (cGBP)": ev, "CPI": ev / proj_ac, "SPI": ev / pv,
        "Story Points Delivered": dv.StoryPointsDelivered.sum(),
    }
    # Executive "value at stake" by action (mirrors the Value at Stake measure)
    def underlying(cats):
        a, bb = s[s.CategoryKey.isin(cats)], bu[bu.CategoryKey.isin(cats)]
        return (a.AmountLC / a.BudgetLCPerGBP).sum() - (bb.BudgetLC / bb.BudgetLCPerGBP).sum()
    p_ac = (s[s.CategoryKey == "C06"].assign(g=lambda t: t.AmountLC / t.LCPerGBP).groupby("ProjectKey").g.sum())
    p_ev = (dv.assign(g=lambda t: t.EarnedValueLC / t.LCPerGBP).groupby("ProjectKey").g.sum())
    overrun = sum(max(0.0, p_ac.get(k, 0) - ev) for k, ev in p_ev.items())
    stake = {"Value at Stake - A1 licences": unused, "Value at Stake - A2 cloud": max(0.0, underlying(["C02"])),
             "Value at Stake - A3 contractors": max(0.0, underlying(["C04", "C05"])), "Value at Stake - A4 projects": overrun}
    kv.update(stake)
    kv["Value at Stake - total"] = sum(stake.values())
    kv["Change Spend %"] = proj_ac / act
    # Recoverable value (stake x assumed recovery %) and the part realisable within 12 months of the period end
    recovery = {"A1": (0.6, None), "A2": (0.5, 0.8), "A3": (0.3, 0.5), "A4": (0.25, 1.0)}
    stake_by = dict(zip(["A1", "A2", "A3", "A4"], stake.values()))
    renew = pd.to_datetime(prod.set_index("ProductKey").NextRenewalDate)
    window = s.Month.max() + pd.offsets.MonthEnd(0) + pd.DateOffset(months=12)
    lr = l[l.ProductKey.map(renew) <= window]
    unused_12m = ((lr.SeatsPurchased - lr.ActiveUsers) / lr.SeatsPurchased * lr.CostLC / lr.LCPerGBP).sum()
    kv["Recoverable Value"] = sum(stake_by[k] * r for k, (r, _) in recovery.items())
    kv["Realisable in 12 Months"] = sum(unused_12m * r if k == "A1" else stake_by[k] * r * w for k, (r, w) in recovery.items())
    # Estimate at completion: in-flight = BAC / project-to-date CPI; closed = project-to-date actual cost
    ptd_end = s.Month.max()
    sp, dp = spend[(spend.CategoryKey == "C06") & (spend.Month <= ptd_end)], deliv[deliv.Month <= ptd_end]
    ac_ptd = sp.assign(g=sp.AmountLC / sp.LCPerGBP).groupby("ProjectKey").g.sum()
    ev_ptd = dp.assign(g=dp.EarnedValueLC / dp.LCPerGBP).groupby("ProjectKey").g.sum()
    bac = proj.set_index("ProjectKey").BudgetAtCompletionGBP
    ended = pd.to_datetime(proj.set_index("ProjectKey").PlannedEndMonth) <= ptd_end  # closed as at the period end
    active = [k for k in p_ac.index if k in bac and pd.notna(bac[k])]
    eac = {k: ac_ptd[k] if ended[k] else bac[k] / (ev_ptd[k] / ac_ptd[k]) for k in active}
    kv["Budget at Completion"] = sum(bac[k] for k in active)
    kv["Estimate at Completion"] = sum(eac.values())
    kv["Forecast Overrun"] = kv["Estimate at Completion"] - kv["Budget at Completion"]
    for k in active:
        kv[f"Forecast Overrun - {k}"] = eac[k] - bac[k]
    # Rate scenarios: actuals re-translated at each scenario's rate; budget stays at plan rates
    prev = spend[spend.FY == {"FY2025/26": "FY2024/25"}.get(fy, "")]
    for name, rate in SCENARIOS.items():
        a = (s.AmountLC / s[rate]).sum()
        kv[f"Scenario {name} - Actual (cGBP)"] = a
        kv[f"Scenario {name} - Variance vs Budget (cGBP)"] = a - bud
        if len(prev):  # prior-year actuals are rows from last year, translated at their own scenario rate
            kv[f"Scenario {name} - YoY Change %"] = a / (prev.AmountLC / prev[rate]).sum() - 1
    rows += [(fy, k, round(v, 4)) for k, v in kv.items()]

out = pd.DataFrame(rows, columns=["FiscalYear", "Measure", "Expected"])
# Licence cost must reconcile to Software Subscriptions in the spend ledger
sub = spend[spend.CategoryKey == "C01"]
gap = (sub.AmountLC / sub.LCPerGBP).sum() - (lic.CostLC / lic.LCPerGBP).sum()
assert abs(gap) < 1, f"licence fact does not reconcile to ledger: {gap}"
out.to_csv(os.path.join(ROOT, "validation", "expected_kpis.csv"), index=False)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print(out.pivot(index="Measure", columns="FiscalYear", values="Expected"))
print(f"\nLicence fact reconciles to Software Subscriptions ledger (difference £{gap:,.2f})")
