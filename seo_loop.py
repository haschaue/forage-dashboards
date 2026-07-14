"""Forage Kitchen SEO loop — weekly GSC pull, trend comparison, dashboard render.

Usage:
  python seo_loop.py fetch    Pull GSC data, save snapshot to seo_history/, write
                              seo_summary.json and print an analysis summary.
  python seo_loop.py render   Render seo_dashboard.html from the latest snapshot
                              plus seo_recommendations.json.
  python seo_loop.py run      fetch + render.

The weekly scheduled task runs fetch, has Claude analyze the summary and write
seo_recommendations.json, then runs render and commits the dashboard.
"""
import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsc_client import get_service, query_search_analytics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(BASE_DIR, "seo_history")
SUMMARY_FILE = os.path.join(BASE_DIR, "seo_summary.json")
RECS_FILE = os.path.join(BASE_DIR, "seo_recommendations.json")
DASHBOARD_FILE = os.path.join(BASE_DIR, "seo_dashboard.html")
SITE = "sc-domain:eatforage.com"
DATA_LAG_DAYS = 3
PERIOD_DAYS = 28
BRANDED_RE = re.compile(r"forage|forge\s*kitchen|4age", re.I)


def normalize_page(url):
    """Collapse www/non-www/http/https duplicates to a bare path."""
    path = re.sub(r"^https?://(www\.)?eatforage\.com", "", url)
    return path.rstrip("/") or "/"


def page_group(path):
    if path == "/":
        return "Homepage"
    if path.startswith("/locations/"):
        return "Location pages"
    if path == "/locations":
        return "Locations index"
    if path.startswith("/blogs/"):
        return "Blog"
    if path.startswith("/menu"):
        return "Menu"
    return "Other"


def aggregate_pages(rows):
    """Aggregate raw page rows by normalized path (position weighted by impressions)."""
    agg = {}
    for r in rows:
        path = normalize_page(r["keys"][0])
        a = agg.setdefault(path, {"clicks": 0, "impressions": 0, "pos_x_impr": 0.0})
        a["clicks"] += r["clicks"]
        a["impressions"] += r["impressions"]
        a["pos_x_impr"] += r["position"] * r["impressions"]
    out = {}
    for path, a in agg.items():
        out[path] = {
            "clicks": a["clicks"],
            "impressions": a["impressions"],
            "ctr": round(a["clicks"] / a["impressions"], 4) if a["impressions"] else 0,
            "position": round(a["pos_x_impr"] / a["impressions"], 1) if a["impressions"] else 0,
        }
    return out


def totals_from_rows(rows):
    clicks = sum(r["clicks"] for r in rows)
    impr = sum(r["impressions"] for r in rows)
    pos = sum(r["position"] * r["impressions"] for r in rows) / impr if impr else 0
    return {"clicks": clicks, "impressions": impr,
            "ctr": round(clicks / impr, 4) if impr else 0, "position": round(pos, 1)}


def fetch_period(service, start, end):
    s, e = start.isoformat(), end.isoformat()
    queries = query_search_analytics(SITE, s, e, dimensions=["query"], row_limit=500, service=service)
    pages = query_search_analytics(SITE, s, e, dimensions=["page"], row_limit=500, service=service)
    by_date = query_search_analytics(SITE, s, e, dimensions=["date"], row_limit=100, service=service)
    devices = query_search_analytics(SITE, s, e, dimensions=["device"], row_limit=10, service=service)
    return {
        "start": s, "end": e,
        "totals": totals_from_rows(by_date),
        "queries": {r["keys"][0]: {"clicks": r["clicks"], "impressions": r["impressions"],
                                   "ctr": round(r["ctr"], 4), "position": round(r["position"], 1)}
                    for r in queries},
        "pages": aggregate_pages(pages),
        "by_date": [{"date": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"]}
                    for r in sorted(by_date, key=lambda r: r["keys"][0])],
        "devices": {r["keys"][0]: {"clicks": r["clicks"], "impressions": r["impressions"]}
                    for r in devices},
    }


def branded_split(queries):
    b = {"clicks": 0, "impressions": 0}
    nb = {"clicks": 0, "impressions": 0}
    for q, m in queries.items():
        t = b if BRANDED_RE.search(q) else nb
        t["clicks"] += m["clicks"]
        t["impressions"] += m["impressions"]
    return {"branded": b, "non_branded": nb}


def compare(cur, prev, min_impr=50):
    """Deltas between two periods for queries and pages."""
    def movers(cur_map, prev_map):
        out = []
        for k in set(cur_map) | set(prev_map):
            c, p = cur_map.get(k), prev_map.get(k)
            c_clicks = c["clicks"] if c else 0
            p_clicks = p["clicks"] if p else 0
            c_impr = c["impressions"] if c else 0
            p_impr = p["impressions"] if p else 0
            if max(c_impr, p_impr) < min_impr:
                continue
            out.append({
                "key": k,
                "clicks": c_clicks, "clicks_prev": p_clicks, "clicks_delta": c_clicks - p_clicks,
                "impressions": c_impr, "impressions_delta": c_impr - p_impr,
                "position": c["position"] if c else None,
                "position_prev": p["position"] if p else None,
                "position_delta": round(c["position"] - p["position"], 1) if c and p else None,
                "status": "new" if not p else ("lost" if not c else ""),
            })
        return out

    return {"queries": movers(cur["queries"], prev["queries"]),
            "pages": movers(cur["pages"], prev["pages"])}


def fetch():
    service = get_service()
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=PERIOD_DAYS - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=PERIOD_DAYS - 1)

    cur = fetch_period(service, start, end)
    prev = fetch_period(service, prev_start, prev_end)
    comparison = compare(cur, prev)

    snapshot = {"fetched": date.today().isoformat(), "current": cur, "previous": prev,
                "branded": {"current": branded_split(cur["queries"]),
                            "previous": branded_split(prev["queries"])},
                "comparison": comparison}

    os.makedirs(HISTORY_DIR, exist_ok=True)
    snap_file = os.path.join(HISTORY_DIR, f"snapshot_{date.today().isoformat()}.json")
    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=1)

    # Compact summary for analysis (and for the weekly Claude run to read)
    q_movers = [m for m in comparison["queries"] if m["status"] != "lost"]
    q_gain = sorted(q_movers, key=lambda m: -m["clicks_delta"])[:15]
    q_loss = sorted(q_movers, key=lambda m: m["clicks_delta"])[:15]
    lost = sorted([m for m in comparison["queries"] if m["status"] == "lost"],
                  key=lambda m: -m["clicks_prev"])[:10]
    p_movers = sorted(comparison["pages"], key=lambda m: m["clicks_delta"])
    loc_pages = sorted([m for m in comparison["pages"] if m["key"].startswith("/locations/")],
                       key=lambda m: -m["clicks"])

    summary = {
        "fetched": snapshot["fetched"],
        "period": {"start": cur["start"], "end": cur["end"]},
        "prev_period": {"start": prev["start"], "end": prev["end"]},
        "totals": cur["totals"], "totals_prev": prev["totals"],
        "branded": snapshot["branded"],
        "query_gainers": q_gain, "query_losers": q_loss, "queries_lost": lost,
        "page_losers": p_movers[:10], "page_gainers": p_movers[::-1][:10],
        "location_pages": loc_pages,
    }
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    t, tp = cur["totals"], prev["totals"]
    print(f"Period {cur['start']} to {cur['end']} vs prior {PERIOD_DAYS}d:")
    print(f"  Clicks {t['clicks']} ({t['clicks']-tp['clicks']:+d})   "
          f"Impressions {t['impressions']} ({t['impressions']-tp['impressions']:+d})   "
          f"CTR {t['ctr']:.2%}   Avg pos {t['position']} (prev {tp['position']})")
    nb, nbp = summary["branded"]["current"]["non_branded"], summary["branded"]["previous"]["non_branded"]
    print(f"  Non-branded clicks {nb['clicks']} ({nb['clicks']-nbp['clicks']:+d})")
    print(f"  Snapshot: {snap_file}")
    print(f"  Summary:  {SUMMARY_FILE}")
    return summary


# ---------------------------------------------------------------- dashboard --

def fmt_delta(d, invert=False):
    if d is None:
        return '<span class="neutral">–</span>'
    good = (d < 0) if invert else (d > 0)
    cls = "positive" if good else ("negative" if d != 0 else "neutral")
    sign = "+" if d > 0 else ""
    return f'<span class="{cls}">{sign}{d:,g}</span>'


def svg_trend(cur_dates, prev_dates, width=1140, height=220):
    """Two-line SVG chart: daily clicks for current and previous period."""
    if not cur_dates:
        return "<p class='neutral'>No trend data.</p>"
    n = max(len(cur_dates), len(prev_dates))
    all_clicks = [d["clicks"] for d in cur_dates + prev_dates] or [1]
    ymax = max(all_clicks) * 1.15 or 1
    pad_l, pad_b, pad_t = 40, 24, 8

    def points(series):
        pts = []
        for i, d in enumerate(series):
            x = pad_l + i * (width - pad_l - 10) / max(n - 1, 1)
            y = pad_t + (height - pad_t - pad_b) * (1 - d["clicks"] / ymax)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    gridlines, labels = "", ""
    for frac in (0, 0.5, 1):
        val = ymax * frac
        y = pad_t + (height - pad_t - pad_b) * (1 - frac)
        gridlines += f'<line x1="{pad_l}" y1="{y:.0f}" x2="{width-10}" y2="{y:.0f}" stroke="#334155" stroke-width="1"/>'
        labels += f'<text x="{pad_l-6}" y="{y+4:.0f}" fill="#94a3b8" font-size="11" text-anchor="end">{val:.0f}</text>'
    for i in (0, len(cur_dates) - 1):
        if i < 0:
            continue
        x = pad_l + i * (width - pad_l - 10) / max(n - 1, 1)
        labels += (f'<text x="{x:.0f}" y="{height-6}" fill="#94a3b8" font-size="11" '
                   f'text-anchor="middle">{cur_dates[i]["date"][5:]}</text>')
    return f"""<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto">
{gridlines}{labels}
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
        print("No snapshots in seo_history/ — run fetch first.")
        return
    with open(os.path.join(HISTORY_DIR, snaps[-1]), encoding="utf-8") as f:
        snap = json.load(f)
    recs = []
    if os.path.exists(RECS_FILE):
        with open(RECS_FILE, encoding="utf-8") as f:
            recs = json.load(f)

    cur, prev = snap["current"], snap["previous"]
    t, tp = cur["totals"], prev["totals"]
    b, bp = snap["branded"]["current"], snap["branded"]["previous"]

    def kpi(label, value, delta_html, sub=""):
        return (f'<div class="kpi-card"><div class="label">{label}</div>'
                f'<div class="value">{value}</div>'
                f'<div class="sub">{delta_html} vs prior 28d {sub}</div></div>')

    ctr_delta = round((t["ctr"] - tp["ctr"]) * 100, 2)
    kpis = "".join([
        kpi("Clicks", f"{t['clicks']:,}", fmt_delta(t["clicks"] - tp["clicks"])),
        kpi("Impressions", f"{t['impressions']:,}", fmt_delta(t["impressions"] - tp["impressions"])),
        kpi("CTR", f"{t['ctr']:.2%}", fmt_delta(ctr_delta) + " pts"),
        kpi("Avg Position", f"{t['position']}", fmt_delta(round(t["position"] - tp["position"], 1), invert=True)),
        kpi("Non-Branded Clicks", f"{b['non_branded']['clicks']:,}",
            fmt_delta(b["non_branded"]["clicks"] - bp["non_branded"]["clicks"])),
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

    def table(rows_html, headers):
        head = "".join(f"<th>{h}</th>" for h in headers)
        return f'<table class="store-table"><thead><tr>{head}</tr></thead><tbody>{rows_html}</tbody></table>'

    loc_rows = ""
    for m in sorted([m for m in snap["comparison"]["pages"] if m["key"].startswith("/locations/")],
                    key=lambda m: -m["clicks"]):
        loc_rows += (f'<tr><td>{m["key"].replace("/locations/","")}</td>'
                     f'<td>{m["clicks"]:,}</td><td>{fmt_delta(m["clicks_delta"])}</td>'
                     f'<td>{m["impressions"]:,}</td>'
                     f'<td>{m["position"] if m["position"] is not None else "–"}</td>'
                     f'<td>{fmt_delta(m["position_delta"], invert=True)}</td></tr>')

    q_movers = [m for m in snap["comparison"]["queries"] if m["status"] != "lost"]
    def q_rows(movers):
        out = ""
        for m in movers:
            tag = ' <span style="color:#22c55e;font-size:11px">NEW</span>' if m["status"] == "new" else ""
            out += (f'<tr><td>{m["key"]}{tag}</td>'
                    f'<td>{m["clicks"]:,}</td><td>{fmt_delta(m["clicks_delta"])}</td>'
                    f'<td>{m["position"] if m["position"] is not None else "–"}</td>'
                    f'<td>{fmt_delta(m["position_delta"], invert=True)}</td></tr>')
        return out

    gain_rows = q_rows(sorted(q_movers, key=lambda m: -m["clicks_delta"])[:12])
    loss_rows = q_rows(sorted(q_movers, key=lambda m: m["clicks_delta"])[:12])
    q_headers = ["Query", "Clicks", "Δ Clicks", "Pos", "Δ Pos"]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forage Kitchen — SEO Dashboard</title>
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
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:900px) {{ .two-col {{ grid-template-columns:1fr; }} }}
.store-table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; border:1px solid #334155; }}
.store-table th {{ background:#334155; padding:10px 14px; text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#94a3b8; font-weight:600; }}
.store-table td {{ padding:10px 14px; border-bottom:1px solid #1e293b; font-size:14px; }}
.store-table tr:nth-child(even) {{ background:#1e293b; }}
.store-table tr:nth-child(odd) {{ background:#172033; }}
.store-table tr:hover {{ background:#253352; }}
.positive {{ color:#22c55e; }} .negative {{ color:#ef4444; }} .neutral {{ color:#94a3b8; }}
</style></head><body>
<div class="header">
  <h1>Forage <span>Kitchen</span> — SEO</h1>
  <div class="meta">
    <div class="period">{cur['start']} → {cur['end']}</div>
    <div>Google Search Console · refreshed {snap['fetched']}</div>
  </div>
</div>
<div class="container">
  <div class="kpi-grid">{kpis}</div>

  <div class="section-header">Daily Clicks Trend</div>
  <div class="chart-card">{svg_trend(cur['by_date'], prev['by_date'])}</div>

  <div class="section-header">Recommendations</div>
  {rec_html}

  <div class="section-header">Location Pages (28 days vs prior)</div>
  {table(loc_rows, ["Location", "Clicks", "Δ Clicks", "Impressions", "Pos", "Δ Pos"])}

  <div class="section-header">Query Movers</div>
  <div class="two-col">
    <div><h3 style="color:#22c55e;font-size:14px;margin-bottom:8px">TOP GAINERS</h3>{table(gain_rows, q_headers)}</div>
    <div><h3 style="color:#ef4444;font-size:14px;margin-bottom:8px">TOP LOSERS</h3>{table(loss_rows, q_headers)}</div>
  </div>
</div>
</body></html>"""
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rendered {DASHBOARD_FILE}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        fetch()
    elif cmd == "render":
        render()
    elif cmd == "run":
        fetch()
        render()
    else:
        print(__doc__)
