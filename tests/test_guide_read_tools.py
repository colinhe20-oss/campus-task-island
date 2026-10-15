import json
import unittest
from datetime import datetime, timedelta, timezone

import test_guide as helpers
from campus.activity_schemas import ActivityCreate
from campus.discovery_schemas import DiscoveryCreate
from campus.volunteer_schemas import VolunteerCreate
from tools.campus import build_campus_registry


class GuideReadToolsTests(unittest.TestCase):
    setUpBase = helpers.GuideTests.setUp
    login = helpers.GuideTests.login

    def setUp(self):
        self.setUpBase()
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.owner = self.users['publisher'][1].id
        self.helper = self.users['helper'][1].id
        self.observer = self.users['observer'][1].id
        self.activity = self.app.state.activity_service
        self.volunteer = self.app.state.volunteer_service
        self.discovery = self.app.state.discovery_service
        self.activity.clock = self.volunteer.clock = self.discovery.clock = lambda: self.now

    def registry(self, user=None):
        return build_campus_registry(self.service, user or self.helper, activities=self.activity,
            volunteers=self.volunteer, discoveries=self.discovery, home=self.app.state.home_service)

    def activity_payload(self, **overrides):
        stamp = lambda hours: (self.now + timedelta(hours=hours)).isoformat()
        return dict(title='美育讲座', description='活动说明', location='活动中心', opens_at=stamp(-1),
            closes_at=stamp(1), starts_at=stamp(2), ends_at=stamp(3), capacity=1,
            registration_mode='direct', recognition_tags=['aesthetic'], recognition_description='活动方说明',
            organization_name='测试组织', information_source='公告', contact='站内联系', participation_requirements='在校生') | overrides

    def test_registry_has_only_read_tools_and_person_identity_is_bound(self):
        registry = self.registry()
        names = {item['function']['name'] for item in registry.schemas()}
        self.assertTrue({'search_activities', 'get_activity_detail', 'search_volunteer_jobs',
            'get_volunteer_detail', 'get_my_volunteer_registrations', 'get_my_volunteer_records',
            'search_discoveries', 'get_discovery_detail', 'get_my_overview'} <= names)
        for name in ('get_my_overview', 'get_my_volunteer_records', 'get_my_activity_registrations'):
            with self.subTest(name=name), self.assertRaises(Exception):
                registry.get(name).invoke({'user_id': self.owner})
        anonymous = build_campus_registry(self.service)
        self.assertNotIn('get_my_overview', {item['function']['name'] for item in anonymous.schemas()})

    def test_activity_waitlist_query_returns_live_capacity_time_and_link(self):
        activity = self.activity.create(ActivityCreate.model_validate(self.activity_payload()), self.owner)
        self.activity.register(activity['id'], self.observer)
        self.activity.register(activity['id'], self.helper)
        data = json.loads(self.registry().get('get_activity_detail').invoke({'activity_id': activity['id']}))
        self.assertEqual(data['my_registration']['status'], 'waitlisted')
        self.assertEqual(data['my_registration']['waitlist_position'], 1)
        self.assertEqual(data['remaining_capacity'], 0)
        self.assertEqual(data['server_time'], self.now.isoformat())
        self.assertEqual(data['href'], '#/activities/' + activity['id'])

    def test_volunteer_hours_are_distinct_from_school_recognition(self):
        stamp = lambda hours: (self.now + timedelta(hours=hours)).isoformat()
        payload = dict(title='志愿服务', description='服务说明', organization_name='测试组织',
            information_source='公告', contact='站内联系', recognition_conditions='按实际服务确认',
            starts_at=stamp(2), ends_at=stamp(4), opens_at=stamp(-1), closes_at=stamp(1),
            registration_mode='direct', jobs=[dict(name='引导岗', description='现场引导', requirements='准时',
                location='活动中心', starts_at=stamp(2), ends_at=stamp(4), capacity=1,
                estimated_minutes=120, estimated_hours_description='按实际参与确认')])
        activity = self.volunteer.create(VolunteerCreate.model_validate(payload), self.owner)
        self.assertEqual(self.volunteer.search('现场引导')['total'], 1)
        registration = self.volunteer.register(activity['jobs'][0]['id'], self.helper, '参加')
        self.now = datetime.fromisoformat(activity['jobs'][0]['ends_at'])
        from campus.volunteer_schemas import ParticipationInput, HoursInput
        self.volunteer.update_record(registration['id'], self.owner,
            ParticipationInput(version=0, attendance='participated', actual_minutes=90, description='完成服务'))
        self.volunteer.update_record(registration['id'], self.owner,
            HoursInput(version=1, confirmed_minutes=75, reason='核验实际时长'))
        data = json.loads(self.registry().get('get_my_volunteer_records').invoke({}))
        self.assertEqual(data['confirmed_minutes'], 75)
        self.assertEqual(data['official_status'], 'not_connected')
        self.assertEqual(data['items'][0]['confirmed_minutes'], 75)

    def test_discovery_reports_self_report_and_respects_withdrawn_visibility(self):
        discovery = self.discovery.create(DiscoveryCreate.model_validate(dict(title='路灯故障',
            description='东门路灯不亮', location='东门', discovered_at=self.now.isoformat(),
            information_source='本人观察', image_ids=[], category='facility')), self.owner)
        self.discovery.state(discovery['id'], self.owner,
            __import__('campus.discovery_schemas', fromlist=['DiscoveryStateInput']).DiscoveryStateInput(
                version=1, status='verified', reason='再次现场查看'))
        visible = json.loads(self.registry(self.helper).get('get_discovery_detail').invoke({'discovery_id': discovery['id']}))
        self.assertEqual(visible['status_source'], 'author_report')
        self.assertEqual(visible['status_source_label'], '发布者自报')
        self.assertEqual(visible['href'], '#/discoveries/' + discovery['id'])
        current = self.discovery.detail(discovery['id'])
        self.discovery.state(discovery['id'], self.owner,
            __import__('campus.discovery_schemas', fromlist=['DiscoveryWithdraw']).DiscoveryWithdraw(
                version=current['version'], reason='撤回内容'), True)
        hidden = json.loads(self.registry(self.helper).get('get_discovery_detail').invoke({'discovery_id': discovery['id']}))
        self.assertTrue(hidden.get('withdrawn'))
        self.assertNotIn('东门路灯不亮', json.dumps(hidden, ensure_ascii=False))

    def test_overview_separates_actionable_from_waiting_and_has_server_links(self):
        activity = self.activity.create(ActivityCreate.model_validate(
            self.activity_payload(registration_mode='review')), self.owner)
        self.activity.register(activity['id'], self.helper, '希望参加')
        data = json.loads(self.registry().get('get_my_overview').invoke({}))
        self.assertIn('todos', data)
        self.assertIn('waiting', data)
        self.assertTrue(any(item['content_type'] == 'activity' and item['href'] == '#/activities/' + activity['id']
                            for item in data['waiting']))
        self.assertEqual(data['server_time'], self.now.isoformat())

