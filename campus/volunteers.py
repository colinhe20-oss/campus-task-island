from contextlib import nullcontext
"""独立志愿业务：按岗位排队，按报名记录核验，所有写操作在获取写锁后读时钟。"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from .activities import ActivityService, ACTIVE
from .errors import AppError
from .notifications import registration_event
from .volunteer_schemas import VolunteerCreate, ParticipationInput, HoursInput


def dt(value):
    return datetime.fromisoformat(value)


class VolunteerService:
    def __init__(self, database, clock=None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    now = ActivityService.now
    _owner = staticmethod(ActivityService._owner)

    @staticmethod
    def _get(conn, table, identifier):
        # table 仅由下面固定的内部调用传入。
        row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise AppError('志愿活动、岗位或报名记录不存在', 404)
        return dict(row)

    @staticmethod
    def _event(conn, activity_id, registration_id, actor, action, now, reason=''):
        cursor=conn.execute('INSERT INTO volunteer_events (activity_id,registration_id,actor_id,action,reason,created_at) VALUES (?,?,?,?,?,?)',
                     (activity_id, registration_id, actor, action, reason, now.isoformat()))
        registration_event(conn,'volunteer',activity_id,registration_id,action,str(cursor.lastrowid),now.isoformat())

    def _context(self, conn, registration_id):
        r = self._get(conn, 'volunteer_registrations', registration_id)
        return r, self._get(conn, 'volunteer_activities', r['activity_id']), self._get(conn, 'volunteer_jobs', r['job_id'])

    @staticmethod
    def _processing(a, j, now):
        if a['cancelled_at']:
            raise AppError('志愿活动已取消')
        if now >= dt(j['starts_at']):
            raise AppError('所报岗位已开始，报名处理已停止')

    def _transition(self, conn, r, status, actor, now, action, reason=''):
        conn.execute('UPDATE volunteer_registrations SET status=?,updated_at=?,review_reason=?,registered_at=CASE WHEN ?=\'registered\' THEN COALESCE(registered_at,?) ELSE registered_at END WHERE id=?',
                     (status, now.isoformat(), reason or r['review_reason'], status, now.isoformat(), r['id']))
        self._event(conn, r['activity_id'], r['id'], actor, action, now, reason)

    def _occupied(self, conn, job_id):
        return conn.execute("SELECT COUNT(*) FROM volunteer_registrations WHERE job_id=? AND status='registered'", (job_id,)).fetchone()[0]

    def _promote(self, conn, a, j, actor, now):
        self._processing(a, j, now)
        remaining = j['capacity'] - self._occupied(conn, j['id'])
        for row in conn.execute("SELECT * FROM volunteer_registrations WHERE job_id=? AND status='waitlisted' ORDER BY queue_sequence LIMIT ?", (j['id'], max(0, remaining))).fetchall():
            self._transition(conn, dict(row), 'registered', actor, now, 'promoted')

    def _seat(self, conn, j, r, actor, now, action, reason=''):
        status = 'registered'
        if self._occupied(conn, j['id']) >= j['capacity']:
            status = 'waitlisted'
            conn.execute('UPDATE volunteer_jobs SET queue_counter=queue_counter+1 WHERE id=?', (j['id'],))
            number = conn.execute('SELECT queue_counter FROM volunteer_jobs WHERE id=?', (j['id'],)).fetchone()[0]
            conn.execute('UPDATE volunteer_registrations SET queue_sequence=? WHERE id=?', (number, r['id']))
        self._transition(conn, r, status, actor, now, action if action == 'approved' else status, reason)

    @staticmethod
    def _qualified(r, a, j, now):
        if now < dt(j['starts_at']) or not r['registered_at'] or dt(r['registered_at']) >= dt(j['starts_at']):
            return False
        return r['status'] == 'registered' or (r['status'] == 'activity_cancelled' and a['cancelled_at'] and dt(a['cancelled_at']) >= dt(j['starts_at']))

    @staticmethod
    def _maximum(a, j, now):
        stop = min(now, dt(j['ends_at']))
        if a['cancelled_at']:
            stop = min(stop, dt(a['cancelled_at']))
        return max(0, int((stop-dt(j['starts_at'])).total_seconds() // 60))

    def _record(self, conn, r, a, j, now):
        if not self._qualified(r, a, j, now):
            return None
        row = conn.execute('SELECT * FROM volunteer_participation WHERE registration_id=?', (r['id'],)).fetchone()
        record = dict(row) if row else dict(registration_id=r['id'], attendance=None, actual_minutes=0, description='', confirmed_minutes=None, hours_reason='', version=0, updated_by=None, updated_at=None)
        ended = now >= dt(j['ends_at']) or a['cancelled_at'] is not None
        record.update(status='confirmed' if record['confirmed_minutes'] is not None else 'pending_verification' if ended else 'in_service',
                      can_confirm=ended and row is not None, maximum_actual_minutes=self._maximum(a, j, now),
                      official_status='not_connected', official_minutes=None,
                      versions=[dict(v) | {'before_fields':json.loads(v['before_fields']), 'after_fields':json.loads(v['after_fields'])} for v in conn.execute('SELECT version,action,reason,created_at,actor_id,before_fields,after_fields FROM volunteer_record_versions WHERE registration_id=? ORDER BY version DESC', (r['id'],))])
        return record

    def _registration_read(self, conn, r, a, j, now, owner=False):
        status = r['status']
        if status in ('pending','waitlisted') and now >= dt(j['starts_at']):
            status = 'not_selected'
        position = None
        if status == 'waitlisted':
            position = conn.execute("SELECT COUNT(*) FROM volunteer_registrations WHERE job_id=? AND status='waitlisted' AND queue_sequence<=?", (j['id'], r['queue_sequence'])).fetchone()[0]
        result = {key:r[key] for key in ('id','activity_id','job_id','application_note','review_reason','queue_sequence','created_at','updated_at')}
        result.update(status=status, job_name=j['name'], starts_at=j['starts_at'], ends_at=j['ends_at'],
                      location=j['location'], estimated_minutes=j['estimated_minutes'], waitlist_position=position,
                      can_cancel=r['status'] in ACTIVE and not a['cancelled_at'] and now < dt(j['starts_at']),
                      can_review=owner and r['status']=='pending' and not a['cancelled_at'] and now < dt(j['starts_at']),
                      service_record=self._record(conn,r,a,j,now),
                      events=[dict(e) for e in conn.execute('SELECT action,reason,created_at FROM volunteer_events WHERE registration_id=? ORDER BY id', (r['id'],))])
        if owner:
            result.update(user_id=r['user_id'], display_name=conn.execute('SELECT display_name FROM users WHERE id=?', (r['user_id'],)).fetchone()[0])
        return result

    def _read(self, conn, a, now, user_id=None, history=False):
        result = dict(a)
        boundaries = [dt(a[k]) for k in ('opens_at','closes_at','starts_at','ends_at')]
        jobs = []
        for row in conn.execute('SELECT * FROM volunteer_jobs WHERE activity_id=? ORDER BY position', (a['id'],)):
            j = dict(row)
            boundaries.extend([dt(j['starts_at']),dt(j['ends_at'])])
            j.pop('queue_counter')
            j['registered_count'] = self._occupied(conn,j['id'])
            j['remaining_capacity'] = max(0,j['capacity']-j['registered_count'])
            jobs.append(j)
        status = 'cancelled' if a['cancelled_at'] else 'not_open' if now < dt(a['opens_at']) else 'closed' if now >= dt(a['closes_at']) else 'full' if all(j['remaining_capacity']==0 for j in jobs) else 'open'
        result.update(jobs=jobs, status=status, server_time=now.isoformat(), next_boundary=min((v for v in boundaries if v>now),default=None),
                      is_owner=user_id==a['owner_id'], can_cancel_activity=user_id==a['owner_id'] and not a['cancelled_at'] and now<dt(a['ends_at']),
                      can_register=not a['cancelled_at'] and dt(a['opens_at'])<=now<dt(a['closes_at']) and user_id!=a['owner_id'], my_registration=None)
        if user_id:
            rows = conn.execute('SELECT * FROM volunteer_registrations WHERE activity_id=? AND user_id=? ORDER BY attempt DESC', (a['id'],user_id)).fetchall()
            if rows:
                read = lambda row:self._registration_read(conn,dict(row),a,self._get(conn,'volunteer_jobs',row['job_id']),now)
                result['my_registration'] = read(rows[0])
                # 已开始的未获名额记录仍禁止绕过“取消后换岗”的约定；截止已在最早岗位前。
                if any(r['status'] in ACTIVE for r in rows):
                    result['can_register'] = False
                if history:
                    result['registration_history'] = [read(r) for r in rows]
        return result

    def create(self, body:VolunteerCreate, user_id, *, connection=None):
        with (nullcontext(connection) if connection is not None else self.database.connect()) as conn:
            if not conn.in_transaction: conn.execute('BEGIN IMMEDIATE')
            now=self.now()
            if not conn.execute("SELECT 1 FROM users WHERE id=? AND account_status='active'",(user_id,)).fetchone():
                raise AppError('请使用有效账号发布志愿活动',403)
            if body.starts_at <= now:
                raise AppError('活动开始必须晚于当前时间',422)
            fields=body.model_dump(mode='json',exclude={'jobs'})
            for key in ('starts_at','ends_at','opens_at','closes_at'):
                fields[key]=getattr(body,key).astimezone(timezone.utc).isoformat()
            fields.update(id=uuid4().hex,owner_id=user_id,created_at=now.isoformat())
            conn.execute(f"INSERT INTO volunteer_activities ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",tuple(fields.values()))
            for position,job in enumerate(body.jobs,1):
                values=job.model_dump(mode='json')
                for key in ('starts_at','ends_at'):
                    values[key]=getattr(job,key).astimezone(timezone.utc).isoformat()
                values.update(id=uuid4().hex,activity_id=fields['id'],position=position)
                conn.execute(f"INSERT INTO volunteer_jobs ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))
            self._event(conn,fields['id'],None,user_id,'published',now)
            return self._read(conn,self._get(conn,'volunteer_activities',fields['id']),now,user_id)

    def detail(self, activity_id, user_id=None):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            return self._read(conn,self._get(conn,'volunteer_activities',activity_id),self.now(),user_id)

    @staticmethod
    def _collection(items, now):
        return dict(items=items,server_time=now.isoformat(),next_boundary=min((i['next_boundary'] for i in items if i['next_boundary']),default=None))

    def search(self, keyword='',limit=20,offset=0):
        with self.database.connect() as conn:
            conn.execute('BEGIN'); now=self.now()
            rows=[dict(r) for r in conn.execute('SELECT * FROM volunteer_activities WHERE cancelled_at IS NULL AND ends_at>? ORDER BY starts_at,id',(now.isoformat(),))]
            rows=[r for r in rows if not keyword or keyword.casefold() in (r['title']+r['description']+r['organization_name']+' '.join(
                ' '.join(str(value or '') for value in j) for j in conn.execute(
                    'SELECT name,description,requirements,location FROM volunteer_jobs WHERE activity_id=?',(r['id'],)))).casefold()]
            return self._collection([self._read(conn,r,now) for r in rows[offset:offset+limit]],now)|dict(total=len(rows),limit=limit,offset=offset)

    def search_jobs(self, keyword='', limit=5, offset=0, *, user_id=None):
        """Search and paginate jobs, with capacity and own registration from one snapshot."""
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            now = self.now()
            needle = keyword.casefold()
            fields = ('title', 'activity_description', 'organization_name',
                      'name', 'description', 'requirements', 'location')
            candidates = conn.execute('''SELECT a.id AS activity_id, j.id AS job_id,
                a.title, a.description AS activity_description, a.organization_name,
                j.name, j.description, j.requirements, j.location
                FROM volunteer_activities a JOIN volunteer_jobs j ON j.activity_id=a.id
                WHERE a.cancelled_at IS NULL AND a.ends_at>?
                ORDER BY a.starts_at,a.id,j.position,j.id''', (now.isoformat(),))
            # Keep Python's Unicode casefold semantics; count every matching job
            # before slicing. Only current-page activities need detailed reads.
            matches = [(row['activity_id'], row['job_id']) for row in candidates
                       if not needle or needle in ' '.join(row[field] for field in fields).casefold()]
            details, items = {}, []
            for activity_id, job_id in matches[offset:offset+limit]:
                if activity_id not in details:
                    activity = self._read(conn, self._get(conn, 'volunteer_activities', activity_id), now, user_id)
                    details[activity_id] = (activity, {job['id']: job for job in activity['jobs']})
                activity, jobs = details[activity_id]
                items.append(dict(jobs[job_id]) | {
                    'title': activity['title'], 'activity_status': activity['status'],
                    'my_registration': activity['my_registration'], 'next_boundary': activity['next_boundary'],
                })
            return self._collection(items, now) | dict(total=len(matches), limit=limit, offset=offset)

    def register(self, job_id, user_id, note=''):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); now=self.now()
            j=self._get(conn,'volunteer_jobs',job_id); a=self._get(conn,'volunteer_activities',j['activity_id'])
            if user_id==a['owner_id']:
                raise AppError('负责人不能报名自己发布的志愿活动',403)
            self._processing(a,j,now)
            prior=conn.execute("SELECT * FROM volunteer_registrations WHERE activity_id=? AND user_id=? AND status IN ('pending','registered','waitlisted')",(a['id'],user_id)).fetchone()
            if prior:
                if prior['job_id']!=job_id:
                    raise AppError('同一活动最多一个有效岗位，请先取消原报名')
                return self._registration_read(conn,dict(prior),a,j,now)
            if not dt(a['opens_at'])<=now<dt(a['closes_at']):
                raise AppError('当前不在报名开放时间内')
            if a['registration_mode']=='review' and not note.strip():
                raise AppError('审核报名必须填写申请说明',422)
            self._promote(conn,a,j,user_id,now)
            attempt=conn.execute('SELECT COALESCE(MAX(attempt),0)+1 FROM volunteer_registrations WHERE activity_id=? AND user_id=?',(a['id'],user_id)).fetchone()[0]
            identifier=uuid4().hex
            conn.execute("INSERT INTO volunteer_registrations (id,activity_id,job_id,user_id,attempt,application_note,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'pending',?,?)",(identifier,a['id'],job_id,user_id,attempt,note,now.isoformat(),now.isoformat()))
            r=self._get(conn,'volunteer_registrations',identifier)
            if a['registration_mode']=='direct':
                self._seat(conn,j,r,user_id,now,'registered')
            else:
                self._event(conn,a['id'],identifier,user_id,'applied',now)
            return self._registration_read(conn,self._get(conn,'volunteer_registrations',identifier),a,j,now)

    def review(self, registration_id,user_id,body):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); now=self.now()
            r,a,j=self._context(conn,registration_id); self._owner(a,user_id); self._processing(a,j,now)
            if r['status']!='pending' or a['registration_mode']!='review':
                raise AppError('该申请已处理，请刷新')
            self._promote(conn,a,j,user_id,now)
            if body.decision=='approve':
                self._seat(conn,j,r,user_id,now,'approved',body.reason)
            else:
                self._transition(conn,r,'rejected',user_id,now,'rejected',body.reason)
            return self._registration_read(conn,self._get(conn,'volunteer_registrations',registration_id),a,j,now,True)

    def cancel_registration(self,registration_id,user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); now=self.now()
            r,a,j=self._context(conn,registration_id)
            if r['user_id']!=user_id:
                raise AppError('只能取消本人的志愿报名',403)
            self._processing(a,j,now)
            if r['status']=='cancelled':
                return self._registration_read(conn,r,a,j,now)
            if r['status'] not in ACTIVE:
                raise AppError('该报名已结束，不能取消')
            self._transition(conn,r,'cancelled',user_id,now,'cancelled')
            self._promote(conn,a,j,user_id,now)
            return self._registration_read(conn,self._get(conn,'volunteer_registrations',registration_id),a,j,now)

    def cancel_activity(self,activity_id,user_id,reason):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); now=self.now()
            a=self._get(conn,'volunteer_activities',activity_id); self._owner(a,user_id)
            if a['cancelled_at']:
                return self._read(conn,a,now,user_id)
            if now>=dt(a['ends_at']):
                raise AppError('志愿活动已结束，不能取消')
            conn.execute('UPDATE volunteer_activities SET cancelled_at=?,cancellation_reason=? WHERE id=?',(now.isoformat(),reason,activity_id))
            for row in conn.execute("SELECT * FROM volunteer_registrations WHERE activity_id=? AND status IN ('pending','registered','waitlisted')",(activity_id,)).fetchall():
                r=dict(row); j=self._get(conn,'volunteer_jobs',r['job_id'])
                if r['status']=='registered' or now<dt(j['starts_at']):
                    self._transition(conn,r,'activity_cancelled',user_id,now,'activity_cancelled',reason)
            self._event(conn,activity_id,None,user_id,'activity_cancelled',now,reason)
            return self._read(conn,self._get(conn,'volunteer_activities',activity_id),now,user_id)

    def roster(self,activity_id,user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN'); now=self.now(); a=self._get(conn,'volunteer_activities',activity_id); self._owner(a,user_id)
            result=self._collection([],now)
            result['items']=[self._registration_read(conn,dict(r),a,self._get(conn,'volunteer_jobs',r['job_id']),now,True) for r in conn.execute('SELECT * FROM volunteer_registrations WHERE activity_id=? ORDER BY created_at,attempt,id',(activity_id,))]
            result['next_boundary']=self._read(conn,a,now)['next_boundary']
            result['events']=[dict(e) for e in conn.execute('SELECT registration_id,action,reason,created_at FROM volunteer_events WHERE activity_id=? ORDER BY id',(activity_id,))]
            return result

    def mine(self,user_id,kind):
        with self.database.connect() as conn:
            conn.execute('BEGIN'); now=self.now()
            if kind=='activities':
                rows=conn.execute('SELECT * FROM volunteer_activities WHERE owner_id=? ORDER BY created_at DESC,id',(user_id,)).fetchall()
            else:
                rows=conn.execute('SELECT DISTINCT a.* FROM volunteer_activities a JOIN volunteer_registrations r ON r.activity_id=a.id WHERE r.user_id=? ORDER BY a.starts_at DESC,a.id',(user_id,)).fetchall()
            items=[self._read(conn,dict(a),now,user_id,history=kind!='activities') for a in rows]
            if kind=='records':
                records=[]
                for item in items:
                    for r in item.get('registration_history',[]):
                        if r['service_record'] is not None:
                            records.append(dict(activity_id=item['id'],title=item['title'],organization_name=item['organization_name'],registration=r))
                result=self._collection(items,now)
                result['items']=records
                result['confirmed_minutes']=sum(r['registration']['service_record']['confirmed_minutes'] or 0 for r in records)
                result.update(official_status='not_connected',official_minutes=None)
                return result
            return self._collection(items,now)

    def _write_record(self,conn,r,user_id,now,old,fields,action,reason):
        version=(old['version'] if old else 0)+1
        fields.update(registration_id=r['id'],version=version,updated_by=user_id,updated_at=now.isoformat())
        conn.execute(f"INSERT INTO volunteer_participation ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(registration_id) DO UPDATE SET "+','.join(f'{k}=excluded.{k}' for k in fields if k!='registration_id'),tuple(fields.values()))
        conn.execute('INSERT INTO volunteer_record_versions VALUES (?,?,?,?,?,?,?,?)',(r['id'],version,user_id,now.isoformat(),action,reason,json.dumps(old or {},ensure_ascii=False),json.dumps(fields,ensure_ascii=False)))
        self._event(conn,r['activity_id'],r['id'],user_id,action,now,reason)

    def update_record(self,registration_id,user_id,body:ParticipationInput|HoursInput):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); now=self.now()
            r,a,j=self._context(conn,registration_id); self._owner(a,user_id)
            if not self._qualified(r,a,j,now):
                raise AppError('该报名未在岗位开始时获得名额，不能登记参与或小时')
            row=conn.execute('SELECT * FROM volunteer_participation WHERE registration_id=?',(registration_id,)).fetchone()
            old=dict(row) if row else None
            if body.version!=(old['version'] if old else 0):
                raise AppError('志愿记录已更新，请刷新后再提交')
            if isinstance(body,ParticipationInput):
                if old and not body.reason:
                    raise AppError('更正参与记录必须填写原因',422)
                if body.actual_minutes>self._maximum(a,j,now):
                    raise AppError('实际分钟数不能超过已发生的岗位服务时段',422)
                fields=dict(attendance=body.attendance,actual_minutes=body.actual_minutes,description=body.description,confirmed_minutes=None,hours_reason='')
                action='participation_updated'
            else:
                if now<dt(j['ends_at']) and not a['cancelled_at']:
                    raise AppError('岗位结束后才能确认小时')
                if old is None:
                    raise AppError('请先登记参与情况')
                if body.confirmed_minutes>old['actual_minutes']:
                    raise AppError('确认分钟数不能超过实际服务分钟数',422)
                if old['confirmed_minutes'] is not None and not body.reason:
                    raise AppError('更正小时确认必须填写原因',422)
                fields={k:old[k] for k in ('attendance','actual_minutes','description')}
                fields.update(confirmed_minutes=body.confirmed_minutes,hours_reason=body.reason)
                action='hours_confirmed'
            self._write_record(conn,r,user_id,now,old,fields,action,body.reason)
            return self._registration_read(conn,r,a,j,now,True)
