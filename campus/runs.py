"""持久化运行摘要与可重连事件；不记录模型推理、密钥、工具参数或原始结果。"""
from __future__ import annotations

import json
import threading
import time
from uuid import uuid4

from agent.loop import RunCancelled
from .errors import AppError
from .service import now

TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted'}


class RunControl:
    def __init__(self, run_id):
        self.id = run_id
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.committed = False

    def check(self):
        if self.cancel.is_set():
            raise RunCancelled('本次运行已取消，未保存本轮对话或草稿')


class RunStore:
    def __init__(self, database):
        self.database = database

    def recover(self):
        with self.database.connect() as conn:
            conn.execute("UPDATE guide_runs SET status='interrupted',finished_at=?,error=? WHERE status IN ('running','cancelling')",
                         (now(), '服务重启中断了本次运行，请查看最新草稿后重试'))

    def create(self, user_id, conversation_id):
        run_id = uuid4().hex
        with self.database.connect() as conn:
            conn.execute('INSERT INTO guide_runs(id,user_id,conversation_id,status,started_at) VALUES(?,?,?,?,?)',
                         (run_id, user_id, conversation_id, 'running', now()))
        return RunControl(run_id)

    def model(self, run_id, name):
        with self.database.connect() as conn:
            conn.execute('UPDATE guide_runs SET model=? WHERE id=?', (name, run_id))

    def event(self, run_id, kind, data):
        # 明确白名单；上游的 run_started.task / tool.arguments / tool.result 不落盘。
        allowed = {'model_started': ('step',), 'model_finished': ('step','duration_ms'),
                   'tool_started': ('step','tool'), 'tool_finished': ('step','tool','success','duration_ms','error_type'),
                   'text_delta': ('step','text')}
        if kind not in allowed:
            return
        item = {'kind': kind, **{k: data[k] for k in allowed[kind] if k in data}}
        with self.database.connect() as conn:
            row = conn.execute('SELECT events,metrics FROM guide_runs WHERE id=?', (run_id,)).fetchone()
            events, metrics = json.loads(row['events']), json.loads(row['metrics'])
            if kind == 'model_started':
                metrics['model_calls'] = metrics.get('model_calls', 0)+1
            if kind == 'model_finished':
                usage = data.get('usage') or {}
                if isinstance(usage.get('total_tokens'), int):
                    metrics['usage_rounds'] = metrics.get('usage_rounds', 0)+1
                    for key in ('prompt_tokens','completion_tokens','total_tokens'):
                        if isinstance(usage.get(key),int) and usage[key]>=0:
                            metrics[key] = metrics.get(key, 0)+usage[key]
                metrics['model_duration_ms'] = metrics.get('model_duration_ms',0)+data['duration_ms']
            if kind == 'tool_finished':
                metrics['tool_calls'] = metrics.get('tool_calls',0)+1
                metrics['tool_errors'] = metrics.get('tool_errors',0)+int(not data['success'])
            item.update(seq=len(events)+1, at=now())
            events.append(item)
            conn.execute('UPDATE guide_runs SET events=?,metrics=? WHERE id=?',
                         (json.dumps(events,ensure_ascii=False),json.dumps(metrics),run_id))

    def finish(self, control, started, *, reply=None, error=None, status='succeeded'):
        with control.lock:
            if reply:
                reply.run_id = control.id
            with self.database.connect() as conn:
                conn.execute('UPDATE guide_runs SET status=?,finished_at=?,duration_ms=?,result=?,error=?,conversation_id=COALESCE(?,conversation_id) WHERE id=?',
                             (status,now(),round((time.monotonic()-started)*1000),
                              reply.model_dump_json() if reply else None,error,
                              reply.conversation_id if reply else None,control.id))

    def read(self, run_id, user_id):
        with self.database.connect() as conn:
            row = conn.execute('SELECT * FROM guide_runs WHERE id=? AND user_id=?', (run_id,user_id)).fetchone()
        if not row:
            raise AppError('运行记录不存在或不属于当前用户',404)
        item = dict(row)
        item.pop('user_id')
        for key in ('metrics','events','result'):
            item[key] = json.loads(item[key]) if item[key] else None
        metrics = item['metrics']
        metrics['usage_complete'] = bool(metrics.get('model_calls')) and metrics.get('model_calls')==metrics.get('usage_rounds')
        return item

    def recent(self, user_id):
        with self.database.connect() as conn:
            ids = [row['id'] for row in conn.execute('SELECT id FROM guide_runs WHERE user_id=? ORDER BY started_at DESC,id DESC LIMIT 20', (user_id,))]
        return [{k:v for k,v in self.read(i,user_id).items() if k not in ('events','result')} for i in ids]
