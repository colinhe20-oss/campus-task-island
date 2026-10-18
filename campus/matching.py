"""Restart-safe opportunity reconciliation. No LLM calls or browser session needed."""
import json
import logging
import threading
from datetime import datetime, timezone, timedelta, time

from .assistance import Preferences
from .notifications import emit

BEIJING = timezone(timedelta(hours=8))
log = logging.getLogger(__name__)


def dt(value): return datetime.fromisoformat(value)


def availability(profile, start, end):
    if profile.valid_until and end > profile.valid_until: return False, '偏好已超过有效期'
    if any(start < s.ends_at and end > s.starts_at for s in profile.unavailable_slots):
        return False, '与不可参与时段冲突'
    exact = any(s.starts_at <= start and end <= s.ends_at for s in profile.available_slots)
    local_start, local_end = start.astimezone(BEIJING), end.astimezone(BEIJING)
    weekly = local_start.date()==local_end.date() and any(
        s.weekday==local_start.weekday() and time.fromisoformat(s.starts)<=local_start.time() and local_end.time()<=time.fromisoformat(s.ends)
        for s in profile.weekly_slots)
    if profile.available_slots or profile.weekly_slots:
        return (True,'时段符合已登记的空闲时间') if exact or weekly else (False,'不在可参与时段内')
    return True, '尚未登记空闲时间，需核对时段'


class MatchingService:
    def __init__(self, service,semantics=None):
        self.service,self.database=service,service.database
        self.semantics=semantics
        self.stop_event=threading.Event()
        self.worker=None
        self.last_success=None
        self.last_error=None

    def start(self):
        self.stop_event.clear()
        self.worker=threading.Thread(target=self._work,daemon=True,name='opportunity-matching')
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if self.worker: self.worker.join(12)

    def _work(self):
        while not self.stop_event.is_set():
            try:
                self.reconcile()
                self.last_error=None
            except Exception:
                self.last_error='机会匹配暂时失败，后台将自动重试'
                log.exception('Opportunity matching failed')
            self.stop_event.wait(5)

    def candidates(self,conn,at):
        result=[]
        for row in conn.execute('''SELECT a.*,j.id job_id,j.name,j.description job_description,j.requirements,
            j.location,j.starts_at job_starts_at,j.ends_at job_ends_at,j.capacity,
            (SELECT COUNT(*) FROM volunteer_registrations r WHERE r.job_id=j.id AND r.status='registered') occupied
            FROM volunteer_activities a JOIN volunteer_jobs j ON j.activity_id=a.id WHERE a.cancelled_at IS NULL'''):
            r=dict(row)
            if at>=dt(r['closes_at']) or at>=dt(r['job_starts_at']):continue
            result.append(dict(content_type='volunteer',resource_id=r['id'],job_id=r['job_id'],
                title=r['title'],subtitle=r['name'],description=r['description']+' '+r['job_description'],
                job_description=r['job_description'],activity_description=r['description'],
                requirements=r['requirements'],location=r['location'],starts_at=r['job_starts_at'],ends_at=r['job_ends_at'],
                owner_id=r['owner_id'],remaining_capacity=max(0,r['capacity']-r['occupied']),
                opens_at=r['opens_at'],closes_at=r['closes_at'],href=f"#/volunteers/{r['id']}"))
        for row in conn.execute('''SELECT a.*,(SELECT COUNT(*) FROM activity_registrations r
                WHERE r.activity_id=a.id AND r.status='registered') occupied FROM activities a WHERE cancelled_at IS NULL'''):
            r=dict(row)
            if at>=dt(r['closes_at']) or at>=dt(r['starts_at']):continue
            result.append(dict(content_type='activity',resource_id=r['id'],job_id='',title=r['title'],subtitle='综素活动',
                description=r['description'],requirements=r['participation_requirements'],location=r['location'],
                starts_at=r['starts_at'],ends_at=r['ends_at'],owner_id=r['owner_id'],
                remaining_capacity=max(0,r['capacity']-r['occupied']),opens_at=r['opens_at'],closes_at=r['closes_at'],href=f"#/activities/{r['id']}"))
        for row in conn.execute("SELECT * FROM tasks WHERE is_listed=1 AND status='published' AND assignee_id IS NULL"):
            r=dict(row)
            if not r['deadline'] or dt(r['deadline'])<=at:continue
            result.append(dict(content_type='ordinary',resource_id=r['id'],job_id='',title=r['title'],subtitle='普通互助',
                description=r['description'],requirements=r['completion_criteria'],location=r['location'] or '',
                starts_at=None,ends_at=None,closes_at=r['deadline'],opens_at=r['created_at'],owner_id=r['publisher_id'],
                remaining_capacity=1,href=f"#/tasks/{r['id']}"))
        return result

    def match(self,profile,candidate,at,person=None,opportunity=None):
        c=candidate
        if c['content_type'] not in profile.content_types:return None
        if at>=dt(c['closes_at']) or (c['starts_at'] and at>=dt(c['starts_at'])):return None
        if profile.valid_until and at>=profile.valid_until:return None
        checks=[];reasons=[]
        if c['starts_at']:
            fits,reason=availability(profile,dt(c['starts_at']),dt(c['ends_at']))
            if not fits:return None
            (reasons if profile.available_slots or profile.weekly_slots else checks).append(reason)
        else: checks.append('任务仅有截止时间，实际协作时段需与发布者确认')
        if c['remaining_capacity']<=0:return None
        from .semantics import semantic_match, lexical_conflict
        if lexical_conflict(profile,c):return None
        if c['requirements'].strip():checks.append('请核对完整参与要求：'+c['requirements'][:500])
        if dt(c['opens_at'])>at:checks.append('报名尚未开放')
        checks.append('名额以实际报名时重新校验为准；技能为用户自述')
        if person is not None and opportunity is not None:
            ranked=semantic_match(profile,c,person,opportunity,checks)
            return ({k:v for k,v in c.items() if k!='owner_id'}|ranked|dict(server_time=at.isoformat())) if ranked else None
        text=' '.join(str(c.get(k,'')) for k in ('title','subtitle','description','requirements')).casefold()
        skills=[s for s in profile.skills if s.casefold() in text]
        interests=[s for s in profile.interests if s.casefold() in text]
        locations=[s for s in profile.locations if s.casefold() in c['location'].casefold()]
        if skills:reasons.append('岗位描述涉及自述技能：'+'、'.join(skills))
        if interests:reasons.append('符合兴趣：'+'、'.join(interests))
        if locations:reasons.append('地点符合偏好：'+'、'.join(locations))
        if not (skills or interests):return None
        if c['requirements'].strip():checks.append('请核对完整参与要求：'+c['requirements'][:500])
        if dt(c['opens_at'])>at:checks.append('报名尚未开放')
        checks.append('名额以实际报名时重新校验为准；技能为用户自述')
        score=min(100,55*bool(skills)+30*bool(interests)+10*bool(locations)+5*bool(c['starts_at'] and (profile.available_slots or profile.weekly_slots)))
        return {k:v for k,v in c.items() if k!='owner_id'}|dict(score=score,reasons=reasons,checks=list(dict.fromkeys(checks)),server_time=at.isoformat(),matching_method='keyword_fallback',semantic_evidence=[])

    def reconcile(self,user_id=None,notify=True):
        """Full current-state reconciliation catches publication, capacity and cancellations.

        Recommendation row and notification commit together. Stable key prevents re-notifying
        on restarts, profile edits and polling; dismissed rows stay dismissed.
        """
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            at=self.service.current_time()
            candidates=self.candidates(conn,at)
            profiles=conn.execute('''SELECT p.* FROM participation_preferences p JOIN users u ON u.id=p.user_id
                WHERE u.account_status='active' '''+('AND p.user_id=?' if user_id else ''), (user_id,) if user_id else ()).fetchall()
            for row in profiles:
                uid=row['user_id'];profile=Preferences.model_validate_json(row['data'])
                active=set()
                registrations={}
                for kind,table in [('volunteer','volunteer_registrations'),('activity','activity_registrations')]:
                    registrations[kind]={r['activity_id'] for r in conn.execute(f"SELECT activity_id FROM {table} WHERE user_id=? AND status IN ('pending','registered','waitlisted')",(uid,))}
                task_applications={r[0] for r in conn.execute("SELECT task_id FROM applications WHERE applicant_id=? AND status IN ('pending','accepted')",(uid,))}
                for c in candidates:
                    if c['owner_id']==uid or c['resource_id'] in registrations.get(c['content_type'],set()) or (c['content_type']=='ordinary' and c['resource_id'] in task_applications):continue
                    person=opportunity=None
                    if self.semantics:
                        from .semantics import profile_source,job_source
                        person=self.semantics.cached(conn,'profile',uid,profile_source(profile.model_dump(mode='json')))
                        opportunity=self.semantics.cached(conn,'opportunity',c.get('job_id') or c['content_type']+':'+c['resource_id'],job_source(c))
                    item=self.match(profile,c,at,person,opportunity)
                    if not item:continue
                    key=(c['content_type'],c['resource_id'],c['job_id']);active.add(key)
                    old=conn.execute('SELECT id,status FROM opportunity_recommendations WHERE user_id=? AND content_type=? AND resource_id=? AND job_id=?',(uid,*key)).fetchone()
                    if old and old['status']=='dismissed':continue
                    data=json.dumps(item,ensure_ascii=False)
                    conn.execute('''INSERT INTO opportunity_recommendations(user_id,content_type,resource_id,job_id,data,status,created_at,updated_at)
                        VALUES (?,?,?,?,?,'recommended',?,?) ON CONFLICT(user_id,content_type,resource_id,job_id)
                        DO UPDATE SET data=excluded.data,status='recommended',updated_at=excluded.updated_at''',(uid,*key,data,at.isoformat(),at.isoformat()))
                    if notify and profile.notifications_enabled:
                        emit(conn,uid,'opportunity:'+':'.join(key),'task' if key[0]=='ordinary' else key[0],key[1],
                             '发现适合你的参与机会',item['title']+' · '+'；'.join(item['reasons']),at.isoformat())
                for old in conn.execute("SELECT * FROM opportunity_recommendations WHERE user_id=? AND status='recommended'",(uid,)).fetchall():
                    if (old['content_type'],old['resource_id'],old['job_id']) not in active:
                        conn.execute("UPDATE opportunity_recommendations SET status='expired',updated_at=? WHERE id=?",(at.isoformat(),old['id']))
        self.last_success=at.isoformat()

    def list(self,user_id,limit=20):
        with self.database.connect() as conn:
            rows=conn.execute("SELECT * FROM opportunity_recommendations WHERE user_id=? AND status='recommended' ORDER BY id DESC",(user_id,)).fetchall()
        items=[dict(json.loads(r['data']),id=r['id'],created_at=r['created_at']) for r in rows]
        items.sort(key=lambda x:(-x['score'],x['starts_at'] or x['closes_at'],x['id']))
        return dict(items=items[:limit],total=len(items),last_checked_at=self.last_success,error=self.last_error)

    def dismiss(self,user_id,identifier):
        from .errors import AppError
        with self.database.connect() as conn:
            result=conn.execute("UPDATE opportunity_recommendations SET status='dismissed' WHERE id=? AND user_id=?",(identifier,user_id))
            if not result.rowcount:raise AppError('推荐不存在',404)
        return {'ok':True}
