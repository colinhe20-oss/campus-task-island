import json,tempfile,unittest,threading,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from campus.app import create_app
from campus.schemas import TASK_CREATE_EXAMPLE,DeadlineInput,ExtensionReviewInput,SettlementInput,StagePlanInput
from campus.errors import AppError
from campus.todos import personal_state
from campus.drafts import DraftBuffer,read_draft
from tools.campus import build_campus_registry

class TermsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=datetime(2030,1,1,tzinfo=timezone.utc)
        self.app=create_app(Path(self.temp.name)/'campus.sqlite3',task_clock=lambda:self.now)
        self.client=self.enterContext(TestClient(self.app));self.service=self.app.state.task_service
        self.accounts=json.loads(self.app.state.auth_service.accounts_path.read_text('utf-8'))
        self.users={}
        for name in ('publisher','helper','observer'):self.users[name]=self.login(name)
        self.login('publisher')

    def login(self,name):
        response=self.client.post('/api/auth/login',json={'username':name,'password':self.accounts[name]['password']});self.assertEqual(response.status_code,200)
        return response.json()['id']

    def stamp(self,h):return (datetime(2030,1,1,tzinfo=timezone.utc)+timedelta(hours=h)).isoformat()

    def create(self,mode='approval',paid=False,**changes):
        self.login('publisher');payload={**TASK_CREATE_EXAMPLE,'acceptance_mode':mode,'deadline':self.stamp(1),'reward_type':'paid' if paid else 'mutual'}
        if paid:payload.update(reward_amount_fen=1050,reward='完整交付后线下支付10.50元')
        payload.update(changes);response=self.client.post('/api/tasks',json=payload);self.assertEqual(response.status_code,201,response.text);return response.json()['id']

    def join(self,task,mode='approval'):
        self.login('helper')
        if mode=='direct':self.assertEqual(self.client.post(f'/api/tasks/{task}/claim',json={'confirmed':True,'reason':'可以参与'}).status_code,200)
        else:
            row=self.client.post(f'/api/tasks/{task}/applications',json={'reason':'可以参与'}).json();self.login('publisher')
            self.assertEqual(self.client.post('/api/applications/'+row['id']+'/accept').status_code,200)

    def finish(self,task):
        self.login('helper');self.assertEqual(self.client.post(f'/api/tasks/{task}/submissions',json={'summary':'完成'}).status_code,201)
        self.login('publisher');self.assertEqual(self.client.post(f'/api/tasks/{task}/review',json={'decision':'accept'}).status_code,200)

    def propose(self,task,h=3):
        response=self.client.post(f'/api/tasks/{task}/extensions',json={'version':self.service.get_task(task).terms_version,'deadline':self.stamp(h),'reason':'需要更多时间'})
        self.assertEqual(response.status_code,200,response.text);return response.json()['items'][0]

    def count(self,table):
        with self.service.database.connect() as c:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_new_deadline_future_timezone(self):
        for deadline in (self.stamp(-1),self.stamp(0),'2030-01-01T01:00:00'):
            response=self.client.post('/api/tasks',json={**TASK_CREATE_EXAMPLE,'deadline':deadline});self.assertEqual(response.status_code,422)
        self.assertEqual(self.count('tasks'),0)
        task=self.create();self.assertEqual(self.client.get('/api/tasks/'+task).json()['deadline'],self.stamp(1).replace('+00:00','Z'))

    def test_new_reward_validation(self):
        for update in ({'reward_type':None},{'reward_type':'legacy'},{'reward_type':'paid'},{'reward_type':'paid','reward_amount_fen':1.2},{'reward_type':'paid','reward_amount_fen':True},{'reward_type':'paid','reward_amount_fen':0},{'reward_type':'paid','reward_amount_fen':-1},{'reward_type':'paid','reward_amount_fen':10,'reward':'  '},{'reward_type':'mutual','reward_amount_fen':1}):
            response=self.client.post('/api/tasks',json={**TASK_CREATE_EXAMPLE,'deadline':self.stamp(1),**update});self.assertEqual(response.status_code,422,str(update))
        body={**TASK_CREATE_EXAMPLE,'deadline':self.stamp(1)};body.pop('reward_type');self.assertEqual(self.client.post('/api/tasks',json=body).status_code,422)
        task=self.create(paid=True);self.assertEqual(self.service.get_task(task).reward_amount_fen,1050)

    def test_expiry_blocks_new_and_accept_preserves_history(self):
        task=self.create();self.login('helper');application=self.client.post(f'/api/tasks/{task}/applications',json={'reason':'申请'}).json()
        self.now+=timedelta(hours=1)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/applications',json={'reason':'重试'}).json(),application)
        self.login('observer');self.assertEqual(self.client.post(f'/api/tasks/{task}/applications',json={'reason':'申请'}).status_code,409)
        self.login('publisher');self.assertEqual(self.client.post('/api/applications/'+application['id']+'/accept').status_code,409)
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
        self.assertEqual(self.client.get('/api/tasks?expired_only=true').json()['items'][0]['id'],task)
        current=self.service.get_task(task);self.assertTrue(current.is_expired);self.assertFalse(current.can_apply)
        self.assertEqual(self.client.get('/api/me/home').json()['todos'][0]['action'],'extend_deadline')
        response=self.client.post(f'/api/tasks/{task}/deadline',json={'version':1,'deadline':self.stamp(2),'reason':'重新开放'})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['terms_version'],2)
        self.assertEqual(self.count('applications'),1)
        self.assertEqual(self.client.post('/api/applications/'+application['id']+'/accept').status_code,200)

    def test_direct_expiry_and_successful_retry(self):
        task=self.create('direct');self.now+=timedelta(hours=1);self.login('helper')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/claim',json={'confirmed':True,'reason':'申请'}).status_code,409)
        self.assertEqual(self.count('applications'),0)
        self.now-=timedelta(seconds=1);self.join(task,'direct');self.now+=timedelta(seconds=2)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/claim',json={'confirmed':True}).status_code,200)
        self.assertTrue(self.service.get_task(task).is_overdue)

    def test_extend_permissions_versions_and_downlisted(self):
        task=self.create();body={'version':1,'deadline':self.stamp(2),'reason':'延期'}
        self.login('helper');self.assertEqual(self.client.post(f'/api/tasks/{task}/deadline',json=body).status_code,403)
        self.login('publisher');self.assertEqual(self.client.post(f'/api/tasks/{task}/deadline',json={**body,'deadline':self.stamp(1)}).status_code,422)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/deadline',json=body).status_code,200)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/deadline',json=body).status_code,409)
        self.client.post(f'/api/tasks/{task}/withdraw');self.assertEqual(self.client.post(f'/api/tasks/{task}/deadline',json={**body,'version':2}).status_code,409)

    def test_overdue_submit_review_and_extension_approval(self):
        task=self.create();self.join(task);self.login('helper');self.now+=timedelta(hours=2)
        row=self.propose(task)
        self.assertTrue(self.service.get_task(task).is_overdue)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'approve'}).status_code,403)
        self.login('publisher');actions={x['action'] for x in self.client.get('/api/me/home').json()['todos']}
        self.assertIn('review_change',actions)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'approve'}).status_code,200)
        self.assertFalse(self.service.get_task(task).is_overdue);self.assertEqual(self.service.get_task(task).terms_version,2)
        self.now+=timedelta(hours=2);self.finish(task);self.assertEqual(self.service.get_task(task).status,'completed')

    def test_extension_cancel_reject_repropose(self):
        task=self.create();self.join(task);self.login('helper');row=self.propose(task)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/extensions',json={'version':1,'deadline':self.stamp(3),'reason':'重复'}).status_code,409)
        self.login('publisher');self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/cancel',json={'version':1}).status_code,403)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'reject'}).status_code,422)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'reject','reason':'时间不合适'}).status_code,200)
        row2=self.propose(task);self.assertEqual(self.client.post('/api/task-extensions/'+row2['id']+'/cancel',json={'version':1}).status_code,200)
        self.assertEqual(len(self.client.get(f'/api/tasks/{task}/extensions').json()['items']),2)

    def test_extension_decision_expired_or_stale(self):
        task=self.create();self.join(task);self.login('helper');row=self.propose(task,h=2)
        self.login('publisher');self.now+=timedelta(hours=2)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'approve'}).status_code,422)
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':9,'decision':'reject','reason':'过期'}).status_code,409)

    def test_completion_closes_pending_extension(self):
        task=self.create();self.join(task);self.login('helper');row=self.propose(task);self.finish(task)
        state=self.client.get(f'/api/tasks/{task}/extensions').json();self.assertEqual(state['items'][0]['status'],'closed')
        self.assertEqual(self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'approve'}).status_code,409)

    def test_stage_deadlines_unchanged_and_final_settlement(self):
        task=self.create(paid=True)
        body={'expected_version':0,'stages':[dict(title='交付',completion_criteria='完成',deadline=self.stamp(1),responsible_role='assignee')]}
        self.client.post(f'/api/tasks/{task}/stages',json=body);self.join(task);self.login('helper');row=self.propose(task)
        self.login('publisher');self.client.post('/api/task-extensions/'+row['id']+'/review',json={'version':1,'decision':'approve'})
        self.now+=timedelta(hours=2);stages=self.client.get(f'/api/tasks/{task}/stages').json();stage=stages['stages'][0]
        self.assertTrue(stage['is_overdue']);self.assertFalse(self.service.get_task(task).is_overdue)
        self.login('helper');self.client.post(f'/api/tasks/{task}/stages/{stage["id"]}/start',json={'version':1})
        self.client.post(f'/api/tasks/{task}/stages/{stage["id"]}/submissions',json={'version':2,'summary':'完成'})
        self.login('publisher');self.assertEqual(self.client.post(f'/api/tasks/{task}/stages/{stage["id"]}/review',json={'version':3,'decision':'accept'}).status_code,200)
        self.assertTrue(self.client.get(f'/api/tasks/{task}/settlement').json()['available'])
        self.assertIn('confirm_settlement',[x.action for x in personal_state(self.service,self.users['publisher']).todos])

    def test_settlement_independent_confirmation_revoke_and_counts(self):
        task=self.create(paid=True);self.join(task);self.finish(task)
        route=f'/api/tasks/{task}/settlement';self.login('helper')
        self.assertEqual(self.client.post(route+'/confirmation',json={'version':0,'confirmed':True}).status_code,200)
        current=self.client.get(route).json();self.assertFalse(current['payer_confirmed']);self.assertTrue(current['payee_confirmed']);self.assertFalse(current['both_confirmed'])
        count=self.count('notifications');self.assertEqual(self.client.post(route+'/confirmation',json={'version':0,'confirmed':True}).status_code,200);self.assertEqual(self.count('notifications'),count)
        self.assertEqual(personal_state(self.service,self.users['helper']).completed_count,1)
        self.assertNotIn('confirm_settlement',[x.action for x in personal_state(self.service,self.users['helper']).todos])
        self.login('publisher');self.assertEqual(self.client.post(route+'/confirmation',json={'version':0,'confirmed':True}).status_code,409)
        self.assertTrue(self.client.post(route+'/confirmation',json={'version':1,'confirmed':True}).json()['both_confirmed'])
        self.assertEqual(self.client.post(route+'/confirmation',json={'version':2,'confirmed':False}).status_code,422)
        result=self.client.post(route+'/confirmation',json={'version':2,'confirmed':False,'reason':'误点，尚未支付'}).json()
        self.assertFalse(result['both_confirmed']);self.assertEqual(len(result['history']),3)
        self.assertTrue(self.client.post(route+'/confirmation',json={'version':3,'confirmed':True}).json()['both_confirmed'])
        self.assertEqual(self.count('task_settlement_history'),4)

    def test_settlement_before_complete_and_private(self):
        task=self.create(paid=True);self.join(task)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/settlement/confirmation',json={'version':0,'confirmed':True}).status_code,409)
        self.login('observer')
        for path in ('settlement','extensions'):
            self.assertEqual(self.client.get(f'/api/tasks/{task}/{path}').status_code,403)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/settlement/confirmation',json={'version':0,'confirmed':True}).status_code,403)
        self.client.post('/api/auth/logout');self.assertEqual(self.client.get(f'/api/tasks/{task}/settlement').status_code,401)

    def test_legacy_reward_no_inference(self):
        task=self.create()
        with self.service.database.connect() as c:c.execute("UPDATE tasks SET reward_type='legacy',reward='报酬约100元' WHERE id=?",(task,))
        value=self.client.get('/api/tasks/'+task).json();self.assertEqual(value['reward_type'],'legacy');self.assertIsNone(value['reward_amount_fen'])
        self.assertEqual(self.client.get(f'/api/tasks/{task}/settlement').status_code,409)

    def test_pending_extension_and_settlement_roll_back_messages(self):
        task=self.create();self.join(task)
        with patch('campus.changes.emit',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):self.service.terms.propose(task,self.users['helper'],DeadlineInput(version=1,deadline=self.stamp(3),reason='延期'))
        self.assertEqual(self.count('task_changes'),0)
        task=self.create(paid=True);self.join(task);self.finish(task)
        with patch('campus.terms.emit',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):self.service.terms.confirm(task,self.users['publisher'],SettlementInput(version=0,confirmed=True))
        self.assertEqual(self.count('task_settlement_history'),0)
        self.assertEqual(self.count('task_settlements'),0)

    def test_concurrent_extensions_and_decisions(self):
        task=self.create();self.join(task)
        def propose(uid):
            try:self.service.terms.propose(task,uid,DeadlineInput(version=1,deadline=self.stamp(3),reason='延期'));return True
            except AppError:return False
        with ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(propose,[self.users['helper'],self.users['publisher']]))
        self.assertEqual(sum(outcomes),1)
        with self.service.database.connect() as c:row=dict(c.execute('SELECT * FROM task_changes').fetchone())
        other=self.users['publisher'] if row['requester_id']==self.users['helper'] else self.users['helper']
        def review(_):
            try:self.service.terms.decide(row['id'],other,ExtensionReviewInput(version=1,decision='approve'));return True
            except AppError:return False
        with ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(review,range(2)))
        self.assertEqual(sum(outcomes),1);self.assertEqual(self.service.get_task(task).terms_version,2)

    def test_simultaneous_settlement_confirmations_version_conflict(self):
        task=self.create(paid=True);self.join(task);self.finish(task)
        def confirm(uid):
            try:self.service.terms.confirm(task,uid,SettlementInput(version=0,confirmed=True));return True
            except AppError:return False
        with ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(confirm,[self.users['publisher'],self.users['helper']]))
        self.assertEqual(sum(outcomes),1);self.assertEqual(self.count('task_settlement_history'),1)

    def test_listing_filter_pagination_and_readonly(self):
        expired=self.create();active=self.create(deadline=self.stamp(3));self.now+=timedelta(hours=1)
        counts={t:self.count(t) for t in ('notifications','task_changes','task_deadline_history')}
        data=self.client.get('/api/tasks?limit=1').json();self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['id'],active)
        self.assertEqual(self.client.get('/api/tasks?expired_only=true&limit=1').json()['items'][0]['id'],expired)
        self.client.get('/api/me/home');self.client.get(f'/api/tasks/{expired}/extensions')
        self.assertEqual(counts,{t:self.count(t) for t in counts})

    def test_agent_reads_real_terms_and_private_settlement(self):
        task=self.create(paid=True);self.join(task);self.login('helper');row=self.propose(task)
        registry=build_campus_registry(self.service,self.users['publisher'])
        data=json.loads(registry.get('get_task_detail').invoke({'task_id':task}))
        self.assertEqual(data['reward_amount_fen'],1050);self.assertEqual(data['extensions'][0]['id'],row['id']);self.assertFalse(data['settlement']['available'])
        data=json.loads(build_campus_registry(self.service,self.users['observer']).get('get_task_detail').invoke({'task_id':task}))
        self.assertNotIn('extensions',data);self.assertNotIn('settlement',data)

    def test_waiting_write_lock_rechecks_cutoff(self):
        task=self.create('direct');uid=self.users['helper'];started=threading.Event()
        def claim():
            started.set()
            try:self.service.claim(task,uid,confirmed=True,reason='参与');return True
            except AppError:return False
        with ThreadPoolExecutor(1) as pool:
            with self.service.database.connect() as c:
                c.execute('BEGIN IMMEDIATE');future=pool.submit(claim);started.wait(1)
                self.now+=timedelta(hours=1)
            self.assertFalse(future.result(timeout=5))
        self.assertEqual(self.count('applications'),0)

    def test_completion_and_extension_approval_race(self):
        task=self.create();self.join(task);self.login('helper');row=self.propose(task)
        self.service.submit(task,self.users['helper'],'已完成')
        def run(action):
            try:
                if action=='complete':self.service.review(task,self.users['publisher'],'accept','')
                else:self.service.terms.decide(row['id'],self.users['publisher'],ExtensionReviewInput(version=1,decision='approve'))
                return True
            except AppError:return False
        with ThreadPoolExecutor(2) as pool:list(pool.map(run,['complete','approve']))
        self.assertEqual(self.service.get_task(task).status,'completed')
        with self.service.database.connect() as c:state=c.execute('SELECT status FROM task_changes WHERE id=?',(row['id'],)).fetchone()[0]
        self.assertIn(state,['approved','closed'])

    def test_reward_cannot_change_through_deadline_endpoint(self):
        task=self.create(paid=True)
        response=self.client.post(f'/api/tasks/{task}/deadline',json={'version':1,'deadline':self.stamp(3),'reason':'延期','reward_amount_fen':1})
        self.assertEqual(response.status_code,422);self.assertEqual(self.service.get_task(task).reward_amount_fen,1050)

    def test_tool_exact_integer_numeric_normalization(self):
        from tools.base import ToolRegistry
        from tools.drafts import register_draft_tools
        registry=ToolRegistry();buffer=DraftBuffer('d'*32,None,lambda:self.now)
        register_draft_tools(registry,buffer);tool=registry.get('update_task_draft')
        tool.invoke({'reward_type':'paid','reward_amount_fen':2550.0,'reward':'线下支付全额'})
        self.assertEqual(buffer.fields.reward_amount_fen,2550)
        tool.invoke({'reward_amount_fen':'2550'})
        self.assertEqual(buffer.fields.reward_amount_fen,2550)
        for invalid in (25.5,'25.50',True,'-1','9007199254740992'):
            with self.assertRaises(Exception):tool.invoke({'reward_amount_fen':invalid})

    def test_expired_draft_and_missing_reward(self):
        fields={**TASK_CREATE_EXAMPLE,'deadline':self.stamp(0)}
        row=dict(conversation_id='a'*32,version=1,status='draft',fields=json.dumps(fields),published_task_id=None)
        draft=read_draft(row,self.now);self.assertFalse(draft.ready);self.assertIn('deadline',draft.missing_fields)
        with self.service.database.connect() as c:
            c.execute('INSERT INTO guide_conversations(id,user_id,history,updated_at) VALUES (?,?,?,?)',('a'*32,self.users['publisher'],'[]',self.now.isoformat()))
            c.execute('INSERT INTO guide_task_drafts(conversation_id,user_id,fields,version,status,updated_at) VALUES (?,?,?,?,?,?)',('a'*32,self.users['publisher'],row['fields'],1,'draft',self.now.isoformat()))
        response=self.client.post('/api/guide/drafts/'+('a'*32)+'/publish',json={'version':1})
        self.assertEqual(response.status_code,409);self.assertIn('过期',response.json()['detail']);self.assertEqual(self.count('tasks'),0)
        fields['deadline']=self.stamp(3);fields.pop('reward_type');row['fields']=json.dumps(fields)
        draft=read_draft(row,self.now);self.assertFalse(draft.ready);self.assertIn('reward_type',draft.missing_fields)
        buffer=DraftBuffer('b'*32,None,lambda:self.now);buffer.update({**fields,'reward_type':'paid','reward':None});self.assertIn('reward_amount_fen',buffer.read().missing_fields);self.assertIn('reward',buffer.read().missing_fields)
