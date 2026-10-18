"""Real-model natural-language planning and annotated semantic-vs-keyword evaluation."""
import argparse
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from uuid import uuid4
from datetime import timedelta

from fastapi.testclient import TestClient
from campus.app import create_app
from campus.guide import model_backend
from campus.schemas import GuideInput,GuideReply
from campus.assistance import AssistanceBuffer,Preferences
from campus.planning_actions import decide
from campus.semantics import profile_source,job_source
from campus.keyword_baseline import rank as keyword_baseline
from .improvement_cases import AT,PLANNING_CASES,ANNOTATED_PROFILES,JOBS,draft


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def planning_check(case,result,before,guide,user,cid):
    a=result.assistance or {};p=a.get('plan') or {};fields=p.get('fields',{});expect=case['expect']
    if expect=='clarify':return not p.get('resource_id') and not fields.get('starts_at') and any(x in result.answer for x in ('时间','地点','内容'))
    review=p.get('review')
    if expect in ('review','accept','reject','stale','headcount'):
        if not review or fields!=before['fields']:return False
        if expect=='review':return bool(review['proposals'] or review['questions'] or review['rechecks'])
        if expect=='headcount':return any(c['code']=='headcount_mismatch' for c in p['checks'])
        if not review['proposals']:return False
        proposal=review['proposals'][0]
        if expect=='stale':
            b=AssistanceBuffer(guide.assistance,cid,user.id);b.plan('volunteer',{'title':'用户在评估后改变了活动目标'})
            with guide.service.database.connect() as c:b.save(c)
            try:decide(guide.assistance,cid,user.id,a['version'],proposal['id'],'accept')
            except Exception as e:return getattr(e,'status_code',None)==409
            return False
        updated=decide(guide.assistance,cid,user.id,a['version'],proposal['id'],'reject' if expect=='reject' else 'accept')
        return updated['plan']['fields']==fields if expect=='reject' else updated['version']>a['version'] and updated['plan']['status']=='draft'
    if expect=='fields':return all(fields.get(k)==v for k,v in case['values'].items())
    if expect=='missing_location':return any('location' in c['path'] for c in p.get('checks',[])) and all(not j.get('location') for j in fields.get('jobs',[]))
    if expect=='end':return fields.get('ends_at') in ('2030-01-05T15:00:00+08:00','2030-01-05T07:00:00+00:00') and fields['jobs']==before['fields']['jobs'] and any(c['code']=='job_outside_activity' for c in p['checks'])
    if expect=='deadline':return any(c['code']=='registration_after_job' for c in p['checks']) and fields['jobs']==before['fields']['jobs']
    if expect=='minutes':return fields['jobs'][0].get('estimated_minutes')==180 and any(c['code']=='service_minutes_exceeded' for c in p['checks'])
    if expect=='rename':return fields['jobs'][0]['name']=='物料整理岗' and p['job_ids'][0]==before['job_ids'][0]
    if expect=='reorder':return [j['name'] for j in fields['jobs']]==['摄影岗','清洁岗'] and p['job_ids']==before['job_ids'][::-1]
    if expect=='add':return len(fields['jobs'])==3 and p['target_volunteers']==22 and fields['jobs'][:2]==before['fields']['jobs']
    if expect=='remove':return len(fields['jobs'])==1 and fields['jobs'][0]['name']=='清洁岗' and p['target_volunteers']==12
    if expect=='clear_contact':return not fields.get('contact') and not p['ready']
    if expect=='clear_target':return p['target_volunteers'] is None and fields['jobs']==before['fields']['jobs']
    if expect=='start':return fields['jobs']==before['fields']['jobs'] and fields.get('starts_at') in ('2030-01-05T13:00:00+08:00','2030-01-05T05:00:00+00:00')
    if expect=='cross_account':
        _,other=guide.test_auth.register('privacy.'+uuid4().hex[:12],'其他账号','Evaluation-Only-2030')
        denied=0
        for operation in (lambda:guide.conversation(cid,other),lambda:guide.runs.read(result.run_id,other.id)):
            try:operation()
            except Exception as exc:denied+=getattr(exc,'status_code',None)==404
        return fields==before['fields'] and denied==2 and guide.assistance.read(cid,other.id) is None
    return False


def run_planning(app,directory,repeats,workers,cases=None,transport='sync'):
    guide=app.state.guide_service;auth=app.state.auth_service;guide.test_auth=auth
    target=directory/'planning-real.json';report=dict(mode='real_model',transport=transport,input_format='natural_language_without_json',repeats=repeats,rows=[])
    work=[]
    for repeat in range(repeats):
        for case in PLANNING_CASES:
            if cases and case['id'] not in cases:continue
            _,user=auth.register('eval.'+uuid4().hex[:16],'规划验收同学','Evaluation-Only-2030')
            work.append((case,repeat,user))
    def one(item):
        case,repeat,user=item;cid=uuid4().hex;before=None
        if case.get('seed',True):
            with guide.service.database.connect() as c:c.execute('INSERT INTO guide_conversations VALUES (?,?,?,?)',(cid,user.id,'[]',AT.isoformat()))
            fields=draft()
            if case.get('remove_location'):
                for job in fields['jobs']:job.pop('location')
            if case.get('mismatch'):
                for job in fields['jobs']:job['capacity']=5
            b=AssistanceBuffer(guide.assistance,cid,user.id);b.plan('volunteer',fields,target_volunteers=20)
            with guide.service.database.connect() as c:b.save(c)
            before=b.read()['plan']
        started=time.monotonic();result=None
        try:
            body=GuideInput(message=case['message'],conversation_id=cid if before else None,purpose='activity_review' if case.get('review') else 'chat',expected_assistance_version=1 if case.get('review') else None)
            if transport=='streaming' or case['expect']=='cancel':
                run_id=guide.start(body,user)['run_id']
                cancellation_requested=False
                while True:
                    observed=guide.runs.read(run_id,user.id)
                    if case['expect']=='cancel' and not cancellation_requested and any(e['kind']=='tool_finished' and e.get('tool')=='update_volunteer_plan' and e.get('success') for e in observed['events']):
                        guide.cancel_run(run_id,user);cancellation_requested=True
                    if case['expect']=='cancel' and observed['status']=='cancelled':
                        current=guide.assistance.read(cid,user.id)
                        preserved=current['version']==1 and current['plan']['fields']==before['fields']
                        return dict(case=case['id'],repeat=repeat+1,passed=cancellation_requested and preserved,
                            seconds=round(time.monotonic()-started,2),message=case['message'],status='cancelled',metrics=observed['metrics'],run_id=run_id,original_draft_preserved=preserved)
                    if observed['status']=='succeeded':result=GuideReply.model_validate(observed['result']);break
                    if observed['status'] in ('failed','cancelled','interrupted'):raise RuntimeError(observed['error'])
                    time.sleep(.2)
            else:result=guide.chat(body,user)
            passed=planning_check(case,result,before,guide,user,cid)
            run=guide.runs.read(result.run_id,user.id)
            return dict(case=case['id'],repeat=repeat+1,passed=passed,seconds=round(time.monotonic()-started,2),message=case['message'],answer=result.answer,assistance=result.assistance,metrics=run['metrics'],run_id=result.run_id)
        except Exception as exc:
            current=guide.assistance.read(cid,user.id) if before else None
            return dict(case=case['id'],repeat=repeat+1,passed=False,seconds=round(time.monotonic()-started,2),error=str(exc),answer=result.answer if result else None,
                        failed_run_preserved_original_draft=bool(current and current['version']==1 and current['plan']['fields']==before['fields']))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(one,x) for x in work]):
            row=future.result();report['rows'].append(row);save(target,report)
            print(json.dumps({k:row.get(k) for k in ('case','repeat','passed','seconds','error')},ensure_ascii=False),flush=True)
    report['summary']=dict(total=len(report['rows']),passed=sum(x['passed'] for x in report['rows']),model_calls=sum(x.get('metrics',{}).get('model_calls',0) for x in report['rows']))
    save(target,report);return report


def run_semantics(app,directory,workers):
    guide=app.state.guide_service;sem=guide.semantics;auth=app.state.auth_service
    _,owner=auth.register('sem.'+uuid4().hex[:16],'语义评测同学','Evaluation-Only-2030')
    profiles=[]
    for i,(text,expected) in enumerate(ANNOTATED_PROFILES):
        fields=Preferences(skills=[text] if i<24 or i>=28 else [],interests=[text] if 24<=i<28 else [],content_types=['volunteer'])
        identifier=f'evaluation-profile-{i}'
        sem.ensure('profile',identifier,owner.id,profile_source(fields.model_dump(mode='json')))
        profiles.append((identifier,fields,expected))
    for c in JOBS:sem.ensure('opportunity',c['job_id'],owner.id,job_source(c))
    context_job=dict(JOBS[8],job_id='context-cleaning',subtitle='清洁岗',job_description='清理现场垃圾并分类收集',activity_description='开展环保清洁行动并由视频岗拍摄宣传片')
    sem.ensure('opportunity',context_job['job_id'],owner.id,job_source(context_job))
    def drain():
        while sem.process_one():pass
    with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(lambda _:drain(),range(workers)))
    rows=[]
    for identifier,profile,expected in profiles:
        with guide.service.database.connect() as conn:
            person=sem.cached(conn,'profile',identifier,profile_source(profile.model_dump(mode='json')))
            parsed={c['job_id']:sem.cached(conn,'opportunity',c['job_id'],job_source(c)) for c in JOBS}
        baseline=[];semantic=[]
        for c in JOBS:
            old=keyword_baseline(profile,c,AT)
            if old:baseline.append((c['job_id'],old['score']))
            if person is not None and parsed[c['job_id']] is not None:
                new=guide.matching.match(profile,c,AT,person,parsed[c['job_id']])
                if new:semantic.append((c['job_id'],new['score']))
        baseline.sort(key=lambda x:-x[1]);semantic.sort(key=lambda x:-x[1])
        relevant=[expected]+(['camera'] if expected=='video' and identifier!='evaluation-profile-28' else [])
        rows.append(dict(profile=profile.model_dump(mode='json'),expected=relevant,baseline_top3=[x[0] for x in baseline[:3]],semantic_top3=[x[0] for x in semantic[:3]],
             parsed=person,baseline_recall=sum(x in [i[0] for i in baseline[:3]] for x in relevant)/len(relevant),semantic_recall=sum(x in [i[0] for i in semantic[:3]] for x in relevant)/len(relevant),
             baseline_precision=sum(x[0] in relevant for x in baseline[:3])/3,semantic_precision=sum(x[0] in relevant for x in semantic[:3])/3,
             explicit_camera_conflict_excluded=not (identifier=='evaluation-profile-28' and 'camera' in [x[0] for x in semantic])))
    by_id={c['job_id']:c for c in JOBS}
    p=profiles[0][1];person=rows[0]['parsed'];video=by_id['video'];camera=by_id['camera']
    outside=p.model_copy(update={'available_slots':Preferences(available_slots=[dict(starts_at='2030-01-05T17:00:00+08:00',ends_at='2030-01-05T18:00:00+08:00')]).available_slots})
    unavailable=p.model_copy(update={'unavailable_slots':Preferences(unavailable_slots=[dict(starts_at=video['starts_at'],ends_at=video['ends_at'])]).unavailable_slots})
    unknown=guide.matching.match(p,camera,AT,person,parsed['camera'])
    with guide.service.database.connect() as conn:context_facts=sem.cached(conn,'opportunity',context_job['job_id'],job_source(context_job))
    constraints=dict(
      outside_available_excluded=guide.matching.match(outside,video,AT,person,parsed['video']) is None,
      explicitly_unavailable_excluded=guide.matching.match(unavailable,video,AT,person,parsed['video']) is None,
      required_equipment_negative_excluded=guide.matching.match(profiles[28][1],camera,AT,rows[28]['parsed'],parsed['camera']) is None,
      full_job_excluded=guide.matching.match(p,dict(video,remaining_capacity=0),AT,person,parsed['video']) is None,
      closed_job_excluded=guide.matching.match(p,dict(video,closes_at=(AT-timedelta(seconds=1)).isoformat()),AT,person,parsed['video']) is None,
      video_does_not_imply_photography=guide.matching.match(p,by_id['photo'],AT,person,parsed['photo']) is None,
      unknown_equipment_flagged=unknown is not None and any('必需条件尚未确认：相机' in c for c in unknown['checks']),
      other_role_skill_not_inherited=context_facts is not None and guide.matching.match(p,context_job,AT,person,context_facts) is None,
      activity_interest_retained=context_facts is not None and guide.matching.match(profiles[24][1],context_job,AT,rows[24]['parsed'],context_facts) is not None)
    report=dict(mode='real_model',annotation_source='Explicit reference labels authored with the evaluation cases; supplied for human review, not external user-study annotations',rows=rows,constraint_checks=constraints,
        summary=dict(cases=len(rows),baseline_recall_at3=sum(r['baseline_recall'] for r in rows)/len(rows),semantic_recall_at3=sum(r['semantic_recall'] for r in rows)/len(rows),
          baseline_precision_at3=sum(r['baseline_precision'] for r in rows)/len(rows),semantic_precision_at3=sum(r['semantic_precision'] for r in rows)/len(rows),
          parsed_profiles=sum(r['parsed'] is not None for r in rows),parsed_jobs=sum(x is not None for x in parsed.values()),explicit_conflicts_excluded=all(r['explicit_camera_conflict_excluded'] for r in rows)))
    report['improved']=all(constraints.values()) and report['summary']['semantic_recall_at3']>report['summary']['baseline_recall_at3'] and report['summary']['semantic_precision_at3']>=report['summary']['baseline_precision_at3']
    save(directory/'semantic-real.json',report);print(json.dumps(report['summary'],ensure_ascii=False),flush=True);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--real-model',action='store_true',required=True)
    parser.add_argument('--suite',choices=['planning','semantic','all'],default='all');parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--directory',type=Path,default=Path('.runtime/evals/agent-improvements'))
    parser.add_argument('--cases',nargs='+',choices=[c['id'] for c in PLANNING_CASES])
    parser.add_argument('--transport',choices=['sync','streaming'],default='sync');args=parser.parse_args()
    if not 1<=args.workers<=3 or args.repeats<1:parser.error('workers 需1–3，repeats需为正整数')
    args.directory.mkdir(parents=True,exist_ok=True)
    app=create_app(args.directory/'evaluation.sqlite3',guide_backend_factory=model_backend,business_clock=lambda:AT,enable_semantics=False)
    with TestClient(app):
        if args.suite in ('semantic','all'):run_semantics(app,args.directory,args.workers)
        if args.suite in ('planning','all'):run_planning(app,args.directory,args.repeats,args.workers,args.cases,args.transport)


if __name__=='__main__':main()
