"""
Competitor agent — hybrid scrape + constrained LLM.

Pipeline:
  1. Run TWO parallel Bright Data SERP queries (broad + alternatives).
  2. Build evidence block with [N] indices linking to specific URLs.
  3. LLM extracts competitors ONLY from named entities in the snippets,
     and tags each competitor with the index of the source snippet.
  4. Each competitor in the output carries its own source_url.

Hard rule: LLM cannot invent competitor names. If it does, post-processing
drops them.
"""

import asyncio
import json
import re

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, MAX_TOKENS
from scraper import fetch_serp
from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
band = BandClient()


PROMPT = """You are a competitive intelligence analyst.

Company entering: {company}
Industry:         {market}
Country:          {country}

EVIDENCE BLOCK (the ONLY source of competitor names allowed):
{evidence}

Rules:
- Every competitor in your output must be named explicitly in the EVIDENCE BLOCK
- "source_index" on each competitor must match the [N] tag of the snippet that
  named them
- If the evidence is thin, return fewer competitors rather than inventing them
- Strengths and weaknesses should derive from snippet context where possible

Return ONLY valid JSON:
{{
  "competitive_threat": "low|medium|high",
  "market_maturity":    "early|growing|mature",
  "competitors": [
    {{
      "name":         "name from EVIDENCE",
      "type":         "local|global|startup|enterprise",
      "strengths":    ["...", "..."],
      "weaknesses":   ["...", "..."],
      "threat_level": "low|medium|high",
      "source_index": 1
    }}
  ],
  "competitive_summary":     "1-2 sentence summary grounded in evidence",
  "recommended_positioning": "how the company should position itself"
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


def _format_evidence(results: list[dict]) -> str:
    if not results:
        return "No search results found."
    return "\n\n".join(
        f"[{i+1}] {r.get('title','')}\n{r.get('snippet','')}\nSOURCE: {r.get('url','')}"
        for i, r in enumerate(results[:8])
    )


def _name_in_text(name: str, texts: list[str]) -> bool:
    """Cheap guard: was this competitor name actually mentioned anywhere?"""
    if not name:
        return False
    name_low = name.lower().strip()
    return any(name_low in (t or "").lower() for t in texts)


async def run_competitor_agent(case: dict, research_context: dict) -> dict:
    case_id = case["case_id"]
    company = case["company"]
    market  = case["market"]
    country = case["country"]

    qs = [
        f"top {market} companies in {country} 2026",
        f"{market} market leaders {country} {company} alternatives",
    ]

    # parallel scrapes
    try:
        result_groups = await asyncio.gather(*[fetch_serp(q, "competitor_agent") for q in qs])
    except Exception:
        result_groups = ([], [])

    # dedupe by URL
    results, seen = [], set()
    for group in result_groups:
        for r in group:
            u = r.get("url", "")
            if u and u not in seen:
                seen.add(u)
                results.append(r)

    used_live = bool(results) and any(
        r.get("url") and "example.com" not in r.get("url","") for r in results
    )

    evidence_text = _format_evidence(results)
    all_snippets  = [(r.get("title","") + " " + r.get("snippet","")) for r in results]

    if not used_live or _openai is None:
        output = {
            "competitive_threat": "medium",
            "market_maturity":    "growing",
            "competitors":        [],
            "competitive_summary":     f"Live competitor data unavailable for {market} in {country}.",
            "recommended_positioning": "Run a small pilot to gather direct competitor intelligence.",
        }
    else:
        try:
            resp = await _openai.chat.completions.create(
                model=OPENAI_MODEL, max_tokens=MAX_TOKENS, temperature=0,
                messages=[
                    {"role":"system","content":"You are a precise competitive intelligence analyst."},
                    {"role":"user","content": PROMPT.format(
                        evidence=evidence_text, company=company, market=market, country=country)},
                ],
            )
            output = _safe_json(resp.choices[0].message.content or "{}")
        except Exception as exc:
            output = {
                "competitive_threat": "medium",
                "market_maturity":    "growing",
                "competitors":        [],
                "competitive_summary":     f"Competitor analysis failed: {exc}",
                "recommended_positioning": "Cautious pilot entry until more competitor evidence is available.",
            }

    # ---- HARD GROUNDING: drop any competitor not literally in snippets ----
    grounded = []
    for c in output.get("competitors", []):
        name = c.get("name","")
        idx  = c.get("source_index", 0)
        if not _name_in_text(name, all_snippets):
            continue  # invented by LLM, drop it
        # attach the actual URL of the snippet that named them
        try:
            url = results[int(idx) - 1].get("url","") if 0 < int(idx) <= len(results) else ""
        except (ValueError, TypeError):
            url = ""
        # if LLM gave a bad index, find first snippet that mentions the name
        if not url:
            for r in results:
                if name.lower() in (r.get("snippet","") + r.get("title","")).lower():
                    url = r.get("url","")
                    break
        c["source_url"] = url
        grounded.append(c)
    output["competitors"] = grounded

    # ensure defaults
    output.setdefault("competitive_threat", "medium")
    output.setdefault("market_maturity",    "growing")
    output.setdefault("competitive_summary",     "Competitive analysis completed.")
    output.setdefault("recommended_positioning",
                     "Enter with a differentiated pilot strategy and monitor competitor response.")

    # global sources list for the panel footer
    output["sources"] = [r.get("url","") for r in results[:6] if r.get("url")]

    output["data_sources"] = {
        "basis":   "bright_data_scrape" if used_live else "llm_only_fallback",
        "queries": qs,
        "urls":    [r.get("url","") for r in results[:6] if r.get("url")],
    }

    save_agent_output(case_id, "competitor_agent", output)
    await band.send_context(
        case_id=case_id, from_agent="competitor_agent",
        to_agent="site_selection_agent",
        payload={
            "competitive_threat":      output["competitive_threat"],
            "market_maturity":         output["market_maturity"],
            "competitors":             output["competitors"],
            "recommended_positioning": output["recommended_positioning"],
            "competitive_summary":     output["competitive_summary"],
        },
    )
    return output