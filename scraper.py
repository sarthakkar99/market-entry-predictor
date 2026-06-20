from urllib.parse import quote_plus
import httpx
from config import BRIGHTDATA_API_KEY, BRIGHTDATA_API_URL, BRIGHTDATA_ZONE, MOCK_MODE, SERP_RESULTS
MOCK_LIBRARY={
 'job_posts':[{'title':'Expansion hiring signal','url':'https://example.com/jobs','snippet':'Hiring market, operations, and partnership roles in the target country.'}],
 'domain_regs':[{'title':'Localized market page','url':'https://example.com/local','snippet':'Localized pages suggest go-to-market preparation.'}],
 'exec_hires':[{'title':'Senior regional leader hired','url':'https://example.com/hire','snippet':'Senior leader hired to build partnerships and operations.'}],
 'partnerships':[{'title':'New ecosystem partnership','url':'https://example.com/partner','snippet':'Local partnership formed to explore the target market.'}],
 'patents':[{'title':'Relevant patent filing','url':'https://patents.google.com/example','snippet':'Patent activity aligns with target market product capability.'}],
 'local_competitors':[{'title':'Top local competitors','url':'https://example.com/competitors','snippet':'Local leaders have distribution, trust, and regulatory relationships.'}],
 'government_incentives':[{'title':'Business incentives and workforce support','url':'https://example.com/incentives','snippet':'Economic development programs offer workforce training and expansion support.'}],
}
async def fetch_serp(query:str, agent_id:str='')->list[dict]:
    if MOCK_MODE: return _mock(query,agent_id)
    try: return await _brightdata(query)
    except Exception: return _mock(query,agent_id)
async def _brightdata(query:str)->list[dict]:
    payload={'zone':BRIGHTDATA_ZONE,'url':f'https://www.google.com/search?q={quote_plus(query)}&num={SERP_RESULTS}&brd_json=1','format':'raw'}
    headers={'Authorization':f'Bearer {BRIGHTDATA_API_KEY}','Content-Type':'application/json'}
    async with httpx.AsyncClient(timeout=30) as client:
        r=await client.post(BRIGHTDATA_API_URL,json=payload,headers=headers); r.raise_for_status(); data=r.json()
    organic=data.get('organic',[]) if isinstance(data,dict) else []
    return [{'title':i.get('title',''),'url':i.get('link',i.get('url','')),'snippet':i.get('description',i.get('snippet',''))} for i in organic[:SERP_RESULTS]]
def _mock(query,agent_id=''):
    rows=MOCK_LIBRARY.get(agent_id) or MOCK_LIBRARY['job_posts']
    return [{**r,'snippet':r['snippet']+' Query: '+query} for r in rows[:SERP_RESULTS]]
