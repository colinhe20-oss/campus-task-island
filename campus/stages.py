"""共享阶段定义、顺序执行和验收；所有变更以版本号与事务防止覆盖。"""
from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from .errors import AppError
from .notifications import emit
from .schemas import (StageFields, StagePlanInput, StagePanelRead, StageRead,
                      StagePlanVersionRead, StageSubmissionRead, StageSuggestionRead)
from .service import now


class StageService:
    def __init__(self, service):
        self.service = service
        self.database = service.database

    @staticmethod
    def version(conn, task_id):
        row = conn.execute('SELECT version FROM task_stage_plans WHERE task_id=?',(task_id,)).fetchone()
        return row['version'] if row else 0

    @staticmethod
    def edit_reason(conn, task):
        if not task['is_listed'] or task['status'] not in ('published','in_progress'):
            return '仅待接取或尚未提交成果的协作任务可以设置阶段'
        if conn.execute('SELECT 1 FROM submissions WHERE task_id=?',(task['id'],)).fetchone():
            return '已有整项成果记录，请继续原验收流程'
        if conn.execute("SELECT 1 FROM task_stages WHERE task_id=? AND status!='not_started'",(task['id'],)).fetchone():
            return '阶段已开始，安排已锁定，保留原约定与执行记录'
        return None

    def editable_task(self, conn, task_id, user_id):
        task = self.service._task(conn,task_id)
        if task['publisher_id'] != user_id:
            raise AppError('只有发布者可以确认阶段安排或请求 AI 建议',403)
        reason = self.edit_reason(conn,task)
        if reason:
            raise AppError(reason,409)
        return task

    @staticmethod
    def validate_fields(task, fields):
        stages = [StageFields.model_validate(s) for s in fields]
        if not 1<=len(stages)<=8:
            raise AppError('阶段数量须为 1 到 8',422)
        last = None
        upper = datetime.fromisoformat(task['deadline']) if task['deadline'] else None
        for stage in stages:
            if last and stage.deadline < last:
                raise AppError('阶段截止时间应按执行顺序排列',422)
            if upper and stage.deadline > upper:
                raise AppError('阶段截止时间不能晚于任务截止时间',422)
            last = stage.deadline
        return stages

    def read(self, task_id, user_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN')
            task = self.service._task(conn,task_id)
            collaborator = user_id in (task['publisher_id'],task['assignee_id'])
            reason = self.edit_reason(conn,task)
            if task['assignee_id'] and conn.execute('SELECT 1 FROM task_stages WHERE task_id=?',(task_id,)).fetchone():
                reason = '已有阶段请在任务约定与记录中提交变更申请'
            rows = conn.execute('SELECT * FROM task_stages WHERE task_id=? ORDER BY position',(task_id,)).fetchall()
            people = {r['id']:r['display_name'] for r in conn.execute('SELECT id,display_name FROM users WHERE id IN (?,?)',
                                                                    (task['publisher_id'],task['assignee_id']))}
            submissions = {}
            if collaborator:
                for r in conn.execute('''SELECT s.*,a.display_name author_name,r.display_name reviewer_name
                    FROM stage_submissions s JOIN users a ON a.id=s.author_id LEFT JOIN users r ON r.id=s.reviewer_id
                    WHERE s.task_id=? ORDER BY s.created_at DESC,s.id DESC''',(task_id,)):
                    submissions.setdefault(r['stage_id'],[]).append(StageSubmissionRead.model_validate(dict(r)))
            stages = []
            for row in rows:
                data = dict(row)
                data.pop('task_id')
                responsible = task['publisher_id'] if row['responsible_role']=='publisher' else task['assignee_id']
                reviewer = task['assignee_id'] if row['responsible_role']=='publisher' else task['publisher_id']
                data['is_overdue']=data['status']!='confirmed' and datetime.fromisoformat(data['deadline'])<=self.service.current_time()
                stages.append(StageRead(**data,responsible_id=responsible,responsible_name=people.get(responsible),
                                        reviewer_id=reviewer,reviewer_name=people.get(reviewer),submissions=submissions.get(row['id'],[])))
            versions = [StagePlanVersionRead(version=r['version'],created_at=r['created_at'],stages=json.loads(r['fields']))
                        for r in conn.execute('SELECT * FROM task_stage_plan_versions WHERE task_id=? ORDER BY version DESC',(task_id,))] if collaborator else []
            suggestion = self.suggestion_row(conn.execute('SELECT * FROM stage_suggestions WHERE task_id=? AND user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                                                          (task_id,user_id)).fetchone()) if task['publisher_id']==user_id else None
            return StagePanelRead(task_id=task_id,plan_version=self.version(conn,task_id),stages=stages,versions=versions,
                                  can_propose_plan=collaborator and bool(task['assignee_id']) and reason is None and not rows,
                                  can_edit=task['publisher_id']==user_id and reason is None,
                                  edit_reason=reason if task['publisher_id']==user_id else '阶段安排由发布者确认',suggestion=suggestion)

    def set_plan(self, task_id, user_id, body: StagePlanInput):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = self.editable_task(conn,task_id,user_id)
            version = self.version(conn,task_id)
            if body.expected_version != version:
                raise AppError('阶段安排已被更新，请读取最新面板后重新核对',409)
            if task['assignee_id']:
                raise AppError('接取后阶段安排须通过双方变更申请，不能直接设置')
            stages = self.validate_fields(task,body.stages)
            if body.suggestion_id:
                suggestion = conn.execute('SELECT * FROM stage_suggestions WHERE id=? AND task_id=? AND user_id=?',
                                          (body.suggestion_id,task_id,user_id)).fetchone()
                if not suggestion:
                    raise AppError('阶段建议不存在或不属于当前用户',404)
                if suggestion['base_version'] != version or suggestion['applied_version'] is not None:
                    raise AppError('这份建议已过期或已采用，请重新核对当前阶段安排',409)
                conn.execute('UPDATE stage_suggestions SET applied_version=? WHERE id=?',(version+1,body.suggestion_id))
            from .changes import snapshot
            snapshot(conn,task,self.service.current_time().isoformat())
            # 未开始的定义可以替换；确认过的每个版本另存快照，执行记录从不删除。
            conn.execute('DELETE FROM task_stages WHERE task_id=?',(task_id,))
            for index, stage in enumerate(stages,1):
                fields = stage.model_dump(mode='json')
                conn.execute('''INSERT INTO task_stages(id,task_id,position,title,completion_criteria,deadline,responsible_role,status)
                    VALUES (?,?,?,?,?,?,?,'not_started')''',(uuid4().hex,task_id,index,fields['title'],fields['completion_criteria'],fields['deadline'],fields['responsible_role']))
            conn.execute('INSERT INTO task_stage_plans VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET version=excluded.version',(task_id,version+1))
            conn.execute('INSERT INTO task_stage_plan_versions VALUES (?,?,?,?,?,?)',
                         (task_id,version+1,json.dumps([s.model_dump(mode='json') for s in stages],ensure_ascii=False),user_id,now(),body.suggestion_id))
            conn.execute('UPDATE tasks SET terms_version=terms_version+1 WHERE id=?',(task_id,))
            snapshot(conn,self.service._task(conn,task_id),self.service.current_time().isoformat(),user_id)
            emit(conn,task['assignee_id'],f'plan:{task_id}:{version+1}','task',task_id,'阶段安排已更新',task['title'])
        return self.read(task_id,user_id)

    def _current(self, conn, task_id, stage_id, user_id, version, *, review=False):
        task = self.service._task(conn,task_id)
        stage = conn.execute('SELECT * FROM task_stages WHERE id=? AND task_id=?',(stage_id,task_id)).fetchone()
        if not stage:
            raise AppError('阶段不存在或已被新的安排替换',404)
        if user_id not in (task['publisher_id'],task['assignee_id']):
            raise AppError('只有本任务的协作成员可以操作阶段',403)
        if not task['is_listed'] or task['status'] not in ('in_progress','pending_review') or not task['assignee_id']:
            raise AppError('正式接取后才能执行阶段；已完成或下架任务不能修改',409)
        responsible = task['publisher_id'] if stage['responsible_role']=='publisher' else task['assignee_id']
        reviewer = task['assignee_id'] if stage['responsible_role']=='publisher' else task['publisher_id']
        if user_id != (reviewer if review else responsible):
            raise AppError('只有本阶段验收方可以确认或退回' if review else '只有本阶段负责人可以开始或提交',403)
        if stage['version'] != version:
            raise AppError('阶段状态已变化，请刷新后查看',409)
        first = conn.execute("SELECT id FROM task_stages WHERE task_id=? AND status!='confirmed' ORDER BY position LIMIT 1",(task_id,)).fetchone()
        if not first or first['id'] != stage_id:
            raise AppError('请先完成并确认前面的阶段',409)
        return task,stage

    def _sync_task(self, conn, task_id):
        statuses = [r['status'] for r in conn.execute('SELECT status FROM task_stages WHERE task_id=?',(task_id,))]
        state = 'completed' if all(s=='confirmed' for s in statuses) else ('pending_review' if 'submitted' in statuses else 'in_progress')
        conn.execute('UPDATE tasks SET status=? WHERE id=?',(state,task_id))
        if state=='completed':self.service.terms.completed(conn,task_id)

    def start(self, task_id, stage_id, user_id, version):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task,stage = self._current(conn,task_id,stage_id,user_id,version)
            if stage['status'] not in ('not_started','changes_requested'):
                raise AppError('该阶段已经开始或正在验收',409)
            conn.execute("UPDATE task_stages SET status='in_progress',version=version+1 WHERE id=?",(stage_id,))
            self._sync_task(conn,task_id)
            self.service.terms.changes.invalidate(conn,task_id,stage_id)
            other=task['assignee_id'] if user_id==task['publisher_id'] else task['publisher_id']
            emit(conn,other,f'stage:{stage_id}:{version+1}','task',task_id,'协作阶段已开始',task['title'])
        return self.read(task_id,user_id)

    def submit(self, task_id, stage_id, user_id, body):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task,stage = self._current(conn,task_id,stage_id,user_id,body.version)
            if stage['status'] != 'in_progress':
                raise AppError('请先开始本阶段，再提交成果',409)
            conn.execute('''INSERT INTO stage_submissions(id,stage_id,task_id,author_id,summary,status,created_at,terms_version)
                VALUES (?,?,?,?,?,'submitted',?,?)''',(uuid4().hex,stage_id,task_id,user_id,body.summary,self.service.current_time().isoformat(),task['terms_version']))
            conn.execute("UPDATE task_stages SET status='submitted',version=version+1 WHERE id=?",(stage_id,))
            self._sync_task(conn,task_id)
            self.service.terms.changes.invalidate(conn,task_id,stage_id)
            other=task['assignee_id'] if user_id==task['publisher_id'] else task['publisher_id']
            emit(conn,other,f'stage:{stage_id}:{body.version+1}','task',task_id,'阶段成果已提交，待验收',task['title'])
        return self.read(task_id,user_id)

    def review(self, task_id, stage_id, user_id, body):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task,stage = self._current(conn,task_id,stage_id,user_id,body.version,review=True)
            if stage['status'] != 'submitted':
                raise AppError('本阶段没有待验收的提交',409)
            conn.execute("UPDATE stage_submissions SET status=?,feedback=?,reviewed_at=?,reviewer_id=? WHERE stage_id=? AND status='submitted'",
                         ('accepted' if body.decision=='accept' else 'changes_requested',body.feedback,now(),user_id,stage_id))
            conn.execute('UPDATE task_stages SET status=?,version=version+1 WHERE id=?',
                         ('confirmed' if body.decision=='accept' else 'changes_requested',stage_id))
            self._sync_task(conn,task_id)
            self.service.terms.changes.invalidate(conn,task_id,stage_id)
            other=task['assignee_id'] if user_id==task['publisher_id'] else task['publisher_id']
            completed=conn.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()[0]=='completed'
            title='阶段验收通过，任务已完成' if completed else '阶段验收通过' if body.decision=='accept' else '阶段成果需补充'
            emit(conn,other,f'stage:{stage_id}:{body.version+1}','task',task_id,title,task['title'])
        return self.read(task_id,user_id)

    @staticmethod
    def suggestion_row(row):
        if row is None:
            return None
        return StageSuggestionRead(id=row['id'],task_id=row['task_id'],conversation_id=row['conversation_id'],
                                   base_version=row['base_version'],stages=json.loads(row['fields']),model=row['model'],applied_version=row['applied_version'])

    def latest_suggestion(self, conversation_id, user_id):
        with self.database.connect() as conn:
            row = conn.execute('SELECT * FROM stage_suggestions WHERE conversation_id=? AND user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                               (conversation_id,user_id)).fetchone()
        return self.suggestion_row(row)


class StageSuggestionBuffer:
    """单次模型运行内暂存建议，失败或取消不保存；建议不能执行阶段操作。"""
    def __init__(self, stages: StageService, task_id, user_id, conversation_id):
        self.service, self.task_id, self.user_id, self.conversation_id = stages,task_id,user_id,conversation_id
        with stages.database.connect() as conn:
            conn.execute('BEGIN')
            self.task = dict(stages.editable_task(conn,task_id,user_id))
            self.base_version = stages.version(conn,task_id)
        self.fields = None
        self.id = uuid4().hex
        self.model = None
        self.detail_loaded = False

    def propose(self, stages):
        if not self.detail_loaded:
            raise ValueError('请先调用 get_task_detail 查询当前任务的真实要求')
        self.fields = self.service.validate_fields(self.task,stages)
        return self.read()

    def read(self):
        if self.fields is None:
            return None
        return StageSuggestionRead(id=self.id,task_id=self.task_id,conversation_id=self.conversation_id,
                                   base_version=self.base_version,stages=self.fields,model=self.model)

    def save(self, conn):
        if self.fields is None:
            raise AppError('AI 尚未生成有效的阶段卡片，请补充要求或手动设置阶段',502)
        self.service.editable_task(conn,self.task_id,self.user_id)
        if self.service.version(conn,self.task_id) != self.base_version:
            raise AppError('生成建议期间阶段安排已变化，请刷新后重新生成',409)
        conn.execute('INSERT INTO stage_suggestions(id,task_id,user_id,conversation_id,base_version,fields,model,created_at) VALUES (?,?,?,?,?,?,?,?)',
                     (self.id,self.task_id,self.user_id,self.conversation_id,self.base_version,
                      json.dumps([s.model_dump(mode='json') for s in self.fields],ensure_ascii=False),self.model,now()))
