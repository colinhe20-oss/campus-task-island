import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pydantic import ValidationError
from campus.schemas import TaskCreate, TASK_CREATE_EXAMPLE, ClaimInput
from campus.errors import AppError
from campus.db import Database
from tools.base import ToolRegistry
from tools.drafts import register_draft_tools
from campus.drafts import DraftBuffer, read_draft
import test_collaboration as collaboration_helpers
import test_publishing as publishing_helpers

RULES = dict(reason='disabled',experience='required',supplement='optional')

class AcceptanceTests(unittest.TestCase):
    setUp = collaboration_helpers.CollaborationTests.setUp
    login = collaboration_helpers.CollaborationTests.login

    def create(self, mode='direct', rules=None):
        self.owner=self.login('publisher')
        self.service=self.client.app.state.task_service
        response=self.client.post('/api/tasks',json={**TASK_CREATE_EXAMPLE,'acceptance_mode':mode,'application_requirements':rules or RULES})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def post(self,task,**changes):
        return self.client.post(f'/api/tasks/{task}/claim',json=dict(confirmed=True,experience='有摄影经验',**changes))

    def rows(self,table):
        with self.service.database.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table)]

    def test_direct_full_cycle_retry_and_messages(self):
        task=self.create();helper=self.login('helper')
        first=self.post(task,supplement='晚上可以参与')
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['assignee_id'],helper)
        self.assertEqual(len(self.rows('notifications')),2)
        self.assertEqual({k:v for k,v in self.post(task).json().items() if k!='server_time'},{k:v for k,v in first.json().items() if k!='server_time'})
        self.assertEqual(len(self.rows('notifications')),2)
        app=self.rows('applications')[0]
        self.assertEqual((app['status'],app['reason'],app['supplement']),('accepted','','晚上可以参与'))
        self.assertEqual(self.client.get('/api/me/tasks').json()['applied'],[])
        self.assertEqual(len(self.client.get('/api/me/tasks').json()['assigned']),1)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/submissions',json={'summary':'照片已交付'}).status_code,201)
        self.login('publisher')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/review',json={'decision':'accept'}).json()['status'],'completed')
        self.assertEqual(self.client.get('/api/me/home').json()['todo_count'],0)
        self.login('helper')
        self.assertEqual(self.post(task).json()['status'],'completed')
        self.assertEqual(len(self.rows('applications')),1)

    def test_required_disabled_optional_and_confirmation(self):
        task=self.create();self.login('helper')
        for payload in ({'confirmed':True},{'confirmed':True,'experience':'  '},{'experience':'有经验'}, {'confirmed':False,'experience':'有经验'}, {'confirmed':1,'experience':'有经验'},{'confirmed':True,'experience':'x'*2001},{'confirmed':True,'experience':'有经验','reason':'不应填写'}):
            with self.subTest(payload=str(payload)[:70]):
                self.assertEqual(self.client.post(f'/api/tasks/{task}/claim',json=payload).status_code,422)
        self.assertEqual(self.rows('applications'),[])
        self.assertEqual(self.rows('notifications'),[])
        self.assertEqual(self.post(task).status_code,200)

    def test_approval_optional_fields_idempotency_privacy(self):
        task=self.create('approval');self.login('helper')
        path=f'/api/tasks/{task}/applications'
        self.assertEqual(self.client.post(path,json={}).status_code,422)
        first=self.client.post(path,json={'experience':' 我的经验 ','supplement':'说明'}).json()
        second=self.client.post(path,json={'experience':'另一份内容'}).json()
        self.assertEqual(first,second)
        self.assertEqual(first['experience'],'我的经验')
        self.assertEqual(len(self.rows('notifications')),1)
        public=self.client.get(f'/api/tasks/{task}').json()
        self.assertNotIn('experience',public)
        self.login('observer')
        self.assertEqual(self.client.get(f'/api/tasks/{task}/workspace').json()['applications'],[])
        self.login('publisher')
        self.assertEqual(self.client.get(f'/api/tasks/{task}/workspace').json()['applications'][0]['supplement'],'说明')
        self.assertEqual(self.client.post('/api/applications/'+first['id']+'/accept').status_code,200)
        self.login('helper')
        self.assertEqual(self.client.post(path,json={}).json(),{**first,'status':'accepted'})

    def test_mode_owner_and_auth_bypass(self):
        task=self.create()
        self.assertEqual(self.post(task).status_code,403)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.post(task).status_code,401)
        self.login('helper')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/applications',json={'experience':'经验'}).status_code,409)
        self.assertEqual(self.post(task).status_code,200)
        app=self.rows('applications')[0];self.login('publisher')
        self.assertEqual(self.client.post('/api/applications/'+app['id']+'/accept').status_code,409)
        other=self.create('approval');self.login('helper')
        self.assertEqual(self.post(other).status_code,409)

    def test_concurrent_claims_last_seat(self):
        task=self.create();users=[self.login(n) for n in ('helper','observer')]
        def claim(uid):
            try:self.service.claim(task,uid,confirmed=True,experience='经验');return True
            except AppError:return False
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,users))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.rows('applications')),1)
        self.assertEqual(len(self.rows('notifications')),2)

    def test_concurrent_same_user_retry(self):
        task=self.create();uid=self.login('helper')
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.service.claim(task,uid,confirmed=True,experience='经验').id,range(2)))
        self.assertEqual(results,[task,task]);self.assertEqual(len(self.rows('notifications')),2)

    def test_claim_withdraw_race(self):
        task=self.create();uid=self.login('helper')
        def run(action):
            try:
                return self.service.claim(task,uid,confirmed=True,experience='经验') if action=='claim' else self.service.withdraw(task,self.owner)
            except AppError:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['claim','withdraw']))
        self.assertEqual(sum(r is not None for r in results),1)
        current=self.service.get_task(task)
        self.assertEqual(len(self.rows('applications')),int(current.status=='in_progress'))

    def test_notification_failure_rolls_back_claim(self):
        task=self.create();uid=self.login('helper')
        with patch('campus.service.emit',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.service.claim(task,uid,confirmed=True,experience='经验')
        self.assertEqual(self.service.get_task(task).status,'published')
        self.assertEqual(self.rows('applications'),[])

    def test_direct_stage_flow(self):
        task=self.create();stage={'title':'交付','completion_criteria':'完成照片','deadline':TASK_CREATE_EXAMPLE['deadline'],'responsible_role':'assignee'}
        self.client.post(f'/api/tasks/{task}/stages',json={'expected_version':0,'stages':[stage]})
        self.login('helper');self.post(task)
        panel=self.client.get(f'/api/tasks/{task}/stages').json();sid=panel['stages'][0]['id']
        self.assertEqual(self.client.post(f'/api/tasks/{task}/stages/{sid}/start',json={'version':1}).status_code,200)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/stages/{sid}/submissions',json={'version':2,'summary':'交付'}).status_code,200)
        self.login('publisher')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/stages/{sid}/review',json={'version':3,'decision':'accept'}).status_code,200)
        self.assertEqual(self.service.get_task(task).status,'completed')

    def test_legacy_defaults_and_invalid_configs(self):
        for value in ({'reason':'required'}, {**RULES,'unexpected':'optional'}, {**RULES,'experience':'sometimes'}):
            with self.assertRaises(ValidationError):TaskCreate(**TASK_CREATE_EXAMPLE,application_requirements=value)
        task=TaskCreate(**TASK_CREATE_EXAMPLE)
        self.assertEqual(task.acceptance_mode,'approval')
        self.assertEqual(task.application_requirements.reason,'required')
        with self.assertRaises(ValidationError):TaskCreate(**TASK_CREATE_EXAMPLE,acceptance_mode='other')

    def test_all_disabled_and_all_required_rules(self):
        task=self.create(rules=dict.fromkeys(RULES,'disabled'));self.login('helper')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/claim',json={'confirmed':True}).status_code,200)
        task=self.create('approval',dict.fromkeys(RULES,'required'));self.login('helper')
        for missing in RULES:
            payload=dict.fromkeys(RULES,'已填写');payload[missing]='  '
            self.assertEqual(self.client.post(f'/api/tasks/{task}/applications',json=payload).status_code,422)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/applications',json=dict.fromkeys(RULES,'已填写')).status_code,201)

    def test_second_notification_failure_rolls_back_first(self):
        from campus.notifications import emit
        task=self.create();uid=self.login('helper');calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('second notification failed')
            return emit(*args)
        with patch('campus.service.emit',side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.service.claim(task,uid,confirmed=True,experience='经验')
        self.assertEqual(self.rows('notifications'),[])
        self.assertEqual(self.rows('applications'),[])
        self.assertEqual(self.service.get_task(task).status,'published')

    def test_schema9_migration_preserves_columns(self):
        task=self.create('approval')
        with self.service.database.connect() as c:
            # Recreate a legacy schema from a fresh temp database by dropping only added columns.
            c.execute('ALTER TABLE tasks DROP COLUMN acceptance_mode')
            c.execute('ALTER TABLE tasks DROP COLUMN application_requirements')
            c.execute('ALTER TABLE applications DROP COLUMN experience')
            c.execute('ALTER TABLE applications DROP COLUMN supplement')
            before=dict(c.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone())
            c.execute('PRAGMA user_version=9')
        self.service.database.initialize()
        with self.service.database.connect() as c:
            after=dict(c.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone())
            self.assertEqual({k:after[k] for k in before},before)
        self.assertEqual(self.service.get_task(task).acceptance_mode,'approval')

class DraftAcceptanceTests(unittest.TestCase):
    setUp=publishing_helpers.PublishingTests.setUp
    login=publishing_helpers.PublishingTests.login
    chat=publishing_helpers.PublishingTests.chat
    publish_draft=publishing_helpers.PublishingTests.publish_draft

    def test_draft_rules_versions_and_publish(self):
        self.login();first=self.chat(TASK_CREATE_EXAMPLE)
        changed=self.chat({'acceptance_mode':'direct','application_requirements':RULES},first['conversation_id'])
        self.assertEqual(changed['draft']['version'],2)
        self.assertEqual(self.publish_draft(changed,1).status_code,409)
        published=self.publish_draft(changed).json()
        task=self.service.get_task(published['draft']['published_task_id'])
        self.assertEqual(task.acceptance_mode,'direct')
        self.assertEqual(task.application_requirements.model_dump(),RULES)

    def test_nested_tool_schema_valid_and_full_replacement(self):
        registry=ToolRegistry();buffer=DraftBuffer('a'*32,None);register_draft_tools(registry,buffer)
        tool=registry.get('update_task_draft')
        self.assertNotIn('$ref',json.dumps(tool.parameters))
        tool.invoke({'acceptance_mode':'direct','application_requirements':RULES})
        tool.invoke({'application_requirements':dict(reason='optional',experience='disabled',supplement='disabled')})
        self.assertEqual(buffer.fields.application_requirements.experience,'disabled')
        with self.assertRaises(Exception):tool.invoke({'application_requirements':{'reason':'required'}})

    def test_legacy_draft_read_defaults(self):
        row=dict(conversation_id='a'*32,version=1,status='draft',fields=json.dumps(TASK_CREATE_EXAMPLE),published_task_id=None)
        draft=read_draft(row)
        self.assertTrue(draft.ready)
        self.assertEqual(draft.fields.acceptance_mode,'approval')
        self.assertEqual(draft.fields.application_requirements.reason,'required')
