"""Snapshot and HTTP acceptance for an isolated simulation directory."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from campus.clock import business_time
from campus.db import Database
from .simulation_dataset import Specification, Replay, aware_time, write_json, relative, ROOT


def verify(directory, *, http_checks=True):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    spec=Specification.load()
    if manifest.get('format_version')!=1:raise ValueError('不支持的模拟数据版本')
    e=aware_time(manifest['observation']);ids=manifest['ids']
    db=Database(directory/'demo.sqlite3')
    if not db.path.is_file():raise FileNotFoundError(db.path)
    state=Replay(db,e);state.time=e;state.refs=ids
    checks=[];counts={};snapshots={}

    def check(label,condition,detail=''):
        checks.append(dict(name=label,passed=bool(condition),detail=str(detail)))

    with business_time(lambda:e),db.connect() as conn:
        check('设计文档版本一致',hashlib.sha256(spec.text.encode()).hexdigest()==manifest['spec_sha256'])
        check('SQLite完整性与外键',conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not conn.execute('PRAGMA foreign_key_check').fetchall())
        for table,expected in [('users',53),('tasks',50),('activities',20),('volunteer_activities',20),('volunteer_jobs',48),('discoveries',30),('task_stage_plans',12),('task_stages',24)]:
            counts[table]=conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            check(f'{table}数量',counts[table]==expected,counts[table])
        check('50个模拟用户均有效',conn.execute("SELECT COUNT(*) FROM users WHERE username GLOB 'sim_u[0-9][0-9][0-9]' AND account_status='active'").fetchone()[0]==50)
        raw_tasks=[dict(r) for r in conn.execute('SELECT * FROM tasks')]
        for field,expected in [('category',dict(learning=18,creative=12,music=6,daily=14)),
            ('status',dict(published=14,in_progress=16,pending_review=6,completed=8,paused=3,cancelled=3)),
            ('reward_type',dict(mutual=32,paid=18)),('acceptance_mode',dict(approval=30,direct=20))]:
            actual=Counter(r[field] for r in raw_tasks);check('任务'+field+'分布',actual==expected,dict(actual))
        for row in spec.rows['T']:
            key=row[0];task=state.tasks.get_task(ids[key]);snapshots[key]=task.model_dump(mode='json')
            expected=row[10].split('，')[0].split('；')[0]
            stored=conn.execute('SELECT status FROM tasks WHERE id=?',(ids[key],)).fetchone()[0]
            check(key+'存储／展示状态与发布者',stored==expected and task.status==('withdrawn' if not task.is_listed else expected) and task.publisher_id==ids[row[3]])
            check(key+'有效截止与验收标准',task.deadline==relative(e,row[8]) and task.completion_criteria==row[5])
        check('未接取已截止三项',{k for k in snapshots if snapshots[k]['is_expired']}=={'T009','T010','T011'})
        check('协作逾期两项',{k for k in snapshots if snapshots[k]['is_overdue']}=={'T025','T029'})
        check('T047暂停但截止已过',snapshots['T047']['status']=='paused' and aware_time(snapshots['T047']['deadline'])<e and not snapshots['T047']['is_overdue'])
        check('下架两项',{f'T{i:03d}' for i in range(1,51) if not snapshots[f'T{i:03d}']['is_listed']}=={'T012','T013'})
        check('无自接任务',not conn.execute('SELECT 1 FROM tasks WHERE assignee_id=publisher_id').fetchone())
        for row in spec.stages:
            stages=state.stages.read(ids[row[1]],ids[next(r[3] for r in spec.rows['T'] if r[0]==row[1])]).stages
            expected=row[4].split('／')
            check(row[1]+'阶段结果',[s.status for s in stages]==expected)
            if row[0]=='S6':check('阶段退回版本',[s.version for s in stages]==[4,4])
        applications=lambda key:[dict(r) for r in conn.execute('SELECT * FROM applications WHERE task_id=?',(ids[key],))]
        check('T002两项待选两项撤回',Counter(r['status'] for r in applications('T002'))==dict(pending=2,withdrawn=2))
        check('T024选定且保留落选历史',Counter(r['status'] for r in applications('T024'))==dict(accepted=1,rejected=1))
        check('T040两次成果提交',Counter(r[0] for r in conn.execute('SELECT status FROM submissions WHERE task_id=?',(ids['T040'],)))==dict(changes_requested=1,accepted=1))
        changes=state.tasks.terms.changes.read(ids['T026'],ids['U004'])
        check('T026已生效与待确认变更',changes['terms_version']==2 and Counter(r['status'] for r in changes['items'])==dict(approved=1,pending=1))
        check('T045暂停恢复再暂停',snapshots['T045']['collaboration_version']==4)
        for key,payer,payee in [('T038',True,True),('T040',True,False),('T042',False,False),('T044',True,True),('T049',True,False)]:
            owner=next(r[3] for r in spec.rows['T'] if r[0]==key)
            settlement=state.tasks.terms.settlement(ids[key],ids[owner])
            check(key+'独立结算',bool(settlement['payer_confirmed'])==payer and bool(settlement['payee_confirmed'])==payee)
        check('T049取消结算2000分',snapshots['T049']['cancellation_settlement_fen']==2000)
        zero=state.tasks.terms.settlement(ids['T050'],ids['U002'])
        check('T050零元无需确认',zero['no_payment_required'] and not zero['available'])

        intervals=defaultdict(list)
        for kind,service,table in [('A',state.activities,'activities'),('V',state.volunteers,'volunteer_activities')]:
            states=[]
            for row in spec.rows[kind]:
                key=row[0];detail=service.detail(ids[key]);snapshots[key]=detail;states.append(detail['status'])
                text=row[9] if kind=='A' else row[11]
                expected='not_open' if text.startswith('未开放') else 'full' if '满额／' in text else 'cancelled' if '取消／' in text else 'open' if text.startswith('开放有位') else 'closed'
                check(key+'时间／名额状态',detail['status']==expected)
                if kind=='A':check(key+'未超额',detail['registered_count']<=detail['capacity'])
                else:check(key+'岗位未超额',all(j['registered_count']<=j['capacity'] for j in detail['jobs']))
                roster=service.roster(ids[key],ids[row[3]])['items']
                if kind=='A':
                    for r in roster:
                        if r['status']=='registered':intervals[r['user_id']].append((aware_time(detail['starts_at']),aware_time(detail['ends_at']),key))
                else:
                    for r in roster:
                        if r['status']=='registered' or (key=='V020' and r['service_record'] is not None):
                            end=aware_time(detail['cancelled_at']) if key=='V020' else aware_time(r['ends_at'])
                            intervals[r['user_id']].append((aware_time(r['starts_at']),end,key))
                registrations='activity_registrations' if kind=='A' else 'volunteer_registrations'
                check(key+'无负责人自报名',not conn.execute(f'SELECT 1 FROM {registrations} WHERE activity_id=? AND user_id=?',(ids[key],ids[row[3]])).fetchone())
            expected=dict(not_open=3,open=7,full=3,closed=5,cancelled=2) if kind=='A' else dict(not_open=2,open=6,full=3,closed=7,cancelled=2)
            check(kind+'展示状态分布',Counter(states)==expected,dict(Counter(states)))
            modes=Counter(r[0] for r in conn.execute(f'SELECT registration_mode FROM {table}'))
            check(kind+'报名方式',modes==dict(direct=10,review=10))
        check('全部已获名额活动时段不重叠',all(all(a[1]<=b[0] for a,b in zip(sorted(v),sorted(v)[1:])) for v in intervals.values()))
        a11=state.activities.detail(ids['A011'],ids['U020'])['my_registration']
        check('A011候补序号2而位置1',a11['status']=='waitlisted' and a11['queue_sequence']==2 and a11['waitlist_position']==1)
        check('A011已转正',state.activities.detail(ids['A011'],ids['U018'])['my_registration']['status']=='registered')
        a18=state.activities.detail(ids['A018'],ids['U012'])['my_registration']
        stored=conn.execute('SELECT status FROM activity_registrations WHERE id=?',(a18['id'],)).fetchone()[0]
        check('A018展示未获名额且存储仍pending',a18['status']=='not_selected' and stored=='pending')
        check('A018重新申请保留两次',conn.execute('SELECT COUNT(*) FROM activity_registrations WHERE activity_id=? AND user_id=?',(ids['A018'],ids['U010'])).fetchone()[0]==2)
        v3=state.volunteers.mine(ids['U009'],'registrations')['items']
        v3=next(r for r in v3 if r['id']==ids['V003'])
        check('V003换岗保留旧记录',v3['my_registration']['job_id']==ids['V003-J2'] and sorted(r['status'] for r in v3['registration_history'])==['cancelled','registered'])
        check('V003部分满额整场open',snapshots['V003']['status']=='open' and [j['remaining_capacity'] for j in snapshots['V003']['jobs']]==[0,0,1])
        check('同人同场唯一有效志愿报名',not conn.execute("SELECT 1 FROM volunteer_registrations WHERE status IN ('pending','registered','waitlisted') GROUP BY activity_id,user_id HAVING COUNT(*)>1").fetchone())
        for row in spec.minutes:
            job,user=row[0].split('／');key=job[:4];owner=next(r[3] for r in spec.rows['V'] if r[0]==key)
            record=next(r['service_record'] for r in state.volunteers.roster(ids[key],ids[owner])['items'] if r['id']==ids[f'{job}/{user}'])
            expected=None if row[2]=='null' else int(row[2]);version,status=row[3].split('／')
            check(row[0]+'最新时长与版本',record is not None and record['actual_minutes']==int(row[1]) and record['confirmed_minutes']==expected and record['version']==int(version) and record['status']==status)
        totals={u:state.volunteers.mine(ids[u],'records')['confirmed_minutes'] for u in ids if re.fullmatch(r'U\d{3}',u)}
        check('个人最新确认合计870分钟',sum(totals.values())==870,totals)
        check('V020取消后核验上限50分钟',all(r['service_record']['maximum_actual_minutes']==50 for r in state.volunteers.roster(ids['V020'],ids['U004'])['items']))
        check('V019取消前未开始无核验资格',all(r['service_record'] is None for r in state.volunteers.roster(ids['V019'],ids['U003'])['items']))

        for row in spec.rows['D']:
            key=row[0];detail=state.discoveries.detail(ids[key],ids[row[3]]);snapshots[key]=detail
            target=re.findall(r'(?<![a-z_])(?:unverified|verified|reported|in_progress|resolved|valid|invalid|visible|expired)(?![a-z_])',row[7])[-1]
            check(key+'分类状态与撤回',detail['category']==row[2] and detail['status']==target and detail['withdrawn']==('撤回' in row[7]))
        check('D001/D030版本',snapshots['D001']['version']==6 and snapshots['D030']['version']==4)
        check('D030外人不可读取正文','description' not in state.discoveries.detail(ids['D030'],ids['U050']))
        for table in ['applications','submissions','stage_submissions','task_changes','task_agreements','task_stage_plans','task_settlement_history','activity_events','volunteer_events','volunteer_record_versions','discoveries','discovery_versions','discovery_comments','notifications']:
            columns=[r['name'] for r in conn.execute(f'PRAGMA table_info({table})') if r['name'].endswith('_at')]
            stamps=[aware_time(r[0]) for col in columns for r in conn.execute(f'SELECT "{col}" FROM {table} WHERE "{col}" IS NOT NULL')]
            check(table+'历史时间窗口',all(e-timedelta(days=28)<=stamp<=e for stamp in stamps))
        for table in ('applications','submissions','stage_submissions','activity_registrations','volunteer_registrations','volunteer_participation','discovery_comments','notifications'):
            counts[table]=conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        check('组织用户有已读历史',conn.execute('SELECT COUNT(*) FROM notifications WHERE read_at IS NOT NULL').fetchone()[0]>0)
        check('T026新提案未读',conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND resource_id=? AND read_at IS NULL",(ids['U004'],ids['T026'])).fetchone()[0]>0)
        log=json.loads((directory/'events.json').read_text(encoding='utf-8'))
        check('回放事件有序且未越过观察时点',len(log)==manifest['events'] and all(aware_time(r['at'])<=e for r in log) and [r['at'] for r in log]==sorted(r['at'] for r in log))
        check('50个账号均有实际业务操作',{r['actor'] for r in log if r['action']!='read_messages'}=={f'U{i:03d}' for i in range(1,51)})

    if http_checks:
        http_acceptance(directory,manifest,check)
    else:
        checks.append(dict(name='HTTP验收',passed=True,detail='调用方显式跳过，未执行HTTP检查'))
    failed=[c for c in checks if not c['passed']]
    report=dict(passed=not failed,observation=e.isoformat(),seed=manifest['seed'],spec_sha256=manifest['spec_sha256'],
        simulated_users=50,builtin_users=3,events=manifest['events'],counts=counts,checks=checks,
        http_checked=http_checks,confirmed_minutes=sum(totals.values()))
    write_json(directory/'acceptance.json',report)
    write_json(directory/'snapshot.json',snapshots)
    lines=['# 模拟环境验收报告','',f"结果：{'PASS' if not failed else 'FAIL'}；观察时点：{e.isoformat()}；种子：{manifest['seed']}。",'',
        '50个模拟账号另加3个系统内置账号；120条主体内容、48个志愿岗位。',
        f"实际回放{manifest['events']}项操作；检查{len(checks)}项，通过{len(checks)-len(failed)}项；HTTP检查：{'已执行' if http_checks else '已跳过'}。",'',
        f'最新有效活动方确认分钟合计{sum(totals.values())}（{sum(totals.values())/60:g}小时），学校正式认定未对接。','',
        '账号密码保存在本目录accounts.json；业务ID映射在manifest.json；操作回放在events.json；E时快照在snapshot.json。',
        '运行 .\\start_simulation.cmd 启动当前演示库；完整命令见项目docs/SIMULATION_USAGE.md。','',
        '| 检查 | 结果 |','|---|---|']
    lines.extend(f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} |" for c in checks)
    if failed:
        lines.extend(['','失败详情：']+[f"- {c['name']}：{c['detail']}" for c in failed])
    lines.extend(['','此报告验证业务数据与HTTP接口，不包含真实模型调用、多浏览器视觉验收或并发压力测试。',''])
    (directory/'acceptance.md').write_text('\n'.join(lines),encoding='utf-8')
    if failed:raise AssertionError('模拟数据验收失败：'+', '.join(c['name'] for c in failed))
    return report


def http_acceptance(directory,manifest,check):
    from fastapi.testclient import TestClient
    from campus.app import create_app
    e=aware_time(manifest['observation']);ids=manifest['ids']
    credentials=json.loads((directory/'accounts.json').read_text(encoding='utf-8'))
    by_key={u['key']:u for u in credentials}
    def offline_backend():raise RuntimeError('模拟验收不允许调用远端模型')
    app=create_app(directory/'demo.sqlite3',business_clock=lambda:e,guide_backend_factory=offline_backend)
    with TestClient(app) as client:
        check('HTTP健康检查',client.get('/api/health').status_code==200)
        frontend=ROOT/'web'/'dist'/'index.html'
        check('前端生产页面可访问',frontend.is_file() and client.get('/').status_code==200)
        for account in credentials:
            response=client.post('/api/auth/login',json={k:account[k] for k in ('username','password')})
            check(account['key']+'可登录且身份正确',response.status_code==200 and response.json().get('id')==ids[account['key']])
            client.post('/api/auth/logout')
        def login(key):
            user=by_key[key]
            result=client.post('/api/auth/login',json=dict(username=user['username'],password=user['password']))
            if result.status_code!=200:raise AssertionError('HTTP测试账号登录失败')
        login('U050')
        workspace=client.get(f"/api/tasks/{ids['T020']}/workspace").json()
        check('任务工作区不泄露他人材料',workspace.get('applications')==[] and workspace.get('submissions')==[])
        stages=client.get(f"/api/tasks/{ids['T020']}/stages").json()
        check('阶段公开计划不泄露成果或版本历史',stages.get('versions')==[] and all(not s['submissions'] for s in stages['stages']))
        for label,url in [('活动名单',f"/api/activities/{ids['A011']}/registrations"),('志愿名单',f"/api/volunteers/{ids['V003']}/registrations")]:
            check(label+'拒绝无关用户',client.get(url).status_code==403)
        for kind,key in [('activities','A011'),('volunteers','V003')]:
            public=client.get(f'/api/{kind}/{ids[key]}').json()
            check(key+'公共详情无他人名单','registrations' not in public and 'application_note' not in public)
        withdrawn=client.get(f"/api/discoveries/{ids['D030']}").json()
        check('HTTP撤回正文不可见',withdrawn.get('withdrawn') is True and 'description' not in withdrawn)
        check('HTTP撤回评论不再公开',client.get(f"/api/discoveries/{ids['D030']}/comments").status_code==410)
        login('U009')
        result=client.get('/api/me/volunteer-records').json()
        check('HTTP旧120不计入本人小时',result['confirmed_minutes']==0 and result['official_minutes'] is None)
        login('U004')
        home=client.get('/api/me/home').json()
        check('HTTP首页真实待办',home['todo_count']>0 and any(t['resource_id']==ids['T026'] and t['action']=='review_change' for t in home['todos']))
        messages=client.get('/api/me/messages').json()
        check('HTTP消息时钟与观察时点一致',aware_time(messages['server_time'])==e)
        login('U049')
        check('HTTP作者保留撤回正文','description' in client.get(f"/api/discoveries/{ids['D030']}").json())
        client.post('/api/auth/logout')
    # Opening a second app performs the normal lifespan initialization on the same file.
    with TestClient(create_app(directory/'demo.sqlite3',business_clock=lambda:e,guide_backend_factory=offline_backend)) as client:
        check('应用重启后内容持久',client.get(f"/api/tasks/{ids['T039']}").json()['status']=='completed' and client.get(f"/api/activities/{ids['A011']}").json()['status']=='full')
