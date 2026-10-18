import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from campus.clock import business_time, utc_now
from examples.simulation_dataset import generate, aware_time
from examples.simulation_server import demo_app
from examples.simulation_verify import verify


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='campus-simulation-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=generate(Path(cls.temp.name)/'baseline',at='2030-01-01T18:00:00+08:00',publish_current=False)
        cls.manifest=json.loads((cls.directory/'manifest.json').read_text(encoding='utf-8'))

    def copy_dataset(self):
        temp=self.enterContext(tempfile.TemporaryDirectory(prefix='campus-simulation-copy-'))
        target=Path(temp)/'copy'
        shutil.copytree(self.directory,target)
        return target

    def test_full_report_and_login_privacy_checks_pass(self):
        report=json.loads((self.directory/'acceptance.json').read_text(encoding='utf-8'))
        self.assertTrue(report['passed'])
        self.assertTrue(report['http_checked'])
        self.assertGreater(len(report['checks']),300)
        self.assertEqual(report['counts']['users'],53)
        self.assertEqual(report['confirmed_minutes'],870)
        log=json.loads((self.directory/'events.json').read_text(encoding='utf-8'))
        self.assertEqual(len(log),self.manifest['events'])
        self.assertEqual(log,sorted(log,key=lambda r:r['at']))

    def test_existing_destination_is_never_overwritten(self):
        before=(self.directory/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):
            generate(self.directory,publish_current=False)
        self.assertEqual((self.directory/'manifest.json').read_bytes(),before)

    def test_fixed_seed_reproduces_business_ids_not_credentials(self):
        other=generate(Path(self.temp.name)/'repeated',at=self.manifest['observation'],seed=self.manifest['seed'],publish_current=False,http_checks=False)
        second=json.loads((other/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(self.manifest['ids'],second['ids'])
        for name in ('events.json','snapshot.json'):
            self.assertEqual(json.loads((self.directory/name).read_text(encoding='utf-8')),json.loads((other/name).read_text(encoding='utf-8')))
        self.assertNotEqual((self.directory/'accounts.json').read_bytes(),(other/'accounts.json').read_bytes())

    def test_clock_context_restores_and_is_async_task_local(self):
        first=aware_time('2030-01-01T18:00:00+08:00')
        second=first+timedelta(days=3)
        async def read_at(at):
            with business_time(lambda:at):
                await asyncio.sleep(0)
                return utc_now()
        async def gather():return await asyncio.gather(read_at(first),read_at(second))
        self.assertEqual(asyncio.run(gather()),[first,second])
        with self.assertRaisesRegex(RuntimeError,'sentinel'):
            with business_time(lambda:first):raise RuntimeError('sentinel')
        self.assertLess(abs((utc_now()-datetime.now(timezone.utc)).total_seconds()),2)

    def test_manual_operation_uses_demo_clock_and_persists_after_restart(self):
        directory=self.copy_dataset();ids=self.manifest['ids']
        accounts=json.loads((directory/'accounts.json').read_text(encoding='utf-8'))
        helper=next(u for u in accounts if u['key']=='U043')
        with TestClient(demo_app(directory,frozen=True)) as client:
            self.assertEqual(client.post('/api/auth/login',json={k:helper[k] for k in ('username','password')}).status_code,200)
            response=client.post(f"/api/tasks/{ids['T004']}/claim",json={'confirmed':True})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['status'],'in_progress')
            self.assertEqual(aware_time(client.get('/api/me/messages').json()['server_time']),aware_time(self.manifest['observation']))
        with TestClient(demo_app(directory,frozen=True)) as client:
            result=client.get(f"/api/tasks/{ids['T004']}").json()
            self.assertEqual(result['assignee_id'],ids['U043'])
        with self.assertRaisesRegex(AssertionError,'验收失败'):
            verify(directory,http_checks=False)
        self.assertFalse(json.loads((directory/'acceptance.json').read_text(encoding='utf-8'))['passed'])

    def test_runtime_clock_anchor_is_persistent(self):
        a=demo_app(self.directory)
        b=demo_app(self.directory)
        with TestClient(a) as first,TestClient(b) as second:
            ta=aware_time(first.get('/api/simulation').json()['server_time'])
            tb=aware_time(second.get('/api/simulation').json()['server_time'])
            self.assertLess(abs((tb-ta).total_seconds()),3)

    def test_failure_does_not_publish_partial_database(self):
        target=Path(self.temp.name)/'failed'
        with patch('examples.simulation_dataset.Replay.run',side_effect=RuntimeError('sentinel')):
            with self.assertRaisesRegex(RuntimeError,'回放失败'):
                generate(target,at=self.manifest['observation'],publish_current=False,http_checks=False)
        self.assertFalse(target.exists())
        self.assertFalse(list(target.parent.glob('.building-*')))

    def test_naive_time_is_rejected_before_creating_output(self):
        target=Path(self.temp.name)/'naive'
        with self.assertRaisesRegex(ValueError,'时区'):
            generate(target,at='2030-01-01T18:00:00',publish_current=False)
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
