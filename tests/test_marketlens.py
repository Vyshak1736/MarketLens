import os
os.environ['API_TOKEN']='test-token'
os.environ['DATABASE_URL']='sqlite://'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from backend import main
from backend.core import parse_holdings, portfolio, technical, mentioned
from backend.engine import workflow
main.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
HEAD={'Authorization':'Bearer test-token'}
@pytest.fixture
def client():
 with main.engine.begin() as c:c.exec_driver_sql('DROP TABLE IF EXISTS state')
 with TestClient(main.app) as c:yield c
@pytest.mark.parametrize('csv',['symbol,quantity,average_cost\nTCS,nan,10','symbol,quantity,average_cost\nTCS,1,inf','symbol,quantity,average_cost\nTCS,-1,10','symbol,quantity,average_cost\nFAKE,1,10','symbol,quantity,average_cost\nTCS,1,10\nTCS,2,20','symbol,quantity,average_cost\n','x,y,z\n1,2,3'])
def test_bad_portfolio(csv):
 with pytest.raises(ValueError):parse_holdings(csv)
def test_missing_quotes_not_reported_as_loss():
 p=portfolio(parse_holdings('symbol,quantity,average_cost\nTCS,2,100'),{})
 assert not p['complete'] and p['pnl']==0 and p['cost']==200 and p['missing_quotes']==['TCS']
def test_portfolio_calculations():
 p=portfolio(parse_holdings('symbol,quantity,average_cost\nTCS,2,100'),{'TCS':{'price':120,'source':'test','as_of':'2026-01-01T00:00:00Z'}})
 assert p['value']==240 and p['pnl']==40 and p['sectors'][0]['weight']==100
def test_short_history():assert not technical([10]*20)['available']
def test_rising_series():
 t=technical(list(range(100,160)));assert t['score']==100 and t['momentum_20d']>0
def test_alias_word_boundaries():assert mentioned('Political discussions of Infosys')==['INFY']
def test_long_horizon_no_unverified_ranking():
 r=workflow.invoke({'symbol':'TCS','horizon':'long','articles':[],'closes':list(range(100,160))})['report']
 assert r['conclusion']=='Insufficient evidence'
def test_no_auth(client):assert client.get('/api/state').status_code==401
def test_missing_server_token(client,monkeypatch):
 monkeypatch.delenv('API_TOKEN');assert client.get('/api/state',headers=HEAD).status_code==503
def test_api_import_and_research(client):
 r=client.post('/api/portfolio/import',headers=HEAD,json={'content':'symbol,quantity,average_cost\nTCS,2,100'});assert r.status_code==200
 assert client.get('/api/portfolio',headers=HEAD).json()['complete'] is False
 r=client.post('/api/prices/import',headers=HEAD,json={'symbol':'TCS','prices':list(range(100,160)),'as_of':'2026-01-01T00:00:00Z','source':'test fixture'});assert r.status_code==200
 assert client.get('/api/portfolio',headers=HEAD).json()['value']==318
 r=client.post('/api/research',headers=HEAD,json={'symbol':'TCS','horizon':'short'});assert r.status_code==200
 assert r.json()['conclusion']=='Insufficient evidence'
 assert len(client.get('/api/export',headers=HEAD).json()['reports'])==1
def test_price_timestamp(client):
 r=client.post('/api/prices/import',headers=HEAD,json={'symbol':'TCS','prices':[100],'as_of':'2999-01-01T00:00:00Z','source':'bad future'});assert r.status_code==422
def test_source_failure_is_not_success(client,monkeypatch):
 async def collect():return {'articles':[],'errors':[{'source':'test','error':'Blocked'}]}
 monkeypatch.setattr(main,'collect',collect)
 r=client.post('/api/scan',headers=HEAD,json={});assert r.status_code==200 and len(r.json()['errors'])==1
 assert client.get('/api/state',headers=HEAD).json()['news']['articles']==[]
def test_ssrf_blocked():
 from backend.ingestion import valid_url
 for u in ['http://www.business-standard.com/a','https://localhost/a','https://127.0.0.1/a','https://evil.com/a','https://www.business-standard.com:8443/a']:
  with pytest.raises(ValueError):valid_url(u)
def test_static_dashboard(client):assert client.get('/').status_code==200
