from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest
from backend.market import refresh_market, fetch_history, MarketDataError
from tests.test_marketlens import client, HEAD
from backend import main

CLOCK=datetime(2026,10,16,12,tzinfo=timezone.utc)
def item(symbol,clock=None):
 t=(clock or CLOCK).isoformat()
 return {'symbol':symbol,'retrieved_at':t,'quote':{'price':120,'as_of':t,'source':'test provider','retrieved_at':t},'closes':list(range(100,160)),'candles':[{'date':'2026-10-16','close':120}]}
def storage():
 state={}
 return state,lambda k,d=None:state.get(k,d),lambda k,v:state.__setitem__(k,v)
def test_cache_avoids_second_provider_request():
 s,get,put=storage();calls=[]
 def fetch(symbol,clock):calls.append(symbol);return item(symbol,clock)
 a=refresh_market(get,put,['TCS'],fetch,CLOCK)
 b=refresh_market(get,put,['TCS'],fetch,CLOCK+timedelta(hours=1))
 assert len(calls)==1 and b['results'][0]['status']=='cached'
 assert s['quotes']['TCS']['source']=='test provider'
def test_cache_expiry_refetches():
 s,get,put=storage();calls=[]
 def fetch(symbol,clock):calls.append(symbol);return item(symbol,clock)
 refresh_market(get,put,['TCS'],fetch,CLOCK)
 refresh_market(get,put,['TCS'],fetch,CLOCK+timedelta(hours=7))
 assert len(calls)==2
def test_failure_retains_previous_data_and_cools_down():
 s,get,put=storage();s['quotes']={'TCS':{'price':99}}
 def bad(*args,**kwargs):raise ConnectionError('private proxy detail')
 r=refresh_market(get,put,['TCS'],bad,CLOCK)
 assert r['errors'] and s['quotes']['TCS']['price']==99
 assert 'private proxy' not in str(r)
 r=refresh_market(get,put,['TCS'],bad,CLOCK+timedelta(seconds=1))
 assert r['errors'][0]['error']=='ProviderCooldown'
def test_partial_success():
 s,get,put=storage()
 def fetch(symbol,clock):
  if symbol=='INFY':raise ValueError('no data')
  return item(symbol,clock)
 r=refresh_market(get,put,['TCS','INFY'],fetch,CLOCK)
 assert len(r['results'])==1 and len(r['errors'])==1 and 'INFY' not in s['quotes']
def test_invalid_symbol():
 s,get,put=storage()
 with pytest.raises(MarketDataError):refresh_market(get,put,['FAKE'],item,CLOCK)
def test_intraday_candle_excluded_and_adjustment_separated(monkeypatch):
 import yfinance as yf
 dates=pd.bdate_range(end='2026-10-16',periods=65,tz='Asia/Kolkata')
 df=pd.DataFrame({'Close':[120.0]*65,'Adj Close':[110.0]*65,'Volume':[10]*65},index=dates)
 class Ticker:
  def __init__(self,*a):pass
  def history(self,**kwargs):return df
 monkeypatch.setattr(yf,'Ticker',Ticker)
 r=fetch_history('TCS',datetime(2026,10,16,8,tzinfo=timezone.utc))
 assert r['candles'][-1]['date']=='2026-10-15'
 assert r['quote']['price']==120 and r['closes'][-1]==110
 assert r['provider_symbol']=='TCS.NS'
def test_market_endpoint_requires_auth(client):assert client.post('/api/market/refresh',json={}).status_code==401
def test_market_endpoint_and_live_scores(client,monkeypatch):
 import backend.market as market
 monkeypatch.setattr(market,'fetch_history',item)
 r=client.post('/api/market/refresh',headers=HEAD,json={'symbols':['TCS']})
 assert r.status_code==200 and len(r.json()['results'])==1
 state=client.get('/api/state',headers=HEAD).json()
 assert state['quotes']['TCS']['price']==120
 assert state['screeners']['TCS']['available']
