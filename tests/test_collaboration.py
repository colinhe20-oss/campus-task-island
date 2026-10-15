import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database
from campus.errors import AppError
from campus.schemas import TASK_CREATE_EXAMPLE


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name)/'tasks.sqlite3'
        self.client = self.enterContext(TestClient(create_app(self.db_path)))
        self.accounts = json.loads(self.db_path.with_suffix('.accounts.json').read_text(encoding='utf-8'))

    def login(self, name):
        response = self.client.post('/api/auth/login',json={'username':name,'password':self.accounts[name]['password']})
        self.assertEqual(response.status_code,200)
        return response.json()['id']

    def publish(self):
        self.login('publisher')
        response = self.client.post('/api/tasks',json=TASK_CREATE_EXAMPLE)
        self.assertEqual(response.status_code,201)
        return response.json()['id']

    def apply(self, task_id, name='helper'):
        self.login(name)
        response = self.client.post(f'/api/tasks/{task_id}/applications',json={'reason':f'{name} 可以协作'})
        self.assertEqual(response.status_code,201)
        return response.json()['id']

    def test_full_cycle_with_changes_and_history(self):
        task_id = self.publish()
        application = self.apply(task_id)
        self.login('publisher')
        self.assertEqual(self.client.post(f'/api/applications/{application}/accept').json()['status'],'in_progress')
        self.login('helper')
        first = self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'第一版'})
        self.assertEqual(first.status_code,201)
        self.assertEqual(self.client.get(f'/api/tasks/{task_id}').json()['status'],'pending_review')
        self.login('publisher')
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'request_changes'}).status_code,422)
        response=self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'request_changes','feedback':'补两张合照'})
        self.assertEqual(response.json()['status'],'in_progress')
        self.login('helper')
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'第二版已补充'}).status_code,201)
        self.login('publisher')
        response=self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'accept','feedback':'验收通过'})
        self.assertEqual(response.json()['status'],'completed')
        for params in [{},{'keyword':'摄影'},{'limit':1,'offset':0}]:
            listing=self.client.get('/api/tasks',params=params).json()
            self.assertEqual(listing['items'],[])
            self.assertEqual(listing['total'],0)
        self.assertEqual(self.client.get(f'/api/tasks/{task_id}').json()['status'],'completed')
        self.assertEqual(self.client.get('/api/tasks',params={'status':'completed'}).json()['items'][0]['id'],task_id)
        history=self.client.get(f'/api/tasks/{task_id}/workspace').json()['submissions']
        self.assertEqual(len(history),2)
        self.assertEqual(history[1]['feedback'],'补两张合照')
        self.assertEqual(history[0]['status'],'accepted')
        self.assertEqual(self.client.get('/api/me/tasks').json()['published'][0]['status'],'completed')
        self.login('helper')
        self.assertEqual(self.client.get('/api/me/tasks').json()['assigned'][0]['status'],'completed')

    def test_permissions_and_private_workspace(self):
        task_id=self.publish()
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/applications',json={'reason':'申请自己'}).status_code,403)
        application=self.apply(task_id)
        self.assertEqual(self.client.post(f'/api/applications/{application}/accept').status_code,403)
        self.login('observer')
        self.assertEqual(self.client.get(f'/api/tasks/{task_id}/workspace').json(),{'applications':[],'submissions':[],'uses_stages':False})
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'伪造提交'}).status_code,403)
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'accept'}).status_code,403)
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/applications',json={'reason':'x','applicant_id':'fake'}).status_code,422)

    def test_concurrent_accept_only_one_winner(self):
        task_id=self.publish()
        first=self.apply(task_id)
        second=self.apply(task_id,'observer')
        publisher=self.login('publisher')
        service=self.client.app.state.task_service
        def accept(application):
            try:
                service.accept_application(application,publisher)
                return True
            except AppError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(accept,[first,second]))
        self.assertEqual(outcomes.count(True),1)
        statuses=[a.status for a in service.workspace(task_id,publisher).applications]
        self.assertCountEqual(statuses,['accepted','rejected'])

    def test_repeated_actions_and_extra_field_do_not_change_state(self):
        task_id=self.publish()
        application=self.apply(task_id)
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/applications',json={'reason':'再申请'}).status_code,201)
        self.login('publisher')
        self.client.post(f'/api/applications/{application}/accept')
        self.assertEqual(self.client.post(f'/api/applications/{application}/accept').status_code,409)
        self.login('helper')
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'x','link':'https://example.com'}).status_code,422)
        self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'成果'})
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'再提交'}).status_code,409)
        self.login('publisher')
        self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'accept'})
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'accept'}).status_code,409)
        self.assertEqual(len(self.client.get(f'/api/tasks/{task_id}/workspace').json()['submissions']),1)

    def test_my_applications_only_show_pending_and_preserve_history(self):
        task_id=self.publish()
        accepted=self.apply(task_id)
        self.assertEqual(self.client.get('/api/me/tasks').json()['applied'][0]['id'],task_id)
        self.apply(task_id,'observer')
        self.assertEqual(self.client.get('/api/me/tasks').json()['applied'][0]['id'],task_id)
        self.login('publisher')
        self.client.post(f'/api/applications/{accepted}/accept')
        self.login('helper')
        tasks=self.client.get('/api/me/tasks').json()
        self.assertEqual(tasks['applied'],[])
        self.assertEqual(tasks['assigned'][0]['id'],task_id)
        self.assertEqual(self.client.get(f'/api/tasks/{task_id}/workspace').json()['applications'][0]['status'],'accepted')
        self.client.post(f'/api/tasks/{task_id}/submissions',json={'summary':'已经完成'})
        self.login('publisher')
        self.client.post(f'/api/tasks/{task_id}/review',json={'decision':'accept'})
        self.login('helper')
        self.assertEqual(self.client.get('/api/me/tasks').json()['applied'],[])
        self.assertEqual(self.client.get('/api/me/tasks').json()['assigned'][0]['status'],'completed')
        self.login('observer')
        tasks=self.client.get('/api/me/tasks').json()
        self.assertEqual(tasks['applied'],[])
        self.assertEqual(tasks['assigned'],[])
        self.assertEqual(self.client.get(f'/api/tasks/{task_id}/workspace').json()['applications'][0]['status'],'rejected')
        with self.client.app.state.task_service.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM applications').fetchone()[0],2)

    def test_sessions_origin_and_missing_login(self):
        self.assertEqual(self.client.post('/api/tasks',json=TASK_CREATE_EXAMPLE).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'publisher','password':'wrong'}).status_code,401)
        self.login('publisher')
        self.assertIn('HttpOnly',self.client.cookies.jar._cookies['testserver.local']['/']['campus_session']._rest)
        self.assertEqual(self.client.post('/api/tasks',json=TASK_CREATE_EXAMPLE,headers={'origin':'https://untrusted.example'}).status_code,403)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.login('helper')
        with self.client.app.state.task_service.database.connect() as connection:
            connection.execute('UPDATE sessions SET expires_at=0')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_legacy_database_migration_preserves_records_and_creates_backup(self):
        path=Path(self.temp.name)/'legacy.sqlite3'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('''CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,category TEXT,description TEXT,
                completion_criteria TEXT,location TEXT,deadline TEXT,reward TEXT,status TEXT CHECK(status='published'),created_at TEXT)''')
            connection.execute("INSERT INTO tasks VALUES ('legacy','原来的任务','creative','需求','标准',NULL,NULL,NULL,'published','2099-10-14T08:00:00Z')")
            connection.commit()
        with TestClient(create_app(path)) as client:
            task=client.get('/api/tasks/legacy').json()
            self.assertEqual(task['title'],'原来的任务')
            self.assertEqual(task['publisher_name'],'发布者小林')
        self.assertEqual(len(list(Path(self.temp.name).glob('legacy.before-collaboration-*.sqlite3'))),1)
        with TestClient(create_app(path)) as client:
            self.assertEqual(client.get('/api/tasks/legacy').json()['publisher_id'],task['publisher_id'])
        self.assertEqual(len(list(Path(self.temp.name).glob('legacy.before-collaboration-*.sqlite3'))),1)
