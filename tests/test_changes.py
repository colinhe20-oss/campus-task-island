import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
import test_terms as base
from campus.schemas import ChangeInput,ExtensionReviewInput,StagePlanInput,StageActionInput,StageSubmitInput,StageReviewInput
from campus.errors import AppError
from tools.campus import build_campus_registry


class ChangeTests(unittest.TestCase):
    setUp=base.TermsTests.setUp
    login=base.TermsTests.login
    stamp=base.TermsTests.stamp
    create=base.TermsTests.create
    join=base.TermsTests.join
    finish=base.TermsTests.finish
    count=base.TermsTests.count

    def ready(self,staged=False):
        t=self.create()
        if staged:
            self.app.state.stage_service.set_plan(t,self.users['publisher'],StagePlanInput(expected_version=0,stages=self.fields()))
        self.join(t);self.login('helper');return t

    def fields(self):
        return [dict(title='初稿',completion_criteria='交初稿',deadline=self.stamp(.5),responsible_role='assignee'),
                dict(title='交付',completion_criteria='交终稿',deadline=self.stamp(1),responsible_role='assignee')]

    def propose(self,t,changes,**extra):
        response=self.client.post(f'/api/tasks/{t}/changes',json=dict(version=self.service.get_task(t).terms_version,reason='共同协商',changes=changes,**extra))
        self.assertEqual(response.status_code,200,response.text);return response.json()['items'][0]

    def review(self,r,decision='approve',reason='',name='publisher'):
        self.login(name);return self.client.post('/api/task-changes/'+r['id']+'/review',json=dict(version=r['version'],decision=decision,reason=reason))

    def state(self,t):return self.client.get(f'/api/tasks/{t}/changes').json()
    def stages(self,t):return self.client.get(f'/api/tasks/{t}/stages').json()['stages']

    def test_combined_change_not_effective_until_counterparty_approval(self):
        t=self.ready();r=self.propose(t,dict(deadline=self.stamp(2),description='新工作范围',completion_criteria='新标准',reward=dict(reward_type='paid',reward_amount_fen=2550,reward='全部完成后支付')))
        self.assertEqual(self.service.get_task(t).reward_type,'mutual');self.assertEqual(self.service.get_task(t).terms_version,1)
        self.assertEqual(self.review(r).status_code,200)
        task=self.service.get_task(t);self.assertEqual(task.terms_version,2);self.assertEqual(task.reward_amount_fen,2550);self.assertEqual(task.description,'新工作范围')
        self.assertEqual(self.client.get(f'/api/tasks/{t}/agreements/1').json()['fields']['reward_type'],'mutual')
        self.assertEqual(self.client.get(f'/api/tasks/{t}/agreements/2').json()['fields']['reward_type'],'paid')

    def test_roles_reject_reason_withdraw_and_repeat(self):
        t=self.ready();r=self.propose(t,dict(description='新范围'))
        self.assertEqual(self.review(r,name='helper').status_code,403)
        self.assertEqual(self.review(r,decision='reject').status_code,422)
        self.assertEqual(self.review(r,decision='reject',reason='不接受范围').status_code,200)
        n=self.count('notifications');self.assertEqual(self.review(r).status_code,409);self.assertEqual(n,self.count('notifications'))
        self.login('helper');r=self.propose(t,dict(description='再商量'))
        self.login('publisher');url='/api/task-changes/'+r['id']+'/cancel';self.assertEqual(self.client.post(url,json={'version':1}).status_code,403)
        self.login('helper');self.assertEqual(self.client.post(url,json={'version':1}).status_code,200)
        self.assertEqual(self.client.post(url,json={'version':1}).status_code,409)

    def test_unknown_empty_null_and_noop_fields(self):
        t=self.ready()
        for changes in ({},{'description':self.service.get_task(t).description},{'deadline':self.stamp(1)},{'description':None},{'title':'改名'},{'reward':{'reward_type':'legacy'}},{'stages':[]}):
            r=self.client.post(f'/api/tasks/{t}/changes',json={'version':1,'reason':'变更','changes':changes});self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.count('task_changes'),0)

    def test_initial_stage_plan_requires_both_parties_and_direct_bypass_rejected(self):
        t=self.ready();self.login('publisher')
        self.assertEqual(self.client.post(f'/api/tasks/{t}/stages',json={'expected_version':0,'stages':self.fields()}).status_code,409)
        r=self.propose(t,dict(initial_stages=self.fields()));self.assertEqual(self.stages(t),[])
        self.assertEqual(self.review(r,name='helper').status_code,200);self.assertEqual(len(self.stages(t)),2)
        self.assertEqual(self.service.get_task(t).terms_version,2)
        self.login('publisher');self.assertEqual(self.client.post(f'/api/tasks/{t}/stages',json={'expected_version':1,'stages':self.fields()}).status_code,409)

    def test_existing_stage_change_updates_both_versions_and_snapshots(self):
        t=self.ready(True);s=self.stages(t)[0]
        r=self.propose(t,dict(stages=[dict(id=s['id'],version=1,completion_criteria='新的交付要求',deadline=self.stamp(.75))]))
        self.assertEqual(self.review(r).status_code,200)
        panel=self.client.get(f'/api/tasks/{t}/stages').json();self.assertEqual(panel['plan_version'],2);self.assertEqual(panel['stages'][0]['version'],2)
        self.assertEqual(panel['stages'][0]['title'],s['title']);self.assertEqual(len(panel['versions']),2)
        self.assertEqual(self.service.get_task(t).terms_version,3)
        self.login('helper');self.assertEqual(self.client.post(f'/api/tasks/{t}/stages/{s["id"]}/start',json={'version':1}).status_code,409)

    def test_stage_order_upper_bound_and_confirmed_stage_immutable(self):
        t=self.ready(True);s=self.stages(t)[0]
        for changes in (dict(deadline=self.stamp(.25)),dict(stages=[dict(id=s['id'],version=1,deadline=self.stamp(2))]),dict(stages=[dict(id=s['id'],version=1,title='改名')])):
            self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':2,'reason':'变更','changes':changes}).status_code,422)
        self.app.state.stage_service.start(t,s['id'],self.users['helper'],1)
        self.app.state.stage_service.submit(t,s['id'],self.users['helper'],StageSubmitInput(version=2,summary='完成'))
        self.app.state.stage_service.review(t,s['id'],self.users['publisher'],StageReviewInput(version=3,decision='accept'))
        self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':2,'reason':'修改完成阶段','changes':{'stages':[dict(id=s['id'],version=4,completion_criteria='重做')]}}).status_code,409)

    def test_submitted_stage_criteria_and_global_scope_need_return(self):
        t=self.ready(True);s=self.stages(t)[0];stages=self.app.state.stage_service
        stages.start(t,s['id'],self.users['helper'],1);stages.submit(t,s['id'],self.users['helper'],StageSubmitInput(version=2,summary='成果'))
        for changes in (dict(description='新范围'),dict(completion_criteria='新整体标准'),dict(stages=[dict(id=s['id'],version=3,completion_criteria='新要求')])):
            self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':2,'reason':'变更','changes':changes}).status_code,409)
        r=self.propose(t,dict(stages=[dict(id=s['id'],version=3,deadline=self.stamp(.75))]));self.assertEqual(self.review(r).status_code,200)
        stages.review(t,s['id'],self.users['publisher'],StageReviewInput(version=4,decision='request_changes',feedback='补充'))
        self.login('helper');self.propose(t,dict(description='退回后可协商'))

    def test_stage_progress_stales_bound_changes_and_notifies_both(self):
        t=self.ready(True);s=self.stages(t)[0];r=self.propose(t,dict(description='范围变更'))
        n=self.count('notifications');self.app.state.stage_service.start(t,s['id'],self.users['helper'],1)
        self.assertEqual(self.state(t)['items'][0]['status'],'stale');self.assertEqual(self.count('notifications'),n+3)
        self.assertEqual(self.review(r).status_code,409)
        self.login('helper');self.propose(t,dict(description='核对后的变更'))

    def test_unrelated_stage_progress_does_not_stale_reward(self):
        t=self.ready(True);s=self.stages(t)[0];r=self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=100,reward='支付')))
        self.app.state.stage_service.start(t,s['id'],self.users['helper'],1)
        self.assertEqual(self.review(r).status_code,200)

    def test_whole_submission_invalidates_scope_but_reward_deadline_remains(self):
        for changes,expected in ((dict(description='新范围'),'stale'),(dict(deadline=self.stamp(2)),'pending'),(dict(reward=dict(reward_type='paid',reward_amount_fen=100,reward='支付')),'pending')):
            t=self.ready();r=self.propose(t,changes);submission=self.service.submit(t,self.users['helper'],'整项成果')
            self.assertEqual(submission.terms_version,1);self.assertEqual(self.state(t)['items'][0]['status'],expected)
            if expected=='pending':self.assertEqual(self.review(r).status_code,200)

    def test_completion_closes_pending_and_final_reward_settlement(self):
        t=self.ready();r=self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=2567,reward='确认金额')));self.assertEqual(self.review(r).status_code,200)
        self.login('helper');self.propose(t,dict(deadline=self.stamp(2)));self.finish(t)
        self.assertEqual(self.state(t)['items'][0]['status'],'closed')
        self.assertEqual(self.client.get(f'/api/tasks/{t}/settlement').json()['amount_fen'],2567)
        self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':2,'reason':'完成后修改','changes':{'description':'不能更改'}}).status_code,409)

    def test_earlier_deadline_future_at_propose_and_approve(self):
        t=self.ready();r=self.propose(t,dict(deadline=self.stamp(.5)));self.assertEqual(self.review(r).status_code,200)
        self.login('helper');r=self.propose(t,dict(deadline=self.stamp(.75)));self.now+=timedelta(hours=.75)
        self.assertEqual(self.review(r).status_code,422);self.assertEqual(self.service.get_task(t).terms_version,2)

    def test_overdue_unchanged_stage_times_allowed(self):
        t=self.ready(True);self.now+=timedelta(hours=2)
        r=self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=100,reward='逾期仍可协商')))
        self.assertEqual(self.review(r).status_code,200)

    def test_reward_validation_conversion_and_legacy(self):
        t=self.ready()
        for reward in (dict(reward_type='paid'),dict(reward_type='paid',reward_amount_fen=1.5,reward='金额'),dict(reward_type='paid',reward_amount_fen=1,reward='  '),dict(reward_type='mutual',reward_amount_fen=1)):
            self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':1,'reason':'变更','changes':{'reward':reward}}).status_code,422)
        with self.service.database.connect() as c:c.execute("UPDATE tasks SET reward_type='legacy' WHERE id=?",(t,))
        r=self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=1,reward='补齐历史约定')));self.assertEqual(self.review(r).status_code,200)
        self.login('helper');r=self.propose(t,dict(reward=dict(reward_type='mutual',reward='改为互助')));self.assertEqual(self.review(r).status_code,200)
        self.assertIsNone(self.service.get_task(t).reward_amount_fen)

    def test_legacy_extensions_share_pending_slot_and_archive_is_readonly(self):
        t=self.ready();r=self.propose(t,dict(description='修改'))
        self.assertEqual(self.client.post(f'/api/tasks/{t}/extensions',json={'version':1,'deadline':self.stamp(3),'reason':'延期'}).status_code,409)
        self.client.post('/api/task-changes/'+r['id']+'/cancel',json={'version':1})
        old=self.client.post(f'/api/tasks/{t}/extensions',json={'version':1,'deadline':self.stamp(3),'reason':'延期'}).json()['items'][0]
        self.assertEqual(self.client.post(f'/api/tasks/{t}/changes',json={'version':1,'reason':'修改','changes':{'description':'修改'}}).status_code,409)
        self.login('publisher');self.assertEqual(self.client.post('/api/task-extensions/'+old['id']+'/review',json={'version':1,'decision':'approve'}).status_code,200)
        self.assertEqual(self.count('task_extensions'),0)

    def test_concurrent_proposals_singleton(self):
        t=self.ready();body=ChangeInput(version=1,reason='并发',changes={'description':'新范围'})
        def send(user):
            try:self.service.terms.changes.propose(t,user,body);return 200
            except AppError as e:return e.status_code
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(send,[self.users['helper'],self.users['publisher']])),[200,409])
        self.assertEqual(self.count('task_changes'),1)

    def test_approval_stage_start_race_never_overwrites_progress(self):
        t=self.ready(True);s=self.stages(t)[0];r=self.propose(t,dict(stages=[dict(id=s['id'],version=1,completion_criteria='新要求')]))
        def run(approve):
            try:
                if approve:self.service.terms.changes.decide(r['id'],self.users['publisher'],ExtensionReviewInput(version=1,decision='approve'))
                else:self.app.state.stage_service.start(t,s['id'],self.users['helper'],1)
                return 200
            except AppError as e:return e.status_code
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(run,[True,False])),[200,409])

    def test_rollback_and_readonly_private(self):
        t=self.ready();body=ChangeInput(version=1,reason='范围变更',changes={'description':'私有提案'})
        with patch('campus.changes.emit',side_effect=RuntimeError('消息失败')):
            with self.assertRaises(RuntimeError):self.service.terms.changes.propose(t,self.users['helper'],body)
        self.assertEqual(self.count('task_changes'),0)
        r=self.propose(t,body.changes.model_dump(exclude_unset=True));n=self.count('notifications')
        with patch('campus.changes.emit',side_effect=RuntimeError('消息失败')):
            with self.assertRaises(RuntimeError):self.service.terms.changes.decide(r['id'],self.users['publisher'],ExtensionReviewInput(version=1,decision='approve'))
        self.assertEqual(self.service.get_task(t).terms_version,1);self.assertEqual(self.state(t)['items'][0]['status'],'pending')
        for _ in range(2):self.state(t);self.client.get(f'/api/tasks/{t}/agreements/1')
        self.assertEqual(n,self.count('notifications'))
        self.login('observer')
        for url in (f'/api/tasks/{t}/changes',f'/api/tasks/{t}/agreements/1'):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertNotIn('私有提案',self.client.get(f'/api/tasks/{t}').text)

    def test_agent_current_and_pending_separate(self):
        t=self.ready();self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=1234,reward='待同意')))
        data=json.loads(build_campus_registry(self.service,self.users['helper']).get('get_task_detail').invoke({'task_id':t}))
        self.assertEqual(data['agreement']['reward_type'],'mutual');self.assertEqual(data['changes'][0]['status'],'pending')
        outsider=build_campus_registry(self.service,self.users['observer']).get('get_task_detail').invoke({'task_id':t})
        self.assertNotIn('待同意',outsider)

    def test_submission_versions_and_missing_history(self):
        t=self.ready();s=self.service.submit(t,self.users['helper'],'原成果');self.assertEqual(s.terms_version,1)
        with self.service.database.connect() as c:c.execute('UPDATE submissions SET terms_version=NULL WHERE id=?',(s.id,))
        self.assertIsNone(self.service.workspace(t,self.users['publisher']).submissions[0].terms_version)
        self.assertEqual(self.client.get(f'/api/tasks/{t}/agreements/99').status_code,404)

    def test_migration_preserves_archive_and_does_not_notify_or_invent_history(self):
        t=self.ready();stamp=self.stamp(0)
        with self.service.database.connect() as c:
            c.execute('''INSERT INTO task_extensions (id,task_id,requester_id,old_deadline,new_deadline,reason,terms_version,status,created_at,updated_at)
                VALUES ('legacy-id',?,?,?,?,?,1,'pending',?,?)''',(t,self.users['helper'],self.stamp(1),self.stamp(3),'旧延期',stamp,stamp))
            c.execute('DELETE FROM task_agreements WHERE task_id=?',(t,))
            before=dict(c.execute("SELECT * FROM task_extensions WHERE id='legacy-id'").fetchone())
        n=self.count('notifications');self.service.initialize();self.service.initialize()
        self.assertEqual(n,self.count('notifications'));self.assertEqual(self.count('task_changes'),1)
        row=self.state(t)['items'][0];self.assertEqual(row['id'],'legacy-id');self.assertEqual(row['created_at'],stamp)
        self.login('publisher');self.assertEqual(self.client.post('/api/task-extensions/legacy-id/review',json={'version':1,'decision':'approve'}).status_code,200)
        with self.service.database.connect() as c:self.assertEqual(dict(c.execute("SELECT * FROM task_extensions WHERE id='legacy-id'").fetchone()),before)
        self.service.initialize();self.assertEqual(self.state(t)['items'][0]['status'],'approved')

    def test_stage_submission_links_current_agreement(self):
        t=self.ready(True);s=self.stages(t)[0]
        stages=self.app.state.stage_service;stages.start(t,s['id'],self.users['helper'],1)
        panel=stages.submit(t,s['id'],self.users['helper'],StageSubmitInput(version=2,summary='初稿'))
        self.assertEqual(panel.stages[0].submissions[0].terms_version,2)
        snap=self.client.get(f'/api/tasks/{t}/agreements/2').json()['fields'];self.assertEqual(snap['stages'][0]['id'],s['id'])

    def test_legacy_stale_maps_to_closed(self):
        t=self.ready(True);s=self.stages(t)[0]
        r=self.client.post(f'/api/tasks/{t}/extensions',json={'version':2,'deadline':self.stamp(3),'reason':'延期'}).json()['items'][0]
        self.app.state.stage_service.start(t,s['id'],self.users['helper'],1)
        self.assertEqual(self.state(t)['items'][0]['status'],'stale')
        old=self.client.get(f'/api/tasks/{t}/extensions').json()['items'][0]
        self.assertEqual(old['status'],'closed');self.assertIn('重新申请',old['review_reason'])
        self.assertEqual(old['id'],r['id'])

    def test_initial_ai_suggestion_adopted_only_after_approval(self):
        t=self.ready();stamp=self.stamp(0);identifier='a'*32;conversation='b'*32
        with self.service.database.connect() as c:
            c.execute('INSERT INTO guide_conversations VALUES (?,?,?,?)',(conversation,self.users['publisher'],'[]',stamp))
            c.execute('INSERT INTO stage_suggestions (id,task_id,user_id,conversation_id,base_version,fields,created_at) VALUES (?,?,?,?,0,?,?)',(identifier,t,self.users['publisher'],conversation,json.dumps(self.fields()),stamp))
        self.login('publisher');r=self.propose(t,dict(initial_stages=self.fields()),suggestion_id=identifier)
        self.assertIsNone(self.client.get(f'/api/tasks/{t}/stages').json()['suggestion']['applied_version'])
        self.assertEqual(self.review(r,name='helper').status_code,200)
        self.login('publisher');self.assertEqual(self.client.get(f'/api/tasks/{t}/stages').json()['suggestion']['applied_version'],1)

    def test_completion_and_change_approval_serializable(self):
        t=self.ready();self.service.submit(t,self.users['helper'],'完整成果')
        r=self.propose(t,dict(reward=dict(reward_type='paid',reward_amount_fen=500,reward='新的报酬')))
        def run(approve):
            try:
                if approve:self.service.terms.changes.decide(r['id'],self.users['publisher'],ExtensionReviewInput(version=1,decision='approve'))
                else:self.service.review(t,self.users['publisher'],'accept','完成')
                return 200
            except AppError as e:return e.status_code
        with ThreadPoolExecutor(2) as pool:codes=list(pool.map(run,[True,False]))
        self.assertIn(200,codes);self.assertEqual(self.service.get_task(t).status,'completed')
        row=self.state(t)['items'][0]
        self.assertIn(row['status'],('closed','approved'))
        task=self.service.get_task(t);self.assertEqual(task.reward_type,'paid' if row['status']=='approved' else 'mutual')
