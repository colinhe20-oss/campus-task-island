"""临时数据库网页验收服务器；默认明确标注离线模式，可显式启用真实模型。"""
import argparse
import json
import tempfile
from pathlib import Path

import uvicorn

from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database
from campus.schemas import TaskCreate, TASK_CREATE_EXAMPLE
from campus.service import TaskService


class DemoGuideBackend:
    is_demo = True

    def chat(self,messages,tools=None):
        if messages[-1]['role']!='tool':
            question=messages[-1]['content']
            if '发布' in question or '10张' in question:
                fields={'completion_criteria':'交付10张清晰照片','location':'学生活动中心','deadline':'2099-10-20T18:00:00+08:00'} if '10张' in question else {
                    'title':'【测试】社团活动摄影','category':'creative','description':'请同学拍摄社团活动照片'}
                return {'content':'','tool_calls':[{'name':'update_task_draft','arguments':fields}]}
            name='search_tasks' if '找摄影' in question else 'get_my_tasks'
            arguments={'keyword':'摄影'} if name=='search_tasks' else {}
            return {'content':'','tool_calls':[{'name':name,'arguments':arguments}]}
        data=json.loads(messages[-1]['content'])
        if messages[-1]['name']=='update_task_draft':
            answer='草稿已完整，请核对卡片后确认发布。' if data['draft']['ready'] else '请补充完成标准、地点和截止时间。'
        elif messages[-1]['name']=='search_tasks':
            answer='找到以下待接取任务：\n'+'\n'.join(item['title'] for item in data['items']) if data['items'] else '当前没有匹配的待接取任务。'
        else:
            todo='\n'.join(f"• {item['title']}：{item['action_label']}" for item in data['todos']) or '当前没有需要你行动的事项。'
            waiting='\n'.join(f"• {item['title']}：{item['action_label']}" for item in data['waiting']) or '当前没有等待事项。'
            answer=f"需要你行动：\n{todo}\n\n等待他人：\n{waiting}\n\n已完成 {data['completed_count']} 条协作。"
        return {'content':answer}


def demo_app(path:Path, *, real_model: bool = False):
    service=TaskService(Database(path))
    service.initialize()
    auth=AuthService(service.database)
    auth.provision_demo_accounts()
    with service.database.connect() as connection:
        users={row['username']:row['id'] for row in connection.execute('SELECT id,username FROM users')}
    first=service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'【测试】校园活动摄影'}),users['publisher'])
    application=service.apply(first.id,users['helper'],'熟悉摄影，可以协作')
    service.accept_application(application.id,users['publisher'])
    second=service.create_task(TaskCreate(reward_type='mutual',title='【测试】整理读书会记录',category='learning',description='整理活动记录',completion_criteria='交付一份文字纪要',location='图书馆',deadline='2099-10-20T18:00:00+08:00'),users['publisher'])
    service.apply(second.id,users['helper'],'可以整理')
    service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'【测试】社团摄影招募'}),users['publisher'])
    return create_app(path,guide_backend_factory=None if real_model else DemoGuideBackend)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8001)
    parser.add_argument('--real-model',action='store_true',help='读取 .env 调用真实模型；数据库仍为临时测试库')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-guide-demo-') as directory:
        path=Path(directory)/'demo.sqlite3'
        app=demo_app(path,real_model=args.real_model)
        print(('真实模型' if args.real_model else '离线测试模型')+'；所有数据均为临时测试数据。',flush=True)
        print('测试账号文件：'+str(path.with_suffix('.accounts.json')),flush=True)
        uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':
    main()
