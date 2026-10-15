"""以同一数据库快照计算个人任务和下一步，不由模型猜测状态。"""
from urllib.parse import quote
from contextlib import nullcontext

from .schemas import PersonalState, TaskRead, TodoItem
from .service import TaskService, TASK_SELECT


def task_href(task_id: str) -> str:
    return '#/tasks/' + quote(task_id, safe='')


def personal_state(service: TaskService, user_id: str, *, include_completed: bool = False, connection=None) -> PersonalState:
    statement = TASK_SELECT.replace('FROM tasks t', ''' ,
        (SELECT COUNT(*) FROM applications ap WHERE ap.task_id=t.id AND ap.status='pending') pending_count,
        EXISTS(SELECT 1 FROM applications ap WHERE ap.task_id=t.id AND ap.applicant_id=? AND ap.status='pending') my_pending
        FROM tasks t''')
    statement = statement.replace(' FROM tasks t', ''' ,
        (SELECT title FROM task_stages WHERE task_id=t.id AND status!='confirmed' ORDER BY position LIMIT 1) stage_title,
        (SELECT status FROM task_stages WHERE task_id=t.id AND status!='confirmed' ORDER BY position LIMIT 1) stage_status,
        (SELECT responsible_role FROM task_stages WHERE task_id=t.id AND status!='confirmed' ORDER BY position LIMIT 1) stage_role
        FROM tasks t''')
    statement += ''' WHERE t.publisher_id=? OR t.assignee_id=? OR
        EXISTS(SELECT 1 FROM applications ap WHERE ap.task_id=t.id AND ap.applicant_id=? AND ap.status='pending')
        ORDER BY t.created_at DESC,t.id DESC'''
    with (nullcontext(connection) if connection is not None else service.database.connect()) as snapshot:
        if connection is None:snapshot.execute('BEGIN')
        rows = snapshot.execute(statement, (user_id,user_id,user_id,user_id)).fetchall()
        at=service.current_time()
        pending_extensions={r['task_id']:dict(r) for r in snapshot.execute("SELECT * FROM task_changes WHERE status='pending'")}
        settlements={r['task_id']:dict(r) for r in snapshot.execute('SELECT * FROM task_settlements')}

    published, assigned, applied, todos, waiting = [], [], [], [], []
    completed = 0
    for row in rows:
        data = dict(row)
        pending_count, my_pending = data.pop('pending_count'), data.pop('my_pending')
        stage_title,stage_status,stage_role = data.pop('stage_title'),data.pop('stage_status'),data.pop('stage_role')
        task = service.read_row(data,at)
        owner = task.publisher_id == user_id
        assignee = task.assignee_id == user_id
        if task.status == 'withdrawn':
            # 历史在“我的任务”中保留，但下架任务不再生成待办。
            if owner:
                published.append(task)
            continue
        if task.status == 'cancelled':
            (published if owner else assigned).append(task)
            if task.reward_type=='paid' and task.cancellation_settlement_fen and task.cancellation_settlement_fen>0:
                settlement=settlements.get(task.id,{})
                confirmed=settlement.get('payer_confirmed' if owner else 'payee_confirmed',0)
                if not (settlement.get('payer_confirmed') and settlement.get('payee_confirmed')):
                    (waiting if confirmed else todos).append(TodoItem(task_id=task.id,title=task.title,role='publisher' if owner else 'assignee',task_status=task.status,
                        action='wait_for_settlement' if confirmed else 'confirm_settlement',action_label='等待对方确认取消结算' if confirmed else '确认取消结算中的付款' if owner else '确认取消结算中的收款',href=task_href(task.id)))
            continue
        if task.status == 'completed':
            completed += 1
            if include_completed:
                (published if owner else assigned).append(task)
            if task.reward_type=='paid':
                settlement=settlements.get(task.id,{})
                confirmed=settlement.get('payer_confirmed' if owner else 'payee_confirmed',0)
                item=TodoItem(task_id=task.id,title=task.title,role='publisher' if owner else 'assignee',task_status=task.status,
                              action='wait_for_settlement' if confirmed else 'confirm_settlement',action_label='等待对方确认线下结算' if confirmed else '确认线下已付款' if owner else '确认线下已收款',href=task_href(task.id))
                if not (settlement.get('payer_confirmed') and settlement.get('payee_confirmed')):
                    (waiting if confirmed else todos).append(item)
            continue
        if task.status == 'paused':
            (published if owner else assigned).append(task)
            pending=pending_extensions.get(task.id)
            if pending and (owner or assignee):
                own=pending['requester_id']==user_id
                todos.append(TodoItem(task_id=task.id,title=task.title,role='publisher' if owner else 'assignee',task_status=task.status,
                    action='wait_for_change' if own else 'review_change',action_label='等待对方处理协作申请' if own else '确认或拒绝协作申请',href=task_href(task.id)))
            continue
        if owner:
            published.append(task)
            if task.status == 'published':
                action,label,active = ('review_applications','查看并选择接取者',True) if pending_count else ('wait_for_applicant','等待同学申请',False)
                if task.is_expired:action,label,active='extend_deadline','延长已截止任务，或选择下架',True
            elif task.status == 'pending_review':
                action,label,active = 'review_results','验收成果或说明需要补充的内容',True
            else:
                action,label,active = 'wait_for_submission','等待接取者提交成果',False
            role = 'publisher'
        elif assignee:
            assigned.append(task)
            if task.status == 'in_progress':
                action,label,active = 'submit_results','完成任务并提交成果说明',True
            else:
                action,label,active = 'wait_for_review','等待发布者验收',False
            role = 'assignee'
        elif my_pending:
            applied.append(task)
            action,label,active,role = 'wait_for_application','任务已截止，等待发布者延长' if task.is_expired else '等待发布者确认申请',False,'applicant'
        else:
            continue
        if stage_status and task.assignee_id and (owner or assignee):
            responsible = owner if stage_role=='publisher' else assignee
            if stage_status=='submitted':
                action,label,active = ('review_stage',f'验收阶段：{stage_title}',True) if not responsible else ('wait_for_stage_review',f'等待对方验收阶段：{stage_title}',False)
            elif responsible:
                action = {'not_started':'start_stage','in_progress':'submit_stage','changes_requested':'revise_stage'}[stage_status]
                label = {'not_started':'开始阶段','in_progress':'提交阶段成果','changes_requested':'补充阶段成果'}[stage_status]+f'：{stage_title}'
                active = True
            else:
                action,label,active = 'wait_for_stage_submission',f'等待对方完成阶段：{stage_title}',False
        extension=pending_extensions.get(task.id)
        if extension and (owner or assignee):
            own=extension['requester_id']==user_id
            control=extension['kind']!='agreement'
            extra=TodoItem(task_id=task.id,title=task.title,role=role,task_status=task.status,
                          action='wait_for_change' if own else 'review_change',
                          action_label='等待对方处理协作申请' if own and control else '等待对方处理变更申请' if own else '确认或拒绝协作申请' if control else '确认或拒绝变更申请',href=task_href(task.id))
            (waiting if own else todos).append(extra)
        item = TodoItem(task_id=task.id,title=task.title,role=role,task_status=task.status,
                        action=action,action_label=label,href=task_href(task.id))
        (todos if active else waiting).append(item)
    return PersonalState(published=published,assigned=assigned,applied=applied,
                         todos=todos,waiting=waiting,completed_count=completed)
