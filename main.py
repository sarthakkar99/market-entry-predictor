import json, asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models    import AnalyzeRequest
from agents    import run_all_agents
from synthesis import synthesize
from config    import AGENTS, MOCK_MODE
from workflows.market_expansion_workflow import run_market_expansion_workflow
from workflows.scout_workflow import scout_stream
from workflows.compare_workflow import compare_stream
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

def _page(filename):
    with open(filename, encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), headers={"Cache-Control":"no-store"})

@app.get("/", response_class=HTMLResponse)
async def index(): return _page("pages/index.html")

@app.get("/analyze", response_class=HTMLResponse)
async def analyze_page(): return _page("pages/analyze.html")

@app.get("/scout", response_class=HTMLResponse)
async def scout_page(): return _page("pages/scout.html")

@app.get("/compare", response_class=HTMLResponse)
async def compare_page(): return _page("pages/compare.html")

@app.get("/company/{name}", response_class=HTMLResponse)
async def company_page(name: str): return _page("pages/company.html")

@app.get("/report", response_class=HTMLResponse)
async def report_page(): return _page("pages/report.html")

@app.get("/health")
async def health():
    return {"status":"ok","mock_mode":MOCK_MODE}

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    return StreamingResponse(
        _stream(req.companies, req.target_market, req.country),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},
    )

@app.post("/api/marketops")
async def marketops(req: AnalyzeRequest):
    return StreamingResponse(
        _marketops_stream(
            req.companies,
            req.target_market,
            req.country,
            req.headcount
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.post("/api/scout")
async def scout(req: AnalyzeRequest):
    company = (req.companies[0] if req.companies else "").strip()
    return StreamingResponse(
        _scout_wrap(company, req.target_market, req.country, req.headcount or 10),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def _scout_wrap(company, market, country, headcount):
    try:
        async for ev in scout_stream(company, market, country, headcount):
            yield _e(ev)
    except Exception as exc:
        yield _e({"type": "error", "message": str(exc)})


from pydantic import BaseModel, Field
class CompareRequest(BaseModel):
    company:   str
    market:    str
    countries: list[str] = Field(..., min_length=1, max_length=3)
    headcount: int = 10


@app.post("/api/compare")
async def compare(req: CompareRequest):
    return StreamingResponse(
        _compare_wrap(req.company.strip(), req.market.strip(),
                      [c.strip() for c in req.countries if c.strip()], req.headcount or 10),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def _compare_wrap(company, market, countries, headcount):
    try:
        async for ev in compare_stream(company, market, countries, headcount):
            yield _e(ev)
    except Exception as exc:
        yield _e({"type": "error", "message": str(exc)})

async def _marketops_stream(companies, market, country, headcount):
    try:
        yield _e({
            "type": "workflow_start",
            "companies": companies,
            "market": market,
            "country": country,
            "headcount": headcount
        })

        # Run every company's full workflow CONCURRENTLY and emit each the
        # moment it finishes, instead of one-after-another.
        tasks = [
            asyncio.create_task(run_market_expansion_workflow(
                company=c, market=market, country=country, headcount=headcount
            ))
            for c in companies
        ]

        for fut in asyncio.as_completed(tasks):
            result = await fut
            case = result["case"]
            company = case["company"]

            for msg in case["messages"]:
                yield _e({"type": "agent_message", "company": company, "data": msg})

            yield _e({
                "type": "marketops_complete",
                "company": company,
                "data": {
                    "case_id": case["case_id"],
                    "research": result["research"],
                    "site_selection": result["site_selection"],
                    "incentives": result["incentives"],
                    "finance": result["finance"],
                    "compliance": result["compliance"],
                    "red_team": result["red_team"],
                    "human_approval": result["human_approval"],
                    "executive_decision": result["executive_decision"],
                    "tasks": result["tasks"],
                    "messages": case["messages"]
                }
            })

        yield _e({"type": "workflow_complete"})

    except Exception as exc:
        yield _e({"type": "error", "message": str(exc)})

async def _stream(companies: list[str], market: str, country: str):
    from agents import run_agents_streaming, run_competitor_analysis
    try:
        yield _e({"type":"start","companies":companies,"market":market,"country":country})

        queue: asyncio.Queue = asyncio.Queue()
        DONE = object()
        reports = {}  # company -> report

        async def company_worker(company):
            agent_results = []
            # emit each agent the instant it finishes
            async for r in run_agents_streaming(company, market, country):
                agent_results.append(r)
                pct = round((r.score/r.max_score)*100) if r.max_score else 0
                strength = "strong" if pct>=70 else "moderate" if pct>=40 else "weak"
                await queue.put(_e({
                    "type":"agent_complete","company":company,"agent_id":r.agent_id,
                    "data":{"score":r.score,"max_score":r.max_score,"results_found":len(r.findings),
                            "strength":strength,"evidence":r.findings,"sources":r.sources}
                }))
            report = await synthesize(company, market, country, agent_results)
            reports[company] = report
            await queue.put(_e({
                "type":"company_complete","company":company,
                "data":{"probability":report.probability,"confidence":report.confidence,"timeline":report.timeline,
                        "verdict":report.verdict,"key_findings":report.key_findings,
                        "strategic_implication":report.strategic_implication,"recommended_actions":report.recommended_actions}
            }))

        async def orchestrator():
            comp_results = {}
            async def comp_worker(company):
                # run competitor analysis CONCURRENTLY with agents (no trailing wave).
                # is_loser=True so a winning_strategy is always produced; we blank it
                # out for the eventual winner at emit time. Winner unknown yet here.
                try:
                    comp_results[company] = await run_competitor_analysis(company, market, country, is_loser=True)
                except Exception:
                    comp_results[company] = None

            # companies, their agents, AND competitor analysis all run at once
            await asyncio.gather(
                *[company_worker(c) for c in companies],
                *[comp_worker(c) for c in companies],
            )

            winner = max(reports.items(), key=lambda kv: kv[1].probability)[0] if reports else None
            for company in companies:
                data = comp_results.get(company)
                if not data:
                    continue
                is_loser = company != winner
                await queue.put(_e({
                    "type":"competitor_analysis","company":company,"is_loser":is_loser,
                    "data":{"competitors":data.get("competitors",[]),
                            "winning_strategy":data.get("winning_strategy","") if is_loser else ""}
                }))
            await queue.put(DONE)

        orch = asyncio.create_task(orchestrator())
        while True:
            item = await queue.get()
            if item is DONE:
                break
            yield item
        await orch
        yield _e({"type":"complete"})

    except Exception as exc:
        yield _e({"type":"error","message":str(exc)})

def _e(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)