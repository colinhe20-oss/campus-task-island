"""Run authored volunteer participant cases through the native matching service."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path

from campus.app import create_app
from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate
from campus.clock import business_time

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {'EXP-V01', 'EXP-V02'}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def run(sample_id: str, target: Path):
    if sample_id not in SUPPORTED:
        raise ValueError(f'Native matching matrix currently supports: {sorted(SUPPORTED)}')
    spec_dir = ROOT / 'docs/dataset_samples' / sample_id
    manifest = load(spec_dir / 'manifest.json')
    for name, expected in manifest['files'].items():
        if sha(spec_dir / name) != expected:
            raise ValueError(f'Frozen sample hash mismatch: {name}')
    gold, cases = load(spec_dir / 'gold.json'), load(spec_dir / 'participant_cases.json')
    if target.exists():
        raise ValueError('Output directory already exists; use a new collection ID')
    target.mkdir(parents=True)
    at = datetime.fromisoformat('2026-10-20T10:00:00+08:00')
    with business_time(lambda: at):
        app = create_app(target / 'world.sqlite3', business_clock=lambda: at, enable_semantics=False)
        app.state.task_service.initialize()
        owner = app.state.auth_service.register('matrix-owner', 'matrix-owner', secrets.token_urlsafe(24))[1]
        cfg = cases['native_opportunity']
        jobs = [{'name': j['name'], 'description': cfg['description'],
                 'requirements': '完整参加自己选择的班次；活动方需人工核对跨岗位重复申请。',
                 'location': cfg['location'], 'starts_at': f"{cfg['date']}T{j['starts_at']}:00+08:00",
                 'ends_at': f"{cfg['date']}T{j['ends_at']}:00+08:00", 'capacity': j['capacity'],
                 'estimated_minutes': j['minutes'],
                 'estimated_hours_description': f"预计{j['minutes']}分钟；具体记录以活动方核验为准。"}
                for j in cfg['jobs']]
        body = VolunteerCreate.model_validate({
            'title': cfg['title'], 'description': cfg['description'],
            'organization_name': cfg['organization_name'], 'information_source': cfg['information_source'],
            'contact': cfg['contact'], 'recognition_conditions': cfg['recognition_conditions'],
            'starts_at': min(j['starts_at'] for j in jobs), 'ends_at': max(j['ends_at'] for j in jobs),
            'opens_at': cfg['opens_at'], 'closes_at': cfg['closes_at'],
            'registration_mode': cfg['registration_mode'], 'jobs': jobs})
        opportunity = app.state.volunteer_service.create(body, owner.id)
        users = {}
        for profile in cases['profiles']:
            user = app.state.auth_service.register(profile['id'].lower(), profile['id'], secrets.token_urlsafe(24))[1]
            users[profile['id']] = user
            fields = Preferences.model_validate(profile['native_preferences']).model_dump(mode='json')
            app.state.guide_service.assistance.save_preferences(user.id, fields, 0)
        pending = cases.get('pending_registration', {})
        if pending:
            applicant = users[pending['profile']]
            job = next(j for j in opportunity['jobs'] if cases['opportunity_id'][pending['opportunity']] in j['name'])
            app.state.volunteer_service.register(job['id'], applicant.id, '模拟已提交对应班次申请。')
        app.state.guide_service.matching.reconcile()
        expected_opps = {key: next(j for j in opportunity['jobs'] if value in j['name'])
                         for key, value in cases['opportunity_id'].items()}
        rows = []
        for profile in cases['profiles']:
            actual_items = app.state.guide_service.matching.list(users[profile['id']].id, 100)['items']
            actual_jobs = {item.get('job_id') for item in actual_items}
            for key, label in profile['expected'].items():
                jid = expected_opps[key]['id']
                present = jid in actual_jobs
                expected_present = label != 'exclude'
                rows.append({'profile': profile['id'], 'opportunity': key, 'expected': label,
                             'actual_present': present, 'presence_agrees': present == expected_present,
                             'actual_item': next((i for i in actual_items if i.get('job_id') == jid), None)})
        result = {'sample_id': sample_id, 'mode': 'native_keyword_matching', 'observation_time': at.isoformat(),
                  'profile_count': len(cases['profiles']), 'opportunity_count': 2, 'pair_count': len(rows),
                  'agreements': sum(x['presence_agrees'] for x in rows),
                  'true_positive': sum(x['expected'] != 'exclude' and x['actual_present'] for x in rows),
                  'false_positive': sum(x['expected'] == 'exclude' and x['actual_present'] for x in rows),
                  'false_negative': sum(x['expected'] != 'exclude' and not x['actual_present'] for x in rows),
                  'rows': rows, 'published_opportunity_id': opportunity['id'],
                  'published_job_ids': {k: v['id'] for k, v in expected_opps.items()},
                  'semantic_mode': 'disabled; keyword fallback explicitly selected',
                  'registration_created_only_for': pending or None,
                  'user_registration_side_effects': 'synthetic isolated world only'}
        tp, fp = result['true_positive'], result['false_positive']
        fn = result['false_negative']
        result['accuracy'] = result['agreements'] / len(rows) if rows else None
        result['precision'] = tp / (tp + fp) if tp + fp else None
        result['recall'] = tp / (tp + fn) if tp + fn else None
        result['runner_sha256'] = sha(Path(__file__))
        save(target / 'results.json', result)
        save(target / 'inputs.json', {'gold_sha256': sha(spec_dir / 'gold.json'),
                                     'participant_cases_sha256': sha(spec_dir / 'participant_cases.json'),
                                     'users': {k: v.id for k, v in users.items()},
                                     'opportunity': opportunity})
    print(json.dumps({k: result[k] for k in ('sample_id','mode','pair_count','agreements','true_positive','false_positive','false_negative')}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    run(args.sample, args.directory.resolve())


if __name__ == '__main__':
    main()
