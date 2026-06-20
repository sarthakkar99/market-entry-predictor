"""
workflows/scout_workflow.py

Single-company "scout" flow for the Band hackathon.

Given ONE company + target country + industry, this async generator streams the
whole pipeline live as Server-Sent-Event payloads (plain dicts; main.py wraps
them in `data: ...`):

    scout_start
    agent_complete   (x5)  -- the live scout/signal agents on the entering company
    report                 -- entry-readiness synthesis
    competitors_found      -- auto-discovered local competition
    gap_analysis           -- the whitespace the incumbents leave open
    band_start
    band_agent       (x8)  -- the Band plan executing on the gap, one agent at a time
    complete

Everything reuses the existing agents -- this file is mostly orchestration.
"""

import asyncio
import json
import re

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, MAX_TOKENS
from band_layer.context_store import create_case, get_case, save_agent_output
from band_layer.band_client import BandClient
from agents import run_agents_streaming
from synthesis import synthesize

from enterprise_agents.competitor_agent import run_competitor_agent
from enterprise_agents.site_selection_agent import run_site_selection_agent
from enterprise_agents.incentives_agent import run_incentives_agent
from enterprise_agents.finance_agent import run_finance_agent
from enterprise_agents.compliance_agent import run_compliance_agent
from enterprise_agents.red_team_agent import run_red_team_agent
from enterprise_agents.human_approval_agent import run_human_approval_agent
from enterprise_agents.executive_agent import run_executive_agent
from enterprise_agents.task_assignment_agent import run_task_assignment_agent

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
band = BandClient()


def _safe_json(raw: str) -> dict:
    try:
        return json.loads(raw.strip())
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            return json.loads(m.group()) if m else {}
        except Exception:
            return {}


GAP_PROMPT = """You are a market strategy analyst.

Company looking to enter: {company}
Industry: {market}
Target country: {country}

Entry-readiness report:
{report}

Local competitors already in this market:
{competitors}

EVIDENCE BLOCK from scraped articles about underserved segments and pain points
in this market (the ONLY source of facts for "underserved_segments" and
"incumbent_weaknesses"):
{evidence}

Find the MARKET GAP -- the whitespace the incumbents leave open that {company}
could win. Rules:
- "underserved_segments" must derive from the EVIDENCE BLOCK or competitor
  weaknesses, not invention
- "incumbent_weaknesses" must come from the competitor list or evidence
- If evidence is thin, return shorter lists rather than inventing items

Return ONLY valid JSON:
{{
  "gap_title": "short punchy name for the opportunity",
  "gap_summary": "2-3 sentence description of the gap",
  "underserved_segments": ["segment 1", "segment 2"],
  "incumbent_weaknesses": ["weakness 1", "weakness 2"],
  "recommended_wedge": "the single best way to enter and win",
  "differentiation": ["how to stand out 1", "how to stand out 2"],
  "confidence": "low|medium|high"
}}
"""


def _fallback_gap(company, competitors):
    weaknesses = []
    for c in (competitors or []):
        weaknesses.extend(c.get("weaknesses", [])[:1])
    weaknesses = weaknesses[:3] or ["slow product cycles", "weak digital experience"]
    return {
        "gap_title": f"Underserved segment vs local incumbents",
        "gap_summary": (
            f"{company} can enter where incumbents are weakest: customer experience, "
            f"speed, and integrations. A focused pilot beats a broad launch."
        ),
        "underserved_segments": ["SMB / mid-market", "digital-first customers"],
        "incumbent_weaknesses": weaknesses,
        "recommended_wedge": "Partner-led pilot targeting an underserved segment.",
        "differentiation": ["faster onboarding", "modern API / integrations", "compliance-ready design"],
        "confidence": "medium",
    }


async def _gap_analysis(company, market, country, report, competitors):
    # Scrape for underserved-segment and customer-pain signals
    qs = [
        f"{market} underserved customer segments {country} 2026",
        f"{market} customer pain points complaints {country}",
    ]
    evidence_results = []
    try:
        from scraper import fetch_serp as _fs
        result_groups = await asyncio.gather(
            *[_fs(q, "gap_signals") for q in qs],
            return_exceptions=True,
        )
        seen = set()
        for g in result_groups:
            if isinstance(g, list):
                for r in g:
                    u = r.get("url","")
                    if u and u not in seen:
                        seen.add(u)
                        evidence_results.append(r)
    except Exception:
        pass

    used_live = bool(evidence_results) and any(
        r.get("url") and "example.com" not in r.get("url","") for r in evidence_results
    )
    evidence_text = "\n\n".join(
        f"[{i+1}] {r.get('title','')}\n{r.get('snippet','')}\nSOURCE: {r.get('url','')}"
        for i, r in enumerate(evidence_results[:6])
    ) or "(no live evidence available)"

    if _openai is None:
        out = _fallback_gap(company, competitors)
        out["data_sources"] = {"basis":"llm_only_fallback","queries":qs,"urls":[]}
        return out

    prompt = GAP_PROMPT.format(
        company=company, market=market, country=country,
        report=json.dumps(report, indent=2)[:2000],
        competitors=json.dumps(competitors, indent=2)[:2000],
        evidence=evidence_text,
    )
    try:
        resp = await _openai.chat.completions.create(
            model=OPENAI_MODEL, max_tokens=MAX_TOKENS, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        out = _safe_json(resp.choices[0].message.content or "{}")
    except Exception:
        out = {}
    if not out.get("gap_title"):
        out = _fallback_gap(company, competitors)
    out.setdefault("underserved_segments", [])
    out.setdefault("incumbent_weaknesses", [])
    out.setdefault("differentiation", [])
    out.setdefault("confidence", "medium" if used_live else "low")

    out["data_sources"] = {
        "basis":   "bright_data_scrape" if used_live else "llm_only_fallback",
        "queries": qs,
        "urls":    [r.get("url","") for r in evidence_results[:5] if r.get("url")],
    }
    return out


async def scout_stream(company, market, country, headcount=10):
    case = create_case(company, market, country, headcount)
    case_id = case["case_id"]

    yield {
        "type": "scout_start",
        "company": company, "market": market, "country": country,
        "case_id": case_id,
    }

    # --- discovery + scout agents run concurrently -----------------------------
    comp_task = asyncio.create_task(
        run_competitor_agent(case, research_context={
            "company": company, "market": market, "country": country
        })
    )

    agent_results = []
    async for r in run_agents_streaming(company, market, country):
        agent_results.append(r)
        pct = round((r.score / r.max_score) * 100) if r.max_score else 0
        strength = "strong" if pct >= 70 else "moderate" if pct >= 40 else "weak"
        yield {
            "type": "agent_complete", "company": company, "agent_id": r.agent_id,
            "data": {
                "score": r.score, "max_score": r.max_score,
                "results_found": len(r.findings), "strength": strength,
                "evidence": r.findings, "sources": r.sources,
            },
        }

    # --- entry-readiness report ------------------------------------------------
    report = await synthesize(company, market, country, agent_results)
    research_output = {
        "company": company, "market": market, "country": country,
        "probability": report.probability, "confidence": report.confidence,
        "timeline": report.timeline, "verdict": report.verdict,
        "key_findings": report.key_findings,
        "recommended_actions": report.recommended_actions,
        "raw_agent_results": [r.model_dump() for r in agent_results],
    }
    save_agent_output(case_id, "research_agent", research_output)
    await band.send_context(
        case_id=case_id, from_agent="research_agent", to_agent="site_selection_agent",
        payload={"market_entry_probability": report.probability,
                 "market": market, "country": country,
                 "top_findings": report.key_findings},
    )
    yield {
        "type": "report", "company": company,
        "data": {
            "probability": report.probability, "confidence": report.confidence,
            "timeline": report.timeline, "verdict": report.verdict,
            "key_findings": report.key_findings,
            "strategic_implication": report.strategic_implication,
            "recommended_actions": report.recommended_actions,
        },
    }

    # --- local competition -----------------------------------------------------
    try:
        competitors_out = await comp_task
    except Exception as exc:
        competitors_out = {"competitors": [], "competitive_summary": f"discovery failed: {exc}"}
    yield {
        "type": "competitors_found", "company": company,
        "data": {
            "competitors": competitors_out.get("competitors", []),
            "competitive_threat": competitors_out.get("competitive_threat", "medium"),
            "market_maturity": competitors_out.get("market_maturity", "growing"),
            "competitive_summary": competitors_out.get("competitive_summary", ""),
            "recommended_positioning": competitors_out.get("recommended_positioning", ""),
        },
    }

    # --- the gap ---------------------------------------------------------------
    gap = await _gap_analysis(company, market, country, research_output,
                              competitors_out.get("competitors", []))
    save_agent_output(case_id, "gap_agent", gap)
    yield {"type": "gap_analysis", "company": company, "data": gap}

    # --- deploy the Band plan, one agent at a time -----------------------------
    yield {"type": "band_start", "company": company}

    # tiny helper: stream 2 fast "thoughts" + a slow one, then the result
    async def _think(agent_id, thoughts, delay=0.4):
        for t in thoughts:
            yield {"type": "band_thought", "company": company, "agent": agent_id, "text": t}
            await asyncio.sleep(delay)

    async for ev in _think("site_selection", [
        f"Pulling office-market data for {country}…",
        f"Scoring talent pool, infra, and cost-of-living…",
        f"Comparing top 3 candidate cities…",
    ]): yield ev
    site = await run_site_selection_agent(case, research_context=research_output)
    yield {"type": "band_agent", "company": company, "agent": "site_selection", "data": site}

    async for ev in _think("incentives", [
        f"Querying government economic-development programs in {country}…",
        f"Cross-checking eligibility for foreign-entity setup…",
        f"Estimating support-package value…",
    ]): yield ev
    incentives = await run_incentives_agent(case, site_context=site)
    yield {"type": "band_agent", "company": company, "agent": "incentives", "data": incentives}

    loc_city = (site.get("recommended_location") or {}).get("city") or country
    async for ev in _think("finance", [
        f"Scraping office rent per sqft in {loc_city} via Bright Data…",
        f"Pulling average tech salary in {loc_city}…",
        f"Building year-1 P&L from live numbers…",
    ]): yield ev
    finance = await run_finance_agent(case, site_context=site, incentives_context=incentives)
    yield {"type": "band_agent", "company": company, "agent": "finance", "data": finance}

    async for ev in _think("compliance", [
        f"Mapping {market} regulatory regime in {country}…",
        "Checking data-privacy, licensing, and KYC/AML requirements…",
        "Flagging concerns requiring human review…",
    ]): yield ev
    compliance = await run_compliance_agent(case, finance_context=finance)
    yield {"type": "band_agent", "company": company, "agent": "compliance", "data": compliance}

    async for ev in _think("red_team", [
        "Stress-testing the plan against worst-case scenarios…",
        "Surfacing hidden risks the other agents missed…",
        "Computing risk-adjusted impact…",
    ]): yield ev
    red_team = await run_red_team_agent(case, all_context={
        "research": research_output, "site_selection": site, "incentives": incentives,
        "finance": finance, "compliance": compliance,
    })
    yield {"type": "band_agent", "company": company, "agent": "red_team", "data": red_team}

    async for ev in _think("human_approval", [
        "Routing to human approver if risk threshold tripped…",
        "Preparing decision package for sign-off…",
    ]): yield ev
    human = await run_human_approval_agent(case, compliance_context=compliance,
                                           red_team_context=red_team)
    yield {"type": "band_agent", "company": company, "agent": "human_approval", "data": human}

    async for ev in _think("executive", [
        "Consolidating signals from all 7 prior agents…",
        "Weighing entry probability vs. regulatory + cost risk…",
        "Drafting executive recommendation…",
    ]): yield ev
    executive = await run_executive_agent(case, all_context={
        "research": research_output, "site_selection": site, "incentives": incentives,
        "finance": finance, "compliance": compliance, "red_team": red_team,
        "human_approval": human,
    })
    yield {"type": "band_agent", "company": company, "agent": "executive", "data": executive}

    async for ev in _think("task_assignment", [
        "Decomposing the plan into team-level tasks…",
        "Assigning owners, deadlines, and dependencies…",
    ]): yield ev
    tasks = await run_task_assignment_agent(case, executive)
    yield {"type": "band_agent", "company": company, "agent": "task_assignment", "data": tasks}

    final_case = get_case(case_id)
    yield {
        "type": "complete", "company": company,
        "data": {
            "case_id": case_id,
            "gap": gap,
            "competitors": competitors_out.get("competitors", []),
            "executive_decision": executive,
            "tasks": tasks,
            "messages": final_case["messages"],
        },
    }