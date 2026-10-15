"""网页活动验收：临时数据库，不写入正式任务数据，不调用远端模型。"""
import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from campus.app import create_app
from campus.auth import AuthService
from campus.activities import ActivityService
from campus.activity_schemas import ActivityCreate
from campus.db import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-activities-') as temp:
        database = Database(Path(temp) / 'demo.sqlite3')
        database.initialize()
        auth = AuthService(database)
        auth.provision_demo_accounts()
        with database.connect() as conn:
            owner = conn.execute("SELECT id FROM users WHERE username='publisher'").fetchone()[0]
        service = ActivityService(database)
        now = datetime.now(timezone.utc)
        common = dict(description='临时数据库的网页验收活动', location='学生活动中心',
                      opens_at=now - timedelta(hours=1), closes_at=now + timedelta(hours=2),
                      starts_at=now + timedelta(hours=3), ends_at=now + timedelta(hours=4),
                      capacity=1, recognition_tags=['aesthetic'], recognition_description='活动方说明，实际认定以主管方为准',
                      organization_name='测试社团', information_source='测试公告', contact='站内联系', participation_requirements='本校在读学生')
        activities = {}
        for key, fields in (
            ('review', dict(title='【验收】美育工作坊', registration_mode='review')),
            ('direct', dict(title='【验收】二课讲座', registration_mode='direct', recognition_tags=['second_class'])),
            ('upcoming', dict(title='【验收】定时开放', registration_mode='direct', opens_at=now + timedelta(seconds=90), recognition_tags=['ideological']))):
            activities[key] = service.create(ActivityCreate.model_validate(common | fields), owner)['id']
        manifest = dict(database=str(database.path), accounts_path=str(auth.accounts_path), activities=activities, base_url=f'http://localhost:{args.port}')
        output = Path(__file__).resolve().parents[1] / '.runtime' / 'activity-demo.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print('验收信息：' + str(output), flush=True)
        uvicorn.run(create_app(database.path), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
