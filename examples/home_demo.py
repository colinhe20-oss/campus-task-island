"""首页与消息网页验收，临时数据库及独立测试时钟。"""
import json,tempfile,argparse
from pathlib import Path
from datetime import datetime,timedelta,timezone
import uvicorn
from campus.app import create_app
from campus.db import Database
from campus.auth import AuthService
from campus.service import TaskService
from campus.activities import ActivityService
from campus.volunteers import VolunteerService
from campus.schemas import TaskCreate
from campus.activity_schemas import ActivityCreate
from campus.volunteer_schemas import VolunteerCreate

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8001);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='campus-home-demo-') as temp:
        root=Path(temp);db=Database(root/'demo.sqlite3');db.initialize();auth=AuthService(db);auth.provision_demo_accounts()
        initial=datetime(2030,1,1,tzinfo=timezone.utc);clock_path=root/'clock.json';clock_path.write_text(json.dumps({'now':initial.isoformat()}),encoding='utf-8')
        def clock():return datetime.fromisoformat(json.loads(clock_path.read_text(encoding='utf-8'))['now'])
        def stamp(h):return (initial+timedelta(hours=h)).isoformat()
        with db.connect() as c:users={r['username']:r['id'] for r in c.execute('SELECT id,username FROM users')}
        task=TaskService(db).create_task(TaskCreate(reward_type='mutual',title='首页验收：校园摄影协作',category='creative',description='为校园活动拍摄照片',location='活动中心',deadline=stamp(48),completion_criteria='交付10张照片'),users['publisher'])
        a=ActivityService(db,clock).create(ActivityCreate(title='消息验收：美育讲座',description='了解校园艺术',location='活动中心',opens_at=stamp(-1),closes_at=stamp(1),starts_at=stamp(2),ends_at=stamp(3),capacity=1,registration_mode='direct',recognition_tags=['aesthetic'],recognition_description='活动方说明',organization_name='测试社团',information_source='合成验收',contact='站内',participation_requirements='本校学生'),users['publisher'])
        occupied=ActivityService(db,clock).register(a['id'],users['observer'])
        vol=VolunteerService(db,clock);v=vol.create(VolunteerCreate(title='消息验收：公益服务',description='校园公益岗位',organization_name='测试社团',information_source='合成验收',contact='站内',recognition_conditions='实际参与后核验',opens_at=stamp(-1),closes_at=stamp(1),starts_at=stamp(2),ends_at=stamp(5),registration_mode='direct',jobs=[dict(name='整理岗',description='整理物料',requirements='按时参与',location='活动中心',starts_at=stamp(2),ends_at=stamp(3),capacity=2,estimated_minutes=60,estimated_hours_description='按实际参与核验')]),users['publisher'])
        vr=vol.register(v['jobs'][0]['id'],users['helper'])
        with db.connect() as c:c.execute('DELETE FROM notifications')
        manifest=dict(database=str(db.path),accounts_path=str(auth.accounts_path),clock_path=str(clock_path),base_url=f'http://localhost:{args.port}',task_id=task.id,activity_id=a['id'],occupied_registration_id=occupied['id'],volunteer_id=v['id'],volunteer_registration_id=vr['id'],users=users)
        runtime=Path(__file__).resolve().parents[1]/'.runtime';(runtime/'home-demo.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print('临时验收信息：'+str(runtime/'home-demo.json'),flush=True)
        uvicorn.run(create_app(db.path,activity_clock=clock,volunteer_clock=clock,discovery_clock=clock),host='127.0.0.1',port=args.port)
if __name__=='__main__':main()
