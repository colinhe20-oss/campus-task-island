"""真实模型辅助发布验收；只使用临时数据库与合成任务。"""
import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from campus.app import create_app


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='guide-real-publish-') as directory:
        app=create_app(Path(directory)/'tasks.sqlite3')
        with TestClient(app) as client:
            auth=app.state.auth_service
            accounts=json.loads(auth.accounts_path.read_text(encoding='utf-8'))
            token,user=auth.login('publisher',accounts['publisher']['password'])
            client.cookies.set('campus_session',token)
            first=client.post('/api/guide/chat',json={'message':'我想发布一个任务，找同学帮我拍社团活动照片。'})
            print('first_status:',first.status_code,flush=True)
            if first.status_code!=200:
                print(first.json(),flush=True)
                raise RuntimeError('首轮真实模型对话失败')
            first=first.json()
            print('first_answer:',first['answer'],flush=True)
            print('first_draft:',first['draft'],flush=True)
            assert first['mode']=='model'
            assert first['draft'] and not first['draft']['ready']
            assert first['draft']['fields']['completion_criteria'] is None
            assert client.get('/api/tasks').json()['total']==0
            second=client.post('/api/guide/chat',json={
                'conversation_id':first['conversation_id'],
                'message':'任务标题是【验收】社团活动摄影，分类创作协作。需求是拍摄读书会活动照片，完成标准为交付10张清晰照片。地点学生活动中心，截止时间2026年10月20日北京时间18点，回报为互助。'})
            print('second_status:',second.status_code,flush=True)
            if second.status_code!=200:
                print(second.json(),flush=True)
                raise RuntimeError('补充信息失败')
            second=second.json()
            print('second_answer:',second['answer'],flush=True)
            print('second_draft:',second['draft'],flush=True)
            assert second['draft']['ready']
            # 模型可改写措辞；确认卡片批准的数据必须原样写入任务。
            criteria=second['draft']['fields']['completion_criteria']
            assert all(word in criteria for word in ('10','清晰','照片'))
            assert second['draft']['fields']['location']=='学生活动中心'
            from datetime import datetime
            assert datetime.fromisoformat(second['draft']['fields']['deadline'])==datetime.fromisoformat('2099-10-20T18:00:00+08:00')
            assert client.get('/api/tasks').json()['total']==0
            published=client.post('/api/guide/chat',json={'message':'确认发布','conversation_id':second['conversation_id'],
                                                        'draft_version':second['draft']['version']})
            assert published.status_code==200,published.text
            task_id=published.json()['draft']['published_task_id']
            task=client.get('/api/tasks/'+task_id).json()
            assert task['publisher_id']==user.id
            assert task['title']==second['draft']['fields']['title']
            assert task['completion_criteria']==criteria
            repeated=client.post('/api/guide/drafts/'+second['conversation_id']+'/publish',json={'version':second['draft']['version']})
            assert repeated.json()['draft']['published_task_id']==task_id
            assert client.get('/api/tasks').json()['total']==1
            print('PASS: 真实模型追问、合并草稿、人工确认发布、重复确认只创建一次；正式数据库未使用。',flush=True)


if __name__=='__main__':
    main()
