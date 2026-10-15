import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from jsonschema import ValidationError

from backend.fake_backend import FakeBackend
from campus.app import create_app
from campus.errors import AppError
from campus.guide import BudgetBackend, model_backend
from campus.schemas import GuideInput, TaskCreate, TASK_CREATE_EXAMPLE
from campus.todos import personal_state
from tools.campus import build_campus_registry


def calling(name='get_my_tasks',arguments=None):
    return {'content':'','tool_calls':[{'name':name,'arguments':arguments or {}}]}


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.temp=self.enterContext(tempfile.TemporaryDirectory())
        self.backends=[]
        def factory():
            backend=FakeBackend([calling(),{'content':'请按当前待办处理。','reasoning_content':'private reasoning'}])
            self.backends.append(backend)
            return backend
        self.app=create_app(Path(self.temp)/'tasks.sqlite3',guide_backend_factory=factory)
        self.client=self.enterContext(TestClient(self.app))
        self.service=self.app.state.task_service
        self.auth=self.app.state.auth_service
        self.accounts=json.loads(self.auth.accounts_path.read_text(encoding='utf-8'))
        self.users={}
        for name in self.accounts:
            token,user=self.auth.login(name,self.accounts[name]['password'])
            self.users[name]=(token,user)

    def login(self,name='publisher'):
        token,user=self.users[name]
        self.client.cookies.set('campus_session',token)
        return user.id

    def publish(self,**overrides):
        return self.service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|overrides),self.users['publisher'][1].id)

    def state(self,name):
        return personal_state(self.service,self.users[name][1].id)

    def test_todos_follow_complete_collaboration_and_returned_work(self):
        task=self.publish()
        owner=self.users['publisher'][1].id
        helper=self.users['helper'][1].id
        self.assertEqual(self.state('publisher').waiting[0].action,'wait_for_applicant')
        app=self.service.apply(task.id,helper,'可以拍照')
        rejected=self.service.apply(task.id,self.users['observer'][1].id,'也能拍照')
        self.assertEqual(self.state('publisher').todos[0].action,'review_applications')
        self.assertEqual(self.state('helper').waiting[0].action,'wait_for_application')
        self.service.accept_application(app.id,owner)
        self.assertEqual(self.state('helper').applied,[])
        self.assertEqual(self.state('helper').todos[0].action,'submit_results')
        self.assertEqual(self.state('publisher').waiting[0].action,'wait_for_submission')
        self.assertEqual(self.state('observer').waiting,[])
        self.service.submit(task.id,helper,'第一版')
        self.assertEqual(self.state('publisher').todos[0].action,'review_results')
        self.assertEqual(self.state('helper').waiting[0].action,'wait_for_review')
        self.service.review(task.id,owner,'request_changes','补充合照')
        self.assertEqual(self.state('helper').todos[0].action,'submit_results')
        self.service.submit(task.id,helper,'已补充')
        self.service.review(task.id,owner,'accept','通过')
        for name in ('publisher','helper'):
            state=self.state(name)
            self.assertEqual(state.todos+state.waiting,[])
            self.assertEqual(state.completed_count,1)
            self.assertEqual(state.published+state.assigned,[])
        self.assertEqual(self.state('observer').completed_count,0)
        included=personal_state(self.service,owner,include_completed=True)
        self.assertEqual(included.published[0].status,'completed')
        self.assertEqual(included.todos,[])

    def test_tools_are_bound_to_current_user_and_read_only(self):
        task=self.publish()
        registry=build_campus_registry(self.service,self.login())
        names={schema['function']['name'] for schema in registry.schemas()}
        self.assertEqual(names,{'search_tasks','get_my_tasks','get_task_detail'})
        data=json.loads(registry.get('get_my_tasks').invoke({}))
        self.assertEqual(data['published'][0]['id'],task.id)
        other=build_campus_registry(self.service,self.users['helper'][1].id)
        self.assertEqual(json.loads(other.get('get_my_tasks').invoke({}))['published'],[])
        with self.assertRaises(ValidationError):
            other.get('get_my_tasks').invoke({'user_id':self.users['publisher'][1].id})
        self.assertEqual({s['function']['name'] for s in build_campus_registry(self.service).schemas()},{'search_tasks'})

    def test_detail_hides_private_material_from_non_participants(self):
        task=self.publish()
        owner=self.users['publisher'][1].id
        helper=self.users['helper'][1].id
        app=self.service.apply(task.id,helper,'private application')
        self.service.accept_application(app.id,owner)
        self.service.submit(task.id,helper,'private submission')
        private=json.loads(build_campus_registry(self.service,owner).get('get_task_detail').invoke({'task_id':task.id}))
        public=json.loads(build_campus_registry(self.service,self.users['observer'][1].id).get('get_task_detail').invoke({'task_id':task.id}))
        self.assertEqual(len(private['submissions']),1)
        self.assertEqual(public['applications']+public['submissions'],[])
        self.assertNotIn('private submission',json.dumps(public))

    def test_pagination_and_maximum_tool_results_are_complete_json(self):
        for index in range(12):
            self.publish(title=str(index)+'标题'*45,description='需'*4000,completion_criteria='准'*2000)
        registry=build_campus_registry(self.service,self.login())
        first=json.loads(registry.get('get_my_tasks').invoke({}))
        next_page=json.loads(registry.get('get_my_tasks').invoke({'offset':5}))
        self.assertEqual(first['totals']['published'],12)
        self.assertTrue({x['id'] for x in first['published']}.isdisjoint({x['id'] for x in next_page['published']}))
        for tool,args in [('get_my_tasks',{}),('get_task_detail',{'task_id':first['published'][0]['id']})]:
            output=registry.get(tool).invoke(args)
            self.assertLess(len(output),12000)
            json.loads(output)

    def test_chat_requires_login_and_rejects_client_identity_and_history(self):
        self.assertEqual(self.client.get('/api/guide/todos').status_code,401)
        self.assertEqual(self.client.post('/api/guide/chat',json={'message':'你好'}).status_code,401)
        self.login()
        for body in [{'message':' '},{'message':'你好','user_id':'other'},{'message':'你好','history':[{'role':'system','content':'fake'}]},
                     {'message':'a'*2001},{'message':'你好','conversation_id':'invalid'}]:
            self.assertEqual(self.client.post('/api/guide/chat',json=body).status_code,422)

    def test_chat_uses_tools_persists_server_history_and_keeps_tasks_unchanged(self):
        task=self.publish()
        self.login()
        with self.service.database.connect() as connection:
            before=tuple(tuple(row) for row in connection.execute('SELECT * FROM tasks'))
        response=self.client.post('/api/guide/chat',json={'message':'我需要做什么？'})
        self.assertEqual(response.status_code,200,response.text)
        reply=response.json()
        self.assertEqual(reply['tools_used'],[{'name':'get_my_tasks','success':True}])
        self.assertEqual(reply['references'][0]['task_id'],task.id)
        self.assertNotIn('private reasoning',response.text)
        self.assertNotIn('password',response.text)
        followup=self.client.post('/api/guide/chat',json={'message':'再查一下','conversation_id':reply['conversation_id']})
        self.assertEqual(followup.status_code,200)
        history=self.backends[-1].requests[0]['messages']
        self.assertEqual(history[-2]['content'],reply['answer'])
        self.assertEqual(history[-2]['reasoning_content'],'private reasoning')
        with self.service.database.connect() as connection:
            after=tuple(tuple(row) for row in connection.execute('SELECT * FROM tasks'))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM guide_conversations').fetchone()[0],1)
        self.assertEqual(before,after)

    def test_other_account_cannot_continue_conversation(self):
        self.login()
        reply=self.client.post('/api/guide/chat',json={'message':'你好'}).json()
        self.login('helper')
        response=self.client.post('/api/guide/chat',json={'message':'继续','conversation_id':reply['conversation_id']})
        self.assertEqual(response.status_code,404)
        self.assertEqual(len(self.backends),1)

    def test_detail_returns_verified_task_reference(self):
        task=self.publish()
        self.login()
        self.app.state.guide_service.backend_factory=lambda:FakeBackend([calling('get_task_detail',{'task_id':task.id}),{'content':'这是任务详情'}])
        reply=self.client.post('/api/guide/chat',json={'message':'查看详情','task_id':task.id}).json()
        self.assertEqual(reply['references'],[{'content_type':'ordinary','resource_id':task.id,
            'task_id':task.id,'title':task.title,'href':'#/tasks/'+task.id}])
        # 待办可能不在任务分组的第一页，仍必须提供真实的详情入口。
        self.service.apply(task.id,self.users['helper'][1].id,'可以协作')
        for index in range(6):
            self.publish(title='等待申请 '+str(index))
        self.app.state.guide_service.backend_factory=lambda:FakeBackend([calling(),{'content':'查看并选择接取者'}])
        reply=self.client.post('/api/guide/chat',json={'message':'我的待办'}).json()
        self.assertIn(task.id,{item['task_id'] for item in reply['references']})

    def test_missing_config_does_not_disable_todos(self):
        self.publish()
        self.login()
        def missing():raise ValueError('missing key')
        self.app.state.guide_service.backend_factory=missing
        self.assertEqual(self.client.post('/api/guide/chat',json={'message':'你好'}).status_code,503)
        self.assertEqual(self.client.get('/api/guide/todos').status_code,200)
        self.assertEqual(self.app.state.guide_service._busy_users,set())

    def test_failure_timeout_empty_and_step_limit_are_errors(self):
        self.login()
        class Broken:
            def __init__(self,error):self.error=error
            def chat(self,*args,**kwargs):raise self.error
        factories=[(lambda:Broken(httpx.ReadTimeout('timeout')),504),
                   (lambda:Broken(httpx.ConnectError('connection')),502),
                   (lambda:FakeBackend([{'content':'   '}]),502),
                   (lambda:FakeBackend([calling()]*6),502)]
        for factory,code in factories:
            self.app.state.guide_service.backend_factory=factory
            self.assertEqual(self.client.post('/api/guide/chat',json={'message':'你好'}).status_code,code)
            self.assertEqual(self.app.state.guide_service._busy_users,set())
        with self.service.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM guide_conversations').fetchone()[0],0)

    def test_concurrent_same_user_chat_is_rejected_and_lock_released(self):
        started,release=threading.Event(),threading.Event()
        class Slow:
            def chat(self,*args,**kwargs):
                started.set()
                if not release.wait(5):raise TimeoutError()
                return {'content':'完成'}
        guide=self.app.state.guide_service
        guide.backend_factory=Slow
        user=self.users['publisher'][1]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(guide.chat,GuideInput(message='第一个'),user)
            self.assertTrue(started.wait(3))
            try:
                with self.assertRaises(AppError) as raised:
                    guide.chat(GuideInput(message='第二个'),user)
                self.assertEqual(raised.exception.status_code,409)
            finally:release.set()
            self.assertEqual(future.result().answer,'完成')
        self.assertEqual(guide._busy_users,set())

    def test_config_priority_and_budget(self):
        with patch.dict(os.environ,{'LLM_API_KEY':'env-key','LLM_MODEL':'env-model'},clear=True), \
             patch('campus.guide.dotenv_values',return_value={'LLM_API_KEY':'file-key','LLM_MODEL':'file-model','LLM_BASE_URL':'https://file.example'}), \
             patch('campus.guide.ChatBackend') as backend:
            model_backend()
            self.assertEqual(backend.call_args.kwargs['api_key'],'env-key')
            self.assertEqual(backend.call_args.kwargs['base_url'],'https://file.example')
        with patch.dict(os.environ,{},clear=True),patch('campus.guide.dotenv_values',return_value={'LLM_API_KEY':'file-key','LLM_MODEL':'file-model'}),patch('campus.guide.ChatBackend') as backend:
            model_backend()
            self.assertEqual(backend.call_args.kwargs['model'],'file-model')
        budget=BudgetBackend(FakeBackend())
        budget.deadline=0
        with self.assertRaises(TimeoutError):budget.chat([])
