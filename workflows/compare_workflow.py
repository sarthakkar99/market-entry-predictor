"""
workflows/compare_workflow.py

Runs scout_stream() in parallel for 2-3 target countries. Multiplexes their
events back to the client tagged with `country` so the frontend can route
each event into the right column.

Event types streamed (in addition to passthrough):
  compare_start  -- payload: {company, market, countries: [...]}
  country_event  -- payload: {country, inner: <original event>}
  compare_done   -- payload: {summary: per-country roll-up for comparison view}
"""

import asyncio
from workflows.scout_workflow import scout_stream


async def compare_stream(company: str, market: str, countries: list[str], headcount: int = 10):
    yield {"type": "compare_start", "company": company, "market": market, "countries": countries}

    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()
    results = {}  # country -> roll-up dict

    async def worker(country: str):
        rollup = {"country": country, "report": None, "gap": None, "competitors": [], "band": {}}
        try:
            async for ev in scout_stream(company, market, country, headcount):
                # capture pieces for the final compare summary
                if ev["type"] == "report":
                    rollup["report"] = ev["data"]
                elif ev["type"] == "gap_analysis":
                    rollup["gap"] = ev["data"]
                elif ev["type"] == "competitors_found":
                    rollup["competitors"] = ev["data"].get("competitors", [])
                elif ev["type"] == "band_agent":
                    rollup["band"][ev["agent"]] = ev["data"]
                await queue.put({"type": "country_event", "country": country, "inner": ev})
        except Exception as exc:
            await queue.put({"type": "country_event", "country": country,
                             "inner": {"type": "error", "message": str(exc)}})
        finally:
            results[country] = rollup
            await queue.put(("country_done", country))

    workers = [asyncio.create_task(worker(c)) for c in countries]
    pending = len(countries)

    while pending > 0:
        item = await queue.get()
        if isinstance(item, tuple) and item[0] == "country_done":
            pending -= 1
            continue
        yield item

    await asyncio.gather(*workers, return_exceptions=True)

    # build the comparison summary
    summary = []
    for c in countries:
        r = results.get(c, {})
        report = r.get("report") or {}
        gap    = r.get("gap") or {}
        fin    = (r.get("band") or {}).get("finance") or {}
        comp   = (r.get("band") or {}).get("compliance") or {}
        site   = (r.get("band") or {}).get("site_selection") or {}
        executive = (r.get("band") or {}).get("executive") or {}
        fyc    = (fin.get("first_year_cost") or {})
        summary.append({
            "country": c,
            "probability": report.get("probability", 0),
            "confidence":  report.get("confidence", "low"),
            "verdict":     report.get("verdict", ""),
            "city":        (site.get("recommended_location") or {}).get("city", ""),
            "year1_cost":  fyc.get("estimated_first_year_cost", 0),
            "rent_psf":    fyc.get("rent_psf_yr", 0),
            "salary":      fyc.get("avg_salary_yr", 0),
            "reg_risk":    comp.get("regulatory_risk", "unknown"),
            "decision":    executive.get("decision", ""),
            "gap_title":   gap.get("gap_title", ""),
            "gap_conf":    gap.get("confidence", "medium"),
            "n_competitors": len(r.get("competitors") or []),
        })

    # rank
    ranked = sorted(summary, key=lambda x: (
        -x["probability"],
        {"high": 0, "medium": 1, "low": 2, "unknown": 3}.get(x["reg_risk"], 3),
        x["year1_cost"] or 9e15,
    ))
    if ranked:
        ranked[0]["recommended"] = True

    yield {"type": "compare_done", "summary": ranked}