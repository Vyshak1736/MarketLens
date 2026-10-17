import os, json, secrets, asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from pathlib import Path
from .core import UNIVERSE, parse_holdings, portfolio, now
from .ingestion import collect
from .engine import workflow
from .market import refresh_market, MarketDataError
DB=os.getenv('DATABASE_URL','sqlite:///./marketlens.db')
engine=create_engine(DB,**({'connect_args':{'check_same_thread':False}} if DB.startswith('sqlite') else {}))
def init():
 with engine.begin() as c:
  c.execute(text('CREATE TABLE IF NOT EXISTS state (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)'))
def get(key,default=None):
 with engine.connect() as c:
  row=c.execute(text('SELECT value FROM state WHERE key=:key'),{'key':key}).first()
 return json.loads(row[0]) if row else default
def put(key,value):
 with engine.begin() as c:
  c.execute(text('INSERT INTO state (key,value) VALUES (:key,:value) ON CONFLICT (key) DO UPDATE SET value=excluded.value'),{'key':key,'value':json.dumps(value)})
@asynccontextmanager
async def lifespan(app):init();yield
app=FastAPI(title='MarketLens Research API',version='0.2.1',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:8000,http://127.0.0.1:8000').split(',')],allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
@app.middleware('http')
async def response_cache_policy(request:Request,call_next):
 response=await call_next(request)
 response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
 return response
def auth(authorization:str=Header(default='')):
 token=os.getenv('API_TOKEN','')
 if not token:raise HTTPException(503,'Set API_TOKEN before using the backend')
 if not secrets.compare_digest(authorization,'Bearer '+token):raise HTTPException(401,'Invalid API token')
@app.get('/api/health')
def health():return {'status':'ok','mode':'live backend','version':'0.2.1','llm_connected':False}
@app.get('/api/state',dependencies=[Depends(auth)])
def state():return {'holdings':get('holdings',[]),'quotes':get('quotes',{}),'news':get('news',{'articles':[],'errors':[]}),'last_scan':get('last_scan'),'reports':get('reports',[]),'universe':UNIVERSE,'market_status':get('market_status'),'screeners':screeners()}
class MarketBody(BaseModel):
 symbols:list[str]|None=Field(default=None,min_length=1,max_length=8)
@app.post('/api/market/refresh',dependencies=[Depends(auth)])
def market_refresh(body:MarketBody):
 try:return refresh_market(get,put,body.symbols)
 except MarketDataError as exc:raise HTTPException(409 if 'running' in str(exc) else 422,str(exc))
def screeners():
 from .core import technical
 quotes=get('quotes',{});history=get('history',{});items={}
 for symbol in UNIVERSE:
  metric=technical(history.get(symbol,[]));q=quotes.get(symbol,{})
  try:fresh=0<=(datetime.now(timezone.utc)-datetime.fromisoformat(q.get('as_of','').replace('Z','+00:00'))).total_seconds()<=96*3600
  except (ValueError,TypeError):fresh=False
  items[symbol]={**metric,'fresh':fresh,'as_of':q.get('as_of'),'source':q.get('source')}
 return items
@app.get('/api/portfolio',dependencies=[Depends(auth)])
def portfolio_api():return portfolio(get('holdings',[]),get('quotes',{}))
class CSVBody(BaseModel):content:str=Field(max_length=150000)
@app.post('/api/portfolio/import',dependencies=[Depends(auth)])
def import_portfolio(body:CSVBody):
 try:holdings=parse_holdings(body.content)
 except ValueError as exc:raise HTTPException(422,str(exc))
 put('holdings',holdings);return {'imported':len(holdings),'portfolio':portfolio(holdings,get('quotes',{}))}
@app.post('/api/scan',dependencies=[Depends(auth)])
async def scan():
 result=await collect();put('news',result);put('last_scan',now());return result
class ResearchBody(BaseModel):symbol:str;horizon:str='long'
@app.post('/api/research',dependencies=[Depends(auth)])
def research(body:ResearchBody):
 if body.symbol not in UNIVERSE or body.horizon not in ('short','long'):raise HTTPException(422,'Unsupported symbol or horizon')
 result=workflow.invoke({'symbol':body.symbol,'horizon':body.horizon,'articles':get('news',{}).get('articles',[]),'closes':get('history',{}).get(body.symbol,[]),'quote':get('quotes',{}).get(body.symbol,{})})['report']
 reports=get('reports',[]);put('reports',([result]+reports)[:100]);return result
class PriceBody(BaseModel):symbol:str;prices:list[float]=Field(min_length=1,max_length=5000);as_of:str;source:str=Field(min_length=1,max_length=250)
@app.post('/api/prices/import',dependencies=[Depends(auth)])
def prices(body:PriceBody):
 import math
 if body.symbol not in UNIVERSE or any(not math.isfinite(p) or p<=0 for p in body.prices):raise HTTPException(422,'Invalid symbol or prices')
 try:dt=datetime.fromisoformat(body.as_of.replace('Z','+00:00'))
 except ValueError:raise HTTPException(422,'as_of must be an ISO timestamp')
 if not dt.tzinfo or dt>datetime.now(timezone.utc):raise HTTPException(422,'as_of needs timezone and must not be in the future')
 history=get('history',{});history[body.symbol]=body.prices;put('history',history)
 quotes=get('quotes',{});quotes[body.symbol]={'price':body.prices[-1],'as_of':body.as_of,'source':body.source,'retrieved_at':now()};put('quotes',quotes);return {'imported':len(body.prices)}
@app.get('/api/export',dependencies=[Depends(auth)])
def export():return {'exported_at':now(),'reports':get('reports',[]),'portfolio':portfolio(get('holdings',[]),get('quotes',{}))}
ROOT=Path(__file__).resolve().parent.parent/'dist'
if ROOT.exists():app.mount('/',StaticFiles(directory=ROOT,html=True),name='dashboard')
