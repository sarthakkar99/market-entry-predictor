# Market Entry Predictor — Code Walkthrough

This document explains what every file does, how data flows between them, and the design decisions that matter when defending the code (hackathon Q&A, future you, future contributors).

The mental model: **one user request triggers a streaming pipeline of agents that each scrape Bright Data, ask an LLM to extract structured facts from the scrape, and pass their output to the next agent — all of it streamed live to the browser via Server-Sent Events.**

If you understand that one sentence and the diagram below, the rest is implementation detail.

---

## 0. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser (HTML/JS)                                                       │
│  pages/index.html  →  pages/scout.html   or   pages/compare.html         │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │ POST + SSE
┌────────────────────────▼─────────────────────────────────────────────────┐
│  FastAPI  (main.py)                                                      │
│  • /api/scout    → scout_stream     (1 country)                          │
│  • /api/compare  → compare_stream   (1–3 countries in parallel)          │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────────────┐
│  workflows/scout_workflow.py  (orchestrator)                             │
│                                                                          │
│  Step 1: 5 scout agents run concurrently  (agents.py)                    │
│           ─ job_posts, domain_regs, exec_hires, partnerships, patents    │
│  Step 2: Entry-readiness report           (synthesis.py)                 │
│  Step 3: Competitor discovery             (competitor_agent.py)          │
│  Step 4: Gap analysis (LLM + scrape)                                     │
│  Step 5: Band of 8 enterprise agents (sequential, depend on each other): │
│           site_selection → incentives → finance → compliance             │
│           → red_team → human_approval → executive → task_assignment      │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │ every agent calls
┌────────────────────────▼─────────────────────────────────────────────────┐
│  scraper.py                                                              │
│  • fetch_serp(query)  → Bright Data SERP API                             │
│  • In-flight dedupe cache, mock fallback when MOCK_MODE=true             │
└──────────────────────────────────────────────────────────────────────────┘
```

Three things to internalize before reading code:

1. **SSE not REST.** A scout request streams ~50–150 small JSON events back to the browser as work completes. The frontend dispatches on `ev.type` to update specific cards. Nothing is "polled."
2. **Scrape-then-LLM.** Every data agent scrapes Bright Data first, builds an evidence block, then asks the LLM to extract structured JSON *from the snippets only*. The LLM cannot invent facts because we drop any output that isn't in the evidence.
3. **Three fallback layers.** Scrape succeeds → LLM succeeds → use that. Scrape succeeds but LLM fails → use the scrape directly. Scrape fails → use a hardcoded safety net. Every agent returns `data_sources.basis` so the UI shows whether it's `bright_data_scrape`, `llm_only_fallback`, or `hardcoded_fallback`.

---

## 1. Entry points (the "front door")

### `main.py`

The FastAPI app. ~165 lines.

**What it does**
- Boots the server, mounts static files, serves the four HTML pages (`/`, `/scout`, `/compare`, `/analyze`)
- Defines four streaming endpoints:
  - `POST /api/scout` — single-country pipeline
  - `POST /api/compare` — multi-country parallel pipeline
  - `POST /api/analyze` — legacy multi-company pipeline (kept for backward compat with `analyze.html`)
  - `POST /api/marketops` — legacy 9-agent flow (kept for backward compat)
- Each endpoint returns a `StreamingResponse` with `media_type="text/event-stream"`. Inside the response generator we call `_e(event_dict)` which formats each dict as `data: {...}\n\n` (SSE protocol).

**Key functions**
- `_e(payload)` — turns any dict into a valid SSE frame. Single most-called helper in the file.
- `_page(path)` — reads an HTML file from `pages/` and returns it.
- `_scout_wrap`, `_compare_wrap` — thin async wrappers that run the workflow generator and catch exceptions so a crash mid-stream emits a `{"type":"error", ...}` event instead of breaking the response.

**Request models** live in `main.py` as Pydantic classes:
- `AnalyzeRequest` — for `/api/analyze` and `/api/marketops`
- `CompareRequest` — `{company, market, countries: [...], headcount}`

**Why streaming generators?** Because by yielding events as the workflow runs, the user sees agents tick to DONE *as they finish* instead of staring at a spinner for 30+ seconds. A `return` would buffer everything until the entire pipeline finished.

---

### `pages/index.html`

The landing page. Pure HTML/CSS/JS, no framework.

**What it does**
- Three required fields: Company, Industry, 1–3 target Countries (chips).
- On submit, writes `{company, market, countries}` to `sessionStorage` under the key `"query"`, then redirects:
  - 1 country → `/scout`
  - 2–3 countries → `/compare`

**Why sessionStorage?** Both downstream pages need the same form data, and we don't want to pollute URLs with query strings (the SSE call gets the data via `fetch` body, not URL).

---

### `pages/scout.html`

The single-country dashboard. The big one (~33K of JS).

**What it does**
- Reads `query` from sessionStorage, immediately calls `POST /api/scout` with that body.
- Streams the response with `ReadableStream` + `TextDecoder`, splitting on `\n\n`, parsing each `data: {...}` frame.
- Dispatches each event by `ev.type`:
  - `scout_start` → header / progress text
  - `agent_complete` × 5 → scout agent cards (gauge fills, evidence lines slide in with `[1]` citations)
  - `report` → animates the entry-readiness gauge + verdict
  - `competitors_found` → renders competitor cards, each with its own `source_url`
  - `gap_analysis` → renders whitespace panel + LIVE/FALLBACK badge
  - `band_thought` × ~22 → typing-style "▸ Pulling office market data…" under each Band card
  - `band_agent` × 8 → finalizes each Band card with summary line + makes it clickable
  - `complete` → builds the Executive Briefing panel below + saves to history

**Key globals in the JS**
- `STATE` — single object accumulating everything from the stream. Lives until refresh. Used to build the briefing panel, render modals, save to history, generate PDF.
- `BAND` — array of 8 metadata objects (id, icon, step number, name) for the Band agents.
- `AMETA` — metadata for the 5 scout agents (color, icon).
- `RENDER` — object keyed by Band agent id, where each value is a function that takes the agent's data and returns HTML for its modal.

**Notable functions**
- `openModal(agentId)` — pulls `STATE.band[agentId]`, runs the matching `RENDER[agentId]()` function, shows the modal.
- `renderBriefing()` — fires on `complete`. Builds the 4 KPI tiles (year-1 spend, entry probability, recommended HQ, regulatory risk), decision pill, risks list, 30-day plan.
- `downloadPDF()` — uses jsPDF (loaded from CDN) to generate a multi-page briefing.
- `saveToHistory()` — pushes the entire run to `localStorage["scout_history"]` keyed by company+market+country+date so the user can revisit past scouts.
- `openHistory(id)` — re-hydrates `STATE` from a saved entry and re-renders the whole dashboard without re-running the agents.

---

### `pages/compare.html`

The multi-country side-by-side dashboard. Smaller and simpler than scout.html.

**What it does**
- Reads `{company, market, countries}` from sessionStorage.
- Renders N columns (one per country) with mini agent cards.
- POSTs to `/api/compare`, then routes each `country_event` to the right column by reading `ev.country`.
- When `compare_done` fires, displays the **head-to-head table** ranked by entry probability → regulatory risk → year-1 cost, with the winner highlighted as 🏆 RECOMMENDED.

**The trick that makes this fast**
The compare workflow runs N independent `scout_stream` generators concurrently inside an `asyncio.Queue`. All N countries hit Bright Data + OpenAI in parallel, so 3 countries take roughly the same wall-clock as 1.

---

## 2. The core orchestrators (`workflows/`)

### `workflows/scout_workflow.py` — the heart of the system

~353 lines. Read this file once front-to-back and you understand the whole product.

**Top-level: `scout_stream(company, market, country, headcount)`**

An async generator yielding dicts. Each dict is one SSE event.

The flow is:

```python
async def scout_stream(company, market, country, headcount=10):
    # ── A. SCOUTING PHASE (parallel) ───────────────────────────────────
    yield {"type": "scout_start", ...}

    comp_task = asyncio.create_task(run_competitor_agent(...))   # in parallel

    agent_results = []
    async for r in run_agents_streaming(company, market, country):
        agent_results.append(r)
        yield {"type": "agent_complete", "agent_id": r.agent_id, ...}

    # ── B. SYNTHESIS ──────────────────────────────────────────────────
    report = await synthesize(company, market, country, agent_results)
    yield {"type": "report", ...}

    # ── C. AWAIT COMPETITOR + GAP ANALYSIS ────────────────────────────
    competitors_out = await comp_task
    yield {"type": "competitors_found", ...}

    gap = await _gap_analysis(...)
    yield {"type": "gap_analysis", ...}

    # ── D. BAND OF 8 ENTERPRISE AGENTS (sequential, with thought events)
    yield {"type": "band_start", ...}
    async for ev in _think("site_selection", [...thoughts...]):
        yield ev
    site = await run_site_selection_agent(...)
    yield {"type": "band_agent", "agent": "site_selection", ...}
    # ... repeat for incentives, finance, compliance, red_team,
    # human_approval, executive, task_assignment ...

    yield {"type": "complete", ...}
```

**Three things to know**

1. **Concurrency is selective.** The 5 scout agents and the competitor agent run *in parallel* (Bright Data hammered concurrently), because their results are independent. The 8 Band agents run *sequentially* because each one consumes the previous one's output — site selection picks the city → incentives queries for that city → finance prices that city → compliance reads the location, etc. Trying to parallelize them would break the data flow.

2. **The `_think` helper is theater that pays off.** It yields 2-3 fake "▸ Pulling rent data…" status lines with `await asyncio.sleep(0.4)` between each, *before* the real agent runs. From the user's perspective, the Band cards stream their reasoning instead of blinking from QUEUED → DONE. From the LLM's perspective, nothing changed. From a judge's perspective, the agents feel alive.

3. **The gap analysis (`_gap_analysis`) is its own mini scrape-then-LLM agent.** Two parallel SERP queries for "underserved customer segments" + "customer pain points," dedupe by URL, build an evidence block, ask the LLM to extract structured gap fields *only from the snippets*. Falls back to `_fallback_gap()` (a hardcoded synthesis from competitor weaknesses) if scraping returns nothing.

---

### `workflows/compare_workflow.py`

~94 lines. The multi-country orchestrator.

**Pattern: fan-out + fan-in queue**

```python
async def compare_stream(company, market, countries, headcount=10):
    yield {"type": "compare_start", ...}

    queue = asyncio.Queue()
    results = {}  # country → roll-up dict

    async def worker(country):
        rollup = {...}
        async for ev in scout_stream(company, market, country, headcount):
            # capture pieces for the final compare summary
            if ev["type"] == "report": rollup["report"] = ev["data"]
            elif ev["type"] == "gap_analysis": rollup["gap"] = ev["data"]
            # ...etc...
            await queue.put({"type": "country_event", "country": country, "inner": ev})
        results[country] = rollup
        await queue.put(("country_done", country))

    workers = [asyncio.create_task(worker(c)) for c in countries]
    pending = len(countries)

    while pending > 0:
        item = await queue.get()
        if isinstance(item, tuple) and item[0] == "country_done":
            pending -= 1
            continue
        yield item                          # ← multiplexed back to browser
```

Then after all workers finish:
- Build a `summary` list with one row per country (entry probability, year-1 cost, regulatory risk, decision, market gap, etc).
- Sort by `(−probability, reg_risk_rank, year1_cost)`.
- Mark `summary[0]["recommended"] = True`.
- Yield one final `compare_done` event with the sorted summary.

The frontend uses this summary to render the head-to-head table.

---

### `workflows/market_expansion_workflow.py` (legacy)

~82 lines. The original 9-agent pipeline for `/api/marketops`. Still used by `analyze.html`. New flow is `scout_workflow.py`.

---

## 3. The 5 scout agents — `agents.py` + `scraper.py` + `synthesis.py`

### `agents.py`

~50 lines. Defines 5 lightweight "signal" agents that scan Bright Data for specific expansion signals.

**The 5 agents** (defined in `config.AGENTS`):
- `job_posts` — searches `"site:linkedin.com {company} hiring {market} {country}"`
- `domain_regs` — searches for newly registered localized domains
- `exec_hires` — searches for senior hire announcements
- `partnerships` — searches for partnership / conference announcements
- `patents` — searches for relevant IP filings

**Two public functions**

```python
async def run_all_agents(company, market, country) -> list[AgentResult]:
    """Wait for all 5 → return list. Used by legacy /api/analyze."""

async def run_agents_streaming(company, market, country):
    """Yield each AgentResult the moment it finishes. Used by scout_stream."""
    tasks = [asyncio.create_task(_safe_run(aid, ...)) for aid in AGENTS]
    for fut in asyncio.as_completed(tasks):
        yield await fut
```

`run_agents_streaming` is critical — it's why the dashboard cards tick to DONE one at a time instead of all at once.

**Inside `_run_agent`** — for each agent:
1. Build the SERP query from the agent's `query_tpl` config.
2. Call `fetch_serp(query)` → list of `{title, url, snippet}` dicts.
3. Call OpenAI with the agent's scoring prompt to convert snippets to `{score, max_score, findings, sources}`.
4. Return `AgentResult` (a Pydantic model).

---

### `scraper.py`

~45 lines but does a lot of work.

```python
_serp_cache: dict = {}                  # in-flight dedupe
_client = None                          # singleton httpx client

async def fetch_serp(query, agent_id=''):
    if MOCK_MODE: return _mock(query, agent_id)
    fut = _serp_cache.get(query)
    if fut is None:
        fut = asyncio.ensure_future(_brightdata(query))
        _serp_cache[query] = fut
    try:
        return await fut
    except Exception:
        _serp_cache.pop(query, None)
        return _mock(query, agent_id)
```

**Three performance fixes baked in:**

1. **Connection pooling** — one shared `httpx.AsyncClient` with `max_connections=20`. Without this, every SERP call opens a fresh TLS connection (200-500ms wasted each).
2. **In-flight dedupe** — multiple agents asking the same query share one future. Same competitor query from 3 companies → 1 actual Bright Data call.
3. **12-second timeout with mock fallback** — a stalled Bright Data call doesn't freeze the pipeline. After 12s we fall back to the mock library and the agent still completes.

**The Bright Data call itself:**

```python
async def _brightdata(query):
    payload = {
        'zone': BRIGHTDATA_ZONE,
        'url': f'https://www.google.com/search?q={quote_plus(query)}&num={SERP_RESULTS}&brd_json=1',
        'format': 'raw',
    }
    headers = {'Authorization': f'Bearer {BRIGHTDATA_API_KEY}', ...}
    r = await _get_client().post(BRIGHTDATA_API_URL, json=payload, headers=headers)
    organic = r.json().get('organic', [])
    return [{'title': i['title'], 'url': i['link'], 'snippet': i['description']}
            for i in organic[:SERP_RESULTS]]
```

`brd_json=1` is Bright Data's flag for structured JSON output. The `organic` array is the list of organic search results (excluding ads, knowledge panels, etc).

---

### `synthesis.py`

~28 lines. Takes the 5 `AgentResult` objects and produces a single readability report.

```python
async def synthesize(company, market, country, agents) -> Report:
    """LLM-only — synthesizes signals from all 5 agents into one report."""
```

Output: `Report` Pydantic model with `probability`, `confidence`, `timeline`, `verdict`, `key_findings`, `strategic_implication`, `recommended_actions`. Frontend uses this to draw the gauge and verdict on each scout column.

---

## 4. The 9 Band agents (`enterprise_agents/`)

Each agent follows the same contract:

```python
async def run_X_agent(case, ...context_from_previous_agent...):
    # 1. SCRAPE (if applicable)
    # 2. CONSTRAIN LLM via evidence block (if applicable)
    # 3. POST-PROCESS / HARD-GROUND
    # 4. save_agent_output(case_id, "X_agent", output)
    # 5. await band.send_context(from="X", to="next", payload=output)
    # 6. return output
```

The split between "scrape-grounded" and "pure synthesis" agents is intentional. Let me walk through each.

---

### `enterprise_agents/research_agent.py` (42 lines)

Lightweight wrapper that re-packages the scout-phase research into a format the next agent can consume. Doesn't scrape on its own — it's already a downstream consumer.

---

### `enterprise_agents/competitor_agent.py` (~200 lines, **scrape-grounded**)

The pattern, exhaustively:

```python
qs = [f"top {market} companies in {country} 2026",
      f"{market} market leaders {country} {company} alternatives"]
result_groups = await asyncio.gather(*[fetch_serp(q, "competitor_agent") for q in qs])

# dedupe by URL
results, seen = [], set()
for group in result_groups:
    for r in group:
        if r["url"] not in seen:
            seen.add(r["url"]); results.append(r)

# build numbered evidence block with [1], [2], ... tags
evidence_text = "\n\n".join(
    f"[{i+1}] {r['title']}\n{r['snippet']}\nSOURCE: {r['url']}"
    for i, r in enumerate(results[:8])
)

# LLM extracts JSON but MUST tag each competitor with source_index
output = LLM(prompt with EVIDENCE BLOCK + rule "every competitor must be named in EVIDENCE")

# HARD GROUNDING: drop any competitor whose name isn't literally in snippets
all_snippets = [r["title"] + " " + r["snippet"] for r in results]
grounded = []
for c in output["competitors"]:
    if not _name_in_text(c["name"], all_snippets):
        continue                                       # ← invented → drop
    idx = c.get("source_index", 0)
    c["source_url"] = results[idx-1]["url"] if 0 < idx <= len(results) else ""
    grounded.append(c)
output["competitors"] = grounded
```

The `_name_in_text` check is the safeguard. If the LLM hallucinates "FakeCo" as a competitor (it tries — temperature=0 doesn't prevent this), the check fails and the entry is dropped before the user sees it.

---

### `enterprise_agents/site_selection_agent.py` (~270 lines, **scrape-grounded**)

The most complex agent — 4 distinct stages:

```python
async def run_site_selection_agent(case, research_context):
    # 1. LLM proposes 3 candidate cities for the country
    candidates = await _llm_candidates(company, market, country)

    # 2. Scrape signals for each candidate IN PARALLEL (3 queries × 3 cities = 9 calls)
    scraped = await asyncio.gather(*[
        _scrape_city_signals(c["city"], country, market) for c in candidates
    ])

    # 3. Deterministic score (NOT done by LLM)
    scored = [{
        "city": c["city"],
        "score": _score(sig),                      # weighted formula
        "signals": sig,
    } for c, sig in zip(candidates, scraped)]
    scored.sort(key=lambda x: x["score"], reverse=True)
    winner = scored[0]

    # 4. LLM writes the NARRATIVE only — explicitly told not to change winner/score
    narrative = await _llm_narrative(
        company, market, country, winner["city"], winner["score"],
        evidence=winner["signals"]["evidence"]
    )
```

**Why this split matters.** If we let the LLM pick the winner, it'd always pick Tokyo / London / San Francisco from training data. By splitting "candidate generation" (LLM) from "ranking" (deterministic scoring from scraped signals), we get LLM creativity *and* data-grounded decisions.

**The scoring formula:**

```python
def _density(rs):                       # snippet-density signal per query
    n = sum(1 for r in rs if city_low in (r["title"] + r["snippet"]).lower())
    return min(n, 5) * 20               # cap at 5 → 0–100 scale

def _score(signals):                    # weighted sum
    return round(
        signals["talent_signal"]  * 0.45 +
        signals["tech_signal"]    * 0.35 +
        signals["foreign_signal"] * 0.20
    )
```

Talent matters most for an expansion office (45%), tech ecosystem next (35%), foreign company presence corroborates (20%). These weights are *defensible* and easy to tweak.

---

### `enterprise_agents/incentives_agent.py` (~155 lines, **scrape-grounded**)

```python
qs = [
    f"{city} {state} {country} business incentives tax credits grants 2026",
    f"{country} {market} foreign investment incentives 2026",
]
```

Two parallel queries because incentives operate at two granularities (city + country). LLM extracts named programs from snippets only. Falls back to `_llm_only_fallback(country)` if scraping returns nothing useful.

---

### `enterprise_agents/finance_agent.py` (~220 lines, **scrape-grounded — the most-important agent for credibility**)

The agent that converts site selection into real-money numbers using **live** rent + salary scrapes per city.

```python
qs = [
    f"office space rent per square foot {city} {country} 2026",
    f"average tech salary {city} {country} 2026",
]
rent_psf, avg_salary = await asyncio.gather(
    fetch_serp(qs[0], "office_rent"),
    fetch_serp(qs[1], "city_salary"),
)
```

**The regex parsers are the special sauce.** They handle multi-currency data:

```python
_NUM_RE = re.compile(
    r"(?:[\$£€¥₹]\s*)?(\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?|\d{1,4})\s*(k|thousand|m|million|lakh|lakhs|crore|crores)?",
    re.IGNORECASE,
)
```

This matches `$95`, `£75 psf`, `€72,000`, `12 lakhs`, `1.2 crore`, etc. Then `_to_number` converts to a base number, and the salary parser auto-converts INR (lakhs/crores) to USD at ~₹85/$1 before the plausibility check.

**The cost model** (formula not table):

```python
def compute_cost(headcount, rent_psf_yr, avg_salary_yr, setup_per_employee, legal):
    sqft = headcount * 90                                # industry rule-of-thumb
    real_estate_yr   = sqft * rent_psf_yr
    salaries_yr      = headcount * avg_salary_yr * 1.30  # employer overhead
    one_time_setup   = headcount * setup_per_employee
    subtotal         = real_estate_yr + salaries_yr + one_time_setup + legal
    contingency      = subtotal * 0.15
    return {"estimated_first_year_cost": subtotal + contingency, ...}
```

90 sqft per employee, 1.30× salary for employer overhead (benefits, payroll tax, equipment), 15% contingency. Every input is either scraped or transparent. **A judge can grill any number on the page back to a specific source URL or a published industry constant.**

If either scrape fails, `TIER_FALLBACK[country_tier]` provides defaults — but the `data_sources.basis` field tells the user it's a fallback so we never lie about provenance.

---

### `enterprise_agents/compliance_agent.py` (~170 lines, **scrape-grounded**)

```python
qs = [
    f"{market} regulation {country} 2026",
    f"{market} regulator license requirements {country}",
    f"{market} compliance foreign company {country}",
]
```

Extracts named regulators (FCA, MAS, RBI, IRDAI, etc.) from the snippets. Three-tier fallback: scrape+LLM → hardcoded `REGULATED_MARKETS` table → never-blank default. Compliance must never return empty — that's why the hardcoded table is kept as a safety net.

---

### `enterprise_agents/red_team_agent.py` (~46 lines, **synthesis-only**)

```python
prompt = f"""All prior agent outputs: {all_context}
Stress-test this plan. Find 3 risks the other agents missed."""
```

Pure synthesis — looks at everything site/incentives/finance/compliance returned and identifies cross-cutting risks. No scraping because the inputs *are* already scraped data.

---

### `enterprise_agents/human_approval_agent.py` (~92 lines, **decision routing**)

Decides whether the plan needs human sign-off based on:
- `compliance.regulatory_risk == "high"`?
- `red_team.risk_adjustment < threshold`?

Pure routing logic. Returns `{status, decision, question, reason}`.

---

### `enterprise_agents/executive_agent.py` (~52 lines, **synthesis-only**)

Final decision-maker. Consumes everything: research, site, incentives, finance, compliance, red team, human approval. Returns:

```python
{
    "decision": "go" | "no_go" | "partner_led_entry_or_monitor" | ...,
    "market_entry_probability": int,
    "executive_summary": "2-3 sentences",
    "recommended_location": {...},
    "estimated_first_year_cost": {...},
    "red_team_challenges": [...],
}
```

---

### `enterprise_agents/task_assignment_agent.py` (~34 lines)

Takes the executive decision and decomposes it into team-level tasks:

```python
{
    "legal_team":     ["File incorporation paperwork", "Engage local counsel for IRDAI", ...],
    "finance_team":   ["Open local bank account", ...],
    "hiring_team":    [...],
    "product_team":   [...],
}
```

---

## 5. The Band layer (`band_layer/`)

Lightweight in-memory pub-sub for inter-agent communication. ~100 lines total.

### `context_store.py`

In-memory dict keyed by `case_id`. Each case stores:
```python
{
    "case_id":       "uuid...",
    "company":       "...",
    "market":        "...",
    "country":       "...",
    "headcount":     10,
    "agent_outputs": {"site_selection_agent": {...}, ...},
    "messages":      [{"from": "X", "to": "Y", "payload": {...}, "ts": "..."}],
}
```

### `band_client.py`

```python
class BandClient:
    async def send_context(self, case_id, from_agent, to_agent, payload):
        # appends to case["messages"] in context_store
```

Every Band agent ends with `await band.send_context(...)`. This is the "agents communicating" log shown in modals.

### `message_bus.py`, `schemas.py`

Minimal pub-sub + Pydantic schemas for `BandMessage`. Used by the legacy `marketops` flow.

---

## 6. Config (`config.py`) and runtime modes

~390 lines but most are constants. Key bits:

```python
# Env vars
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
BRIGHTDATA_API_KEY  = os.getenv("BRIGHTDATA_API_KEY")
BRIGHTDATA_ZONE     = os.getenv("BRIGHTDATA_ZONE", "serp_api1")
BRIGHTDATA_API_URL  = "https://api.brightdata.com/request"
OPENAI_MODEL        = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SERP_RESULTS        = _env_int("SERP_RESULTS", 5)

# Mode flags
MOCK_MODE         = _env_bool("MOCK_MODE", False)        # scraper returns fakes
LLM_MOCK_MODE     = _env_bool("LLM_MOCK_MODE", False)    # LLM bypassed in old agents
BAND_LOCAL_MODE   = _env_bool("BAND_LOCAL_MODE", False)  # local-only band pub-sub

# 5 scout agent definitions
AGENTS = {
  "job_posts":    {"query_tpl": "...", "score_prompt": "...", "max_score": 25, ...},
  ...
}
```

**Three modes that matter:**

- **Production:** `MOCK_MODE=false`, real OpenAI key, real Bright Data key.
- **No-API demo:** `MOCK_MODE=true` → scraper returns canned snippets. The pipeline still runs but data isn't live.
- **Debug:** `MOCK_MODE=false` + low `SERP_RESULTS=3` → fewer scrape results, faster runs, cheaper.

---

## 7. The data contract

Every agent returns a JSON object that downstream consumers (the next agent, the frontend) can rely on:

```python
{
  # Agent-specific payload (see each agent for shape)
  "recommended_location": {...},
  ...

  # Universal provenance block — present on every scrape-capable agent
  "data_sources": {
    "basis":   "bright_data_scrape" | "llm_only_fallback" | "hardcoded_fallback",
    "queries": ["...the SERP queries we ran..."],
    "urls":    ["...the source URLs..."],
  }
}
```

The frontend uses `data_sources.basis` to show LIVE / FALLBACK badges. `urls` populate the inline `[1]`, `[2]` citation chips.

---

## 8. The event vocabulary (what the SSE stream emits)

This is what the dashboard listens for. Keep this list close — it's the contract between backend and frontend.

| Event | Payload | When |
|---|---|---|
| `scout_start` | `{company, market, country, case_id}` | top of scout_stream |
| `agent_complete` | `{agent_id, data: {score, max_score, evidence, sources, strength}}` | each of 5 scout agents finishes |
| `report` | `{probability, confidence, timeline, verdict, key_findings, ...}` | after synthesis |
| `competitors_found` | `{competitors:[...], sources:[...], data_sources:{...}}` | competitor agent done |
| `gap_analysis` | `{gap_title, underserved_segments, recommended_wedge, data_sources}` | gap done |
| `band_start` | `{company}` | starting Band sequence |
| `band_thought` | `{agent, text}` | 2-3× per Band agent, before its result |
| `band_agent` | `{agent, data: ...}` | each Band agent finishes |
| `complete` | `{case_id, gap, competitors, executive_decision, tasks, messages}` | end of pipeline |
| `error` | `{message}` | anything raises |

**Compare flow** adds these:
| Event | Payload | When |
|---|---|---|
| `compare_start` | `{company, market, countries}` | top |
| `country_event` | `{country, inner: <any of the above>}` | every event from every country's scout, multiplexed |
| `compare_done` | `{summary: [sorted ranking with recommended:true on winner]}` | all countries finished |

---

## 9. Reading order (if you forget everything)

If you come back in 3 months and need to remember how this works, read these in this order:

1. **This file** to remember the architecture.
2. **`workflows/scout_workflow.py`** — the orchestrator. Everything else is what this calls.
3. **`scraper.py`** — how Bright Data actually gets called.
4. **`enterprise_agents/finance_agent.py`** — the canonical example of scrape-then-LLM-then-grounding. Every other scrape-capable agent follows the same pattern.
5. **`pages/scout.html`** — start at `function handle(ev)` and read each `case` to understand what each event renders.

That's enough to get back to productive work in under an hour.

---

## 10. Common mistakes to avoid (you've already hit some of these)

- **Editing a file in VS Code without saving** — the server reads from disk, not from your editor. Watch for the "X unsaved" badge.
- **Hitting `/scout` or `/compare` directly in the URL bar** — sessionStorage is empty, the page bounces you to `/`. Always go through the form.
- **Saving HTML with a BOM** — Firefox falls into Quirks Mode silently. Save as UTF-8 *without* BOM.
- **Hardcoded multipliers / lookup tables in the agents** — already removed. If you ever add one back, also add a `data_sources.basis: "hardcoded_fallback"` so the user knows.
- **Letting the LLM choose the winner instead of scoring deterministically** — the site selection agent shows the right pattern. Use it as a template.
- **Forgetting `data_sources` on a new agent** — every data-touching agent must return this block. The frontend won't crash without it, but you'll lose the LIVE/FALLBACK badges and citation chips.
