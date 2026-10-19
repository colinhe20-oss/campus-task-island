"""Business-level regressions for the populated v2 demo, without remote models."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from examples.simulation_dataset import generate, Replay, aware_time
from campus.db import Database
from examples.simulation_verify import verify_timeline_and_stories


class SimulationTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='simulation-timeline-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = generate(Path(cls.temp.name) / 'demo', at='2026-10-19T18:00:00+08:00',
                                 publish_current=False, http_checks=False)
        cls.manifest = json.loads((cls.directory / 'manifest.json').read_text(encoding='utf-8'))
        cls.ids = cls.manifest['ids']

    def connect(self):
        conn = sqlite3.connect(self.directory / 'demo.sqlite3')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def recommended(self, conn, user, activity):
        return conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE user_id=? AND resource_id=? AND status='recommended'",
                            (self.ids[user], self.ids[activity])).fetchone()[0]

    def test_campus_activities_stay_within_daytime(self):
        zone = timezone(timedelta(hours=8))
        for table in ('activities', 'volunteer_activities'):
            for row in self.connect().execute('SELECT title,starts_at,ends_at FROM ' + table):
                start, end = [datetime.fromisoformat(row[k]).astimezone(zone) for k in ('starts_at', 'ends_at')]
                with self.subTest(title=row['title']):
                    self.assertEqual(start.date(), end.date())
                    self.assertGreaterEqual(start.hour, 8)
                    self.assertLessEqual(end.hour + end.minute / 60, 21)

    def test_actual_service_records_do_not_overlap(self):
        rows = list(self.connect().execute("""SELECT r.user_id,r.activity_id,j.starts_at,j.ends_at
            FROM volunteer_participation p JOIN volunteer_registrations r ON r.id=p.registration_id
            JOIN volunteer_jobs j ON j.id=r.job_id WHERE p.attendance='participated' AND p.actual_minutes>0"""))
        overlaps = [(a['activity_id'], b['activity_id']) for i, a in enumerate(rows) for b in rows[i+1:]
                    if a['user_id'] == b['user_id'] and a['activity_id'] != b['activity_id']
                    and max(a['starts_at'], b['starts_at']) < min(a['ends_at'], b['ends_at'])]
        self.assertEqual(overlaps, [])

    def test_story_prospects_are_unregistered_and_recommended(self):
        conn = self.connect()
        for user, activity in [('U012', 'A008'), ('U012', 'V036'), ('U010', 'A036'),
                               ('U013', 'A036'), ('U020', 'V003'), ('U009', 'V024'), ('U019', 'V017')]:
            with self.subTest(user=user, activity=activity):
                table = 'activity_registrations' if activity[0] == 'A' else 'volunteer_registrations'
                active = conn.execute("SELECT COUNT(*) FROM " + table + " WHERE user_id=? AND activity_id=? AND status IN ('pending','registered','waitlisted')",
                                      (self.ids[user], self.ids[activity])).fetchone()[0]
                self.assertEqual(active, 0)
                self.assertGreater(self.recommended(conn, user, activity), 0)

    def test_muted_profiles_have_candidates_but_no_opportunity_notifications(self):
        conn = self.connect()
        for user in ('U010', 'U015'):
            with self.subTest(user=user):
                self.assertGreater(conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE user_id=? AND status='recommended'", (self.ids[user],)).fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'", (self.ids[user],)).fetchone()[0], 0)

    def test_enrolled_and_expired_profiles_still_excluded(self):
        conn = self.connect()
        self.assertEqual(self.recommended(conn, 'U017', 'V024'), 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE user_id=? AND status='recommended'", (self.ids['U042'],)).fetchone()[0], 0)

    def test_matching_rerun_does_not_duplicate_notifications(self):
        conn = self.connect()
        before = conn.execute("SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'opportunity:%'").fetchone()[0]
        replay = Replay(Database(self.directory / 'demo.sqlite3'), aware_time(self.manifest['observation']))
        replay.time = aware_time(self.manifest['observation'])
        replay.matching.reconcile()
        after = conn.execute("SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'opportunity:%'").fetchone()[0]
        self.assertEqual(before, after)

    def test_verifier_rejects_overlapping_actual_records(self):
        conn = self.connect()
        start, end = conn.execute('SELECT starts_at,ends_at FROM volunteer_jobs WHERE activity_id=? LIMIT 1', (self.ids['V026'],)).fetchone()
        checks = {}
        try:
            conn.execute('UPDATE volunteer_jobs SET starts_at=?,ends_at=? WHERE activity_id=?', (start, end, self.ids['V032']))
            verify_timeline_and_stories(conn, self.ids, aware_time(self.manifest['observation']),
                                       lambda name, passed, detail='': checks.update({name: bool(passed)}))
            self.assertFalse(checks['实际志愿服务时间不重叠'])
        finally:
            conn.rollback()

    def test_verifier_rejects_missing_story_recommendation(self):
        conn = self.connect()
        checks = {}
        try:
            conn.execute("UPDATE opportunity_recommendations SET status='expired' WHERE user_id=? AND resource_id=?", (self.ids['U010'], self.ids['A036']))
            verify_timeline_and_stories(conn, self.ids, aware_time(self.manifest['observation']),
                                       lambda name, passed, detail='': checks.update({name: bool(passed)}))
            self.assertFalse(checks['U010/A036实际获得推荐'])
        finally:
            conn.rollback()
