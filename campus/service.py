"""HTTP 和 Agent 共用的任务查询、发布逻辑。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .db import Database
from .errors import AppError
from .notifications import emit
from .clock import utc_now
from .schemas import (MAX_TASK_OFFSET, Category, TaskCreate, TaskList, TaskRead,
                      TaskStatus, ApplicationInput, ApplicationRead, SubmissionRead, WorkspaceRead, MyTasks)

TASK_SELECT = '''SELECT t.*, p.display_name publisher_name, a.display_name assignee_name
    FROM tasks t LEFT JOIN users p ON p.id=t.publisher_id LEFT JOIN users a ON a.id=t.assignee_id'''


def now() -> str:
    return utc_now().isoformat()


class TaskNotFound(AppError):
    def __init__(self, task_id: str):
        super().__init__('任务不存在', 404)


class TaskService:
    def __init__(self, database: Database, clock=None):
        self.database = database
        self.clock = clock or utc_now
        from .terms import TaskTerms
        self.terms = TaskTerms(self)

    def current_time(self):
        return self.clock().astimezone(timezone.utc)

    def read_row(self, row, at=None):
        return TaskRead.model_validate({**dict(row),'server_time':at or self.current_time()})

    def _check_open(self, task):
        if task['deadline'] and datetime.fromisoformat(task['deadline']) <= self.current_time():
            raise AppError('任务已截止，请等待发布者延长截止时间')

    def initialize(self) -> None:
        self.database.initialize()

    def create_task(self, task: TaskCreate, publisher_id: str | None = None) -> TaskRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task_id = self.insert_task(connection, task, publisher_id)
        return self.get_task(task_id)

    def insert_task(self, connection, task: TaskCreate, publisher_id: str | None = None) -> str:
        """在调用方事务中插入任务，供普通发布和草稿确认共用。"""
        # 所有新增写入，包括 AI 草稿确认，都通过同一必填校验。
        record = TaskCreate.model_validate(task.model_dump(mode='json',include=set(TaskCreate.model_fields))).model_dump(mode='json')
        if task.deadline <= self.current_time():
            raise AppError('截止时间必须晚于服务端当前时间',422)
        record['deadline'] = task.deadline.astimezone(timezone.utc).isoformat()
        record['application_requirements'] = json.dumps(record['application_requirements'], ensure_ascii=False)
        record.update(id=uuid4().hex, status="published",
                      created_at=self.current_time().isoformat(), publisher_id=publisher_id)
        connection.execute("""
            INSERT INTO tasks (id,title,category,description,completion_criteria,
                               location,deadline,reward,status,created_at,publisher_id,acceptance_mode,application_requirements,reward_type,reward_amount_fen)
            VALUES (:id,:title,:category,:description,:completion_criteria,
                    :location,:deadline,:reward,:status,:created_at,:publisher_id,:acceptance_mode,:application_requirements,:reward_type,:reward_amount_fen)
        """, record)
        from .changes import snapshot
        snapshot(connection,self._task(connection,record['id']),record['created_at'],publisher_id)
        return record['id']

    def get_task(self, task_id: str) -> TaskRead:
        with self.database.connect() as connection:
            row = connection.execute(TASK_SELECT + ' WHERE t.id=?', (task_id,)).fetchone()
            stages=connection.execute("SELECT deadline FROM task_stages WHERE task_id=? AND status!='confirmed'",(task_id,)).fetchall()
        if row is None:
            raise TaskNotFound(task_id)
        task=self.read_row(row)
        if task.status in ('in_progress','pending_review'):
            boundaries=[datetime.fromisoformat(r[0]) for r in stages if datetime.fromisoformat(r[0])>task.server_time]
            if task.next_boundary:boundaries.append(task.next_boundary)
            task.next_boundary=min(boundaries) if boundaries else None
        return task

    def copy_source(self,task_id: str,user_id: str) -> TaskRead:
        with self.database.connect() as connection:
            row=connection.execute(TASK_SELECT+' WHERE t.id=?',(task_id,)).fetchone()
        if row is None:raise TaskNotFound(task_id)
        if row['publisher_id']!=user_id:raise AppError('只有原发布者可以复制已取消的任务',403)
        if row['status']!='cancelled':raise AppError('只有已取消的任务可以复制',409)
        return self.read_row(row)

    def search_tasks(self, keyword: str = "", category: Category | str | None = None,
                     limit: int = 20, offset: int = 0, status: TaskStatus | str | None = 'published',
                     *, exclude_completed: bool = False, expired_only: bool = False) -> TaskList:
        if not isinstance(keyword, str) or len(keyword) > 200:
            raise ValueError("keyword 必须是最多 200 字符的文本")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit 必须在 1~50 之间")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= MAX_TASK_OFFSET:
            raise ValueError(f"offset 必须为 0~{MAX_TASK_OFFSET} 之间的整数")
        clauses = ['1=1']
        parameters: list = []
        if exclude_completed:
            clauses.append("t.status != 'completed'")
        if status is not None:
            state = TaskStatus(status)
            if state == TaskStatus.withdrawn:
                clauses.append('t.is_listed=0')
            else:
                clauses.append('t.is_listed=1 AND t.status=?')
                parameters.append(state.value)
        else:
            clauses.append('t.is_listed=1')
        keyword = keyword.strip()
        if keyword:
            # LIKE 中的 % 和 _ 当作用户文字，所有值使用参数绑定。
            escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(t.title LIKE ? ESCAPE '\\' OR t.description LIKE ? ESCAPE '\\' "
                           "OR t.completion_criteria LIKE ? ESCAPE '\\')")
            parameters.extend([f"%{escaped}%"] * 3)
        if category is not None:
            clauses.append("t.category = ?")
            parameters.append(Category(category).value)
        where = " AND ".join(clauses)
        with self.database.connect() as connection:
            # count 和列表在同一个读事务中，避免并发发布导致结果不一致。
            connection.execute("BEGIN")
            rows = connection.execute(TASK_SELECT + f" WHERE {where} ORDER BY t.created_at DESC,t.id DESC",parameters).fetchall()
            at=self.current_time()
            values=[self.read_row(row,at) for row in rows]
            values=[task for task in values if task.is_expired] if expired_only else [task for task in values if not task.is_expired]
            boundaries=[task.next_boundary for task in values if task.next_boundary]
        return TaskList(items=values[offset:offset+limit],total=len(values),limit=limit,offset=offset,
                        server_time=at,next_boundary=min(boundaries) if boundaries else None)

    def _task(self, connection, task_id: str):
        task = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if task is None:
            raise TaskNotFound(task_id)
        return task

    def _validate_application(self, task, fields):
        values = ApplicationInput.model_validate(fields).model_dump(exclude={'request_id'})
        rules = json.loads(task['application_requirements'])
        labels = {'reason':'申请理由','experience':'技能经验','supplement':'补充说明'}
        for key, value in values.items():
            if rules[key] == 'required' and not value:
                raise AppError(f'请填写{labels[key]}',422)
            if rules[key] == 'disabled' and value:
                raise AppError(f'{labels[key]}未启用，请勿填写',422)
        return values

    def apply(self, task_id: str, user_id: str, reason: str = '', experience: str = '', supplement: str = '', request_id: str | None = None) -> ApplicationRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._task(connection, task_id)
            if task['publisher_id'] == user_id:
                raise AppError('不能申请自己发布的任务',403)
            if task['acceptance_mode'] != 'approval':
                raise AppError('本任务采用直接接取，请确认任务条件后接取')
            existing = connection.execute('SELECT id,status FROM applications WHERE task_id=? AND applicant_id=? AND request_id=?',(task_id,user_id,request_id)).fetchone() if request_id else None
            active=connection.execute("SELECT id,status FROM applications WHERE task_id=? AND applicant_id=? AND status IN ('pending','accepted') ORDER BY rowid DESC LIMIT 1",(task_id,user_id)).fetchone()
            latest=connection.execute('SELECT id,status FROM applications WHERE task_id=? AND applicant_id=? ORDER BY rowid DESC LIMIT 1',(task_id,user_id)).fetchone()
            if existing:
                application_id=existing['id']
            elif active or (latest and request_id is None):
                application_id=(active or latest)['id']
            else:
                if not task['is_listed'] or task['status'] != 'published':
                    raise AppError('任务已下架或已被接取，请刷新后查看')
                self._check_open(task)
                values = self._validate_application(task,dict(reason=reason,experience=experience,supplement=supplement))
                application_id = uuid4().hex
                connection.execute('INSERT INTO applications (id,task_id,applicant_id,reason,status,created_at,experience,supplement,request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                    (application_id,task_id,user_id,values['reason'],'pending',self.current_time().isoformat(),values['experience'],values['supplement'],request_id))
                emit(connection,task['publisher_id'],'apply:'+application_id,'task',task_id,'收到新的接取申请',task['title'])
        return next(a for a in self.workspace(task_id,user_id).applications if a.id == application_id)

    def claim(self, task_id, user_id, *, confirmed, reason='', experience='', supplement='', request_id=None):
        if confirmed is not True:
            raise AppError('请确认已阅读任务条件',422)
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._task(connection,task_id)
            if task['publisher_id'] == user_id:
                raise AppError('不能接取自己发布的任务',403)
            if task['acceptance_mode'] != 'direct':
                raise AppError('本任务需要申请后由发布者确认')
            existing = connection.execute("SELECT id FROM applications WHERE task_id=? AND applicant_id=? AND status='accepted'",(task_id,user_id)).fetchone()
            if not existing:
                if not task['is_listed'] or task['status'] != 'published' or task['assignee_id']:
                    raise AppError('任务已下架或已被接取，请刷新后查看')
                self._check_open(task)
                values = self._validate_application(task,dict(reason=reason,experience=experience,supplement=supplement))
                identifier = uuid4().hex
                connection.execute('INSERT INTO applications (id,task_id,applicant_id,reason,status,created_at,experience,supplement) VALUES (?,?,?,?,?,?,?,?)',
                    (identifier,task_id,user_id,values['reason'],'accepted',self.current_time().isoformat(),values['experience'],values['supplement']))
                connection.execute("UPDATE tasks SET status='in_progress',assignee_id=? WHERE id=?",(user_id,task_id))
                emit(connection,task['publisher_id'],'claim-owner:'+identifier,'task',task_id,'任务已被接取',task['title'])
                emit(connection,user_id,'claim-result:'+identifier,'task',task_id,'接取成功',task['title'])
        return self.get_task(task_id)

    def withdraw_application(self, application_id: str, user_id: str):
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row=connection.execute('SELECT * FROM applications WHERE id=?',(application_id,)).fetchone()
            if row is None:raise AppError('申请不存在',404)
            if row['applicant_id']!=user_id:raise AppError('只能撤回自己的申请',403)
            if row['status']!='withdrawn':
                if row['status']!='pending':raise AppError('只有待确认的申请可以撤回；已接取任务请使用协作管理',409)
                task=self._task(connection,row['task_id']);stamp=self.current_time().isoformat()
                connection.execute("UPDATE applications SET status='withdrawn',withdrawn_at=? WHERE id=? AND status='pending'",(stamp,application_id))
                emit(connection,task['publisher_id'],'application-withdrawn:'+application_id,'task',task['id'],'申请者已撤回接取申请',task['title'])
        return next(a for a in self.workspace(row['task_id'],user_id).applications if a.id==application_id)

    def accept_application(self, application_id: str, user_id: str) -> TaskRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            application = connection.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
            if application is None:
                raise AppError('申请不存在',404)
            task = self._task(connection,application['task_id'])
            if task['publisher_id'] != user_id:
                raise AppError('只有发布者能接受申请',403)
            if task['acceptance_mode'] != 'approval':
                raise AppError('直接接取任务无需审核')
            if not task['is_listed'] or task['status'] != 'published' or task['assignee_id'] is not None or application['status'] != 'pending':
                raise AppError('任务或申请状态已变化，请刷新后查看')
            self._check_open(task)
            pending=connection.execute("SELECT id,applicant_id FROM applications WHERE task_id=? AND status='pending'",(task['id'],)).fetchall()
            connection.execute("UPDATE tasks SET status='in_progress',assignee_id=? WHERE id=?",
                               (application['applicant_id'],task['id']))
            connection.execute("UPDATE applications SET status='rejected' WHERE task_id=? AND status='pending'",(task['id'],))
            connection.execute("UPDATE applications SET status='accepted' WHERE id=?",(application_id,))
            for item in pending:
                emit(connection,item['applicant_id'],'application-result:'+item['id'],'task',task['id'],'接取申请已通过' if item['id']==application_id else '任务已选择其他接取者',task['title'])
        return self.get_task(task['id'])

    def withdraw(self, task_id: str, user_id: str) -> TaskRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._task(connection,task_id)
            if task['publisher_id'] != user_id:
                raise AppError('只有发布者能下架任务',403)
            if task['status'] != 'published' or task['assignee_id'] is not None:
                raise AppError('只有尚未接取的任务可以下架',409)
            if task['is_listed']:
                for item in connection.execute("SELECT id,applicant_id FROM applications WHERE task_id=? AND status='pending'",(task_id,)).fetchall():
                    emit(connection,item['applicant_id'],'application-result:'+item['id'],'task',task_id,'任务已下架，申请已结束',task['title'])
                connection.execute('UPDATE tasks SET is_listed=0 WHERE id=?',(task_id,))
                self.terms.close_pending(connection,task_id)
                connection.execute("UPDATE applications SET status='rejected' WHERE task_id=? AND status='pending'",(task_id,))
        return self.get_task(task_id)

    def submit(self, task_id: str, user_id: str, summary: str, collaboration_version: int | None = None) -> SubmissionRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._task(connection,task_id)
            if collaboration_version is not None and collaboration_version!=task['collaboration_version']:
                raise AppError('协作状态已变化，请刷新任务后重新提交',409)
            if task['assignee_id'] != user_id:
                raise AppError('只有接取者能提交成果',403)
            if connection.execute('SELECT 1 FROM task_stage_plans WHERE task_id=?',(task_id,)).fetchone():
                raise AppError('这项任务使用阶段协作，请在阶段面板提交成果',409)
            if task['status'] != 'in_progress':
                raise AppError('当前状态不能提交成果，请刷新查看')
            submission_id = uuid4().hex
            connection.execute('''INSERT INTO submissions (id,task_id,author_id,summary,status,created_at,terms_version)
                VALUES (?,?,?,?,'submitted',?,?)''',(submission_id,task_id,user_id,summary,self.current_time().isoformat(),task['terms_version']))
            self.terms.changes.invalidate(connection,task_id,whole_submission=True)
            connection.execute("UPDATE tasks SET status='pending_review' WHERE id=?",(task_id,))
            emit(connection,task['publisher_id'],'submission:'+submission_id,'task',task_id,'成果已提交，待验收',task['title'])
        return next(s for s in self.workspace(task_id,user_id).submissions if s.id == submission_id)

    def review(self, task_id: str, user_id: str, decision: str, feedback: str, collaboration_version: int | None = None) -> TaskRead:
        if decision not in {'accept','request_changes'} or (decision == 'request_changes' and not feedback.strip()):
            raise AppError('退回时请填写修改说明',422)
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._task(connection,task_id)
            if collaboration_version is not None and collaboration_version!=task['collaboration_version']:
                raise AppError('协作状态已变化，请刷新任务后重新验收',409)
            if task['publisher_id'] != user_id:
                raise AppError('只有发布者能验收',403)
            if connection.execute('SELECT 1 FROM task_stage_plans WHERE task_id=?',(task_id,)).fetchone():
                raise AppError('这项任务使用阶段协作，请逐阶段验收',409)
            if task['status'] != 'pending_review':
                raise AppError('任务当前没有待验收成果')
            submission = connection.execute("SELECT id FROM submissions WHERE task_id=? AND status='submitted'",(task_id,)).fetchone()
            if submission is None:
                raise AppError('未找到待验收成果')
            connection.execute('UPDATE submissions SET status=?,feedback=?,reviewed_at=? WHERE id=?',
                ('accepted' if decision == 'accept' else 'changes_requested',feedback,self.current_time().isoformat(),submission['id']))
            connection.execute('UPDATE tasks SET status=? WHERE id=?',
                ('completed' if decision == 'accept' else 'in_progress',task_id))
            if decision=='accept':self.terms.completed(connection,task_id)
            else:self.terms.changes.invalidate(connection,task_id,whole_submission=True)
            emit(connection,task['assignee_id'],'review:'+submission['id'],'task',task_id,'验收通过，任务已完成' if decision=='accept' else '成果需补充，请查看验收意见',task['title'])
        return self.get_task(task_id)

    def workspace(self, task_id: str, user_id: str) -> WorkspaceRead:
        with self.database.connect() as connection:
            connection.execute('BEGIN')
            task = self._task(connection,task_id)
            owner = task['publisher_id'] == user_id
            arguments = [task_id]
            condition = 'a.task_id=?'
            if not owner:
                condition += ' AND a.applicant_id=?'
                arguments.append(user_id)
            applications = connection.execute('''SELECT a.*,u.display_name applicant_name FROM applications a
                JOIN users u ON u.id=a.applicant_id WHERE '''+condition+' ORDER BY a.rowid DESC',arguments).fetchall()
            submissions = connection.execute('SELECT * FROM submissions WHERE task_id=? ORDER BY created_at DESC,id DESC',
                (task_id,)).fetchall() if owner or task['assignee_id'] == user_id else []
            uses_stages = connection.execute('SELECT 1 FROM task_stage_plans WHERE task_id=?',(task_id,)).fetchone() is not None
        return WorkspaceRead(applications=[ApplicationRead.model_validate(dict(row)) for row in applications],
                             submissions=[SubmissionRead.model_validate(dict(row)) for row in submissions],uses_stages=uses_stages)

    def my_tasks(self, user_id: str) -> MyTasks:
        order = ''' ORDER BY CASE
            WHEN t.is_listed=0 THEN 6
            WHEN t.status='published' THEN 0
            WHEN t.status='in_progress' THEN 1
            WHEN t.status='paused' THEN 2
            WHEN t.status='pending_review' THEN 3
            WHEN t.status='completed' THEN 4
            WHEN t.status='cancelled' THEN 5
            ELSE 6 END, t.created_at DESC,t.id DESC'''
        def query(connection, where):
            return [self.read_row(row) for row in connection.execute(
                TASK_SELECT+' WHERE '+where+order,(user_id,)).fetchall()]
        with self.database.connect() as connection:
            connection.execute('BEGIN')
            return MyTasks(published=query(connection,'t.publisher_id=?'),assigned=query(connection,'t.assignee_id=?'),
                applied=query(connection,"EXISTS(SELECT 1 FROM applications a WHERE a.task_id=t.id AND a.applicant_id=? AND a.status='pending')"),
                application_history=query(connection,"EXISTS(SELECT 1 FROM applications a WHERE a.task_id=t.id AND a.applicant_id=? AND a.status IN ('withdrawn','rejected') AND NOT EXISTS (SELECT 1 FROM applications newer WHERE newer.task_id=a.task_id AND newer.applicant_id=a.applicant_id AND newer.rowid>a.rowid))"))
