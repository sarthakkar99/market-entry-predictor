"""
Compliance agent — scrape recent regulatory news for {market}+{country},
then let the LLM extract structured concerns from the snippets.

Preserves the original hardcoded REGULATED_MARKETS list as a safety net
so we always return *something* compliance-relevant even when scraping
is empty.
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


# ---- safety-net concerns when scraping yields nothing ----
REGULATED_MARKETS = {
    "insurance":  ["insurance licensing", "consumer protection", "data privacy"],
    "finance":    ["payments regulation", "KYC/AML", "data privacy"],
    "payments":   ["payments regulation", "KYC/AML", "card scheme rules"],
    "healthcare": ["health data privacy", "medical compliance", "patient data security"],
    "banking":    ["banking license", "KYC/AML", "financial regulator review"],
    "ai":         ["model risk", "data governance", "AI policy compliance"],
    "fintech":    ["payments regulation", "KYC/AML", "data privacy"],
    "crypto":     ["virtual asset license", "AML / travel rule", "consumer protection"],
}


PROMPT = """You are a regulatory-compliance analyst.

EVIDENCE BLOCK (the ONLY source of facts you may use):
{evidence}

Company entering: {company}
Industry:         {market}
Country:          {country}
Recommended HQ:   {city}

Identify the regulatory concerns this expansion will face. Rules:
- Use ONLY facts present in the EVIDENCE BLOCK
- "concerns" should be specific (named regulators, laws, frameworks where possible)
- If evidence is thin, return short conservative lists
- "regulatory_risk" is your judgment on the severity: low | medium | high
- "human_approval_required" should be true for high-risk regulated industries

Return ONLY valid JSON:
{{
  "regulatory_risk": "low|medium|high",
  "concerns": ["specific concern with source if possible", "..."],
  "named_regulators": ["e.g. FCA, MAS, RBI"],
  "human_approval_required": true|false,
  "recommendation": "1-sentence next step"
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


def _hardcoded_fallback(market: str) -> dict:
    market_low = (market or "").lower()
    concerns, risk, human = [], "low", False
    for key, items in REGULATED_MARKETS.items():
        if key in market_low:
            concerns, risk, human = items, "high", True
            break
    if not concerns:
        concerns = ["standard business registration", "employment law review", "tax registration"]
    return {
        "regulatory_risk": risk,
        "concerns": concerns,
        "named_regulators": [],
        "human_approval_required": human,
        "recommendation": "legal review required before launch" if human else "standard review sufficient",
        "_source": "hardcoded_fallback",
    }


async def run_compliance_agent(case, finance_context):
    case_id = case["case_id"]
    company = case["company"]
    market  = case["market"]
    country = case["country"]
    site    = finance_context.get("location", {}) or {}
    city    = site.get("city", "")

    qs = [
        f"{market} regulation {country} 2026",
        f"{market} regulator license requirements {country}",
        f"{market} compliance foreign company {country}",
    ]

    try:
        result_groups = await asyncio.gather(*[fetch_serp(q, "compliance_news") for q in qs])
    except Exception:
        result_groups = ([], [], [])

    # dedupe by URL
    results, seen = [], set()
    for g in result_groups:
        for r in g:
            u = r.get("url", "")
            if u and u not in seen:
                seen.add(u)
                results.append(r)

    evidence_text = "\n\n".join(
        f"[{i+1}] {r.get('title','')}\n{r.get('snippet','')}\nSOURCE: {r.get('url','')}"
        for i, r in enumerate(results[:8])
    )

    used_live = bool(results) and any(
        r.get("url") and "example.com" not in r.get("url","") for r in results
    )

    output = None
    if used_live and _openai is not None:
        try:
            resp = await _openai.chat.completions.create(
                model=OPENAI_MODEL, max_tokens=MAX_TOKENS, temperature=0,
                messages=[{"role":"user","content": PROMPT.format(
                    evidence=evidence_text, company=company, market=market,
                    country=country, city=city,
                )}],
            )
            out = _safe_json(resp.choices[0].message.content or "{}")
            if out.get("concerns"):
                output = out
                output["_source"] = "bright_data_scrape"
        except Exception:
            output = None

    if output is None:
        output = _hardcoded_fallback(market)

    # ensure keys
    output.setdefault("regulatory_risk", "medium")
    output.setdefault("concerns", [])
    output.setdefault("named_regulators", [])
    output.setdefault("human_approval_required", output["regulatory_risk"] == "high")
    output.setdefault("recommendation", "legal review recommended")

    output["data_sources"] = {
        "basis":   output.pop("_source", "bright_data_scrape"),
        "queries": qs,
        "urls":    [r.get("url","") for r in results[:5] if r.get("url")],
    }

    save_agent_output(case_id, "compliance_agent", output)
    await band.send_context(
        case_id=case_id, from_agent="compliance_agent",
        to_agent="red_team_agent",
        payload={"finance_context": finance_context, "compliance_context": output},
    )
    return output