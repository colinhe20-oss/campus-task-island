import unittest
from datetime import datetime,timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import test_terms as base
from campus.schemas import StagePlanInput
from campus.todos import personal_state


class CollaborationLifecycleTests(unittest.TestCase):
    setUp=base.TermsTests.setUp
    login=base.TermsTests.login
    stamp=base.TermsTests.stamp
    create=base.TermsTests.create
    join=base.TermsTests.join
    count=base.TermsTests.count

    def control(self,task,action,*,name='helper',reason='一起商量处理',**extra):
        self.login(name);task_row=self.service.get_task(task)
        response=self.client.post(f'/api/tasks/{task}/collaboration-requests',json={
            'action':action,'version':task_row.terms_version,'collaboration_version':task_row.collaboration_version,
            'reason':reason,'extend_deadline':bool(extra.pop('extend_deadline',False)),**extra})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['items'][0]

    def decide(self,row,*,decision='approve',name='publisher',reason='已与对方确认'):
        self.login(name)
        return self.client.post(f"/api/task-changes/{row['id']}/review",json={'version':row['version'],'decision':decision,'reason':reason})

    def test_application_withdrawal_retry_and_reapply_keep_separate_attempts(self):
        task=self.create();self.login('helper');request_id='11111111-1111-4111-8111-111111111111'
        first=self.client.post(f'/api/tasks/{task}/applications',json={'reason':'第一次','request_id':request_id}).json()
        self.assertEqual(self.client.post(f"/api/applications/{first['id']}/withdraw").status_code,200)
        self.assertEqual(self.client.post(f"/api/applications/{first['id']}/withdraw").status_code,200)
        second=self.client.post(f'/api/tasks/{task}/applications',json={'reason':'重新申请','request_id':'22222222-2222-4222-8222-222222222222'}).json()
        rows=self.client.get(f'/api/tasks/{task}/workspace').json()['applications']
        self.assertEqual({r['id']:r['status'] for r in rows},{first['id']:'withdrawn',second['id']:'pending'})
        self.assertEqual(self.client.post(f"/api/applications/{first['id']}/withdraw").status_code,200)
        self.assertEqual(self.client.get(f'/api/tasks/{task}/workspace').json()['applications'][0]['id'],second['id'])

    def test_pause_extension_freezes_and_resume_restores_execution_state(self):
        task=self.create()
        stages=[dict(title='第一阶段',completion_criteria='交初稿',deadline=self.stamp(.5),responsible_role='assignee')]
        self.login('publisher');self.app.state.stage_service.set_plan(task,self.users['publisher'],StagePlanInput(expected_version=0,stages=stages))
        self.join(task)
        self.login('helper');row=self.control(task,'pause',extend_deadline=True,deadline=self.stamp(2))
        self.assertEqual(row['kind'],'pause');self.assertEqual(self.service.get_task(task).status,'in_progress')
        self.assertEqual(self.decide(row).status_code,200);paused=self.service.get_task(task)
        self.assertEqual(paused.status,'paused');self.assertEqual(paused.deadline,self.service.current_time()+timedelta(hours=2))
        panel=self.client.get(f'/api/tasks/{task}/stages').json();stage=panel['stages'][0]
        self.assertEqual(datetime.fromisoformat(stage['deadline']),datetime.fromisoformat(self.stamp(.5)));self.assertEqual(self.client.post(f"/api/tasks/{task}/stages/{stage['id']}/start",json={'version':stage['version']}).status_code,409)
        resume=self.control(task,'resume',name='publisher',reason='双方准备恢复')
        self.assertEqual(self.decide(resume,name='helper').status_code,200)
        restored=self.service.get_task(task);self.assertEqual(restored.status,'in_progress');self.assertEqual(restored.collaboration_version,3)
        self.assertEqual(self.client.post(f"/api/tasks/{task}/stages/{stage['id']}/start",json={'version':stage['version']}).status_code,409)

    def test_cancel_requires_no_pending_review_and_preserves_paid_cancel_settlement(self):
        task=self.create(paid=True);self.join(task)
        self.login('helper');self.assertEqual(self.client.post(f'/api/tasks/{task}/submissions',json={'summary':'待验收成果','collaboration_version':1}).status_code,201)
        self.login('helper');blocked=self.client.post(f'/api/tasks/{task}/collaboration-requests',json={'action':'cancel','version':1,'collaboration_version':1,'reason':'无法继续','extend_deadline':False,'cancellation_settlement_fen':500})
        self.assertEqual(blocked.status_code,409)
        self.login('publisher');self.client.post(f'/api/tasks/{task}/review',json={'decision':'request_changes','feedback':'先补充成果','collaboration_version':1})
        row=self.control(task,'cancel',cancellation_settlement_fen=500)
        self.assertEqual(self.decide(row).status_code,200)
        cancelled=self.service.get_task(task);self.assertEqual(cancelled.status,'cancelled');self.assertEqual(cancelled.cancellation_settlement_fen,500)
        self.login('publisher');settlement=self.client.get(f'/api/tasks/{task}/settlement').json();self.assertTrue(settlement['available']);self.assertEqual(settlement['amount_fen'],500)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/settlement/confirmation',json={'confirmed':True,'version':settlement['version']}).status_code,200)
        self.login('helper');settlement=self.client.get(f'/api/tasks/{task}/settlement').json();self.assertFalse(settlement['both_confirmed'])
        self.assertEqual(self.client.post(f'/api/tasks/{task}/settlement/confirmation',json={'confirmed':True,'version':settlement['version']}).status_code,200)
        self.assertTrue(self.client.get(f'/api/tasks/{task}/settlement').json()['both_confirmed'])
        self.assertEqual(personal_state(self.service,self.users['publisher']).completed_count,0)

    def test_cancel_zero_needs_no_settlement_and_pending_slot_is_shared(self):
        task=self.create(paid=True);self.join(task)
        self.login('helper');row=self.control(task,'pause')
        state=self.client.get(f'/api/tasks/{task}/changes').json()
        self.assertEqual(state['items'][0]['kind'],'pause')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/changes',json={'version':1,'reason':'不能并发占用','changes':{'description':'覆盖'}}).status_code,409)
        self.assertEqual(self.decide(row,decision='reject',reason='现在不暂停').status_code,200)
        row=self.control(task,'cancel',cancellation_settlement_fen=0)
        self.assertEqual(self.decide(row).status_code,200)
        self.login('publisher');settlement=self.client.get(f'/api/tasks/{task}/settlement').json()
        self.assertTrue(settlement['no_payment_required']);self.assertFalse(settlement['available']);self.assertEqual(settlement['amount_fen'],0)

    def test_submission_progress_invalidates_pending_control_and_old_version_is_rejected_after_resume(self):
        task=self.create();self.join(task);row=self.control(task,'pause')
        self.login('helper');response=self.client.post(f'/api/tasks/{task}/submissions',json={'summary':'协作已推进','collaboration_version':1})
        self.assertEqual(response.status_code,201)
        self.login('publisher');state=self.client.get(f'/api/tasks/{task}/changes').json();self.assertEqual(state['items'][0]['status'],'stale')
        review_url='/api/task-changes/'+row['id']+'/review'
        self.assertEqual(self.client.post(review_url,json={'version':1,'decision':'approve'}).status_code,409)
        self.client.post(f'/api/tasks/{task}/review',json={'decision':'request_changes','feedback':'继续调整','collaboration_version':1})
        pause=self.control(task,'pause');self.assertEqual(self.decide(pause).status_code,200)
        resume=self.control(task,'resume',name='publisher');self.assertEqual(self.decide(resume,name='helper').status_code,200)
        self.login('helper');stale=self.client.post(f'/api/tasks/{task}/submissions',json={'summary':'旧版本提交','collaboration_version':1})
        self.assertEqual(stale.status_code,409)


if __name__=='__main__':unittest.main()
