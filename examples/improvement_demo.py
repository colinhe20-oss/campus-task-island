"""Isolated, repeatable same-event demo using the configured real model.

Explicit form actions below represent the organizer's confirmations. They are
recorded separately from model proposals; no model can publish or register.
"""
import argparse
import copy
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from campus.app import create_app
from campus.guide import model_backend
from campus.schemas import GuideInput,GuideReply
from campus.assistance import Preferences
from .improvement_cases import AT,draft
from .improvement_eval import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-model',action='store_true',required=True)
    parser.add_argument('--directory',type=Path,default=Path('.runtime/evals/agent-improvements/demo'))
    parser.add_argument('--resume',action='store_true',help='从已有未发布草稿恢复，保留失败运行')
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    report=json.loads((args.directory/'demo-real.json').read_text(encoding='utf-8')) if args.resume else dict(mode='real_model',steps=[],human_form_submissions=0)
    database=Path(report.get('database_path',str(args.directory/'demo.sqlite3'))) if args.resume else args.directory/('demo-'+uuid4().hex[:12]+'.sqlite3')
    report['database_path']=str(database)
    app=create_app(database,business_clock=lambda:AT,guide_backend_factory=model_backend,enable_semantics=False)
    started=time.monotonic()
    with TestClient(app) as client:
        guide=app.state.guide_service;auth=app.state.auth_service
        if args.resume:
            cid=report['steps'][0]['value']['conversation_id']
            with guide.service.database.connect() as conn:
                username=conn.execute('SELECT u.username FROM guide_conversations c JOIN users u ON u.id=c.user_id WHERE c.id=?',(cid,)).fetchone()[0]
            token,organizer=auth.login(username,'Demo-Only-2030')
        else:token,organizer=auth.register('demo.o.'+uuid4().hex[:12],'演示组织者','Demo-Only-2030')
        client.cookies.set('campus_session',token)
        def record(name,value):
            report['steps'].append(dict(name=name,value=value));save(args.directory/'demo-real.json',report)
            print(name,flush=True)
        def request(method,path,data):
            response=client.request(method,path,json=data)
            if response.status_code>=400:raise RuntimeError(response.text)
            return response.json()
        def edit(a,fields,**metadata):
            report['human_form_submissions']+=1
            return request('PUT',f"/api/guide/assistance/{a['conversation_id']}/plan",dict(version=a['version'],fields=fields,**metadata))

        def ask(body):
            run=guide.start(body,organizer)
            while True:
                row=guide.runs.read(run['run_id'],organizer.id)
                if row['status']=='succeeded':return GuideReply.model_validate(row['result'])
                if row['status'] in ('failed','cancelled','interrupted'):
                    report.setdefault('failed_runs',[]).append(dict(run_id=run['run_id'],error=row['error']))
                    save(args.directory/'demo-real.json',report)
                    raise RuntimeError(row['error'])
                time.sleep(.2)

        if args.resume:
            a=guide.assistance.read(cid,organizer.id)
            if a['plan']['status']!='draft':raise RuntimeError('该演示已结束，请不带 --resume 启动新的隔离演示')
        else:
            result=ask(GuideInput(message='想组织校园环保志愿服务，同时拍一段短视频宣传。请先把已知构想保存为草稿，未知时间地点和岗位人数先不要替我决定。'))
            a=result.assistance;cid=result.conversation_id;record('模糊构想转为未发布草稿',a)
            fields=draft();fields.pop('jobs')
            fields['description']='清理校园垃圾并拍摄环保短视频；需要清洁与视频记录两类分工。'
            a=edit(a,fields,target_volunteers=20)
            record('用户表单确认时间地点及20名志愿者',a)
        review=ask(GuideInput(message='请提出一个可采纳的完整岗位方案，包含清洁岗与视频记录岗。岗位人数合计二十人，时段均为活动14点到16点，地点紫金港活动中心，预计120分钟，按实际服务核验。视频岗需要会拍视频并自备相机，集合点与培训尚未确认。至少一项建议 fields 包含完整 jobs 列表，等待我采纳。',conversation_id=cid,purpose='activity_review',expected_assistance_version=a['version']))
        a=review.assistance;record('真实模型提出有依据的岗位方案',a)
        proposal=next((p for p in a['plan']['review']['proposals'] if p['fields'].get('jobs')),None)
        if not proposal:raise RuntimeError('模型没有生成可演示的岗位方案；保留本次结果供检查')
        edited=copy.deepcopy(proposal['fields'])
        for j in edited['jobs']:
            if '视频' in j['name']:j['requirements']='需要会拍视频，必须自备相机；集合点与培训待确认'
        report['human_proposal_edits']=1
        a=request('POST',f"/api/guide/assistance/{cid}/proposals/{proposal['id']}",dict(version=a['version'],decision='accept',fields=edited))
        record('用户逐条采纳到草稿而非发布',a)
        jobs=copy.deepcopy(a['plan']['fields']['jobs'])
        fields=copy.deepcopy(a['plan']['fields']);fields['ends_at']='2030-01-05T15:00:00+08:00'
        a=edit(a,fields,job_ids=a['plan']['job_ids'])
        assert a['plan']['fields']['jobs']==jobs
        assert any(c['code']=='job_outside_activity' for c in a['plan']['checks'])
        record('活动提前结束并显示确定影响，岗位未静默平移',a)
        impact=ask(GuideInput(message='请解释刚才活动提前结束的影响，列出集合、培训和设备需复核的事项。不要改草稿字段。',purpose='activity_review',conversation_id=cid,expected_assistance_version=a['version']))
        a=impact.assistance;record('AI提出关联筹备事项复核',a)
        fields=copy.deepcopy(a['plan']['fields'])
        for j in fields['jobs']:
            j['ends_at']='2030-01-05T15:00:00+08:00';j['estimated_minutes']=60
            j['estimated_hours_description']='按实际服务时长核验，预计60分钟。'
            for key in ('description','requirements'):
                j[key]=j[key].replace('120分钟','60分钟').replace('14:00–16:00','14:00–15:00').replace('14:00-16:00','14:00-15:00')
        a=edit(a,fields,job_ids=a['plan']['job_ids'])
        assert a['plan']['ready'],a['plan']['checks']
        a=request('POST',f'/api/guide/assistance/{cid}/publish',dict(version=a['version']))
        record('用户独立确认正式发布',a)
        token,participant=auth.register('demo.p.'+uuid4().hex[:12],'演示参与者','Demo-Only-2030');client.cookies.set('campus_session',token)
        preferences=Preferences(skills=['拍过社团宣传片'],available_slots=[dict(starts_at='2030-01-05T14:00:00+08:00',ends_at='2030-01-05T16:00:00+08:00')],content_types=['volunteer'],notifications_enabled=True)
        record('参与者明确保存原始偏好',request('PUT','/api/guide/preferences',dict(version=0,fields=preferences.model_dump(mode='json'))))
        guide.semantics.sync_sources()
        while True:
            if guide.semantics.process_one():continue
            with guide.service.database.connect() as conn:
                pending=conn.execute("SELECT MIN(next_attempt) FROM semantic_jobs WHERE status IN ('queued','retry')").fetchone()[0]
            if pending is None:break
            time.sleep(max(.2,min(2,pending-time.time())))
        guide.matching.reconcile(participant.id)
        recommendations=guide.matching.list(participant.id)
        assert recommendations['items'],'未生成推荐，保留实际模型输出'
        item=next(i for i in recommendations['items'] if i['semantic_evidence'] and any(e['tag']=='video_shooting' for e in i['semantic_evidence']))
        assert any('必需条件尚未确认：相机' in check for check in item['checks']),'未知器材须列为待核对'
        record('不同措辞技能命中真实岗位，设备待确认',item)
        with guide.service.database.connect() as conn:
            before=conn.execute('SELECT SUM(attempts) FROM semantic_jobs').fetchone()[0]
        for _ in range(3):guide.semantics.sync_sources();guide.matching.reconcile(participant.id)
        with guide.service.database.connect() as conn:
            after=conn.execute('SELECT SUM(attempts) FROM semantic_jobs').fetchone()[0]
            notifications=conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(participant.id,)).fetchone()[0]
            runs=[dict(r) for r in conn.execute('SELECT id,status,metrics FROM guide_runs')]
        report.update(passed=True,seconds=round(time.monotonic()-started,2),semantic_calls=before,repeat_scan_extra_calls=after-before,opportunity_notifications=notifications,
                      model_calls=sum(json.loads(r['metrics']).get('model_calls',0) for r in runs),runs=runs)
        assert after==before and notifications==1
        save(args.directory/'demo-real.json',report)
        print(json.dumps({k:v for k,v in report.items() if k not in ('steps','runs')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
