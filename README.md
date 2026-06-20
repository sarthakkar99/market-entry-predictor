# Market Entry Predictor

> A multi-agent system that scouts a market, finds the competitive gap, and produces a board-ready entry plan — entirely from live web data via Bright Data SERP scrapes.

Built for the **Band of Agents hackathon**, extending an earlier Bright Data hackathon project.

**You give it:** one company, one industry, 1–3 target countries.
**It gives you:** local competitor map, market-gap analysis, recommended HQ city, year-1 cost from live rent + salary scrapes, regulatory risks named by their actual regulator, an executive briefing with go/no-go, and a downloadable PDF.

All in roughly 30 seconds, streamed live.

---

## Demo flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  Company  ─┐                                                            │
│  Industry  ├──► 9-agent pipeline ──► Executive Briefing + PDF           │
│  Country/s ─┘                                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| Step | Agent | Data source |
|---|---|---|
| 1 | 5 scout agents (jobs, domains, exec hires, partnerships, patents) | Bright Data SERP |
| 2 | Synthesis → Entry-readiness score | LLM (over scrape) |
| 3 | Competitor discovery — every name grounded in scraped snippets | Bright Data SERP |
| 4 | Gap analysis — underserved segments + pain points | Bright Data SERP |
| 5 | Site selection — talent / tech / foreign-company signals per candidate city | Bright Data SERP |
| 6 | Government incentives — extracted from program announcements | Bright Data SERP |
| 7 | Finance — year-1 cost from live $/sqft rent + city salary | Bright Data SERP |
| 8 | Compliance — concerns + named regulators | Bright Data SERP |
| 9 | Red team → Human approval → Executive decision → Tasks | Synthesis |

Multi-country mode (`/compare`) runs the whole pipeline in parallel for 2–3 countries and ranks them head-to-head.

---

## Why this design

**The rule:** Bright Data data is authoritative. The LLM is constrained to extract structured facts from the scraped snippets only — it cannot invent numbers, regulators, competitor names, or cities.

For each agent that touches the real world:
1. **Scrape** — one or more Bright Data SERP queries (in parallel where possible)
2. **Build evidence block** — `[1] title / snippet / source URL` per result
3. **Ask LLM** — extract structured JSON, citing snippet indices
4. **Post-process / hard-ground** — drop any output that doesn't appear in the snippets
5. **Surface provenance** — every output has a `data_sources` block; UI shows LIVE · Bright Data vs FALLBACK badges and clickable `[1]`, `[2]` citation chips

If a scrape fails:
- LLM-only fallback for low-stakes agents
- Hardcoded safety net for compliance (never blank)
- The `basis` field always says which path was used — the UI never lies about provenance

Synthesis agents (red team, executive, task assignment) do not scrape. Their inputs are the outputs of the scrape-grounded agents.

---

## Quick start

### Prerequisites
- Python 3.11+
- A Bright Data SERP zone (`brd_json=1` supported)
- An OpenAI API key

### 1. Install

```bash
git clone <your-repo-url>
cd Band_hackathon
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

Create `.env` in the project root:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

BRIGHTDATA_API_KEY=...
BRIGHTDATA_ZONE=serp_api1

# Tunables
SERP_RESULTS=5
MOCK_MODE=false
```

For a no-API offline demo set `MOCK_MODE=true` — the scraper returns canned snippets and the pipeline still runs end-to-end.

### 3. Run

```bash
uvicorn main:app --reload
```

Open <http://localhost:8000>.

Fill the form: **company** + **industry** + pick **1–3 countries**.
- 1 country → live single-country dashboard
- 2–3 countries → parallel side-by-side comparison

---

## Project structure

```
Band_hackathon/
├── main.py                          # FastAPI app · all routes · SSE wrappers
├── agents.py                        # 5 scout agents (concurrent)
├── scraper.py                       # Bright Data SERP client (pooled, cached)
├── synthesis.py                     # 5-agent → entry-readiness report
├── config.py                        # env vars + agent definitions
├── models.py                        # Pydantic schemas
│
├── workflows/
│   ├── scout_workflow.py            # single-country pipeline (streams ~50 events)
│   ├── compare_workflow.py          # multi-country parallel orchestrator
│   └── market_expansion_workflow.py # legacy 9-agent flow (kept for /analyze)
│
├── enterprise_agents/
│   ├── competitor_agent.py          # scrape + hard-grounded LLM extraction
│   ├── site_selection_agent.py      # LLM candidates → scrape signals → score
│   ├── incentives_agent.py          # scrape gov programs + LLM extract
│   ├── finance_agent.py             # scrape rent + salary → real cost model
│   ├── compliance_agent.py          # scrape regs + name regulators
│   ├── red_team_agent.py            # synthesis: stress-test other agents
│   ├── human_approval_agent.py      # decision routing
│   ├── executive_agent.py           # final go/no-go synthesis
│   └── task_assignment_agent.py     # team-level task decomposition
│
├── band_layer/                      # lightweight in-memory pub-sub
│   ├── band_client.py
│   ├── context_store.py
│   └── message_bus.py
│
├── pages/
│   ├── index.html                   # landing — country picker
│   ├── scout.html                   # single-country dashboard
│   └── compare.html                 # multi-country head-to-head
│
├── requirements.txt
├── .env.example
├── CODE_WALKTHROUGH.md              # detailed code documentation
└── README.md
```

Total: ~2,700 lines of Python + HTML/CSS/JS.

---

## Three things judges should look for

**1. Click any competitor card → it opens a real news/industry URL.**
Citation chips `[1]`, `[2]` next to each competitor and each finding link to the exact Bright Data SERP result that named them. No fabricated competitors — the post-processor drops any LLM output not literally in the scrape.

**2. Open the Finance agent modal — every number is sourced.**
"Total Year-1: $1.78M (Tokyo)" → click `LIVE · Bright Data` badge → see the office-rent and salary source URLs that fed the calculation. Run again for London ($1.61M) and see a different set of URLs. Two cities, two real prices, derived from live scrapes.

**3. The 8 Band cards stream their reasoning as they work.**
Site Selection card shows `▸ Pulling office-market data for Bangalore…` → `▸ Scoring talent pool, infra, cost-of-living…` → `▸ Comparing top 3 candidate cities…` before resolving. Not a progress bar — a streamed internal monologue per agent.

---

## Architecture notes

- **Streaming, not polling.** All pipelines yield Server-Sent Events. The frontend dispatches on `ev.type` to update specific UI elements. Users see agents tick to DONE as they finish.
- **Selective concurrency.** The 5 scout agents and the competitor agent run in parallel (Bright Data hammered concurrently). The 8 Band agents run sequentially because each consumes the previous one's output.
- **Multi-country parallelism.** `/api/compare` runs N independent `scout_stream` generators concurrently inside an `asyncio.Queue`. 3 countries take the same wall-clock as 1.
- **In-flight SERP dedupe.** Multiple agents asking the same query share one future via `_serp_cache`. Same competitor query from 3 companies → 1 actual Bright Data call.
- **Connection pooling.** One shared `httpx.AsyncClient` with `max_connections=20`. Avoids the 200-500ms TLS handshake cost per call.

See [CODE_WALKTHROUGH.md](./CODE_WALKTHROUGH.md) for line-by-line.

---

## Acknowledgements

- [Bright Data](https://brightdata.com) for the SERP API
- [Anthropic / OpenAI](https://openai.com) for the LLM
- The **Band of Agents** hackathon by [lablab.ai](https://lablab.ai)
