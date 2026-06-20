import json, re
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, MAX_TOKENS
from scraper import fetch_serp
from band_layer.context_store import save_agent_output
from band_layer.band_client import BandClient

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
band = BandClient()

async def run_incentives_agent(case, site_context):
    case_id = case["case_id"]
    location = site_context.get("recommended_location", {})

    city = location.get("city", "")
    state = location.get("state", "")
    country = location.get("country", case["country"])

    query = f'{city} {state} {country} business incentives tax credits grants workforce training economic development'

    results = await fetch_serp(query, "government_incentives")

    text = "\n\n".join(
        f"{i+1}. {r['title']}\n{r['url']}\n{r['snippet']}"
        for i, r in enumerate(results)
    )

    prompt = f"""
You are a government incentives analyst.

Analyze possible government support for opening an office in:
City: {city}
State: {state}
Country: {country}

Search Results:
{text}

Evaluate:
- tax credits
- grants
- workforce training
- relocation support
- site-selection support
- innovation/startup support
- permitting/business support

Return ONLY valid JSON:
{{
  "incentive_score": 0,
  "incentive_fit": "low|medium|high",
  "available_support": ["...", "..."],
  "likely_requirements": ["...", "..."],
  "risks": ["...", "..."],
  "sources": ["...", "..."]
}}
"""

    resp = await _openai.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = resp.choices[0].message.content

    try:
        output = json.loads(raw.strip())
    except:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        output = json.loads(m.group()) if m else {}

    save_agent_output(case_id, "incentives_agent", output)

    await band.send_context(
        case_id=case_id,
        from_agent="incentives_agent",
        to_agent="finance_agent",
        payload={
            "site_context": site_context,
            "incentives": output
        }
    )

    return output