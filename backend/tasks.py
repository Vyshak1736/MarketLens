"""Scheduled collection runs without an open browser; UTC schedule, weekdays."""
import os, asyncio
from celery import Celery
from celery.schedules import crontab
from .main import init, put
from .core import now
from .ingestion import collect
app=Celery('marketlens',broker=os.getenv('CELERY_BROKER_URL','amqp://guest:guest@localhost:5672//'))
app.conf.update(timezone='UTC',task_ignore_result=True,broker_connection_retry_on_startup=True,beat_schedule={'news-weekdays':{'task':'marketlens.scan','schedule':crontab(minute='0',hour='3-12',day_of_week='1-5')}})
@app.task(name='marketlens.scan',autoretry_for=(ConnectionError,),retry_backoff=True,max_retries=3)
def scan():
 init();result=asyncio.run(collect());put('news',result);put('last_scan',now());return {'articles':len(result['articles']),'errors':len(result['errors'])}
