"""Allowlisted RSS + robots-aware article reader; article text is untrusted data."""
import hashlib, os, socket, ipaddress, re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from html.parser import HTMLParser
from datetime import datetime, timezone
import feedparser, httpx
from .core import now, mentioned
AGENT='MarketLensResearch/0.1'
ALLOWED=set(x.strip().lower() for x in os.getenv('NEWS_ALLOWED_HOSTS','www.business-standard.com').split(',') if x.strip())
class Text(HTMLParser):
 def __init__(self): super().__init__();self.blocks=[];self.current=[];self.inside=False;self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style','nav','footer'): self.skip+=1
  if tag=='p':self.inside=True;self.current=[]
 def handle_endtag(self,tag):
  if tag in ('script','style','nav','footer'):self.skip=max(0,self.skip-1)
  if tag=='p' and self.inside:
   t=' '.join(' '.join(self.current).split())
   if len(t)>50:self.blocks.append(t)
   self.inside=False
 def handle_data(self,data):
  if self.inside and not self.skip:self.current.append(data)
def valid_url(url):
 p=urlparse(url)
 if p.scheme!='https' or p.hostname not in ALLOWED or p.username or p.password or p.port not in (None,443):raise ValueError('URL must use HTTPS on a configured news host')
 for info in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
  if not ipaddress.ip_address(info[4][0]).is_global:raise ValueError('Non-public host address blocked')
 return url
async def fetch(url):
 valid_url(url)
 async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':AGENT}) as c:
  async with c.stream('GET',url) as r:
   r.raise_for_status(); data=b''
   async for chunk in r.aiter_bytes():
    data+=chunk
    if len(data)>2_000_000:raise ValueError('Source exceeds 2 MB limit')
   return data.decode('utf-8',errors='replace')
async def article_body(url):
 p=urlparse(url);robot=RobotFileParser();robot.parse((await fetch(f'https://{p.netloc}/robots.txt')).splitlines())
 if not robot.can_fetch(AGENT,url):raise ValueError('robots.txt disallows article reading')
 parser=Text();parser.feed(await fetch(url));return '\n'.join(parser.blocks)[:16000]
async def collect():
 feeds=[s.strip() for s in os.getenv('NEWS_FEEDS','https://www.business-standard.com/rss/markets-106.rss').split(',') if s.strip()]
 articles=[];errors=[];seen=set()
 for url in feeds[:10]:
  try:
   parsed=feedparser.parse(await fetch(url))
   if parsed.bozo and not parsed.entries:raise ValueError('Invalid or empty RSS response')
   for e in parsed.entries[:25]:
    link=e.get('link',''); title=e.get('title','')[:500]
    try:valid_url(link)
    except ValueError:continue
    key=hashlib.sha256(re.sub(r'\W+',' ',title.lower()).strip().encode()).hexdigest()
    if key in seen:continue
    seen.add(key);published=None
    if e.get('published_parsed'):published=datetime(*e.published_parsed[:6],tzinfo=timezone.utc).isoformat()
    summary=re.sub('<[^>]+>',' ',e.get('summary',''))[:2000]
    a={'id':key,'title':title,'url':link,'published_at':published,'retrieved_at':now(),'summary':summary,'symbols':mentioned(title+' '+summary),'source':urlparse(link).hostname,'body':'','read_status':'feed excerpt only'}
    if a['symbols'] and os.getenv('READ_ARTICLES','false').lower()=='true':
     try:a['body']=await article_body(link);a['read_status']='article fetched' if a['body'] else 'no readable paragraphs'
     except Exception as exc:a['read_status']=f'Article unavailable: {type(exc).__name__}'
    articles.append(a)
  except Exception as exc:errors.append({'source':url,'error':type(exc).__name__,'detail':str(exc)[:180]})
 return {'articles':articles,'errors':errors,'retrieved_at':now()}
