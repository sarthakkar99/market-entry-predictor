"""
Finance agent — costs the recommended city using LIVE Bright Data scrapes
of office rent + tech salary search results, rather than a hardcoded multiplier.

Pipeline:
  1. Scrape "office rent per square foot {city} 2026" via fetch_serp -> parse $/sqft/yr
  2. Scrape "average tech salary {city}" via fetch_serp -> parse $/yr
  3. Compute: real estate ($/sqft × sqft/employee × headcount)
            + salaries (avg × headcount × employer overhead)
            + setup + legal + contingency
  4. If either scrape produces no parsable number, fall back to the tier table.
"""

import asyncio
import re

from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient
from scraper import fetch_serp

band = BandClient()

# ----- tier table kept as a fallback when scraping fails -----
COUNTRY_TIER = {
    "united kingdom": "high", "uk": "high", "switzerland": "high", "norway": "high",
    "denmark": "high", "singapore": "high", "japan": "high", "australia": "high",
    "hong kong": "high",
    "united states": "medium", "usa": "medium", "us": "medium",
    "germany": "medium", "france": "medium", "netherlands": "medium",
    "sweden": "medium", "finland": "medium", "austria": "medium", "italy": "medium",
    "spain": "medium", "ireland": "medium", "belgium": "medium",
    "canada": "medium", "new zealand": "medium", "israel": "medium",
    "south korea": "medium", "china": "medium", "uae": "medium",
    "united arab emirates": "medium", "qatar": "medium", "saudi arabia": "medium",
    "india": "low", "vietnam": "low", "indonesia": "low", "philippines": "low",
    "thailand": "low", "malaysia": "low", "poland": "low", "czech republic": "low",
    "hungary": "low", "portugal": "low", "romania": "low", "bulgaria": "low",
    "mexico": "low", "brazil": "low", "argentina": "low", "colombia": "low",
    "egypt": "low", "nigeria": "low", "kenya": "low", "south africa": "low",
    "turkey": "low",
}
TIER_FALLBACK = {
    "low":    {"avg_salary_yr": 30000,  "rent_psf_yr": 18, "setup_per_employee": 6000,  "legal": 25000},
    "medium": {"avg_salary_yr": 70000,  "rent_psf_yr": 45, "setup_per_employee": 9000,  "legal": 50000},
    "high":   {"avg_salary_yr": 130000, "rent_psf_yr": 95, "setup_per_employee": 14000, "legal": 90000},
}
SQFT_PER_EMPLOYEE = 90        # industry rule-of-thumb for office space
EMPLOYER_OVERHEAD = 1.30      # benefits, payroll tax, equipment ~30% on top of salary

# ----- regex parsers (currency-aware) -----
# matches $1,234 / £45 / €1.23k / 1,500 etc.
_NUM_RE = re.compile(
    r"(?:[\$£€¥₹]\s*)?(\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?|\d{1,4})\s*(k|thousand|m|million|lakh|lakhs|crore|crores)?",
    re.IGNORECASE,
)

def _to_number(raw: str, unit: str | None) -> float:
    n = float(raw.replace(",", ""))
    if not unit:
        return n
    u = unit.lower()
    if u in ("k", "thousand"): return n * 1_000
    if u in ("m", "million"):  return n * 1_000_000
    if u in ("lakh", "lakhs"):     return n * 100_000
    if u in ("crore", "crores"):   return n * 10_000_000
    return n


def _parse_rent_psf(snippets: list[str]) -> float | None:
    """Find a $/sqft/year figure in scraped snippets."""
    candidates = []
    for s in snippets:
        if not s: continue
        s_low = s.lower()
        # look for $/sqft style phrases
        for m in re.finditer(r"([\$£€]?\s*\d{1,4}(?:\.\d+)?)\s*(?:per|/)?\s*(?:sq\s*ft|sqft|square\s*foot|psf)", s_low):
            try:
                v = float(re.sub(r"[^\d.]", "", m.group(1)))
                # plausibility filter: $5–$300 / sqft / year
                if 5 <= v <= 300:
                    candidates.append(v)
            except ValueError:
                continue
    if not candidates: return None
    candidates.sort()
    return candidates[len(candidates) // 2]   # median -> robust to outliers


def _parse_salary(snippets: list[str]) -> float | None:
    """Find an average annual salary figure in scraped snippets."""
    candidates = []
    for s in snippets:
        if not s: continue
        s_low = s.lower()
        # any sentence that talks about salary in any unit
        is_salary_snippet = any(k in s_low for k in (
            "salary", "salaries", "earn", "earns", "earning",
            "pay ", "paid", "wage", "compensation", "ctc", "package"
        ))
        if not is_salary_snippet:
            continue
        for m in _NUM_RE.finditer(s_low):
            raw, unit = m.group(1), m.group(2)
            try:
                v = _to_number(raw, unit)
            except ValueError:
                continue
            # lakh/crore -> INR; convert to USD (~₹85/$1) for the comparison
            if unit and unit.lower() in ("lakh", "lakhs", "crore", "crores"):
                v = v / 85.0
            # plausibility filter: $8k – $400k annual
            if 8_000 <= v <= 400_000:
                candidates.append(v)
    if not candidates: return None
    candidates.sort()
    return candidates[len(candidates) // 2]


async def _scrape_city_costs(city: str, country: str) -> dict:
    """Returns dict with rent_psf_yr, avg_salary_yr (None if not found), plus source URLs."""
    if not city:
        return {"rent_psf_yr": None, "avg_salary_yr": None, "rent_sources": [], "salary_sources": []}

    rent_q   = f"office space rent per square foot {city} {country} 2026"
    salary_q = f"average tech salary {city} {country} 2026"

    try:
        rent_res, sal_res = await asyncio.gather(
            fetch_serp(rent_q, "office_rent"),
            fetch_serp(salary_q, "city_salary"),
        )
    except Exception:
        rent_res, sal_res = [], []

    rent_snips = [(r.get("title", "") + " " + r.get("snippet", "")) for r in rent_res]
    sal_snips  = [(r.get("title", "") + " " + r.get("snippet", "")) for r in sal_res]

    return {
        "rent_psf_yr":    _parse_rent_psf(rent_snips),
        "avg_salary_yr":  _parse_salary(sal_snips),
        "rent_sources":   [r.get("url", "") for r in rent_res[:3] if r.get("url")],
        "salary_sources": [r.get("url", "") for r in sal_res[:3]  if r.get("url")],
    }


def infer_cost_tier(location):
    country = (location.get("country") or "").strip().lower()
    return COUNTRY_TIER.get(country, "medium")


def compute_cost(headcount: int, rent_psf_yr: float, avg_salary_yr: float,
                 setup_per_employee: float, legal: float) -> dict:
    sqft = headcount * SQFT_PER_EMPLOYEE
    real_estate_yr   = round(sqft * rent_psf_yr)
    salaries_yr      = round(headcount * avg_salary_yr * EMPLOYER_OVERHEAD)
    one_time_setup   = round(headcount * setup_per_employee)
    annual_operating = real_estate_yr + salaries_yr
    subtotal         = annual_operating + one_time_setup + legal
    contingency      = round(subtotal * 0.15)
    total            = subtotal + contingency

    return {
        "annual_operating_cost":    annual_operating,
        "real_estate_cost":         real_estate_yr,
        "salaries_cost":            salaries_yr,
        "one_time_setup_cost":      one_time_setup,
        "legal_compliance_cost":    round(legal),
        "contingency":              contingency,
        "estimated_first_year_cost": total,
        "currency":                 "USD",
        "office_sqft":              sqft,
        "rent_psf_yr":              round(rent_psf_yr, 2),
        "avg_salary_yr":            round(avg_salary_yr),
    }


async def run_finance_agent(case, site_context, incentives_context):
    case_id   = case["case_id"]
    location  = site_context.get("recommended_location", {}) or {}
    headcount = case.get("headcount", 10)
    city      = (location.get("city") or "").strip()
    country   = (location.get("country") or case.get("country") or "").strip()

    tier     = infer_cost_tier(location or {"country": country})
    fb       = TIER_FALLBACK[tier]

    scrape   = await _scrape_city_costs(city, country)
    rent     = scrape["rent_psf_yr"]   or fb["rent_psf_yr"]
    salary   = scrape["avg_salary_yr"] or fb["avg_salary_yr"]
    rent_src = "bright_data_scrape" if scrape["rent_psf_yr"]   else "tier_fallback"
    sal_src  = "bright_data_scrape" if scrape["avg_salary_yr"] else "tier_fallback"

    cost = compute_cost(
        headcount, rent, salary,
        setup_per_employee=fb["setup_per_employee"],
        legal=fb["legal"],
    )

    output = {
        "location":  location,
        "headcount": headcount,
        "cost_tier": tier,
        "first_year_cost": cost,
        "data_sources": {
            "rent_basis":   rent_src,
            "salary_basis": sal_src,
            "rent_urls":    scrape["rent_sources"],
            "salary_urls":  scrape["salary_sources"],
        },
        "incentive_fit": incentives_context.get("incentive_fit", "medium"),
        "finance_recommendation":
            "pilot office" if cost["estimated_first_year_cost"] < 900_000
            else "partner-led or phased entry",
    }

    save_agent_output(case_id, "finance_agent", output)
    await band.send_context(
        case_id=case_id,
        from_agent="finance_agent",
        to_agent="compliance_agent",
        payload=output,
    )
    return output