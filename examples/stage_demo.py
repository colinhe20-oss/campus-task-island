"""阶段面板网页验收服务器，使用独立临时任务与账号。"""
import argparse
import tempfile
from pathlib import Path

import uvicorn
from backend.fake_backend import FakeBackend
from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database
from campus.schemas import TaskCreate,TASK_CREATE_EXAMPLE
from campus.service import TaskService
from examples.stage_check import STAGES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8001)
    parser.add_argument('--real-model',action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-stage-demo-') as temp:
        path=Path(temp)/'demo.sqlite3';service=TaskService(Database(path));service.initialize()
        auth=AuthService(service.database);auth.provision_demo_accounts()
        with service.database.connect() as conn:
            publisher=conn.execute("SELECT id FROM users WHERE username='publisher'").fetchone()['id']
        task=service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'【阶段验收】社团摄影'}),publisher)
        def backend():
            demo=FakeBackend([
                {'tool_calls':[{'name':'get_task_detail','arguments':{'task_id':task.id}}]},
                {'tool_calls':[{'name':'propose_task_stages','arguments':{'stages':STAGES}}]},
                {'content':'离线流程演示：请核对并确认阶段安排。'}])
            demo.is_demo=True
            return demo
        app=create_app(path,guide_backend_factory=None if args.real_model else backend)
        print('测试任务链接：http://localhost:'+str(args.port)+'/#/tasks/'+task.id,flush=True)
        print('测试账号文件：'+str(auth.accounts_path),flush=True)
        print('真实模型' if args.real_model else '离线脚本；仅验证调用链',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
