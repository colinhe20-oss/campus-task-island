import unittest
from concurrent.futures import ThreadPoolExecutor

import test_guide as helpers
from backend.fake_backend import FakeBackend
from campus.errors import AppError
from campus.schemas import TASK_CREATE_EXAMPLE, TaskCreate
from tools.campus import build_campus_registry


class TaskRuleTests(unittest.TestCase):
    setUp = helpers.GuideTests.setUp
    login = helpers.GuideTests.login
    publish = helpers.GuideTests.publish

    def test_location_and_time_required_for_every_api_publish(self):
        self.login()
        bodies=[]
        for name in ('location','deadline'):
            missing=TASK_CREATE_EXAMPLE.copy()
            missing.pop(name)
            bodies.extend([missing,TASK_CREATE_EXAMPLE|{name:None},TASK_CREATE_EXAMPLE|{name:''}])
        bodies.append(TASK_CREATE_EXAMPLE|{'location':'   '})
        bodies.append(TASK_CREATE_EXAMPLE|{'deadline':'2099-10-20T18:00:00'})
        for body in bodies:
            self.assertEqual(self.client.post('/api/tasks',json=body).status_code,422)
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
        self.assertEqual(self.client.post('/api/tasks',json=TASK_CREATE_EXAMPLE).status_code,201)
        required=self.client.get('/openapi.json').json()['components']['schemas']['TaskCreate']['required']
        self.assertTrue({'location','deadline'}.issubset(required))

    def test_draft_missing_place_or_time_cannot_publish(self):
        self.login()
        for name in ('location','deadline'):
            fields=TASK_CREATE_EXAMPLE.copy()
            fields.pop(name)
            self.app.state.guide_service.backend_factory=lambda:FakeBackend([helpers.calling('update_task_draft',fields),{'content':'请补充地点或时间'}])
            reply=self.client.post('/api/guide/chat',json={'message':'帮我发布任务'}).json()
            self.assertFalse(reply['draft']['ready'])
            self.assertIn(name,reply['draft']['missing_fields'])
            self.assertEqual(self.client.post('/api/guide/drafts/'+reply['conversation_id']+'/publish',json={'version':1}).status_code,409)
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)

    def test_withdraw_hides_task_closes_applications_and_keeps_history(self):
        owner=self.login()
        task=self.publish()
        self.service.apply(task.id,self.users['helper'][1].id,'可以协作')
        self.service.apply(task.id,self.users['observer'][1].id,'也可以协作')
        response=self.client.post('/api/tasks/'+task.id+'/withdraw')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'withdrawn')
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
        self.assertEqual(self.client.get('/api/tasks',params={'keyword':'摄影'}).json()['total'],0)
        self.assertEqual(self.client.get('/api/tasks',params={'status':'published'}).json()['total'],0)
        self.assertEqual(self.client.get('/api/tasks',params={'status':'withdrawn'}).json()['total'],1)
        self.assertEqual(self.client.get('/api/me/tasks').json()['published'][0]['status'],'withdrawn')
        self.assertEqual(self.client.get('/api/guide/todos').json()['todos'],[])
        self.assertEqual(self.client.get('/api/guide/todos').json()['waiting'],[])
        self.assertEqual(self.client.get('/api/guide/todos').json()['completed_count'],0)
        self.assertTrue(all(a.status=='rejected' for a in self.service.workspace(task.id,owner).applications))
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,200)
        self.login('helper')
        self.assertEqual(self.client.get('/api/me/tasks').json()['applied'],[])
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/applications',json={'reason':'重试'}).status_code,201)
        self.assertEqual(self.service.get_task(task.id).description,TASK_CREATE_EXAMPLE['description'])

    def test_only_owner_can_withdraw_and_taken_tasks_are_rejected(self):
        task=self.publish()
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,401)
        self.login('helper')
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,403)
        application=self.service.apply(task.id,self.users['helper'][1].id,'申请')
        owner=self.login()
        self.service.accept_application(application.id,owner)
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,409)
        self.service.submit(task.id,self.users['helper'][1].id,'完成')
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,409)
        self.service.review(task.id,owner,'accept','通过')
        self.assertEqual(self.client.post('/api/tasks/'+task.id+'/withdraw').status_code,409)
        self.assertEqual(self.service.get_task(task.id).status,'completed')

    def test_concurrent_withdraw_and_accept_have_only_one_winner(self):
        owner=self.login()
        task=self.publish()
        application=self.service.apply(task.id,self.users['helper'][1].id,'申请')
        def action(kind):
            try:
                result=self.service.withdraw(task.id,owner) if kind=='withdraw' else self.service.accept_application(application.id,owner)
                return result.status
            except AppError:return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(action,['withdraw','accept']))
        self.assertEqual(outcomes.count('rejected'),1)
        task=self.service.get_task(task.id)
        self.assertIn(task.status,('withdrawn','in_progress'))
        if task.status=='withdrawn':self.assertIsNone(task.assignee_id)
        else:self.assertTrue(task.is_listed)

    def test_agent_search_excludes_withdrawn_and_details_report_withdrawn(self):
        owner=self.login()
        task=self.publish()
        self.service.withdraw(task.id,owner)
        import json
        registry=build_campus_registry(self.service,owner)
        self.assertEqual(json.loads(registry.get('search_tasks').invoke({}))['total'],0)
        self.assertEqual(json.loads(registry.get('get_task_detail').invoke({'task_id':task.id}))['status'],'withdrawn')
        state=json.loads(registry.get('get_my_tasks').invoke({}))
        self.assertEqual(state['todos']+state['waiting'],[])

    def test_old_nullable_records_still_read_without_fabricated_values(self):
        self.login()
        task=self.publish()
        with self.service.database.connect() as connection:
            connection.execute('UPDATE tasks SET location=NULL,deadline=NULL WHERE id=?',(task.id,))
        response=self.client.get('/api/tasks/'+task.id)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.json()['location'])
        self.assertIsNone(response.json()['deadline'])
        self.assertEqual(self.client.get('/api/tasks').status_code,200)
        self.assertEqual(self.client.get('/api/me/tasks').status_code,200)
        self.assertEqual(self.client.get('/api/guide/todos').status_code,200)
        # 不能绕过公开发布接口，用历史读取对象再次创建无时间地点任务。
        with self.assertRaises(ValueError):self.service.create_task(self.service.get_task(task.id))
