"""双方确认的约定变更。写入、失效及消息始终使用业务事务。"""
import json
from datetime import datetime
from datetime import datetime, timezone
from uuid import uuid4
from .errors import AppError
from .notifications import emit
from .schemas import ChangeInput

STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS task_changes (
      id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
      requester_id TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
      terms_version INTEGER NOT NULL, changes TEXT NOT NULL, differences TEXT NOT NULL,
      stage_versions TEXT NOT NULL, suggestion_id TEXT REFERENCES stage_suggestions(id),
      status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled','stale','closed')),
      version INTEGER NOT NULL DEFAULT 1, review_reason TEXT NOT NULL DEFAULT '',
      reviewed_by TEXT REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      legacy INTEGER NOT NULL DEFAULT 0)''',
    "CREATE UNIQUE INDEX IF NOT EXISTS one_pending_change ON task_changes(task_id) WHERE status='pending'",
    '''CREATE TABLE IF NOT EXISTS task_agreements (
      task_id TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
      fields TEXT NOT NULL, actor_id TEXT REFERENCES users(id), created_at TEXT NOT NULL,
      change_id TEXT, PRIMARY KEY(task_id,version))''',
]

def migrate_control_columns(c):
    columns={r['name'] for r in c.execute('PRAGMA table_info(task_changes)')}
    if 'kind' not in columns:c.execute("ALTER TABLE task_changes ADD COLUMN kind TEXT NOT NULL DEFAULT 'agreement' CHECK(kind IN ('agreement','pause','resume','cancel'))")
    if 'collaboration_version' not in columns:c.execute('ALTER TABLE task_changes ADD COLUMN collaboration_version INTEGER')

def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

def agreement(c, task):
    fields={k:task[k] for k in ('description','completion_criteria','deadline','reward_type','reward_amount_fen','reward')}
    fields['stages']=[{k:r[k] for k in ('id','position','title','completion_criteria','deadline','responsible_role')} for r in c.execute('SELECT * FROM task_stages WHERE task_id=? ORDER BY position',(task['id'],))]
    return fields

def snapshot(c, task, stamp, actor=None, change_id=None):
    c.execute('INSERT OR IGNORE INTO task_agreements VALUES (?,?,?,?,?,?)',
              (task['id'],task['terms_version'],dump(agreement(c,task)),actor,stamp,change_id))

def migrate(c):
    for sql in STATEMENTS:c.execute(sql)
    for table in ('submissions','stage_submissions'):
        if 'terms_version' not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
            c.execute(f'ALTER TABLE {table} ADD COLUMN terms_version INTEGER')
    # 截止历史可恢复；其余历史内容不推断。旧表从此只读。
    for r in c.execute('SELECT * FROM task_extensions').fetchall():
        changes={'deadline':r['new_deadline']}
        differences=[dict(field='deadline',before=r['old_deadline'],after=r['new_deadline'])]
        bound={s['id']:s['version'] for s in c.execute('SELECT id,version FROM task_stages WHERE task_id=?',(r['task_id'],))} if r['status']=='pending' else {}
        c.execute('''INSERT OR IGNORE INTO task_changes
          (id,task_id,requester_id,reason,terms_version,changes,differences,stage_versions,status,version,review_reason,reviewed_by,created_at,updated_at,legacy)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
          (r['id'],r['task_id'],r['requester_id'],r['reason'],r['terms_version'],dump(changes),dump(differences),dump(bound),r['status'],r['version'],r['review_reason'],r['reviewed_by'],r['created_at'],r['updated_at']))
    for task in c.execute('SELECT * FROM tasks').fetchall():
        snapshot(c,task,datetime.now(timezone.utc).isoformat())


class TaskChanges:
    def __init__(self, terms):
        self.terms=terms;self.service=terms.service;self.database=terms.database

    def _active(self,task):
        if not task['is_listed'] or not task['assignee_id'] or task['status'] not in ('in_progress','pending_review','paused'):
            raise AppError('只有协作中的任务可以提出或批准变更')

    def propose_control(self,task_id,user,body):
        """将暂停、恢复、取消提案写入统一变更队列。"""
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');task=self.terms._party(c,task_id,user)
            if task['status'] in ('completed','cancelled') or not task['assignee_id']:
                raise AppError('当前任务状态不能申请协作变更',409)
            if task['terms_version']!=body.version or task['collaboration_version']!=body.collaboration_version:
                raise AppError('任务约定或协作状态已变化，请刷新后重建申请',409)
            pending=c.execute("SELECT 1 FROM task_changes WHERE task_id=? AND status='pending'",(task_id,)).fetchone()
            if pending:raise AppError('已有待处理变更申请，请先处理或撤销',409)
            action=body.action
            expected={'pause':('in_progress','pending_review'),'resume':('paused',),'cancel':('in_progress','pending_review','paused')}
            if task['status'] not in expected[action]:raise AppError('任务状态已变化，不能提出该申请',409)
            if action=='cancel':
                waiting=c.execute("SELECT 1 FROM submissions WHERE task_id=? AND status='submitted' UNION ALL SELECT 1 FROM stage_submissions WHERE task_id=? AND status='submitted' LIMIT 1",(task_id,task_id)).fetchone()
                if waiting:raise AppError('仍有成果等待验收，请先退回补充后再申请取消',409)
            patch={'action':action,'reason':body.reason,'extend_deadline':body.extend_deadline}
            differences=[]
            if action=='pause' and body.extend_deadline:
                if body.deadline is None:raise AppError('选择延长时必须填写新的整体截止时间',422)
                deadline,stamp=self.terms._deadline(task,body.deadline);patch['deadline']=deadline
                differences.append(dict(field='deadline',before=task['deadline'],after=deadline))
            elif body.deadline is not None or body.extend_deadline:
                raise AppError('只有暂停申请可以同时延长整体截止时间',422)
            if action=='cancel' and task['reward_type']=='paid':
                amount=body.cancellation_settlement_fen
                if amount is None or amount>task['reward_amount_fen']:
                    raise AppError('有偿任务取消时须约定 0 至原报酬的取消结算金额',422)
                patch['cancellation_settlement_fen']=amount
            elif body.cancellation_settlement_fen is not None:
                raise AppError('只有有偿任务取消申请可以填写取消结算金额',422)
            if not body.extend_deadline:patch['deadline']=None
            stages={r['id']:r['version'] for r in c.execute("SELECT id,version FROM task_stages WHERE task_id=? AND status!='confirmed'",(task_id,))}
            stamp=self.service.current_time().isoformat();identifier=uuid4().hex
            differences.append(dict(field='collaboration_action',before=task['status'],after=action))
            if 'cancellation_settlement_fen' in patch:
                differences.append(dict(field='cancellation_settlement_fen',before=None,after=patch['cancellation_settlement_fen']))
            c.execute('''INSERT INTO task_changes (id,task_id,requester_id,reason,terms_version,changes,differences,stage_versions,status,created_at,updated_at,kind,collaboration_version)
                VALUES (?,?,?,?,?,?,?,?, 'pending',?,?,?,?)''',(identifier,task_id,user,body.reason,task['terms_version'],dump(patch),dump(differences),dump(stages),stamp,stamp,action,task['collaboration_version']))
            emit(c,self.terms.other(task,user),'collaboration-request:'+identifier,'task',task_id,{'pause':'收到暂停协作申请','resume':'收到恢复协作申请','cancel':'收到协商取消申请'}[action],task['title'])
        return self.read(task_id,user)

    def validate(self,c,task,patch,expected_stages=None):
        """提案与审批共同使用，返回实际差异及需要绑定的执行版本。"""
        stages=[dict(r) for r in c.execute('SELECT * FROM task_stages WHERE task_id=? ORDER BY position',(task['id'],))]
        by_id={r['id']:r for r in stages};diff=[];bound={}
        current=self.service.current_time()
        def changed(field,before,after):
            if before!=after:diff.append(dict(field=field,before=before,after=after))
        def future(value):
            dt=datetime.fromisoformat(value)
            if dt.tzinfo is None or dt<=current:raise AppError('被修改的截止时间必须带时区且晚于服务端当前时间',422)
            return dt.astimezone(timezone.utc).isoformat()
        def same_time(before,after):
            return before is not None and datetime.fromisoformat(before)==datetime.fromisoformat(after)
        for key in patch:
            if patch[key] is None:raise AppError('选中的修改项不能为 null',422)
        if 'deadline' in patch:
            if same_time(task['deadline'],patch['deadline']):patch.pop('deadline')
            else:
                patch['deadline']=future(patch['deadline']);changed('deadline',task['deadline'],patch['deadline'])
        scope=any(k in patch and patch[k]!=task[k] for k in ('description','completion_criteria'))
        if scope:
            if task['status']=='pending_review' or any(s['status']=='submitted' for s in stages):
                raise AppError('有待验收成果，请先退回补充，再修改工作范围或完成标准')
            bound.update({s['id']:s['version'] for s in stages if s['status']!='confirmed'})
        for key in ('description','completion_criteria'):
            if key in patch:
                if task[key]==patch[key]:patch.pop(key)
                else:changed(key,task[key],patch[key])
        if 'reward' in patch:
            for key,value in patch['reward'].items():changed(key,task[key],value)
        if 'stages' in patch and 'initial_stages' in patch:raise AppError('首次安排和既有阶段修改不能同时提交',422)
        seen=set()
        for update in patch.get('stages',[]):
            identifier=update['id'];stage=by_id.get(identifier)
            if identifier in seen:raise AppError('同一阶段不能重复修改',422)
            seen.add(identifier)
            if stage is None or stage['status']=='confirmed':raise AppError('阶段不存在或已确认完成，不能修改')
            if stage['version']!=update['version']:raise AppError('阶段执行状态已变化，请重新核对')
            for key in ('deadline','completion_criteria'):
                if key not in update:continue
                if update[key] is None:raise AppError('阶段修改项不能为 null',422)
                if (key=='deadline' and same_time(stage[key],update[key])) or stage[key]==update[key]:
                    update.pop(key);continue
                value=future(update[key]) if key=='deadline' else update[key]
                if key=='completion_criteria' and stage['status']=='submitted' and value!=stage[key]:
                    raise AppError('阶段成果待验收，请先退回补充再修改完成要求')
                changed('stages.'+identifier+'.'+key,stage[key],value)
                diff[-1]['stage_title']=stage['title']
                stage[key]=value;update[key]=value
            if len(update)>2:bound[identifier]=stage['version']
        if 'stages' in patch:
            patch['stages']=[u for u in patch['stages'] if len(u)>2]
            if not patch['stages']:patch.pop('stages')
        if 'initial_stages' in patch:
            if stages or c.execute('SELECT 1 FROM submissions WHERE task_id=?',(task['id'],)).fetchone():
                raise AppError('已有阶段或整项成果记录，不能创建首次阶段安排')
            for s in patch['initial_stages']:s['deadline']=future(s['deadline'])
            stages=patch['initial_stages'];changed('initial_stages',[],stages)
        upper=datetime.fromisoformat(patch.get('deadline') or task['deadline']) if (patch.get('deadline') or task['deadline']) else None
        last=None
        for stage in stages:
            dt=datetime.fromisoformat(stage['deadline'])
            if (upper and dt>upper) or (last and dt<last):raise AppError('阶段截止时间须按顺序不递减，且不得晚于整体截止时间',422)
            last=dt
        # 整体时间变化也依赖所有阶段内容版本，防止审批绕过新安排。
        if 'deadline' in patch:bound.update({s['id']:s['version'] for s in by_id.values()})
        if expected_stages is not None and bound!=expected_stages:raise AppError('涉及阶段已推进，请核对后重新申请')
        if not diff:raise AppError('没有实际变更，请修改后再提出',422)
        return diff,bound

    def read(self,task_id,user,connection=None):
        def inner(c):
            task=self.terms._party(c,task_id,user)
            rows=[]
            for r in c.execute('SELECT * FROM task_changes WHERE task_id=? ORDER BY created_at DESC,rowid DESC',(task_id,)):
                row=dict(r)
                for key in ('changes','differences','stage_versions'):row[key]=json.loads(row[key])
                rows.append(row)
            return dict(items=rows,terms_version=task['terms_version'],agreement=agreement(c,task),
                        stages=[dict(r) for r in c.execute('SELECT * FROM task_stages WHERE task_id=? ORDER BY position',(task_id,))],
                        server_time=self.service.current_time().isoformat(),next_boundary=None)
        if connection is not None:return inner(connection)
        with self.database.connect() as c:c.execute('BEGIN');return inner(c)

    def history(self,task_id,user,version):
        with self.database.connect() as c:
            c.execute('BEGIN');self.terms._party(c,task_id,user)
            r=c.execute('SELECT * FROM task_agreements WHERE task_id=? AND version=?',(task_id,version)).fetchone()
            if not r:raise AppError('该历史约定未记录，不能推断当时内容',404)
            return {**dict(r),'fields':json.loads(r['fields'])}

    def propose(self,task_id,user,body,*,legacy=False):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');task=self.terms._party(c,task_id,user);self._active(task)
            if body.version!=task['terms_version']:raise AppError('约定已变化，请读取最新版本')
            if c.execute("SELECT 1 FROM task_changes WHERE task_id=? AND status='pending'",(task_id,)).fetchone():raise AppError('已有待处理变更申请，请先处理或撤销')
            patch=body.changes.model_dump(mode='json',exclude_unset=True)
            # 完整替换报酬对象，默认空值也须保存。
            if body.changes.reward:patch['reward']=body.changes.reward.model_dump(mode='json')
            diff,bound=self.validate(c,task,patch)
            if legacy:self.terms._deadline(task,datetime.fromisoformat(patch['deadline']))
            if body.suggestion_id:self._suggestion(c,task,user,body.suggestion_id,patch)
            stamp=self.service.current_time().isoformat();identifier=uuid4().hex
            snapshot(c,task,stamp)
            c.execute('''INSERT INTO task_changes (id,task_id,requester_id,reason,terms_version,changes,differences,stage_versions,suggestion_id,status,created_at,updated_at,legacy)
              VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?,?)''',(identifier,task_id,user,body.reason,body.version,dump(patch),dump(diff),dump(bound),body.suggestion_id,stamp,stamp,int(legacy)))
            emit(c,self.terms.other(task,user),'change:'+identifier,'task',task_id,'收到约定变更申请，确认前仍执行原约定',task['title'])
        return self.read(task_id,user)

    def _suggestion(self,c,task,user,identifier,patch):
        from .stages import StageService
        row=c.execute('SELECT * FROM stage_suggestions WHERE id=? AND task_id=? AND user_id=?',(identifier,task['id'],user)).fetchone()
        if user!=task['publisher_id'] or not row:raise AppError('阶段建议不存在或无权采用',403)
        if 'initial_stages' not in patch or row['applied_version'] is not None or row['base_version']!=StageService.version(c,task['id']):
            raise AppError('建议已失效或不适用于首次安排')

    def _apply(self,c,task,row,patch,user,stamp):
        from .stages import StageService
        snapshot(c,task,stamp)
        fields={k:patch[k] for k in ('deadline','description','completion_criteria') if k in patch}
        fields.update(patch.get('reward',{}));fields['terms_version']=task['terms_version']+1
        c.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),task['id']))
        if 'deadline' in patch:
            c.execute('INSERT INTO task_deadline_history VALUES (?,?,?,?,?,?,?,?,?)',(uuid4().hex,task['id'],user,task['deadline'],patch['deadline'],row['reason'],fields['terms_version'],row['id'],stamp))
        if 'stages' in patch or 'initial_stages' in patch:
            pv=StageService.version(c,task['id'])+1
            for update in patch.get('stages',[]):
                values={k:v for k,v in update.items() if k not in ('id','version')}
                c.execute('UPDATE task_stages SET '+','.join(k+'=?' for k in values)+',version=version+1 WHERE id=?',(*values.values(),update['id']))
            for i,s in enumerate(patch.get('initial_stages',[]),1):
                c.execute("INSERT INTO task_stages (id,task_id,position,title,completion_criteria,deadline,responsible_role,status) VALUES (?,?,?,?,?,?,?,'not_started')",(uuid4().hex,task['id'],i,s['title'],s['completion_criteria'],s['deadline'],s['responsible_role']))
            c.execute('INSERT INTO task_stage_plans VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET version=excluded.version',(task['id'],pv))
            stages=agreement(c,self.service._task(c,task['id']))['stages']
            stages=[{k:s[k] for k in ('title','completion_criteria','deadline','responsible_role')} for s in stages]
            c.execute('INSERT INTO task_stage_plan_versions VALUES (?,?,?,?,?,?)',(task['id'],pv,dump(stages),user,stamp,row['suggestion_id']))
            if row['suggestion_id']:c.execute('UPDATE stage_suggestions SET applied_version=? WHERE id=?',(pv,row['suggestion_id']))
        snapshot(c,self.service._task(c,task['id']),stamp,user,row['id'])

    def decide(self,identifier,user,body=None,*,cancel=False,version=None,legacy=False):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM task_changes WHERE id=?',(identifier,)).fetchone()
            if not row:raise AppError('变更申请不存在',404)
            task=self.terms._party(c,row['task_id'],user)
            if legacy and not row['legacy']:raise AppError('请使用统一变更入口处理此申请')
            if (cancel and row['requester_id']!=user) or (not cancel and row['requester_id']==user):raise AppError('只有提出者可撤销，只有对方可审批',403)
            expected=version if cancel else body.version
            if row['status']!='pending' or expected!=row['version']:raise AppError('申请已处理或失效，请读取最新状态')
            if row['kind']!='agreement':
                self._decide_control(c,row,task,user,body,cancel,expected)
            else:
                self._active(task)
                if task['terms_version']!=row['terms_version']:raise AppError('约定已变化，请重新核对')
                status='cancelled' if cancel else 'approved' if body.decision=='approve' else 'rejected'
                reason='' if cancel else body.reason
                if status=='rejected' and not reason:raise AppError('拒绝变更必须填写原因',422)
                stamp=self.service.current_time().isoformat()
                if status=='approved':
                    patch=json.loads(row['changes']);self.validate(c,task,patch,json.loads(row['stage_versions']))
                    if row['legacy']:self.terms._deadline(task,datetime.fromisoformat(patch['deadline']))
                    if row['suggestion_id']:self._suggestion(c,task,row['requester_id'],row['suggestion_id'],patch)
                    self._apply(c,task,row,patch,user,stamp)
                c.execute('UPDATE task_changes SET status=?,review_reason=?,reviewed_by=?,version=version+1,updated_at=? WHERE id=?',(status,reason,user,stamp,identifier))
                emit(c,self.terms.other(task,user),f'change:{identifier}:{row["version"]+1}','task',task['id'],{'approved':'约定变更已生效','rejected':'约定变更已拒绝','cancelled':'约定变更已撤销'}[status],task['title'])
        return self.read(task['id'],user)

    def _decide_control(self,c,row,task,user,body,cancel,expected):
        if cancel:
            status='cancelled';reason=''
        else:
            status='approved' if body.decision=='approve' else 'rejected';reason=body.reason
            if status=='rejected' and not reason:raise AppError('拒绝申请必须填写原因',422)
        if status=='approved':
            if task['collaboration_version']!=row['collaboration_version'] or task['terms_version']!=row['terms_version']:
                raise AppError('协作状态或约定已变化，请重新核对后申请',409)
            patch=json.loads(row['changes']);action=row['kind']
            if action=='pause' and task['status'] not in ('in_progress','pending_review'):raise AppError('任务已不在可暂停状态',409)
            if action=='resume' and task['status']!='paused':raise AppError('任务当前未暂停',409)
            if action=='cancel' and task['status'] not in ('in_progress','pending_review','paused'):raise AppError('任务已结束，不能取消',409)
            if action=='cancel':
                waiting=c.execute("SELECT 1 FROM submissions WHERE task_id=? AND status='submitted' UNION ALL SELECT 1 FROM stage_submissions WHERE task_id=? AND status='submitted' LIMIT 1",(task['id'],task['id'])).fetchone()
                if waiting:raise AppError('成果已进入待验收，请先处理验收记录',409)
            stamp=self.service.current_time().isoformat();new_version=task['collaboration_version']+1
            if action=='pause':
                deadline=patch.get('deadline')
                if deadline:
                    self.terms._deadline(task,datetime.fromisoformat(deadline))
                    terms_version=task['terms_version']+1
                    from .changes import snapshot
                    snapshot(c,task,stamp)
                    c.execute('UPDATE tasks SET status=\'paused\',paused_from_status=?,pause_reason=?,collaboration_version=?,deadline=?,terms_version=? WHERE id=?',(task['status'],patch['reason'],new_version,deadline,terms_version,task['id']))
                    c.execute('INSERT INTO task_deadline_history VALUES (?,?,?,?,?,?,?,?,?)',(uuid4().hex,task['id'],user,task['deadline'],deadline,row['reason'],terms_version,row['id'],stamp))
                    snapshot(c,self.service._task(c,task['id']),stamp,user,row['id'])
                else:c.execute("UPDATE tasks SET status='paused',paused_from_status=?,pause_reason=?,collaboration_version=? WHERE id=?",(task['status'],patch['reason'],new_version,task['id']))
                c.execute("UPDATE task_stages SET version=version+1 WHERE task_id=? AND status!='confirmed'",(task['id'],))
            elif action=='resume':
                restored=task['paused_from_status'] or 'in_progress'
                c.execute('UPDATE tasks SET status=?,paused_from_status=NULL,pause_reason=NULL,collaboration_version=? WHERE id=?',(restored,new_version,task['id']))
                c.execute("UPDATE task_stages SET version=version+1 WHERE task_id=? AND status!='confirmed'",(task['id'],))
            else:
                amount=patch.get('cancellation_settlement_fen')
                c.execute("UPDATE tasks SET status='cancelled',cancelled_at=?,cancel_reason=?,cancellation_settlement_fen=?,cancellation_settlement_reason=?,collaboration_version=? WHERE id=?",(stamp,patch['reason'],amount,patch['reason'] if amount is not None else None,new_version,task['id']))
                if amount is not None and amount>0:
                    c.execute('''INSERT INTO task_settlements(task_id,payer_confirmed,payee_confirmed,version,updated_at,amount_fen) VALUES (?,0,0,0,?,?)
                        ON CONFLICT(task_id) DO UPDATE SET payer_confirmed=0,payee_confirmed=0,version=version+1,updated_at=excluded.updated_at,amount_fen=excluded.amount_fen''',(task['id'],stamp,amount))
                    for recipient in (task['publisher_id'],task['assignee_id']):emit(c,recipient,'cancellation-settlement:'+task['id'],'task',task['id'],'任务已协商取消，请按双方约定记录线下结算',task['title'])
                elif amount==0:
                    c.execute('UPDATE task_settlements SET payer_confirmed=0,payee_confirmed=0,version=version+1,updated_at=? WHERE task_id=?',(stamp,task['id']))
                self.invalidate(c,task['id'],close=True,exclude_id=row['id'])
            c.execute('UPDATE task_changes SET status=?,review_reason=?,reviewed_by=?,version=version+1,updated_at=? WHERE id=?',(status,reason,user,stamp,row['id']))
            if status=='approved':
                title={'pause':'双方已确认暂停协作','resume':'双方已确认恢复协作','cancel':'双方已协商取消任务'}[action]
            else:title={'rejected':'协作申请已拒绝','cancelled':'协作申请已撤销'}[status]
            emit(c,self.terms.other(task,user),'collaboration-result:'+row['id']+':'+str(row['version']+1),'task',task['id'],title,task['title'])
        else:
            stamp=self.service.current_time().isoformat()
            c.execute('UPDATE task_changes SET status=?,review_reason=?,reviewed_by=?,version=version+1,updated_at=? WHERE id=?',(status,reason,user,stamp,row['id']))
            emit(c,self.terms.other(task,user),'collaboration-result:'+row['id']+':'+str(row['version']+1),'task',task['id'],'协作申请已撤销' if cancel else '协作申请已拒绝',task['title'])

    def invalidate(self,c,task_id,stage_id=None,*,whole_submission=False,close=False,exclude_id=None):
        task=self.service._task(c,task_id)
        for row in c.execute("SELECT * FROM task_changes WHERE task_id=? AND status='pending'",(task_id,)).fetchall():
            if row['id']==exclude_id:continue
            patch=json.loads(row['changes']);bound=json.loads(row['stage_versions'])
            control=row['kind']!='agreement'
            if not close and not (control and (stage_id is not None or whole_submission) or stage_id in bound or (whole_submission and any(k in patch for k in ('description','completion_criteria','initial_stages')))):continue
            state='closed' if close else 'stale';reason='任务已完成或下架' if close else '涉及的阶段或成果已推进，请核对最新状态后重新申请'
            c.execute('UPDATE task_changes SET status=?,review_reason=?,version=version+1,updated_at=? WHERE id=?',(state,reason,self.service.current_time().isoformat(),row['id']))
            for user in (task['publisher_id'],task['assignee_id']):
                if user:emit(c,user,f'change-{state}:{row["id"]}','task',task_id,'变更申请已关闭' if close else '变更申请已失效，请重新核对',task['title'])
