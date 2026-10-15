"""任务时间与结算验收：临时库和可控时钟，--real 运行真实模型场景。"""
import argparse,json,tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from campus.app import create_app
from campus.db import Database
from campus.auth import AuthService
from campus.service import TaskService
from campus.schemas import TaskCreate,TASK_CREATE_EXAMPLE

BASE=datetime(2030,1,1,tzinfo=timezone.utc)
def real_check(only=None):
    from unittest.mock import patch
    from agent.loop import AgentLoop
    original=AgentLoop._emit
    def traced(loop,kind,**data):
        if kind=='tool_finished' and not data.get('success'):
            print(json.dumps({'tool_error':str(data.get('result',''))[:1000]},ensure_ascii=False),flush=True)
        return original(loop,kind,**data)
    current=[BASE];results=[]
    with patch.object(AgentLoop,'_emit',traced), tempfile.TemporaryDirectory(prefix='terms-real-') as temp:
        app=create_app(Path(temp)/'campus.sqlite3',task_clock=lambda:current[0])
        with TestClient(app) as client:
            accounts=json.loads(app.state.auth_service.accounts_path.read_text('utf-8'))
            client.post('/api/auth/login',json=dict(username='publisher',password=accounts['publisher']['password']))
            messages=[('ask_reward','我要发布普通创作任务：找同学拍校园照片，地点图书馆，截止2030年1月2日北京时间18点，完成标准交付10张清晰照片。我还没有说明回报方式，请先问我确认回报类型。'),('paid_draft','请整理普通任务草稿：标题校园摄影，分类creative，需求拍校园照片，标准交付10张照片，地点图书馆，截止2030-01-02T18:00:00+08:00。有偿paid，25.50元，说明验收后线下支付全额。其余采用默认接取规则。请用工具保存并简洁回复。')]
            for name,message in messages:
                if only and name!=only:continue
                response=client.post('/api/guide/chat',json={'message':message});body=response.json();draft=body.get('draft')
                checks=dict(http_ok=response.status_code==200,real_model=body.get('mode')=='model')
                if name=='ask_reward':
                    checks['asked_reward']=any(word in body.get('answer','') for word in ('回报','有偿','报酬','无偿'))
                    checks['not_ready']=not (draft and draft['ready'])
                else:
                    fields=(draft or {}).get('fields',{})
                    checks['paid_exact_amount']=fields.get('reward_type')=='paid' and fields.get('reward_amount_fen')==2550
                    checks['ready']=bool(draft and draft['ready'])
                    if checks['ready']:
                        current[0]=BASE+timedelta(days=3)
                        expired=client.post('/api/guide/drafts/'+body['conversation_id']+'/publish',json={'version':draft['version']})
                        checks['expired_publish_rejected']=expired.status_code==409
                        current[0]=BASE
                        published=client.post('/api/guide/drafts/'+body['conversation_id']+'/publish',json={'version':draft['version']})
                        checks['confirmed_publish']=published.status_code==200
                results.append(dict(scenario=name,passed=all(checks.values()),checks=checks,answer=body.get('answer'),error=body.get('detail')))
                print(json.dumps(dict(scenario=name,checks=checks),ensure_ascii=False),flush=True)
    output=Path('.runtime/evals/terms-real-latest.json');output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(passed=all(r['passed'] for r in results),scenarios=results),ensure_ascii=False,indent=2),'utf-8')
    if not all(r['passed'] for r in results):raise SystemExit('真实模型场景未通过，见报告')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--real',action='store_true');parser.add_argument('--case',choices=['ask_reward','paid_draft']);parser.add_argument('--port',type=int,default=8001);args=parser.parse_args()
    if args.real:return real_check(args.case)
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='terms-web-') as temp:
        root=Path(temp);clock_file=root/'clock.json';clock_file.write_text(json.dumps({'now':BASE.isoformat()}),'utf-8')
        def clock():return datetime.fromisoformat(json.loads(clock_file.read_text('utf-8'))['now'])
        db=Database(root/'campus.sqlite3');db.initialize();auth=AuthService(db);auth.provision_demo_accounts()
        with db.connect() as c:owner=c.execute("SELECT id FROM users WHERE username='publisher'").fetchone()[0]
        task=TaskService(db,clock).create_task(TaskCreate(**{**TASK_CREATE_EXAMPLE,'title':'截止与结算网页验收','deadline':(BASE+timedelta(hours=1)).isoformat(),'reward_type':'paid','reward_amount_fen':2550,'reward':'验收完成后线下支付人民币25.50元'}),owner)
        Path('.runtime/terms-demo.json').write_text(json.dumps(dict(database=str(db.path),accounts_path=str(auth.accounts_path),clock_path=str(clock_file),task_id=task.id),ensure_ascii=False,indent=2),'utf-8')
        print('临时验收信息：.runtime/terms-demo.json',flush=True)
        uvicorn.run(create_app(db.path,task_clock=clock),host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
