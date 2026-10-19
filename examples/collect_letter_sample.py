"""Collect one real, operator-guided sample without changing its frozen gold data.

Run each turn separately, inspecting the answer before selecting disclosure cards.
No gold answer or evaluator instructions are sent to the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from campus.app import create_app
from campus.clock import business_time
from campus.guide import model_backend
from campus.schemas import GuideInput, UserRead

ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = ROOT / 'docs/dataset_samples'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def snapshot_sources(spec_directory, directory, manifest, working_diff):
    """Keep evaluator-only replay sources; none are sent to the tested model."""
    source_root = spec_directory.resolve()
    names = (*manifest['files'], 'manifest.json')
    if any(Path(name).is_absolute() or '..' in Path(name).parts for name in names):
        raise ValueError('源清单文件必须在样本目录内')
    snapshot = directory / 'frozen-spec'
    snapshot.mkdir()
    for name in names:
        source = (source_root / name).resolve()
        relative_source = source.relative_to(source_root)
        destination = snapshot / relative_source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    (directory / 'collector-source.py').write_bytes(Path(__file__).read_bytes())
    (directory / 'source-working-diff.patch').write_bytes(working_diff)
    return {'spec_directory': 'frozen-spec', 'collector_source': 'collector-source.py',
            'tracked_working_diff': 'source-working-diff.patch', 'visibility': 'evaluator_only'}


def counts(database):
    with database.connect() as conn:
        return {name: conn.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                for name in ('tasks', 'activities', 'volunteer_activities', 'discoveries')}


def transcript(directory, rows, sample_id):
    lines = [f'# {sample_id} 首轮实际对话', '', '真实模型运行；组织者回复由执行者按已冻结的信息卡选择。', '']
    for row in rows:
        lines += [f"## 第{row['turn']}轮", '', '**组织者**', '', row['user_message'], '',
                  '**引航员（原文）**', '', row.get('answer') or '本轮运行失败，见JSON记录。', '',
                  f"卡片：{', '.join(row['cards']) or '无'}；耗时：{row['seconds']}秒。", '']
    (directory / 'transcript.md').write_text('\n'.join(lines), encoding='utf-8')


class ObservedBackend:
    """Keep model behavior unchanged; record configuration and context digests only."""
    def __init__(self, backend, observations):
        self.backend = backend
        self.model = backend.model
        self.guide_run_timeout = backend.guide_run_timeout
        self.observations = observations

    def request_budget(self, seconds):
        return self.backend.request_budget(seconds)

    def chat(self, messages, tools=None, **kwargs):
        self.observations.append({
            'model': self.model,
            'endpoint_sha256': digest(self.backend.base_url.encode()),
            'temperature': kwargs.get('temperature', 0.0),
            'request_timeout_seconds': self.backend.request_timeout,
            'run_timeout_seconds': self.guide_run_timeout,
            'system_prompt_sha256': digest(json.dumps(
                [m for m in messages if m['role'] == 'system'], ensure_ascii=False, sort_keys=True).encode()),
            'tool_schema_sha256': digest(json.dumps(tools, ensure_ascii=False, sort_keys=True).encode()),
            'tool_names': [t['function']['name'] for t in tools or []],
            'message_count': len(messages),
        })
        return self.backend.chat(messages, tools=tools, **kwargs)

    def close(self):
        self.backend.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['begin', 'step'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--sample', default='VOL-LETTER-001')
    parser.add_argument('--cards', nargs='*', default=[])
    parser.add_argument('--reason', default='首句，无底稿披露')
    parser.add_argument('--unknown', action='store_true')
    parser.add_argument('--unknown-topic')
    parser.add_argument('--reject', action='store_true')
    parser.add_argument('--finish', action='store_true')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)*', args.sample):
        raise ValueError('无效样本编号')
    spec_directory = SPEC_ROOT / args.sample
    directory = args.directory.resolve()
    manifest = json.loads((spec_directory / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if digest((spec_directory / name).read_bytes()) != expected:
            raise ValueError('冻结样本摘要不一致：' + name)
    spec = json.loads((spec_directory / 'gold.json').read_text(encoding='utf-8'))
    if args.unknown and spec['user_simulation'].get('require_unknown_topic') and not args.unknown_topic:
        raise ValueError('未知回复必须明确指出尚未确定的事项')
    if args.action == 'begin':
        if directory.exists():
            raise ValueError('首轮采集必须使用不存在的新目录')
        if args.cards or args.finish or args.unknown or args.reject:
            raise ValueError('首轮只能发送原始首句')
        # Validate configuration before creating any run artifacts; never print keys.
        probe = model_backend()
        model_name = probe.model
        probe.close()
        directory.mkdir(parents=True)
        diff = subprocess.run(['git', 'diff', 'HEAD', '--'], cwd=ROOT, capture_output=True, check=True).stdout
        source_snapshot = snapshot_sources(spec_directory, directory, manifest, diff)
        state = {
            'collection_id': directory.name, 'sample_id': spec['sample_id'], 'version': spec['version'],
            'started_at': stamp(), 'status': 'collecting', 'model': model_name,
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'tracked_working_diff_sha256': digest(diff),
            'collector_sha256': digest(Path(__file__).read_bytes()),
            'source_snapshot': source_snapshot,
            'spec_manifest_sha256': digest((spec_directory / 'manifest.json').read_bytes()),
            'business_clock': spec['clock'], 'transport': 'GuideService.chat (sync, existing product path)',
            'semantic_background_worker': 'not_started', 'operator': 'Codex acting as fixed-card operator',
            'protocol_deviation': spec['environment'].get('operator_note', '执行者为Codex，按卡片操作；并非独立人类测试员，需审核卡片选择。'),
            'conversation_id': None, 'disclosed_cards': [], 'turns': [],
        }
    else:
        state = json.loads((directory / 'collection.json').read_text(encoding='utf-8'))
        if state['status'] != 'collecting':
            raise ValueError('采集已结束；保留原记录，不能续写或覆盖')
        if state['sample_id'] != args.sample:
            raise ValueError('运行与样本编号不一致')
        if state['spec_manifest_sha256'] != digest((spec_directory / 'manifest.json').read_bytes()):
            raise ValueError('采集中途不可更换样本版本')
        if state['collector_sha256'] != digest(Path(__file__).read_bytes()):
            raise ValueError('采集中途不可更换采集器')
    if len(state['turns']) >= spec['user_simulation']['max_agent_responses']:
        raise ValueError('达到协议轮数上限')
    cards = {c['id']: c for c in spec['user_simulation']['cards']}
    selected = sorted(set(args.cards))
    if not set(selected) <= cards.keys():
        raise ValueError('未知卡片编号')
    if args.action == 'step' and not (selected or args.finish or args.unknown or args.reject):
        raise ValueError('后续轮需要指定卡片或协议回复')
    disclosed = sorted(set(state['disclosed_cards']) | set(selected))
    if args.finish and set(disclosed) != cards.keys():
        raise ValueError('所有卡片披露后才能请求最终整理')
    parts = []
    if args.reject:
        parts.append(spec['user_simulation'].get('rejection_reply', '这部分请按我提供的安排保留，建议可以单独列出。'))
    parts.extend(cards[c]['reply'] for c in selected)
    if args.unknown:
        parts.append(spec['user_simulation']['unknown_reply'].replace('{topic}', args.unknown_topic or '这点'))
    if args.finish:
        parts.append(spec['user_simulation']['final_user_message'])
    message = spec['initial_message'] if args.action == 'begin' else '\n\n'.join(parts)
    at = datetime.fromisoformat(spec['clock']['base_at'])
    observations = []
    factory = lambda: ObservedBackend(model_backend(), observations)
    app = create_app(directory / 'experiment.sqlite3', guide_backend_factory=factory,
                     business_clock=lambda: at, enable_semantics=False)
    service, auth, guide = app.state.task_service, app.state.auth_service, app.state.guide_service
    with business_time(lambda: at):
        service.initialize()
        if args.action == 'begin':
            _, user = auth.register('sample.organizer', spec['environment'].get('organizer_display_name', '书信活动组织者'), secrets.token_urlsafe(24))
            state['user'] = user.model_dump(mode='json')
            state['initial_counts'] = counts(service.database)
        user = UserRead.model_validate(state['user'])
        row = {'turn': len(state['turns']) + 1, 'user_message': message, 'cards': selected,
               'operator_reason': args.reason, 'disclosed_before': state['disclosed_cards'],
               'finish_requested': args.finish, 'unknown_topic': args.unknown_topic, 'started_at': stamp()}
        # Record the attempted input before any remote call, including on interruption.
        save(directory / f"turn-{row['turn']:02d}-input.json", row)
        save(directory / 'collection.json', state)
        started = time.monotonic()
        try:
            result = guide.chat(GuideInput(message=message, conversation_id=state['conversation_id']), user)
            row.update(result=result.model_dump(mode='json'), answer=result.answer, status='succeeded')
            state['conversation_id'] = result.conversation_id
            row['trace'] = guide.runs.read(result.run_id, user.id)
            row['persisted_assistance'] = guide.assistance.read(result.conversation_id, user.id)
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__, error=str(exc))
            row['recent_runs'] = guide.runs.recent(user.id)
            if state['conversation_id']:
                row['persisted_assistance'] = guide.assistance.read(state['conversation_id'], user.id)
            state['status'] = 'interrupted_requires_classification'
        finally:
            guide.shutdown()
        row.update(seconds=round(time.monotonic() - started, 3), finished_at=stamp(),
                   model_calls=observations, business_counts=counts(service.database))
    state['disclosed_cards'] = disclosed
    state['turns'].append(row)
    if state['status'] == 'collecting' and (args.finish or len(state['turns']) == 8):
        state['status'] = 'collected_pending_scoring'
    state['last_updated_at'] = stamp()
    save(directory / f"turn-{row['turn']:02d}.json", row)
    save(directory / 'collection.json', state)
    transcript(directory, state['turns'], spec['sample_id'])
    plan = (row.get('persisted_assistance') or {}).get('plan') or {}
    print(json.dumps({'turn': row['turn'], 'status': row['status'], 'seconds': row['seconds'],
                      'answer': row.get('answer'), 'error': row.get('error'),
                      'plan': plan, 'counts': row['business_counts'],
                      'disclosed': disclosed}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
