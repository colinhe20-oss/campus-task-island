import json
import threading
import time
import unittest
from pathlib import Path

import httpx

import test_guide as helpers
from backend.client import ChatBackend
from backend.fake_backend import FakeBackend
from app_factory import create_app
from fastapi.testclient import TestClient


class RunTests(unittest.TestCase):
    setUp = helpers.GuideTests.setUp
    login = helpers.GuideTests.login

    def wait(self, run_id):
        for _ in range(250):
            item = self.client.get('/api/guide/runs/'+run_id).json()
            if item['status'] not in ('running','cancelling'):
                return item
            time.sleep(.01)
        self.fail('run did not terminate')

    def start(self):
        response = self.client.post('/api/guide/runs',json={'message':'我的待办'})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['run_id']

    def test_metrics_persistence_and_user_isolation(self):
        self.login()
        self.app.state.guide_service.backend_factory = lambda: FakeBackend([
            helpers.calling()|{'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}},
            {'content':'当前待办','reasoning_content':'secret-thought',
             'usage':{'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}}])
        run_id = self.start()
        run = self.wait(run_id)
        self.assertEqual(run['status'],'succeeded')
        self.assertEqual(run['result']['run_id'],run_id)
        self.assertEqual(run['metrics']['total_tokens'],38)
        self.assertTrue(run['metrics']['usage_complete'])
        self.assertEqual(run['metrics']['model_calls'],2)
        self.assertEqual(run['metrics']['tool_calls'],1)
        self.assertNotIn('secret-thought',json.dumps(run))
        self.assertNotIn('arguments',json.dumps(run))
        with TestClient(create_app(Path(self.temp)/'tasks.sqlite3',guide_backend_factory=FakeBackend)) as other:
            other.cookies.set('campus_session',self.users['publisher'][0])
            self.assertEqual(other.get('/api/guide/runs/'+run_id).json()['metrics']['total_tokens'],38)
        self.login('helper')
        self.assertEqual(self.client.get('/api/guide/runs/'+run_id).status_code,404)
        self.assertEqual(self.client.post('/api/guide/runs/'+run_id+'/cancel').status_code,404)
        self.assertEqual(self.client.get('/api/guide/runs/'+run_id+'/events').status_code,404)
        self.assertEqual(self.client.get('/api/guide/runs').json()['items'],[])

    def test_cancel_after_staged_tool_rolls_back_and_keeps_slot_until_worker_ends(self):
        self.login()
        entered, release = threading.Event(), threading.Event()
        class Slow(FakeBackend):
            def chat(inner,*args,**kwargs):
                if inner.requests:
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError()
                return super().chat(*args,**kwargs)
        self.app.state.guide_service.backend_factory = lambda:Slow([
            helpers.calling('update_task_draft',{'title':'不应保存'}),{'content':'完成'}])
        run_id = self.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.client.post('/api/guide/runs/'+run_id+'/cancel').json()['status'],'cancelling')
            self.assertEqual(self.client.post('/api/guide/runs',json={'message':'重试'}).status_code,409)
        finally:
            release.set()
        run = self.wait(run_id)
        self.assertEqual(run['status'],'cancelled')
        self.assertIsNone(run['result'])
        with self.service.database.connect() as conn:
            for table in ('guide_conversations','guide_task_drafts','tasks'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.app.state.guide_service.backend_factory = lambda:FakeBackend([{'content':'新回答'}])
        self.assertEqual(self.wait(self.start())['status'],'succeeded')

    def test_failed_run_no_raw_errors_unknown_usage_and_sse_resume(self):
        self.login()
        class Broken:
            def chat(self,*args,**kwargs):raise httpx.ConnectError('sk-secret-password')
        self.app.state.guide_service.backend_factory=Broken
        failed=self.wait(self.start())
        self.assertEqual(failed['status'],'failed')
        self.assertFalse(failed['metrics']['usage_complete'])
        self.assertNotIn('sk-secret',json.dumps(failed))
        self.app.state.guide_service.backend_factory=lambda:FakeBackend([helpers.calling(),{'content':'完成'}])
        run_id=self.start()
        result=self.wait(run_id)
        response=self.client.get('/api/guide/runs/'+run_id+'/events',headers={'Last-Event-ID':'2'})
        self.assertEqual(response.status_code,200)
        self.assertIn('event: terminal',response.text)
        self.assertNotIn('id: 1\n',response.text)
        self.assertIn('id: 3\n',response.text)
        self.assertEqual(self.client.get('/api/guide/runs/'+run_id+'/events',headers={'Last-Event-ID':'bad'}).status_code,400)
        self.assertEqual(self.client.post('/api/guide/runs/'+run_id+'/cancel').json()['status'],'succeeded')
        self.assertEqual(result['result']['answer'],'完成')

    def test_sync_and_action_routes_are_logged_and_restart_marks_interrupted(self):
        self.login()
        reply=self.client.post('/api/guide/chat',json={'message':'你好'}).json()
        self.assertEqual(self.client.get('/api/guide/runs/'+reply['run_id']).json()['status'],'succeeded')
        self.client.post('/api/guide/drafts/'+reply['conversation_id']+'/publish',json={'version':1})
        self.assertEqual(self.client.get('/api/guide/runs').json()['items'][0]['status'],'failed')
        control=self.app.state.guide_service.runs.create(self.users['publisher'][1].id,None)
        self.app.state.guide_service.runs.recover()
        self.assertEqual(self.client.get('/api/guide/runs/'+control.id).json()['status'],'interrupted')


class StreamProtocolTests(unittest.TestCase):
    def backend(self,chunks,done=True):
        raw=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+('data: [DONE]\n\n' if done else '')
        backend=ChatBackend(api_key='test-only',base_url='https://example.test/v1',model='test')
        backend._client.close()
        def handler(request):
            body=json.loads(request.content)
            self.assertTrue(body['stream_options']['include_usage'])
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=raw.encode())
        backend._client=httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(backend.close)
        return backend

    def test_interleaved_fragmented_calls_text_usage_and_private_reasoning(self):
        chunks=[{'choices':[{'delta':{'reasoning_content':'private','content':'你',
            'tool_calls':[{'index':1,'id':'b','function':{'name':'get_', 'arguments':'{'}},
                          {'index':0,'id':'a','function':{'name':'search_', 'arguments':'{"keyword":'}}]}}]},
            {'choices':[{'delta':{'content':'好','tool_calls':[
                {'index':0,'function':{'name':'tasks','arguments':'"摄影"}'}},
                {'index':1,'function':{'name':'my_tasks','arguments':'}'}}]},'finish_reason':'tool_calls'}]},
            {'choices':[],'usage':{'total_tokens':12,'prompt_tokens':10,'completion_tokens':2}}]
        deltas=[]
        result=self.backend(chunks).chat_stream([],on_delta=lambda text:deltas.append(text) if text else None,cancel_event=threading.Event())
        self.assertEqual(deltas,['你','好'])
        self.assertEqual(result['tool_calls'],[{'id':'a','name':'search_tasks','arguments':'{"keyword":"摄影"}'},
                                               {'id':'b','name':'get_my_tasks','arguments':'{}'}])
        self.assertEqual(result['usage']['total_tokens'],12)
        self.assertEqual(result['reasoning_content'],'private')

    def test_partial_or_length_limited_stream_is_not_success(self):
        for finish in (None,'length'):
            with self.subTest(finish=finish):
                backend=self.backend([{'choices':[{'delta':{'content':'半段'},'finish_reason':finish}]}])
                with self.assertRaises(ValueError):
                    backend.chat_stream([],on_delta=lambda _:None,cancel_event=threading.Event())

    def test_cancellation_closes_stream_before_tools(self):
        from agent.loop import RunCancelled
        cancel=threading.Event()
        backend=self.backend([{'choices':[{'delta':{'content':'第一个片段'}}]},
                              {'choices':[{'delta':{'content':'第二个片段'},'finish_reason':'stop'}]}])
        with self.assertRaises(RunCancelled):
            backend.chat_stream([],on_delta=lambda _:cancel.set(),cancel_event=cancel)
