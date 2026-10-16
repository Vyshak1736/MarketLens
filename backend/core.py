"""Deterministic calculations. All financial inputs require provenance."""
import csv
import io
import math
from datetime import datetime, timezone

UNIVERSE = {
 'TCS': {'name':'Tata Consultancy Services','sector':'Technology','aliases':['tcs','tata consultancy']},
 'INFY': {'name':'Infosys','sector':'Technology','aliases':['infosys']},
 'HDFCBANK': {'name':'HDFC Bank','sector':'Banking','aliases':['hdfc bank']},
 'ICICIBANK': {'name':'ICICI Bank','sector':'Banking','aliases':['icici bank']},
 'RELIANCE': {'name':'Reliance Industries','sector':'Energy','aliases':['reliance industries']},
 'SUNPHARMA': {'name':'Sun Pharmaceutical','sector':'Healthcare','aliases':['sun pharma']},
 'LT': {'name':'Larsen & Toubro','sector':'Industrials','aliases':['larsen','l&t']},
 'ITC': {'name':'ITC','sector':'Consumer','aliases':['itc']},
}
def now(): return datetime.now(timezone.utc).isoformat()
def finite(value, name, positive=False):
 try: value=float(value)
 except (ValueError,TypeError): raise ValueError(f'{name} must be a number')
 if not math.isfinite(value) or (positive and value<=0) or (not positive and value<0):
  raise ValueError(f'{name} must be finite and {"positive" if positive else "non-negative"}')
 return value

def parse_holdings(content):
 reader=csv.DictReader(io.StringIO(content))
 if not {'symbol','quantity','average_cost'}.issubset(reader.fieldnames or []):
  raise ValueError('CSV requires symbol,quantity,average_cost columns')
 holdings=[]; seen=set()
 for line,row in enumerate(reader,2):
  if len(holdings)>=500: raise ValueError('Maximum 500 holdings')
  symbol=(row.get('symbol') or '').strip().upper()
  if symbol not in UNIVERSE: raise ValueError(f'Line {line}: unsupported symbol {symbol}')
  if symbol in seen: raise ValueError(f'Line {line}: duplicate symbol {symbol}; combine lots first')
  seen.add(symbol)
  holdings.append({'symbol':symbol,'quantity':finite(row.get('quantity'),'quantity',True),'average_cost':finite(row.get('average_cost'),'average_cost',True)})
 if not holdings: raise ValueError('CSV is empty')
 return holdings

def portfolio(holdings, quotes, threshold=35):
 rows=[]; sectors={}; cost=0; valued_cost=0; value=0; missing=[]; stale=[]
 for h in holdings:
  s=h['symbol']; c=h['quantity']*h['average_cost']; cost+=c; q=quotes.get(s)
  row={**h,**UNIVERSE[s],'cost':round(c,2),'price':None,'value':None,'pnl':None}
  if q and q.get('price',0)>0:
   v=h['quantity']*q['price']; value+=v; valued_cost+=c
   try:
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(q['as_of'].replace('Z','+00:00'))).total_seconds()/3600
    if age>96: stale.append(s)
   except (ValueError,KeyError,TypeError): stale.append(s)
   row.update(price=q['price'],value=round(v,2),pnl=round(v-c,2),as_of=q['as_of'],source=q['source'])
   sectors[row['sector']]=sectors.get(row['sector'],0)+v
  else: missing.append(s)
  rows.append(row)
 weights=[{'sector':s,'value':round(v,2),'weight':round(v/value*100,2) if value else 0} for s,v in sectors.items()]
 alerts=[f"{r['sector']} is {r['weight']:.1f}% of priced holdings (limit {threshold}%)." for r in weights if r['weight']>threshold]
 if stale: alerts.insert(0,'Stale or undated quotes: '+', '.join(stale))
 if missing: alerts.insert(0,'Incomplete valuation: missing quotes for '+', '.join(missing))
 return {'holdings':rows,'cost':round(cost,2),'priced_cost':round(valued_cost,2),'value':round(value,2),'pnl':round(value-valued_cost,2),'complete':not missing,'missing_quotes':missing,'stale_quotes':stale,'sectors':weights,'alerts':alerts,'as_of':now()}

def technical(closes):
 if len(closes)<51: return {'available':False,'reason':'At least 51 daily closing prices required'}
 prices=[finite(p,'close',True) for p in closes]
 mean20=sum(prices[-20:])/20; mean50=sum(prices[-50:])/50
 momentum=(prices[-1]/prices[-21]-1)*100
 returns=[math.log(b/a) for a,b in zip(prices[-21:-1],prices[-20:])]
 avg=sum(returns)/len(returns); vol=(sum((r-avg)**2 for r in returns)/len(returns))**0.5*(252**0.5)*100
 score=round(50+20*(prices[-1]>mean20)+20*(mean20>mean50)+10*(momentum>0))
 return {'available':True,'score':score,'momentum_20d':round(momentum,2),'sma20':round(mean20,2),'sma50':round(mean50,2),'annualized_volatility':round(vol,2),'label':'Research candidate' if score>=80 else 'Watch','method':'Trend screen v1; no volume or liquidity model; not a return forecast'}

def mentioned(text):
 import re
 return [s for s,v in UNIVERSE.items() if any(re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)',text.lower()) for a in v['aliases'])]
