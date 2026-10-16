"""Collect news on the deployed API without a resident free-tier worker."""
import json, os, urllib.request, urllib.error, sys
from urllib.parse import urlparse
base=os.environ.get('MARKETLENS_API_URL','').rstrip('/')
token=os.environ.get('MARKETLENS_API_TOKEN','')
if not base or not token:
 print('Set MARKETLENS_API_URL and MARKETLENS_API_TOKEN repository secrets to enable scans.')
 sys.exit(0)
u=urlparse(base)
if u.scheme!='https' or u.username or u.password:raise SystemExit('API URL must be HTTPS without credentials')
# Wake a sleeping free service first. No repeated keep-alive traffic.
try:
 with urllib.request.urlopen(base+'/api/health',timeout=150) as r:
  if r.status!=200:raise SystemExit('Health check failed')
 req=urllib.request.Request(base+'/api/scan',data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
 print(json.dumps({'articles':len(result.get('articles',[])),'source_errors':len(result.get('errors',[]))}))
 if result.get('errors') and not result.get('articles'):raise SystemExit('No source succeeded. Check configured feed access.')
except urllib.error.HTTPError as e:
 raise SystemExit(f'API returned HTTP {e.code}. Check service status and repository secret configuration.') from None
except (urllib.error.URLError,TimeoutError):
 raise SystemExit('API unavailable or timed out. Inspect the hosting dashboard.') from None
