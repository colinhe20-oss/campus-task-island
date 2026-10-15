"""普通任务约定、延期和双方线下结算记录。所有写入与通知在同一事务。"""
import json
from datetime import datetime, timezone
from uuid import uuid4
from .errors import AppError
from .notifications import emit

STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS task_deadline_history (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), actor_id TEXT NOT NULL REFERENCES users(id),
        old_deadline TEXT, new_deadline TEXT NOT NULL, reason TEXT NOT NULL, version INTEGER NOT NULL,
        extension_id TEXT, created_at TEXT NOT NULL, UNIQUE(task_id,version))''',
    '''CREATE TABLE IF NOT EXISTS task_extensions (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), requester_id TEXT NOT NULL REFERENCES users(id),
        old_deadline TEXT, new_deadline TEXT NOT NULL, reason TEXT NOT NULL, terms_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled','closed')),
        version INTEGER NOT NULL DEFAULT 1, review_reason TEXT NOT NULL DEFAULT '', reviewed_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    "CREATE UNIQUE INDEX IF NOT EXISTS one_pending_extension ON task_extensions(task_id) WHERE status='pending'",
    '''CREATE TABLE IF NOT EXISTS task_settlements (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id), payer_confirmed INTEGER NOT NULL DEFAULT 0,
        payee_confirmed INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS task_settlement_history (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), actor_id TEXT NOT NULL REFERENCES users(id),
        role TEXT NOT NULL, reason TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL,
        version INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(task_id,version))''',
]

class TaskTerms:
    def __init__(self, service):
        self.service=service
        self.database=service.database
        from .changes import TaskChanges
        self.changes=TaskChanges(self)

    def _party(self,c,task_id,user_id):
        task=self.service._task(c,task_id)
        if user_id not in (task['publisher_id'],task['assignee_id']):
            raise AppError('只有本任务协作双方可以查看或操作',403)
        return task

    @staticmethod
    def other(task,user):
        return task['assignee_id'] if task['publisher_id']==user else task['publisher_id']

    def _deadline(self,task,deadline):
        current=self.service.current_time()
        if deadline <= current or (task['deadline'] and deadline <= datetime.fromisoformat(task['deadline'])):
            raise AppError('新截止时间必须晚于原截止时间和服务端当前时间',422)
        return deadline.astimezone(timezone.utc).isoformat(),current.isoformat()

    def _change(self,c,task,user,deadline,reason,stamp,extension_id=None):
        from .changes import snapshot
        snapshot(c,task,stamp)
        version=task['terms_version']+1
        c.execute('UPDATE tasks SET deadline=?,terms_version=? WHERE id=?',(deadline,version,task['id']))
        c.execute('INSERT INTO task_deadline_history VALUES (?,?,?,?,?,?,?,?,?)',
                  (uuid4().hex,task['id'],user,task['deadline'],deadline,reason,version,extension_id,stamp))
        snapshot(c,self.service._task(c,task['id']),stamp,user,extension_id)
        return version

    def extend_unassigned(self,task_id,user,body):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');task=self.service._task(c,task_id)
            if task['publisher_id']!=user:raise AppError('只有发布者可以延长未接取任务',403)
            if not task['is_listed'] or task['status']!='published' or task['assignee_id']:
                raise AppError('只有尚未接取且未下架的任务可以直接延长')
            if body.version!=task['terms_version']:raise AppError('约定已变化，请读取最新版本')
            deadline,stamp=self._deadline(task,body.deadline)
            version=self._change(c,task,user,deadline,body.reason,stamp)
            for row in c.execute("SELECT applicant_id FROM applications WHERE task_id=? AND status='pending'",(task_id,)):
                emit(c,row[0],f'deadline:{task_id}:{version}','task',task_id,'任务截止时间已延长，可继续等待发布者确认',task['title'])
        return self.service.get_task(task_id)

    def extensions(self,task_id,user,connection=None):
        if connection is None:
            with self.database.connect() as c:
                c.execute('BEGIN')
                return self.extensions(task_id,user,c)
        state=self.changes.read(task_id,user,connection)
        items=[]
        for r in state['items']:
            if not r['legacy']:continue
            delta=next(d for d in r['differences'] if d['field']=='deadline')
            items.append({k:r[k] for k in ('id','task_id','requester_id','reason','terms_version','version','review_reason','reviewed_by','created_at','updated_at')} | dict(status='closed' if r['status']=='stale' else r['status'],old_deadline=delta['before'],new_deadline=delta['after']))
        def history(c):return [dict(r) for r in c.execute('SELECT * FROM task_deadline_history WHERE task_id=? ORDER BY version DESC',(task_id,))]
        if connection is not None:records=history(connection)
        else:
            with self.database.connect() as c:records=history(c)
        return dict(server_time=state['server_time'],next_boundary=None,terms_version=state['terms_version'],items=items,deadline_history=records)

    def propose(self,task_id,user,body):
        from .schemas import ChangeInput
        self.changes.propose(task_id,user,ChangeInput(version=body.version,reason=body.reason,changes={'deadline':body.deadline}),legacy=True)
        return self.extensions(task_id,user)

    def decide(self,identifier,user,body=None,*,cancel=False,version=None):
        state=self.changes.decide(identifier,user,body,cancel=cancel,version=version,legacy=True)
        return self.extensions(state['items'][0]['task_id'],user)

    def close_pending(self,c,task_id):
        self.changes.invalidate(c,task_id,close=True)

    def completed(self,c,task_id):
        self.close_pending(c,task_id)
        task=self.service._task(c,task_id)
        if task['reward_type']=='paid':
            for user in (task['publisher_id'],task['assignee_id']):
                emit(c,user,'settlement-ready:'+task_id,'task',task_id,'任务已完成，请记录线下付款或收款确认',task['title'])

    def settlement(self,task_id,user,connection=None):
        def read(c):
            task=self._party(c,task_id,user)
            if task['reward_type']!='paid':raise AppError('仅有偿任务提供结构化结算记录')
            row=c.execute('SELECT * FROM task_settlements WHERE task_id=?',(task_id,)).fetchone()
            value=dict(row) if row else dict(task_id=task_id,payer_confirmed=0,payee_confirmed=0,version=0,updated_at=None)
            cancellation=task['status']=='cancelled'
            amount=(task['cancellation_settlement_fen'] if task['cancellation_settlement_fen'] is not None else value.get('amount_fen')) if cancellation else task['reward_amount_fen']
            value.update(server_time=self.service.current_time().isoformat(),next_boundary=None,
                         available=task['status']=='completed' or (cancellation and amount>0),
                         amount_fen=amount,basis='协商取消金额' if cancellation else '任务固定报酬',
                         no_payment_required=cancellation and task['cancellation_settlement_fen']==0,
                         both_confirmed=bool(value['payer_confirmed'] and value['payee_confirmed']),
                         my_role='payer' if task['publisher_id']==user else 'payee',
                         history=[dict(r) for r in c.execute('SELECT * FROM task_settlement_history WHERE task_id=? ORDER BY version DESC',(task_id,))])
            return value
        if connection is not None:return read(connection)
        with self.database.connect() as c:
            c.execute('BEGIN');return read(c)

    def confirm(self,task_id,user,body):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');task=self._party(c,task_id,user)
            settlement=self.settlement(task_id,user,c)
            if task['reward_type']!='paid' or not settlement['available']:raise AppError('当前任务没有可确认的有偿结算')
            old=settlement;role=old['my_role'];field=role+'_confirmed'
            if bool(old[field])==body.confirmed:return old
            if old['version']!=body.version:raise AppError('结算记录已变化，请读取最新版本')
            if not body.confirmed and not body.reason:raise AppError('撤销确认必须填写原因',422)
            new=dict(payer_confirmed=old['payer_confirmed'],payee_confirmed=old['payee_confirmed']);new[field]=int(body.confirmed)
            version=old['version']+1;stamp=self.service.current_time().isoformat()
            amount=old['amount_fen']
            c.execute('''INSERT INTO task_settlements(task_id,payer_confirmed,payee_confirmed,version,updated_at,amount_fen) VALUES (?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET payer_confirmed=excluded.payer_confirmed,payee_confirmed=excluded.payee_confirmed,version=excluded.version,updated_at=excluded.updated_at,amount_fen=COALESCE(excluded.amount_fen,task_settlements.amount_fen)''',
                      (task_id,new['payer_confirmed'],new['payee_confirmed'],version,stamp,amount if task['status']=='cancelled' else None))
            before={key:old[key] for key in new}|{'amount_fen':amount,'basis':old['basis']}
            after={**new,'amount_fen':amount,'basis':old['basis']}
            c.execute('INSERT INTO task_settlement_history VALUES (?,?,?,?,?,?,?,?,?)',(uuid4().hex,task_id,user,role,body.reason,json.dumps(before),json.dumps(after),version,stamp))
            emit(c,self.other(task,user),f'settlement:{task_id}:{version}','task',task_id,('付款方已确认付款' if role=='payer' else '收款方已确认收款') if body.confirmed else '对方已撤销线下结算确认',task['title'])
        return self.settlement(task_id,user)
