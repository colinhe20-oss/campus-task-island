import json
import os
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import httpx

from backend.client import ChatBackend
from campus.guide import BudgetBackend, model_backend


class TimeoutTests(unittest.TestCase):
    def backend(self, handler, timeout=120):
        backend = ChatBackend(api_key='test-only', model='test', base_url='https://example.test/v1', timeout=timeout)
        backend._client.close()
        backend._client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(backend.close)
        return backend

    def test_defaults_and_env_over_file(self):
        settings = {'LLM_API_KEY': 'test-only', 'LLM_MODEL': 'test'}
        with patch.dict(os.environ, settings, clear=True), patch('campus.guide.dotenv_values', return_value={}):
            backend = model_backend()
            self.addCleanup(backend.close)
            self.assertEqual(backend.request_timeout, 120)
            self.assertEqual(backend.guide_run_timeout, 300)
        with patch.dict(os.environ, settings | {'LLM_REQUEST_TIMEOUT_SECONDS': '90', 'GUIDE_RUN_TIMEOUT_SECONDS': '240'}, clear=True), \
             patch('campus.guide.dotenv_values', return_value={'LLM_REQUEST_TIMEOUT_SECONDS': '50', 'GUIDE_RUN_TIMEOUT_SECONDS': '100'}):
            backend = model_backend()
            self.addCleanup(backend.close)
            self.assertEqual(backend.request_timeout, 90)
            self.assertEqual(backend.guide_run_timeout, 240)

    def test_file_settings_and_invalid_budgets(self):
        with patch.dict(os.environ, {'LLM_API_KEY': 'test-only', 'LLM_MODEL': 'test'}, clear=True):
            with patch('campus.guide.dotenv_values', return_value={'LLM_REQUEST_TIMEOUT_SECONDS': '75', 'GUIDE_RUN_TIMEOUT_SECONDS': '210'}):
                backend = model_backend()
                self.addCleanup(backend.close)
                self.assertEqual(backend.request_timeout, 75)
                self.assertEqual(backend.guide_run_timeout, 210)
            for key in ('LLM_REQUEST_TIMEOUT_SECONDS', 'GUIDE_RUN_TIMEOUT_SECONDS'):
                for value in ('0', '-1', 'nan', 'inf', 'invalid'):
                    with self.subTest(key=key, value=value), patch('campus.guide.dotenv_values', return_value={key: value}):
                        with self.assertRaises(ValueError):
                            model_backend()

    def test_request_timeouts_are_capped_by_remaining_budget_and_reset(self):
        observed = []
        def handler(request):
            observed.append(request.extensions['timeout'])
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]})
        backend = self.backend(handler)
        with backend.request_budget(4):
            self.assertEqual(backend.chat([])['content'], 'ok')
        backend.chat([])
        for value in observed[0].values():
            self.assertGreater(value, 0)
            self.assertLessEqual(value, 4)
        self.assertEqual(observed[1], {'connect': 10, 'read': 120, 'write': 30, 'pool': 10})

    def test_multiple_calls_share_one_run_budget(self):
        now = [0]
        remaining = []
        class Timed:
            guide_run_timeout = 300
            @contextmanager
            def request_budget(self, seconds):
                remaining.append(seconds)
                yield
            def chat(self, *args, **kwargs):
                now[0] += 70
                return {'content': 'ok'}
        with patch('campus.guide.time.monotonic', side_effect=lambda: now[0]):
            budget = BudgetBackend(Timed())
            budget.chat([])
            budget.chat([])
            self.assertEqual(remaining, [300, 230])
            now[0] = 300
            with self.assertRaises(TimeoutError):
                budget.chat([])
            self.assertEqual(len(remaining), 2)

    def test_non_streaming_trickle_cannot_commit_past_deadline(self):
        now, closed = [0], []
        class Bytes(httpx.SyncByteStream):
            def __iter__(self):
                yield b'{'
                now[0] = 301
                yield b'}'
            def close(self):
                closed.append(True)
        backend = self.backend(lambda request: httpx.Response(200, stream=Bytes()))
        with patch('backend.client.time.monotonic', side_effect=lambda: now[0]), backend.request_budget(300):
            with self.assertRaises(TimeoutError):
                backend.chat([])
        self.assertTrue(closed)

    def test_streaming_heartbeat_also_checks_deadline(self):
        now, closed = [0], []
        class Heartbeat(httpx.SyncByteStream):
            def __iter__(self):
                now[0] = 301
                yield b': heartbeat\n\n'
            def close(self):
                closed.append(True)
        backend = self.backend(lambda request: httpx.Response(200, stream=Heartbeat()))
        with patch('backend.client.time.monotonic', side_effect=lambda: now[0]), backend.request_budget(300):
            with self.assertRaises(TimeoutError):
                backend.chat_stream([], on_delta=lambda _: None, cancel_event=threading.Event())
        self.assertTrue(closed)


if __name__ == '__main__':
    unittest.main()
