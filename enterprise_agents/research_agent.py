from agents import run_all_agents
from synthesis import synthesize
from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient

band = BandClient()

async def run_research_agent(case):
    case_id = case["case_id"]
    company = case["company"]
    market = case["market"]
    country = case["country"]

    agent_results = await run_all_agents(company, market, country)
    report = await synthesize(company, market, country, agent_results)

    output = {
        "company": company,
        "market": market,
        "country": country,
        "probability": report.probability,
        "confidence": report.confidence,
        "timeline": report.timeline,
        "key_findings": report.key_findings,
        "recommended_actions": report.recommended_actions,
        "raw_agent_results": [r.model_dump() for r in agent_results]
    }

    save_agent_output(case_id, "research_agent", output)

    await band.send_context(
        case_id=case_id,
        from_agent="research_agent",
        to_agent="site_selection_agent",
        payload={
            "market_entry_probability": report.probability,
            "market": market,
            "country": country,
            "top_findings": report.key_findings
        }
    )

    return output