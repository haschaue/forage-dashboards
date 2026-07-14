"""Forage Kitchen paid ads loop — weekly Google Ads analysis dashboard.

Google Ads data arrives via the GoMarble MCP connector (google_ads_run_gaql),
which only the weekly Claude task can call — so this script ingests raw GAQL
JSON results rather than fetching itself.

Usage:
  python ads_loop.py dates                Print the date ranges to query.
  python ads_loop.py ingest CUR PREV DAILY
                                          Parse raw GAQL JSON files (campaigns
                                          current period, campaigns previous
                                          period, daily customer metrics for
                                          both periods) into a snapshot in
                                          ads_history/ + ads_summary.json.
  python ads_loop.py render               Render ads_dashboard.html from the
                                          latest snapshot + ads_recommendations.json.

Weekly flow: Claude runs `dates`, executes two GAQL queries via GoMarble,
saves raw results, runs `ingest`, analyzes ads_summary.json, rewrites
ads_recommendations.json, runs `render`, commits.
"""
import json
import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(BASE_DIR, "ads_history")
SUMMARY_FILE = os.path.join(BASE_DIR, "ads_summary.json")
RECS_FILE = os.path.join(BASE_DIR, "ads_recommendations.json")
DASHBOARD_FILE = os.path.join(BASE_DIR, "ads_dashboard.html")
DATA_LAG_DAYS = 3
PERIOD_DAYS = 28


def date_ranges():
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=PERIOD_DAYS - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=PERIOD_DAYS - 1)
    return start.isoformat(), end.isoformat(), prev_start.isoformat(), prev_end.isoformat()


def parse_campaigns(raw):
    """Raw GAQL campaign results -> list of campaign dicts (spend>0 or ENABLED)."""
    out = []
    for r in raw.get("results", []):
        c, m = r["campaign"], r["metrics"]
        cost = float(m.get("cost", 0) or 0)
        if cost <= 0 and c["status"] != "ENABLED":
            continue
        out.append({
            "name": c["name"], "status": c["status"],
            "channel": c.get("advertisingChannelType", ""),
            "cost": round(cost, 2),
            "clicks": int(m.get("clicks", 0)),
            "impressions": int(m.get("impressions", 0)),
            "conversions": round(float(m.get("conversions", 0)), 1),
            "conv_value": round(float(m.get("conversionsValue", 0)), 2),
        })
    return sorted(out, key=lambda c: -c["cost"])


def parse_daily(raw, start, end):
    out = []
    for r in raw.get("results", []):
        d = r["segments"]["date"]
        if not (start <= d <= end):
            continue
        m = r["metrics"]
        out.append({"date": d, "cost": round(float(m.get("cost", 0) or 0), 2),
                    "clicks": int(m.get("clicks", 0)),
                    "conversions": round(float(m.get("conversions", 0)), 1),
                    "conv_value": round(float(m.get("conversionsValue", 0)), 2)})
    return sorted(out, key=lambda r: r["date"])


def totals(campaigns):
    cost = sum(c["cost"] for c in campaigns)
    clicks = sum(c["clicks"] for c in campaigns)
    impr = sum(c["impressions"] for c in campaigns)
    conv = sum(c["conversions"] for c in campaigns)
    value = sum(c["conv_value"] for c in campaigns)
    return {"cost": round(cost, 2), "clicks": clicks, "impressions": impr,
            "conversions": round(conv, 1), "conv_value": round(value, 2),
            "roas": round(value / cost, 2) if cost else 0,
            "cpa": round(cost / conv, 2) if conv else 0,
            "cpc": round(cost / clicks, 2) if clicks else 0}


def ingest(cur_file, prev_file, daily_file):
    start, end, prev_start, prev_end = date_ranges()
    with open(cur_file, encoding="utf-8") as f:
        cur_campaigns = parse_campaigns(json.load(f))
    with open(prev_file, encoding="utf-8") as f:
        prev_campaigns = parse_campaigns(json.load(f))
    with open(daily_file, encoding="utf-8") as f:
        daily_raw = json.load(f)

    snapshot = {
        "fetched": date.today().isoformat(),
        "current": {"start": start, "end": end, "campaigns": cur_campaigns,
                    "totals": totals(cur_campaigns),
                    "by_date": parse_daily(daily_raw, start, end)},
        "previous": {"start": prev_start, "end": prev_end, "campaigns": prev_campaigns,
                     "totals": totals(prev_campaigns),
                     "by_date": parse_daily(daily_raw, prev_start, prev_end)},
    }
    os.makedirs(HISTORY_DIR, exist_ok=True)
    snap_file = os.path.join(HISTORY_DIR, f"snapshot_{date.today().isoformat()}.json")
    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=1)

    prev_by_name = {c["name"]: c for c in prev_campaigns}
    comparison = []
    for c in cur_campaigns:
        p = prev_by_name.get(c["name"])
        roas = c["conv_value"] / c["cost"] if c["cost"] else 0
        roas_prev = (p["conv_value"] / p["cost"]) if p and p["cost"] else None
        comparison.append({
            "name": c["name"], "status": c["status"],
            "cost": c["cost"], "cost_prev": p["cost"] if p else 0,
            "cost_delta": round(c["cost"] - (p["cost"] if p else 0), 2),
            "conversions": c["conversions"], "conv_value": c["conv_value"],
            "roas": round(roas, 2),
            "roas_prev": round(roas_prev, 2) if roas_prev is not None else None,
            "roas_delta": round(roas - roas_prev, 2) if roas_prev is not None else None,
            "cpa": round(c["cost"] / c["conversions"], 2) if c["conversions"] else None,
        })

    summary = {"fetched": snapshot["fetched"],
               "period": {"start": start, "end": end},
               "prev_period": {"start": prev_start, "end": prev_end},
               "totals": snapshot["current"]["totals"],
               "totals_prev": snapshot["previous"]["totals"],
               "campaigns": comparison}
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    t, tp = summary["totals"], summary["totals_prev"]
    print(f"Period {start} to {end} vs prior {PERIOD_DAYS}d:")
    print(f"  Spend ${t['cost']:,.0f} ({t['cost']-tp['cost']:+,.0f})   "
          f"Conv value ${t['conv_value']:,.0f} ({t['conv_value']-tp['conv_value']:+,.0f})   "
          f"ROAS {t['roas']} (prev {tp['roas']})   CPA ${t['cpa']} (prev ${tp['cpa']})")
    for c in comparison:
        flag = " [ZERO SPEND, ENABLED]" if c["cost"] == 0 else ""
        print(f"  {c['name']:<32} spend ${c['cost']:>8,.0f} ({c['cost_delta']:+8,.0f})  "
              f"ROAS {c['roas']:>5} (prev {c['roas_prev']}){flag}")
    print(f"  Snapshot: {snap_file}")
    print(f"  Summary:  {SUMMARY_FILE}")


# ---------------------------------------------------------------- dashboard --

def fmt_delta(d, invert=False, money=False, decimals=0):
    if d is None:
        return '<span class="neutral">–</span>'
    good = (d < 0) if invert else (d > 0)
    cls = "positive" if good else ("negative" if d != 0 else "neutral")
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    v = abs(d)
    txt = f"${v:,.{decimals}f}" if money else f"{v:,.{decimals}f}" if decimals else f"{v:,g}"
    return f'<span class="{cls}">{sign}{txt}</span>'


def svg_trend(cur_dates, prev_dates, key="cost", width=1140, height=220):
    if not cur_dates:
        return "<p class='neutral'>No trend data.</p>"
    n = max(len(cur_dates), len(prev_dates))
    vals = [d[key] for d in cur_dates + prev_dates] or [1]
    ymax = max(vals) * 1.15 or 1
    pad_l, pad_b, pad_t = 48, 24, 8

    def points(series):
        pts = []
        for i, d in enumerate(series):
            x = pad_l + i * (width - pad_l - 10) / max(n - 1, 1)
            y = pad_t + (height - pad_t - pad_b) * (1 - d[key] / ymax)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    grid, labels = "", ""
    for frac in (0, 0.5, 1):
        val = ymax * frac
        y = pad_t + (height - pad_t - pad_b) * (1 - frac)
        grid += f'<line x1="{pad_l}" y1="{y:.0f}" x2="{width-10}" y2="{y:.0f}" stroke="#334155" stroke-width="1"/>'
        labels += f'<text x="{pad_l-6}" y="{y+4:.0f}" fill="#94a3b8" font-size="11" text-anchor="end">${val:,.0f}</text>'
    for i in (0, len(cur_dates) - 1):
        if i < 0:
            continue
        x = pad_l + i * (width - pad_l - 10) / max(n - 1, 1)
        labels += (f'<text x="{x:.0f}" y="{height-6}" fill="#94a3b8" font-size="11" '
                   f'text-anchor="middle">{cur_dates[i]["date"][5:]}</text>')
    return f"""<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto">
{grid}{labels}
<polyline points="{points(prev_dates)}" fill="none" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4 3"/>
<polyline points="{points(cur_dates)}" fill="none" stroke="#22c55e" stroke-width="2.5"/>
</svg>
<div style="font-size:12px;color:#94a3b8;margin-top:4px">
<span style="color:#22c55e">&#9644;</span> current period &nbsp;
<span style="color:#64748b">&#9644;</span> previous period (dashed)</div>"""


PRIORITY_COLORS = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}


def render():
    snaps = sorted(os.listdir(HISTORY_DIR)) if os.path.isdir(HISTORY_DIR) else []
    if not snaps:
        print("No snapshots in ads_history/ — run ingest first.")
        return
    with open(os.path.join(HISTORY_DIR, snaps[-1]), encoding="utf-8") as f:
        snap = json.load(f)
    recs = []
    if os.path.exists(RECS_FILE):
        with open(RECS_FILE, encoding="utf-8") as f:
            recs = json.load(f)

    cur, prev = snap["current"], snap["previous"]
    t, tp = cur["totals"], prev["totals"]

    def kpi(label, value, delta_html):
        return (f'<div class="kpi-card"><div class="label">{label}</div>'
                f'<div class="value">{value}</div>'
                f'<div class="sub">{delta_html} vs prior 28d</div></div>')

    kpis = "".join([
        kpi("Spend", f"${t['cost']:,.0f}", fmt_delta(round(t["cost"] - tp["cost"]), money=True)),
        kpi("Conv Value", f"${t['conv_value']:,.0f}", fmt_delta(round(t["conv_value"] - tp["conv_value"]), money=True)),
        kpi("ROAS", f"{t['roas']}", fmt_delta(round(t["roas"] - tp["roas"], 2), decimals=2)),
        kpi("Conversions", f"{t['conversions']:,.0f}", fmt_delta(round(t["conversions"] - tp["conversions"]))),
        kpi("CPA", f"${t['cpa']}", fmt_delta(round(t["cpa"] - tp["cpa"], 2), invert=True, money=True, decimals=2)),
    ])

    rec_html = ""
    for r in recs:
        color = PRIORITY_COLORS.get(r.get("priority", "medium"), "#f59e0b")
        rec_html += (f'<div class="chart-card" style="border-left:4px solid {color};margin-bottom:12px">'
                     f'<h3 style="color:{color}">{r.get("priority","medium").upper()}</h3>'
                     f'<div style="font-size:15px;font-weight:600;color:#f8fafc;margin-bottom:6px">{r["title"]}</div>'
                     f'<div style="font-size:13px;color:#cbd5e1;line-height:1.5">{r["detail"]}</div></div>')
    if not rec_html:
        rec_html = "<p class='neutral'>No recommendations this week.</p>"

    prev_by_name = {c["name"]: c for c in prev["campaigns"]}
    camp_rows = ""
    for c in cur["campaigns"]:
        p = prev_by_name.get(c["name"])
        roas = c["conv_value"] / c["cost"] if c["cost"] else 0
        roas_prev = (p["conv_value"] / p["cost"]) if p and p["cost"] else None
        cpa = c["cost"] / c["conversions"] if c["conversions"] else None
        name = c["name"] + (' <span style="color:#f59e0b;font-size:11px">NO SPEND</span>'
                            if c["cost"] == 0 and c["status"] == "ENABLED" else "")
        camp_rows += (f'<tr><td>{name}</td>'
                      f'<td>${c["cost"]:,.0f}</td>'
                      f'<td>{fmt_delta(round(c["cost"] - (p["cost"] if p else 0)), money=True)}</td>'
                      f'<td>{c["conversions"]:,.0f}</td>'
                      f'<td>${c["conv_value"]:,.0f}</td>'
                      f'<td>{roas:.2f}</td>'
                      f'<td>{fmt_delta(round(roas - roas_prev, 2), decimals=2) if roas_prev else "–"}</td>'
                      f'<td>{"$%.2f" % cpa if cpa else "–"}</td></tr>')

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forage Kitchen — Paid Ads Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f172a; color:#e2e8f0; min-height:100vh; }}
.header {{ background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%); padding:20px 30px; border-bottom:1px solid #334155; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:24px; font-weight:700; color:#f8fafc; }}
.header h1 span {{ color:#22c55e; }}
.header .meta {{ text-align:right; font-size:13px; color:#94a3b8; }}
.header .meta .period {{ font-size:16px; color:#f8fafc; font-weight:600; }}
.container {{ max-width:1200px; margin:0 auto; padding:24px 30px; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:16px; }}
.kpi-card {{ background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; }}
.kpi-card .label {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#94a3b8; margin-bottom:8px; }}
.kpi-card .value {{ font-size:28px; font-weight:700; color:#f8fafc; }}
.kpi-card .sub {{ font-size:13px; color:#94a3b8; margin-top:4px; }}
.section-header {{ font-size:18px; font-weight:600; color:#f8fafc; margin:28px 0 12px; padding-bottom:8px; border-bottom:1px solid #334155; }}
.chart-card {{ background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; }}
.chart-card h3 {{ font-size:14px; color:#94a3b8; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.5px; }}
.store-table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; border:1px solid #334155; }}
.store-table th {{ background:#334155; padding:10px 14px; text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#94a3b8; font-weight:600; }}
.store-table td {{ padding:10px 14px; border-bottom:1px solid #1e293b; font-size:14px; }}
.store-table tr:nth-child(even) {{ background:#1e293b; }}
.store-table tr:nth-child(odd) {{ background:#172033; }}
.store-table tr:hover {{ background:#253352; }}
.positive {{ color:#22c55e; }} .negative {{ color:#ef4444; }} .neutral {{ color:#94a3b8; }}
</style></head><body>
<div class="header">
  <h1>Forage <span>Kitchen</span> — Paid Ads</h1>
  <div class="meta">
    <div class="period">{cur['start']} → {cur['end']}</div>
    <div>Google Ads · refreshed {snap['fetched']}</div>
  </div>
</div>
<div class="container">
  <div class="kpi-grid">{kpis}</div>

  <div class="section-header">Daily Spend Trend</div>
  <div class="chart-card">{svg_trend(cur['by_date'], prev['by_date'])}</div>

  <div class="section-header">Recommendations</div>
  {rec_html}

  <div class="section-header">Campaigns (28 days vs prior)</div>
  <table class="store-table"><thead><tr>
    <th>Campaign</th><th>Spend</th><th>&Delta; Spend</th><th>Conv</th><th>Conv Value</th><th>ROAS</th><th>&Delta; ROAS</th><th>CPA</th>
  </tr></thead><tbody>{camp_rows}</tbody></table>
</div>
</body></html>"""
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rendered {DASHBOARD_FILE}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "dates":
        s, e, ps, pe = date_ranges()
        print(f"current:  {s} to {e}")
        print(f"previous: {ps} to {pe}")
    elif cmd == "ingest":
        ingest(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "render":
        render()
    else:
        print(__doc__)
