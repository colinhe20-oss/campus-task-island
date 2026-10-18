"""Activity planning and explicitly confirmed participation preferences.

Model tools only modify the per-run buffer. Commit happens with conversation history;
publishing and preference authorization are independent versioned user actions.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, time
from typing import Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .activity_schemas import ActivityCreate
from .volunteer_schemas import VolunteerCreate
from .errors import AppError
from . import planning

STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS guide_assistance (
       conversation_id TEXT PRIMARY KEY REFERENCES guide_conversations(id),
       user_id TEXT NOT NULL REFERENCES users(id), data TEXT NOT NULL,
       version INTEGER NOT NULL, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS participation_preferences (
       user_id TEXT PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL,
       version INTEGER NOT NULL, confirmed_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS opportunity_recommendations (
       id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
       content_type TEXT NOT NULL, resource_id TEXT NOT NULL, job_id TEXT NOT NULL DEFAULT '',
       data TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
       UNIQUE(user_id,content_type,resource_id,job_id))''',
    'CREATE INDEX IF NOT EXISTS idx_recommendations_user ON opportunity_recommendations(user_id,status)',
    '''CREATE TABLE IF NOT EXISTS guide_plan_revisions (
       conversation_id TEXT NOT NULL REFERENCES guide_conversations(id), version INTEGER NOT NULL,
       user_id TEXT NOT NULL REFERENCES users(id), changes TEXT NOT NULL, created_at TEXT NOT NULL,
       PRIMARY KEY(conversation_id,version))''',
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class TimeSlot(StrictModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode='after')
    def valid(self):
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None or self.starts_at >= self.ends_at:
            raise ValueError('可参与时段须带时区，且开始早于结束')
        return self


class WeeklySlot(StrictModel):
    weekday: int = Field(ge=0, le=6, strict=True, description='周一为0，周日为6；北京时间')
    starts: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    ends: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @model_validator(mode='after')
    def valid(self):
        if time.fromisoformat(self.starts) >= time.fromisoformat(self.ends):
            raise ValueError('每周时段开始须早于结束，跨天请拆分')
        return self


class Preferences(StrictModel):
    skills: list[str] = Field(default_factory=list, max_length=30)
    interests: list[str] = Field(default_factory=list, max_length=30)
    locations: list[str] = Field(default_factory=list, max_length=20)
    available_slots: list[TimeSlot] = Field(default_factory=list, max_length=50)
    weekly_slots: list[WeeklySlot] = Field(default_factory=list, max_length=30)
    unavailable_slots: list[TimeSlot] = Field(default_factory=list, max_length=50)
    valid_until: datetime | None = None
    content_types: list[Literal['volunteer', 'activity', 'ordinary']] = Field(default_factory=lambda:['volunteer','activity'], max_length=3)
    notifications_enabled: bool = Field(default=False, strict=True)
    semantic_exclusions: list[str] = Field(default_factory=list,max_length=50)

    @model_validator(mode='after')
    def limits(self):
        from .semantics import TAGS
        if any(tag not in TAGS for tag in self.semantic_exclusions):raise ValueError('只能停用标签表中的语义标签')
        if any(not s or len(s)>100 for s in self.skills+self.interests+self.locations):
            raise ValueError('技能、兴趣、地点须为1至100字')
        if self.valid_until and self.valid_until.utcoffset() is None:
            raise ValueError('偏好有效期须带时区')
        return self


MODELS = {'volunteer': VolunteerCreate, 'activity': ActivityCreate}


def partial_schema(kind):
    schema = copy.deepcopy(MODELS[kind].model_json_schema())
    def walk(node):
        if isinstance(node, dict):
            node.pop('required', None)
            for value in node.values(): walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    walk(schema)
    schema['properties']={k:{'anyOf':[v,{'type':'null'}]} for k,v in schema.get('properties',{}).items()}
    return schema


def inspect_plan(plan, at):
    if not plan:return None
    result=planning.metadata(plan)
    rows=planning.checks(result,at,MODELS[plan['kind']])
    result.update(checks=rows,issues=[r['message'] for r in rows],ready=not rows and plan['status']=='draft')
    result['impacts']=[r for r in rows if r['code'] in ('job_outside_activity','registration_after_job','service_minutes_exceeded','headcount_mismatch','activity_interval','registration_interval','registration_after_start')]
    return result


class AssistanceService:
    def __init__(self, service, activities, volunteers):
        self.service, self.database = service, service.database
        self.activities, self.volunteers = activities, volunteers

    def preferences(self, user_id):
        with self.database.connect() as conn:
            return self.preference_row(conn, user_id)

    @staticmethod
    def preference_row(conn, user_id):
        row = conn.execute('SELECT * FROM participation_preferences WHERE user_id=?',(user_id,)).fetchone()
        return dict(fields=json.loads(row['data']), version=row['version'], confirmed_at=row['confirmed_at']) if row else dict(fields=Preferences().model_dump(mode='json'),version=0,confirmed_at=None)

    def read(self, conversation_id, user_id):
        with self.database.connect() as conn:
            row = conn.execute('SELECT * FROM guide_assistance WHERE conversation_id=? AND user_id=?',(conversation_id,user_id)).fetchone()
        if not row: return None
        data = json.loads(row['data'])
        data['plan'] = inspect_plan(data.get('plan'),self.service.current_time())
        if data['plan'] and data['plan'].get('review'):
            data['plan']['review']['stale']=data['plan']['review']['base_version']!=row['version']
        return dict(data, version=row['version'],conversation_id=conversation_id)

    def action(self, conversation_id, user_id, version, action, expected_profile_version=None):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM guide_assistance WHERE conversation_id=? AND user_id=?',(conversation_id,user_id)).fetchone()
            if not row: raise AppError('草稿不存在',404)
            data = json.loads(row['data'])
            if action=='publish' and (data.get('plan') or {}).get('status')=='published' and version==data['plan'].get('published_from_version'):
                return self.read(conversation_id,user_id)
            if row['version'] != version: raise AppError('草稿已更新，请读取最新版本',409)
            at = self.service.current_time()
            if action == 'publish':
                plan = inspect_plan(data.get('plan'),at)
                if not plan: raise AppError('尚无活动方案',409)
                if plan['status']=='published': return self.read(conversation_id,user_id)
                if not plan['ready']: raise AppError('请先补齐并核对方案：'+'；'.join(plan['issues']),409)
                body = MODELS[plan['kind']].model_validate(plan['fields'])
                target = self.volunteers if plan['kind']=='volunteer' else self.activities
                resource = target.create(body,user_id,connection=conn)
                data['plan'].update(status='published',published_from_version=version,resource_id=resource['id'],href=f"#/{'volunteers' if plan['kind']=='volunteer' else 'activities'}/{resource['id']}")
            elif action == 'cancel':
                if (data.get('plan') or {}).get('status')!='draft': raise AppError('只能取消尚未发布的方案',409)
                data['plan']['status']='cancelled'
            elif action == 'preferences':
                proposal = data.get('preference_proposal')
                if not proposal: raise AppError('尚无偏好草稿',409)
                current = self.preference_row(conn,user_id)
                if current['version'] != expected_profile_version or proposal['base_version'] != current['version']:
                    raise AppError('偏好已经改变，请重新整理并核对草稿',409)
                fields = Preferences.model_validate(proposal['fields']).model_dump(mode='json')
                conn.execute('''INSERT INTO participation_preferences VALUES (?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,version=excluded.version,confirmed_at=excluded.confirmed_at''',
                    (user_id,json.dumps(fields,ensure_ascii=False),current['version']+1,at.isoformat()))
                data['preference_proposal']=None
            else: raise AppError('未知操作',422)
            conn.execute('UPDATE guide_assistance SET data=?,version=version+1,updated_at=? WHERE conversation_id=?',
                         (json.dumps(data,ensure_ascii=False),at.isoformat(),conversation_id))
        return self.read(conversation_id,user_id)

    def save_preferences(self,user_id,fields,version):
        fields = Preferences.model_validate(fields).model_dump(mode='json')
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=self.preference_row(conn,user_id)
            if current['version']!=version: raise AppError('偏好已更新，请刷新后重试',409)
            conn.execute('''INSERT INTO participation_preferences VALUES (?,?,?,?) ON CONFLICT(user_id)
                DO UPDATE SET data=excluded.data,version=excluded.version,confirmed_at=excluded.confirmed_at''',
                (user_id,json.dumps(fields,ensure_ascii=False),version+1,self.service.current_time().isoformat()))
            # A manual preference save supersedes pending proposals from any conversation.
            for row in conn.execute('SELECT * FROM guide_assistance WHERE user_id=?',(user_id,)).fetchall():
                data=json.loads(row['data'])
                if data.get('preference_proposal'):
                    data['preference_proposal']=None
                    conn.execute('UPDATE guide_assistance SET data=?,version=version+1 WHERE conversation_id=?',
                                 (json.dumps(data,ensure_ascii=False),row['conversation_id']))
        return self.preferences(user_id)


class AssistanceBuffer:
    def __init__(self, service, conversation_id,user_id,source_message=''):
        self.service,self.conversation_id,self.user_id=service,conversation_id,user_id
        existing=service.read(conversation_id,user_id)
        self.version=existing['version'] if existing else 0
        self.data={k:copy.deepcopy(existing.get(k)) if existing else None for k in ('plan','preference_proposal')}
        if self.data['plan']:
            for key in ('issues','ready','checks','impacts'):self.data['plan'].pop(key,None)
        self.original_plan=copy.deepcopy(self.data['plan'])
        self.review_only=False
        self.dirty=False
        self.source_message=source_message
        self.explicit={}
        decoder=json.JSONDecoder()
        for match in re.finditer(r'\{',source_message):
            try:
                value,_=decoder.raw_decode(source_message[match.start():])
                if isinstance(value,dict):
                    self.explicit=value
                    break
            except ValueError:pass

    @staticmethod
    def same(left,right):
        if isinstance(left,dict) and isinstance(right,dict):
            return left.keys()==right.keys() and all(AssistanceBuffer.same(v,right[k]) for k,v in left.items())
        if isinstance(left,list) and isinstance(right,list):
            return len(left)==len(right) and all(AssistanceBuffer.same(a,b) for a,b in zip(left,right))
        if isinstance(left,str) and isinstance(right,str) and 'T' in left and 'T' in right:
            try:return datetime.fromisoformat(left)==datetime.fromisoformat(right)
            except ValueError:pass
        return left==right

    def check_explicit(self,fields,allowed):
        expected={k:v for k,v in self.explicit.items() if k in allowed}
        errors=[k for k,v in expected.items() if not ((v is None and fields.get(k) is None) or (k in fields and self.same(fields[k],v)))]
        if errors:
            raise ValueError('用户已明确提供这些字段，工具必须逐项忠实保存，不能遗漏或改写：'+', '.join(errors))
        return expected

    def read(self):
        return dict(self.data,plan=inspect_plan(self.data['plan'],self.service.service.current_time()),
                    version=self.version+int(self.dirty),conversation_id=self.conversation_id)

    def plan(self,kind,fields=None,suggestions=None,checklist=None,target_volunteers=None,job_ids=None,clear_target=False):
        if self.review_only:raise ValueError('当前仅评估方案，请调用 review_activity_plan，不能改动正式字段')
        previous=self.data['plan']
        if previous and previous['status']!='draft': raise ValueError('已发布或已取消，请开始新对话')
        if previous and previous['kind']!=kind: raise ValueError('更换活动类型请开始新对话')
        merged=copy.deepcopy(previous['fields']) if previous else {}
        for key,value in (fields or {}).items():
            if value is None: merged.pop(key,None)
            else: merged[key]=value
        # Explicit structured user fields are authoritative. Project them directly
        # instead of relying on the model to copy dates and nested jobs losslessly.
        for key,value in self.explicit.items():
            if key not in MODELS[kind].model_fields:continue
            if value is None:merged.pop(key,None)
            else:merged[key]=copy.deepcopy(value)
        self.check_explicit(merged,MODELS[kind].model_fields)
        Draft202012Validator(partial_schema(kind),format_checker=FormatChecker()).validate(merged)
        if len(json.dumps(merged,ensure_ascii=False))>25000: raise ValueError('活动方案过长')
        result=planning.metadata(dict(previous or {},kind=kind,fields=merged,status='draft'))
        result['job_ids']=planning.job_ids(previous,merged.get('jobs',[]),job_ids)
        if clear_target:result['target_volunteers']=None
        elif target_volunteers is not None:
            if kind!='volunteer':raise ValueError('计划招募志愿者人数仅用于志愿服务草稿')
            if isinstance(target_volunteers,bool) or not isinstance(target_volunteers,int) or not 1<=target_volunteers<=100000:raise ValueError('计划招募人数须为正整数')
            result['target_volunteers']=target_volunteers
        result['changes']=planning.differences(self.original_plan,result)
        if result['changes']:result['review']=None
        if suggestions is not None: result['suggestions']=suggestions
        if checklist is not None: result['checklist']=checklist
        self.data['plan']=result; self.dirty=True
        return self.read()

    def review(self,value):
        if not self.data['plan'] or self.data['plan']['status']!='draft':raise ValueError('请先创建未发布的活动草稿')
        plan=self.data['plan']
        # The review and history commit at the same resulting assistance version.
        review=planning.validate_review(value,plan,self.version+1)
        from jsonschema import ValidationError as SchemaError
        for i,proposal in enumerate(review['proposals']):
            try:Draft202012Validator(partial_schema(plan['kind']),format_checker=FormatChecker()).validate(proposal['fields'])
            except SchemaError:
                raise planning.PlanReviewError('plan_fields_invalid','建议字段格式不正确，请使用当前活动类型的可编辑字段；人数约束放在 target_volunteers',f'proposals.{i}.fields') from None
        plan['review']=review
        self.dirty=True
        return self.read()

    def preferences(self,changes):
        current=self.service.preferences(self.user_id)
        previous=self.data.get('preference_proposal')
        fields=(previous['fields'] if previous and previous['base_version']==current['version'] else current['fields'])|changes
        expected=self.check_explicit(fields,Preferences.model_fields)
        if expected:
            extras=[k for k,v in changes.items() if k not in expected and not self.same(v,current['fields'].get(k))]
            if extras:raise ValueError('用户未要求变更这些偏好，不能填入示例值：'+', '.join(extras))
        elif self.source_message:
            for key in ('skills','interests','locations'):
                for value in changes.get(key,[]):
                    if value not in current['fields'][key] and value not in self.source_message:
                        raise ValueError('偏好必须依据本轮原话，不得添加用户未提及的'+key+'：'+value)
        fields=Preferences.model_validate(fields).model_dump(mode='json')
        self.data['preference_proposal']=dict(fields=fields,base_version=current['version'])
        self.dirty=True
        return self.read()

    def save(self,conn):
        if not self.dirty:return
        current=conn.execute('SELECT version FROM guide_assistance WHERE conversation_id=?',(self.conversation_id,)).fetchone()
        if (current['version'] if current else 0)!=self.version: raise AppError('方案已被其他操作更新，请重试',409)
        conn.execute('''INSERT INTO guide_assistance VALUES (?,?,?,?,?) ON CONFLICT(conversation_id)
            DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at''',
            (self.conversation_id,self.user_id,json.dumps(self.data,ensure_ascii=False),self.version+1,self.service.service.current_time().isoformat()))
        if self.data['plan']:
            changes=planning.differences(self.original_plan,self.data['plan'])
            if changes:
                conn.execute('INSERT INTO guide_plan_revisions VALUES (?,?,?,?,?)',
                    (self.conversation_id,self.version+1,self.user_id,json.dumps(changes,ensure_ascii=False),self.service.service.current_time().isoformat()))
