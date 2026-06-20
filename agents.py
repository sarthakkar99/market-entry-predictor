import asyncio,json,re
from openai import AsyncOpenAI
from config import AGENTS, LLM_MOCK_MODE, MAX_TOKENS, OPENAI_API_KEY, OPENAI_MODEL
from scraper import fetch_serp
from models import AgentResult
_openai=AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
async def _safe_run(aid,company,market,country):
    try: return await _run_agent(aid,company,market,country)
    except Exception as e: return _fallback(aid,str(e))
async def run_agents_streaming(company:str, market:str, country:str):
    """Yield each AgentResult the moment it finishes (for live SSE streaming)."""
    tasks=[asyncio.create_task(_safe_run(aid,company,market,country)) for aid in AGENTS]
    for fut in asyncio.as_completed(tasks):
        yield await fut
async def run_all_agents(company:str, market:str, country:str)->list[AgentResult]:
    tasks=[_run_agent(aid,company,market,country) for aid in AGENTS]
    res=await asyncio.gather(*tasks, return_exceptions=True)
    return [_fallback(aid,str(r)) if isinstance(r,Exception) else r for aid,r in zip(AGENTS.keys(),res)]
async def _run_agent(agent_id,company,market,country):
    cfg=AGENTS[agent_id]; q=cfg['query_tpl'].format(company=company,market=market,country=country); serp=await fetch_serp(q,agent_id)
    if LLM_MOCK_MODE or _openai is None: return _mock_agent_result(agent_id,serp)
    text='\n\n'.join(f"{i+1}. {r['title']}\n{r['url']}\n{r['snippet']}" for i,r in enumerate(serp)) or 'No results.'
    prompt=f'''You are a competitive intelligence analyst. Analyze whether {company} is entering {market} in {country}. Focus on {cfg['signal']}. Results: {text}. Score 0-{cfg['max_score']}. Return ONLY JSON: {{"score":0,"findings":["..."],"reasoning":"...","sources":["..."]}}'''
    resp=await _openai.chat.completions.create(model=OPENAI_MODEL,max_tokens=MAX_TOKENS,temperature=0,messages=[{'role':'user','content':prompt}])
    data=_safe_json(resp.choices[0].message.content or '{}')
    return AgentResult(agent_id=agent_id,label=cfg['label'],emoji=cfg['emoji'],score=max(0,min(cfg['max_score'],int(data.get('score',0)))),max_score=cfg['max_score'],findings=data.get('findings') or ['No strong findings.'],reasoning=data.get('reasoning',''),sources=data.get('sources') or [r['url'] for r in serp[:2]])
def _safe_json(raw):
    try: return json.loads(raw.strip())
    except Exception:
        m=re.search(r'\{.*\}',raw,re.DOTALL)
        try: return json.loads(m.group()) if m else {}
        except Exception: return {}
def _fallback(agent_id,error):
    cfg=AGENTS[agent_id]
    return AgentResult(agent_id=agent_id,label=cfg['label'],emoji=cfg['emoji'],score=0,max_score=cfg['max_score'],findings=[f'Agent error: {error}'],reasoning='',sources=[])
def _mock_agent_result(agent_id,serp):
    cfg=AGENTS[agent_id]; scores={'job_posts':18,'domain_regs':15,'exec_hires':13,'partnerships':11,'patents':7}; score=min(cfg['max_score'],scores.get(agent_id,cfg['max_score']//2))
    return AgentResult(agent_id=agent_id,label=cfg['label'],emoji=cfg['emoji'],score=score,max_score=cfg['max_score'],findings=[f'Demo evidence suggests {cfg["signal"]}.','Signal should be validated with live sources.','Fallback mode keeps the demo stable.'],reasoning='Fallback analysis used because live LLM/search is not configured.',sources=[r['url'] for r in serp[:2]])
async def run_competitor_analysis(company:str, market:str, country:str, is_loser:bool=False)->dict:
    serp=await fetch_serp(f'top {market} companies in {country} market leaders competitors','local_competitors')
    if LLM_MOCK_MODE or _openai is None:
        return {'competitors':[{'name':'Local Leader A','strengths':['brand trust','distribution'],'weaknesses':['legacy UX','slow integrations']},{'name':'Local Leader B','strengths':['regulatory relationships','partnerships'],'weaknesses':['limited product depth']}],'competitive_threat':'high' if is_loser else 'medium','winning_strategy':'Use a partner-led pilot, target underserved enterprise segments, and differentiate on speed, integrations, and compliance-ready design.' if is_loser else ''}
    text='\n\n'.join(f"{i+1}. {r['title']}\n{r['url']}\n{r['snippet']}" for i,r in enumerate(serp))
    prompt=f'''Analyze local competitors in {market} in {country} for {company}. {text}. Return ONLY JSON: {{"competitors":[{{"name":"...","strengths":["..."],"weaknesses":["..."]}}],"competitive_threat":"low|medium|high","winning_strategy":"..."}}'''
    resp=await _openai.chat.completions.create(model=OPENAI_MODEL,max_tokens=MAX_TOKENS,temperature=0,messages=[{'role':'user','content':prompt}])
    return _safe_json(resp.choices[0].message.content or '{}')