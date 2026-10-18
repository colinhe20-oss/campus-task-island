# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app_factory import create_app
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

    def test_account_profile_has_no_closure_actions(self):
        user_id = self.register().json()['id']
        info = self.client.get('/api/me/account')
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json(), {'id': user_id, 'username': 'new.user', 'display_name': '新同学'})
        schema = self.client.get('/openapi.json').json()
        self.assertNotIn('/api/me/account/close', schema['paths'])
        self.assertNotIn('CloseAccountInput', schema['components']['schemas'])
        for logged_in in (True, False):
            if not logged_in:
                self.client.post('/api/auth/logout')
            response = self.client.post('/api/me/account/close', json={
                'password': 'correct-horse-battery', 'confirmed': True,
            })
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.login('new.user', 'correct-horse-battery').status_code, 200)

    def test_logout_revokes_only_current_session_and_allows_relogin(self):
        registered = self.register().json()
        current_token = self.client.cookies.get('campus_session')
        auth = self.client.app.state.auth_service
        other_token, _ = auth.login('new.user', 'correct-horse-battery')
        response = self.client.post('/api/auth/logout')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.cookies.get('campus_session'))
        self.assertEqual(self.client.get('/api/me/account').status_code, 401)
        with self.assertRaises(AppError):
            auth.current_user(current_token)
        self.assertEqual(auth.current_user(other_token).id, registered['id'])
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        logged_in = self.login('new.user', 'correct-horse-battery')
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(logged_in.json()['id'], registered['id'])
        self.assertEqual(logged_in.json()['display_name'], registered['display_name'])

    def test_logout_preserves_unfinished_business_settlement_and_private_history(self):
        from datetime import datetime, timedelta, timezone
        from backend.fake_backend import FakeBackend
        from campus.schemas import TaskCreate, TASK_CREATE_EXAMPLE
        from campus.volunteer_schemas import VolunteerCreate
        user = self.register().json()
        app = self.client.app
        service, auth = app.state.task_service, app.state.auth_service
        _, helper = auth.login('helper', self.accounts['helper']['password'])
        at = datetime.now(timezone.utc)
        fields = TASK_CREATE_EXAMPLE | {'deadline': (at+timedelta(days=1)).isoformat(),
                                        'reward_type': 'paid', 'reward_amount_fen': 2550, 'reward': '线下结算'}
        unfinished = service.create_task(TaskCreate.model_validate(fields), user['id'])
        completed = service.create_task(TaskCreate.model_validate(fields), user['id'])
        application = service.apply(completed.id, helper.id, '可以完成')
        service.accept_application(application.id, user['id'])
        service.submit(completed.id, helper.id, '完成内容')
        service.review(completed.id, user['id'], 'accept', '')
        self.assertFalse(service.terms.settlement(completed.id, user['id'])['both_confirmed'])
        stamp = lambda hours: (at+timedelta(hours=hours)).isoformat()
        volunteer = app.state.volunteer_service
        volunteer.clock = lambda: at
        activity = volunteer.create(VolunteerCreate.model_validate(dict(
            title='待核验服务', description='测试服务', organization_name='测试组织',
            information_source='测试公告', contact='测试联系', recognition_conditions='实际参与',
            starts_at=stamp(1), ends_at=stamp(2), opens_at=stamp(-1), closes_at=stamp(.5),
            registration_mode='direct', jobs=[dict(name='测试岗位', description='协助', requirements='按时到场',
                location='校园', starts_at=stamp(1), ends_at=stamp(2), capacity=1,
                estimated_minutes=60, estimated_hours_description='按实际参与确认')],
        )), user['id'])
        volunteer.register(activity['jobs'][0]['id'], helper.id)
        volunteer.clock = lambda: at+timedelta(hours=3)
        app.state.guide_service.backend_factory = lambda: FakeBackend([
            {'tool_calls': [{'name': 'update_task_draft', 'arguments': {'title': '保留草稿'}}]},
            {'content': '请补充其他信息'},
        ])
        reply = self.client.post('/api/guide/chat', json={'message': '帮我整理草稿'})
        self.assertEqual(reply.status_code, 200, reply.text)
        conversation_id = reply.json()['conversation_id']

        def snapshot():
            with service.database.connect() as connection:
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='sessions'")]
                return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
                        for table in tables}

        before = snapshot()
        self.assertTrue(before['notifications'])
        self.assertTrue(before['guide_task_drafts'])
        self.assertTrue(before['guide_runs'])
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(before, snapshot())
        self.assertEqual(self.login('new.user', 'correct-horse-battery').status_code, 200)
        self.assertEqual(self.client.get(f'/api/tasks/{unfinished.id}').json()['status'], 'published')
        history = self.client.get(f'/api/guide/conversations/{conversation_id}')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['draft']['fields']['title'], '保留草稿')
        self.assertEqual(before, snapshot())

    def test_legacy_closed_accounts_are_not_automatically_restored(self):
        user_id = self.register('legacy.closed').json()['id']
        with self.client.app.state.task_service.database.connect() as connection:
            connection.execute("UPDATE users SET account_status='closed',closed_at='2026-01-01',display_name='历史账号' WHERE id=?", (user_id,))
        self.client.app.state.task_service.initialize()
        self.assertEqual(self.login('legacy.closed', 'correct-horse-battery').status_code, 401)
        self.assertEqual(self.client.get('/api/me/account').status_code, 401)
        with self.client.app.state.task_service.database.connect() as connection:
            row = connection.execute('SELECT account_status,closed_at,display_name FROM users WHERE id=?', (user_id,)).fetchone()
        self.assertEqual(tuple(row), ('closed', '2026-01-01', '历史账号'))

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

