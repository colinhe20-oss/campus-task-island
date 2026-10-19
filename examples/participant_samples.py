"""Frozen participant fixtures, native matching/lifecycle runs, and real dialogues.

All writes target a new isolated experiment directory. Gold labels are authored
from the activity rules, never produced by the ranker being evaluated.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from campus.app import create_app
from campus.assistance import Preferences
from campus.activity_schemas import ActivityCreate, RegistrationReview
from campus.volunteer_schemas import VolunteerCreate
from campus.clock import business_time
from campus.schemas import GuideInput, UserRead
from campus.guide import model_backend
from .collect_letter_sample import ObservedBackend

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'docs/dataset_samples/PART-MATCH-001'
BASE = '2027-05-16T10:00:00+08:00'
AT = '2027-05-16T13:00:00+08:00'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def slot(start, end):
    return {'starts_at': '2027-05-23T' + start + ':00+08:00',
            'ends_at': '2027-05-23T' + end + ':00+08:00'}


def verify_spec():
    m = read(SPEC / 'manifest.json')
    assert all(sha(SPEC / n) == h for n, h in m['files'].items()), 'Frozen sample changed'
    d = read(SPEC / 'gold.json')
    for source in d['sources']:
        p = ROOT / source['path']
        assert sha(p) == source['sha256'], 'Source gold changed'
    return d


def make_spec():
    if SPEC.exists():
        raise ValueError('Refusing to overwrite sample specification')
    def profile(key, name, interests, kinds, hours, notifications=True, skills=None, **extra):
        fields = dict(skills=skills or [], interests=interests, locations=['紫金港'],
                      content_types=kinds, notifications_enabled=notifications,
                      available_slots=[slot(*hours)] if hours else []) | extra
        return {'id': key, 'name': name, 'persona': '模拟浙江大学在校学生；身份为场景自述，不视为学校认证。',
                'fields': Preferences.model_validate(fields).model_dump(mode='json')}
    people = [
        profile('P01', '书信兴趣且全程有空', ['书信', '公益'], ['volunteer'], ('14:00', '16:00'), skills=['回信']),
        profile('P02', '手作兴趣且开放时段均有空', ['手作', '传统文化'], ['activity'], ('12:00', '17:00')),
        profile('P03', '书信志愿仅后半段有空', ['书信', '公益'], ['volunteer'], ('15:00', '17:00'), skills=['回信']),
        profile('P04', '游园仅一小时有空', ['手作', '传统文化'], ['activity'], ('14:00', '15:00')),
        profile('P05', '书信兴趣但未登记空闲', ['书信', '公益'], ['volunteer'], None, skills=['回信']),
        profile('P06', '只有地点相同', ['篮球'], ['volunteer', 'activity'], ('12:00', '17:00')),
        profile('P07', '已申请书信活动', ['书信', '公益'], ['volunteer'], ('14:00', '16:00'), skills=['回信']),
        profile('P08', '手作匹配但不接收提醒', ['手作', '传统文化'], ['activity'], ('12:00', '17:00'), notifications=False),
        profile('P09', '两个方向均感兴趣', ['书信', '公益', '手作', '传统文化'], ['volunteer', 'activity'], ('12:00', '17:00'), skills=['回信']),
        profile('P10', '偏好已过期', ['书信', '公益', '手作', '传统文化'], ['volunteer', 'activity'], ('12:00', '17:00'), valid_until='2027-05-16T12:00:00+08:00'),
        profile('P11', '中段不可参与但可错时游园', ['书信', '公益', '手作', '传统文化'], ['volunteer', 'activity'], ('12:00', '17:00'), skills=['回信'], unavailable_slots=[slot('14:00', '16:00')]),
        profile('P12', '传统文化语义表达', ['传统文化'], ['activity'], ('12:00', '17:00')),
    ]
    people[6]['initial_registration'] = {'opportunity': 'V', 'status': 'pending'}
    # These labels follow the activity rules, including the free-arrival rule.
    verdicts = [
        ('recommend', 'exclude', '志愿时段完整且兴趣吻合；综素不在用户选择类型中。'),
        ('exclude', 'recommend', '游园兴趣和时段吻合；志愿不在选择类型中。'),
        ('exclude', 'exclude', '书信岗位要求14至16点全程，15至17点不满足；综素未选。'),
        ('exclude', 'conditional', '游园允许自由到场，14至15点可作为候选；需核对体验耗时，不保证集满章。'),
        ('conditional', 'exclude', '书信方向相关，空闲未知应提醒核对14至16点；不是自动判定有空。'),
        ('exclude', 'exclude', '地点相同不足以建立兴趣或技能相关性。'),
        ('exclude', 'exclude', '本人已有有效待审核申请，不重复招募；综素未选。'),
        ('exclude', 'recommend', '关闭提醒不应关闭推荐列表，只禁止发送机会提醒。'),
        ('recommend', 'recommend', '两项兴趣与时段均吻合，不规定两项之间的唯一排序。'),
        ('exclude', 'exclude', '偏好在观察时点已过期。'),
        ('exclude', 'conditional', '14至16点不能完整服务，但可12至14点或16至17点游园；需核对体验条件。'),
        ('exclude', 'recommend', '传统文化与小满传统手作语义相关，不要求逐字命中。'),
    ]
    pairs = [{'profile': p['id'], 'opportunity': k, 'label': row[i], 'reason': row[2]}
             for p, row in zip(people, verdicts) for i, k in enumerate(('V', 'A'))]
    sources = []
    for name in ('VOL-LETTER-001', 'ACT-XIAOMAN-001'):
        rel = f'docs/dataset_samples/{name}/gold.json'
        sources.append({'sample_id': name, 'path': rel, 'sha256': sha(ROOT / rel)})
    messages = {
        'P01': '我会回信，兴趣是书信、公益，优先紫金港。只关注志愿服务。我在2027年5月23日14:00到16:00有空，按北京时间，只是这一次，不是每周。请帮我登记成待核对偏好，我希望确认保存后通过站内消息提醒新机会。',
        'P02': '我的兴趣是手作、传统文化，优先紫金港，只关注综素活动。我在2027年5月23日12:00到17:00有空，按北京时间，只是这一次。请登记成待核对偏好，我希望确认保存后通过站内消息提醒新机会。',
        'P04': '我的兴趣是手作、传统文化，优先紫金港，只关注综素活动。我在2027年5月23日14:00到15:00只有这一小时有空，按北京时间，只是这一次。请登记成待核对偏好，我希望确认保存后通过站内消息提醒新机会。',
    }
    d = {'sample_id': 'PART-MATCH-001', 'version': '1.0.0-candidate', 'status': 'pending_user_review',
         'sources': sources, 'clock': {'source_base': BASE, 'observation': AT},
         'overlay': '书信样本所有时间从原基准整体平移到2027-05-16基准；游园不改。只改变运行副本时间，原样本保持不变。观察在报名开放后一小时。',
         'world': {'V': '集中回信，2027-05-23 14至16点，8个审核名额；必须全程。',
                   'A': '小满游园，2027-05-23 12至17点开放，60个直接名额；允许自由到场。'},
         'profiles': people, 'pairs': pairs, 'natural_messages': messages,
         'explanation_message': '请根据我已保存的偏好，查询并解释适合我的参与机会和需要核对的条件。请引用当前记录，不要替我报名。',
         'labels': {'recommend': '方向相关且已知时间可参与，推荐不代表资格获官方认证。',
                    'conditional': '可列为需核对的候选，不保证能完成服务、体验或认定。',
                    'exclude': '该用户在当前业务状态和偏好下不应收到此招募推荐。'},
         'evaluation': {'oracle': '依据活动规则和独立人工场景判断；不调用当前matching函数产生标签。',
                        'binary_metrics': 'recommend和conditional合为应展示候选，计算24对的precision/recall；另逐项检查conditional提示。不对两个候选计算NDCG或宣称大规模排序质量。',
                        'natural_extraction': '检查一次性时段、类型、提醒意愿、原话支持、无擅自增加技能；只在忠实核对后模拟用户独立确认。',
                        'lifecycle': '发布触达、本人过滤、去重、重启、忽略、关闭提醒、报名和退出、满额和释放、取消、截止。',
                        'acceptance': '规格、产品运行结果和用户接受分别记录；不改变金标准迎合当前算法。'},
         'operator': 'Codex执行固定合成人物和模拟用户确认，仅写入独立实验库；不代表真实学生试用。',
         'split': '公开开发集；12个人物共享两个活动原型，不当作24个独立活动或未见测试样本。'}
    SPEC.mkdir(parents=True)
    save(SPEC / 'gold.json', d)
    print('specification authored; write REVIEW.md then freeze before running', flush=True)


def activity_fields(spec):
    v = copy.deepcopy(read(ROOT / spec['sources'][0]['path'])['gold_plan']['fields'])
    a = copy.deepcopy(read(ROOT / spec['sources'][1]['path'])['gold_plan']['fields'])
    old_base = datetime.fromisoformat(read(ROOT / spec['sources'][0]['path'])['clock']['base_at'])
    delta = datetime.fromisoformat(BASE) - old_base
    for item in [v, *v['jobs']]:
        for key in ('starts_at', 'ends_at', 'opens_at', 'closes_at'):
            if key in item:
                item[key] = (datetime.fromisoformat(item[key]) + delta).isoformat()
    return {'V': v, 'A': a}


def app_for(directory, clock=None, backend=None):
    at = datetime.fromisoformat(AT)
    app = create_app(directory / 'world.sqlite3', business_clock=clock or (lambda: at),
                     guide_backend_factory=backend, enable_semantics=False)
    app.state.task_service.initialize()
    return app


def user(app, name):
    return app.state.auth_service.register(name.lower(), name, secrets.token_urlsafe(24))[1]


def publish(app, fields, owner):
    v = app.state.volunteer_service.create(VolunteerCreate.model_validate(fields['V']), owner.id)
    a = app.state.activity_service.create(ActivityCreate.model_validate(fields['A']), owner.id)
    return {'V': v['id'], 'A': a['id'], 'V_job': v['jobs'][0]['id']}


def notice_count(app, uid):
    with app.state.task_service.database.connect() as c:
        return c.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'", (uid,)).fetchone()[0]


def opportunities(app, uid, ids):
    items = app.state.guide_service.matching.list(uid, 100)['items']
    return {k: next((x for x in items if x['resource_id'] == ids[k]), None) for k in ('V', 'A')}


def evaluate_snapshot(app, spec, state, label):
    rows = []
    for pair in spec['pairs']:
        uid = state['users'][pair['profile']]['id']
        actual = opportunities(app, uid, state['ids'])[pair['opportunity']]
        want = pair['label'] != 'exclude'
        rows.append(pair | {'actual_present': actual is not None, 'agrees_on_presence': want == (actual is not None),
                            'actual_item': actual, 'conditional_hint_review': '需人工核对提示是否充分' if pair['label'] == 'conditional' and actual else None})
    tp = sum(r['label'] != 'exclude' and r['actual_present'] for r in rows)
    fp = sum(r['label'] == 'exclude' and r['actual_present'] for r in rows)
    fn = sum(r['label'] != 'exclude' and not r['actual_present'] for r in rows)
    return {'mode': label, 'pairs': rows, 'presence_agreements': sum(r['agrees_on_presence'] for r in rows),
            'pair_count': len(rows), 'true_positive': tp, 'false_positive': fp, 'false_negative': fn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'opportunity_notifications': {k: notice_count(app, v['id']) for k, v in state['users'].items()},
            'numeric_scores_are_probabilities': False}


def matrix(directory):
    spec = verify_spec()
    if directory.exists():
        raise ValueError('Use a new output directory')
    directory.mkdir(parents=True)
    save(directory / 'source-spec.json', spec)
    save(directory / 'source-manifest.json', read(SPEC / 'manifest.json'))
    with business_time(lambda: datetime.fromisoformat(AT)):
        app = app_for(directory)
        owner = user(app, 'organizer')
        state = {'sample_id': spec['sample_id'], 'version': spec['version'], 'users': {}, 'owner': owner.model_dump(mode='json'),
                 'spec_manifest_sha256': sha(SPEC / 'manifest.json'), 'runner_sha256': sha(Path(__file__)),
                 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 'working_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--'], cwd=ROOT)).hexdigest()}
        for p in spec['profiles']:
            u = user(app, p['id'])
            state['users'][p['id']] = u.model_dump(mode='json')
            app.state.guide_service.assistance.save_preferences(u.id, p['fields'], 0)
        fields = activity_fields(spec)
        state['ids'] = publish(app, fields, owner)
        save(directory / 'world-inputs.json', fields)
        app.state.volunteer_service.register(state['ids']['V_job'], state['users']['P07']['id'], '模拟参与者已申请且能全程参加。')
        app.state.guide_service.matching.semantics = None
        app.state.guide_service.matching.reconcile()
        report = evaluate_snapshot(app, spec, state, 'native_keyword_fallback')
        save(directory / 'world.json', state)
        save(directory / 'keyword-results.json', report)
    print(json.dumps({k: report[k] for k in ('mode', 'presence_agreements', 'pair_count', 'precision', 'recall')}, ensure_ascii=False), flush=True)


def open_world(directory):
    spec = verify_spec()
    state = read(directory / 'world.json')
    assert state['spec_manifest_sha256'] == sha(SPEC / 'manifest.json')
    assert state['runner_sha256'] == sha(Path(__file__)), 'Runner changed during experiment'
    return spec, state, app_for(directory)


def semantics(directory):
    with business_time(lambda: datetime.fromisoformat(AT)):
        spec, state, app = open_world(directory)
        sem = app.state.guide_service.semantics
        sem.sync_sources()
    def drain():
        with business_time(lambda: datetime.fromisoformat(AT)):
            while sem.process_one():
                with app.state.task_service.database.connect() as c:
                    counts = {r['status']: r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM semantic_jobs GROUP BY status')}
                print(json.dumps({'semantic_jobs': counts}, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(drain), pool.submit(drain)]:
            future.result()
    with business_time(lambda: datetime.fromisoformat(AT)):
        app.state.guide_service.matching.reconcile()
        report = evaluate_snapshot(app, spec, state, 'real_semantic_cache_with_explicit_fallback_if_unavailable')
        with app.state.task_service.database.connect() as c:
            report['semantic_jobs'] = [dict(r) for r in c.execute('SELECT kind,resource_id,status,attempts,error FROM semantic_jobs')]
        save(directory / 'semantic-results.json', report)
    print(json.dumps({k: report[k] for k in ('mode', 'presence_agreements', 'pair_count', 'precision', 'recall')}, ensure_ascii=False), flush=True)


def lifecycle(directory):
    spec = verify_spec()
    target = directory / 'lifecycle'
    if target.exists():
        raise ValueError('Lifecycle output already exists')
    target.mkdir(parents=True)
    now = [datetime.fromisoformat(AT)]
    checks = []
    with business_time(lambda: now[0]):
        app = app_for(target, lambda: now[0]);g = app.state.guide_service
        owner, pv, pa = (user(app, n) for n in ('owner', 'volunteer', 'visitor'))
        profiles = {p['id']: p['fields'] for p in spec['profiles']}
        for u, fields in ((pv, profiles['P01']), (pa, profiles['P02']), (owner, profiles['P09'])):
            g.assistance.save_preferences(u.id, fields, 0)
        g.matching.reconcile()
        empty = g.matching.list(pv.id)['total'] == 0
        ids = publish(app, activity_fields(spec), owner)
        def check(name, ok):
            checks.append({'name': name, 'passed': bool(ok)})
            save(target / 'results.json', {'checks': checks})
        check('L01 发布前没有机会', empty)
        g.matching.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not g.matching.list(pa.id)['total']:
            time.sleep(.05)
        g.matching.stop()
        check('L02 无聊天后台扫描触达且不推荐本人活动', bool(opportunities(app, pv.id, ids)['V']) and bool(opportunities(app, pa.id, ids)['A']) and g.matching.list(owner.id)['total'] == 0)
        before = {u.id: notice_count(app, u.id) for u in (pv, pa)}
        for _ in range(3):g.matching.reconcile()
        check('L03 重复扫描提醒去重', before == {u.id: notice_count(app, u.id) for u in (pv, pa)})
        app = app_for(target, lambda: now[0]);g = app.state.guide_service;g.matching.reconcile()
        check('L04 重启保留推荐且不重复提醒', before == {u.id: notice_count(app, u.id) for u in (pv, pa)} and bool(opportunities(app, pa.id, ids)['A']))
        item = opportunities(app, pa.id, ids)['A'];g.matching.dismiss(pa.id, item['id']);g.matching.reconcile()
        check('L05 主动忽略后不恢复推荐', not opportunities(app, pa.id, ids)['A'])
        off = copy.deepcopy(profiles['P02']);off['notifications_enabled'] = False
        g.assistance.save_preferences(pa.id, off, 1)
        extra = activity_fields(spec)['A'];extra['title'] = '小满游园追加模拟场（生命周期对照）'
        new = app.state.activity_service.create(ActivityCreate.model_validate(extra), owner.id)
        g.matching.reconcile()
        check('L06 关闭提醒仍显示新机会且无新机会消息', any(i['resource_id'] == new['id'] for i in g.matching.list(pa.id)['items']) and notice_count(app, pa.id) == before[pa.id])
        reg = app.state.volunteer_service.register(ids['V_job'], pv.id, '可全程参加，申请模拟书信服务。');g.matching.reconcile()
        check('L07 有效待审核报名使原招募失效', reg['status'] == 'pending' and not opportunities(app, pv.id, ids)['V'])
        app.state.volunteer_service.cancel_registration(reg['id'], pv.id);g.matching.reconcile()
        check('L08 退出可重新出现但不重复提醒', bool(opportunities(app, pv.id, ids)['V']) and notice_count(app, pv.id) == before[pv.id])
        occupied = []
        for i in range(8):
            u = user(app, f'fill{i}')
            r = app.state.volunteer_service.register(ids['V_job'], u.id, '全程参加。')
            app.state.volunteer_service.review(r['id'], owner.id, RegistrationReview(decision='approve'))
            occupied.append((u, r))
        g.matching.reconcile()
        check('L09 岗位满额后推荐失效', not opportunities(app, pv.id, ids)['V'])
        u, r = occupied[0];app.state.volunteer_service.cancel_registration(r['id'], u.id);g.matching.reconcile()
        check('L10 释放名额后恢复且提醒去重', bool(opportunities(app, pv.id, ids)['V']) and notice_count(app, pv.id) == before[pv.id])
        app.state.activity_service.cancel_activity(new['id'], owner.id, '模拟活动取消。');g.matching.reconcile()
        check('L11 取消使新机会失效', not any(i['resource_id'] == new['id'] for i in g.matching.list(pa.id)['items']))
        now[0] = datetime.fromisoformat('2027-05-22T18:00:00+08:00');g.matching.reconcile()
        check('L12 截止瞬间不再推荐', g.matching.list(pv.id)['total'] == 0 and g.matching.list(pa.id)['total'] == 0)
    result = {'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks), 'model_calls': 0,
              'note': '真实业务服务及后台扫描；仅生命周期独立库多创建一场衍生活动，不计入主世界两场活动。'}
    save(target / 'results.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def proposal_checks(expected, proposal):
    if not proposal:return {'proposal_exists': False}
    actual = proposal['fields'];text = lambda k: ' '.join(actual.get(k, []))
    times = lambda values: [(datetime.fromisoformat(x['starts_at']), datetime.fromisoformat(x['ends_at'])) for x in values]
    return {'proposal_exists': True,
            'one_time_exact': times(actual.get('available_slots', [])) == times(expected['available_slots']),
            'no_weekly_invention': not actual.get('weekly_slots'),
            'types_exact': set(actual['content_types']) == set(expected['content_types']),
            'reminder_intent': actual['notifications_enabled'] == expected['notifications_enabled'],
            'interests_retained': all(x in text('interests') for x in expected['interests']),
            'no_interest_invention': all(all(part in ' '.join(expected['interests']) for part in [x]) for x in actual.get('interests', [])),
            'skills_retained_without_invention': (not actual.get('skills') if not expected['skills'] else all(x in text('skills') for x in expected['skills']) and all(x in ' '.join(expected['skills']) for x in actual.get('skills', []))),
            'locations_exact': actual['locations'] == expected['locations'],
            'no_unrequested_expiry_or_exclusion': actual.get('valid_until') is None and not actual.get('unavailable_slots') and not actual.get('semantic_exclusions')}


def dialogue(directory, pid):
    spec, state, app = open_world(directory)
    if pid not in spec['natural_messages']:raise ValueError('No authored dialogue for this profile')
    target = directory / ('dialogue-' + pid)
    if target.exists():raise ValueError('Do not overwrite an attempted dialogue')
    target.mkdir()
    calls = []
    guide = app.state.guide_service
    guide.backend_factory = lambda: ObservedBackend(model_backend(), calls)
    expected = next(p['fields'] for p in spec['profiles'] if p['id'] == pid)
    u = user(app, 'live.' + pid)
    report = {'sample_id': spec['sample_id'], 'profile': pid, 'user': u.model_dump(mode='json'), 'mode': 'real_model', 'messages': [], 'score': None}
    def chat(message, cid=None):
        row = {'user_message': message};report['messages'].append(row);save(target / 'result.json', report)
        start = time.monotonic()
        try:
            reply = guide.chat(GuideInput(message=message, conversation_id=cid), u)
            row.update(answer=reply.answer, result=reply.model_dump(mode='json'), trace=guide.runs.read(reply.run_id, u.id), status='succeeded')
            return reply
        finally:
            row['seconds'] = round(time.monotonic() - start, 3)
            report['model_calls'] = calls
            save(target / 'result.json', report)
    with business_time(lambda: datetime.fromisoformat(AT)):
        try:
            r = chat(spec['natural_messages'][pid]);a = guide.assistance.read(r.conversation_id, u.id)
            proposal = (a or {}).get('preference_proposal')
            checks = proposal_checks(expected, proposal)
            checks['not_saved_before_confirmation'] = guide.assistance.preferences(u.id)['version'] == 0
            checks['no_reminder_before_confirmation'] = notice_count(app, u.id) == 0
            report['preference_checks'] = checks
            if all(checks.values()):
                guide.assistance.action(r.conversation_id, u.id, a['version'], 'preferences', 0)
                report['confirmation'] = '模拟参与者核对忠实后，通过独立偏好确认服务保存；不是模型自行授权。'
                guide.semantics.sync_sources()
                # Process only this newly confirmed profile, not retries from earlier phases.
                from campus.semantics import profile_source
                key = guide.semantics.key('profile', u.id, profile_source(proposal['fields']))[0]
                with app.state.task_service.database.connect() as c:
                    # Existing retry jobs may be due: leave their scheduling intact.
                    report['new_profile_semantic_key'] = key
                for _ in range(4):
                    with app.state.task_service.database.connect() as c:
                        status = c.execute('SELECT status FROM semantic_jobs WHERE key=?', (key,)).fetchone()['status']
                    if status in ('ready', 'retry', 'failed'):break
                    if not guide.semantics.process_one():break
                guide.matching.reconcile(u.id)
                report['saved_preferences'] = guide.assistance.preferences(u.id)
                report['recommendations'] = guide.matching.list(u.id)
                report['notifications'] = notice_count(app, u.id)
                chat(spec['explanation_message'], r.conversation_id)
            else:
                report['confirmation'] = '偏好提议未通过忠实性检查，保留原结果，不自动修正或确认。'
            report['status'] = 'collected_pending_review'
        except Exception as exc:
            report.update(status='interrupted_requires_classification', error_type=type(exc).__name__, error=str(exc))
            report['recent_runs'] = guide.runs.recent(u.id)
        finally:
            guide.shutdown()
            report['model_calls'] = calls
            save(target / 'result.json', report)
    lines = [f'# {pid} 偏好登记与推荐解释真实对话', '']
    for i, row in enumerate(report['messages'], 1):
        lines += [f'## 第{i}轮', '', '**参与者**', '', row['user_message'], '', '**引航员原文**', '', row.get('answer', '本轮中断，见JSON。'), '']
    (target / 'transcript.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'profile': pid, 'status': report['status'], 'checks': report.get('preference_checks'),
                      'recommendations': (report.get('recommendations') or {}).get('total'), 'error': report.get('error')}, ensure_ascii=False), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['spec', 'matrix', 'semantics', 'lifecycle', 'dialogue'])
    p.add_argument('--directory', type=Path)
    p.add_argument('--profile', choices=['P01', 'P02', 'P04'])
    args = p.parse_args()
    if args.action == 'spec':return make_spec()
    if not args.directory:p.error('--directory is required')
    directory = args.directory.resolve()
    if args.action == 'dialogue':
        if not args.profile:p.error('--profile is required')
        return dialogue(directory, args.profile)
    return globals()[args.action](directory)


if __name__ == '__main__':
    main()
