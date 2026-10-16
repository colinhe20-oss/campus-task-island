"""R4: job pagination, matching and live user-specific state, on temporary databases."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from jsonschema import ValidationError

import test_guide as helpers
from campus.volunteer_schemas import VolunteerCreate
from tools.campus import build_campus_registry


class VolunteerJobSearchTests(unittest.TestCase):
    def setUp(self):
        helpers.GuideTests.setUp(self)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.volunteer = self.app.state.volunteer_service
        self.volunteer.clock = lambda: self.now
        self.owner = self.users['publisher'][1].id
        self.helper = self.users['helper'][1].id
        self.observer = self.users['observer'][1].id

    def create(self, count=6, *, start=2, **updates):
        stamp = lambda hours: (self.now + timedelta(hours=hours)).isoformat()
        payload = dict(title='校园公益服务', description='公益岗位招募', organization_name='测试社团',
            information_source='测试公告', contact='站内联系', recognition_conditions='按实际参与确认',
            starts_at=stamp(start), ends_at=stamp(start+1), opens_at=stamp(-1), closes_at=stamp(1),
            registration_mode='direct', jobs=[dict(name=f'岗位 {index}', description='整理物料',
                requirements='按时参与', location='活动中心', starts_at=stamp(start), ends_at=stamp(start+1),
                capacity=1, estimated_minutes=60, estimated_hours_description='按实际参与确认')
                for index in range(count)])
        return self.volunteer.create(VolunteerCreate.model_validate(payload | updates), self.owner)

    def search(self, *, user=None, **arguments):
        registry = build_campus_registry(self.service, user or self.helper, volunteers=self.volunteer)
        return json.loads(registry.get('search_volunteer_jobs').invoke(arguments))

    def test_volunteer_job_search_total_counts_all_jobs(self):
        self.create()
        result = self.search(limit=5, offset=0)
        self.assertEqual(result['total'], 6)
        self.assertEqual(len(result['items']), 5)

    def test_volunteer_job_search_second_page_keeps_remaining_job(self):
        activity = self.create()
        result = self.search(limit=5, offset=5)
        self.assertEqual([item['job_id'] for item in result['items']], [activity['jobs'][5]['id']])
        self.assertEqual(result['total'], 6)

    def test_pages_across_activities_have_stable_order_without_duplicates_or_gaps(self):
        activities = [self.create(3, start=3), self.create(4), self.create(2)]
        expected = [job['id'] for activity in sorted(activities, key=lambda a: (a['starts_at'], a['id']))
                    for job in activity['jobs']]
        actual = []
        for offset in (0, 5):
            page = self.search(limit=5, offset=offset)
            self.assertEqual(page['total'], 9)
            actual.extend(item['job_id'] for item in page['items'])
        self.assertEqual(actual, expected)
        self.assertEqual(len(set(actual)), 9)
        self.assertEqual([item['job_id'] for item in self.search(limit=5, offset=0)['items']], expected[:5])

    def test_matching_job_fields_is_case_insensitive_and_happens_before_pagination(self):
        activity = self.create(6)
        with self.service.database.connect() as connection:
            connection.execute('UPDATE volunteer_jobs SET name=?,description=?,requirements=?,location=? WHERE id=?',
                ('Straße 引导岗', 'x'*450+'摄影', 'Python', '紫金港', activity['jobs'][5]['id']))
        for keyword in ('STRASSE', '摄影', 'pYtHoN', '紫金港'):
            with self.subTest(keyword=keyword):
                result = self.search(keyword=keyword, limit=1)
                self.assertEqual(result['total'], 1)
                self.assertEqual([item['job_id'] for item in result['items']], [activity['jobs'][5]['id']])
                self.assertEqual(self.search(keyword=keyword, offset=1)['items'], [])

    def test_activity_field_matches_include_all_its_jobs(self):
        activity = self.create(3, title='校园接待', description='新生导览', organization_name='ZJU Club')
        self.create(2)
        for keyword in ('校园接待', '新生导览', 'zju club'):
            with self.subTest(keyword=keyword):
                result = self.search(keyword=keyword)
                self.assertEqual(result['total'], 3)
                self.assertEqual([item['job_id'] for item in result['items']], [job['id'] for job in activity['jobs']])

    def test_empty_results_and_out_of_range_offsets_keep_true_total(self):
        self.assertEqual(self.search()['items'], [])
        self.assertEqual(self.search()['total'], 0)
        self.create(2)
        self.assertEqual(self.search(keyword='不存在的关键词')['total'], 0)
        for offset in (2, 999):
            with self.subTest(offset=offset):
                result = self.search(offset=offset)
                self.assertEqual(result['items'], [])
                self.assertEqual(result['total'], 2)
        self.assertEqual(len(self.search(limit=1)['items']), 1)

    def test_visibility_keeps_full_closed_and_not_open_but_excludes_cancelled_and_ended(self):
        cancelled = self.create(1)
        self.volunteer.cancel_activity(cancelled['id'], self.owner, '取消测试')
        self.create(1, start=2)  # Ends exactly at the clock boundary below.
        full = self.create(1, start=5, closes_at=(self.now+timedelta(hours=4)).isoformat())
        self.volunteer.register(full['jobs'][0]['id'], self.observer, '占用唯一名额')
        closed = self.create(1, start=5)
        not_open = self.create(1, start=6, opens_at=(self.now+timedelta(hours=4)).isoformat(),
                               closes_at=(self.now+timedelta(hours=5)).isoformat())
        self.now += timedelta(hours=3)
        result = self.search()
        self.assertEqual(result['total'], 3)
        by_activity = {item['activity_id']: item for item in result['items']}
        self.assertEqual(by_activity[full['id']]['activity_status'], 'full')
        self.assertEqual(by_activity[full['id']]['remaining_capacity'], 0)
        self.assertEqual(by_activity[closed['id']]['activity_status'], 'closed')
        self.assertEqual(by_activity[not_open['id']]['activity_status'], 'not_open')

    def test_capacity_and_private_registration_are_read_for_bound_user(self):
        activity = self.create(2)
        job = activity['jobs'][0]
        self.volunteer.register(job['id'], self.observer, '另一用户的私人说明')
        registration = self.volunteer.register(job['id'], self.helper, '本人的报名说明')
        helper_result = self.search()
        item = next(item for item in helper_result['items'] if item['job_id'] == job['id'])
        self.assertEqual(item['remaining_capacity'], 0)
        self.assertEqual(item['my_registration']['id'], registration['id'])
        self.assertEqual(item['my_registration']['status'], 'waitlisted')
        self.assertEqual(item['my_registration']['waitlist_position'], 1)
        self.assertNotIn('另一用户的私人说明', json.dumps(helper_result, ensure_ascii=False))
        self.assertTrue(all(item['my_registration'] is None for item in self.search(user=self.owner)['items']))
        self.assertEqual(item['href'], '#/volunteers/' + activity['id'])

    def test_search_uses_one_clock_and_reuses_each_activity_detail_without_writes(self):
        activity = self.create()
        self.create(2, start=3)  # The next activity is outside this page.
        with self.service.database.connect() as connection:
            before = '\n'.join(connection.iterdump())
        with patch.object(self.volunteer, 'clock', side_effect=[self.now, self.now+timedelta(hours=4)]) as clock, \
                patch.object(self.volunteer, '_read', wraps=self.volunteer._read) as read:
            result = self.search()
        self.assertEqual(clock.call_count, 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['server_time'], self.now.isoformat())
        self.assertEqual(result['next_boundary'], activity['closes_at'])
        self.assertTrue(all(item['activity_status'] == 'open' for item in result['items']))
        with self.service.database.connect() as connection:
            self.assertEqual('\n'.join(connection.iterdump()), before)

    def test_registration_committed_during_search_is_visible_only_on_next_query(self):
        activity = self.create(1)
        original_read = self.volunteer._read

        def register_after_matching(*arguments, **keywords):
            # This write uses a separate connection after job selection has fixed
            # the read snapshot, before capacity is calculated on that snapshot.
            self.volunteer.register(activity['jobs'][0]['id'], self.observer, '并发报名')
            return original_read(*arguments, **keywords)

        with patch.object(self.volunteer, '_read', side_effect=register_after_matching):
            result = self.search()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['remaining_capacity'], 1)
        self.assertEqual(result['items'][0]['activity_status'], 'open')
        refreshed = self.search()
        self.assertEqual(refreshed['items'][0]['remaining_capacity'], 0)
        self.assertEqual(refreshed['items'][0]['activity_status'], 'full')

    def test_existing_activity_search_still_paginates_activities(self):
        activities = [self.create(6), self.create(2)]
        expected = sorted(activities, key=lambda a: (a['starts_at'], a['id']))
        for offset in (0, 1):
            result = self.volunteer.search(limit=1, offset=offset)
            self.assertEqual(result['total'], 2)
            self.assertEqual(result['items'][0]['id'], expected[offset]['id'])
            self.assertEqual(len(result['items'][0]['jobs']), len(expected[offset]['jobs']))

    def test_tool_rejects_invalid_pagination_and_forged_identity(self):
        for arguments in ({'limit': 0}, {'limit': 6}, {'offset': -1}, {'user_id': self.observer}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                self.search(**arguments)


if __name__ == '__main__':
    unittest.main()
