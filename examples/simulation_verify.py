"""Snapshot and HTTP acceptance for the v2 isolated simulation directory."""
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from campus.clock import business_time
from campus.db import Database
from .simulation_dataset import Specification, Replay, aware_time, write_json, ROOT, LOCAL_ZONE


def verify_timeline_and_stories(conn, ids, e, check):
    """Check actual business relationships, independent of the allocation algorithm."""
    for table in ('activities', 'volunteer_activities'):
        invalid = []
        for row in conn.execute('SELECT id,starts_at,ends_at FROM ' + table):
            start, end = [datetime.fromisoformat(row[k]).astimezone(LOCAL_ZONE) for k in ('starts_at', 'ends_at')]
            if not (start.date() == end.date() and start.hour >= 8 and end.hour + end.minute / 60 <= 21
                    and start < end <= e + timedelta(days=21)):
                invalid.append(row['id'])
        check(table + '合理校园时段与未来窗口', not invalid, invalid)
    rows = list(conn.execute("""SELECT r.user_id,r.activity_id,j.starts_at,j.ends_at
        FROM volunteer_participation p JOIN volunteer_registrations r ON r.id=p.registration_id
        JOIN volunteer_jobs j ON j.id=r.job_id WHERE p.attendance='participated' AND p.actual_minutes>0"""))
    overlaps = [(a['activity_id'], b['activity_id']) for i, a in enumerate(rows) for b in rows[i+1:]
                if a['user_id'] == b['user_id'] and a['activity_id'] != b['activity_id']
                and max(a['starts_at'], b['starts_at']) < min(a['ends_at'], b['ends_at'])]
    check('实际志愿服务时间不重叠', not overlaps, overlaps)
    for user, key in [('U012', 'A008'), ('U012', 'V036'), ('U010', 'A036'), ('U013', 'A036'),
                      ('U020', 'V003'), ('U009', 'V024'), ('U019', 'V017')]:
        table = 'activity_registrations' if key[0] == 'A' else 'volunteer_registrations'
        enrolled = conn.execute("SELECT COUNT(*) FROM " + table + " WHERE user_id=? AND activity_id=? AND status IN ('pending','registered','waitlisted')", (ids[user], ids[key])).fetchone()[0]
        check(user + '/' + key + '尚未报名', enrolled == 0)
        matches = conn.execute("SELECT * FROM opportunity_recommendations WHERE user_id=? AND resource_id=? AND status='recommended'", (ids[user], ids[key])).fetchall()
        check(user + '/' + key + '实际获得推荐', bool(matches))
        if user == 'U012':
            check(user + '/' + key + '机会提醒已触发', any(conn.execute('SELECT 1 FROM notifications WHERE recipient_id=? AND event_key=?',
                (ids[user], 'opportunity:' + ':'.join((r['content_type'], r['resource_id'], r['job_id'])))).fetchone() for r in matches))
    for user in ('U010', 'U015'):
        candidates = conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE user_id=? AND status='recommended'", (ids[user],)).fetchone()[0]
        notices = conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'", (ids[user],)).fetchone()[0]
        check(user + '有推荐且关闭机会提醒', candidates > 0 and notices == 0)
    for user in ('U011', 'U042'):
        check(user + '时间冲突或过期偏好无推荐', conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE user_id=? AND status='recommended'", (ids[user],)).fetchone()[0] == 0)
    check('U017已报名V024不重复推荐', not conn.execute("SELECT 1 FROM opportunity_recommendations WHERE user_id=? AND resource_id=? AND status='recommended'", (ids['U017'], ids['V024'])).fetchone())
    check('U016关键词模式不误作A008语义推荐', not conn.execute("SELECT 1 FROM opportunity_recommendations WHERE user_id=? AND resource_id=? AND status='recommended'", (ids['U016'], ids['A008'])).fetchone())


def verify(directory, *, http_checks=True):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    snapshot = directory / 'specification.md'
    spec = Specification.load(snapshot) if snapshot.is_file() else Specification.load()
    if manifest.get('format_version') != 2:
        raise ValueError('不支持的模拟数据版本')
    e = aware_time(manifest['observation'])
    ids = manifest['ids']
    db = Database(directory / 'demo.sqlite3')
    if not db.path.is_file():
        raise FileNotFoundError(db.path)
    state = Replay(db, e)
    state.time = e
    state.refs = ids
    checks = []
    counts = {}

    def check(label, condition, detail=''):
        checks.append(dict(name=label, passed=bool(condition), detail=str(detail)))

    with business_time(lambda: e), db.connect() as conn:
        check('设计文档版本一致', hashlib.sha256(spec.text.encode()).hexdigest() == manifest['spec_sha256'])
        check('SQLite完整性与外键', conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not conn.execute('PRAGMA foreign_key_check').fetchall())
        for table, expected in [('users', 53), ('tasks', 12), ('activities', 48), ('volunteer_activities', 48),
                                ('volunteer_jobs', 104), ('discoveries', 12), ('task_stage_plans', 2), ('task_stages', 4)]:
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            check(f'{table}数量', counts[table] == expected, counts[table])
        check('50个模拟用户均有效', conn.execute("SELECT COUNT(*) FROM users WHERE username GLOB 'sim_u[0-9][0-9][0-9]' AND account_status='active'").fetchone()[0] == 50)

        raw_tasks = [dict(r) for r in conn.execute('SELECT * FROM tasks')]
        for field, expected in [('category', dict(learning=4, creative=2, music=1, daily=5)),
                                ('status', dict(published=3, in_progress=3, pending_review=1, completed=2, paused=1, cancelled=2)),
                                ('reward_type', dict(mutual=10, paid=2)), ('acceptance_mode', dict(approval=9, direct=3))]:
            actual = Counter(r[field] for r in raw_tasks)
            check('任务' + field + '分布', actual == expected, dict(actual))

        # 活动展示状态分布
        for kind, service, expected in [('A', state.activities, dict(not_open=4, open=12, full=4, closed=24, cancelled=4)),
                                        ('V', state.volunteers, dict(not_open=4, open=12, full=4, closed=23, cancelled=5))]:
            states = Counter()
            for row in spec.rows[kind]:
                key = row[0]
                detail = service.detail(ids[key])
                states[detail['status']] += 1
            check(kind + '展示状态分布', states == expected, dict(states))

        # 满额场 remaining_capacity=0（活动级）或每岗满（志愿级）
        for row in spec.rows['A']:
            if row[8] == '满额':
                d = state.activities.detail(ids[row[0]])
                check(row[0] + '满额', d['status'] == 'full' and d['remaining_capacity'] == 0)
        for row in spec.rows['V']:
            if row[7] == '满额':
                d = state.volunteers.detail(ids[row[0]])
                check(row[0] + '满额', d['status'] == 'full' and all(j['remaining_capacity'] == 0 for j in d['jobs']))

        # 无负责人自报名
        for kind, table in [('A', 'activity_registrations'), ('V', 'volunteer_registrations')]:
            for row in spec.rows[kind]:
                key = row[0]
                owner = row[4] if kind == 'A' else row[3]
                self_reg = conn.execute(f'SELECT 1 FROM {table} WHERE activity_id=? AND user_id=?', (ids[key], ids[owner])).fetchone()
                check(key + '无负责人自报名', self_reg is None)

        # 时长：个人最新确认分钟合计
        totals = {}
        for i in range(1, 51):
            u = f'U{i:03d}'
            totals[u] = state.volunteers.mine(ids[u], 'records')['confirmed_minutes']
        check('个人最新确认分钟合计1660', sum(totals.values()) == 1660, sum(totals.values()))

        # 关键更正：V026-J1/U009 旧120失效；V032-J2/U007 最新90
        v26 = next(r['service_record'] for r in state.volunteers.roster(ids['V026'], ids['U001'])['items'] if r['id'] == ids['V026-J1/U009'])
        check('V026-J1/U009更正后confirmed为null', v26['confirmed_minutes'] is None and v26['actual_minutes'] == 110 and v26['version'] == 3)
        v32 = next(r['service_record'] for r in state.volunteers.roster(ids['V032'], ids['U008'])['items'] if r['id'] == ids['V032-J2/U007'])
        check('V032-J2/U007更正确认90', v32['confirmed_minutes'] == 90 and v32['version'] == 3)
        v48 = state.volunteers.roster(ids['V048'], ids['U008'])['items']
        check('V048服务中取消分钟上限50', all(r['service_record']['maximum_actual_minutes'] == 50 for r in v48))

        # 换岗 V008：U009 有 cancelled + registered 两条历史
        v8 = next(r for r in state.volunteers.mine(ids['U009'], 'registrations')['items'] if r['id'] == ids['V008'])
        check('V008换岗保留旧记录', v8['my_registration']['job_id'] == ids['V008-J2'] and sorted(r['status'] for r in v8['registration_history']) == ['cancelled', 'registered'])

        # 偏好：16 份授权，其余 version=0
        pref = conn.execute('SELECT COUNT(*) FROM participation_preferences').fetchone()[0]
        check('偏好档案16份', pref == 16, pref)
        check('推荐表有记录', conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE status='recommended'").fetchone()[0] > 0)
        if manifest.get('data_revision') == '2.1':
            check('生成规格副本已保存', snapshot.is_file())
            verify_timeline_and_stories(conn, ids, e, check)

        # 消息：业务操作触发
        for table in ('applications', 'submissions', 'activity_registrations', 'volunteer_registrations', 'volunteer_participation', 'discovery_comments', 'notifications'):
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        check('组织用户有已读历史', conn.execute('SELECT COUNT(*) FROM notifications WHERE read_at IS NOT NULL').fetchone()[0] > 0)

        # 时间窗口
        log = json.loads((directory / 'events.json').read_text(encoding='utf-8'))
        check('回放事件有序', len(log) == manifest['events'] and all(aware_time(r['at']) <= e for r in log) and [r['at'] for r in log] == sorted(r['at'] for r in log))

    if http_checks:
        http_acceptance(directory, manifest, check)
    else:
        checks.append(dict(name='HTTP验收', passed=True, detail='调用方显式跳过，未执行HTTP检查'))

    failed = [c for c in checks if not c['passed']]
    report = dict(passed=not failed, observation=e.isoformat(), seed=manifest['seed'], spec_sha256=manifest['spec_sha256'],
                  simulated_users=50, builtin_users=3, events=manifest['events'], counts=counts, checks=checks,
                  http_checked=http_checks, confirmed_minutes=sum(totals.values()))
    write_json(directory / 'acceptance.json', report)
    lines = ['# 模拟环境验收报告', '', f"结果：{'PASS' if not failed else 'FAIL'}；观察时点：{e.isoformat()}；种子：{manifest['seed']}。", '',
             '50个模拟账号另加3个系统内置账号；48志愿 + 48综素 + 12任务 + 12发现；104个志愿岗位。',
             f"实际回放{manifest['events']}项操作；检查{len(checks)}项，通过{len(checks)-len(failed)}项；HTTP检查：{'已执行' if http_checks else '已跳过'}。", '',
             '账号密码保存在本目录accounts.json；业务ID映射在manifest.json；操作回放在events.json。', '',
             '| 检查 | 结果 |', '|---|---|']
    lines.extend(f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} |" for c in checks)
    if failed:
        lines.extend(['', '失败详情：'] + [f"- {c['name']}：{c['detail']}" for c in failed])
    lines.extend(['', '此报告验证业务数据与HTTP接口，不包含真实模型调用、多浏览器视觉验收或并发压力测试。', ''])
    (directory / 'acceptance.md').write_text('\n'.join(lines), encoding='utf-8')
    if failed:
        raise AssertionError('模拟数据验收失败：' + ', '.join(c['name'] for c in failed))
    return report


def http_acceptance(directory, manifest, check):
    from fastapi.testclient import TestClient
    from campus.app import create_app
    e = aware_time(manifest['observation'])
    ids = manifest['ids']
    credentials = json.loads((directory / 'accounts.json').read_text(encoding='utf-8'))
    by_key = {u['key']: u for u in credentials}

    def offline_backend():
        raise RuntimeError('模拟验收不允许调用远端模型')

    app = create_app(directory / 'demo.sqlite3', business_clock=lambda: e, guide_backend_factory=offline_backend, enable_semantics=False)
    with TestClient(app) as client:
        check('HTTP健康检查', client.get('/api/health').status_code == 200)
        frontend = ROOT / 'web' / 'dist' / 'index.html'
        check('前端生产页面可访问', frontend.is_file() and client.get('/').status_code == 200)
        for account in credentials:
            response = client.post('/api/auth/login', json={k: account[k] for k in ('username', 'password')})
            check(account['key'] + '可登录且身份正确', response.status_code == 200 and response.json().get('id') == ids[account['key']])
            client.post('/api/auth/logout')

        def login(key):
            user = by_key[key]
            result = client.post('/api/auth/login', json=dict(username=user['username'], password=user['password']))
            if result.status_code != 200:
                raise AssertionError('HTTP测试账号登录失败')

        # 权限隔离：无关用户不能取得他人名单
        login('U050')
        for label, url in [('活动名单', f"/api/activities/{ids['A027']}/registrations"), ('志愿名单', f"/api/volunteers/{ids['V008']}/registrations")]:
            check(label + '拒绝无关用户', client.get(url).status_code == 403)
        check('任务工作区不泄露他人材料', client.get(f"/api/tasks/{ids['T008']}/workspace").json().get('applications') == [])
        # 撤回可见性
        withdrawn = client.get(f"/api/discoveries/{ids['D012']}").json()
        check('HTTP撤回正文不可见', withdrawn.get('withdrawn') is True and 'description' not in withdrawn)
        # 志愿记录：U009 旧120失效
        login('U009')
        result = client.get('/api/me/volunteer-records').json()
        check('HTTP旧120不计入本人小时', result['confirmed_minutes'] == 120 and result['official_minutes'] is None)
        # 首页待办：U004 有 T008 变更待审批
        login('U004')
        home = client.get('/api/me/home').json()
        check('HTTP首页真实待办', home['todo_count'] > 0 and any(t['resource_id'] == ids['T008'] and t['action'] == 'review_change' for t in home['todos']))
        login('U049')
        check('HTTP作者保留撤回正文', 'description' in client.get(f"/api/discoveries/{ids['D012']}").json())
        client.post('/api/auth/logout')
    with TestClient(create_app(directory / 'demo.sqlite3', business_clock=lambda: e, guide_backend_factory=offline_backend, enable_semantics=False)) as client:
        check('应用重启后内容持久', client.get(f"/api/tasks/{ids['T006']}").json()['status'] == 'completed' and client.get(f"/api/activities/{ids['A027']}").json()['status'] == 'full')
