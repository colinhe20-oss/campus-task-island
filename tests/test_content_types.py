"""普通任务工具与综素活动数据保持隔离。"""
import json
import unittest
from datetime import datetime, timedelta, timezone

import test_guide as helpers
from campus.activity_schemas import ActivityCreate
from tools.campus import build_campus_registry


class ContentTypeTests(unittest.TestCase):
    setUp = helpers.GuideTests.setUp
    login = helpers.GuideTests.login
    publish = helpers.GuideTests.publish

    def test_ordinary_queries_never_return_activity_records(self):
        ordinary = self.publish(title='校园摄影协作')
        now = datetime.now(timezone.utc)
        activity = self.app.state.activity_service.create(ActivityCreate(
            title='校园摄影美育活动', description='摄影活动报名', location='活动中心',
            starts_at=now+timedelta(hours=3), ends_at=now+timedelta(hours=4),
            opens_at=now-timedelta(hours=1), closes_at=now+timedelta(hours=2),
            capacity=10, registration_mode='direct', recognition_tags=['aesthetic'],
            recognition_description='由活动方公布，以正式认定为准', organization_name='测试社团',
            information_source='测试公告', contact='站内联系', participation_requirements='本校学生'), self.users['publisher'][1].id)
        registry = build_campus_registry(self.service, self.users['publisher'][1].id)
        result = json.loads(registry.get('search_tasks').invoke({'keyword': '摄影'}))
        self.assertEqual([item['id'] for item in result['items']], [ordinary.id])
        self.assertNotIn(activity['id'], json.dumps(result))
        self.login()
        reply = self.client.post('/api/guide/chat', json={'message':'我的待办'}).json()
        self.assertNotIn(activity['id'], json.dumps(reply['references']))

    def test_model_receives_content_type_policy_and_no_activity_write_tools(self):
        self.login()
        response = self.client.post('/api/guide/chat', json={'message':'我想发布综素活动'})
        self.assertEqual(response.status_code, 200)
        request = self.backends[-1].requests[0]
        prompt = request['messages'][0]['content']
        # 验证编排确实将区别与能力边界传给模型，而非仅存在于未使用的常量。
        for rule in ('校园发现','/#/discoveries','/#/mine/discoveries','不宣称已经核实设施或安全情况','志愿服务','search_volunteer_jobs','get_my_volunteer_records','/#/mine/volunteer-records','综素活动', '二课分、美育分、形策二分', '只查询普通任务', 'search_activities','综素活动发布暂不支持 AI 草稿', '先询问', '/#/tasks/new'):
            self.assertIn(rule, prompt)
        names = {tool['function']['name'] for tool in request['tools']}
        self.assertEqual(names, {'search_tasks','get_my_tasks','get_task_detail','get_task_draft','update_task_draft',
            'search_activities','get_activity_detail','get_my_activity_registrations','search_volunteer_jobs',
            'get_volunteer_detail','get_my_volunteer_registrations','get_my_volunteer_records',
            'search_discoveries','get_discovery_detail','get_my_overview'})
        self.assertIsNone(response.json()['draft'])
        with self.service.database.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM activities').fetchone()[0], 0)
