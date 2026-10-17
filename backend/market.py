"""Owner-authenticated Yahoo daily data for personal testing, never synthetic fallback."""
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
import math
import threading
from .core import UNIVERSE, now

YAHOO_SYMBOLS={s:s+'.NS' for s in UNIVERSE}
LOCK=threading.Lock()
TTL_SECONDS=21600
COOLDOWN_SECONDS=300

class MarketDataError(ValueError):pass

def parse_time(value):
 try:
  d=datetime.fromisoformat(value.replace('Z','+00:00'))
  return d if d.tzinfo else None
 except (ValueError,TypeError,AttributeError):return None

def fetch_history(symbol, clock=None):
 # Lazy import keeps the dashboard/API startup lightweight.
 import yfinance as yf
 current=clock or datetime.now(timezone.utc)
 frame=yf.Ticker(YAHOO_SYMBOLS[symbol]).history(period='6mo',interval='1d',auto_adjust=False,actions=True,timeout=8,raise_errors=True)
 if frame.empty:raise MarketDataError('Provider returned no daily candles')
 # .NS mappings in this adapter are fixed to NSE equities and INR.
 local=current.astimezone(ZoneInfo('Asia/Kolkata'))
 candles=[]
 for index,row in frame.iterrows():
  d=index.date()
  # Exclude unfinished daily candles; 30-minute buffer after regular close.
  if d>local.date() or (d==local.date() and local.time()<time(16,0)):continue
  close=float(row['Close']);adjusted=float(row.get('Adj Close',close));volume=float(row.get('Volume',0))
  if not all(math.isfinite(x) for x in (close,adjusted,volume)) or close<=0 or adjusted<=0 or volume<0:continue
  as_of=datetime.combine(d,time(15,30),tzinfo=ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc).isoformat()
  candles.append({'date':d.isoformat(),'as_of':as_of,'close':close,'adjusted_close':adjusted,'volume':volume})
 # Do not silently accept a malformed provider ordering or duplicate dates.
 candles.sort(key=lambda c:c['date'])
 if len({c['date'] for c in candles})!=len(candles):raise MarketDataError('Duplicate provider candle dates')
 if len(candles)<51:raise MarketDataError('Provider returned fewer than 51 completed daily candles')
 return {'symbol':symbol,'provider_symbol':YAHOO_SYMBOLS[symbol],'currency':'INR','exchange':'NSE','candles':candles,
         'quote':{'price':candles[-1]['close'],'as_of':candles[-1]['as_of'],'source':'Yahoo Finance via yfinance / unofficial personal testing','provider_symbol':YAHOO_SYMBOLS[symbol],'retrieved_at':current.isoformat(),'price_type':'completed daily close','currency':'INR'},
         'closes':[c['adjusted_close'] for c in candles],'retrieved_at':current.isoformat(),'adjustment':'Adjusted closes for trend analysis; raw close for current valuation'}

def refresh_market(get,put,symbols=None,fetcher=None,clock=None):
 symbols=list(dict.fromkeys(symbols or UNIVERSE.keys()))
 if not symbols or len(symbols)>8 or any(s not in UNIVERSE for s in symbols):raise MarketDataError('Choose 1–8 supported symbols')
 if not LOCK.acquire(blocking=False):raise MarketDataError('A price refresh is already running; try again shortly')
 try:
  current=clock or datetime.now(timezone.utc);fetcher=fetcher or fetch_history
  cache=get('market_cache',{});attempts=get('market_attempts',{});results=[];errors=[]
  for s in symbols:
   item=cache.get(s);updated=parse_time(item.get('retrieved_at')) if item else None
   if updated and 0<=(current-updated).total_seconds()<TTL_SECONDS:
    results.append({'symbol':s,'status':'cached','as_of':item['quote']['as_of']});continue
   last=parse_time(attempts.get(s))
   if last and 0<=(current-last).total_seconds()<COOLDOWN_SECONDS:
    errors.append({'symbol':s,'error':'ProviderCooldown','detail':'Last attempt was within five minutes. Existing data retained.'});continue
   attempts[s]=current.isoformat();put('market_attempts',attempts)
   try:
    item=fetcher(s,clock=current)
    cache[s]=item;put('market_cache',cache)
    results.append({'symbol':s,'status':'updated','as_of':item['quote']['as_of']})
   except Exception as exc:
    # Do not leak network/proxy settings or secrets from provider exception messages.
    errors.append({'symbol':s,'error':type(exc).__name__,'detail':'Provider data unavailable. Existing prices retained; no sample prices substituted.'})
  # Restore a cached series only when it remains the selected source. A newer manual import wins until provider refresh.
  for result in results:
   s=result['symbol'];item=cache[s]
   quotes=get('quotes',{});history=get('history',{});candles=get('price_candles',{})
   existing=parse_time(quotes.get(s,{}).get('retrieved_at'))
   if result['status']=='cached' and existing and existing>parse_time(item['retrieved_at']):continue
   quotes[s]=item['quote'];history[s]=item['closes'];candles[s]=item['candles']
   put('quotes',quotes);put('history',history);put('price_candles',candles)
  output={'provider':'Yahoo Finance / yfinance','usage':'personal testing only','results':results,'errors':errors,'retrieved_at':current.isoformat(),'cache_ttl_seconds':TTL_SECONDS,'price_type':'completed daily closes, not real-time quotes'}
  put('market_status',output);return output
 finally:LOCK.release()
