"""普通任务接取规则验收：临时数据库、网页演示与真实模型草稿。"""
import argparse,json,tempfile
from pathlib import Path
from datetime import datetime,timezone
from fastapi.testclient import TestClient
from campus.app import create_app
from campus.db import Database
from campus.auth import AuthService
from campus.schemas import TaskCreate,TASK_CREATE_EXAMPLE
from campus.service import TaskService

RULES=dict(reason='disabled',experience='required',supplement='optional')

def real_check():
    results=[]
    with tempfile.TemporaryDirectory(prefix='acceptance-real-') as temp:
        app=create_app(Path(temp)/'campus.sqlite3')
        with TestClient(app) as client:
            accounts=json.loads(app.state.auth_service.accounts_path.read_text('utf-8'))
            client.post('/api/auth/login',json=dict(username='publisher',password=accounts['publisher']['password']))
            cases=[('direct','我要发布普通任务：社团活动摄影，分类 creative，找一位同学拍摄活动，完成标准交付10张照片，地点学生活动中心，截止2030年10月20日北京时间18点，互助。使用直接接取，不收申请理由，技能经验必填，补充说明选填。'),('clarify','我想发布一个普通摄影任务，但还没决定是让同学直接接取还是先申请由我选择。也没想好技能经验要选填还是必填，请先问我确认这两项，再整理草稿。')]
            for name,message in cases:
                response=client.post('/api/guide/chat',json={'message':message});body=response.json()
                checks={'http_ok':response.status_code==200,'real_model':body.get('mode')=='model'}
                if name=='direct':
                    draft=body.get('draft') or {};fields=draft.get('fields',{})
                    checks.update(ready=draft.get('ready') is True,mode=fields.get('acceptance_mode')=='direct',rules=fields.get('application_requirements')==RULES)
                    if all(checks.values()):
                        published=client.post('/api/guide/drafts/'+body['conversation_id']+'/publish',json={'version':draft['version']}).json()
                        identifier=published['draft']['published_task_id'];task=client.get('/api/tasks/'+identifier).json()
                        checks['confirmed_publish']=task['acceptance_mode']=='direct' and task['application_requirements']==RULES
                else:
                    checks['clarification']='？' in body.get('answer','') or '?' in body.get('answer','')
                results.append(dict(scenario=name,checks=checks,passed=all(checks.values()),answer=body.get('answer'),tools=body.get('tools_used'),http_status=response.status_code,error=body.get('detail')))
                print(json.dumps({'scenario':name,'checks':checks},ensure_ascii=False),flush=True)
    output=Path('.runtime/evals/acceptance-real-latest.json');output.parent.mkdir(exist_ok=True,parents=True)
    output.write_text(json.dumps(dict(checked_at=datetime.now(timezone.utc).isoformat(),passed=all(r['passed'] for r in results),scenarios=results),ensure_ascii=False,indent=2),'utf-8')
    if not all(r['passed'] for r in results):raise SystemExit('真实模型验收未通过，见报告')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--real',action='store_true');p.add_argument('--port',type=int,default=8001);args=p.parse_args()
    if args.real:return real_check()
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='acceptance-web-') as temp:
        db=Database(Path(temp)/'campus.sqlite3');db.initialize();auth=AuthService(db);auth.provision_demo_accounts()
        with db.connect() as c:owner=c.execute("SELECT id FROM users WHERE username='publisher'").fetchone()[0]
        service=TaskService(db)
        tasks={}
        for mode in ('direct','approval'):
            task=service.create_task(TaskCreate(**{**TASK_CREATE_EXAMPLE,'title':('直接接取' if mode=='direct' else '申请确认')+'：摄影协作验收','acceptance_mode':mode,'application_requirements':RULES}),owner);tasks[mode]=task.id
        Path('.runtime/acceptance-demo.json').write_text(json.dumps(dict(database=str(db.path),accounts_path=str(auth.accounts_path),tasks=tasks),ensure_ascii=False,indent=2),'utf-8')
        print('临时验收信息：.runtime/acceptance-demo.json',flush=True)
        uvicorn.run(create_app(db.path),host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
