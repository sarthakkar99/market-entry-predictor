"""
Site selection agent — hybrid scrape + LLM.

Flow:
  1. LLM proposes 3 candidate cities for the country.
  2. We scrape Bright Data for each candidate:
       - tech ecosystem density
       - talent supply (job market)
       - foreign company presence
  3. We score each candidate from the scraped evidence.
  4. LLM rewrites the narrative ("why_this_location", "risks") using the
     scraped facts, but cannot change the numeric ranking.

Hard rule: SCRAPED data is authoritative. LLM is decoration.
"""

import asyncio
import json
import re

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, MAX_TOKENS
from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient
from scraper import fetch_serp

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
band = BandClient()


# -------- Step 1: ask the LLM for 3 candidate cities for the country --------
CANDIDATE_PROMPT = """For a {market} company called {company} entering {country},
list the 3 best candidate cities for a small expansion office.
Return ONLY valid JSON:
{{"candidates": [{{"city":"...","state":"..."}}, ...]}}
"""

# -------- Step 4: ask the LLM to write the narrative using scraped facts ----
NARRATIVE_PROMPT = """You are a site-selection analyst writing the narrative for
a city already chosen by quantitative scoring.

DO NOT change the recommended city or score. Use ONLY the evidence below.

Company: {company}
Market: {market}
Country: {country}
Recommended city: {city}, {state}
Quantitative score: {score}/100 (this is fixed, do not change it)

Scraped evidence:
{evidence}

Return ONLY valid JSON:
{{
  "why_this_location": ["fact-grounded reason 1", "fact-grounded reason 2", "..."],
  "risks": ["risk 1", "risk 2"]
}}
"""


def _safe_json(raw: str) -> dict:
    try:
        return json.loads(raw.strip())
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            return json.loads(m.group()) if m else {}
        except Exception:
            return {}


async def _llm_candidates(company, market, country):
    """Step 1: ask LLM for 3 candidate cities."""
    if _openai is None:
        return _fallback_candidates(country)
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL, max_tokens=400, temperature=0,
            messages=[{"role":"user","content": CANDIDATE_PROMPT.format(
                company=company, market=market, country=country)}],
        )
        out = _safe_json(resp.choices[0].message.content or "{}")
        cands = out.get("candidates", [])
        if not cands:
            return _fallback_candidates(country)
        return cands[:3]
    except Exception:
        return _fallback_candidates(country)


def _fallback_candidates(country):
    table = {
        "united states": [{"city":"San Francisco","state":"CA"},{"city":"New York","state":"NY"},{"city":"Austin","state":"TX"}],
        "united kingdom":[{"city":"London","state":""},{"city":"Manchester","state":""},{"city":"Edinburgh","state":""}],
        "india":          [{"city":"Bangalore","state":"KA"},{"city":"Mumbai","state":"MH"},{"city":"Hyderabad","state":"TG"}],
        "germany":        [{"city":"Berlin","state":""},{"city":"Munich","state":""},{"city":"Hamburg","state":""}],
        "japan":          [{"city":"Tokyo","state":""},{"city":"Osaka","state":""},{"city":"Fukuoka","state":""}],
        "singapore":      [{"city":"Singapore","state":""}],
        "france":         [{"city":"Paris","state":""},{"city":"Lyon","state":""},{"city":"Toulouse","state":""}],
        "canada":         [{"city":"Toronto","state":"ON"},{"city":"Vancouver","state":"BC"},{"city":"Montreal","state":"QC"}],
        "australia":      [{"city":"Sydney","state":""},{"city":"Melbourne","state":""},{"city":"Brisbane","state":""}],
        "uae":            [{"city":"Dubai","state":""},{"city":"Abu Dhabi","state":""}],
        "brazil":         [{"city":"Sao Paulo","state":""},{"city":"Rio de Janeiro","state":""}],
        "netherlands":    [{"city":"Amsterdam","state":""},{"city":"Rotterdam","state":""}],
    }
    return table.get((country or "").lower(), [{"city": country or "—", "state": ""}])


# -------- Step 2: scrape signals for each candidate --------
async def _scrape_city_signals(city, country, market):
    """Returns: dict with three signal scores + source URLs."""
    if not city:
        return {"tech_signal":0, "talent_signal":0, "foreign_signal":0, "sources":[], "evidence":[]}

    qs = {
        "tech":    f"tech startups headquartered in {city} {country} 2026",
        "talent":  f"software engineer hiring jobs {city} {country} 2026",
        "foreign": f"{market} foreign companies office {city} {country}",
    }
    try:
        results = await asyncio.gather(
            fetch_serp(qs["tech"],    "site_tech"),
            fetch_serp(qs["talent"],  "site_talent"),
            fetch_serp(qs["foreign"], "site_foreign"),
            return_exceptions=True,
        )
    except Exception:
        results = ([], [], [])

    tech, talent, foreign = [r if isinstance(r, list) else [] for r in results]

    # Density signal: number of results that name the city (cheap, robust)
    city_low = city.lower()
    def _density(rs):
        n = 0
        for r in rs:
            txt = (r.get("title","") + " " + r.get("snippet","")).lower()
            if city_low in txt:
                n += 1
        # cap at 5 -> normalize to 0-100
        return min(n, 5) * 20

    sources = []
    evidence = []
    for r in tech[:3] + talent[:3] + foreign[:3]:
        u = r.get("url","")
        if u and u not in sources:
            sources.append(u)
        snip = r.get("snippet","").strip()
        if snip:
            evidence.append(snip[:200])

    return {
        "tech_signal":    _density(tech),
        "talent_signal":  _density(talent),
        "foreign_signal": _density(foreign),
        "sources":        sources[:8],
        "evidence":       evidence[:6],
    }


# -------- Step 3: score from scraped signals --------
def _score(signals):
    # weighted: talent matters most for an expansion office
    return round(
        signals["talent_signal"]  * 0.45 +
        signals["tech_signal"]    * 0.35 +
        signals["foreign_signal"] * 0.20
    )


# -------- Step 4: ask LLM to write the narrative using the scraped facts ----
async def _llm_narrative(company, market, country, city, state, score, evidence):
    fallback = {
        "why_this_location": [
            f"{city} surfaced as a top result across our hiring, tech-ecosystem, and foreign-company queries.",
            "Scraped signals indicate active hiring and competitor / partner presence in this metro.",
        ],
        "risks": [
            "Quality of evidence varies per query; verify hiring volume directly.",
            "Cost-of-living and talent competition not fully captured in density signal alone.",
        ],
    }
    if _openai is None or not evidence:
        return fallback
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL, max_tokens=MAX_TOKENS, temperature=0,
            messages=[{"role":"user","content": NARRATIVE_PROMPT.format(
                company=company, market=market, country=country,
                city=city, state=state, score=score,
                evidence="\n".join(f"- {e}" for e in evidence[:6])
            )}],
        )
        out = _safe_json(resp.choices[0].message.content or "{}")
        return {
            "why_this_location": out.get("why_this_location") or fallback["why_this_location"],
            "risks":             out.get("risks")             or fallback["risks"],
        }
    except Exception:
        return fallback


# -------- main agent ---------
async def run_site_selection_agent(case, research_context):
    case_id   = case["case_id"]
    company   = case["company"]
    market    = case["market"]
    country   = case["country"]

    # 1. propose candidates
    candidates = await _llm_candidates(company, market, country)

    # 2. scrape signals for each candidate IN PARALLEL
    scraped = await asyncio.gather(*[
        _scrape_city_signals(c.get("city",""), country, market) for c in candidates
    ])

    # 3. score and rank
    scored = []
    for cand, sig in zip(candidates, scraped):
        scored.append({
            "city":   cand.get("city",""),
            "state":  cand.get("state",""),
            "score":  _score(sig),
            "signals": sig,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    winner = scored[0]

    # 4. ask LLM to write the *narrative* using only the scraped evidence
    narrative = await _llm_narrative(
        company, market, country,
        winner["city"], winner["state"], winner["score"],
        winner["signals"]["evidence"],
    )

    # any signal at all means we used Bright Data successfully on the winner
    used_live = any(winner["signals"][k] > 0 for k in ("tech_signal","talent_signal","foreign_signal"))

    output = {
        "recommended_location": {
            "city":    winner["city"],
            "state":   winner["state"],
            "country": country,
            "location_score":    winner["score"],
            "why_this_location": narrative["why_this_location"],
            "risks":             narrative["risks"],
        },
        "alternatives": [
            {
                "city":   s["city"],
                "state":  s["state"],
                "score":  s["score"],
                "reason": f"talent {s['signals']['talent_signal']}, tech {s['signals']['tech_signal']}, foreign {s['signals']['foreign_signal']}",
            } for s in scored[1:]
        ],
        "data_sources": {
            "basis":   "bright_data_scrape" if used_live else "llm_only_fallback",
            "queries": ["tech ecosystem", "talent hiring", "foreign company presence"],
            "urls":    winner["signals"]["sources"],
        },
        "signals": winner["signals"],   # full raw signals for the modal
    }

    save_agent_output(case_id, "site_selection_agent", output)
    await band.send_context(
        case_id=case_id, from_agent="site_selection_agent",
        to_agent="incentives_agent", payload=output,
    )
    return output