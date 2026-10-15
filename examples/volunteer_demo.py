"""志愿网页验收服务器：临时数据库与可推进的测试时钟，不写正式库。"""
import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uvicorn
from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database
from campus.volunteers import VolunteerService
from campus.volunteer_schemas import VolunteerCreate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8001)
    args=parser.parse_args()
    runtime=Path(__file__).resolve().parents[1]/'.runtime'
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='campus-volunteer-demo-') as temp:
        db=Database(Path(temp)/'demo.sqlite3');db.initialize();auth=AuthService(db);auth.provision_demo_accounts()
        clock_path=Path(temp)/'clock.json'
        initial=datetime(2030,1,1,tzinfo=timezone.utc)
        clock_path.write_text(json.dumps({'now':initial.isoformat()}),encoding='utf-8')
        def clock():return datetime.fromisoformat(json.loads(clock_path.read_text(encoding='utf-8'))['now'])
        with db.connect() as conn:owner=conn.execute("SELECT id FROM users WHERE username='publisher'").fetchone()[0]
        def stamp(h):return initial+timedelta(hours=h)
        jobs=[dict(name=name,description='整理公益活动物料',requirements='本校学生，能按时参加',location='学生活动中心',starts_at=stamp(start),ends_at=stamp(start+1),capacity=1,estimated_minutes=60,estimated_hours_description='预计60分钟，按实际参与核验') for name,start in [('上午整理岗',2),('下午引导岗',4)]]
        body=VolunteerCreate(title='【志愿验收】校园公益活动',description='合成测试活动，两个岗位分别服务',organization_name='测试公益社团',information_source='测试公告',contact='站内联系负责人',recognition_conditions='按岗位工作完成情况核验实际服务分钟数',starts_at=stamp(2),ends_at=stamp(5),opens_at=stamp(-1),closes_at=stamp(1),registration_mode='review',jobs=jobs)
        service=VolunteerService(db,clock)
        activity=service.create(body,owner)
        manifest=dict(database=str(db.path),accounts_path=str(auth.accounts_path),clock_path=str(clock_path),initial_time=initial.isoformat(),activity_id=activity['id'],jobs=[j['id'] for j in activity['jobs']],base_url=f'http://localhost:{args.port}')
        (runtime/'volunteer-demo.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print('测试信息：'+str(runtime/'volunteer-demo.json'),flush=True)
        uvicorn.run(create_app(db.path,volunteer_clock=clock),host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
