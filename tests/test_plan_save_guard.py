"""A recognition mention must not change the tool required for an existing draft."""
import tempfile
import unittest
from pathlib import Path

from backend.fake_backend import FakeBackend
from campus.app import create_app
from campus.schemas import GuideInput


def call(name, fields):
    return {'content': '', 'tool_calls': [{'name': name, 'arguments': {'fields': fields}}]}


class PlanSaveGuardTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        app = create_app(Path(root) / 'test.sqlite3', enable_semantics=False)
        app.state.task_service.initialize()
        _, self.user = app.state.auth_service.register('guard.test', '测试组织者', 'test-password')
        self.guide = app.state.guide_service

    def chat(self, kind, fields, message, conversation_id=None):
        backend = FakeBackend([call('update_' + kind + '_plan', fields), {'content': '已保存草稿，请核对。'}])
        self.guide.backend_factory = lambda: backend
        reply = self.guide.chat(GuideInput(message=message, conversation_id=conversation_id), self.user)
        self.assertEqual(len(backend.requests), 2)
        return reply

    def test_volunteer_draft_with_activity_recognition_mention(self):
        initial = self.chat('volunteer', {'title': '室内资料核对'}, '先记录这些安排。')
        reply = self.chat('volunteer', {'recognition_conditions': '综素认定未知'},
                          '综素认定未知，请保存草稿。', initial.conversation_id)
        self.assertEqual(reply.assistance['plan']['kind'], 'volunteer')
        self.assertEqual(reply.assistance['plan']['fields']['recognition_conditions'], '综素认定未知')

    def test_activity_draft_with_volunteer_hours_mention(self):
        initial = self.chat('activity', {'title': '校园艺术体验'}, '先记录这些安排。')
        reply = self.chat('activity', {'recognition_description': '不提供志愿时长'},
                          '不提供志愿时长，请保存草稿。', initial.conversation_id)
        self.assertEqual(reply.assistance['plan']['kind'], 'activity')
        self.assertEqual(reply.assistance['plan']['fields']['recognition_description'], '不提供志愿时长')

    def test_new_volunteer_draft(self):
        reply = self.chat('volunteer', {'title': '志愿活动'}, '整理成志愿活动草稿。')
        self.assertEqual(reply.assistance['plan']['kind'], 'volunteer')

    def test_new_activity_draft(self):
        reply = self.chat('activity', {'title': '综素活动'}, '整理成综素活动草稿。')
        self.assertEqual(reply.assistance['plan']['kind'], 'activity')
