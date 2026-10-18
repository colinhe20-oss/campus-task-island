"""End-to-end proposal acceptance, isolated data. --real-model uses configured LLM."""
import argparse
import json
import tempfile
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path

from fastapi.testclient import TestClient
from campus.app import create_app
from campus.guide import model_backend
from backend.fake_backend import FakeBackend


def payload(at):
    stamp=lambda h:(at+timedelta(hours=h)).isoformat()
    return dict(title='校园环保公益摄影志愿活动',description='记录校园环保公益行动，招募摄影志愿者',organization_name='演示公益社团',
        information_source='演示社团公告',contact='站内联系负责人',recognition_conditions='完成岗位工作后由活动方核验实际服务分钟',
        starts_at=stamp(48),ends_at=stamp(51),opens_at=stamp(-1),closes_at=stamp(24),registration_mode='direct',
        jobs=[dict(name='摄影岗',description='拍摄公益活动现场',requirements='能使用相机并按时到场，设备请与负责人核对',location='紫金港活动中心',
            starts_at=stamp(48),ends_at=stamp(51),capacity=3,estimated_minutes=180,estimated_hours_description='以实际服务及活动方核验为准')])


def run(real=False,output=None,directory=None):
    at=datetime.now(timezone.utc).replace(microsecond=0)
    backend= model_backend if real else lambda:FakeBackend([{'content':'请核对卡片。'}])
    report={'mode':'real_model' if real else 'scripted_tools','at':at.isoformat(),'checks':[]}
    target=Path(output or ('.runtime/evals/proposal-real-latest.json' if real else '.runtime/evals/proposal-offline-latest.json'))
    def check(name,condition,detail=None):
        report['checks'].append(dict(name=name,passed=bool(condition),detail=detail))
        if not condition:
            report['passed']=False
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            raise AssertionError(name+': '+str(detail))
    with tempfile.TemporaryDirectory() if directory is None else _directory(directory) as folder:
        app=create_app(Path(folder)/'proposal.sqlite3',guide_backend_factory=backend)
        with TestClient(app) as client:
            guide=app.state.guide_service
            accounts=json.loads(app.state.auth_service.accounts_path.read_text(encoding='utf-8'))
            users={name:app.state.auth_service.login(name,account['password']) for name,account in accounts.items()}
            def login(name):client.cookies.set('campus_session',users[name][0])
            def chat(message,calls=None,cid=None):
                if not real:
                    guide.backend_factory=lambda:FakeBackend([*(calls or []),{'content':'请核对方案与偏好，报名状态以真实记录为准。'}])
                started=time.monotonic()
                response=client.post('/api/guide/chat',json={'message':message,**({'conversation_id':cid} if cid else {})})
                check('对话完成',response.status_code==200,{'status':response.status_code,'seconds':round(time.monotonic()-started,2)})
                return response.json()
            def call(name,args):return {'content':'','tool_calls':[{'name':name,'arguments':args}]}
            login('publisher')
            vague=chat('周末想组织一次志愿活动，但具体内容、地点和时间还没定，请帮我明确关键问题。',
                       [call('update_volunteer_plan',{'fields':{'title':'周末志愿活动'}})])
            check('模糊需求不会发布',not vague.get('assistance',{}).get('plan',{}).get('resource_id') if vague.get('assistance',{}).get('plan') else True)
            if real:check('模糊需求提出澄清',any(word in vague['answer'] for word in ['时间','地点','内容','服务']))
            fields=payload(at)
            organized=chat('现在确定为志愿服务。下面全部是我确认的信息，请逐项保存在志愿活动草稿，形成筹备清单；不要发布。'+json.dumps(fields,ensure_ascii=False),
                           [call('update_volunteer_plan',{'fields':fields,'checklist':['核对场地与设备','确认岗位人员','活动后核验服务记录']})],vague['conversation_id'])
            plan=organized.get('assistance',{}).get('plan') or {}
            check('完整多岗位方案可核对',plan.get('ready'),plan.get('issues'))
            check('关键字段忠实保留',plan['fields']==fields)
            check('生成筹备清单',bool(plan.get('checklist')))
            login('helper')
            prefs=dict(skills=['摄影'],interests=['环保','公益'],locations=['紫金港'],notifications_enabled=True,
                       available_slots=[dict(starts_at=fields['starts_at'],ends_at=fields['ends_at'])])
            preferred=chat('请登记这些本人偏好为待核对草稿：我会摄影，兴趣环保、公益，优先紫金港，以下是一次性空闲时间。我希望保存后持续关注新活动并通过站内消息提醒。'+json.dumps(prefs,ensure_ascii=False),
                           [call('propose_preferences',{'changes':prefs})])
            proposal=preferred.get('assistance',{}).get('preference_proposal')
            check('偏好需本人确认',proposal is not None and guide.assistance.preferences(users['helper'][1].id)['version']==0)
            a=preferred['assistance']
            confirmed=client.post(f"/api/guide/assistance/{a['conversation_id']}/preferences",json={'version':a['version'],'profile_version':0})
            check('确认偏好',confirmed.status_code==200)
            login('publisher');a=organized['assistance']
            published=client.post(f"/api/guide/assistance/{a['conversation_id']}/publish",json={'version':a['version']})
            check('负责人确认发布',published.status_code==200,published.text if published.status_code!=200 else None)
            activity_id=published.json()['plan']['resource_id']
            login('helper')
            recommended=client.get('/api/guide/recommendations').json()['items']
            check('新活动主动匹配',any(r['resource_id']==activity_id for r in recommended))
            with guide.service.database.connect() as conn:
                notices=conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(users['helper'][1].id,)).fetchone()[0]
            check('主动触达站内消息',notices>0)
            explained=chat('请根据我已保存的偏好，查询并解释适合我的机会，包括待核对的参与条件。',[call('get_recommendations',{})],preferred['conversation_id'])
            check('推荐调用真实匹配工具',any(t['name']=='get_recommendations' and t['success'] for t in explained['tools_used']))
            activity=app.state.volunteer_service.detail(activity_id,users['helper'][1].id)
            registration=client.post('/api/volunteer-jobs/'+activity['jobs'][0]['id']+'/registrations',json={'application_note':'演示账号可以按时参与'})
            check('参与者自主报名',registration.status_code in (200,201),registration.text[:200])
            queried=chat('我刚才报名了，请查询我的志愿报名实际状态。',[call('get_my_volunteer_registrations',{})],preferred['conversation_id'])
            check('查询真实报名记录',any(t['name']=='get_my_volunteer_registrations' and t['success'] for t in queried['tools_used']))
            if real:check('正确解释直接报名成功',any(word in queried['answer'] for word in ['报名成功','已报名','registered','已成功报名']))
            events=guide.runs.read(organized['run_id'],users['publisher'][1].id)['events']
            check('调用轨迹具有时间与工具ID',any(e.get('call_id') and e.get('at') for e in events))
            login('publisher')
            activity_fields={k:fields[k] for k in ('title','description','organization_name','information_source','contact','starts_at','ends_at','opens_at','closes_at','registration_mode')}
            activity_fields.update(title='校园环保摄影美育工作坊',location='紫金港活动中心',capacity=12,recognition_tags=['aesthetic'],recognition_description='由活动方公布，学校正式认定另行核验',participation_requirements='本校学生，自备拍摄设备')
            alternate=chat('我还要组织一场独立的综素活动。请按以下本人已确认字段整理综素活动方案，生成筹备清单，不要发布。'+json.dumps(activity_fields,ensure_ascii=False),[call('update_activity_plan',{'fields':activity_fields,'checklist':['核对场地与认定说明','发布招募通知']})])
            alternate_plan=alternate.get('assistance',{}).get('plan') or {}
            check('综素活动独立方案完整且忠实',alternate_plan.get('ready') and alternate_plan.get('fields')==activity_fields)
            check('综素活动使用对应工具',any(t['name']=='update_activity_plan' and t['success'] for t in alternate['tools_used']))
            report['sample_answers']={'clarification':vague['answer'],'planning':organized['answer'],'recommendation':explained['answer'],'registration':queried['answer']}
            report['plan']=plan
            report['counts']={'checks':len(report['checks']),'passed':sum(c['passed'] for c in report['checks'])}
    report['passed']=all(c['passed'] for c in report['checks'])
    target=Path(output or ('.runtime/evals/proposal-real-latest.json' if real else '.runtime/evals/proposal-offline-latest.json'))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':report['counts'],'report':str(target)},ensure_ascii=False))
    return report


class _directory:
    def __init__(self,path):self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True)
    def __enter__(self):return str(self.path)
    def __exit__(self,*args):pass


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--real-model',action='store_true');parser.add_argument('--output');parser.add_argument('--directory')
    args=parser.parse_args();run(args.real_model,args.output,args.directory)
