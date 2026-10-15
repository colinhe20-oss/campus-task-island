"""对话草稿与确认发布：工具先暂存，回复成功后提交，人工确认后创建任务。"""
import json
from datetime import datetime, timezone

from .errors import AppError
from .schemas import DraftFields, TaskCreate, TaskDraftRead
from .service import TaskService, now
from .todos import task_href

REQUIRED_FIELDS = ('title', 'category', 'description', 'completion_criteria', 'location', 'deadline', 'reward_type')


def missing_fields(fields, at=None):
    missing=[field for field in REQUIRED_FIELDS if getattr(fields,field) is None]
    if fields.reward_type=='paid':
        if fields.reward_amount_fen is None:missing.append('reward_amount_fen')
        if not fields.reward:missing.append('reward')
    if fields.deadline and fields.deadline <= (at or datetime.now(timezone.utc)):
        if 'deadline' not in missing:missing.append('deadline')
    return missing


def read_draft(row, at=None) -> TaskDraftRead | None:
    if row is None:
        return None
    fields = DraftFields.model_validate(json.loads(row['fields']))
    missing = missing_fields(fields, at)
    return TaskDraftRead(conversation_id=row['conversation_id'], version=row['version'],
                         status=row['status'], fields=fields, missing_fields=missing,
                         ready=not missing and row['status'] == 'draft',
                         published_task_id=row['published_task_id'],
                         href=task_href(row['published_task_id']) if row['published_task_id'] else None)


class DraftService:
    def __init__(self, service: TaskService):
        self.service = service

    def get(self, conversation_id: str, user_id: str):
        with self.service.database.connect() as connection:
            return read_draft(connection.execute('SELECT * FROM guide_task_drafts WHERE conversation_id=? AND user_id=?',
                                                 (conversation_id,user_id)).fetchone(),self.service.current_time())

    def _owned(self, connection, conversation_id: str, user_id: str):
        conversation = connection.execute('SELECT * FROM guide_conversations WHERE id=? AND user_id=?',
                                          (conversation_id,user_id)).fetchone()
        if conversation is None:
            raise AppError('对话不存在或不属于当前用户',404)
        return conversation

    def publish(self, conversation_id: str, user_id: str, version: int):
        with self.service.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            conversation = self._owned(connection,conversation_id,user_id)
            row = connection.execute('SELECT * FROM guide_task_drafts WHERE conversation_id=? AND user_id=?',
                                     (conversation_id,user_id)).fetchone()
            draft = read_draft(row,self.service.current_time())
            if draft is None:
                raise AppError('还没有任务草稿，请先描述你要发布的任务',409)
            if draft.version != version:
                raise AppError('草稿已更新，请查看最新内容后再确认发布',409)
            if draft.status == 'published':
                task_id = draft.published_task_id
            else:
                if draft.status != 'draft':
                    raise AppError('草稿已取消，请开始新对话再发布任务',409)
                if draft.fields.deadline and draft.fields.deadline <= self.service.current_time():
                    raise AppError('草稿截止时间已过期，请修改后再确认发布',409)
                if not draft.ready:
                    raise AppError('任务草稿尚未完整，请先补齐必填信息',409)
                task = TaskCreate.model_validate(draft.fields.model_dump(mode='json'))
                task_id = self.service.insert_task(connection,task,user_id)
                connection.execute("UPDATE guide_task_drafts SET status='published',published_task_id=?,updated_at=? WHERE conversation_id=?",
                                   (task_id,now(),conversation_id))
                self._append_history(connection,conversation,'确认发布',f'任务已发布：{task.title}。任务编号：{task_id}。')
        return self.service.get_task(task_id)

    def cancel(self, conversation_id: str, user_id: str, version: int):
        with self.service.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            conversation = self._owned(connection,conversation_id,user_id)
            row = connection.execute('SELECT * FROM guide_task_drafts WHERE conversation_id=? AND user_id=?',
                                     (conversation_id,user_id)).fetchone()
            draft = read_draft(row,self.service.current_time())
            if draft is None or draft.version != version:
                raise AppError('草稿不存在或已更新，请刷新后重试',409)
            if draft.status == 'published':
                raise AppError('任务已发布，取消草稿不会撤回已发布任务',409)
            if draft.status != 'cancelled':
                connection.execute("UPDATE guide_task_drafts SET status='cancelled',updated_at=? WHERE conversation_id=?",
                                   (now(),conversation_id))
                self._append_history(connection,conversation,'取消草稿','草稿已取消，尚未发布任务。开始新对话可以整理另一项任务。')
        return self.get(conversation_id,user_id)

    @staticmethod
    def _append_history(connection, conversation, message: str, answer: str):
        history = [*json.loads(conversation['history']),{'role':'user','content':message},
                   {'role':'assistant','content':answer}][-10:]
        connection.execute('UPDATE guide_conversations SET history=?,updated_at=? WHERE id=?',
                           (json.dumps(history,ensure_ascii=False),now(),conversation['id']))


class DraftBuffer:
    """一次模型请求的草稿工作副本；模型失败时不覆盖已保存版本。"""
    def __init__(self, conversation_id: str, baseline: TaskDraftRead | None, clock=None):
        self.clock=clock or (lambda: datetime.now(timezone.utc))
        self.conversation_id = conversation_id
        self.baseline = baseline
        self.fields = baseline.fields.model_copy(deep=True) if baseline else DraftFields()
        self.dirty = False

    def read(self):
        if self.baseline is None and not self.dirty:
            return None
        missing = missing_fields(self.fields,self.clock())
        status = self.baseline.status if self.baseline else 'draft'
        return TaskDraftRead(conversation_id=self.conversation_id,
                             version=(self.baseline.version if self.baseline else 0)+int(self.dirty),
                             status=status,fields=self.fields,missing_fields=missing,
                             ready=not missing and status=='draft',
                             published_task_id=self.baseline.published_task_id if self.baseline else None,
                             href=self.baseline.href if self.baseline else None)

    def update(self, changes: dict):
        if self.baseline and self.baseline.status != 'draft':
            raise AppError('本草稿已发布或取消，请开始新对话整理新的任务',409)
        if not changes:
            raise ValueError('请至少提供一个需要更新的任务字段')
        validated = DraftFields.model_validate(self.fields.model_dump(mode='json') | changes)
        if validated != self.fields:
            self.fields = validated
            self.dirty = True
        return self.read()

    def save(self, connection, user_id: str):
        if not self.dirty:
            return
        current = connection.execute('SELECT version,status FROM guide_task_drafts WHERE conversation_id=?',
                                     (self.conversation_id,)).fetchone()
        if self.baseline:
            if current is None or current['version'] != self.baseline.version or current['status'] != self.baseline.status:
                raise AppError('草稿已被其他请求更新，请重新查看后再修改',409)
        elif current is not None:
            raise AppError('草稿已被其他请求更新，请重新查看后再修改',409)
        draft = self.read()
        connection.execute('''INSERT INTO guide_task_drafts (conversation_id,user_id,fields,version,status,updated_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET
            fields=excluded.fields,version=excluded.version,updated_at=excluded.updated_at''',
            (self.conversation_id,user_id,json.dumps(self.fields.model_dump(mode='json'),ensure_ascii=False),
             draft.version,'draft',now()))
