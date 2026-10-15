import json,sqlite3,unittest
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import test_guide as helpers
import test_activities as activity_helpers
import test_volunteers as volunteer_helpers
import test_discoveries as discovery_helpers
from test_stages import FIELDS
from campus.notifications import emit
from campus.errors import AppError
from campus.activity_schemas import ActivityCreate,RegistrationReview
from campus.volunteer_schemas import VolunteerCreate,ParticipationInput,HoursInput
from campus.discovery_schemas import DiscoveryCreate,DiscoveryCommentInput,DiscoveryWithdraw
from campus.schemas import StagePlanInput,StageSubmitInput,StageReviewInput

class HomeMessageTests(unittest.TestCase):
    login=helpers.GuideTests.login
    publish=helpers.GuideTests.publish
    payload=volunteer_helpers.VolunteerTests.payload
    def setUp(self):
        helpers.GuideTests.setUp(self)
        self.now=datetime(2030,1,1,tzinfo=timezone.utc)
        self.owner=self.users['publisher'][1].id;self.helper=self.users['helper'][1].id;self.observer=self.users['observer'][1].id
        self.messages=self.app.state.notification_service;self.home=self.app.state.home_service
        self.activities=self.app.state.activity_service;self.vol=self.app.state.volunteer_service;self.dis=self.app.state.discovery_service
        for service in (self.activities,self.vol,self.dis):service.clock=lambda:self.now
    def inbox(self,user=None):return self.messages.list(user or self.owner,limit=50)['items']
    def activity(self,**updates):return self.activities.create(ActivityCreate.model_validate(activity_helpers.ActivityTests.payload(self,**updates)),self.owner)
    def volunteer(self,**updates):return self.vol.create(VolunteerCreate.model_validate(self.payload(**updates)),self.owner)
    def joined(self):
        t=self.publish();a=self.service.apply(t.id,self.helper,'私密申请说明');self.service.accept_application(a.id,self.owner);return t
    def test_task_application_selection_and_rejected_peer(self):
        t=self.publish();a=self.service.apply(t.id,self.helper,'申请');self.service.apply(t.id,self.observer,'另一个申请')
        self.assertEqual(len(self.inbox()),2);self.service.accept_application(a.id,self.owner)
        self.assertIn('通过',self.inbox(self.helper)[0]['title']);self.assertIn('其他',self.inbox(self.observer)[0]['title'])
        with self.assertRaises(AppError):self.service.accept_application(a.id,self.owner)
        self.assertEqual(len(self.inbox(self.helper)),1)
    def test_task_withdraw_ends_pending_once(self):
        t=self.publish();self.service.apply(t.id,self.helper,'申请');self.service.withdraw(t.id,self.owner);self.service.withdraw(t.id,self.owner)
        self.assertEqual(len(self.inbox(self.helper)),1);self.assertIn('下架',self.inbox(self.helper)[0]['title'])
    def test_submit_return_resubmit_complete_and_counts(self):
        t=self.joined();self.service.submit(t.id,self.helper,'私密成果');self.service.review(t.id,self.owner,'request_changes','私密反馈')
        self.assertIn('补充',self.inbox(self.helper)[0]['title']);self.service.submit(t.id,self.helper,'再次提交');self.service.review(t.id,self.owner,'accept','通过')
        for user in (self.owner,self.helper):self.assertEqual(self.home.summary(user)['completed_count'],1)
        self.assertEqual(self.home.summary(self.observer)['completed_count'],0)
        text=json.dumps(self.inbox()+self.inbox(self.helper),ensure_ascii=False)
        for private in ('私密申请说明','私密成果','私密反馈'):self.assertNotIn(private,text)
    def test_notification_failure_rolls_back_business(self):
        t=self.publish()
        with self.service.database.connect() as c:c.execute("CREATE TRIGGER fail_message BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.service.apply(t.id,self.helper,'申请')
        with self.service.database.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM applications').fetchone()[0],0)
        self.assertEqual(self.inbox(),[])
    def test_emit_unique_key_and_transaction_rollback(self):
        with self.service.database.connect() as c:
            emit(c,self.owner,'same','task','id','一次');emit(c,self.owner,'same','task','id','重复')
        self.assertEqual(len(self.inbox()),1)
        with self.assertRaises(RuntimeError):
            with self.service.database.connect() as c:emit(c,self.owner,'rollback','task','id','不保留');raise RuntimeError()
        self.assertEqual(len(self.inbox()),1)
    def test_direct_seat_waitlist_promotion_and_cancel_owner(self):
        a=self.activity();r=self.activities.register(a['id'],self.helper);w=self.activities.register(a['id'],self.observer)
        self.activities.register(a['id'],self.helper);self.assertEqual(len(self.inbox(self.helper)),1)
        self.activities.cancel_registration(r['id'],self.helper);self.activities.cancel_registration(r['id'],self.helper)
        self.assertEqual(len(self.inbox(self.helper)),1);self.assertEqual(len(self.inbox()),1)
        self.assertIn('转正',self.inbox(self.observer)[0]['title'])
    def test_review_pending_rejected_and_reapply(self):
        a=self.activity(registration_mode='review');r=self.activities.register(a['id'],self.helper,'申请')
        self.assertIn('待审核',self.inbox(self.helper)[0]['title']);self.assertEqual(self.home.summary(self.owner)['todos'][0]['count'],1)
        self.activities.review(r['id'],self.owner,RegistrationReview(decision='reject',reason='不符合'))
        self.activities.register(a['id'],self.helper,'新申请');self.assertEqual(len(self.inbox(self.helper)),3)
    def test_approved_waitlist_uses_actual_result(self):
        a=self.activity(registration_mode='review');r=self.activities.register(a['id'],self.helper,'申请');w=self.activities.register(a['id'],self.observer,'申请')
        for item in (r,w):self.activities.review(item['id'],self.owner,RegistrationReview(decision='approve'))
        self.assertIn('成功',self.inbox(self.helper)[0]['title']);self.assertIn('候补',self.inbox(self.observer)[0]['title'])
    def test_activity_cancellation_idempotent(self):
        a=self.activity();self.activities.register(a['id'],self.helper);self.activities.register(a['id'],self.observer)
        self.activities.cancel_activity(a['id'],self.owner,'取消');self.activities.cancel_activity(a['id'],self.owner,'取消')
        for user in (self.helper,self.observer):self.assertEqual(sum('活动方已取消' in m['title'] for m in self.inbox(user)),1)
    def test_volunteer_cancel_after_start_keeps_hours_and_notice(self):
        a=self.volunteer();r=self.vol.register(a['jobs'][0]['id'],self.helper);self.now+=timedelta(hours=2,minutes=20)
        self.vol.cancel_activity(a['id'],self.owner,'中途取消');self.assertIn('取消',self.inbox(self.helper)[0]['title'])
        self.vol.update_record(r['id'],self.owner,ParticipationInput(version=0,attendance='participated',actual_minutes=20,description='完成'))
        self.vol.update_record(r['id'],self.owner,HoursInput(version=1,confirmed_minutes=20))
        self.assertIn('活动方确认',self.inbox(self.helper)[0]['title'])
    def test_volunteer_hours_correction_invalidation_and_summary(self):
        a=self.volunteer();r=self.vol.register(a['jobs'][0]['id'],self.helper);self.now+=timedelta(hours=3)
        self.assertEqual(self.home.summary(self.owner)['todos'][0]['action'],'record_participation')
        self.vol.update_record(r['id'],self.owner,ParticipationInput(version=0,attendance='participated',actual_minutes=60,description='完成'))
        self.assertEqual(self.home.summary(self.owner)['todos'][0]['action'],'verify_hours')
        self.vol.update_record(r['id'],self.owner,HoursInput(version=1,confirmed_minutes=60));self.assertEqual(self.home.summary(self.owner)['todo_count'],0)
        self.vol.update_record(r['id'],self.owner,HoursInput(version=2,confirmed_minutes=50,reason='更正'))
        self.vol.update_record(r['id'],self.owner,ParticipationInput(version=3,attendance='participated',actual_minutes=45,description='更正',reason='修正'))
        self.assertIn('重新核验',self.inbox(self.helper)[0]['title']);self.assertEqual(self.home.summary(self.owner)['todo_count'],1)
    def test_volunteer_pending_grouped_by_job_and_boundary(self):
        a=self.volunteer(registration_mode='review')
        self.vol.register(a['jobs'][0]['id'],self.helper,'申请');self.vol.register(a['jobs'][0]['id'],self.observer,'申请')
        summary=self.home.summary(self.owner);self.assertEqual(summary['todos'][0]['count'],2)
        self.now+=timedelta(hours=2);self.assertEqual(self.home.summary(self.owner)['todo_count'],0)
    def test_discovery_comment_minimal_and_withdraw_privacy(self):
        d=self.dis.create(DiscoveryCreate.model_validate(discovery_helpers.DiscoveryTests.payload(self)),self.owner)
        self.dis.comment(d['id'],self.owner,DiscoveryCommentInput(content='自己的评论'))
        self.assertEqual(self.inbox(),[])
        comment=self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='私密评论'))
        self.dis.withdraw_comment(comment['id'],self.helper);self.dis.state(d['id'],self.owner,DiscoveryWithdraw(version=1,reason='撤回'),True)
        self.assertEqual(len(self.inbox()),1);text=json.dumps(self.inbox(),ensure_ascii=False)
        for private in ('私密评论','图书馆路灯异常','image_ids'):self.assertNotIn(private,text)
        self.assertEqual(self.home.summary(self.owner)['todo_count'],0)
    def test_auth_and_cross_user_read(self):
        with self.service.database.connect() as c:emit(c,self.owner,'private','task','id','私有消息')
        mid=self.inbox()[0]['id'];self.login('helper')
        self.assertEqual(self.client.get('/api/me/messages').json()['items'],[])
        self.assertEqual(self.client.post(f'/api/me/messages/{mid}/read').status_code,404)
        self.client.cookies.clear()
        for path in ('/api/me/home','/api/me/messages','/api/me/messages/unread-count'):self.assertEqual(self.client.get(path).status_code,401)
    def test_single_read_idempotent_and_does_not_remove_todo(self):
        t=self.publish();self.service.apply(t.id,self.helper,'申请');mid=self.inbox()[0]['id']
        self.messages.read(self.owner,mid);stamp=self.inbox()[0]['read_at'];self.messages.read(self.owner,mid)
        self.assertEqual(self.inbox()[0]['read_at'],stamp);self.assertEqual(self.home.summary(self.owner)['todo_count'],1)
    def test_cursor_and_read_all_preserves_new_messages(self):
        with self.service.database.connect() as c:
            for i in range(5):emit(c,self.owner,str(i),'task','id',str(i))
        page=self.messages.list(self.owner,limit=2);older=self.messages.list(self.owner,limit=2,before_id=page['next_cursor'])
        self.assertFalse({m['id'] for m in page['items']}&{m['id'] for m in older['items']})
        with self.service.database.connect() as c:emit(c,self.owner,'new','task','id','新消息')
        self.messages.read(self.owner,through_id=page['max_id']);self.assertEqual(self.messages.count(self.owner)['unread_count'],1)
        self.assertEqual(self.messages.list(self.owner,True)['items'][0]['title'],'新消息')
    def test_read_all_does_not_affect_other_user(self):
        with self.service.database.connect() as c:
            emit(c,self.owner,'a','task','id','a');emit(c,self.helper,'b','task','id','b')
        self.messages.read(self.owner,through_id=999);self.assertEqual(self.messages.count(self.helper)['unread_count'],1)
    def test_list_get_is_readonly_and_schema_has_no_backfill(self):
        t=self.publish();self.service.apply(t.id,self.helper,'申请')
        with self.service.database.connect() as c:c.execute('DELETE FROM notifications')
        self.service.database.initialize();self.assertEqual(self.inbox(),[])
        self.assertEqual(self.home.summary(self.owner)['todo_count'],1);self.messages.list(self.owner)
        self.assertEqual(self.inbox(),[])
    def test_home_limit_priority_and_no_completed_or_waiting(self):
        for i in range(7):
            t=self.publish(title=f'任务{i}');self.service.apply(t.id,self.helper,'申请')
        t=self.joined();self.service.submit(t.id,self.helper,'成果')
        summary=self.home.summary(self.owner);self.assertEqual(summary['todo_count'],8);self.assertEqual(len(summary['todos']),5)
        self.assertEqual(summary['todos'][0]['action'],'review_results');self.assertEqual(self.home.summary(self.observer)['todo_count'],0)
    def test_rollback_during_promotion_and_concurrent_cancel(self):
        a=self.activity();r=self.activities.register(a['id'],self.helper);self.activities.register(a['id'],self.observer)
        barrier=Barrier(2)
        def cancel(whole):
            barrier.wait()
            try:
                if whole:self.activities.cancel_activity(a['id'],self.owner,'取消')
                else:self.activities.cancel_registration(r['id'],self.helper)
            except AppError:pass
        with ThreadPoolExecutor(2) as pool:list(pool.map(cancel,(True,False)))
        for user in (self.helper,self.observer):
            notice=[m for m in self.inbox(user) if '活动方已取消' in m['title']]
            with self.service.database.connect() as c:status=c.execute('SELECT status FROM activity_registrations WHERE activity_id=? AND user_id=?',(a['id'],user)).fetchone()[0]
            self.assertEqual(len(notice),int(status=='activity_cancelled'))
    def test_stage_plan_start_submit_review_single_final_message(self):
        t=self.joined();stages=self.app.state.stage_service
        from campus.schemas import ChangeInput,ExtensionReviewInput
        request=self.service.terms.changes.propose(t.id,self.owner,ChangeInput(version=1,reason='共同确认首次安排',changes={'initial_stages':FIELDS[:1]}))['items'][0]
        self.assertIn('变更申请',self.inbox(self.helper)[0]['title'])
        self.service.terms.changes.decide(request['id'],self.helper,ExtensionReviewInput(version=1,decision='approve'))
        panel=stages.read(t.id,self.owner);s=panel.stages[0]
        stages.start(t.id,s.id,self.helper,s.version)
        self.assertIn('已开始',self.inbox()[0]['title']);panel=stages.read(t.id,self.helper)
        stages.submit(t.id,s.id,self.helper,StageSubmitInput(version=panel.stages[0].version,summary='阶段成果'))
        self.assertEqual(self.home.summary(self.owner)['todos'][0]['action'],'review_stage')
        panel=stages.read(t.id,self.owner);before=len(self.inbox(self.helper))
        stages.review(t.id,s.id,self.owner,StageReviewInput(version=panel.stages[0].version,decision='accept',feedback='通过'))
        self.assertEqual(len(self.inbox(self.helper)),before+1);self.assertIn('任务已完成',self.inbox(self.helper)[0]['title'])

    def test_api_read_all_validation_and_unread_count(self):
        self.login()
        with self.service.database.connect() as c:emit(c,self.owner,'api','task','id','API消息')
        page=self.client.get('/api/me/messages?limit=1').json()
        self.assertEqual(self.client.get('/api/me/messages/unread-count').json()['unread_count'],1)
        for invalid in ({'through_id':-1},{'through_id':True},{'through_id':'1'},{'through_id':0,'recipient_id':self.helper}):
            self.assertEqual(self.client.post('/api/me/messages/read-all',json=invalid).status_code,422)
        self.assertEqual(self.client.post('/api/me/messages/read-all',json={'through_id':page['max_id']}).status_code,200)
        self.assertEqual(self.client.get('/api/me/messages?unread_only=true').json()['items'],[])
    def test_home_api_does_not_include_other_owner_or_expired_review(self):
        a=self.activity(registration_mode='review');self.activities.register(a['id'],self.helper,'申请')
        self.login('helper');self.assertEqual(self.client.get('/api/me/home').json()['todos'],[])
        self.login();self.assertEqual(self.client.get('/api/me/home').json()['todos'][0]['href'],f"#/activities/{a['id']}?manage=1")
        before=len(self.inbox());self.now+=timedelta(hours=2)
        self.assertEqual(self.client.get('/api/me/home').json()['todos'],[]);self.assertEqual(len(self.inbox()),before)
