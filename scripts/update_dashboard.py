#!/usr/bin/env python3
"""
Open English LLM Dashboard — Weekly Auto-Update
Corre cada lunes 9 AM Colombia (14:00 UTC via GitHub Actions).

Secrets requeridos en GitHub:
  GH_PAT                  → Personal Access Token (Contents R/W) del repo AnalyticsOE/oe-llm-dashboard
  GA4_SERVICE_ACCOUNT_JSON → JSON de cuenta de servicio de Google Cloud con acceso a ambas propiedades GA4
  OE_MCP_BASE_URL         → URL base del oe-marketing-mcp (ej: https://mcp.openenglish.com)
  OE_MCP_TOKEN            → Bearer token del oe-marketing-mcp
"""

import os, json, base64, urllib.request, urllib.parse
import requests
from datetime import date, timedelta, datetime

# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
GH_PAT   = os.environ['GH_PAT']
OWNER    = "AnalyticsOE"
REPO     = "oe-llm-dashboard"

GA4_SA_JSON  = os.environ.get('GA4_SERVICE_ACCOUNT_JSON', '')
MCP_BASE_URL = os.environ.get('OE_MCP_BASE_URL', '').rstrip('/')
MCP_TOKEN    = os.environ.get('OE_MCP_TOKEN', '')

LATAM_PROP   = "283620827"
BRAZIL_PROP  = "321847880"

LLM_SOURCES  = ["chatgpt.com","gemini.google.com","copilot.microsoft.com","claude.ai","perplexity.ai"]
PLAT_MAP     = {"chatgpt.com":"chatgpt","gemini.google.com":"gemini",
                "copilot.microsoft.com":"copilot","claude.ai":"claude_ai","perplexity.ai":"perplexity"}

GH_HEADERS   = {"Authorization": f"Bearer {GH_PAT}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json"}

# ── GITHUB HELPERS ────────────────────────────────────────────────────────────
def gh_get(path):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    req = urllib.request.Request(url, headers=GH_HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def gh_download(path):
    meta = gh_get(path)
    raw  = urllib.request.urlopen(meta['download_url']).read()
    return json.loads(raw), meta['sha']

def gh_upload(local_bytes, remote_path, sha, message):
    b64 = base64.b64encode(local_bytes).decode()
    data = json.dumps({"message": message, "content": b64, "sha": sha}).encode()
    req  = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{remote_path}",
        data=data, method="PUT", headers=GH_HEADERS
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    print(f"  ✅ {remote_path}: {resp['commit']['sha'][:8]}")

# ── DATE HELPERS ──────────────────────────────────────────────────────────────
def last_date_in_json(data):
    days = data.get('daily', [])
    return max(d['date'] for d in days) if days else None

def compute_range(data):
    env_start = os.environ.get('START_DATE', '').strip()
    env_end   = os.environ.get('END_DATE', '').strip()
    if env_start and env_end:
        return env_start, env_end
    last = last_date_in_json(data)
    if not last:
        return None, None
    start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    end   = (date.today() - timedelta(days=1)).isoformat()
    return (start, end) if start <= end else (None, None)

# ── GA4 QUERY ─────────────────────────────────────────────────────────────────
def ga4_sessions(property_id, start, end):
    """Returns dict: {date: {organic: N, llm: N, plat: {chatgpt: N, ...}}}"""
    import tempfile, json as _json
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric,
        FilterExpression, FilterExpressionList, Filter,
        InListFilter, StringFilter, NotExpression
    )

    # Write service account JSON to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(GA4_SA_JSON)
        cred_file = f.name
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = cred_file

    client = BetaAnalyticsDataClient()
    base_filter = FilterExpression(
        and_group=FilterExpressionList(expressions=[
            FilterExpression(not_expression=NotExpression(
                expression=FilterExpression(filter=Filter(
                    field_name="pagePath",
                    string_filter=StringFilter(match_type=StringFilter.MatchType.BEGINS_WITH, value="/junior")
                ))
            )),
            FilterExpression(not_expression=NotExpression(
                expression=FilterExpression(filter=Filter(
                    field_name="pagePath",
                    string_filter=StringFilter(match_type=StringFilter.MatchType.BEGINS_WITH, value="/blog")
                ))
            )),
            FilterExpression(not_expression=NotExpression(
                expression=FilterExpression(filter=Filter(
                    field_name="pagePath",
                    string_filter=StringFilter(match_type=StringFilter.MatchType.BEGINS_WITH, value="/para-empresas")
                ))
            )),
        ])
    )

    result = {}

    # Organic sessions
    organic_filter = FilterExpression(
        and_group=FilterExpressionList(expressions=[
            base_filter,
            FilterExpression(filter=Filter(
                field_name="sessionDefaultChannelGroup",
                string_filter=StringFilter(match_type=StringFilter.MatchType.EXACT, value="Organic Search")
            ))
        ])
    )
    resp = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions")],
        dimension_filter=organic_filter,
        order_bys=[{"dimension": {"dimension_name": "date"}}]
    ))
    for row in resp.rows:
        dt = f"{row.dimension_values[0].value[:4]}-{row.dimension_values[0].value[4:6]}-{row.dimension_values[0].value[6:]}"
        result.setdefault(dt, {"organic": 0, "llm": 0, "plat": {}})
        result[dt]["organic"] = int(row.metric_values[0].value)

    # LLM sessions by source
    llm_filter = FilterExpression(
        and_group=FilterExpressionList(expressions=[
            base_filter,
            FilterExpression(filter=Filter(
                field_name="sessionSource",
                in_list_filter=InListFilter(values=LLM_SOURCES)
            ))
        ])
    )
    resp = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name="date"), Dimension(name="sessionSource")],
        metrics=[Metric(name="sessions")],
        dimension_filter=llm_filter,
        order_bys=[{"dimension": {"dimension_name": "date"}}]
    ))
    for row in resp.rows:
        raw_dt = row.dimension_values[0].value
        dt = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:]}"
        src = row.dimension_values[1].value
        n   = int(row.metric_values[0].value)
        result.setdefault(dt, {"organic": 0, "llm": 0, "plat": {}})
        result[dt]["llm"] += n
        plat_key = PLAT_MAP.get(src, src)
        result[dt]["plat"][plat_key] = result[dt]["plat"].get(plat_key, 0) + n

    os.unlink(cred_file)
    return result

# ── OE-MARKETING-MCP QUERY ────────────────────────────────────────────────────
def mcp_query(**params):
    """POST to oe-marketing-mcp GrossSalesDynamic endpoint."""
    url = f"{MCP_BASE_URL}/GrossSalesDynamic"
    headers = {
        "Authorization": f"Bearer {MCP_TOKEN}",
        "Content-Type": "application/json"
    }
    resp = requests.post(url, json=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # Support both {value: [...]} and direct list responses
    if isinstance(data, dict) and 'value' in data:
        return data['value'].get('value', data['value']) if isinstance(data['value'], dict) else data['value']
    return data

def mcp_daily(country_group, type_val, start, end):
    """Returns dict: {date: (leads, sales)}"""
    rows = mcp_query(
        CountryGroup=country_group, Type=type_val,
        Start_date=start, End_date=end,
        Organization="OE", MarketingOrganization="OE", ReportPillar="Core",
        GroupByDate=True, GroupByMonth=False, GroupByYear=False, GroupByCountry=False
    )
    return {r['LeadDate']: (r['LeadCountEligible'], r['CoreEnrollmentsTotal']) for r in rows}

def mcp_monthly_total(country_group, type_val, start, end):
    """Returns (leads, sales) total for date range."""
    rows = mcp_query(
        CountryGroup=country_group, Type=type_val,
        Start_date=start, End_date=end,
        Organization="OE", MarketingOrganization="OE", ReportPillar="Core",
        GroupByDate=False, GroupByMonth=False, GroupByYear=False, GroupByCountry=False
    )
    if not rows:
        return 0, 0
    r = rows[0]
    return r['LeadCountEligible'], r['CoreEnrollmentsTotal']

def mcp_platform_totals(country_group, start, end):
    """Returns {chatgpt: (leads,sales), copilot: ..., perplexity: ...}"""
    result = {}
    for plat in ["ChatGPT", "Copilot", "Perplexity"]:
        key = plat.lower()
        leads, sales = mcp_monthly_total(country_group, plat, start, end)
        result[key] = {"leads": leads, "sales": sales}
    result["gemini"]   = {"leads": 0, "sales": 0}
    result["claude_ai"] = {"leads": 0, "sales": 0}
    return result

# ── MONTHLY RECORD HELPERS ────────────────────────────────────────────────────
def period_label(dt_str):
    """'2026-08-05' → ('2026-08', 'Ago')"""
    dt  = date.fromisoformat(dt_str)
    lbl = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"][dt.month-1]
    return f"{dt.year}-{dt.month:02d}", lbl

def month_start(period):
    """'2026-08' → '2026-08-01'"""
    y, m = period.split('-')
    return f"{y}-{m}-01"

def month_end_of_update(period, update_end):
    """Month end = last day of that month OR update_end, whichever is earlier."""
    import calendar
    y, m = int(period.split('-')[0]), int(period.split('-')[1])
    last_day = calendar.monthrange(y, m)[1]
    month_last = f"{y}-{m:02d}-{last_day}"
    return min(month_last, update_end)

def get_or_create_monthly(data, period, label):
    for m in data['monthly']:
        if m['period'] == period:
            return m
    new_m = {
        "period": period, "label": label,
        "llm_sessions": 0, "organic_sessions": 0,
        "leads": 0, "organic_leads": 0,
        "mcp_organic": {"leads": 0, "sales": 0},
        "mcp_llm":     {"leads": 0, "sales": 0},
        "mcp_platforms": {
            "chatgpt": {"leads":0,"sales":0}, "copilot": {"leads":0,"sales":0},
            "perplexity": {"leads":0,"sales":0}, "gemini": {"leads":0,"sales":0},
            "claude_ai": {"leads":0,"sales":0}
        },
        "platforms": {
            "chatgpt": {"sessions":0,"leads":0}, "gemini": {"sessions":0,"leads":0},
            "copilot": {"sessions":0,"leads":0}, "claude_ai": {"sessions":0,"leads":0},
            "perplexity": {"sessions":0,"leads":0}
        }
    }
    data['monthly'].append(new_m)
    data['monthly'].sort(key=lambda x: x['period'])
    return new_m

# ── MAIN UPDATE ───────────────────────────────────────────────────────────────
def update(region_label, data, ga4_prop, country_group, start, end):
    print(f"\n{'='*50}")
    print(f"  {region_label}  {start} → {end}")
    print(f"{'='*50}")

    # 1. GA4 sessions
    print("  📊 GA4 sessions...")
    ga4 = ga4_sessions(ga4_prop, start, end)

    # 2. MCP daily data
    print("  📈 MCP SEO diario...")
    mcp_seo_d = mcp_daily(country_group, "SEO", start, end)
    print(f"     {len(mcp_seo_d)} días con leads SEO")

    print("  🤖 MCP LLMs diario...")
    mcp_llm_d = mcp_daily(country_group, ["ChatGPT","Copilot","Perplexity"], start, end)
    print(f"     {len(mcp_llm_d)} días con leads LLM")

    # 3. Determine which months are affected
    all_dates = sorted(set(ga4.keys()) | set(mcp_seo_d.keys()) | set(mcp_llm_d.keys()))
    affected_periods = {}
    for dt in all_dates:
        period, label = period_label(dt)
        affected_periods[period] = label

    # 4. Append/update daily records
    existing = {d['date'] for d in data['daily']}
    for dt in all_dates:
        ga4_rec   = ga4.get(dt, {})
        seo_leads, seo_sales = mcp_seo_d.get(dt, (0, 0))
        llm_leads, llm_sales = mcp_llm_d.get(dt, (0, 0))
        rec = {
            "date": dt,
            "llm_sessions":      ga4_rec.get("llm", 0),
            "organic_sessions":  ga4_rec.get("organic", 0),
            "leads": 0, "organic_leads": 0,
            "mcp_organic_leads": seo_leads,
            "mcp_organic_sales": seo_sales,
            "mcp_llm_leads":     llm_leads,
            "mcp_llm_sales":     llm_sales,
            "platforms":         ga4_rec.get("plat", {})
        }
        if dt not in existing:
            data['daily'].append(rec)
        else:
            for d in data['daily']:
                if d['date'] == dt:
                    d.update(rec)
                    break
    data['daily'].sort(key=lambda x: x['date'])

    # 5. Rebuild monthly records for affected periods
    for period, label in affected_periods.items():
        print(f"  📅 Actualizando mes {period}...")
        mstart = month_start(period)
        mend   = month_end_of_update(period, end)

        # MCP monthly totals
        org_leads, org_sales = mcp_monthly_total(country_group, "SEO", mstart, mend)
        llm_leads, llm_sales = mcp_monthly_total(
            country_group, ["ChatGPT","Copilot","Perplexity"], mstart, mend
        )
        plat_totals = mcp_platform_totals(country_group, mstart, mend)

        # GA4 monthly sessions (sum from daily records)
        m_days = [d for d in data['daily'] if d['date'].startswith(period[:7])]
        llm_s  = sum(d.get('llm_sessions', 0) for d in m_days)
        org_s  = sum(d.get('organic_sessions', 0) for d in m_days)

        m = get_or_create_monthly(data, period, label)
        m['llm_sessions']     = llm_s
        m['organic_sessions'] = org_s
        m['mcp_organic']      = {"leads": org_leads, "sales": org_sales}
        m['mcp_llm']          = {"leads": llm_leads, "sales": llm_sales}
        m['mcp_platforms']    = plat_totals
        print(f"     org={org_leads} leads, {org_sales} sales | llm={llm_leads} leads, {llm_sales} sales")

    # 6. Update metadata
    data['meta']['last_updated'] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data['meta']['to'] = end
    return data

def rebuild_html(latam_json, brazil_json, html):
    old_start = html.find('const INLINE_DATA = {')
    old_end   = html.find('\n};', old_start) + 3
    old_block = html[old_start:old_end]
    new_block = f'const INLINE_DATA = {{\n  latam: {latam_json},\n  brazil: {brazil_json}\n}};'
    return html.replace(old_block, new_block)

# ── ENTRY POINT ───────────────────────────────────────────────────────────────
def main():
    print("🚀 Open English LLM Dashboard — Weekly Update")
    print(f"   Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    # Download current data
    print("\n📥 Descargando datos actuales de GitHub...")
    latam_data,  latam_sha  = gh_download('data/latam.json')
    brazil_data, brazil_sha = gh_download('data/brazil.json')
    html_raw,    html_sha   = gh_download('index.html')
    html_str = html_raw if isinstance(html_raw, str) else html_raw.decode('utf-8') if isinstance(html_raw, bytes) else str(html_raw)

    # Compute date range
    start, end = compute_range(latam_data)
    if not start:
        print("\n✅ Los datos ya están actualizados. Nada que hacer.")
        return

    print(f"\n📅 Rango: {start} → {end}")

    # Update LATAM
    latam_data = update("LATAM", latam_data, LATAM_PROP, "LATAM", start, end)

    # Update Brazil
    brazil_data = update("Brazil", brazil_data, BRAZIL_PROP, "Brazil", start, end)

    # Rebuild embedded HTML
    print("\n🔧 Reconstruyendo HTML embebido...")
    latam_json_str  = json.dumps(latam_data,  separators=(',', ':'))
    brazil_json_str = json.dumps(brazil_data, separators=(',', ':'))

    if 'const INLINE_DATA = {' in html_str:
        new_html = rebuild_html(latam_json_str, brazil_json_str, html_str)
    else:
        print("  ⚠️  No se encontró INLINE_DATA en el HTML. Saltando reconstrucción.")
        new_html = html_str

    # Upload to GitHub
    print("\n📤 Subiendo a GitHub...")
    msg = f"Auto-update {start} → {end} (weekly cron)"
    gh_upload(latam_json_str.encode(),  'data/latam.json',  latam_sha,  msg)
    gh_upload(brazil_json_str.encode(), 'data/brazil.json', brazil_sha, msg)
    gh_upload(new_html.encode('utf-8'), 'index.html',       html_sha,   msg)

    print(f"\n🎉 Actualización completada: {start} → {end}")
    print(f"   LATAM:  {len(latam_data['daily'])} días totales")
    print(f"   Brazil: {len(brazil_data['daily'])} días totales")

if __name__ == "__main__":
    main()
