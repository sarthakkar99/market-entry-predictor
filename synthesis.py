import json,re
from openai import AsyncOpenAI
from config import LLM_MOCK_MODE, MAX_TOKENS, OPENAI_API_KEY, OPENAI_MODEL, TOTAL_MAX_SCORE
from models import AgentResult, CompanyReport
_openai=AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
async def synthesize(company,market,country,agent_results:list[AgentResult])->CompanyReport:
    total=sum(r.score for r in agent_results); probability=round((total/TOTAL_MAX_SCORE)*100) if TOTAL_MAX_SCORE else 0; confidence='high' if probability>=70 else 'medium' if probability>=40 else 'low'
    if LLM_MOCK_MODE or _openai is None: return _fallback_report(company,market,country,probability,confidence,agent_results)
    summaries='\n'.join(f'- {r.label}: {r.score}/{r.max_score}. {", ".join(r.findings[:2])}' for r in agent_results)
    prompt=f'''Create an executive market-entry brief for {company}, {market}, {country}. Score {probability}/100. Findings: {summaries}. Return ONLY JSON: {{"timeline":"...","verdict":"...","key_findings":["..."],"strategic_implication":"...","recommended_actions":["..."]}}'''
    resp=await _openai.chat.completions.create(model=OPENAI_MODEL,max_tokens=MAX_TOKENS,temperature=0,messages=[{'role':'user','content':prompt}])
    data=_safe_json(resp.choices[0].message.content or '{}')
    return CompanyReport(company=company,market=market,country=country,probability=probability,confidence=confidence,timeline=data.get('timeline',_timeline(probability)),verdict=data.get('verdict',_verdict(probability)),key_findings=data.get('key_findings',_top_findings(agent_results)),strategic_implication=data.get('strategic_implication','Expansion signals should be validated before capital commitment.'),recommended_actions=data.get('recommended_actions',_actions(probability)),agent_results=agent_results)
def _safe_json(raw):
    try: return json.loads(raw.strip())
    except Exception:
        m=re.search(r'\{.*\}',raw,re.DOTALL)
        try: return json.loads(m.group()) if m else {}
        except Exception: return {}
def _fallback_report(company,market,country,probability,confidence,agent_results):
    return CompanyReport(company=company,market=market,country=country,probability=probability,confidence=confidence,timeline=_timeline(probability),verdict=_verdict(probability),key_findings=_top_findings(agent_results),strategic_implication='The evidence suggests a market-entry opportunity, but leadership should validate location, cost, incentives, and compliance risk before execution.',recommended_actions=_actions(probability),agent_results=agent_results)
def _timeline(p): return '0-6 months' if p>=75 else '6-12 months' if p>=55 else '12+ months or monitor' if p>=35 else 'monitor only'
def _verdict(p): return 'Strong expansion signal' if p>=75 else 'Moderate expansion signal' if p>=55 else 'Weak but watch-worthy signal' if p>=35 else 'Insufficient evidence'
def _actions(p): return ['Open expansion planning case','Evaluate office location and incentives','Run legal and finance review'] if p>=70 else ['Monitor new signals weekly','Validate competitor activity','Prepare partner-led entry option'] if p>=40 else ['Continue monitoring','Collect stronger evidence before investment']
def _top_findings(results):
    out=[]
    for r in sorted(results,key=lambda x:x.score,reverse=True): out.extend(r.findings[:1])
    return out[:5] or ['No strong findings found.']
