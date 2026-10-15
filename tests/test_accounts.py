# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database
from campus.errors import AppError


class AccountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'accounts.sqlite3'
        self.client = self.enterContext(TestClient(create_app(self.db_path)))
        self.accounts = json.loads(self.db_path.with_suffix('.accounts.json').read_text(encoding='utf-8'))

    def register(self, username='new.user', password='correct-horse-battery'):
        return self.client.post('/api/auth/register', json={
            'username': username, 'display_name': '新同学', 'password': password,
        })

    def login(self, username, password=None):
        credential = password or self.accounts[username]['password']
        return self.client.post('/api/auth/login', json={'username': username, 'password': credential})

    def test_registration_normalizes_username_and_grants_ordinary_permissions(self):
        response = self.register('  New.User  ')
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['username'], 'new.user')
        self.assertTrue(body['can_publish_activities'])
        self.assertTrue(body['can_publish_volunteers'])
        self.assertNotIn('salt', body)
        self.assertNotIn('password_hash', body)
        duplicate = self.register('NEW.USER')
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.client.get('/api/me/account').status_code, 200)

    def test_registration_validation_and_concurrent_unique_username(self):
        for payload in [
            {'username': 'ab', 'display_name': '甲', 'password': 'long-password-123'},
            {'username': 'okay', 'display_name': ' ', 'password': 'long-password-123'},
            {'username': 'okay', 'display_name': '甲', 'password': 'short'},
            {'username': 'bad/name', 'display_name': '甲', 'password': 'long-password-123'},
        ]:
            self.assertEqual(self.client.post('/api/auth/register', json=payload).status_code, 422)
        self.client.cookies.clear()
        app = self.client.app
        def register_once(_):
            with TestClient(app) as client:
                return client.post('/api/auth/register', json={
                    'username': 'race.user', 'display_name': '并发用户', 'password': 'long-password-123',
                }).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(register_once, range(2)))
        self.assertCountEqual(statuses, [201, 409])

    def test_registration_accepts_six_character_password(self):
        response = self.register('sixchar', 'abc123')
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.login('sixchar', 'abc123').status_code, 200)

    def test_closure_requires_password_and_confirmation_and_cannot_target_other_user(self):
        self.register()
        self.assertEqual(self.client.post('/api/me/account/close', json={
            'password': 'correct-horse-battery', 'confirmed': True, 'user_id': 'publisher',
        }).status_code, 422)
        self.assertEqual(self.client.post('/api/me/account/close', json={
            'password': 'wrong-password', 'confirmed': True,
        }).status_code, 403)
        self.assertEqual(self.client.post('/api/me/account/close', json={
            'password': 'correct-horse-battery', 'confirmed': False,
        }).status_code, 422)
        self.assertEqual(self.client.get('/api/me/account').status_code, 200)

    def test_closure_anonymizes_and_revokes_sessions_but_keeps_username_reserved(self):
        user_id = self.register('closer').json()['id']
        with self.client.app.state.task_service.database.connect() as connection:
            connection.execute('INSERT INTO activity_permissions(user_id,can_publish) VALUES (?,1)', (user_id,))
            connection.execute("INSERT INTO notifications(recipient_id,event_key,content_type,resource_id,title,summary,created_at) VALUES (?,'e1','task','t1','title','summary','2026-01-01')", (user_id,))
        self.client.post('/api/auth/login', json={
            'username': 'closer', 'password': 'correct-horse-battery',
        })
        # Create private Guide data to ensure closure clears content without deleting the account's business identity.
        with self.client.app.state.task_service.database.connect() as connection:
            connection.execute("INSERT INTO guide_conversations(user_id,history,updated_at) VALUES (?,'[\\\"private\\\"]','2026-01-01')", (user_id,))
        closed = self.client.post('/api/me/account/close', json={
            'password': 'correct-horse-battery', 'confirmed': True,
        })
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.login('closer', 'correct-horse-battery').status_code, 401)
        self.assertEqual(self.register('CLOSER').status_code, 409)
        with self.client.app.state.task_service.database.connect() as connection:
            row = connection.execute('SELECT display_name,account_status,closed_at FROM users WHERE id=?', (user_id,)).fetchone()
            self.assertEqual(row['display_name'], '已注销用户')
            self.assertEqual(row['account_status'], 'closed')
            self.assertTrue(row['closed_at'])
            self.assertEqual(connection.execute('SELECT can_publish FROM activity_permissions WHERE user_id=?', (user_id,)).fetchone()['can_publish'], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?', (user_id,)).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM notifications WHERE recipient_id=?', (user_id,)).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT history FROM guide_conversations WHERE user_id=?', (user_id,)).fetchone()['history'], '[]')

    def test_unfinished_task_blocks_closure_with_link(self):
        publisher = self.login('publisher').json()['id']
        with self.client.app.state.task_service.database.connect() as connection:
            connection.execute("INSERT INTO tasks(id,title,description,completion_criteria,category,location,deadline,reward,status,publisher_id,is_listed,created_at) VALUES ('unfinished','未完成','说明','完成标准','daily','地点','2099-01-01T00:00:00+00:00','互助','published',?,1,'2026-01-01')", (publisher,))
        response = self.client.get('/api/me/account')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['can_close'])
        self.assertTrue(any(item['href'] == '#/tasks/unfinished' for item in response.json()['blockers']))
        blocked = self.client.post('/api/me/account/close', json={
            'password': self.accounts['publisher']['password'], 'confirmed': True,
        })
        self.assertEqual(blocked.status_code, 409)

    def test_password_reset_changes_only_active_account_and_revokes_sessions(self):
        response = self.register('reset.me')
        self.assertEqual(response.status_code, 201)
        service = AuthService(Database(self.db_path))
        service.reset_password('reset.me', 'replacement-password')
        self.assertEqual(self.login('reset.me', 'correct-horse-battery').status_code, 401)
        self.assertEqual(self.login('reset.me', 'replacement-password').status_code, 200)
        with self.assertRaises(AppError):
            service.reset_password('missing-user', 'replacement-password')


if __name__ == '__main__':
    unittest.main()

