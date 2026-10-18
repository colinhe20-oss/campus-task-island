"""Deterministic draft checks, stable job identity, diffs and grounded proposals."""
from __future__ import annotations
import copy
import json
from datetime import datetime
from uuid import uuid4, uuid5, NAMESPACE_URL
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


def metadata(plan):
    result=copy.deepcopy(plan)
    jobs=result.get('fields',{}).get('jobs',[])
    if len(result.get('job_ids',[]))!=len(jobs):
        result['job_ids']=[uuid5(NAMESPACE_URL,f"{i}:{json.dumps(j,sort_keys=True,ensure_ascii=False)}").hex for i,j in enumerate(jobs)]
    result.setdefault('target_volunteers',None)
    result.setdefault('changes',[])
    result.setdefault('review',None)
    return result


def job_ids(previous,jobs,provided=None):
    old=metadata(previous) if previous else {'fields':{},'job_ids':[]}
    known=set(old['job_ids'])
    if provided is not None:
        if len(provided)!=len(jobs) or len([x for x in provided if x])!=len(set(x for x in provided if x)):
            raise ValueError('岗位标识必须与岗位列表一一对应且不能重复')
        if any(x and x not in known for x in provided):raise ValueError('岗位标识不属于当前草稿')
        return [x or uuid4().hex for x in provided]
    old_jobs=old['fields'].get('jobs',[]);result=[];used=set()
    for job in jobs:
        matches=[i for i,j in enumerate(old_jobs) if i not in used and j.get('name')==job.get('name')]
        if len(matches)==1:
            i=matches[0];result.append(old['job_ids'][i]);used.add(i)
        else:result.append(None)
    # A single unmatched rename is unambiguous; multiple anonymous replacements
    # are reported as additions/removals rather than inventing identity.
    pending=[i for i,x in enumerate(result) if x is None];remaining=[i for i in range(len(old_jobs)) if i not in used]
    if len(pending)==len(remaining)==1:result[pending[0]]=old['job_ids'][remaining[0]]
    return [x or uuid4().hex for x in result]


def differences(before,after):
    before=metadata(before) if before else {'fields':{},'job_ids':[],'target_volunteers':None}
    after=metadata(after);changes=[]
    def equivalent(a,b):
        if isinstance(a,str) and isinstance(b,str) and 'T' in a and 'T' in b:
            try:return datetime.fromisoformat(a)==datetime.fromisoformat(b)
            except ValueError:pass
        return a==b
    def add(path,a,b,label=None):
        if not equivalent(a,b):changes.append(dict(path=path,before=a,after=b,label=label or path))
    for key in sorted(set(before['fields'])|set(after['fields'])):
        if key!='jobs':add('fields.'+key,before['fields'].get(key),after['fields'].get(key))
    add('target_volunteers',before.get('target_volunteers'),after.get('target_volunteers'),'计划招募总人数')
    old=dict(zip(before['job_ids'],before['fields'].get('jobs',[])));new=dict(zip(after['job_ids'],after['fields'].get('jobs',[])))
    for key in sorted(set(old)|set(new)):
        if key not in old or key not in new:add('jobs.'+key,old.get(key),new.get(key),'岗位新增或移除')
        else:
            for field in sorted(set(old[key])|set(new[key])):add('jobs.'+key+'.'+field,old[key].get(field),new[key].get(field),new[key].get('name',key)+' · '+field)
    if set(before['job_ids'])==set(after['job_ids']) and before['job_ids']!=after['job_ids']:
        add('job_order',[j.get('name','未命名岗位') for j in before['fields'].get('jobs',[])],
            [j.get('name','未命名岗位') for j in after['fields'].get('jobs',[])],'岗位顺序')
    return changes


def checks(plan,at,model):
    from pydantic import ValidationError
    rows=[];fields=plan['fields']
    def problem(code,path,message):rows.append(dict(code=code,path=path,message=message,severity='blocking',source='backend'))
    try:model.model_validate(fields)
    except ValidationError as exc:
        for e in exc.errors():
            path='.'.join(map(str,e['loc']))
            problem(e['type'],path,('请补充 '+path) if e['type']=='missing' else path+'：'+e['msg'].removeprefix('Value error, '))
    def stamp(value):
        try:
            d=datetime.fromisoformat(value)
            return d if d.utcoffset() is not None else None
        except (ValueError,TypeError):return None
    start,end,opens,closes=[stamp(fields.get(k)) for k in ('starts_at','ends_at','opens_at','closes_at')]
    if start and start<=at:problem('activity_past','starts_at','活动开始时间必须晚于当前时间')
    if closes and closes<=at:problem('registration_past','closes_at','报名截止时间必须晚于当前时间')
    if start and end and start>=end:problem('activity_interval','ends_at','活动开始必须早于结束')
    if opens and closes and opens>=closes:problem('registration_interval','closes_at','报名开放必须早于截止')
    if plan['kind']=='activity' and start and closes and closes>start:problem('registration_after_start','closes_at','报名截止不能晚于活动开始')
    jobs=fields.get('jobs',[])
    for i,j in enumerate(jobs):
        prefix=f'jobs.{i}';a,b=stamp(j.get('starts_at')),stamp(j.get('ends_at'))
        if a and b:
            if start and end and not start<=a<b<=end:problem('job_outside_activity',prefix,'岗位 '+str(j.get('name',i+1))+' 的时段超出活动时段')
            if isinstance(j.get('estimated_minutes'),int) and j['estimated_minutes']>(b-a).total_seconds()/60:
                problem('service_minutes_exceeded',prefix+'.estimated_minutes','岗位预计服务分钟超过岗位时长')
        if closes and a and closes>a:problem('registration_after_job',prefix+'.starts_at','报名截止晚于岗位开始')
    target=plan.get('target_volunteers')
    if target is not None and jobs and all(isinstance(j.get('capacity'),int) and not isinstance(j.get('capacity'),bool) for j in jobs):
        actual=sum(j['capacity'] for j in jobs)
        if actual!=target:problem('headcount_mismatch','target_volunteers',f'计划招募 {target} 名志愿者，岗位名额合计 {actual} 人，请核对')
    # Preserve distinct errors but avoid duplicate model-level interval messages.
    return list({(r['code'],r['path'],r['message']):r for r in rows}.values())


class Evidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str=Field(max_length=200)
    value:Any=Field(default=None,description='可省略，由服务端读取当前草稿原值。若提供，必须与字段完整值一致。')


class Proposal(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title:str=Field(min_length=1,max_length=200)
    reason:str=Field(min_length=1,max_length=1500)
    evidence:list[Evidence]=Field(min_length=1,max_length=20)
    fields:dict=Field(default_factory=dict)
    target_volunteers:int|None=Field(default=None,ge=1,le=100000,strict=True)


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    proposals:list[Proposal]=Field(default_factory=list,max_length=15)
    questions:list[str]=Field(default_factory=list,max_length=15)
    rechecks:list[str]=Field(default_factory=list,max_length=15)


def evidence_value(plan,path):
    parts=path.split('.')
    if parts[0]=='jobs' and len(parts)>1:
        plan=metadata(plan)
        if parts[1] not in plan['job_ids']:raise ValueError('建议引用了不存在的岗位')
        value=plan['fields']['jobs'][plan['job_ids'].index(parts[1])]
        parts=parts[2:]
    else:value=plan
    for key in parts:
        if isinstance(value,list):
            if not key.isdigit():raise ValueError('岗位下标必须是非负整数')
            value=value[int(key)]
        else:value=value[key]
    return value


class PlanReviewError(ValueError):
    """Only controlled descriptions and structural paths may enter the trace."""
    def __init__(self,code,message,path):
        super().__init__(message+'（'+path+'）')
        self.public_diagnostic=dict(code=code,message=message,path=path)


def evidence_paths(plan):
    if not plan:return []
    paths=['kind','target_volunteers']
    def visit(value,path):
        paths.append(path)
        if isinstance(value,dict):
            for key,child in value.items():visit(child,path+'.'+key)
        elif isinstance(value,list):
            for i,child in enumerate(value):visit(child,path+'.'+str(i))
    visit(plan.get('fields',{}),'fields')
    for identifier,job in zip(metadata(plan)['job_ids'],plan.get('fields',{}).get('jobs',[])):
        visit(job,'jobs.'+identifier)
    return paths


def validate_review(value,plan,version):
    parsed=Review.model_validate(value)
    result=parsed.model_dump(mode='json')
    for i,proposal in enumerate(result['proposals']):
        for n,e in enumerate(proposal['evidence']):
            location=f'proposals.{i}.evidence.{n}'
            try:actual=evidence_value(plan,e['path'])
            except (KeyError,ValueError,IndexError,TypeError):
                raise PlanReviewError('plan_evidence_missing','建议依据不存在，请重新读取草稿并选择当前可用的依据路径',location+'.path') from None
            supplied=parsed.proposals[i].evidence[n]
            if 'value' in supplied.model_fields_set and actual!=e['value']:
                raise PlanReviewError('plan_evidence_mismatch','建议依据与当前草稿不一致；可省略 value，由服务端读取原值',location+'.value')
            e['value']=copy.deepcopy(actual)
        proposal.update(id=uuid4().hex,status='pending')
    return dict(result,base_version=version)
