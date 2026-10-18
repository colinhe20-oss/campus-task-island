import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import test_guide as helpers
from backend.fake_backend import FakeBackend
from app_factory import create_app
from campus.drafts import DraftBuffer
from campus.errors import AppError
from campus.schemas import TASK_CREATE_EXAMPLE


class PublishingTests(unittest.TestCase):
    setUp = helpers.GuideTests.setUp
    login = helpers.GuideTests.login

    def count_tasks(self):
        with self.service.database.connect() as connection:
            return connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]

    def chat(self, fields, conversation_id=None):
        fields={'reward_type':'mutual',**fields}
        self.app.state.guide_service.backend_factory=lambda:FakeBackend([
            helpers.calling('update_task_draft',fields),{'content':'请检查草稿或补充缺失信息。'}])
        response=self.client.post('/api/guide/chat',json={'message':'帮我整理任务','conversation_id':conversation_id})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def publish_draft(self, reply, version=None):
        return self.client.post(f"/api/guide/drafts/{reply['conversation_id']}/publish",
                                json={'version':version or reply['draft']['version']})

    def test_partial_information_is_saved_but_never_published(self):
        self.login()
        reply=self.chat({'title':'活动摄影','description':'拍摄社团活动'})
        self.assertEqual(reply['draft']['missing_fields'],['category','completion_criteria','location','deadline'])
        self.assertFalse(reply['draft']['ready'])
        self.assertIsNone(reply['draft']['fields']['deadline'])
        self.assertEqual(reply['draft']['status'],'draft')
        self.assertEqual(self.count_tasks(),0)
        self.assertEqual(self.publish_draft(reply).status_code,409)
        restored=self.client.get('/api/guide/conversations/'+reply['conversation_id']).json()
        self.assertEqual(restored['draft'],reply['draft'])

    def test_followup_merges_fields_and_confirm_creates_real_task(self):
        user_id=self.login()
        first=self.chat({'title':'活动摄影','description':'拍摄社团活动'})
        complete=self.chat({'category':'creative','completion_criteria':'交付10张清晰照片','location':'学生活动中心','deadline':'2099-10-20T18:00:00+08:00'},first['conversation_id'])
        self.assertEqual(complete['draft']['fields']['title'],'活动摄影')
        self.assertTrue(complete['draft']['ready'])
        self.assertEqual(complete['draft']['version'],2)
        self.assertEqual(self.count_tasks(),0)
        published=self.publish_draft(complete)
        self.assertEqual(published.status_code,200,published.text)
        self.assertEqual(published.json()['draft']['status'],'published')
        task_id=published.json()['draft']['published_task_id']
        task=self.client.get('/api/tasks/'+task_id).json()
        self.assertEqual(task['publisher_id'],user_id)
        self.assertEqual(task['completion_criteria'],'交付10张清晰照片')
        self.assertEqual(self.client.get('/api/tasks').json()['items'][0]['id'],task_id)
        self.assertEqual(self.client.get('/api/guide/todos').json()['waiting'][0]['task_id'],task_id)

    def test_edit_rejects_stale_confirmation_and_optional_fields_can_be_cleared(self):
        self.login()
        first=self.chat(TASK_CREATE_EXAMPLE)
        edited=self.chat({'title':'新的活动摄影','location':None,'deadline':'2099-10-22T18:00:00+08:00'},first['conversation_id'])
        self.assertEqual(self.publish_draft(edited,first['draft']['version']).status_code,409)
        self.assertEqual(self.count_tasks(),0)
        self.assertFalse(edited['draft']['ready'])
        self.assertEqual(self.publish_draft(edited).status_code,409)
        edited=self.chat({'location':'图书馆'},first['conversation_id'])
        response=self.publish_draft(edited)
        task=self.client.get('/api/tasks/'+response.json()['draft']['published_task_id']).json()
        self.assertEqual(task['location'],'图书馆')
        self.assertEqual(task['title'],'新的活动摄影')
        self.assertEqual(task['deadline'],'2099-10-22T10:00:00Z')

    def test_repeat_and_concurrent_confirmation_only_create_one_task(self):
        user_id=self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        drafts=self.app.state.guide_service.drafts
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=list(pool.map(lambda _:drafts.publish(reply['conversation_id'],user_id,reply['draft']['version']),range(2)))
        self.assertEqual(tasks[0].id,tasks[1].id)
        self.assertEqual(self.count_tasks(),1)
        self.assertEqual(self.publish_draft(reply).json()['draft']['published_task_id'],tasks[0].id)
        restored=self.client.get('/api/guide/conversations/'+reply['conversation_id']).json()
        self.assertEqual(len(restored['messages']),4)

    def test_other_user_cannot_read_publish_cancel_or_continue_draft(self):
        self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        self.login('helper')
        self.assertEqual(self.client.get('/api/guide/conversations/'+reply['conversation_id']).status_code,404)
        self.assertEqual(self.publish_draft(reply).status_code,404)
        self.assertEqual(self.client.post('/api/guide/drafts/'+reply['conversation_id']+'/cancel',json={'version':1}).status_code,404)
        self.assertEqual(self.client.post('/api/guide/chat',json={'message':'确认发布','conversation_id':reply['conversation_id'],'draft_version':1}).status_code,404)
        self.assertEqual(self.count_tasks(),0)

    def test_client_and_tool_cannot_spoof_publisher_or_extra_fields(self):
        self.login()
        for fields in [TASK_CREATE_EXAMPLE|{'publisher_id':'another'},TASK_CREATE_EXAMPLE|{'status':'completed'}]:
            reply=self.chat(fields)
            self.assertEqual(reply['tools_used'][0]['success'],False)
            self.assertIsNone(reply['draft'])
        reply=self.chat(TASK_CREATE_EXAMPLE)
        response=self.client.post('/api/guide/drafts/'+reply['conversation_id']+'/publish',json={'version':1,'publisher_id':'other'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.count_tasks(),0)

    def test_invalid_patch_is_atomic_and_keeps_saved_version(self):
        self.login()
        first=self.chat(TASK_CREATE_EXAMPLE)
        for fields in [{'category':'unknown'},{'deadline':'2099-10-22T18:00:00'},{'title':' '},{'reward':'x'*501}]:
            reply=self.chat(fields,first['conversation_id'])
            self.assertEqual(reply['tools_used'][0]['success'],False)
            self.assertEqual(reply['draft'],first['draft'])
        self.assertEqual(self.count_tasks(),0)

    def test_model_failure_rolls_back_staged_draft_and_history(self):
        self.login()
        first=self.chat(TASK_CREATE_EXAMPLE)
        class FailsAfterTool(FakeBackend):
            def chat(self,*args,**kwargs):
                if self.requests:raise httpx.ReadTimeout('test timeout')
                return super().chat(*args,**kwargs)
        self.app.state.guide_service.backend_factory=lambda:FailsAfterTool([helpers.calling('update_task_draft',{'title':'should not be saved'})])
        response=self.client.post('/api/guide/chat',json={'message':'改一下','conversation_id':first['conversation_id']})
        self.assertEqual(response.status_code,504)
        restored=self.client.get('/api/guide/conversations/'+first['conversation_id']).json()
        self.assertEqual(restored['draft'],first['draft'])
        self.assertEqual(len(restored['messages']),2)
        self.assertEqual(self.count_tasks(),0)
        response=self.client.post('/api/guide/chat',json={'message':'新的任务'})
        self.assertEqual(response.status_code,504)
        with self.service.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM guide_conversations').fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM guide_task_drafts').fetchone()[0],1)

    def test_exact_text_confirmation_works_without_model_and_is_idempotent(self):
        self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        def disabled():raise ValueError('model not configured')
        self.app.state.guide_service.backend_factory=disabled
        payload={'message':'确认发布','conversation_id':reply['conversation_id'],'draft_version':reply['draft']['version']}
        self.assertEqual(self.client.post('/api/guide/chat',json=payload).status_code,200)
        self.assertEqual(self.client.post('/api/guide/chat',json=payload).status_code,200)
        self.assertEqual(self.count_tasks(),1)
        self.assertEqual(self.client.post('/api/guide/chat',json={'message':'确认发布'}).status_code,409)

    def test_cancel_draft_does_not_publish_and_new_conversation_can_start(self):
        self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        url='/api/guide/drafts/'+reply['conversation_id']+'/cancel'
        response=self.client.post(url,json={'version':1})
        self.assertEqual(response.json()['draft']['status'],'cancelled')
        self.assertEqual(self.publish_draft(reply).status_code,409)
        rejected=self.chat({'title':'想再修改'},reply['conversation_id'])
        self.assertFalse(rejected['tools_used'][0]['success'])
        fresh=self.chat(TASK_CREATE_EXAMPLE)
        self.assertNotEqual(fresh['conversation_id'],reply['conversation_id'])
        self.assertEqual(self.publish_draft(fresh).status_code,200)
        self.assertEqual(self.client.post('/api/guide/drafts/'+fresh['conversation_id']+'/cancel',json={'version':1}).status_code,409)

    def test_published_draft_is_frozen_and_survives_restart(self):
        self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        published=self.publish_draft(reply).json()
        rejected=self.chat({'title':'偷偷修改'},reply['conversation_id'])
        self.assertFalse(rejected['tools_used'][0]['success'])
        self.assertEqual(rejected['draft'],published['draft'])
        with TestClient(create_app(self.service.database.path)) as client:
            client.cookies.set('campus_session',self.users['publisher'][0])
            restored=client.get('/api/guide/conversations/'+reply['conversation_id'])
            self.assertEqual(restored.json()['draft']['published_task_id'],published['draft']['published_task_id'])

    def test_task_creation_and_draft_confirmation_share_one_transaction(self):
        user_id=self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        original=self.service.insert_task
        def fail_after_insert(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('test transaction rollback')
        with patch.object(self.service,'insert_task',side_effect=fail_after_insert):
            with self.assertRaises(RuntimeError):
                self.app.state.guide_service.drafts.publish(reply['conversation_id'],user_id,1)
        self.assertEqual(self.count_tasks(),0)
        self.assertEqual(self.app.state.guide_service.drafts.get(reply['conversation_id'],user_id).status,'draft')
        self.assertEqual(self.publish_draft(reply).status_code,200)

    def test_stale_buffer_cannot_overwrite_published_draft(self):
        user_id=self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        draft=self.app.state.guide_service.drafts.get(reply['conversation_id'],user_id)
        buffer=DraftBuffer(reply['conversation_id'],draft)
        buffer.update({'title':'stale data'})
        self.publish_draft(reply)
        with self.assertRaises(AppError),self.service.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            buffer.save(connection,user_id)
        self.assertEqual(self.service.get_task(self.app.state.guide_service.drafts.get(reply['conversation_id'],user_id).published_task_id).title,TASK_CREATE_EXAMPLE['title'])

    def test_model_has_no_publish_tool_and_draft_outlives_short_history(self):
        self.login()
        reply=self.chat(TASK_CREATE_EXAMPLE)
        backend=FakeBackend([helpers.calling('create_task',TASK_CREATE_EXAMPLE),{'content':'尚未发布'}])
        self.app.state.guide_service.backend_factory=lambda:backend
        response=self.client.post('/api/guide/chat',json={'message':'发布吧','conversation_id':reply['conversation_id']})
        self.assertFalse(response.json()['tools_used'][0]['success'])
        names={s['function']['name'] for s in backend.requests[0]['tools']}
        self.assertEqual(names,{'get_my_tasks','get_task_detail','search_tasks','get_task_draft','update_task_draft',
            'search_activities','get_activity_detail','get_my_activity_registrations','search_volunteer_jobs',
            'get_volunteer_detail','get_my_volunteer_registrations','get_my_volunteer_records',
            'search_discoveries','get_discovery_detail','get_my_overview',
            'review_activity_plan','get_assistance','update_volunteer_plan','update_activity_plan','get_participation_preferences','propose_preferences','get_recommendations'})
        for _ in range(6):
            self.app.state.guide_service.backend_factory=lambda:FakeBackend([{'content':'请查看当前草稿'}])
            self.client.post('/api/guide/chat',json={'message':'再查看','conversation_id':reply['conversation_id']})
        restored=self.client.get('/api/guide/conversations/'+reply['conversation_id']).json()
        self.assertEqual(len(restored['messages']),10)
        self.assertEqual(restored['draft'],reply['draft'])
        self.assertNotIn('reasoning_content',json.dumps(restored))
        self.assertEqual(self.count_tasks(),0)
