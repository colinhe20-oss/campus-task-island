"""临时数据库阶段闭环验收；--real 调用真实模型，默认离线。"""
import argparse
import json
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path

from fastapi.testclient import TestClient
from backend.fake_backend import FakeBackend
from campus.app import create_app
from campus.schemas import TASK_CREATE_EXAMPLE


STAGES=[{'title':title,'completion_criteria':criteria,'deadline':deadline,'responsible_role':'assignee'}
    for title,criteria,deadline in [
        ('需求确认','确认拍摄范围与交付10张清晰照片的要求','2099-10-18T18:00:00+08:00'),
        ('拍摄与整理','拍摄并整理符合要求的照片','2099-10-19T18:00:00+08:00'),
        ('交付验收','提交10张清晰照片供发布者确认','2099-10-20T18:00:00+08:00')]]


def check(real=False):
    report={'mode':'real-model' if real else 'offline-scripted','passed':False,'checks':[],'runs':[],'suggestions':[],'created_at':datetime.now(timezone.utc).isoformat()}
    def require(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    try:
        with tempfile.TemporaryDirectory(prefix='campus-stage-check-') as tmp:
            app=create_app(Path(tmp)/'tasks.sqlite3',guide_backend_factory=None if real else FakeBackend)
            with TestClient(app) as client:
                accounts=json.loads(app.state.auth_service.accounts_path.read_text(encoding='utf-8'))
                users={name:app.state.auth_service.login(name,data['password']) for name,data in accounts.items()}
                def login(name):client.cookies.set('campus_session',users[name][0])
                login('publisher')
                response=client.post('/api/tasks',json=TASK_CREATE_EXAMPLE)
                require(response.status_code==201,'创建合成任务')
                task_id=response.json()['id'];path=f'/api/tasks/{task_id}/stages'
                def suggest(message,fields,conversation_id=None):
                    if not real:
                        app.state.guide_service.backend_factory=lambda:FakeBackend([
                            {'tool_calls':[{'name':'get_task_detail','arguments':{'task_id':task_id}}]},
                            {'tool_calls':[{'name':'propose_task_stages','arguments':{'stages':fields}}]},
                            {'content':'请核对阶段安排后确认'}])
                    response=client.post('/api/guide/runs',json={'purpose':'stage_plan','task_id':task_id,'message':message,'conversation_id':conversation_id})
                    require(response.status_code==202,'阶段建议运行被接受')
                    run_id=response.json()['run_id'];deadline=time.monotonic()+90
                    while time.monotonic()<deadline:
                        run=client.get('/api/guide/runs/'+run_id).json()
                        if run['status'] not in ('running','cancelling'):break
                        time.sleep(.05)
                    report['runs'].append({k:run[k] for k in ('id','status','model','duration_ms','metrics')})
                    require(run['status']=='succeeded','AI 实际完成结构化建议')
                    reply=run['result'];proposal=reply['stage_suggestion']
                    require(proposal is not None,'返回结构化阶段卡片')
                    require('propose_task_stages' in [t['name'] for t in reply['tools_used']],'实际调用阶段建议工具')
                    require(client.get(path).json()['plan_version']==0,'建议未自行生效')
                    report['suggestions'].append(proposal)
                    return reply,proposal
                first,proposal=suggest('请只安排三个阶段：需求确认、拍摄与整理、交付验收，全部由接取者负责。截止时间分别为2026年10月18日18点、19日18点、20日18点北京时间。按原任务完成标准拆分，不增加额外交付要求。',STAGES)
                require(len(proposal['stages'])==3,'按明确要求拆为三个阶段')
                require(all(s['responsible_role']=='assignee' for s in proposal['stages']),'负责人符合用户要求')
                require([datetime.fromisoformat(s['deadline']) for s in proposal['stages']]==[datetime.fromisoformat(s['deadline']) for s in STAGES],'三个阶段日期符合用户要求')
                edited=[STAGES[0],STAGES[1]|{'deadline':'2099-10-19T20:00:00+08:00'},STAGES[2]]
                _,proposal=suggest('把第二阶段截止时间改为2026年10月19日20点北京时间；保持三个阶段以及其他截止时间和负责人不变。仍只生成建议，不确认安排。',edited,first['conversation_id'])
                require(len(proposal['stages'])==3,'多轮调整保留三个阶段')
                require(datetime.fromisoformat(proposal['stages'][1]['deadline'])==datetime.fromisoformat('2099-10-19T20:00:00+08:00'),'多轮修改阶段截止时间生效')
                require([datetime.fromisoformat(proposal['stages'][i]['deadline']) for i in (0,2)]==[datetime.fromisoformat(STAGES[i]['deadline']) for i in (0,2)],'修改没有改变其他阶段时间')
                response=client.post(path,json={'expected_version':0,'suggestion_id':proposal['id'],'stages':proposal['stages']})
                require(response.status_code==200,'发布者明确确认阶段安排')
                approved=response.json()
                login('helper');application=client.post(f'/api/tasks/{task_id}/applications',json={'reason':'可以完成摄影'}).json()['id']
                login('publisher');require(client.post('/api/applications/'+application+'/accept').status_code==200,'接受协作成员')
                owner_panel=client.get(path).json()
                login('helper');require(client.get(path).json()['stages']==owner_panel['stages'],'双方读取同一份共享安排')
                def action(index,name,**body):
                    stage=client.get(path).json()['stages'][index]
                    response=client.post(path+'/'+stage['id']+'/'+name,json={'version':stage['version'],**body})
                    require(response.status_code==200,'阶段'+str(index+1)+' '+name)
                next_stage=approved['stages'][1]
                require(client.post(path+'/'+next_stage['id']+'/start',json={'version':1}).status_code==409,'拒绝跳过前置阶段')
                action(0,'start');action(0,'submissions',summary='已确认拍摄要求')
                login('publisher');action(0,'review',decision='request_changes',feedback='请补充拍摄范围确认')
                login('helper');action(0,'start');action(0,'submissions',summary='已补充范围确认')
                login('publisher');action(0,'review',decision='accept')
                require(client.get(f'/api/tasks/{task_id}').json()['status']=='in_progress','中间阶段确认不提前完成任务')
                for index in (1,2):
                    login('helper');action(index,'start');action(index,'submissions',summary='已按本阶段要求完成')
                    login('publisher');action(index,'review',decision='accept')
                require(client.get(f'/api/tasks/{task_id}').json()['status']=='completed','最后阶段确认后整项任务完成')
                panel=client.get(path).json()
                require(all(s['status']=='confirmed' for s in panel['stages']),'三个阶段均已实际确认')
                report['final_panel']={'plan_version':panel['plan_version'],'confirmed_count':len(panel['stages']),
                                       'submission_counts':[len(s['submissions']) for s in panel['stages']]}
                require(len(panel['stages'][0]['submissions'])==2,'退回与重提历史保留')
                for name in ('publisher','helper'):
                    login(name);state=client.get('/api/guide/todos').json()
                    require(state['todos']+state['waiting']==[],'完成后双方待办清空')
                login('observer');outsider=client.get(path).json()
                require(all(not s['submissions'] for s in outsider['stages']),'旁观者看不到阶段成果')
                with TestClient(create_app(Path(tmp)/'tasks.sqlite3')) as restarted:
                    restarted.cookies.set('campus_session',users['publisher'][0])
                    require(restarted.get(path).json()['stages']==panel['stages'],'重启后阶段及历史完整保留')
                report['passed']=True
    except Exception as exc:
        report['error']=str(exc) if isinstance(exc,AssertionError) else type(exc).__name__
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--real',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=check(args.real)
    output=args.output or Path('.runtime/evals')/('stages-real-latest.json' if args.real else 'stages-offline-latest.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(('PASS' if report['passed'] else 'FAIL '+report.get('error',''))+'; '+str(output.resolve()))
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
