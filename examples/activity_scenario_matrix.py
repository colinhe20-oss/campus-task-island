"""Run authored synthetic comprehensive-activity cases against native matching.

The synthetic recognition tag exists only to let the matcher service create a
test opportunity. It is not part of the sample's organizer gold or recognition
claim and must never be used as evidence about school credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path

from campus.activity_schemas import ActivityCreate
from campus.app import create_app
from campus.assistance import Preferences
from campus.clock import business_time

ROOT = Path(__file__).resolve().parents[1]


def load(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value): p.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')


def run(sid: str, target: Path):
    if sid not in {'EXP-A01','EXP-A02'}: raise ValueError('Unsupported activity sample: '+sid)
    spec=ROOT/'docs/dataset_samples'/sid
    manifest=load(spec/'manifest.json')
    for name, digest in manifest['files'].items():
        if sha(spec/name)!=digest: raise ValueError('Frozen source hash mismatch: '+name)
    cases=load(spec/'participant_cases.json')
    if target.exists(): raise ValueError('Choose a new output directory')
    target.mkdir(parents=True)
    cfg=cases['native_matrix']
    at=datetime.fromisoformat('2026-10-20T10:00:00+08:00')
    with business_time(lambda:at):
        app=create_app(target/'world.sqlite3',business_clock=lambda:at,enable_semantics=False)
        app.state.task_service.initialize()
        owner=app.state.auth_service.register('matrix-owner','matrix-owner',secrets.token_urlsafe(24))[1]
        def activity_body(title, capacity):
          return ActivityCreate.model_validate({
            'title':title,'description':cfg['description'],'location':cfg['location'],
            'starts_at':f"{cfg['date']}T{cfg['start']}:00+08:00",'ends_at':f"{cfg['date']}T{cfg['end']}:00+08:00",
            'opens_at':cfg['opens_at'],'closes_at':cfg['closes_at'],
            'capacity':capacity,'registration_mode':cfg['mode'],'recognition_tags':[cfg['credited_tag_fixture']],
            'recognition_description':'仅为原生匹配服务构造的测试标签，不代表学校认定；认定未知。',
            'organization_name':cfg['org'],'information_source':cfg['source'],'contact':cfg['contact'],
            'participation_requirements':cfg['requirements']})
        activity=app.state.activity_service.create(activity_body(cfg['title'],cfg['capacity']),owner.id)
        full_activity=app.state.activity_service.create(activity_body(cfg['title']+'（满额对照）',cfg['capacity']),owner.id)
        users={}
        for pid,vector in cfg['profiles'].items():
            interests=vector['interests']; ranges=vector.get('available',[]); notify=vector.get('notifications',True)
            u=app.state.auth_service.register(pid.lower(),pid,secrets.token_urlsafe(24))[1]; users[pid]=u
            prefs={'skills':[],'interests':interests,'locations':['紫金港'],'available_slots':[{'starts_at':f"{cfg['date']}T{s}:00+08:00",'ends_at':f"{cfg['date']}T{e}:00+08:00"} for s,e in ranges], 'weekly_slots':[],'unavailable_slots':[{'starts_at':f"{cfg['date']}T{s}:00+08:00",'ends_at':f"{cfg['date']}T{e}:00+08:00"} for s,e in vector.get('unavailable',[])],'valid_until':None,'content_types':['activity'],'notifications_enabled':notify,'semantic_exclusions':[]}
            app.state.guide_service.assistance.save_preferences(u.id,Preferences.model_validate(prefs).model_dump(mode='json'),0)
        app.state.activity_service.register(activity['id'],users[cfg['registered_profile']].id)
        for i in range(cfg['capacity']):
            u=app.state.auth_service.register(f'fill{i}',f'fill{i}',secrets.token_urlsafe(24))[1]
            app.state.activity_service.register(full_activity['id'],u.id)
        app.state.guide_service.matching.reconcile()
        expected={x['id']:x for x in cases['profiles']}; rows=[]
        for pid,u in users.items():
            items=app.state.guide_service.matching.list(u.id,100)['items']
            target_id=full_activity['id'] if pid==cfg['full_state_profile'] else activity['id']
            item=next((x for x in items if x['resource_id']==target_id),None)
            want=expected[pid]['expected']!='exclude'
            rows.append({'profile':pid,'expected':expected[pid]['expected'],'actual_present':item is not None,'presence_agrees':want==(item is not None),'actual_item':item})
        with app.state.task_service.database.connect() as conn:
            notices={pid:conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(u.id,)).fetchone()[0] for pid,u in users.items()}
        result={'sample_id':sid,'mode':'native_keyword_matching','observation_time':at.isoformat(),'pairs':rows,'pair_count':len(rows),'agreements':sum(x['presence_agrees'] for x in rows),'true_positive':sum(x['expected']!='exclude' and x['actual_present'] for x in rows),'false_positive':sum(x['expected']=='exclude' and x['actual_present'] for x in rows),'false_negative':sum(x['expected']!='exclude' and not x['actual_present'] for x in rows),'notifications_by_profile':notices,'capacity_fixture':f"Open event used except {cfg['full_state_profile']}; separate clone filled to capacity.",'test_only_recognition_tag':cfg['credited_tag_fixture']+'; harness fixture only, not source fact or gold label','semantic_mode':'disabled; keyword fallback explicitly selected','runner_sha256':sha(Path(__file__))}
        result['accuracy']=result['agreements']/len(rows)
        result['precision']=result['true_positive']/(result['true_positive']+result['false_positive']) if result['true_positive']+result['false_positive'] else None
        result['recall']=result['true_positive']/(result['true_positive']+result['false_negative']) if result['true_positive']+result['false_negative'] else None
        save(target/'results.json',result)
        save(target/'inputs.json',{'participant_cases_sha256':sha(spec/'participant_cases.json'),'activity_id':activity['id'],'full_capacity_activity_id':full_activity['id'],'profile_user_ids':{k:v.id for k,v in users.items()}})
    print(json.dumps({k:result[k] for k in ('pair_count','agreements','true_positive','false_positive','false_negative','accuracy','precision','recall')},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',choices=['EXP-A01','EXP-A02'],required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(); run(args.sample,args.directory.resolve())


if __name__=='__main__': main()
