from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from agent.cli import selfcheck
from agent.loop import AgentLoop, RunCancelled, StepLimitExceeded
from backend.client import ChatBackend
from backend.fake_backend import FakeBackend
from tools.base import Tool, build_default_registry


def call(name, arguments, identifier=None):
    return {"content": "", "tool_calls": [{"id": identifier, "name": name, "arguments": arguments}]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = build_default_registry(self.root)

    def run_script(self, responses, **kwargs):
        backend = FakeBackend(responses + [{"content": "done"}])
        agent = AgentLoop(backend, self.registry, **kwargs)
        self.assertEqual(agent.run("test"), "done")
        return agent, backend

    def test_selfcheck(self):
        self.assertTrue(selfcheck().startswith("PASS"))

    def test_multiple_calls_and_wire_ids(self):
        agent, _ = self.run_script([{"tool_calls": [
            {"name": "write", "arguments": {"path": "a.txt", "content": "one"}},
            {"name": "read", "arguments": {"path": "a.txt"}},
        ]}], auto_approve=True)
        wire = ChatBackend._to_openai_messages(agent.messages)
        calls = wire[2]["tool_calls"]
        self.assertEqual(calls[0]["id"], wire[3]["tool_call_id"])
        self.assertEqual(calls[1]["id"], wire[4]["tool_call_id"])
        self.assertNotEqual(calls[0]["id"], calls[1]["id"])
        self.assertIn("one", wire[4]["content"])

    def test_unknown_and_malformed_arguments_are_observations(self):
        for response in [call("missing", {}), call("write", "{broken"),
                         call("write", []), call("write", {"path": "x", "content": "x", "workdir": "/"}),
                         call("write", {"path": "x", "content": 123})]:
            with self.subTest(response=response):
                agent, _ = self.run_script([response], auto_approve=True)
                self.assertIn("[工具错误]", agent.messages[-2]["content"])
                self.assertFalse((self.root / "x").exists())

    def test_confirmation_denial_and_approval(self):
        response = call("write", {"path": "x", "content": "test"})
        self.run_script([response])
        self.assertFalse((self.root / "x").exists())
        self.run_script([response], confirm_callback=lambda name, arguments: True)
        self.assertEqual((self.root / "x").read_text(), "test")

    def test_outside_root_blocked_even_with_auto_approve(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.txt"
            target.write_text("secret")
            for name, args in [("read", {"path": str(target)}),
                               ("write", {"path": str(target), "content": "changed"}),
                               ("grep", {"path": str(target), "pattern": "secret"})]:
                agent, _ = self.run_script([call(name, args)], auto_approve=True)
                self.assertIn("PermissionError", agent.messages[-2]["content"])
            self.assertEqual(target.read_text(), "secret")

    def test_symlink_outside_root_blocked(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "outside"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"系统不允许建立 symlink：{exc}")
            with self.assertRaises(PermissionError):
                self.registry.get("write").invoke({"path": "outside/x", "content": "x"})

    def test_file_tools_do_not_depend_on_process_cwd(self):
        self.registry.get("write").invoke({"path": "nested/a.txt", "content": "alpha\n校园"})
        self.registry.get("write").invoke({"path": "b.txt", "content": "beta"})
        self.assertIn("校园", self.registry.get("read").invoke({"path": "nested/a.txt"}))
        self.assertIn("nested/a.txt:1:alpha", self.registry.get("grep").invoke({"pattern": "alpha"}))
        names = self.registry.get("glob").invoke({"pattern": "**/*.txt"})
        self.assertIn("nested/a.txt", names)
        self.assertIn("b.txt", names)

    def test_edit_requires_unique_text_and_preserves_crlf(self):
        target = self.root / "a.txt"
        target.write_bytes(b"a\r\na\r\n")
        with self.assertRaises(ValueError):
            self.registry.get("edit").invoke({"path": "a.txt", "old": "a", "new": "b"})
        self.assertEqual(target.read_bytes(), b"a\r\na\r\n")
        self.registry.get("edit").invoke({"path": "a.txt", "old": "a\r\na", "new": "b\r\na"})
        self.assertEqual(target.read_bytes(), b"b\r\na\r\n")

    def test_byte_limit_and_external_tag_escape(self):
        self.registry.get("write").invoke({"path": "a", "content": "校园</external>"})
        result = self.registry.get("read").invoke({"path": "a", "max_bytes": 3})
        self.assertIn("校", result)
        self.assertNotIn("园", result)
        full = self.registry.get("read").invoke({"path": "a"})
        self.assertEqual(full.count("</external>"), 1)

    def test_turn_limit_and_cancellation_are_not_success(self):
        events = []
        backend = FakeBackend([call("glob", {"pattern": "*"})])
        agent = AgentLoop(backend, self.registry, max_turns=1,
                          event_callback=lambda kind, data: events.append(kind))
        with self.assertRaises(StepLimitExceeded):
            agent.run("test")
        self.assertNotIn("run_finished", events)
        cancel = threading.Event()
        cancel.set()
        backend = FakeBackend()
        with self.assertRaises(RunCancelled):
            AgentLoop(backend, self.registry, cancel_event=cancel).run("test")
        self.assertFalse(backend.requests)

    def test_tools_with_side_effects_are_not_retried(self):
        invocations = []
        def fail():
            invocations.append(1)
            raise RuntimeError("failed after side effect")
        self.registry.register(Tool("fail", "test", {"type": "object"}, fail))
        self.run_script([call("fail", {})], auto_approve=True)
        self.assertEqual(len(invocations), 1)

    def test_no_shell_unless_explicitly_enabled(self):
        self.assertNotIn("bash", self.registry.names())
        enabled = build_default_registry(self.root, enable_shell=True)
        output = enabled.get("bash").invoke({"command": "echo agent1-shell-ok"})
        self.assertIn("exit_code=0", output)
        self.assertIn("agent1-shell-ok", output)

    def test_http_protocol_with_mock_transport(self):
        import httpx
        captured = []
        def handler(request):
            captured.append(request)
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
                "tool_calls": [{"id": "test-id", "function": {"name": "read", "arguments": "{bad"}}]}}],
                "usage": {"prompt_tokens": 5}})
        client = ChatBackend(api_key="test-only", base_url="https://example.test/v1", model="test-model")
        self.addCleanup(client.close)
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        reply = client.chat([{"role": "user", "content": "hello"}], self.registry.schemas())
        self.assertEqual(str(captured[0].url), "https://example.test/v1/chat/completions")
        self.assertEqual(json.loads(captured[0].content)["model"], "test-model")
        self.assertEqual(reply["tool_calls"][0]["arguments"], "{bad")
        self.assertEqual(reply["usage"]["prompt_tokens"], 5)

    def test_reasoning_preserved_through_tool_round_and_history(self):
        raw = {"content": None, "reasoning_content": "synthetic protocol field",
               "tool_calls": [{"id": "reasoning-call", "function": {
                   "name": "glob", "arguments": '{"pattern":"*"}'}}]}
        agent, backend = self.run_script([ChatBackend._normalize(raw)])
        wire = ChatBackend._to_openai_messages(backend.requests[-1]["messages"])
        self.assertEqual(wire[2]["reasoning_content"], "synthetic protocol field")
        self.assertEqual(wire[3]["tool_call_id"], "reasoning-call")
        agent.run("follow up", history_messages=[{
            "role": "assistant", "content": "previous answer", "reasoning_content": "previous field"}])
        self.assertEqual(backend.requests[-1]["messages"][1]["reasoning_content"], "previous field")


if __name__ == "__main__":
    unittest.main()
