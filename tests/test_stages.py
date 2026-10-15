import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

import test_guide as helpers
from backend.fake_backend import FakeBackend
from campus.app import create_app
from campus.errors import AppError
from campus.schemas import StagePlanInput, StageActionInput
from campus.todos import personal_state
from tools.campus import build_campus_registry


FIELDS = [
    {'title':'确认需求','completion_criteria':'确认拍摄范围和10张清晰照片的交付标准',
     'deadline':'2099-10-19T18:00:00+08:00','responsible_role':'assignee'},
    {'title':'交付照片','completion_criteria':'交付10张清晰照片',
     'deadline':'2099-10-20T18:00:00+08:00','responsible_role':'assignee'},
]


class StageTests(unittest.TestCase):
    setUp=helpers.GuideTests.setUp
    login=helpers.GuideTests.login
    publish=helpers.GuideTests.publish

    def setUp(self):
        helpers.GuideTests.setUp(self)
        self.task=self.publish()
        self.stages=self.app.state.stage_service
        self.path=f'/api/tasks/{self.task.id}/stages'

    def join(self):
        application=self.service.apply(self.task.id,self.users['helper'][1].id,'可以完成')
        self.service.accept_application(application.id,self.users['publisher'][1].id)

    def plan(self,fields=None,version=0):
        self.login()
        response=self.client.post(self.path,json={'expected_version':version,'stages':fields or FIELDS})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def read(self):
        return self.client.get(self.path).json()

    def action(self,index,action,**body):
        stage=self.read()['stages'][index]
        return self.client.post(self.path+'/'+stage['id']+'/'+action,json={'version':stage['version'],**body})

    def test_full_sequential_cycle_return_resubmit_and_complete(self):
        self.plan();self.join();self.login('helper')
        self.assertEqual(self.action(1,'start').status_code,409)
        self.assertEqual(self.action(0,'submissions',summary='未开始').status_code,409)
        self.assertEqual(self.action(0,'start').status_code,200)
        response=self.action(0,'submissions',summary='已核对范围')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.service.get_task(self.task.id).status,'pending_review')
        self.assertEqual(self.action(0,'submissions',summary='重复').status_code,409)
        self.login()
        self.assertEqual(self.action(0,'review',decision='request_changes',feedback='').status_code,422)
        self.assertEqual(self.action(0,'review',decision='request_changes',feedback='补充拍摄清单').status_code,200)
        self.assertEqual(self.service.get_task(self.task.id).status,'in_progress')
        self.login('helper')
        self.assertEqual(self.action(0,'start').status_code,200)
        self.assertEqual(self.action(0,'submissions',summary='已补充清单').status_code,200)
        self.login()
        self.assertEqual(self.action(0,'review',decision='accept',feedback='').status_code,200)
        self.assertEqual(self.service.get_task(self.task.id).status,'in_progress')
        self.assertEqual(len(self.read()['stages'][0]['submissions']),2)
        self.login('helper');self.action(1,'start');self.action(1,'submissions',summary='10张照片已交付')
        self.login();self.assertEqual(self.action(1,'review',decision='accept').status_code,200)
        self.assertEqual(self.service.get_task(self.task.id).status,'completed')
        self.assertTrue(all(s['status']=='confirmed' for s in self.read()['stages']))
        self.assertEqual(self.action(1,'review',decision='accept').status_code,409)
        for name in ('publisher','helper'):
            state=personal_state(self.service,self.users[name][1].id)
            self.assertEqual(state.todos+state.waiting,[])
            self.assertEqual(state.completed_count,1)

    def test_publisher_owned_stage_is_reviewed_by_assignee_and_todos_match(self):
        self.plan([FIELDS[0]|{'responsible_role':'publisher'},FIELDS[1]])
        self.join();self.login()
        publisher,helper=self.users['publisher'][1],self.users['helper'][1]
        def state(user):return personal_state(self.service,user.id)
        self.assertEqual(state(publisher).todos[0].action,'start_stage')
        self.assertEqual(state(helper).waiting[0].action,'wait_for_stage_submission')
        self.action(0,'start')
        self.assertEqual(state(publisher).todos[0].action,'submit_stage')
        self.action(0,'submissions',summary='已明确需求')
        self.assertEqual(state(helper).todos[0].action,'review_stage')
        self.assertEqual(state(publisher).waiting[0].action,'wait_for_stage_review')
        self.assertEqual(self.action(0,'review',decision='accept').status_code,403)
        self.login('helper');self.action(0,'review',decision='accept')
        self.assertEqual(state(helper).todos[0].action,'start_stage')
        self.action(1,'start');self.action(1,'submissions',summary='已完成')
        self.login();self.action(1,'review',decision='request_changes',feedback='补充')
        self.assertEqual(state(helper).todos[0].action,'revise_stage')
        self.assertEqual(state(publisher).waiting[0].action,'wait_for_stage_submission')

    def test_members_share_plan_but_outsiders_cannot_read_submissions_or_operate(self):
        owner=self.users['publisher'][1].id
        self.plan();self.join();self.login('helper')
        stage=self.read()['stages'][0]
        self.assertEqual(stage['responsible_id'],self.users['helper'][1].id)
        self.assertEqual(stage['reviewer_id'],owner)
        self.action(0,'start');self.action(0,'submissions',summary='PRIVATE_STAGE_SECRET')
        shared=self.read()
        self.login();self.assertEqual(self.read()['stages'],shared['stages'])
        self.login('observer')
        public=self.read()
        self.assertEqual(public['stages'][0]['status'],'submitted')
        self.assertEqual(public['stages'][0]['submissions'],[])
        self.assertEqual(public['versions'],[])
        self.assertEqual(self.action(0,'review',decision='accept').status_code,403)
        self.assertEqual(self.action(0,'start').status_code,403)
        self.assertEqual(self.client.post(self.path,json={'expected_version':1,'stages':FIELDS}).status_code,403)
        tool=build_campus_registry(self.service,self.users['observer'][1].id)
        self.assertNotIn('PRIVATE_STAGE_SECRET',tool.get('get_task_detail').invoke({'task_id':self.task.id}))
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.path).status_code,401)

    def test_start_requires_join_and_stage_belongs_to_path_task(self):
        plan=self.plan()
        self.assertEqual(self.action(0,'start').status_code,409)
        self.join();self.login('helper')
        other=self.publish(title='另一项任务')
        response=self.client.post(f'/api/tasks/{other.id}/stages/{plan["stages"][0]["id"]}/start',json={'version':1})
        self.assertEqual(response.status_code,404)

    def test_plan_versions_preserve_definitions_stale_edits_and_executed_plan_are_rejected(self):
        first=self.plan()
        second=self.plan([FIELDS[0]|{'title':'改名后的确认'},FIELDS[1]],1)
        self.assertNotEqual(first['stages'][0]['id'],second['stages'][0]['id'])
        self.assertEqual(len(second['versions']),2)
        self.assertEqual(second['versions'][1]['stages'][0]['title'],FIELDS[0]['title'])
        self.assertEqual(self.client.post(self.path,json={'expected_version':1,'stages':FIELDS}).status_code,409)
        self.join();self.login('helper');self.action(0,'start');self.login()
        self.assertFalse(self.read()['can_edit'])
        self.assertEqual(self.client.post(self.path,json={'expected_version':2,'stages':FIELDS}).status_code,409)

    def test_invalid_dates_roles_and_empty_stage_lists_do_not_create_plan(self):
        self.login()
        for fields,code in [([],422),([FIELDS[0]|{'deadline':'2099-10-19T18:00:00'}],422),
                            ([FIELDS[0]|{'deadline':'2099-10-21T18:00:00+08:00'}],422),
                            ([FIELDS[1],FIELDS[0]],422),([FIELDS[0]|{'responsible_role':'other'}],422),
                            ([FIELDS[0]]*9,422),([FIELDS[0]|{'title':' '}],422)]:
            with self.subTest(fields=fields):
                self.assertEqual(self.client.post(self.path,json={'expected_version':0,'stages':fields}).status_code,code)
                self.assertEqual(self.read()['plan_version'],0)

    def test_legacy_endpoints_cannot_bypass_stages_and_old_workflow_stays_available(self):
        self.plan();self.join();self.login('helper');self.action(0,'start')
        self.assertEqual(self.client.post(f'/api/tasks/{self.task.id}/submissions',json={'summary':'绕过阶段'}).status_code,409)
        self.action(0,'submissions',summary='阶段提交');self.login()
        self.assertEqual(self.client.post(f'/api/tasks/{self.task.id}/review',json={'decision':'accept'}).status_code,409)
        self.assertEqual(self.service.get_task(self.task.id).status,'pending_review')
        other=self.publish(title='原流程任务')
        application=self.service.apply(other.id,self.users['helper'][1].id,'可以')
        self.service.accept_application(application.id,self.users['publisher'][1].id)
        self.service.submit(other.id,self.users['helper'][1].id,'原成果')
        self.service.review(other.id,self.users['publisher'][1].id,'request_changes','补充')
        self.assertEqual(self.client.post(f'/api/tasks/{other.id}/stages',json={'expected_version':0,'stages':FIELDS}).status_code,409)
        self.assertFalse(self.client.get(f'/api/tasks/{other.id}/workspace').json()['uses_stages'])
        self.service.submit(other.id,self.users['helper'][1].id,'已补充')
        self.service.review(other.id,self.users['publisher'][1].id,'accept','通过')
        self.assertEqual(self.service.get_task(other.id).status,'completed')

    def test_stage_completion_and_history_survive_restart(self):
        self.plan(FIELDS[:1]);self.join();self.login('helper');self.action(0,'start');self.action(0,'submissions',summary='已核对')
        self.login();self.action(0,'review',decision='accept')
        before=self.read()
        with TestClient(create_app(self.service.database.path)) as client:
            client.cookies.set('campus_session',self.users['publisher'][0])
            self.assertEqual(client.get(self.path).json(),before)
            self.assertEqual(client.get(f'/api/tasks/{self.task.id}').json()['status'],'completed')

    def test_concurrent_submissions_accept_only_one_and_reject_old_review_version(self):
        self.plan();self.join();self.login('helper');self.action(0,'start')
        stage=self.read()['stages'][0]
        from campus.schemas import StageSubmitInput
        body=StageSubmitInput(version=stage['version'],summary='同一份提交')
        def submit(_):
            try:self.stages.submit(self.task.id,stage['id'],self.users['helper'][1].id,body);return 200
            except AppError as exc:return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit,range(2))),[200,409])
        self.login();self.assertEqual(len(self.read()['stages'][0]['submissions']),1)
        self.assertEqual(self.client.post(self.path+'/'+stage['id']+'/review',json={'version':stage['version'],'decision':'accept'}).status_code,409)

    def test_plan_edit_and_stage_start_are_mutually_exclusive(self):
        plan=self.plan();self.join()
        def start():
            try:self.stages.start(self.task.id,plan['stages'][0]['id'],self.users['helper'][1].id,1);return 200
            except AppError as exc:return exc.status_code
        def edit():
            try:self.stages.set_plan(self.task.id,self.users['publisher'][1].id,StagePlanInput(expected_version=1,stages=FIELDS));return 200
            except AppError as exc:return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(start),pool.submit(edit)]
            codes=[f.result() for f in futures]
        self.assertEqual(codes.count(200),1)
        self.assertIn(next(c for c in codes if c!=200),(404,409))

    def ai(self,responses,**body):
        self.app.state.guide_service.backend_factory=lambda:FakeBackend(responses)
        return self.client.post('/api/guide/chat',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议阶段',**body})

    def script(self,fields=FIELDS):
        return [helpers.calling('get_task_detail',{'task_id':self.task.id}),helpers.calling('propose_task_stages',{'stages':fields}),{'content':'请核对后确认阶段安排'}]

    def test_ai_suggestion_is_separate_editable_confirmed_explicitly_and_restorable(self):
        self.login()
        response=self.ai(self.script());self.assertEqual(response.status_code,200,response.text)
        reply=response.json();suggestion=reply['stage_suggestion']
        self.assertEqual(self.read()['stages'],[])
        self.assertIsNone(reply['draft'])
        self.assertEqual(suggestion['base_version'],0)
        self.assertEqual(self.read()['suggestion'],suggestion)
        restored=self.client.get('/api/guide/conversations/'+reply['conversation_id']).json()
        self.assertEqual(restored['stage_suggestion'],suggestion)
        result=self.client.post(self.path,json={'expected_version':0,'suggestion_id':suggestion['id'],
                                                'stages':[FIELDS[0]|{'title':'我修改的第一阶段'},FIELDS[1]]})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['stages'][0]['title'],'我修改的第一阶段')
        self.assertEqual(self.client.get('/api/guide/conversations/'+reply['conversation_id']).json()['stage_suggestion']['applied_version'],1)
        self.login('helper');self.assertIsNone(self.read()['suggestion']);self.login()
        run=self.client.get('/api/guide/runs/'+reply['run_id']).json()
        self.assertEqual(run['metrics']['tool_calls'],2)
        self.assertIn('propose_task_stages',[e.get('tool') for e in run['events']])

    def test_ai_requires_current_task_details_and_cannot_publish_or_operate_stages(self):
        self.login()
        response=self.ai([helpers.calling('propose_task_stages',{'stages':FIELDS}),{'content':'完成'}])
        self.assertEqual(response.status_code,502)
        self.assertEqual(self.read()['stages'],[])
        self.app.state.guide_service.backend_factory=lambda:FakeBackend(self.script())
        self.client.post('/api/guide/chat',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议'})
        # 没有可供模型直接确认计划、接取、提交、验收或发布任务的写工具。
        class Inspect(FakeBackend):pass
        backend=Inspect(self.script());self.app.state.guide_service.backend_factory=lambda:backend
        response=self.client.post('/api/guide/chat',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议'})
        self.assertEqual(response.status_code,200,response.text)
        names={t['function']['name'] for t in backend.requests[0]['tools']}
        self.assertEqual(names,{'search_tasks','get_my_tasks','get_task_detail','propose_task_stages',
            'search_activities','get_activity_detail','get_my_activity_registrations','search_volunteer_jobs',
            'get_volunteer_detail','get_my_volunteer_registrations','get_my_volunteer_records',
            'search_discoveries','get_discovery_detail','get_my_overview'})

    def test_ai_forbidden_for_other_user_or_finished_withdrawn_executing_task(self):
        self.login('helper');self.assertEqual(self.ai(self.script()).status_code,403)
        self.login();self.plan();self.join();self.login('helper');self.action(0,'start');self.login()
        self.assertEqual(self.ai(self.script()).status_code,409)
        other=self.publish(title='下架任务');self.service.withdraw(other.id,self.users['publisher'][1].id)
        self.assertEqual(self.ai(self.script(),task_id=other.id).status_code,409)

    def test_ai_failure_after_tool_does_not_persist_suggestion_or_history(self):
        self.login()
        class Broken(FakeBackend):
            def chat(inner,*args,**kwargs):
                if len(inner.requests)==2:raise httpx.ReadTimeout('secret-transport-details')
                return super().chat(*args,**kwargs)
        self.app.state.guide_service.backend_factory=lambda:Broken(self.script())
        response=self.client.post('/api/guide/chat',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议阶段'})
        self.assertEqual(response.status_code,504)
        with self.service.database.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM stage_suggestions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_conversations').fetchone()[0],0)
        self.assertEqual(self.read()['stages'],[])

    def test_stale_ai_generation_rolls_back_while_manual_plan_wins(self):
        self.login()
        class Editing(FakeBackend):
            def chat(inner,*args,**kwargs):
                if len(inner.requests)==2:
                    self.stages.set_plan(self.task.id,self.users['publisher'][1].id,StagePlanInput(expected_version=0,stages=FIELDS[:1]))
                return super().chat(*args,**kwargs)
        self.app.state.guide_service.backend_factory=lambda:Editing(self.script())
        response=self.client.post('/api/guide/chat',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议阶段'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(len(self.read()['stages']),1)
        with self.service.database.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM stage_suggestions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM guide_conversations').fetchone()[0],0)

    def test_ai_cancellation_after_staging_rolls_back(self):
        self.login();entered,release=threading.Event(),threading.Event()
        class Slow(FakeBackend):
            def chat(inner,*args,**kwargs):
                if len(inner.requests)==2:entered.set();release.wait(5)
                return super().chat(*args,**kwargs)
        self.app.state.guide_service.backend_factory=lambda:Slow(self.script())
        response=self.client.post('/api/guide/runs',json={'purpose':'stage_plan','task_id':self.task.id,'message':'建议阶段'})
        run_id=response.json()['run_id']
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.client.post('/api/guide/runs/'+run_id+'/cancel').json()['status'],'cancelling')
        finally:release.set()
        for _ in range(100):
            run=self.client.get('/api/guide/runs/'+run_id).json()
            if run['status']=='cancelled':break
            time.sleep(.01)
        self.assertEqual(run['status'],'cancelled')
        with self.service.database.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM stage_suggestions').fetchone()[0],0)
        self.assertEqual(self.read()['stages'],[])
