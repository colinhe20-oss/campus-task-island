"""统一变更网页/真实模型验收，全部使用临时数据库与测试账号。"""
import argparse,json,tempfile
from pathlib import Path
from datetime import datetime,timezone
from campus.app import create_app
from campus.schemas import TaskCreate,TASK_CREATE_EXAMPLE,ChangeInput,ExtensionReviewInput,StagePlanInput
from campus.db import Database
from campus.service import TaskService
from campus.auth import AuthService

BASE=datetime(2030,1,1,tzinfo=timezone.utc)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--real',action='store_true');parser.add_argument('--port',type=int,default=8001);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-changes-') as temp:
        root=Path(temp);db=Database(root/'campus.sqlite3');service=TaskService(db,lambda:BASE);service.initialize()
        auth=AuthService(db);auth.provision_demo_accounts()
        accounts=json.loads(auth.accounts_path.read_text('utf-8'));users={name:auth.login(name,accounts[name]['password'])[1] for name in accounts}
        owner,helper=users['publisher'].id,users['helper'].id
        task=service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'【变更验收】校园摄影','deadline':'2030-01-03T18:00:00+08:00'}),owner)
        stages=service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'【阶段变更验收】海报协作','deadline':'2030-01-03T18:00:00+08:00'}),owner)
        from campus.stages import StageService
        StageService(service).set_plan(stages.id,owner,StagePlanInput(expected_version=0,stages=[dict(title='初稿',completion_criteria='交付海报初稿',deadline='2030-01-02T18:00:00+08:00',responsible_role='assignee'),dict(title='定稿',completion_criteria='交付海报定稿',deadline='2030-01-03T18:00:00+08:00',responsible_role='assignee')]))
        for t in (task,stages):
            application=service.apply(t.id,helper,'可以协作');service.accept_application(application.id,owner)
        app=create_app(db.path,task_clock=lambda:BASE)
        if args.real:
            from fastapi.testclient import TestClient
            results=[]
            with TestClient(app) as client:
                client.post('/api/auth/login',json={'username':'publisher','password':accounts['publisher']['password']})
                proposal=service.terms.changes.propose(task.id,helper,ChangeInput(version=1,reason='协商回报',changes={'reward':{'reward_type':'paid','reward_amount_fen':2550,'reward':'线下支付全额'}}))['items'][0]
                for state in ('pending','approved'):
                    if state=='approved':service.terms.changes.decide(proposal['id'],owner,ExtensionReviewInput(version=1,decision='approve'))
                    response=client.post('/api/guide/chat',json={'task_id':task.id,'message':f'请实际读取任务 {task.id} 的最新详情，分别说明当前已生效回报、约定版本，以及变更申请的处理结果。待处理提案是否已经生效？请简洁回答，不修改任何数据。'})
                    body=response.json();answer=body.get('answer','')
                    checks={'ok':response.status_code==200,'model':body.get('mode')=='model','read':any(t['name']=='get_task_detail' for t in body.get('tools_used',[]))}
                    checks['distinguishes']=any(s in answer for s in ('未生效','尚未生效','未通过','确认前','无偿')) if state=='pending' else any(s in answer for s in ('25.50','25.5','2550')) and any(s in answer for s in ('生效','通过','有偿'))
                    results.append(dict(scenario=state,passed=all(checks.values()),checks=checks,answer=answer,error=body.get('detail')))
                    print(json.dumps(dict(scenario=state,checks=checks),ensure_ascii=False),flush=True)
            report=Path('.runtime/evals/changes-real-latest.json');report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(dict(passed=all(r['passed'] for r in results),scenarios=results),ensure_ascii=False,indent=2),'utf-8')
            if not all(r['passed'] for r in results):raise SystemExit('真实模型场景未通过，见报告')
        else:
            manifest=dict(database=str(db.path),accounts=str(auth.accounts_path),task_id=task.id,staged_task_id=stages.id,base_url=f'http://127.0.0.1:{args.port}')
            Path('.runtime/changes-demo.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
            print(json.dumps(manifest,ensure_ascii=False),flush=True)
            import uvicorn
            uvicorn.run(app,host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
