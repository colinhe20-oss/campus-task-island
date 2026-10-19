"""Collect one natural-language preference and recommendation dialogue per activity scene.

Only synthetic scenario data is used. Recognition tags in the isolated activity
are matcher fixtures required by the current ActivityCreate schema.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import time
from datetime import datetime
from pathlib import Path

from campus.activity_schemas import ActivityCreate
from campus.app import create_app
from campus.assistance import Preferences
from campus.clock import business_time
from campus.guide import model_backend
from campus.schemas import GuideInput
from .collect_letter_sample import ObservedBackend

ROOT=Path(__file__).resolve().parents[1]
SUPPORTED={'EXP-A01','EXP-A02'}


def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def run(sid,target):
 if sid not in SUPPORTED: raise ValueError('Unsupported scene')
 spec=ROOT/'docs/dataset_samples'/sid; m=read(spec/'manifest.json')
 for n,h in m['files'].items():
  if sha(spec/n)!=h: raise ValueError('Frozen source hash mismatch: '+n)
 cases=read(spec/'participant_cases.json'); cfg=cases['native_matrix']; dialogue=cases['natural_dialogues'][0]; pid,message=dialogue['profile'],dialogue['message']
 if target.exists(): raise ValueError('Use a new output directory')
 target.mkdir(parents=True); at=datetime.fromisoformat('2026-10-20T10:00:00+08:00'); calls=[]; report={'sample_id':sid,'profile':pid,'status':'collecting','messages':[],'numeric_score':None}
 with business_time(lambda:at):
  app=create_app(target/'world.sqlite3',business_clock=lambda:at,enable_semantics=False);app.state.task_service.initialize()
  owner=app.state.auth_service.register('organizer','organizer',secrets.token_urlsafe(24))[1]
  body=ActivityCreate.model_validate({'title':cfg['title'],'description':cfg['description'],'location':cfg['location'],'starts_at':f"{cfg['date']}T{cfg['start']}:00+08:00",'ends_at':f"{cfg['date']}T{cfg['end']}:00+08:00",'opens_at':cfg['opens_at'],'closes_at':cfg['closes_at'],'capacity':cfg['capacity'],'registration_mode':cfg['mode'],'recognition_tags':[cfg['credited_tag_fixture']],'recognition_description':'测试夹具标签，不代表校方认定。','organization_name':cfg['org'],'information_source':cfg['source'],'contact':cfg['contact'],'participation_requirements':cfg['requirements']})
  activity=app.state.activity_service.create(body,owner.id);u=app.state.auth_service.register(pid.lower(),pid,secrets.token_urlsafe(24))[1]
  guide=app.state.guide_service;guide.matching.semantics=None;guide.backend_factory=lambda:ObservedBackend(model_backend(),calls)
  try:
   start=time.monotonic();r=guide.chat(GuideInput(message=message),u);row={'turn':1,'user':message,'answer':r.answer,'run_id':r.run_id,'seconds':round(time.monotonic()-start,3),'trace':guide.runs.read(r.run_id,u.id)};report['messages'].append(row)
   assistance=guide.assistance.read(r.conversation_id,u.id);proposal=(assistance or {}).get('preference_proposal');fields=(proposal or {}).get('fields') or {}
   conf=cfg['profiles'][pid]; avail=[{'starts_at':f"{cfg['date']}T{s}:00+08:00",'ends_at':f"{cfg['date']}T{e}:00+08:00"} for s,e in conf.get('available',[])]
   checks={'proposal_exists':proposal is not None,'interests_exact':set(fields.get('interests',[]))==set(conf['interests']),'time_exact':fields.get('available_slots')==avail,'no_weekly_invention':not fields.get('weekly_slots'),'activity_type_only':fields.get('content_types')==['activity'],'reminder_intent_exact':fields.get('notifications_enabled',True)==conf.get('notifications',True),'location_exact':fields.get('locations')==['紫金港'],'no_unrequested_fields':not fields.get('skills') and not fields.get('unavailable_slots') and not fields.get('semantic_exclusions') and fields.get('valid_until') is None,'not_saved_before_confirmation':guide.assistance.preferences(u.id)['version']==0,'no_notification_before_confirmation':guide.matching.list(u.id)['total']==0}
   report['preference_checks']=checks;report['model_calls']=calls
   if all(checks.values()):
    guide.assistance.action(r.conversation_id,u.id,assistance['version'],'preferences',0)
    guide.matching.reconcile(u.id)
    items=guide.matching.list(u.id,100)
    report['confirmation']='模拟用户逐字段核对忠实后独立确认；并非Agent自动授权。'
    report['saved_preferences']=guide.assistance.preferences(u.id)
    report['recommendations']=items
    report['target_recommendation']=next((x for x in items['items'] if x['resource_id']==activity['id']),None)
    with app.state.task_service.database.connect() as conn:
     report['opportunity_notifications']=conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(u.id,)).fetchone()[0]
    start=time.monotonic();e=guide.chat(GuideInput(message='请依据我刚确认的偏好，查找并解释这个活动是否适合我、有哪些需要核对的条件，不要替我报名。',conversation_id=r.conversation_id),u)
    report['messages'].append({'turn':2,'user':'请依据我刚确认的偏好，查找并解释这个活动是否适合我、有哪些需要核对的条件，不要替我报名。','answer':e.answer,'run_id':e.run_id,'seconds':round(time.monotonic()-start,3),'trace':guide.runs.read(e.run_id,u.id)})
    report['registration_count']=0;report['status']='collected_pending_human_review'
   else: report['status']='proposal_mismatch_no_confirmation'
  except Exception as exc:
   report.update(status='interrupted_requires_classification',error_type=type(exc).__name__,error=str(exc))
  finally:
   report['model_calls']=calls;save(target/'result.json',report);guide.shutdown()
 save(target/'transcript.json',report['messages'])
 print(json.dumps({'sample_id':sid,'profile':pid,'status':report['status'],'checks':report.get('preference_checks'),'candidate':bool(report.get('target_recommendation'))},ensure_ascii=False))


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sample',choices=sorted(SUPPORTED),required=True);p.add_argument('--directory',type=Path,required=True);a=p.parse_args();run(a.sample,a.directory.resolve())
if __name__=='__main__':main()
