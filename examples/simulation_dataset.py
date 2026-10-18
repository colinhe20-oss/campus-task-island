"""Replay the documented 50-user campus scenario through existing services.

python -m examples.simulation_dataset generate
python -m examples.simulation_dataset verify --directory .runtime/simulation/<run>
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import random
import re
import secrets
import tempfile
from unittest.mock import patch
from uuid import UUID, uuid4

from campus.activities import ActivityService
from campus.activity_schemas import ActivityCreate, RegistrationReview
from campus.auth import AuthService
from campus.clock import business_time
from campus.db import Database
from campus.discoveries import DiscoveryService
from campus.discovery_schemas import (DiscoveryCreate, DiscoveryEdit,
    DiscoveryCommentInput, DiscoveryStateInput, DiscoveryWithdraw)
from campus.notifications import NotificationService
from campus.schemas import (TaskCreate, RegisterInput, StagePlanInput,
    StageSubmitInput, StageReviewInput, CollaborationRequestInput,
    ExtensionReviewInput, ChangeInput, SettlementInput)
from campus.service import TaskService
from campus.stages import StageService
from campus.volunteers import VolunteerService
from campus.volunteer_schemas import VolunteerCreate, ParticipationInput, HoursInput

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / 'docs' / 'SIMULATION_DATASET.md'
SIMULATION_ROOT = ROOT / '.runtime' / 'simulation'
LOCAL_ZONE = timezone(timedelta(hours=8))
FORMAT_VERSION = 1


def write_json(path, data):
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f'Unsupported JSON value: {type(value).__name__}')
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=encode) + '\n', encoding='utf-8')


def aware_time(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('时间须带时区，例如 2026-10-17T18:00:00+08:00')
    return result.astimezone(LOCAL_ZONE)


def relative(base, expression):
    text = expression.replace('E', '').strip()
    if not re.fullmatch(r'(?:[+-]\d+[dhm])+', text):
        raise ValueError(f'未知时间表达式: {expression}')
    result = base
    for sign, count, unit in re.findall(r'([+-])(\d+)([dhm])', text):
        result += timedelta(**{{'d': 'days', 'h': 'hours', 'm': 'minutes'}[unit]:
                              int(count) * (1 if sign == '+' else -1)})
    return result


@dataclass
class Specification:
    text: str
    rows: dict = field(default_factory=dict)
    stages: list = field(default_factory=list)
    minutes: list = field(default_factory=list)

    @classmethod
    def load(cls, path=SPEC_PATH):
        spec = cls(Path(path).read_text(encoding='utf-8'))
        spec.rows = {kind: [] for kind in 'UTAVD'}
        widths = {'U': 7, 'T': 11, 'A': 10, 'V': 12, 'D': 8}
        for line in spec.text.splitlines():
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            match = re.match(r'^\| ([UTAVD]\d{3}) \|', line)
            if match and len(cells) == widths[match[1][0]]:
                spec.rows[match[1][0]].append(cells)
            elif re.match(r'^\| S\d+ \| T\d{3} \|', line):
                spec.stages.append(cells)
            elif re.match(r'^\| V\d{3}-J\d／U\d{3} \|', line):
                spec.minutes.append(cells)
        for kind, count in [('U', 50), ('T', 50), ('A', 20), ('V', 20), ('D', 30)]:
            keys = [r[0] for r in spec.rows[kind]]
            if len(keys) != count or set(keys) != {f'{kind}{i:03d}' for i in range(1, count + 1)}:
                raise ValueError(f'设计文档{kind}清单不完整／重复，请更新解析器与规格')
        if len(spec.stages) != 12 or len(spec.minutes) != 21:
            raise ValueError('设计文档阶段／时长表结构改变，请更新回放器')
        return spec


@dataclass
class Event:
    at: datetime
    resource: str
    actor: str
    action: str
    data: dict
    sequence: int

    def ordering(self):
        return self.at, 'TAVDU'.index(self.resource[0]), self.resource, self.sequence


class Scenario:
    def __init__(self, spec, observation):
        self.spec = spec
        self.observation = observation
        self.events = []
        self.payloads = {}

    def add(self, at, key, actor, action, **data):
        if not self.observation - timedelta(days=28) <= at <= self.observation:
            raise ValueError(f'操作超出历史窗口: {key} {action} {at}')
        self.events.append(Event(at, key, actor, action, data, len(self.events)))

    def build(self):
        self.tasks()
        self.activities('A')
        self.activities('V')
        self.records()
        self.discoveries()
        for i in range(1, 9):
            self.add(self.observation-timedelta(hours=6), f'U{i:03d}', f'U{i:03d}', 'read_messages')
        return sorted(self.events, key=Event.ordering)

    def tasks(self):
        e = self.observation
        stage_map = {r[1]: r for r in self.spec.stages}
        for row in self.spec.rows['T']:
            key, title, category, owner, location, criteria, reward, mode, deadline, chain, _ = row
            n = int(key[1:])
            group = 0 if n <= 14 else 1 if n <= 30 else 2 if n <= 36 else 3 if n <= 44 else 4
            c = e-timedelta(days=[7, 12, 10, 21, 15][group])+timedelta(minutes=(n-[1,15,31,37,45][group])*5)
            if n in (2, 39):
                c = e-timedelta(days=7 if n == 2 else 21)
            paid = reward != '无'
            body = dict(title='【模拟】'+title, category=category,
                description=f'需要同学协助完成《{title}》：{criteria}；材料由发布者提供，可使用模拟材料，不涉及课程代做或真实个人资料。',
                completion_criteria=criteria, location=location, deadline=relative(e, deadline),
                reward_type='paid' if paid else 'mutual',
                reward_amount_fen=int(reward[1:])*100 if paid else None,
                reward=f'固定报酬{reward[1:]}元，验收后双方线下结算，平台仅记录确认' if paid else '无偿互助，完成后交流方法',
                acceptance_mode='approval' if mode == '申' else 'direct',
                application_requirements=dict(reason='required' if mode == '申' else 'disabled',
                    experience='optional' if mode == '申' else 'disabled', supplement='disabled'))
            if n == 26:
                body.update(deadline=e+timedelta(days=3), completion_criteria='1版300字以内文案')
            self.payloads[key] = body
            self.add(c, key, owner, 'task_create', body=body)
            if n <= 14:
                actors = re.findall(r'U\d{3}', chain)
                for i, actor in enumerate(actors):
                    self.add(c+timedelta(hours=i+1), key, actor, 'task_apply')
                if n == 2:
                    for i, actor in enumerate(('U041', 'U043')):
                        self.add(c+timedelta(hours=5+i), key, actor, 'task_withdraw_application')
                if n in (12, 13):
                    self.add(c+timedelta(days=1), key, owner, 'task_withdraw')
                continue
            assignee = re.search(r'U\d{3}', chain)[0]
            self.add(c+timedelta(hours=1), key, assignee, 'task_apply' if mode == '申' else 'task_claim')
            if n == 24:
                self.add(c+timedelta(minutes=90), key, 'U020', 'task_apply')
            if mode == '申':
                self.add(c+timedelta(hours=2), key, owner, 'task_accept', assignee=assignee)
            if key in stage_map:
                self.stage_events(key, stage_map[key], c, owner, assignee)
            elif 31 <= n <= 44:
                self.add(c+timedelta(days=3), key, assignee, 'task_submit')
                if n == 40:
                    self.add(c+timedelta(days=3,hours=1), key, owner, 'task_review', decision='request_changes', feedback='第3张缺少使用说明，请补充后重交')
                    self.add(c+timedelta(days=4), key, assignee, 'task_submit', summary='已完成5张标牌，已补充第3张使用说明')
                if n >= 37:
                    self.add(c+timedelta(days=4,hours=1 if n == 40 else 0), key, owner, 'task_review', decision='accept')
            if n in (46,47):
                self.control(c+timedelta(days=2), key, assignee, owner, 'pause', '等待模拟材料确认')
            if n == 45:
                self.control(c+timedelta(days=2), key, assignee, owner, 'pause', '等待模拟书目材料')
                self.control(c+timedelta(days=3), key, owner, assignee, 'resume', '模拟材料已补齐')
                self.control(c+timedelta(days=4), key, assignee, owner, 'pause', '等待目录分类确认')
            if n >= 48:
                self.control(c+timedelta(days=3), key, assignee, owner, 'cancel', '范围调整，双方按已完成工作协商取消', amount=2000 if n == 49 else 0 if n == 50 else None)
            if n in (38,40,44,49):
                self.add(c+timedelta(days=4 if n == 49 else 5), key, owner, 'settlement')
                if n in (38,44):
                    self.add(c+timedelta(days=5,hours=1), key, assignee, 'settlement')
            if n == 26:
                self.add(c+timedelta(days=3), key, assignee, 'change_propose', reason='补充活动背景，需要增加比较版本', changes=dict(completion_criteria=criteria,deadline=(e+timedelta(days=5)).isoformat()))
                self.add(c+timedelta(days=3,hours=1), key, owner, 'proposal_approve')
                self.add(e-timedelta(hours=2), key, assignee, 'change_propose', reason='希望留出额外校对时间', changes=dict(deadline=(e+timedelta(days=7)).isoformat()))

    def control(self, at, key, requester, reviewer, action, reason, amount=None):
        self.add(at, key, requester, 'control_propose', control=action, reason=reason, amount=amount)
        self.add(at+timedelta(hours=1), key, reviewer, 'proposal_approve')

    def stage_events(self, key, row, c, owner, assignee):
        plan = int(row[0][1:])
        fields = [dict(title=title, completion_criteria=criteria,
            deadline=relative(self.observation, stamp), responsible_role='assignee')
            for title,criteria,stamp in [('范围核对','列出本任务验收项及输入材料，逐项确认',row[2]),
                ('交付复核','交付任务表验收栏全部内容并说明核对结果',row[3])]]
        self.add(c+timedelta(minutes=30),key,owner,'stage_plan',stages=fields)
        if plan == 4:
            return
        def action(days, who, verb, position, hours=0, **data):
            self.add(c+timedelta(days=days,hours=hours),key,who,'stage_'+verb,position=position,**data)
        action(1,assignee,'start',1)
        if plan in (3,11,12):
            return
        action(2,assignee,'submit',1)
        if plan == 8:
            return
        action(2,owner,'review',1,hours=1,decision='accept')
        if plan == 2:
            return
        action(3,assignee,'start',2)
        if plan in (6,7,9,10):
            action(4,assignee,'submit',2)
        if plan in (6,9,10):
            action(4,owner,'review',2,hours=1,decision='request_changes' if plan==6 else 'accept',
                feedback='字幕第40秒人名为合成代号，请与说明表统一' if plan==6 else '')

    def activities(self, kind):
        e = self.observation
        for row in self.spec.rows[kind]:
            key, owner = row[0], row[3]
            n = int(key[1:]); start = relative(e,row[7]); end = start+timedelta(hours=2)
            unopened = n <= (3 if kind=='A' else 2)
            opens = e+timedelta(days=1) if unopened else e-timedelta(days=10)
            if kind=='A':
                closes = start-timedelta(days=1) if unopened or n in (17,18) else e-timedelta(hours=1) if n in (14,15,16) else e+timedelta(days=1)
            else:
                closes = start-timedelta(days=1) if unopened or n>=14 else e-timedelta(hours=1) if n in (12,13) else e+timedelta(days=1)
            organizations = ['求知科普小组','代码共学小组','纸上读书小组','匠心实践小组','青叶环保小组','光影创作小组','和声交流小组','同行服务小组']
            title = row[1].split('／')[0]
            body = dict(title='【模拟】'+title, description=f'《{title}》的合成演示，按参与要求与岗位说明开展，不使用真实个人资料。',
                organization_name='模拟·'+organizations[int(owner[1:])-1], information_source='模拟组织公告／'+key,
                contact='演示联系代号'+owner+'（无真实联系方式）', starts_at=start,ends_at=end,
                opens_at=opens,closes_at=closes,registration_mode=row[6] if kind=='A' else row[5])
            if kind=='A':
                body.update(location=row[4],capacity=int(row[5]),
                    recognition_tags=[{'二课':'second_class','美育':'aesthetic','形策':'ideological'}[row[2]]],
                    recognition_description=f'模拟{row[2]}参与说明，仅作活动方信息展示，不产生学校正式认定',
                    participation_requirements='本校在读学生；按时到场，遵守现场安排；'+row[1].split('／')[1])
            else:
                role_names = {'图书':['分类整理岗','标签核对岗','阅读引导岗'], '环保':['物料整理岗','宣传引导岗','数据记录岗'],
                    '科普':['展台说明岗','材料准备岗','体验引导岗'], '赛事':['路线引导岗','物资整理岗','信息记录岗'],
                    '引导':['场地导览岗','资料分发岗','问询说明岗']}[row[2]]
                role_work = {'图书':['按模拟目录分类书目','检查分类标签与清单','向参与者说明分类规则'],
                    '环保':['整理演示回收物料','解释模拟分类规则','记录匿名合成统计数量'],
                    '科普':['介绍公开科普材料','整理演示教学材料','引导参与者完成模拟实验'],
                    '赛事':['按模拟路线提示方向','核对虚构物料清单','记录模拟服务安排'],
                    '引导':['介绍公共空间路线','整理并分发模拟资料','解释公开场所信息']}[row[2]]
                body.update(recognition_conditions='活动负责人根据实际参与登记核验分钟数；缺席为0；活动方确认不等于学校认定',
                    jobs=[dict(name=role_names[j],description=role_work[j],requirements='本校在读学生，能全程参加；阅读岗位工作说明',
                        location=row[4],starts_at=start,ends_at=end,capacity=2 if n in (9,10,11) else 3,
                        estimated_minutes=120,estimated_hours_description='预计120分钟，最终按实际参与由活动方核验') for j in range(int(row[6]))])
            self.payloads[key]=body
            self.add(e-timedelta(days=18)+timedelta(hours=(n-1)*4),key,owner,'activity_create',body=body)
            b=e-timedelta(days=9)
            if kind=='A' and n==18:
                for minute,actor,decision in [(0,'U010','reject'),(10,'U012',None),(20,'U014','reject'),(30,'U010','approve'),(40,'U016','approve')]:
                    self.add(b+timedelta(minutes=minute),key,actor,'register')
                    if decision:self.add(b+timedelta(minutes=minute+2),key,owner,'registration_review',participant=actor,decision=decision)
            else:
                chains=[row[8]] if kind=='A' else row[8:8+int(row[6])]
                for j,chain in enumerate(chains):
                    target=key if kind=='A' else key+f'-J{j+1}'
                    for i,(code,actor) in enumerate(re.findall(r'([rpjwx])(U\d{3})',chain)):
                        at=b+timedelta(minutes=i*10)
                        self.add(at,target,actor,'register')
                        if body['registration_mode']=='review' and code in ('r','w','j'):
                            self.add(at+timedelta(minutes=2),target,owner,'registration_review',participant=actor,decision='reject' if code=='j' else 'approve')
                        if code=='x':self.add(at+timedelta(minutes=3),target,actor,'registration_cancel')
            if kind=='A' and n==11:
                self.add(b+timedelta(hours=1),key,'U009','registration_cancel')
            if kind=='V' and n==3:
                self.add(b+timedelta(hours=1),key+'-J1','U009','registration_cancel')
                self.add(b+timedelta(hours=1,minutes=5),key+'-J2','U009','register')
            if n in (19,20):
                at=start+timedelta(minutes=50) if kind=='V' and n==20 else e-timedelta(days=1)
                self.add(at,key,owner,'activity_cancel')

    def records(self):
        owners={r[0]:r[3] for r in self.spec.rows['V']}
        for row in self.spec.minutes:
            job,actor=row[0].split('／');key=job[:4];version=int(row[3].split('／')[0])
            if version==0:continue
            actual=int(row[1]);confirmed=None if row[2]=='null' else int(row[2])
            start=self.payloads[key]['starts_at'];end=self.payloads[key]['ends_at']
            at=self.observation-timedelta(minutes=10) if key in ('V014','V015') else start+timedelta(minutes=60) if key=='V020' else end+timedelta(minutes=10)
            initial=120 if job=='V017-J1' and actor=='U009' else actual
            self.add(at,job,owners[key],'participation',participant=actor,actual=initial,attendance='absent' if 'absent' in row[4] else 'participated')
            first_confirmation=120 if job=='V017-J1' and actor=='U009' else 100 if job=='V017-J2' and actor=='U011' else confirmed
            if first_confirmation is not None:
                self.add(at+timedelta(minutes=10),job,owners[key],'hours',participant=actor,minutes=first_confirmation,reason='未实际参与，不予计时' if first_confirmation==0 else '')
            if job=='V017-J1' and actor=='U009':
                self.add(at+timedelta(minutes=20),job,owners[key],'participation',participant=actor,actual=110,attendance='participated',reason='核对后扣除10分钟非服务时间')
            if job=='V017-J2' and actor=='U011':
                self.add(at+timedelta(minutes=20),job,owners[key],'hours',participant=actor,minutes=90,reason='扣除未实际服务的休息时间')

    def discoveries(self):
        for row in self.spec.rows['D']:
            key,title,category,owner,location,description,comments,chain=row
            c=self.observation-timedelta(days=8)+timedelta(hours=(int(key[1:])-1)*4)
            body=dict(title='【模拟】'+title,category=category,location=location,
                description=description.split('／')[0]+'。本条为模拟记录，状态由发布者自报',
                discovered_at=c-timedelta(minutes=30),information_source='虚构校园观察／'+key+'，仅供模拟演示',image_ids=[])
            self.payloads[key]=body
            self.add(c,key,owner,'discovery_create',body=body)
            for i,actor in enumerate(re.findall(r'U\d{3}',comments)):
                self.add(c+timedelta(hours=i+1),key,actor,'comment',content=description.split('／')[1]+('；补充观察，建议发布者复核' if i else ''))
            if '编辑' in chain or key=='D030':self.add(c+timedelta(hours=3),key,owner,'discovery_edit')
            states=re.findall(r'(?<![a-z_])(?:unverified|verified|reported|in_progress|resolved|valid|invalid|visible|expired)(?![a-z_])',chain)
            for i,status in enumerate(states[1:]):
                self.add(c+timedelta(days=1,hours=i),key,owner,'discovery_state',status=status)
            if '撤回' in chain:self.add(c+timedelta(days=2),key,owner,'discovery_withdraw')


class Replay:
    def __init__(self, database, observation):
        self.db=database
        self.time=observation-timedelta(days=28)
        clock=lambda:self.time
        self.auth=AuthService(database)
        self.tasks=TaskService(database,clock)
        self.stages=StageService(self.tasks)
        self.activities=ActivityService(database,clock)
        self.volunteers=VolunteerService(database,clock)
        self.discoveries=DiscoveryService(database,clock)
        self.messages=NotificationService(database)
        self.refs={};self.log=[]

    def remember(self, prefix, identifier):
        attempt=1
        while f'{prefix}/{attempt}' in self.refs:
            attempt+=1
        self.refs[f'{prefix}/{attempt}']=identifier
        return identifier

    def run(self,event):
        self.time=event.at
        key,actor,action,data=event.resource,self.refs[event.actor],event.action,event.data
        identifier=self.refs.get(key)
        task_key=key[:4]
        if action=='task_create':self.refs[key]=self.tasks.create_task(TaskCreate(**data['body']),actor).id
        elif action=='task_apply':
            r=self.tasks.apply(identifier,actor,reason='我愿意按本任务验收要求完成，可在截止前交付',experience='具备名册所列相关技能')
            self.refs[f'{key}/{event.actor}']=r.id
            self.remember(f'{key}/{event.actor}',r.id)
        elif action=='task_claim':
            self.tasks.claim(identifier,actor,confirmed=True)
            application=self.tasks.workspace(identifier,actor).applications[0]
            self.refs[f'{key}/{event.actor}']=application.id
            self.remember(f'{key}/{event.actor}',application.id)
        elif action=='task_accept':self.tasks.accept_application(self.refs[f"{key}/{data['assignee']}"],actor)
        elif action=='task_withdraw_application':self.tasks.withdraw_application(self.refs[f'{key}/{event.actor}'],actor)
        elif action=='task_withdraw':self.tasks.withdraw(identifier,actor)
        elif action=='task_submit':
            submitted=self.tasks.submit(identifier,actor,data.get('summary','已完成：'+self.tasks.get_task(identifier).completion_criteria+'；请按约定核对'),self.tasks.get_task(identifier).collaboration_version)
            self.remember(f'{key}/submission/{event.actor}',submitted.id)
        elif action=='task_review':self.tasks.review(identifier,actor,data['decision'],data.get('feedback',''),self.tasks.get_task(identifier).collaboration_version)
        elif action=='stage_plan':
            panel=self.stages.set_plan(identifier,actor,StagePlanInput(expected_version=0,stages=data['stages']))
            for i,stage in enumerate(panel.stages,1):self.refs[f'{key}-S{i}']=stage.id
        elif action in ('stage_start','stage_submit','stage_review'):
            stage=self.stages.read(identifier,actor).stages[data['position']-1]
            self.refs[key+f"-S{data['position']}"]=stage.id
            if action=='stage_start':self.stages.start(identifier,stage.id,actor,stage.version)
            elif action=='stage_submit':
                panel=self.stages.submit(identifier,stage.id,actor,StageSubmitInput(version=stage.version,summary='已完成本阶段约定要求，请按清单核对'))
                self.remember(f"{key}-S{data['position']}/submission/{event.actor}",panel.stages[data['position']-1].submissions[0].id)
            else:self.stages.review(identifier,stage.id,actor,StageReviewInput(version=stage.version,decision=data['decision'],feedback=data.get('feedback','')))
        elif action in ('control_propose','change_propose'):
            task=self.tasks.get_task(identifier)
            if action=='control_propose':
                body=CollaborationRequestInput(action=data['control'],version=task.terms_version,collaboration_version=task.collaboration_version,
                    reason=data['reason'],extend_deadline=False,cancellation_settlement_fen=data['amount'])
                self.tasks.terms.changes.propose_control(identifier,actor,body)
            else:self.tasks.terms.changes.propose(identifier,actor,ChangeInput(version=task.terms_version,reason=data['reason'],changes=data['changes']))
            proposal=next(r for r in self.tasks.terms.changes.read(identifier,actor)['items'] if r['status']=='pending')
            self.remember(key+'/change',proposal['id'])
        elif action=='proposal_approve':
            pending=next(r for r in self.tasks.terms.changes.read(identifier,actor)['items'] if r['status']=='pending')
            self.tasks.terms.changes.decide(pending['id'],actor,ExtensionReviewInput(version=pending['version'],decision='approve'))
        elif action=='settlement':self.tasks.terms.confirm(identifier,actor,SettlementInput(version=self.tasks.terms.settlement(identifier,actor)['version'],confirmed=True))
        elif action=='activity_create':
            if key[0]=='A':self.refs[key]=self.activities.create(ActivityCreate(**data['body']),actor)['id']
            else:
                created=self.volunteers.create(VolunteerCreate(**data['body']),actor)
                self.refs[key]=created['id']
                for i,job in enumerate(created['jobs'],1):self.refs[key+f'-J{i}']=job['id']
        elif action=='register':
            service=self.activities if key[0]=='A' else self.volunteers
            r=service.register(identifier,actor,'我已阅读活动及岗位要求，愿按时参加并完成准备')
            latest=f'{key}/{event.actor}';self.refs[latest]=r['id']
            # Keep both attempts for cancelled/re-applied accounts and job switches.
            self.remember(latest,r['id'])
        elif action in ('registration_review','registration_cancel'):
            service=self.activities if key[0]=='A' else self.volunteers
            participant=data.get('participant',event.actor);rid=self.refs[f'{key}/{participant}']
            if action=='registration_cancel':service.cancel_registration(rid,actor)
            else:service.review(rid,actor,RegistrationReview(decision=data['decision'],reason='申请说明未满足本场准备要求' if data['decision']=='reject' else ''))
        elif action=='activity_cancel':
            service=self.activities if key[0]=='A' else self.volunteers
            service.cancel_activity(identifier,actor,'模拟场地临时关闭，提前结束' if key=='V020' else '模拟场地调整，本场取消')
        elif action in ('participation','hours'):
            rid=self.refs[f"{key}/{data['participant']}"]
            with self.db.connect() as conn:row=conn.execute('SELECT version FROM volunteer_participation WHERE registration_id=?',(rid,)).fetchone()
            version=row[0] if row else 0
            body=ParticipationInput(version=version,attendance=data['attendance'],actual_minutes=data['actual'],description='按岗位工作说明登记实际服务／未到场',reason=data.get('reason','')) if action=='participation' else HoursInput(version=version,confirmed_minutes=data['minutes'],reason=data['reason'])
            self.volunteers.update_record(rid,actor,body)
        elif action=='discovery_create':self.refs[key]=self.discoveries.create(DiscoveryCreate(**data['body']),actor)['id']
        elif action=='comment':
            comment=self.discoveries.comment(identifier,actor,DiscoveryCommentInput(content=data['content']))
            self.remember(f'{key}/comment/{event.actor}',comment['id'])
        elif action in ('discovery_edit','discovery_state','discovery_withdraw'):
            old=self.discoveries.detail(identifier,actor);version=old['version']
            if action=='discovery_edit':
                body={k:old[k] for k in DiscoveryCreate.model_fields if k!='category'}
                body['description']+='；已补充具体位置'
                self.discoveries.edit(identifier,actor,DiscoveryEdit(version=version,**body))
            elif action=='discovery_state':self.discoveries.state(identifier,actor,DiscoveryStateInput(version=version,status=data['status'],reason='根据模拟补充信息，发布者复核后更新'))
            else:self.discoveries.state(identifier,actor,DiscoveryWithdraw(version=version,reason='模拟地点说明有歧义，撤回原文'),withdraw=True)
        elif action=='read_messages':self.messages.read(actor,through_id=self.messages.list(actor)['max_id'])
        else:raise ValueError(f'未知回放操作: {action}')
        self.log.append(dict(at=event.at.isoformat(),resource=key,actor=event.actor,action=action))


def current_directory():
    pointer=SIMULATION_ROOT/'current.json'
    if not pointer.exists():raise ValueError('尚未生成演示库，请先运行 generate 或一键启动脚本')
    directory=Path(json.loads(pointer.read_text(encoding='utf-8'))['directory']).resolve()
    if not directory.is_relative_to(SIMULATION_ROOT.resolve()):raise ValueError('演示库指针必须位于 .runtime/simulation 内')
    return directory


def generate(output=None, *, at=None, seed=20261017, publish_current=True, http_checks=True):
    observation=aware_time(at) if isinstance(at,str) else at or datetime.now(LOCAL_ZONE).replace(second=0,microsecond=0)
    if observation.utcoffset() is None:raise ValueError('观察时间须带时区')
    spec=Specification.load();scenario=Scenario(spec,observation);events=scenario.build()
    directory=Path(output).resolve() if output else SIMULATION_ROOT/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    if directory.exists():raise FileExistsError(f'目标目录已存在，不覆盖现有数据: {directory}')
    directory.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-',dir=directory.parent) as temp:
        staging=Path(temp)/'dataset';staging.mkdir()
        db=Database(staging/'demo.sqlite3');replay=Replay(db,observation)
        rng=random.Random(seed)
        with ExitStack() as stack:
            stack.enter_context(business_time(lambda:replay.time))
            # Scoped deterministic business IDs; credentials remain cryptographically random.
            for module in ('auth','service','stages','terms','changes','activities','volunteers','discoveries'):
                stack.enter_context(patch.object(importlib.import_module('campus.'+module),'uuid4',lambda:UUID(int=rng.getrandbits(128),version=4)))
            db.initialize();replay.auth.provision_demo_accounts()
            credentials=[]
            for row in spec.rows['U']:
                password=secrets.token_urlsafe(14)
                body=RegisterInput(username='sim_'+row[1],display_name='模拟·'+row[2],password=password)
                token,user=replay.auth.register(**body.model_dump());replay.auth.logout(token)
                replay.refs[row[0]]=user.id
                credentials.append(dict(key=row[0],username=user.username,display_name=user.display_name,password=password,profile=row[5]))
            for event in events:
                try:replay.run(event)
                except Exception as exc:
                    raise RuntimeError(f'回放失败: {event.at.isoformat()} {event.resource} {event.actor} {event.action}: {exc}') from exc
            replay.time=observation
        manifest=dict(format_version=FORMAT_VERSION,observation=observation.isoformat(),seed=seed,
            spec_sha256=hashlib.sha256(spec.text.encode()).hexdigest(),
            created_at=datetime.now(timezone.utc).isoformat(),database='demo.sqlite3',credentials='accounts.json',
            ids=replay.refs,events=len(replay.log),simulated_users=50,builtin_users=3)
        write_json(staging/'manifest.json',manifest);write_json(staging/'accounts.json',credentials)
        write_json(staging/'events.json',replay.log)
        from .simulation_verify import verify
        verify(staging,http_checks=http_checks)
        # Every connection is closed before promotion; failed runs never replace an old run.
        staging.replace(directory)
    if publish_current and directory.is_relative_to(SIMULATION_ROOT.resolve()):
        SIMULATION_ROOT.mkdir(parents=True,exist_ok=True)
        pointer=SIMULATION_ROOT/'current.json';temporary=pointer.with_suffix('.tmp')
        write_json(temporary,dict(directory=str(directory)));temporary.replace(pointer)
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    gen=sub.add_parser('generate',help='生成新演示目录并验收，不覆盖已有目录')
    gen.add_argument('--output',type=Path);gen.add_argument('--at',help='带时区的观察时点，默认当前北京时间')
    gen.add_argument('--seed',type=int,default=20261017)
    check=sub.add_parser('verify',help='重新核对演示目录，以原观察时点验收')
    check.add_argument('--directory',type=Path)
    args=parser.parse_args()
    if args.command=='generate':directory=generate(args.output,at=args.at,seed=args.seed)
    else:
        directory=args.directory or current_directory()
        from .simulation_verify import verify
        verify(directory)
    print(f'演示目录: {directory}')
    print(f'验收报告: {directory / "acceptance.md"}')
    print(f'模拟账号: {directory / "accounts.json"}')


if __name__=='__main__':main()
