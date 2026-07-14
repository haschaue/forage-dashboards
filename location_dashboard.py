"""Forage Kitchen — combined per-location view: organic search + paid ads + sales.

Joins three sources on location, over the same 28-day window (vs prior 28):
  - Toast POS net sales (direct API, reuses daily_dashboard caches)
  - Google Search Console organic clicks/position (latest seo_history/ snapshot)
  - Google Ads spend/ROAS (latest ads_history/ snapshot)

Usage:
  python location_dashboard.py          Build (pull sales, join snapshots, write
                                        combined_summary.json) and render.
  python location_dashboard.py render   Re-render from combined_summary.json +
                                        combined_findings.json without pulling.

Run AFTER seo_loop and ads_loop have produced same-week snapshots. The weekly
task writes combined_findings.json (cross-channel narrative) between build and
render; findings are a JSON array of {"type": "win"|"concern"|"watch",
"title": "...", "detail": "..."}.
"""
import glob
import json
import os
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from daily_dashboard import (toast_authenticate, pull_toast_orders_day,
                             load_cache, save_cache, TOAST_RESTAURANTS)

SEO_HISTORY = os.path.join(BASE_DIR, "seo_history")
ADS_HISTORY = os.path.join(BASE_DIR, "ads_history")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DASHBOARD_FILE = os.path.join(BASE_DIR, "combined_dashboard.html")
SUMMARY_FILE = os.path.join(BASE_DIR, "combined_summary.json")
FINDINGS_FILE = os.path.join(BASE_DIR, "combined_findings.json")
DATA_LAG_DAYS = 3
PERIOD_DAYS = 28

# store number -> GSC location page path + Google Ads campaign name
LOCATIONS = {
    "8001": {"name": "State Street",      "page": "/locations/state-street-madison-wi", "campaign": "PMax_Cube_StateStreet"},
    "8002": {"name": "Hilldale",          "page": "/locations/hilldale-madison-wi",     "campaign": "PMax_Cube_Hilldale_Madison"},
    "8003": {"name": "Monona",            "page": "/locations/monona-wi",               "campaign": "PMax_Cube_Monona"},
    "8004": {"name": "Middleton",         "page": "/locations/middleton-wi",            "campaign": "PMax_Cube_Middleton"},
    "8005": {"name": "Champaign",         "page": "/locations/champaign-il",            "campaign": "PMax_Cube_Champaign"},
    "8006": {"name": "Whitefish Bay",     "page": "/locations/whitefish-bay",           "campaign": "PMax_Cube_WhitefishBay"},
    "8007": {"name": "Sun Prairie",       "page": "/locations/sun-prairie",             "campaign": "PMax_Cube_Sun Prairie"},
    "8008": {"name": "Pewaukee",          "page": "/locations/pewaukee",                "campaign": "PMax_Cube_Pewaukee"},
    "8009": {"name": "MKE Public Market", "page": "/locations/milwaukee-public-market", "campaign": "PMax_Cube_Milwaukee"},
    "8010": {"name": "Brookfield",        "page": "/locations/brookfield",              "campaign": "PMax_Cube_Brookfield"},
}


def date_ranges():
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=PERIOD_DAYS - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=PERIOD_DAYS - 1)
    return start, end, prev_start, prev_end


def merged_cache_days(store_num):
    """Merge every existing sales cache for a store into {date_str: day_totals}."""
    merged = {}
    for path in glob.glob(os.path.join(CACHE_DIR, f"*_sales_{store_num}.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        # Skip caches with a different shape (e.g. cogs caches store bare numbers)
        merged.update({d: v for d, v in data.items()
                       if isinstance(v, dict) and "net_sales" in v})
    return merged


def get_sales(token, store_num, start, end):
    """Net sales total for [start, end], reusing any cached days, fetching gaps."""
    guid = TOAST_RESTAURANTS[store_num]["guid"]
    cached = merged_cache_days(store_num)
    own_cache = load_cache(f"loc_sales_{store_num}")
    cached.update(own_cache)

    total = 0.0
    fetched = 0
    current = start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        if ds in cached:
            total += cached[ds].get("net_sales", 0) or 0
        else:
            try:
                day = pull_toast_orders_day(token, guid, current)
                if day["checks"] > 0:
                    own_cache[ds] = day
                    total += day["net_sales"]
                else:
                    own_cache[ds] = {"net_sales": 0, "checks": 0}
                fetched += 1
            except Exception as e:
                print(f"    {store_num} {ds}: {e}")
        current += timedelta(days=1)
    if fetched:
        save_cache(f"loc_sales_{store_num}", own_cache)
    return round(total, 2), fetched


def latest_snapshot(history_dir):
    snaps = sorted(glob.glob(os.path.join(history_dir, "snapshot_*.json")))
    if not snaps:
        return None
    with open(snaps[-1], encoding="utf-8") as f:
        return json.load(f)


def build():
    start, end, prev_start, prev_end = date_ranges()
    seo = latest_snapshot(SEO_HISTORY)
    ads = latest_snapshot(ADS_HISTORY)
    if not seo or not ads:
        print("Missing seo_history/ or ads_history/ snapshot — run those loops first.")
        sys.exit(1)

    seo_cur, seo_prev = seo["current"]["pages"], seo["previous"]["pages"]
    ads_cur = {c["name"]: c for c in ads["current"]["campaigns"]}
    ads_prev = {c["name"]: c for c in ads["previous"]["campaigns"]}

    print("Pulling Toast sales (cached days reused)...")
    token = toast_authenticate()
    rows = []
    for store_num, loc in sorted(LOCATIONS.items()):
        sales_cur, f1 = get_sales(token, store_num, start, end)
        sales_prev, f2 = get_sales(token, store_num, prev_start, prev_end)
        if f1 or f2:
            print(f"  {loc['name']}: fetched {f1 + f2} days from Toast")

        og_c = seo_cur.get(loc["page"], {})
        og_p = seo_prev.get(loc["page"], {})
        ad_c = ads_cur.get(loc["campaign"], {})
        ad_p = ads_prev.get(loc["campaign"], {})

        spend = ad_c.get("cost", 0)
        conv_value = ad_c.get("conv_value", 0)
        spend_prev = ad_p.get("cost", 0)
        rows.append({
            "store": store_num, "name": loc["name"],
            "sales": sales_cur, "sales_prev": sales_prev,
            "sales_pct": round((sales_cur - sales_prev) / sales_prev * 100, 1) if sales_prev else None,
            "organic_clicks": og_c.get("clicks", 0),
            "organic_clicks_prev": og_p.get("clicks", 0),
            "organic_pos": og_c.get("position"),
            "spend": spend, "spend_prev": spend_prev,
            "paid_clicks": ad_c.get("clicks", 0),
            "conv_value": conv_value,
            "roas": round(conv_value / spend, 2) if spend else None,
            "roas_prev": round(ad_p.get("conv_value", 0) / spend_prev, 2) if spend_prev else None,
            "ad_pct_sales": round(spend / sales_cur * 100, 2) if sales_cur else None,
        })

    data = {"built": date.today().isoformat(),
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "prev_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
            "locations": rows}
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data


def fmt_delta(d, invert=False, money=False, pct=False, decimals=0):
    if d is None:
        return '<span class="neutral">–</span>'
    good = (d < 0) if invert else (d > 0)
    cls = "positive" if good else ("negative" if d != 0 else "neutral")
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    v = abs(d)
    if money:
        txt = f"${v:,.{decimals}f}"
    elif pct:
        txt = f"{v:,.1f}%"
    else:
        txt = f"{v:,.{decimals}f}" if decimals else f"{v:,g}"
    return f'<span class="{cls}">{sign}{txt}</span>'


FINDING_STYLES = {"win": ("#22c55e", "WIN"), "concern": ("#ef4444", "CONCERN"),
                  "watch": ("#f59e0b", "WATCH")}


def findings_html():
    if not os.path.exists(FINDINGS_FILE):
        return ""
    with open(FINDINGS_FILE, encoding="utf-8") as f:
        findings = json.load(f)
    if not findings:
        return ""
    cards = ""
    for fi in findings:
        color, label = FINDING_STYLES.get(fi.get("type", "watch"), FINDING_STYLES["watch"])
        cards += (f'<div class="chart-card" style="border-left:4px solid {color};margin-bottom:12px">'
                  f'<h3 style="color:{color};font-size:12px;text-transform:uppercase;'
                  f'letter-spacing:1px;margin-bottom:6px">{label}</h3>'
                  f'<div style="font-size:15px;font-weight:600;color:#f8fafc;margin-bottom:6px">{fi["title"]}</div>'
                  f'<div style="font-size:13px;color:#cbd5e1;line-height:1.5">{fi["detail"]}</div></div>')
    return f'<div class="section-header">This Week\'s Findings</div>{cards}'


def render(data):
    rows = data["locations"]
    tot_sales = sum(r["sales"] for r in rows)
    tot_sales_prev = sum(r["sales_prev"] for r in rows)
    tot_spend = sum(r["spend"] for r in rows)
    tot_spend_prev = sum(r["spend_prev"] for r in rows)
    tot_organic = sum(r["organic_clicks"] for r in rows)
    tot_organic_prev = sum(r["organic_clicks_prev"] for r in rows)
    tot_value = sum(r["conv_value"] for r in rows)

    def kpi(label, value, sub):
        return (f'<div class="kpi-card"><div class="label">{label}</div>'
                f'<div class="value">{value}</div><div class="sub">{sub}</div></div>')

    kpis = "".join([
        kpi("Net Sales", f"${tot_sales:,.0f}",
            fmt_delta(round(tot_sales - tot_sales_prev), money=True) + " vs prior 28d"),
        kpi("Ad Spend", f"${tot_spend:,.0f}",
            fmt_delta(round(tot_spend - tot_spend_prev), money=True, invert=True) + " vs prior 28d"),
        kpi("Ad Spend % of Sales", f"{tot_spend / tot_sales * 100:.2f}%" if tot_sales else "–",
            f"prev {tot_spend_prev / tot_sales_prev * 100:.2f}%" if tot_sales_prev else ""),
        kpi("Blended ROAS", f"{tot_value / tot_spend:.2f}" if tot_spend else "–",
            f"${tot_value:,.0f} tracked conv value"),
        kpi("Organic Clicks (loc pages)", f"{tot_organic:,}",
            fmt_delta(tot_organic - tot_organic_prev) + " vs prior 28d"),
    ])

    body_rows = ""
    for r in sorted(rows, key=lambda r: -r["sales"]):
        body_rows += (
            f'<tr><td><strong>{r["name"]}</strong> <span class="neutral" style="font-size:11px">{r["store"]}</span></td>'
            f'<td>${r["sales"]:,.0f}</td>'
            f'<td>{fmt_delta(r["sales_pct"], pct=True)}</td>'
            f'<td>{r["organic_clicks"]:,}</td>'
            f'<td>{fmt_delta(r["organic_clicks"] - r["organic_clicks_prev"])}</td>'
            f'<td>{r["organic_pos"] if r["organic_pos"] is not None else "–"}</td>'
            f'<td>${r["spend"]:,.0f}</td>'
            f'<td>{fmt_delta(round(r["spend"] - r["spend_prev"]), money=True, invert=True)}</td>'
            f'<td>{r["roas"] if r["roas"] is not None else "–"}</td>'
            f'<td>{fmt_delta(round(r["roas"] - r["roas_prev"], 2), decimals=2) if r["roas"] is not None and r["roas_prev"] else "–"}</td>'
            f'<td>{("%.2f%%" % r["ad_pct_sales"]) if r["ad_pct_sales"] is not None else "–"}</td></tr>')

    totals_roas = tot_value / tot_spend if tot_spend else 0
    body_rows += (
        f'<tr class="total-row"><td><strong>ALL LOCATIONS</strong></td>'
        f'<td>${tot_sales:,.0f}</td><td>{fmt_delta(round((tot_sales-tot_sales_prev)/tot_sales_prev*100,1) if tot_sales_prev else None, pct=True)}</td>'
        f'<td>{tot_organic:,}</td><td>{fmt_delta(tot_organic - tot_organic_prev)}</td><td>–</td>'
        f'<td>${tot_spend:,.0f}</td><td>{fmt_delta(round(tot_spend - tot_spend_prev), money=True, invert=True)}</td>'
        f'<td>{totals_roas:.2f}</td><td>–</td>'
        f'<td>{tot_spend / tot_sales * 100:.2f}%</td></tr>')

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forage Kitchen — Search &amp; Sales by Location</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f172a; color:#e2e8f0; min-height:100vh; }}
.header {{ background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%); padding:20px 30px; border-bottom:1px solid #334155; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:24px; font-weight:700; color:#f8fafc; }}
.header h1 span {{ color:#22c55e; }}
.header .meta {{ text-align:right; font-size:13px; color:#94a3b8; }}
.header .meta .period {{ font-size:16px; color:#f8fafc; font-weight:600; }}
.container {{ max-width:1300px; margin:0 auto; padding:24px 30px; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:16px; }}
.kpi-card {{ background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; }}
.kpi-card .label {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#94a3b8; margin-bottom:8px; }}
.kpi-card .value {{ font-size:28px; font-weight:700; color:#f8fafc; }}
.kpi-card .sub {{ font-size:13px; color:#94a3b8; margin-top:4px; }}
.section-header {{ font-size:18px; font-weight:600; color:#f8fafc; margin:28px 0 12px; padding-bottom:8px; border-bottom:1px solid #334155; }}
.chart-card {{ background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; }}
.store-table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; border:1px solid #334155; }}
.store-table th {{ background:#334155; padding:10px 12px; text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#94a3b8; font-weight:600; }}
.store-table td {{ padding:10px 12px; border-bottom:1px solid #1e293b; font-size:14px; }}
.store-table tr:nth-child(even) {{ background:#1e293b; }}
.store-table tr:nth-child(odd) {{ background:#172033; }}
.store-table tr:hover {{ background:#253352; }}
.store-table tr.total-row {{ background:#334155 !important; font-weight:700; }}
.positive {{ color:#22c55e; }} .negative {{ color:#ef4444; }} .neutral {{ color:#94a3b8; }}
.note {{ font-size:12px; color:#94a3b8; margin-top:10px; line-height:1.5; }}
</style></head><body>
<div class="header">
  <h1>Forage <span>Kitchen</span> — Search &amp; Sales by Location</h1>
  <div class="meta">
    <div class="period">{data['period']['start']} → {data['period']['end']}</div>
    <div>Toast · Search Console · Google Ads · refreshed {data['built']}</div>
  </div>
</div>
<div class="container">
  <div class="kpi-grid">{kpis}</div>

  {findings_html()}

  <div class="section-header">By Location (28 days vs prior 28)</div>
  <table class="store-table"><thead><tr>
    <th>Location</th><th>Net Sales</th><th>&Delta; Sales</th>
    <th>Organic Clicks</th><th>&Delta;</th><th>Pos</th>
    <th>Ad Spend</th><th>&Delta;</th><th>ROAS</th><th>&Delta;</th>
    <th>Ads % of Sales</th>
  </tr></thead><tbody>{body_rows}</tbody></table>

  <div class="note">
    Organic clicks are from each location's page on eatforage.com (Search Console); homepage and menu traffic is not attributed to locations.
    ROAS uses Google-tracked conversion value, not Toast sales. Ad spend % of sales is Google Ads spend ÷ Toast net sales for the same window.
  </div>
</div>
</body></html>"""
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rendered {DASHBOARD_FILE}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            render(json.load(f))
    else:
        render(build())
