"""Evidence workflow. Deliberately rules-based; no unconfigured LLM claims."""
from typing import TypedDict
from datetime import datetime, timezone
import hashlib, json
from langgraph.graph import StateGraph, START, END
from .core import now, technical
class State(TypedDict, total=False):
 symbol:str
 horizon:str
 articles:list
 closes:list
 quote:dict
 report:dict

def gather(s):
 return {'articles':[a for a in s.get('articles',[]) if s['symbol'] in a.get('symbols',[])]}
def assess(s):
 articles=s['articles']; tech=technical(s.get('closes',[]))
 risks=['News coverage is incomplete and may be delayed.','Price reactions may already reflect the news.']
 if s['horizon']=='long': risks.append('Fundamentals and valuation are not connected; long-term ranking is unavailable.')
 if not articles: risks.append('No matching source evidence found in the collected feed window.')
 if s['horizon']=='short': risks.append('Trend scores do not include liquidity, volume or transaction costs.')
 status='Insufficient evidence'
 fresh_price=False; fresh_news=False
 try:
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(s.get('quote',{}).get('as_of','').replace('Z','+00:00'))).total_seconds()/3600
  fresh_price=0<=age<=96
 except (ValueError,TypeError): pass
 for a in articles:
  try:
   age=(datetime.now(timezone.utc)-datetime.fromisoformat((a.get('published_at') or '').replace('Z','+00:00'))).total_seconds()/3600
   fresh_news=fresh_news or 0<=age<=168
  except (ValueError,TypeError): pass
 if not fresh_price: risks.append('Price history is stale, undated or missing; no current trend ranking is supported.')
 if not fresh_news: risks.append('No timestamped news in the last seven days supports a current ranking.')
 if s['horizon']=='short' and tech['available'] and fresh_price and fresh_news: status=tech['label']
 return {'report':{'symbol':s['symbol'],'horizon':s['horizon'],'conclusion':status,'generated_at':now(),'engine':'LangGraph / deterministic evidence workflow','technical':tech,'evidence':[{'title':a['title'],'url':a['url'],'published_at':a.get('published_at'),'retrieved_at':a['retrieved_at'],'body_fetched':bool(a.get('body')),'excerpt':a.get('body','')[:700] or a.get('summary','')[:700]} for a in articles[:12]],'risks':risks,'reason':'Review the linked reporting alongside verified financial data. No automated buy/sell decision is produced.','invalidation':'Refresh after corrected reporting, new filings or changed market data.'}}

def verify(s):
 r=s['report']; r['input_fingerprint']=hashlib.sha256(json.dumps({'closes':s.get('closes',[]),'quote':s.get('quote',{}),'articles':s['articles']},sort_keys=True).encode()).hexdigest(); r['price_provenance']=s.get('quote',{}); r['evidence_count']=len(r['evidence']); r['sources_checked']=all(a['url'].startswith('https://') for a in r['evidence']); return {'report':r}
b=StateGraph(State); b.add_node('gather',gather);b.add_node('assess',assess);b.add_node('verify',verify)
b.add_edge(START,'gather');b.add_edge('gather','assess');b.add_edge('assess','verify');b.add_edge('verify',END)
workflow=b.compile()
