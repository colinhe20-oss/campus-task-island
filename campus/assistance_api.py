"""Session-bound, explicitly confirmed activity and preference actions."""
from fastapi import APIRouter, Depends
from pydantic import Field
from .assistance import Preferences, StrictModel


class Confirm(StrictModel):
    version: int = Field(ge=1)
    profile_version: int | None = Field(default=None,ge=0)


class PreferenceUpdate(StrictModel):
    version: int = Field(ge=0)
    fields: Preferences


class PlanUpdate(StrictModel):
    version: int = Field(ge=1)
    fields: dict
    target_volunteers:int|None=Field(default=None,ge=1,le=100000,strict=True)
    job_ids:list[str]|None=None
    clear_target:bool=False


class ProposalDecision(StrictModel):
    version:int=Field(ge=1)
    decision:str=Field(pattern='^(accept|reject)$')
    fields:dict|None=None
    target_volunteers:int|None=Field(default=None,ge=1,le=100000,strict=True)


class Correction(StrictModel):
    version:int=Field(ge=0)
    tag:str
    suppressed:bool=True


def assistance_router(guide,current_user):
    router=APIRouter(prefix='/api/guide',tags=['活动规划与推荐'])
    @router.get('/preferences')
    def preferences(user=Depends(current_user)):
        return guide.assistance.preferences(user.id)

    @router.put('/preferences')
    def update_preferences(body:PreferenceUpdate,user=Depends(current_user)):
        result=guide.assistance.save_preferences(user.id,body.fields.model_dump(mode='json'),body.version)
        guide.matching.reconcile(user.id)
        return result

    @router.get('/assistance/{conversation_id}')
    def read(conversation_id:str,user=Depends(current_user)):
        guide.conversation(conversation_id,user)
        return guide.assistance.read(conversation_id,user.id)

    @router.get('/assistance/{conversation_id}/revisions')
    def revisions(conversation_id:str,user=Depends(current_user)):
        import json
        guide.conversation(conversation_id,user)
        with guide.service.database.connect() as conn:
            rows=conn.execute('SELECT version,changes,created_at FROM guide_plan_revisions WHERE conversation_id=? AND user_id=? ORDER BY version DESC LIMIT 30',(conversation_id,user.id)).fetchall()
        return {'items':[dict(version=r['version'],changes=json.loads(r['changes']),created_at=r['created_at']) for r in rows]}

    @router.put('/assistance/{conversation_id}/plan')
    def edit(conversation_id:str,body:PlanUpdate,user=Depends(current_user)):
        import json
        from .assistance import AssistanceBuffer
        from .errors import AppError
        guide.conversation(conversation_id,user)
        with guide._slot(user.id):
            buffer=AssistanceBuffer(guide.assistance,conversation_id,user.id)
            if buffer.version!=body.version:raise AppError('方案已更新，请刷新',409)
            if not buffer.data['plan']:raise AppError('方案不存在',404)
            try:
                # Complete replacement permits explicit clearing from review page.
                buffer.plan(buffer.data['plan']['kind'],{**{k:None for k in buffer.data['plan']['fields']},**body.fields},
                            target_volunteers=body.target_volunteers,job_ids=body.job_ids,clear_target=body.clear_target)
            except Exception as exc:
                raise AppError('方案字段格式不正确，请检查字段类型与时间格式',422) from exc
            with guide.service.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE');buffer.save(conn)
        return guide.assistance.read(conversation_id,user.id)

    @router.post('/assistance/{conversation_id}/review',status_code=202)
    def review(conversation_id:str,body:Confirm,user=Depends(current_user)):
        from .schemas import GuideInput
        return guide.start(GuideInput(message='请评估当前活动草稿，提出有依据的岗位与人数方案、待确认条件及修改影响，调用 review_activity_plan，不要直接修改正式字段。',
            purpose='activity_review',conversation_id=conversation_id,expected_assistance_version=body.version),user)

    @router.post('/assistance/{conversation_id}/proposals/{proposal_id}')
    def proposal(conversation_id:str,proposal_id:str,body:ProposalDecision,user=Depends(current_user)):
        from .planning_actions import decide
        guide.conversation(conversation_id,user)
        with guide._slot(user.id):
            try:return decide(guide.assistance,conversation_id,user.id,body.version,proposal_id,body.decision,body.fields,
                              body.target_volunteers if 'target_volunteers' in body.model_fields_set else ...)
            except (ValueError,TypeError) as exc:
                from .errors import AppError
                raise AppError('建议修改格式不正确，请核对字段',422) from exc

    @router.get('/semantics/preferences')
    def semantic_preferences(user=Depends(current_user)):
        from .semantics import profile_source,TAGS
        profile=guide.assistance.preferences(user.id)
        result=guide.semantics.read('profile',user.id,profile_source(profile['fields']))
        return dict(result,exclusions=profile['fields'].get('semantic_exclusions',[]),labels={k:v[1] for k,v in TAGS.items()},profile_version=profile['version'])

    @router.post('/semantics/preferences/correction')
    def semantic_correction(body:Correction,user=Depends(current_user)):
        from .semantics import TAGS
        from .errors import AppError
        if body.tag not in TAGS:raise AppError('标签不存在',422)
        profile=guide.assistance.preferences(user.id)
        fields=profile['fields'];exclusions=set(fields.get('semantic_exclusions',[]))
        if body.suppressed:exclusions.add(body.tag)
        else:exclusions.discard(body.tag)
        fields['semantic_exclusions']=sorted(exclusions)
        result=guide.assistance.save_preferences(user.id,fields,body.version)
        guide.matching.reconcile(user.id)
        return result

    def action(conversation_id,body,user,name):
        with guide._slot(user.id):
            result=guide.assistance.action(conversation_id,user.id,body.version,name,body.profile_version)
        if name in ('publish','preferences'):guide.matching.reconcile()
        return result

    @router.post('/assistance/{conversation_id}/publish')
    def publish(conversation_id:str,body:Confirm,user=Depends(current_user)):
        return action(conversation_id,body,user,'publish')

    @router.post('/assistance/{conversation_id}/cancel')
    def cancel(conversation_id:str,body:Confirm,user=Depends(current_user)):
        return action(conversation_id,body,user,'cancel')

    @router.post('/assistance/{conversation_id}/preferences')
    def confirm_preferences(conversation_id:str,body:Confirm,user=Depends(current_user)):
        return action(conversation_id,body,user,'preferences')

    @router.get('/recommendations')
    def recommendations(user=Depends(current_user)):
        return guide.matching.list(user.id)

    @router.post('/recommendations/refresh')
    def refresh(user=Depends(current_user)):
        guide.matching.reconcile(user.id)
        return guide.matching.list(user.id)

    @router.post('/recommendations/{identifier}/dismiss')
    def dismiss(identifier:int,user=Depends(current_user)):
        return guide.matching.dismiss(user.id,identifier)
    return router
