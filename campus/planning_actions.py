"""Versioned user-only proposal decisions. No model call is made under a write lock."""
import copy
from .assistance import AssistanceBuffer
from .errors import AppError


def decide(service,conversation_id,user_id,version,proposal_id,decision,fields=None,target_volunteers=...):
    buffer=AssistanceBuffer(service,conversation_id,user_id)
    if buffer.version!=version:raise AppError('草稿已更新，请重新评估后再采纳',409)
    plan=buffer.data.get('plan')
    if not plan or plan['status']!='draft':raise AppError('只能处理未发布的活动方案',409)
    review=plan.get('review')
    if not review or review['base_version']!=version:raise AppError('建议已过期，请重新评估方案',409)
    proposal=next((p for p in review['proposals'] if p['id']==proposal_id),None)
    if not proposal:raise AppError('建议不存在',404)
    if proposal['status']!='pending':raise AppError('该建议已经处理',409)
    if decision=='reject':
        proposal['status']='rejected';review['base_version']=version+1;buffer.dirty=True
    elif decision=='accept':
        patch=proposal['fields'] if fields is None else fields
        target=proposal.get('target_volunteers') if target_volunteers is ... else target_volunteers
        buffer.plan(plan['kind'],patch,target_volunteers=target,clear_target=target_volunteers is None)
        buffer.data['plan']['last_decision']=dict(proposal_id=proposal_id,title=proposal['title'],decision='accepted')
        # All remaining proposals are invalidated by the changed draft.
        if buffer.data['plan'].get('review'):
            buffer.data['plan']['review']=None
    else:raise AppError('未知建议操作',422)
    with service.database.connect() as conn:
        conn.execute('BEGIN IMMEDIATE');buffer.save(conn)
    return service.read(conversation_id,user_id)
