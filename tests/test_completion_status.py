"""R6: real HTTP adapters reject incomplete output before tools or persistence."""
import json
import threading
import time
import unittest

import httpx

import test_guide as helpers
from test_stages import FIELDS
from agent.loop import AgentLoop
from backend.client import ChatBackend
from tools.base import Tool, ToolRegistry


MISSING = object()


def completion(content='完整回答', finish='stop', calls=None):
    choice = {'index': 0, 'message': {'role': 'assistant', 'content': content}}
    if finish is not MISSING:
        choice['finish_reason'] = finish
    if calls:
        choice['message']['tool_calls'] = calls
    return {'choices': [choice], 'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8}}


def tool_call(name, arguments):
    return {'id': 'test-call', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}


class HttpScripts:
    def backend(self, responses):
        replies = iter(responses)
        backend = ChatBackend(api_key='test-only', base_url='https://example.test/v1', model='test-model')
        backend._client.close()

        def respond(request):
            body = next(replies)
            if not json.loads(request.content).get('stream'):
                return httpx.Response(200, json=body)
            choice = body['choices'][0]
            delta = dict(choice['message'])
            if delta.get('tool_calls'):
                delta['tool_calls'] = [call | {'index': index} for index, call in enumerate(delta['tool_calls'])]
            chunk = {'choices': [{'index': 0, 'delta': delta}]}
            if 'finish_reason' in choice:
                chunk['choices'][0]['finish_reason'] = choice['finish_reason']
            raw = 'data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=raw.encode())

        backend._client = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(backend.close)
        return backend


class CompletionProtocolTests(HttpScripts, unittest.TestCase):
    def test_stop_preserves_answer_and_usage(self):
        reply = self.backend([completion()]).chat([])
        self.assertEqual(reply['content'], '完整回答')
        self.assertEqual(reply['usage']['total_tokens'], 8)

    def test_tool_calls_then_stop_execute_valid_tool_and_finish_normally(self):
        executed = []
        registry = ToolRegistry()
        registry.register(Tool('check', 'test', {'type': 'object'},
                               lambda: executed.append(True) or 'ok', requires_confirmation=False))
        backend = self.backend([completion('', 'tool_calls', [tool_call('check', {})]), completion()])
        self.assertEqual(AgentLoop(backend, registry).run('test'), '完整回答')
        self.assertEqual(executed, [True])

    def test_nonstream_rejects_incomplete_unknown_and_missing_finish_reasons(self):
        for finish in ('length', 'content_filter', 'unknown', None, MISSING, '', False):
            with self.subTest(finish=finish), self.assertRaises(ValueError):
                self.backend([completion('TRUNCATED_ANSWER', finish)]).chat([])

    def test_invalid_choice_or_message_is_a_controlled_protocol_failure(self):
        for body in ({}, {'choices': []}, {'choices': 'invalid'}, {'choices': [None]},
                     {'choices': [{'finish_reason': 'stop', 'message': None}]}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.backend([body]).chat([])

    def test_truncated_response_never_executes_even_valid_tool_arguments(self):
        executed = []
        registry = ToolRegistry()
        registry.register(Tool('side_effect', 'test', {'type': 'object'},
                               lambda: executed.append(True) or 'ok', requires_confirmation=False))
        backend = self.backend([completion('', 'length', [tool_call('side_effect', {})]), completion()])
        with self.assertRaises(ValueError):
            AgentLoop(backend, registry).run('test')
        self.assertEqual(executed, [])

    def test_stream_allows_intermediate_null_and_normal_terminal_reasons(self):
        for finish in ('stop', 'tool_calls'):
            with self.subTest(finish=finish):
                backend = self.backend([])
                backend._client.close()
                first = {'choices': [{'index': 0, 'delta': {'content': '前半段'}, 'finish_reason': None}]}
                last = {'choices': [{'index': 0, 'delta': {'content': '后半段'}, 'finish_reason': finish}]}
                raw = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in (first, last)) + 'data: [DONE]\n\n'
                backend._client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw.encode())))
                reply = backend.chat_stream([], on_delta=lambda _: None, cancel_event=threading.Event())
                self.assertEqual(reply['content'], '前半段后半段')

    def test_stream_rejects_abnormal_terminal_or_absent_finish(self):
        for finish in ('length', 'content_filter', 'unknown', None, MISSING, '', False):
            with self.subTest(finish=finish), self.assertRaises(ValueError):
                self.backend([completion('TRUNCATED_ANSWER', finish)]).chat_stream(
                    [], on_delta=lambda _: None, cancel_event=threading.Event())


class GuideCompletionTests(HttpScripts, unittest.TestCase):
    setUp = helpers.GuideTests.setUp
    login = helpers.GuideTests.login
    publish = helpers.GuideTests.publish

    def install(self, responses):
        self.app.state.guide_service.backend_factory = lambda: self.backend(responses)

    def snapshot(self):
        tables = ('guide_conversations', 'guide_task_drafts', 'stage_suggestions', 'tasks',
                  'task_stage_plans', 'task_stages', 'task_stage_plan_versions')
        with self.service.database.connect() as connection:
            return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in tables}

    def failed_run(self, expected_tools=0):
        summary = self.client.get('/api/guide/runs').json()['items'][0]
        run = self.client.get('/api/guide/runs/' + summary['id']).json()
        self.assertEqual(run['status'], 'failed')
        self.assertIsNone(run['result'])
        self.assertEqual(run['metrics'].get('tool_calls', 0), expected_tools)
        self.assertNotIn('TRUNCATED_ANSWER', json.dumps(run, ensure_ascii=False))
        return run

    def test_nonstream_truncation_is_not_persisted_as_success(self):
        self.login()
        before = self.snapshot()
        self.install([completion('TRUNCATED_ANSWER', 'length')])
        response = self.client.post('/api/guide/chat', json={'message': '测试截断'})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(self.snapshot(), before)
        self.failed_run()
        # A failed request releases the user slot and permits a normal retry.
        self.install([completion()])
        retry = self.client.post('/api/guide/chat', json={'message': '重新提问'})
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(self.client.get('/api/guide/runs/' + retry.json()['run_id']).json()['status'], 'succeeded')

    def test_invalid_finish_reasons_return_502_and_preserve_business_data(self):
        self.login()
        before = self.snapshot()
        for finish in ('content_filter', 'unknown', None, MISSING, ''):
            with self.subTest(finish=finish):
                self.install([completion('TRUNCATED_ANSWER', finish)])
                response = self.client.post('/api/guide/chat', json={'message': '异常结束测试'})
                self.assertEqual(response.status_code, 502, response.text)
                self.assertEqual(self.snapshot(), before)
                self.failed_run()

    def test_later_truncation_discards_staged_draft_and_keeps_existing_history(self):
        self.login()
        self.install([completion('', 'tool_calls', [tool_call('update_task_draft', {'title': '原有草稿'})]), completion()])
        first = self.client.post('/api/guide/chat', json={'message': '整理草稿'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['draft']['version'], 1)
        before = self.snapshot()
        for conversation_id in (None, first.json()['conversation_id']):
            with self.subTest(existing_conversation=bool(conversation_id)):
                self.install([completion('', 'tool_calls', [tool_call('update_task_draft', {'title': '不应保存的新草稿'})]),
                              completion('TRUNCATED_ANSWER', 'length')])
                body = {'message': '修改草稿'}
                if conversation_id:
                    body['conversation_id'] = conversation_id
                response = self.client.post('/api/guide/chat', json=body)
                self.assertEqual(response.status_code, 502, response.text)
                self.assertEqual(self.snapshot(), before)
                self.failed_run(expected_tools=1)

    def test_later_truncation_discards_stage_suggestion_and_preserves_saved_version(self):
        self.login()
        task = self.publish()
        script = lambda fields, final: [
            completion('', 'tool_calls', [tool_call('get_task_detail', {'task_id': task.id})]),
            completion('', 'tool_calls', [tool_call('propose_task_stages', {'stages': fields})]), final,
        ]
        self.install(script(FIELDS, completion()))
        body = {'purpose': 'stage_plan', 'task_id': task.id, 'message': '整理阶段建议'}
        first = self.client.post('/api/guide/chat', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertIsNotNone(first.json()['stage_suggestion'])
        before = self.snapshot()
        changed = [FIELDS[0] | {'title': '不应保存的新阶段'}, FIELDS[1]]
        for conversation_id in (None, first.json()['conversation_id']):
            with self.subTest(existing_conversation=bool(conversation_id)):
                self.install(script(changed, completion('TRUNCATED_ANSWER', 'length')))
                request = body | ({'conversation_id': conversation_id} if conversation_id else {})
                response = self.client.post('/api/guide/chat', json=request)
                self.assertEqual(response.status_code, 502, response.text)
                self.assertEqual(self.snapshot(), before)
                self.failed_run(expected_tools=2)

    def test_stream_run_truncation_discards_staged_draft_and_finishes_failed(self):
        self.login()
        before = self.snapshot()
        self.install([completion('', 'tool_calls', [tool_call('update_task_draft', {'title': '流式暂存草稿'})]),
                      completion('TRUNCATED_ANSWER', 'length')])
        response = self.client.post('/api/guide/runs', json={'message': '流式截断测试'})
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()['run_id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = self.client.get('/api/guide/runs/' + run_id).json()
            if run['status'] not in ('running', 'cancelling'):
                break
            time.sleep(.01)
        else:
            self.fail('stream run did not finish')
        self.assertEqual(run['status'], 'failed')
        self.assertIsNone(run['result'])
        self.assertEqual(run['metrics']['tool_calls'], 1)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
