import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from pydantic import ValidationError
import test_guide as helpers
from campus.activity_schemas import RegistrationReview
from campus.errors import AppError
from campus.volunteer_schemas import VolunteerCreate, ParticipationInput, HoursInput


class VolunteerTests(unittest.TestCase):
    setUpBase=helpers.GuideTests.setUp
    login=helpers.GuideTests.login

    def setUp(self):
        self.setUpBase()
        self.now=datetime(2030,1,1,tzinfo=timezone.utc)
        self.vol=self.app.state.volunteer_service
        self.vol.clock=lambda:self.now
        self.owner=self.users['publisher'][1].id
        self.helper=self.users['helper'][1].id
        self.observer=self.users['observer'][1].id

    def payload(self,**updates):
        def stamp(hours):return (self.now+timedelta(hours=hours)).isoformat()
        jobs=[dict(name=name,description='整理活动物料',requirements='能按时参与',location='活动中心',starts_at=stamp(start),ends_at=stamp(start+1),capacity=1,estimated_minutes=60,estimated_hours_description='按实际参与确认') for name,start in [('上午岗',2),('下午岗',4)]]
        return dict(title='校园公益服务',description='公益岗位招募',organization_name='测试社团',information_source='测试公告',contact='站内联系',recognition_conditions='全程参与且完成岗位工作',starts_at=stamp(2),ends_at=stamp(5),opens_at=stamp(-1),closes_at=stamp(1),registration_mode='direct',jobs=jobs)|updates

    def create(self,**updates):return self.vol.create(VolunteerCreate.model_validate(self.payload(**updates)),self.owner)
    def register(self,a,user=None,job=0):return self.vol.register(a['jobs'][job]['id'],user or self.helper,'可以参加')
    def approve(self,r):return self.vol.review(r['id'],self.owner,RegistrationReview(decision='approve'))
    def participation(self,r,version=0,minutes=60,reason='',attendance='participated'):
        return self.vol.update_record(r['id'],self.owner,ParticipationInput(version=version,attendance=attendance,actual_minutes=minutes,description='已完成岗位工作',reason=reason))
    def hours(self,r,version=1,minutes=60,reason=''):
        return self.vol.update_record(r['id'],self.owner,HoursInput(version=version,confirmed_minutes=minutes,reason=reason))
    def advance(self,a,key='ends_at',job=0):self.now=datetime.fromisoformat(a['jobs'][job][key])

    def test_job_intervals_timezone_and_integer_validation(self):
        for update in ({'jobs':[]},{'opens_at':'2030-01-01T00:00:00'}, {'closes_at':'2030-01-01T03:00:00Z'}):
            with self.subTest(update=update),self.assertRaises(ValidationError):VolunteerCreate.model_validate(self.payload(**update))
        for change in ({'capacity':0},{'estimated_minutes':61},{'starts_at':'2030-01-01T01:00:00Z'},{'ends_at':'2030-01-01T06:00:00Z'},{'estimated_minutes':1.5}):
            p=self.payload();p['jobs'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValidationError):VolunteerCreate.model_validate(p)

    def test_publish_capability_and_no_edit_endpoint(self):
        self.login('helper')
        self.assertFalse(self.client.get('/api/auth/me').json()['can_publish_volunteers'])
        self.assertEqual(self.client.post('/api/volunteers',json=self.payload()).status_code,403)
        self.login()
        self.assertTrue(self.client.get('/api/auth/me').json()['can_publish_volunteers'])
        a=self.client.post('/api/volunteers',json=self.payload()).json()
        self.assertEqual(len(a['jobs']),2)
        self.assertEqual(self.client.patch('/api/volunteers/'+a['id'],json={'capacity':3}).status_code,405)

    def test_open_cutoff_and_server_time(self):
        a=self.create(opens_at=(self.now+timedelta(minutes=1)).isoformat())
        self.login('helper')
        path='/api/volunteer-jobs/'+a['jobs'][0]['id']+'/registrations'
        self.assertEqual(self.client.post(path,json={},headers={'Date':'2040-01-01'}).status_code,409)
        self.now=datetime.fromisoformat(a['opens_at'])
        r=self.register(a)
        self.now=datetime.fromisoformat(a['closes_at'])
        self.assertEqual(self.register(a)['id'],r['id'])
        with self.assertRaises(AppError):self.register(a,self.observer)

    def test_clock_checked_after_write_lock(self):
        a=self.create();started=Event()
        def run():started.set();return self.register(a)
        with ThreadPoolExecutor(1) as pool:
            with self.vol.database.connect() as c:
                c.execute('BEGIN IMMEDIATE');future=pool.submit(run);self.assertTrue(started.wait(2));self.now=datetime.fromisoformat(a['closes_at'])
            with self.assertRaises(AppError):future.result(5)

    def test_owner_cannot_register(self):
        a=self.create()
        with self.assertRaises(AppError):self.register(a,self.owner)

    def test_capacity_is_per_job(self):
        a=self.create()
        self.assertEqual(self.register(a)['status'],'registered')
        self.assertEqual(self.register(a,self.observer,1)['status'],'registered')
        self.assertEqual([j['registered_count'] for j in self.vol.detail(a['id'])['jobs']],[1,1])

    def test_duplicate_and_cross_job_active_constraint(self):
        a=self.create();r=self.register(a)
        self.assertEqual(self.register(a)['id'],r['id'])
        with self.assertRaises(AppError):self.register(a,job=1)
        self.vol.cancel_registration(r['id'],self.helper)
        new=self.register(a,job=1)
        self.vol.cancel_registration(r['id'],self.helper)
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['id'],new['id'])
        self.assertEqual(len(self.vol.mine(self.helper,'registrations')['items'][0]['registration_history']),2)

    def test_concurrent_last_seat(self):
        a=self.create();gate=Barrier(2)
        def run(user):gate.wait();return self.register(a,user)
        with ThreadPoolExecutor(2) as p:results=list(p.map(run,[self.helper,self.observer]))
        self.assertCountEqual([r['status'] for r in results],['registered','waitlisted'])

    def test_concurrent_approvals_last_seat(self):
        a=self.create(registration_mode='review');regs=[self.register(a,u) for u in (self.helper,self.observer)];gate=Barrier(2)
        def run(r):gate.wait();return self.approve(r)
        with ThreadPoolExecutor(2) as p:results=list(p.map(run,regs))
        self.assertCountEqual([r['status'] for r in results],['registered','waitlisted'])

    def test_confirmed_record_and_history_survive_database_reinitialization(self):
        a=self.create();r=self.register(a);self.advance(a);self.participation(r);self.hours(r)
        self.vol.database.initialize()
        records=self.vol.mine(self.helper,'records')
        self.assertEqual(records['confirmed_minutes'],60)
        self.assertEqual(len(records['items'][0]['registration']['service_record']['versions']),2)

    def test_concurrent_same_user_cross_job(self):
        a=self.create();gate=Barrier(2)
        def run(job):
            gate.wait()
            try:return self.register(a,job=job)
            except AppError:return None
        with ThreadPoolExecutor(2) as p:results=list(p.map(run,[0,1]))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_concurrent_same_user_duplicate(self):
        a=self.create();gate=Barrier(2)
        def run(_):gate.wait();return self.register(a)
        with ThreadPoolExecutor(2) as p:results=list(p.map(run,[0,1]))
        self.assertEqual(results[0]['id'],results[1]['id'])

    def test_review_note_rejection_and_reapplication(self):
        a=self.create(registration_mode='review')
        with self.assertRaises(AppError):self.vol.register(a['jobs'][0]['id'],self.helper,'')
        r=self.register(a)
        self.assertEqual(r['status'],'pending')
        self.assertEqual(self.vol.detail(a['id'])['jobs'][0]['remaining_capacity'],1)
        self.login()
        self.assertEqual(self.client.post('/api/volunteer-registrations/'+r['id']+'/review',json={'decision':'reject'}).status_code,422)
        self.vol.review(r['id'],self.owner,RegistrationReview(decision='reject',reason='请补充资料'))
        new=self.register(a,job=1)
        history=self.vol.mine(self.helper,'registrations')['items'][0]['registration_history']
        self.assertNotEqual(new['id'],r['id']);self.assertEqual(history[1]['review_reason'],'请补充资料')

    def test_approval_order_and_promotion_after_close(self):
        a=self.create(registration_mode='review');first=self.register(a);second=self.register(a,self.observer)
        self.now=datetime.fromisoformat(a['closes_at'])
        self.assertEqual(self.approve(second)['status'],'registered')
        self.assertEqual(self.approve(first)['waitlist_position'],1)
        self.vol.cancel_registration(second['id'],self.observer)
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['status'],'registered')

    def test_fifo_leaving_queue_and_reapplying(self):
        a=self.create()
        with self.vol.database.connect() as c:c.execute('INSERT INTO users (id,username,display_name,salt,password_hash) VALUES (?,?,?,?,?)',('extra','extra','同学四','00','unused'))
        holder=self.register(a,'extra');first=self.register(a);second=self.register(a,self.observer)
        self.vol.cancel_registration(first['id'],self.helper);last=self.register(a)
        self.assertGreater(last['queue_sequence'],second['queue_sequence'])
        self.vol.cancel_registration(holder['id'],'extra')
        self.assertEqual(self.vol.detail(a['id'],self.observer)['my_registration']['status'],'registered')
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['waitlist_position'],1)

    def test_new_registration_cannot_bypass_waitlist(self):
        a=self.create();holder=self.register(a);waiter=self.register(a,self.observer)
        with self.vol.database.connect() as c:c.execute("UPDATE volunteer_registrations SET status='cancelled' WHERE id=?",(holder['id'],))
        self.assertEqual(self.register(a)['status'],'waitlisted')
        self.assertEqual(self.vol.detail(a['id'],self.observer)['my_registration']['id'],waiter['id'])
        self.assertEqual(self.vol.detail(a['id'],self.observer)['my_registration']['status'],'registered')

    def test_each_job_start_has_independent_cutoff(self):
        a=self.create(registration_mode='review');early=self.register(a);late=self.register(a,self.observer,1)
        self.advance(a,'starts_at')
        with self.assertRaises(AppError):self.approve(early)
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['status'],'not_selected')
        self.assertEqual(self.approve(late)['status'],'registered')
        self.vol.cancel_registration(late['id'],self.observer)

    def test_pending_and_waitlisted_never_qualify_for_hours(self):
        a=self.create();self.register(a);waiter=self.register(a,self.observer)
        self.advance(a)
        with self.assertRaises(AppError):self.participation(waiter)
        self.assertEqual(self.vol.mine(self.observer,'records')['items'],[])

    def test_signup_does_not_create_hours_or_attendance(self):
        a=self.create();r=self.register(a)
        self.assertIsNone(r['service_record']);self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],0)
        self.advance(a,'starts_at')
        record=self.vol.detail(a['id'],self.helper)['my_registration']['service_record']
        self.assertIsNone(record['attendance']);self.assertIsNone(record['confirmed_minutes']);self.assertEqual(record['version'],0)
        with self.assertRaises(AppError):self.hours(r)

    def test_full_record_and_confirm_and_correction_cycle(self):
        a=self.create();r=self.register(a);self.advance(a)
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['service_record']['status'],'pending_verification')
        p=self.participation(r);self.assertEqual(p['service_record']['version'],1)
        h=self.hours(r);self.assertEqual(h['service_record']['confirmed_minutes'],60)
        corrected=self.hours(r,version=2,minutes=45,reason='核对培训记录后调整')
        self.assertEqual(corrected['service_record']['version'],3)
        result=self.vol.mine(self.helper,'records');self.assertEqual(result['confirmed_minutes'],45);self.assertIsNone(result['official_minutes'])
        self.participation(r,version=3,minutes=50,reason='补充实际参与记录')
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],0)
        last=self.hours(r,version=4,minutes=50)
        self.assertEqual(len(last['service_record']['versions']),5)
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],50)

    def test_stale_versions_and_missing_correction_reason(self):
        a=self.create();r=self.register(a);self.advance(a);self.participation(r);self.hours(r)
        for call in (lambda:self.participation(r,version=1),lambda:self.hours(r,version=1),lambda:self.hours(r,version=2,minutes=45),lambda:self.participation(r,version=2)):
            with self.assertRaises(AppError):call()
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],60)

    def test_minutes_validation_and_zero_reason(self):
        a=self.create();r=self.register(a);self.advance(a)
        with self.assertRaises(AppError):self.participation(r,minutes=61)
        with self.assertRaises(ValidationError):ParticipationInput(version=0,attendance='absent',actual_minutes=1,description='未参加')
        with self.assertRaises(ValidationError):HoursInput(version=1,confirmed_minutes=0)
        with self.assertRaises(ValidationError):HoursInput(version=1,confirmed_minutes=1.5)
        self.participation(r,minutes=0,attendance='absent')
        with self.assertRaises(AppError):self.hours(r,minutes=1)
        self.hours(r,minutes=0,reason='未实际参与')
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],0)

    def test_confirm_requires_job_end_but_participation_can_be_recorded_during_service(self):
        a=self.create();r=self.register(a);self.advance(a,'starts_at');self.now+=timedelta(minutes=20)
        self.participation(r,minutes=20)
        with self.assertRaises(AppError):self.hours(r,minutes=20)
        with self.assertRaises(AppError):self.participation(r,version=1,minutes=21,reason='超时')

    def test_cancel_mid_service_limits_hours_and_preserves_eligibility(self):
        a=self.create();early=self.register(a);late=self.register(a,self.observer,1)
        self.advance(a,'starts_at');self.now+=timedelta(minutes=25)
        self.vol.cancel_activity(a['id'],self.owner,'天气原因')
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['status'],'activity_cancelled')
        with self.assertRaises(AppError):self.participation(early,minutes=26)
        self.participation(early,minutes=25);self.hours(early,minutes=25)
        with self.assertRaises(AppError):self.participation(late,minutes=0)
        self.now+=timedelta(hours=2)
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],25)
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['service_record']['maximum_actual_minutes'],25)

    def test_cancel_preserves_confirmed_prior_job_and_rejected_history(self):
        a=self.create(registration_mode='review');r=self.register(a);other=self.register(a,self.observer,1)
        self.approve(r);self.vol.review(other['id'],self.owner,RegistrationReview(decision='reject',reason='资料不符'))
        self.advance(a);self.participation(r);self.hours(r)
        self.vol.cancel_activity(a['id'],self.owner,'后续场次取消')
        self.assertEqual(self.vol.mine(self.helper,'records')['confirmed_minutes'],60)
        self.assertEqual(self.vol.detail(a['id'],self.observer)['my_registration']['status'],'rejected')

    def test_personal_cancel_before_start_cannot_receive_hours(self):
        a=self.create();r=self.register(a);self.vol.cancel_registration(r['id'],self.helper);self.advance(a)
        with self.assertRaises(AppError):self.participation(r)

    def test_cancel_registration_vs_review_has_consistent_terminal_state(self):
        a=self.create(registration_mode='review');r=self.register(a);gate=Barrier(2)
        def run(cancel):
            gate.wait()
            try:return self.vol.cancel_registration(r['id'],self.helper) if cancel else self.approve(r)
            except AppError:return None
        with ThreadPoolExecutor(2) as p:list(p.map(run,[True,False]))
        self.assertEqual(self.vol.detail(a['id'],self.helper)['my_registration']['status'],'cancelled')

    def test_whole_cancel_races_registration_and_review(self):
        for mode in ('direct','review'):
            a=self.create(registration_mode=mode);r=self.register(a) if mode=='review' else None;gate=Barrier(2)
            def run(cancel):
                gate.wait()
                try:return self.vol.cancel_activity(a['id'],self.owner,'取消') if cancel else self.approve(r) if r else self.register(a)
                except AppError:return None
            with ThreadPoolExecutor(2) as p:list(p.map(run,[True,False]))
            self.assertTrue(all(r['status']=='activity_cancelled' for r in self.vol.roster(a['id'],self.owner)['items']))

    def test_concurrent_confirm_version_only_one_wins(self):
        a=self.create();r=self.register(a);self.advance(a);self.participation(r);gate=Barrier(2)
        def run(minutes):
            gate.wait()
            try:return self.hours(r,minutes=minutes)
            except AppError:return None
        with ThreadPoolExecutor(2) as p:results=list(p.map(run,[45,60]))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertIn(self.vol.mine(self.helper,'records')['confirmed_minutes'],[45,60])

    def test_public_and_other_user_privacy_and_permissions(self):
        a=self.create();r=self.register(a);self.advance(a);self.participation(r);self.hours(r)
        self.client.cookies.clear()
        public=self.client.get('/api/volunteers/'+a['id']).json()
        self.assertIsNone(public['my_registration']);self.assertNotIn('已完成岗位工作',json.dumps(public,ensure_ascii=False))
        self.client.cookies.set('campus_session','expired')
        self.assertEqual(self.client.get('/api/volunteers/'+a['id']).status_code,200)
        self.login('observer')
        for method,path,body in [('get','/api/volunteers/'+a['id']+'/registrations',None),('post','/api/volunteer-registrations/'+r['id']+'/review',{'decision':'approve'}),('post','/api/volunteer-registrations/'+r['id']+'/cancel',None),('post','/api/volunteers/'+a['id']+'/cancel',{'reason':'越权'}),('post','/api/volunteer-registrations/'+r['id']+'/participation',{'version':2,'attendance':'participated','actual_minutes':1,'description':'冒用','reason':'冒用'}),('post','/api/volunteer-registrations/'+r['id']+'/hours',{'version':2,'confirmed_minutes':1,'reason':'冒用'})]:
            response=self.client.request(method,path,**({'json':body} if body is not None else {}))
            self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.client.get('/api/me/volunteer-records').json()['items'],[])

    def test_unauthenticated_writes_and_private_reads(self):
        a=self.create()
        for method,path,body in [('post','/api/volunteers',self.payload()),('post','/api/volunteer-jobs/'+a['jobs'][0]['id']+'/registrations',{}),('get','/api/me/volunteer-records',None),('get','/api/volunteers/'+a['id']+'/registrations',None)]:
            self.assertEqual(self.client.request(method,path,**({'json':body} if body is not None else {})).status_code,401)

    def test_search_and_personal_history_survive_reinitialize(self):
        a=self.create();r=self.register(a);self.vol.cancel_registration(r['id'],self.helper);self.register(a,job=1)
        self.vol.database.initialize()
        self.assertEqual(self.vol.search(keyword='下午岗')['total'],1)
        self.assertEqual(len(self.vol.mine(self.helper,'registrations')['items'][0]['registration_history']),2)
        self.assertEqual(self.app.state.activity_service.search()['total'],0)
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
        self.assertEqual(self.vol.mine(self.observer,'activities')['items'],[])
