"""站内活动报名。所有状态变更先获取 SQLite 写锁，再读取服务端时间。"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from .activity_schemas import ActivityCreate, RegistrationReview
from .db import Database
from .errors import AppError
from .notifications import registration_event

ACTIVE = ('pending', 'registered', 'waitlisted')


class ActivityService:
    def __init__(self, database: Database, clock=None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def now(self):
        value = self.clock()
        if value.utcoffset() is None:
            raise ValueError('activity clock must be timezone aware')
        return value.astimezone(timezone.utc)

    @staticmethod
    def _activity(conn, activity_id):
        row = conn.execute('SELECT * FROM activities WHERE id=?', (activity_id,)).fetchone()
        if row is None:
            raise AppError('活动不存在', 404)
        return dict(row)

    @staticmethod
    def _registration(conn, registration_id):
        row = conn.execute('SELECT * FROM activity_registrations WHERE id=?', (registration_id,)).fetchone()
        if row is None:
            raise AppError('报名记录不存在', 404)
        return dict(row)

    @staticmethod
    def _owner(activity, user_id):
        if activity['owner_id'] != user_id:
            raise AppError('只有活动负责人可以执行此操作', 403)

    @staticmethod
    def _processing(activity, now):
        if activity['cancelled_at']:
            raise AppError('活动已取消')
        if now >= datetime.fromisoformat(activity['starts_at']):
            raise AppError('活动已开始，报名处理已停止')

    @staticmethod
    def _event(conn, activity_id, registration_id, actor_id, action, now, reason=''):
        event_id=uuid4().hex
        conn.execute('INSERT INTO activity_events VALUES (?,?,?,?,?,?,?,?)',
                     (event_id, activity_id, registration_id, actor_id, action, reason, now.isoformat(),
                      conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM activity_events WHERE activity_id=?', (activity_id,)).fetchone()[0]))
        registration_event(conn,'activity',activity_id,registration_id,action,event_id,now.isoformat())

    def _set_status(self, conn, registration, status, now, actor_id, action, reason=''):
        conn.execute('UPDATE activity_registrations SET status=?,updated_at=?,review_reason=? WHERE id=?',
                     (status, now.isoformat(), reason or registration['review_reason'], registration['id']))
        self._event(conn, registration['activity_id'], registration['id'], actor_id, action, now, reason)

    def _promote(self, conn, activity, now, actor_id):
        """调用者已获得写锁；只有活动开始前才调用。"""
        occupied = conn.execute("SELECT COUNT(*) FROM activity_registrations WHERE activity_id=? AND status='registered'", (activity['id'],)).fetchone()[0]
        remaining = activity['capacity'] - occupied
        if remaining > 0:
            rows = conn.execute("SELECT * FROM activity_registrations WHERE activity_id=? AND status='waitlisted' ORDER BY queue_sequence LIMIT ?", (activity['id'], remaining)).fetchall()
            for row in rows:
                self._set_status(conn, dict(row), 'registered', now, actor_id, 'promoted')

    def _seat(self, conn, activity, registration_id, now):
        occupied = conn.execute("SELECT COUNT(*) FROM activity_registrations WHERE activity_id=? AND status='registered'", (activity['id'],)).fetchone()[0]
        if occupied < activity['capacity']:
            return 'registered', None
        sequence = activity['queue_counter'] + 1
        conn.execute('UPDATE activities SET queue_counter=? WHERE id=?', (sequence, activity['id']))
        conn.execute('UPDATE activity_registrations SET queue_sequence=? WHERE id=?', (sequence, registration_id))
        return 'waitlisted', sequence

    def _registration_read(self, conn, registration, activity, now, *, roster=False):
        status = registration['status']
        if status in ('pending', 'waitlisted') and now >= datetime.fromisoformat(activity['starts_at']):
            status = 'not_selected'
        elif status in ACTIVE and activity['cancelled_at']:
            status = 'activity_cancelled'
        position = None
        if status == 'waitlisted':
            position = conn.execute("SELECT COUNT(*) FROM activity_registrations WHERE activity_id=? AND status='waitlisted' AND queue_sequence<=?", (activity['id'], registration['queue_sequence'])).fetchone()[0]
        result = {key: registration[key] for key in ('id', 'activity_id', 'application_note', 'created_at', 'updated_at', 'review_reason', 'queue_sequence')}
        result.update(status=status, waitlist_position=position,
                      can_cancel=status in ACTIVE and now < datetime.fromisoformat(activity['starts_at']) and not activity['cancelled_at'])
        result['events'] = [dict(row) for row in conn.execute('SELECT action,reason,created_at FROM activity_events WHERE registration_id=? ORDER BY sequence', (registration['id'],))]
        if roster:
            person = conn.execute('SELECT display_name FROM users WHERE id=?', (registration['user_id'],)).fetchone()
            result.update(user_id=registration['user_id'], display_name=person['display_name'])
        return result

    def _read(self, conn, activity, now, user_id=None):
        # 白名单返回公共字段，内部计数器与他人申请均不外泄。
        fields = set(ActivityCreate.model_fields) | {'id', 'owner_id', 'created_at', 'cancelled_at', 'cancellation_reason'}
        result = {key: activity[key] for key in fields}
        result['recognition_tags'] = json.loads(activity['recognition_tags'])
        occupied = conn.execute("SELECT COUNT(*) FROM activity_registrations WHERE activity_id=? AND status='registered'", (activity['id'],)).fetchone()[0]
        result['registered_count'] = occupied
        result['remaining_capacity'] = max(0, activity['capacity'] - occupied)
        boundaries = {key: datetime.fromisoformat(activity[key]) for key in ('opens_at', 'closes_at', 'starts_at', 'ends_at')}
        if activity['cancelled_at']:
            status = 'cancelled'
        elif now < boundaries['opens_at']:
            status = 'not_open'
        elif now >= boundaries['closes_at']:
            status = 'closed'
        elif occupied >= activity['capacity']:
            status = 'full'
        else:
            status = 'open'
        result.update(status=status, server_time=now.isoformat(),
                      next_boundary=min((v for v in boundaries.values() if v > now), default=None),
                      can_register=not activity['cancelled_at'] and boundaries['opens_at'] <= now < boundaries['closes_at'] and user_id != activity['owner_id'],
                      can_review=user_id == activity['owner_id'] and not activity['cancelled_at'] and now < boundaries['starts_at'],
                      can_cancel_activity=user_id == activity['owner_id'] and not activity['cancelled_at'] and now < boundaries['ends_at'],
                      is_owner=user_id == activity['owner_id'], my_registration=None)
        if user_id:
            row = conn.execute('SELECT * FROM activity_registrations WHERE activity_id=? AND user_id=? ORDER BY attempt DESC LIMIT 1', (activity['id'], user_id)).fetchone()
            if row:
                result['my_registration'] = self._registration_read(conn, dict(row), activity, now)
                if result['my_registration']['status'] in ACTIVE:
                    result['can_register'] = False
        return result

    def create(self, body: ActivityCreate, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = self.now()
            if not conn.execute("SELECT 1 FROM users WHERE id=? AND account_status='active'", (user_id,)).fetchone():
                raise AppError('请使用有效账号发布活动', 403)
            if body.starts_at <= now:
                raise AppError('活动开始时间必须晚于当前时间', 422)
            fields = body.model_dump(mode='json')
            for key in ('opens_at', 'closes_at', 'starts_at', 'ends_at'):
                fields[key] = getattr(body, key).astimezone(timezone.utc).isoformat()
            fields['recognition_tags'] = json.dumps(fields['recognition_tags'])
            fields.update(id=uuid4().hex, owner_id=user_id, created_at=now.isoformat())
            conn.execute(f"INSERT INTO activities ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fields.values()))
            self._event(conn, fields['id'], None, user_id, 'published', now)
            return self._read(conn, self._activity(conn, fields['id']), now, user_id)

    def detail(self, activity_id, user_id=None):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            return self._read(conn, self._activity(conn, activity_id), self.now(), user_id)

    def search(self, keyword='', tag=None, limit=20, offset=0):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            now = self.now()
            rows = conn.execute('SELECT * FROM activities WHERE cancelled_at IS NULL AND ends_at>? ORDER BY starts_at,id', (now.isoformat(),)).fetchall()
            rows = [dict(r) for r in rows if (not tag or tag in json.loads(r['recognition_tags'])) and (not keyword or keyword.casefold() in (r['title'] + r['description'] + r['organization_name']).casefold())]
            items = [self._read(conn, r, now) for r in rows[offset:offset + limit]]
            return dict(items=items, total=len(rows), limit=limit, offset=offset, server_time=now.isoformat(),
                        next_boundary=min((item['next_boundary'] for item in items if item['next_boundary']), default=None))

    def register(self, activity_id, user_id, application_note=''):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = self.now()
            activity = self._activity(conn, activity_id)
            if activity['owner_id'] == user_id:
                raise AppError('负责人不能报名自己发布的活动', 403)
            self._processing(activity, now)
            # 有效重复请求返回原记录，即使重试发生在报名截止后，也不新占名额。
            row = conn.execute("SELECT * FROM activity_registrations WHERE activity_id=? AND user_id=? AND status IN ('pending','registered','waitlisted')", (activity_id, user_id)).fetchone()
            if row:
                return self._registration_read(conn, dict(row), activity, now)
            if not datetime.fromisoformat(activity['opens_at']) <= now < datetime.fromisoformat(activity['closes_at']):
                raise AppError('当前不在报名开放时间内')
            if activity['registration_mode'] == 'review' and not application_note.strip():
                raise AppError('审核报名必须填写申请说明', 422)
            self._promote(conn, activity, now, user_id)
            attempt = conn.execute('SELECT COALESCE(MAX(attempt),0)+1 FROM activity_registrations WHERE activity_id=? AND user_id=?', (activity_id, user_id)).fetchone()[0]
            registration_id = uuid4().hex
            conn.execute("INSERT INTO activity_registrations (id,activity_id,user_id,attempt,application_note,status,created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?)", (registration_id, activity_id, user_id, attempt, application_note, now.isoformat(), now.isoformat()))
            if activity['registration_mode'] == 'direct':
                status, _ = self._seat(conn, activity, registration_id, now)
                conn.execute('UPDATE activity_registrations SET status=? WHERE id=?', (status, registration_id))
            self._event(conn, activity_id, registration_id, user_id, 'applied' if activity['registration_mode'] == 'review' else 'registered' if status == 'registered' else 'waitlisted', now)
            return self._registration_read(conn, self._registration(conn, registration_id), activity, now)

    def review(self, registration_id, user_id, body: RegistrationReview):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = self.now()
            registration = self._registration(conn, registration_id)
            activity = self._activity(conn, registration['activity_id'])
            self._owner(activity, user_id)
            self._processing(activity, now)
            if registration['status'] != 'pending' or activity['registration_mode'] != 'review':
                raise AppError('该申请已处理，请刷新后查看结果')
            self._promote(conn, activity, now, user_id)
            if body.decision == 'approve':
                status, _ = self._seat(conn, activity, registration_id, now)
            else:
                status = 'rejected'
            self._set_status(conn, registration, status, now, user_id, 'approved' if body.decision == 'approve' else 'rejected', body.reason)
            return self._registration_read(conn, self._registration(conn, registration_id), activity, now, roster=True)

    def cancel_registration(self, registration_id, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = self.now()
            registration = self._registration(conn, registration_id)
            if registration['user_id'] != user_id:
                raise AppError('只能取消本人的报名', 403)
            activity = self._activity(conn, registration['activity_id'])
            self._processing(activity, now)
            if registration['status'] == 'cancelled':
                return self._registration_read(conn, registration, activity, now)
            if registration['status'] not in ACTIVE:
                raise AppError('该报名已结束，不能取消')
            self._set_status(conn, registration, 'cancelled', now, user_id, 'cancelled')
            self._promote(conn, activity, now, user_id)
            return self._registration_read(conn, self._registration(conn, registration_id), activity, now)

    def cancel_activity(self, activity_id, user_id, reason):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = self.now()
            activity = self._activity(conn, activity_id)
            self._owner(activity, user_id)
            if activity['cancelled_at']:
                return self._read(conn, activity, now, user_id)
            if now >= datetime.fromisoformat(activity['ends_at']):
                raise AppError('活动已结束，不能取消')
            conn.execute('UPDATE activities SET cancelled_at=?,cancellation_reason=? WHERE id=?', (now.isoformat(), reason, activity_id))
            # 开始后，未转正者已是“未获名额”，取消整场不能覆盖这一历史结果。
            eligible = ACTIVE if now < datetime.fromisoformat(activity['starts_at']) else ('registered',)
            marks = ','.join('?' for _ in eligible)
            for row in conn.execute(f'SELECT * FROM activity_registrations WHERE activity_id=? AND status IN ({marks})', (activity_id, *eligible)).fetchall():
                self._set_status(conn, dict(row), 'activity_cancelled', now, user_id, 'activity_cancelled', reason)
            self._event(conn, activity_id, None, user_id, 'activity_cancelled', now, reason)
            return self._read(conn, self._activity(conn, activity_id), now, user_id)

    def roster(self, activity_id, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            now = self.now()
            activity = self._activity(conn, activity_id)
            self._owner(activity, user_id)
            rows = conn.execute('SELECT * FROM activity_registrations WHERE activity_id=? ORDER BY created_at,attempt,id', (activity_id,)).fetchall()
            return dict(items=[self._registration_read(conn, dict(row), activity, now, roster=True) for row in rows],
                        events=[dict(row) for row in conn.execute('SELECT registration_id,action,reason,created_at FROM activity_events WHERE activity_id=? ORDER BY sequence', (activity_id,))],
                        server_time=now.isoformat(), next_boundary=self._read(conn, activity, now)['next_boundary'])

    def my_activities(self, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            now = self.now()
            items = [self._read(conn, dict(row), now, user_id) for row in conn.execute('SELECT * FROM activities WHERE owner_id=? ORDER BY created_at DESC,id', (user_id,))]
            return self._collection(items, now)

    @staticmethod
    def _collection(items, now):
        return dict(items=items, server_time=now.isoformat(), next_boundary=min((i['next_boundary'] for i in items if i['next_boundary']), default=None))

    def my_registrations(self, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            now = self.now()
            activities = conn.execute('SELECT DISTINCT a.* FROM activities a JOIN activity_registrations r ON r.activity_id=a.id WHERE r.user_id=? ORDER BY a.starts_at DESC,a.id', (user_id,)).fetchall()
            items = []
            for row in activities:
                activity = dict(row)
                item = self._read(conn, activity, now, user_id)
                item['registration_history'] = [self._registration_read(conn, dict(r), activity, now) for r in conn.execute('SELECT * FROM activity_registrations WHERE activity_id=? AND user_id=? ORDER BY attempt DESC', (activity['id'], user_id))]
                items.append(item)
            return self._collection(items, now)
