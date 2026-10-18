import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event

from fastapi.testclient import TestClient
from pydantic import ValidationError
from app_factory import create_app
from campus.activity_schemas import ActivityCreate, RegistrationReview
from campus.errors import AppError


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.app = create_app(Path(self.temp) / 'campus.sqlite3', activity_clock=lambda: self.now)
        self.client = self.enterContext(TestClient(self.app))
        self.service = self.app.state.activity_service
        self.auth = self.app.state.auth_service
        accounts = json.loads(self.auth.accounts_path.read_text(encoding='utf-8'))
        self.users = {name: self.auth.login(name, account['password']) for name, account in accounts.items()}
        self.owner = self.users['publisher'][1].id
        self.helper = self.users['helper'][1].id
        self.observer = self.users['observer'][1].id

    def login(self, name):
        self.client.cookies.set('campus_session', self.users[name][0])

    def payload(self, **overrides):
        return dict(title='校园美育讲座', description='介绍艺术与校园生活', location='活动中心',
                    opens_at=(self.now - timedelta(hours=1)).isoformat(),
                    closes_at=(self.now + timedelta(hours=1)).isoformat(),
                    starts_at=(self.now + timedelta(hours=2)).isoformat(),
                    ends_at=(self.now + timedelta(hours=3)).isoformat(), capacity=1,
                    registration_mode='direct', recognition_tags=['aesthetic'],
                    recognition_description='活动方公布美育分认定说明，以正式认定为准',
                    organization_name='测试组织方', information_source='社团公告', contact='站内联系',
                    participation_requirements='本校在读学生') | overrides

    def create(self, **overrides):
        return self.service.create(ActivityCreate.model_validate(self.payload(**overrides)), self.owner)

    def approve(self, registration):
        return self.service.review(registration['id'], self.owner, RegistrationReview(decision='approve'))

    def test_timezone_order_and_positive_integer_validation(self):
        for fields in ({'opens_at': '2030-01-01T00:00:00'}, {'capacity': 0}, {'capacity': 1.5}, {'capacity': True},
                       {'closes_at': '2030-01-01T03:00:00Z'}, {'recognition_tags': []},
                       {'recognition_tags': ['aesthetic', 'aesthetic']}, {'location': '  '}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                ActivityCreate.model_validate(self.payload(**fields))

    def test_any_active_account_can_publish(self):
        token, user = self.auth.register('ordinary.activity', '普通账号', 'secret12')
        self.client.cookies.set('campus_session', token)
        response = self.client.post('/api/activities', json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['owner_id'], user.id)
        self.login('helper')
        self.assertEqual(self.client.post('/api/activities', json=self.payload()).status_code, 201)
        self.assertTrue(self.client.get('/api/auth/me').json()['can_publish_activities'])
        self.login('publisher')
        self.assertTrue(self.client.get('/api/auth/me').json()['can_publish_activities'])
        self.assertEqual(self.client.post('/api/activities', json=self.payload()).status_code, 201)

    def test_legacy_permission_record_no_longer_controls_publishing(self):
        with self.service.database.connect() as conn:
            conn.execute('UPDATE activity_permissions SET can_publish=0 WHERE user_id=?', (self.owner,))
        self.auth.provision_demo_accounts()
        self.login('publisher')
        self.assertTrue(self.client.get('/api/auth/me').json()['can_publish_activities'])
        self.create()
        self.assertEqual(self.client.post('/api/activities', json=self.payload(can_publish_activities=True)).status_code, 422)
        with self.assertRaises(AppError) as caught:
            self.service.create(ActivityCreate.model_validate(self.payload()), 'missing-user')
        self.assertEqual(caught.exception.status_code, 403)

    def test_owner_cannot_register_own_activity(self):
        activity = self.create()
        with self.assertRaises(AppError) as caught:
            self.service.register(activity['id'], self.owner)
        self.assertEqual(caught.exception.status_code, 403)

    def test_open_boundary_uses_server_clock(self):
        opens = self.now + timedelta(seconds=1)
        activity = self.create(opens_at=opens.isoformat())
        self.login('helper')
        self.assertEqual(self.client.post(f"/api/activities/{activity['id']}/registrations", json={}, headers={'Date': 'Fri, 01 Jan 2040 00:00:00 GMT'}).status_code, 409)
        self.assertEqual(self.service.detail(activity['id'])['status'], 'not_open')
        self.now = opens
        self.assertEqual(self.service.register(activity['id'], self.helper)['status'], 'registered')

    def test_exact_cutoff_rejects_new_registration(self):
        activity = self.create()
        self.now = datetime.fromisoformat(activity['closes_at'])
        with self.assertRaises(AppError):
            self.service.register(activity['id'], self.helper)
        self.assertEqual(self.service.detail(activity['id'])['status'], 'closed')

    def test_duplicate_requests_share_one_seat_and_record(self):
        activity = self.create()
        first = self.service.register(activity['id'], self.helper)
        self.assertEqual(self.service.register(activity['id'], self.helper)['id'], first['id'])
        self.now = datetime.fromisoformat(activity['closes_at'])
        self.assertEqual(self.service.register(activity['id'], self.helper)['id'], first['id'])
        self.assertEqual(len(self.service.roster(activity['id'], self.owner)['items']), 1)

    def test_last_seat_concurrent_registration(self):
        activity = self.create()
        gate = Barrier(2)
        def register(user):
            gate.wait()
            return self.service.register(activity['id'], user)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(register, [self.helper, self.observer]))
        self.assertCountEqual([r['status'] for r in results], ['registered', 'waitlisted'])
        self.assertEqual(self.service.detail(activity['id'])['registered_count'], 1)

    def test_concurrent_duplicate_is_idempotent(self):
        activity = self.create()
        gate = Barrier(2)
        def register(_):
            gate.wait()
            return self.service.register(activity['id'], self.helper)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(register, range(2)))
        self.assertEqual(results[0]['id'], results[1]['id'])

    def test_concurrent_approvals_last_seat(self):
        activity = self.create(registration_mode='review')
        registrations = [self.service.register(activity['id'], user, '参加') for user in (self.helper, self.observer)]
        gate = Barrier(2)
        def approve(registration):
            gate.wait()
            return self.approve(registration)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(approve, registrations))
        self.assertCountEqual([r['status'] for r in results], ['registered', 'waitlisted'])

    def test_time_is_rechecked_after_waiting_for_write_lock(self):
        activity = self.create()
        attempted = Event()
        def register():
            attempted.set()
            return self.service.register(activity['id'], self.helper)
        with ThreadPoolExecutor(1) as pool:
            with self.service.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                future = pool.submit(register)
                self.assertTrue(attempted.wait(2))
                self.now = datetime.fromisoformat(activity['closes_at'])
            with self.assertRaises(AppError):
                future.result(timeout=5)

    def test_unauthenticated_mutations_and_roster_are_rejected(self):
        activity = self.create()
        for method, url, payload in (
            ('post', '/api/activities', self.payload()),
            ('post', f"/api/activities/{activity['id']}/registrations", {}),
            ('post', f"/api/activities/{activity['id']}/cancel", {'reason': '取消'}),
            ('get', f"/api/activities/{activity['id']}/registrations", None),
            ('get', '/api/me/registrations', None), ('get', '/api/me/activities', None)):
            response = self.client.request(method, url, **({'json': payload} if payload is not None else {}))
            self.assertEqual(response.status_code, 401)

    def test_second_publisher_cannot_manage_someone_elses_activity(self):
        activity = self.create(registration_mode='review')
        registration = self.service.register(activity['id'], self.helper, '参加')
        with self.service.database.connect() as conn:
            conn.execute('INSERT INTO activity_permissions VALUES (?,1)', (self.observer,))
        self.login('observer')
        self.assertTrue(self.client.get('/api/auth/me').json()['can_publish_activities'])
        self.assertEqual(self.client.get(f"/api/activities/{activity['id']}/registrations").status_code, 403)
        self.assertEqual(self.client.post(f"/api/registrations/{registration['id']}/review", json={'decision': 'approve'}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/activities/{activity['id']}/cancel", json={'reason': '取消'}).status_code, 403)

    def test_no_edit_endpoint_and_cancel_reason_required(self):
        activity = self.create()
        self.login('publisher')
        self.assertEqual(self.client.patch(f"/api/activities/{activity['id']}", json={'capacity': 2}).status_code, 405)
        self.assertEqual(self.client.post(f"/api/activities/{activity['id']}/cancel", json={'reason': '  '}).status_code, 422)
        self.assertEqual(self.service.detail(activity['id'])['status'], 'open')

    def test_review_pending_does_not_occupy_and_requires_note(self):
        activity = self.create(registration_mode='review')
        self.login('helper')
        self.assertEqual(self.client.post(f"/api/activities/{activity['id']}/registrations", json={}).status_code, 422)
        registration = self.service.register(activity['id'], self.helper, '希望参加学习')
        self.assertEqual(registration['status'], 'pending')
        self.assertEqual(self.service.detail(activity['id'])['remaining_capacity'], 1)
        self.assertEqual(self.approve(registration)['status'], 'registered')

    def test_review_approval_order_determines_queue(self):
        activity = self.create(registration_mode='review')
        first = self.service.register(activity['id'], self.helper, '先申请')
        second = self.service.register(activity['id'], self.observer, '后申请')
        self.assertEqual(self.approve(second)['status'], 'registered')
        self.assertEqual(self.approve(first)['waitlist_position'], 1)

    def test_rejection_reason_and_new_attempt_history(self):
        activity = self.create(registration_mode='review')
        first = self.service.register(activity['id'], self.helper, '第一申请')
        self.login('publisher')
        self.assertEqual(self.client.post(f"/api/registrations/{first['id']}/review", json={'decision': 'reject'}).status_code, 422)
        self.service.review(first['id'], self.owner, RegistrationReview(decision='reject', reason='需补充条件'))
        second = self.service.register(activity['id'], self.helper, '补充后的申请')
        self.assertNotEqual(first['id'], second['id'])
        history = self.service.my_registrations(self.helper)['items'][0]['registration_history']
        self.assertEqual([r['status'] for r in history], ['pending', 'rejected'])
        self.assertEqual(history[1]['review_reason'], '需补充条件')

    def test_cancel_promotes_and_old_request_does_not_cancel_new_attempt(self):
        activity = self.create()
        first = self.service.register(activity['id'], self.helper)
        waiting = self.service.register(activity['id'], self.observer)
        self.service.cancel_registration(first['id'], self.helper)
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['status'], 'registered')
        self.assertIn('promoted', [e['action'] for e in self.service.detail(activity['id'], self.observer)['my_registration']['events']])
        new = self.service.register(activity['id'], self.helper)
        self.service.cancel_registration(first['id'], self.helper)
        self.assertEqual(self.service.detail(activity['id'], self.helper)['my_registration']['id'], new['id'])
        self.assertEqual(new['status'], 'waitlisted')
        self.assertNotEqual(waiting['id'], new['id'])

    def test_waitlist_leave_reapply_moves_to_back(self):
        activity = self.create(registration_mode='review')
        # 占位者也使用真实用户记录；第三人授予权限不影响原活动归属。
        with self.service.database.connect() as conn:
            conn.execute('INSERT INTO users (id,username,display_name,salt,password_hash) VALUES (?,?,?,?,?)', ('extra', 'extra', '同学四', '00', 'unused'))
        holder = self.service.register(activity['id'], 'extra', '参加')
        self.approve(holder)
        first = self.approve(self.service.register(activity['id'], self.helper, '参加'))
        second = self.approve(self.service.register(activity['id'], self.observer, '参加'))
        self.service.cancel_registration(first['id'], self.helper)
        last = self.approve(self.service.register(activity['id'], self.helper, '重新参加'))
        self.assertGreater(last['queue_sequence'], second['queue_sequence'])
        self.service.cancel_registration(holder['id'], 'extra')
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['status'], 'registered')
        self.assertEqual(self.service.detail(activity['id'], self.helper)['my_registration']['waitlist_position'], 1)

    def test_pending_cancel_can_reapply(self):
        activity = self.create(registration_mode='review')
        pending = self.service.register(activity['id'], self.helper, '参加')
        self.service.cancel_registration(pending['id'], self.helper)
        second = self.service.register(activity['id'], self.helper, '再次申请')
        self.assertEqual(second['status'], 'pending')
        self.assertNotEqual(second['id'], pending['id'])

    def test_after_close_review_and_promotion_still_work(self):
        activity = self.create(registration_mode='review')
        first = self.service.register(activity['id'], self.helper, '参加')
        second = self.service.register(activity['id'], self.observer, '参加')
        self.now = datetime.fromisoformat(activity['closes_at'])
        self.approve(first)
        self.assertEqual(self.approve(second)['status'], 'waitlisted')
        self.service.cancel_registration(first['id'], self.helper)
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['status'], 'registered')
        with self.assertRaises(AppError):
            self.service.register(activity['id'], self.helper, '再申请')

    def test_start_boundary_expires_pending_and_waitlist(self):
        activity = self.create(registration_mode='review')
        pending = self.service.register(activity['id'], self.helper, '参加')
        self.now = datetime.fromisoformat(activity['starts_at'])
        self.assertEqual(self.service.detail(activity['id'], self.helper)['my_registration']['status'], 'not_selected')
        for operation in (lambda: self.approve(pending), lambda: self.service.cancel_registration(pending['id'], self.helper)):
            with self.assertRaises(AppError):
                operation()
        self.assertEqual(self.service.roster(activity['id'], self.owner)['items'][0]['status'], 'not_selected')
        direct = self.create()
        self.service.register(direct['id'], self.helper)
        self.service.register(direct['id'], self.observer)
        self.now = datetime.fromisoformat(direct['starts_at'])
        self.assertEqual(self.service.my_registrations(self.observer)['items'][0]['my_registration']['status'], 'not_selected')

    def test_whole_cancel_preserves_rejected_and_self_cancelled_history(self):
        activity = self.create(registration_mode='review')
        rejected = self.service.register(activity['id'], self.helper, '参加')
        self.service.review(rejected['id'], self.owner, RegistrationReview(decision='reject', reason='理由'))
        cancelled = self.service.register(activity['id'], self.observer, '参加')
        self.service.cancel_registration(cancelled['id'], self.observer)
        latest = self.service.register(activity['id'], self.helper, '参加')
        self.approve(latest)
        self.service.cancel_activity(activity['id'], self.owner, '组织方调整')
        statuses = [r['status'] for r in self.service.roster(activity['id'], self.owner)['items']]
        self.assertCountEqual(statuses, ['rejected', 'cancelled', 'activity_cancelled'])
        for operation in (lambda: self.service.register(activity['id'], self.observer, '参加'), lambda: self.service.cancel_registration(latest['id'], self.helper)):
            with self.assertRaises(AppError):
                operation()
        self.assertEqual(self.service.search()['total'], 0)

    def test_organizer_cancel_ongoing_but_not_ended_activity(self):
        activity = self.create()
        self.now = datetime.fromisoformat(activity['starts_at'])
        self.assertEqual(self.service.cancel_activity(activity['id'], self.owner, '场地关闭')['status'], 'cancelled')
        later = self.create()
        self.now = datetime.fromisoformat(later['ends_at'])
        with self.assertRaises(AppError):
            self.service.cancel_activity(later['id'], self.owner, '已结束')

    def test_ongoing_activity_cancel_does_not_overwrite_not_selected_result(self):
        activity = self.create(registration_mode='review')
        self.approve(self.service.register(activity['id'], self.helper, '参加'))
        self.approve(self.service.register(activity['id'], self.observer, '参加'))
        self.now = datetime.fromisoformat(activity['starts_at'])
        self.service.cancel_activity(activity['id'], self.owner, '场地临时关闭')
        self.assertEqual(self.service.detail(activity['id'], self.helper)['my_registration']['status'], 'activity_cancelled')
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['status'], 'not_selected')

    def test_cancel_races_register_and_review_without_active_leftovers(self):
        for mode in ('direct', 'review'):
            activity = self.create(registration_mode=mode)
            pending = self.service.register(activity['id'], self.helper, '参加') if mode == 'review' else None
            gate = Barrier(2)
            def operate(cancel):
                gate.wait()
                try:
                    if cancel:
                        return self.service.cancel_activity(activity['id'], self.owner, '取消')
                    return self.approve(pending) if pending else self.service.register(activity['id'], self.helper)
                except AppError:
                    return None
            with ThreadPoolExecutor(2) as pool:
                list(pool.map(operate, [True, False]))
            self.assertEqual(self.service.detail(activity['id'])['status'], 'cancelled')
            self.assertTrue(all(r['status'] == 'activity_cancelled' for r in self.service.roster(activity['id'], self.owner)['items']))

    def test_unauthorized_review_cancel_roster_and_activity_cancel(self):
        activity = self.create(registration_mode='review')
        registration = self.service.register(activity['id'], self.helper, '私有说明')
        self.login('observer')
        for method, url, payload in (
            ('get', f"/api/activities/{activity['id']}/registrations", None),
            ('post', f"/api/registrations/{registration['id']}/review", {'decision': 'approve'}),
            ('post', f"/api/registrations/{registration['id']}/cancel", None),
            ('post', f"/api/activities/{activity['id']}/cancel", {'reason': '冒充'})):
            response = self.client.request(method, url, **({'json': payload} if payload else {}))
            self.assertEqual(response.status_code, 403)
        self.assertNotIn('私有说明', json.dumps(self.client.get(f"/api/activities/{activity['id']}").json(), ensure_ascii=False))
        self.assertEqual(self.client.get('/api/me/registrations').json()['items'], [])

    def test_public_detail_contains_no_roster(self):
        activity = self.create()
        self.service.register(activity['id'], self.helper, '不要公开')
        response = self.client.get(f"/api/activities/{activity['id']}").json()
        self.assertIsNone(response['my_registration'])
        self.assertNotIn('不要公开', json.dumps(response, ensure_ascii=False))
        self.assertNotIn('接取者小陈', json.dumps(response, ensure_ascii=False))
        self.client.cookies.set('campus_session', 'expired-cookie')
        expired = self.client.get(f"/api/activities/{activity['id']}")
        self.assertEqual(expired.status_code, 200)
        self.assertIsNone(expired.json()['my_registration'])

    def test_my_latest_record_history_and_refresh_persist(self):
        activity = self.create()
        first = self.service.register(activity['id'], self.helper)
        self.service.cancel_registration(first['id'], self.helper)
        last = self.service.register(activity['id'], self.helper)
        self.service.database.initialize()
        self.login('helper')
        result = self.client.get('/api/me/registrations').json()['items']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['my_registration']['id'], last['id'])
        self.assertEqual(len(result[0]['registration_history']), 2)

    def test_separate_search_tag_and_pagination(self):
        self.create(title='艺术体验', recognition_tags=['aesthetic', 'second_class'])
        self.create(title='形势政策', recognition_tags=['ideological'])
        self.assertEqual(self.service.search(tag='second_class')['total'], 1)
        self.assertEqual(self.service.search(keyword='艺术体验')['total'], 1)
        self.assertEqual(self.service.search(limit=1, offset=1)['total'], 2)
        self.assertEqual(len(self.service.search(limit=1, offset=1)['items']), 1)
        self.assertEqual(self.client.get('/api/tasks').json()['total'], 0)
        self.assertEqual(self.service.my_activities(self.helper)['items'], [])

    def test_new_signup_cannot_skip_existing_waitlist(self):
        activity = self.create()
        holder = self.service.register(activity['id'], self.helper)
        waiter = self.service.register(activity['id'], self.observer)
        # 模拟尚未递补的空位，验证入口也会优先补入已有候补。
        with self.service.database.connect() as conn:
            conn.execute("UPDATE activity_registrations SET status='cancelled' WHERE id=?", (holder['id'],))
        new = self.service.register(activity['id'], self.helper)
        self.assertEqual(new['status'], 'waitlisted')
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['id'], waiter['id'])
        self.assertEqual(self.service.detail(activity['id'], self.observer)['my_registration']['status'], 'registered')

    def test_event_history_has_publish_reviews_and_promotion(self):
        activity = self.create(registration_mode='review')
        first = self.service.register(activity['id'], self.helper, '参加')
        second = self.service.register(activity['id'], self.observer, '参加')
        self.approve(first)
        self.approve(second)
        self.service.cancel_registration(first['id'], self.helper)
        actions = [e['action'] for e in self.service.roster(activity['id'], self.owner)['events']]
        self.assertEqual(actions, ['published', 'applied', 'applied', 'approved', 'approved', 'cancelled', 'promoted'])


if __name__ == '__main__':
    unittest.main()
