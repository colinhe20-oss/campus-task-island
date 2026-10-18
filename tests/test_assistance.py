"""Proposal requirements: real persistence, permissions, matching, delivery and trace."""
import json
import threading
import time
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

import test_guide as helpers
import test_volunteers as volunteer_helpers
import test_activities as activity_helpers
from backend.fake_backend import FakeBackend
from campus.assistance import Preferences
from campus.activity_schemas import ActivityCreate
from campus.matching import availability
from campus.volunteer_schemas import VolunteerCreate


class AssistanceTests(unittest.TestCase):
    setUpBase=helpers.GuideTests.setUp
    login=helpers.GuideTests.login
    payload=volunteer_helpers.VolunteerTests.payload

    def setUp(self):
        self.setUpBase()
        self.guide=self.app.state.guide_service
        self.guide.matching.stop()
        self.now=datetime(2030,1,1,tzinfo=timezone.utc)
        self.service.clock=lambda:self.now
        self.vol=self.app.state.volunteer_service;self.vol.clock=lambda:self.now
        self.app.state.activity_service.clock=lambda:self.now
        self.owner=self.users['publisher'][1].id;self.helper=self.users['helper'][1].id
        self.login()

    def chat(self,calls,message='规划活动，技能摄影，兴趣环保。',conversation_id=None):
        self.guide.backend_factory=lambda:FakeBackend([*calls,{'content':'请核对卡片并补充缺失条件。'}])
        result=self.client.post('/api/guide/chat',json={'message':message,**({'conversation_id':conversation_id} if conversation_id else {})})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def plan(self,kind='volunteer',fields=None):
        fields=fields or self.payload()
        return self.chat([helpers.calling('update_'+kind+'_plan',{'fields':fields,'suggestions':['建议增加一名机动人员'],'checklist':['发布前核对场地','活动前确认岗位人员']})])

    def action(self,reply,name,**extra):
        a=reply.get('assistance',reply)
        return self.client.post('/api/guide/assistance/'+a['conversation_id']+'/'+name,json={'version':a['version'],**extra})

    def preferences(self,**changes):
        self.login('helper')
        fields=Preferences(skills=['摄影'],interests=['公益'],notifications_enabled=True,**changes).model_dump(mode='json')
        r=self.client.put('/api/guide/preferences',json={'version':self.guide.assistance.preferences(self.helper)['version'],'fields':fields})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_incomplete_plan_clarification_no_ordinary_task_or_publication(self):
        r=self.plan(fields={'title':'公益活动'})
        a=r['assistance'];self.assertFalse(a['plan']['ready']);self.assertTrue(a['plan']['issues'])
        self.assertEqual(self.action(r,'publish').status_code,409)
        self.assertIsNone(r['draft'])
        with self.service.database.connect() as c:
            for table in ('tasks','volunteer_activities'):self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_volunteer_plan_update_confirm_restore_and_isolation(self):
        r=self.plan();a=r['assistance'];self.assertTrue(a['plan']['ready'],a['plan'])
        cid=r['conversation_id']
        restored=self.client.get('/api/guide/conversations/'+cid).json()
        self.assertEqual(restored['assistance']['plan']['fields'],a['plan']['fields'])
        self.login('observer')
        self.assertEqual(self.client.get('/api/guide/assistance/'+cid).status_code,404)
        self.assertEqual(self.action(r,'publish').status_code,404)
        self.login()
        result=self.action(r,'publish');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['plan']['status'],'published')
        published=self.vol.detail(result.json()['plan']['resource_id'],self.owner)
        self.assertEqual(len(published['jobs']),2)
        # No need to call an LLM to confirm.
        self.assertEqual(self.action(result.json(),'publish').status_code,200)
        self.assertEqual(self.action(r,'publish').status_code,200)
        with self.service.database.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM volunteer_activities').fetchone()[0],1)

    def test_activity_plan_publishes_to_distinct_business(self):
        payload=activity_helpers.ActivityTests.payload(self)
        r=self.plan('activity',payload)
        result=self.action(r,'publish');self.assertEqual(result.status_code,200,result.text)
        with self.service.database.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM activities').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM volunteer_activities').fetchone()[0],0)

    def test_stale_plan_version_and_invalid_time_rejected(self):
        r=self.plan();new=self.chat([helpers.calling('update_volunteer_plan',{'fields':{'title':'新标题'}})],conversation_id=r['conversation_id'])
        self.assertEqual(self.action(r,'publish').status_code,409)
        self.now+=timedelta(hours=6)
        self.assertEqual(self.action(new,'publish').status_code,409)

    def test_preferences_require_authorization_and_preserve_unspecified_fields(self):
        self.login('helper')
        r=self.chat([helpers.calling('propose_preferences',{'changes':{'skills':['摄影'],'interests':['环保'],'notifications_enabled':True}})])
        self.assertEqual(self.guide.assistance.preferences(self.helper)['version'],0)
        result=self.action(r,'preferences',profile_version=0);self.assertEqual(result.status_code,200,result.text)
        profile=self.guide.assistance.preferences(self.helper)
        self.assertEqual(profile['fields']['skills'],['摄影'])
        r=self.chat([helpers.calling('propose_preferences',{'changes':{'notifications_enabled':False}})])
        self.assertEqual(self.action(r,'preferences',profile_version=0).status_code,409)
        self.assertEqual(self.action(r,'preferences',profile_version=1).status_code,200)
        profile=self.guide.assistance.preferences(self.helper)
        self.assertEqual(profile['fields']['interests'],['环保']);self.assertFalse(profile['fields']['notifications_enabled'])

    def test_tool_failure_rolls_back_plan_and_preferences(self):
        class Broken(FakeBackend):
            def chat(inner,*args,**kwargs):
                if inner.requests:raise TimeoutError()
                return super().chat(*args,**kwargs)
        self.guide.backend_factory=lambda:Broken([{'content':'','tool_calls':[{'name':'update_volunteer_plan','arguments':{'fields':{'title':'未提交'}}},{'name':'propose_preferences','arguments':{'changes':{'skills':['摄影']}}}]}])
        r=self.client.post('/api/guide/chat',json={'message':'整理'})
        self.assertEqual(r.status_code,504,r.text)
        with self.service.database.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM guide_assistance').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM participation_preferences').fetchone()[0],0)

    def test_matching_notification_dedup_dismiss_and_registration(self):
        self.preferences()
        a=self.vol.create(VolunteerCreate.model_validate(self.payload()),self.owner)
        match=self.guide.matching;match.reconcile()
        items=match.list(self.helper)['items'];self.assertEqual(len(items),2)
        self.assertTrue(items[0]['reasons']);self.assertTrue(items[0]['checks'])
        match.reconcile()
        with self.service.database.connect() as c:
            count=c.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(self.helper,)).fetchone()[0]
        self.assertEqual(count,2)
        match.dismiss(self.helper,items[0]['id']);match.reconcile()
        self.assertEqual(match.list(self.helper)['total'],1)
        self.vol.register(a['jobs'][1]['id'],self.helper,'参加')
        match.reconcile();self.assertEqual(match.list(self.helper)['total'],0)

    def test_worker_generates_reminder_without_chat_and_restart_does_not_duplicate(self):
        self.preferences();self.vol.create(VolunteerCreate.model_validate(self.payload()),self.owner)
        self.guide.matching.start()
        for _ in range(100):
            if self.guide.matching.list(self.helper)['total']:break
            time.sleep(.03)
        self.guide.matching.stop()
        self.assertEqual(self.guide.matching.list(self.helper)['total'],2)
        from campus.matching import MatchingService
        MatchingService(self.service).reconcile()
        with self.service.database.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'opportunity:%'").fetchone()[0],2)

    def test_time_filters_cancellation_and_disabled_reminders(self):
        self.preferences(available_slots=[{'starts_at':(self.now+timedelta(hours=2)).isoformat(),'ends_at':(self.now+timedelta(hours=3)).isoformat()}])
        a=self.vol.create(VolunteerCreate.model_validate(self.payload()),self.owner)
        match=self.guide.matching;match.reconcile()
        self.assertEqual(match.list(self.helper)['total'],1)
        self.vol.cancel_activity(a['id'],self.owner,'测试取消');match.reconcile()
        self.assertEqual(match.list(self.helper)['total'],0)

    def test_weekly_and_one_time_availability_and_exceptions(self):
        start=datetime(2030,1,5,6,tzinfo=timezone.utc);end=start+timedelta(hours=1)
        p=Preferences(weekly_slots=[{'weekday':5,'starts':'14:00','ends':'16:00'}])
        self.assertTrue(availability(p,start,end)[0]);self.assertFalse(availability(p,start+timedelta(days=1),end+timedelta(days=1))[0])
        p=Preferences.model_validate(p.model_dump()|{'unavailable_slots':[{'starts_at':start.isoformat(),'ends_at':end.isoformat()}]})
        self.assertFalse(availability(p,start,end)[0])

    def test_trace_contains_actual_ids_timestamps_and_safe_summaries(self):
        r=self.plan()
        run=self.guide.runs.read(r['run_id'],self.owner)
        starts=[e for e in run['events'] if e['kind']=='tool_started'];ends=[e for e in run['events'] if e['kind']=='tool_finished']
        self.assertEqual(starts[0]['call_id'],ends[0]['call_id']);self.assertIn('at',starts[0]);self.assertIn('summary',ends[0])
        trace=json.dumps(run['events'],ensure_ascii=False)
        self.assertNotIn('arguments',trace);self.assertNotIn('建议增加一名机动人员',trace)

    def test_concrete_preference_action_cannot_finish_with_generic_greeting(self):
        self.login('helper')
        self.guide.backend_factory=lambda:FakeBackend([{'content':'你好，我可以帮助你。'},helpers.calling('propose_preferences',{'changes':{'skills':['摄影']}}),{'content':'请核对偏好卡片。'}])
        result=self.client.post('/api/guide/chat',json={'message':'我会摄影，请登记我的技能偏好。'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['assistance']['preference_proposal']['fields']['skills'],['摄影'])
        self.assertEqual(self.guide.assistance.preferences(self.helper)['version'],0)
        self.assertEqual(self.action(result.json(),'publish').status_code,409)
        self.assertEqual(self.action(result.json(),'cancel').status_code,409)

    def test_preference_form_clears_stale_proposals_and_checks_version(self):
        self.login('helper')
        r=self.chat([helpers.calling('propose_preferences',{'changes':{'skills':['旧偏好']}})],message='请登记技能旧偏好')
        fields=Preferences(skills=['新偏好']).model_dump(mode='json')
        self.assertEqual(self.client.put('/api/guide/preferences',json={'version':0,'fields':fields}).status_code,200)
        self.assertIsNone(self.guide.assistance.read(r['conversation_id'],self.helper)['preference_proposal'])
        self.assertEqual(self.client.put('/api/guide/preferences',json={'version':0,'fields':fields}).status_code,409)
        self.assertEqual(self.action(r,'preferences',profile_version=0).status_code,409)

    def test_plan_form_edit_clear_and_versions(self):
        r=self.plan();a=r['assistance'];url='/api/guide/assistance/'+r['conversation_id']+'/plan'
        fields=a['plan']['fields']|{'title':'手动编辑后的活动'};fields.pop('contact')
        edited=self.client.put(url,json={'version':a['version'],'fields':fields})
        self.assertEqual(edited.status_code,200,edited.text)
        self.assertFalse(edited.json()['plan']['ready'])
        self.assertEqual(edited.json()['plan']['fields']['title'],'手动编辑后的活动')
        self.assertEqual(self.client.put(url,json={'version':a['version'],'fields':fields}).status_code,409)
        self.login('helper');self.assertEqual(self.client.put(url,json={'version':a['version'],'fields':fields}).status_code,404)

    def test_publishing_rollback_keeps_draft_unpublished(self):
        r=self.plan();original=self.vol.create
        def broken(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('simulated transaction failure')
        with patch.object(self.vol,'create',side_effect=broken),self.assertRaises(RuntimeError):
            self.guide.assistance.action(r['conversation_id'],self.owner,r['assistance']['version'],'publish')
        with self.service.database.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM volunteer_activities').fetchone()[0],0)
        self.assertEqual(self.guide.assistance.read(r['conversation_id'],self.owner)['plan']['status'],'draft')

    def test_disabled_reminders_capacity_and_expiry(self):
        self.preferences()
        fields=self.guide.assistance.preferences(self.helper)['fields']|{'notifications_enabled':False}
        self.guide.assistance.save_preferences(self.helper,fields,1)
        a=self.vol.create(VolunteerCreate.model_validate(self.payload()),self.owner)
        match=self.guide.matching;match.reconcile()
        self.assertEqual(match.list(self.helper)['total'],2)
        with self.service.database.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'opportunity:%'").fetchone()[0],0)
        self.vol.register(a['jobs'][0]['id'],self.users['observer'][1].id,'参加')
        match.reconcile();self.assertEqual(match.list(self.helper)['total'],1)
        self.now+=timedelta(hours=2)
        match.reconcile();self.assertEqual(match.list(self.helper)['total'],0)

    def test_explicit_input_rejects_invented_or_omitted_preferences(self):
        from campus.assistance import AssistanceBuffer
        buffer=AssistanceBuffer(self.guide.assistance,'f'*32,self.owner,json.dumps({'skills':['摄影'],'available_slots':[{'starts_at':'2030-01-01T02:00:00Z','ends_at':'2030-01-01T03:00:00Z'}]}))
        with self.assertRaises(ValueError):buffer.preferences({'skills':['设计']})
        with self.assertRaises(ValueError):buffer.preferences({'skills':['摄影'],'available_slots':[{'starts_at':'2030-01-01T02:00:00Z','ends_at':'2030-01-01T03:00:00Z'}],'locations':['杭州']})
        self.assertFalse(buffer.dirty)

    def test_dialogue_can_clear_an_activity_field_and_query_must_use_tool(self):
        r=self.plan()
        cleared=self.chat([helpers.calling('update_volunteer_plan',{'fields':{'contact':None}})],message='清除联系方式，已确认变更 {"contact":null}',conversation_id=r['conversation_id'])
        self.assertNotIn('contact',cleared['assistance']['plan']['fields'])
        self.assertFalse(cleared['assistance']['plan']['ready'])
        self.login('helper')
        self.guide.backend_factory=lambda:FakeBackend([{'content':'你的报名正在等待。'},helpers.calling('get_my_volunteer_registrations'),{'content':'当前没有志愿报名记录。'}])
        result=self.client.post('/api/guide/chat',json={'message':'请查询我的志愿报名状态'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(any(t['name']=='get_my_volunteer_registrations' for t in result.json()['tools_used']))

    def test_activity_and_ordinary_opportunities_use_distinct_resources(self):
        self.preferences(content_types=['activity','ordinary'])
        activity=self.app.state.activity_service.create(ActivityCreate.model_validate(activity_helpers.ActivityTests.payload(self)|{'description':'公益摄影讲座'}),self.owner)
        from campus.schemas import TaskCreate,TASK_CREATE_EXAMPLE
        task=self.service.create_task(TaskCreate.model_validate(TASK_CREATE_EXAMPLE|{'title':'公益摄影互助','deadline':(self.now+timedelta(days=2)).isoformat()}),self.owner)
        self.guide.matching.reconcile()
        items=self.guide.matching.list(self.helper)['items']
        self.assertEqual({i['content_type'] for i in items},{'activity','ordinary'})
        self.assertTrue(any(i['resource_id']==activity['id'] for i in items))
        ordinary=next(i for i in items if i['resource_id']==task.id)
        self.assertIsNone(ordinary['starts_at']);self.assertTrue(any('确认' in c for c in ordinary['checks']))


if __name__=='__main__':unittest.main()
