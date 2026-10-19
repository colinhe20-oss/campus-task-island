"""Replay the v2 50-user campus scenario (48 志愿 + 48 综素 + 12 任务 + 12 发现) through existing services.

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
from campus.assistance import AssistanceService, Preferences
from campus.auth import AuthService
from campus.clock import business_time
from campus.db import Database
from campus.discoveries import DiscoveryService
from campus.discovery_schemas import (DiscoveryCreate, DiscoveryEdit,
    DiscoveryCommentInput, DiscoveryStateInput, DiscoveryWithdraw)
from campus.matching import MatchingService
from campus.notifications import NotificationService
from campus.schemas import (TaskCreate, RegisterInput, StagePlanInput,
    StageSubmitInput, StageReviewInput, CollaborationRequestInput,
    ExtensionReviewInput, ChangeInput, SettlementInput)
from campus.service import TaskService
from campus.stages import StageService
from campus.volunteers import VolunteerService
from campus.volunteer_schemas import VolunteerCreate, ParticipationInput, HoursInput

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / 'docs' / 'SIMULATION_DATASET_V2_SPEC.md'
SIMULATION_ROOT = ROOT / '.runtime' / 'simulation'
LOCAL_ZONE = timezone(timedelta(hours=8))
FORMAT_VERSION = 2
DATA_REVISION = '2.1'

# These users must remain prospects, including when filling popular events.
STORY_PROSPECTS = {'A008': {'U012', 'U016'}, 'V036': {'U012'},
                   'A036': {'U010', 'U013'}, 'V003': {'U020'},
                   'V024': {'U009'}, 'V017': {'U019'}}
STORY_TIME_SLOTS = {'A036': (5, 9), 'V024': (2, 18), 'V017': (4, 15)}

# 50 人昵称（U001..U050，沿用初版名册）。
ROSTER = ['林知远', '周予安', '沈清禾', '许景行', '陈星澜', '顾南舟', '叶初晴', '江以宁',
          '陆闻溪', '苏映川', '唐书白', '宋晚棠', '程亦航', '梁雨桐', '方时序', '温见月',
          '何沐辰', '白若岚', '郑云帆', '孟知夏', '韩亦可', '罗锦书', '邵星野', '夏语宁',
          '丁墨池', '魏澄', '乔思齐', '袁鹿鸣', '齐晓风', '樊舒然', '戴望舒', '纪泊言',
          '谢听澜', '潘予乐', '姜禾', '于清越', '蓝景', '蒋若水', '傅言蹊', '彭念',
          '蔡小满', '郁星', '柯北', '田雨声', '杭一诺', '汪浅', '童栖', '施晨',
          '钱竹', '安可']

# 组织名映射（U001..U008）。
ORGS = {'U001': '求知科普小组', 'U002': '代码共学小组', 'U003': '纸上读书小组', 'U004': '匠心实践小组',
        'U005': '青叶环保小组', 'U006': '光影创作小组', 'U007': '和声交流小组', 'U008': '同行服务小组'}

# 志愿 7 主题：背景句、岗位模板（J1/J2/J3 名称+工作内容）、岗位附加要求。
VOLUNTEER_THEMES = {
    '书信': ('校园书信公益面向山区儿童开展书信往来与整理回访，',
             [('书信分拣岗', '按模拟地址分拣'), ('书信整理岗', '核对清单与装袋'), ('回访记录岗', '登记匿名回访记录')],
             '无需回信经验，能耐心核对地址与清单。'),
    '图书': ('图书馆开展图书整理与阅读引导服务，',
             [('分类整理岗', '按模拟目录分类'), ('标签核对岗', '核对标签与清单'), ('阅读引导岗', '向参与者说明规则')],
             '熟悉分类标签或愿意按模拟目录操作。'),
    '环保': ('青叶环保小组开展校园低碳与分类实践，',
             [('物料整理岗', '整理演示回收物料'), ('宣传引导岗', '解释模拟分类规则'), ('数据记录岗', '记录匿名合成统计')],
             '愿意整理演示回收物料。'),
    '科普': ('求知科普小组开展公开科普与实验体验，',
             [('展台说明岗', '介绍公开科普材料'), ('材料准备岗', '整理演示教学材料'), ('体验引导岗', '引导完成模拟实验')],
             '能向参与者说明公开科普材料。'),
    '赛事': ('校园赛事期间开展路线引导与物资服务，',
             [('路线引导岗', '按模拟路线提示'), ('物资整理岗', '核对虚构物料清单'), ('信息记录岗', '记录模拟服务安排')],
             '能按模拟路线提示方向或核对物料清单。'),
    '展览': ('学生活动中心展览期间开展布展与导览协助，',
             [('布展协助岗', '协助布置模拟展区'), ('现场引导岗', '引导参观路线'), ('导览讲解岗', '讲解作品说明')],
             '能协助布置展区或引导参观路线。'),
    '引导': ('面向师生开展校园公共空间引导服务，',
             [('场地导览岗', '介绍公共空间路线'), ('资料分发岗', '整理分发模拟资料'), ('问询说明岗', '解释公开场所信息')],
             '熟悉公共空间路线或能分发资料。'),
}

# 综素 7 主题：背景句、参与方式句（固定/自由到场）。
ACTIVITY_THEMES = {
    '画展': ('校园展览馆举办画展参观，', '按时到场参观'),
    '手作': ('学生活动中心开展手作体验，', '按时到场体验'),
    '美育讲座': ('美育中心举办专题讲座，', '按时到场听讲'),
    '游园': ('校园举办文化游园活动，', '开放时段内自主参观'),
    '阅读': ('图书馆开展阅读分享交流，', '按时到场交流'),
    '科创': ('科创中心开展创新实践交流，', '按时到场参与'),
    '体育': ('校园开展体育文化活动，', '开放时段内自主到场'),
}

TAG = {'美育': 'aesthetic', '二课': 'second_class', '形策': 'ideological'}
TAG_DESC = {'美育': '模拟美育参与说明', '二课': '模拟二课参与说明', '形策': '模拟形策参与说明'}

# 16 份偏好档案（第 10.2 节）。weekday 周一=0；starts/ends 为北京时间 HH:MM。
def _wk(day, starts, ends):
    return {'weekday': day, 'starts': starts, 'ends': ends}


PREFERENCES = {
    'U001': dict(skills=['讲解'], interests=['科普'], locations=['紫金港'],
                 weekly_slots=[_wk(2, '18:00', '21:00')], content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U003': dict(skills=['写作'], interests=['书信', '阅读'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U009': dict(skills=['Python', '调试'], interests=['科普'], locations=['紫金港'],
                 weekly_slots=[_wk(2, '18:00', '21:00')], content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U010': dict(skills=['前端'], interests=['科创'], locations=['紫金港'],
                 weekly_slots=[_wk(5, '09:00', '12:00')], content_types=['volunteer', 'activity'], notifications_enabled=False),
    'U011': dict(skills=[], interests=['摄影'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U012': dict(skills=[], interests=['设计', '手作'], locations=['学生活动中心'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U013': dict(skills=['电路'], interests=['科创'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U014': dict(skills=['剪辑', '拍摄'], interests=['摄影', '视频'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U015': dict(skills=['Linux'], interests=['科普'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=False),
    'U016': dict(skills=[], interests=['传统文化'], locations=['紫金港'],
                 content_types=['activity'], notifications_enabled=True),
    'U017': dict(skills=['讲解'], interests=['科普'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U018': dict(skills=[], interests=['翻译', '引导'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U019': dict(skills=[], interests=['数据处理'], locations=['紫金港'],
                 weekly_slots=[_wk(4, '14:00', '17:00')], content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U020': dict(skills=[], interests=['调研', '公益'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U041': dict(skills=[], interests=['学习记录'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
    'U042': dict(skills=[], interests=['科普阅读'], locations=['紫金港'],
                 content_types=['volunteer', 'activity'], notifications_enabled=True),
}


def write_json(path, data):
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f'Unsupported JSON value: {type(value).__name__}')
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=encode) + '\n', encoding='utf-8')


def aware_time(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('时间须带时区，例如 2026-10-19T18:00:00+08:00')
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


def shift(n, e):
    """志愿/综素发布时间 C = E-18d+(编号-1)×4h。"""
    return e - timedelta(days=18) + timedelta(hours=(n - 1) * 4)


def activity_calendar(spec, e):
    """Allocate separate local-time sessions; reserve actual story availability."""
    local = e.astimezone(LOCAL_ZONE)
    def slot(day, hour):
        return local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=day)
    groups = {r[0]: r[8] for r in spec.rows['A']} | {r[0]: r[7] for r in spec.rows['V']}
    ordering = lambda key: (int(key[1:]), key[0])
    history = sorted((key for key, group in groups.items() if group == '已结束'), key=ordering)
    history_slots = [slot(day, hour) for day in range(-7, 0) for hour in (9, 12, 15, 18)]
    if len(history) > len(history_slots):
        raise ValueError('历史活动超过独立场次容量，请调整日历')
    calendar = dict(zip(history, history_slots))
    future = sorted((key for key, group in groups.items() if group not in ('已结束', '进行中', '取消(服务中)')), key=ordering)
    available = [slot(day, hour) for day in range(2, 21) for hour in (9, 12, 15, 18)]
    for key, (weekday, hour) in STORY_TIME_SLOTS.items():
        if key not in future:
            raise ValueError('推荐故事的目标必须为未来场次：' + key)
        chosen = next(at for at in available if at.weekday() == weekday and at.hour == hour)
        calendar[key] = chosen
        available.remove(chosen)
    remaining = [key for key in future if key not in calendar]
    if len(remaining) > len(available):
        raise ValueError('未来活动超过独立场次容量，请调整日历')
    calendar.update(zip(remaining, available))
    return calendar


def window(group, n, e, is_volunteer, *, scheduled_start=None):
    """Keep state boundaries while assigning local sessions independently of E's hour."""
    start = scheduled_start
    if group == '尚未开放':
        opens = (e + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        closes = start - timedelta(days=1)
    elif group.startswith('正在招募') or group == '满额':
        opens = e - timedelta(days=10)
        closes = e + timedelta(days=1)
    elif group == '截止未开始':
        opens = e - timedelta(days=10)
        closes = e - timedelta(hours=1)
    elif group == '进行中':
        opens = e - timedelta(days=10)
        start = e - timedelta(minutes=110 if n == 30 and is_volunteer else 60)
        closes = start - timedelta(days=1)
    elif group == '已结束':
        opens = e - timedelta(days=10)
        closes = start - timedelta(days=1)
    elif group == '取消' or group == '取消(服务中)':
        opens = e - timedelta(days=10)
        if group == '取消(服务中)':
            start = e - timedelta(minutes=100)
        closes = start - timedelta(days=1)
    else:
        raise ValueError(f'未知时间分组: {group}')
    return opens, start, closes, start + timedelta(hours=2)


def chain_codes(text):
    """把报名链解析为 [(code, user), ...]，code ∈ r/p/j/w/x。"""
    return re.findall(r'([rpjwx])(U\d{3})', text)


def fill_pool(used, start=9, end=50):
    """从 U009..U050 取未占用的账号（补齐热/满额场用）。"""
    for i in range(start, end + 1):
        u = f'U{i:03d}'
        if u not in used:
            yield u


@dataclass
class Specification:
    text: str
    rows: dict = field(default_factory=dict)
    minutes: list = field(default_factory=list)

    @classmethod
    def load(cls, path=SPEC_PATH):
        spec = cls(Path(path).read_text(encoding='utf-8'))
        spec.rows = {kind: [] for kind in 'TAVD'}
        widths = {'T': 10, 'A': 10, 'V': 9, 'D': 8}
        for line in spec.text.splitlines():
            match = re.match(r'^\| ([TAVD]\d{3}) \|', line)
            if match:
                cells = [cell.strip() for cell in line.strip('|').split('|')]
                if len(cells) == widths[match[1][0]]:
                    spec.rows[match[1][0]].append(cells)
            elif re.match(r'^\| V\d{3}-J\d/U\d{3} \|', line):
                spec.minutes.append([cell.strip() for cell in line.strip('|').split('|')])
        for kind, count in [('T', 12), ('A', 48), ('V', 48), ('D', 12)]:
            keys = [r[0] for r in spec.rows[kind]]
            if len(keys) != count or set(keys) != {f'{kind}{i:03d}' for i in range(1, count + 1)}:
                raise ValueError(f'设计文档{kind}清单不完整／重复，请更新解析器与规格')
        if len(spec.minutes) != 30:
            raise ValueError(f'设计文档时长表应为 30 行，实际 {len(spec.minutes)}')
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
        self.cancelled = set()  # 开始前取消的场次
        self.calendar = activity_calendar(spec, observation)
        # 时长表指定的志愿报名者岗位：{Vxxx: {Uyyy: 岗位序号(1-based)}}
        self.job_map = {}
        for row in spec.minutes:
            job, user = row[0].split('/')
            key = job[:4]
            idx = int(job.split('-J')[1])
            self.job_map.setdefault(key, {})[user] = idx

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
            self.add(self.observation - timedelta(hours=6), f'U{i:03d}', f'U{i:03d}', 'read_messages')
        return sorted(self.events, key=Event.ordering)

    # ---- 普通任务 12 条 ----
    def tasks(self):
        e = self.observation
        publish = {'T001': e - timedelta(days=5), 'T002': e - timedelta(days=7),
                   'T003': e - timedelta(days=12), 'T004': e - timedelta(days=12),
                   'T008': e - timedelta(days=12), 'T005': e - timedelta(days=10),
                   'T012': e - timedelta(days=10), 'T009': e - timedelta(days=15),
                   'T010': e - timedelta(days=15), 'T006': e - timedelta(days=21),
                   'T007': e - timedelta(days=21), 'T011': e - timedelta(days=21)}
        for row in self.spec.rows['T']:
            key, title_criteria, category, owner, location, reward, mode, deadline, chain, result = row
            title, criteria = title_criteria.split('/', 1)
            n = int(key[1:])
            c = publish[key]
            paid = reward != '无'
            task_deadline = relative(e, deadline)
            body = dict(title='【模拟】' + title, category=category,
                        description=f'需要同学协助完成《{title}》：{criteria}；材料由发布者提供，可使用模拟材料，不涉及课程代做或真实个人资料。',
                        completion_criteria=criteria, location=location, deadline=task_deadline,
                        reward_type='paid' if paid else 'mutual',
                        reward_amount_fen=int(reward[1:]) * 100 if paid else None,
                        reward=f'固定报酬{reward[1:]}元，验收后双方线下结算，平台仅记录确认' if paid else '无偿互助，完成后交流方法',
                        acceptance_mode='approval' if mode == '申' else 'direct',
                        application_requirements=dict(reason='required' if mode == '申' else 'disabled',
                                                      experience='optional' if mode == '申' else 'disabled', supplement='disabled'))
            if key == 'T008':
                body['deadline'] = e + timedelta(days=3)
                body['completion_criteria'] = '1版300字以内文案'
            self.payloads[key] = body
            self.add(c, key, owner, 'task_create', body=body)
            if key == 'T001':
                continue  # P0：发布不产生申请
            if key == 'T002':
                for i, actor in enumerate(('U009', 'U010', 'U041', 'U043')):
                    self.add(c + timedelta(hours=i + 1), key, actor, 'task_apply')
                for i, actor in enumerate(('U041', 'U043')):
                    self.add(c + timedelta(hours=5 + i), key, actor, 'task_withdraw_application')
                continue
            if key == 'T012':
                for i, actor in enumerate(('U017', 'U020')):
                    self.add(c + timedelta(hours=i + 1), key, actor, 'task_apply')
                continue
            assignee = re.search(r'U\d{3}', chain)[0]
            self.add(c + timedelta(hours=1), key, assignee, 'task_apply' if mode == '申' else 'task_claim')
            if mode == '申':
                self.add(c + timedelta(hours=2), key, owner, 'task_accept', assignee=assignee)
            if key in ('T003', 'T004'):
                self.stage_events(key, 'S1' if key == 'T003' else 'S2', c, owner, assignee, task_deadline)
            elif key == 'T007':
                self.add(c + timedelta(days=3), key, assignee, 'task_submit')
                self.add(c + timedelta(days=4), key, owner, 'task_review', decision='accept', feedback='')
                self.add(c + timedelta(days=5), key, owner, 'settlement')
                self.add(c + timedelta(days=5, hours=1), key, assignee, 'settlement')
            elif key == 'T005':
                self.add(c + timedelta(days=3), key, assignee, 'task_submit')
            elif key == 'T006':
                self.add(c + timedelta(days=3), key, assignee, 'task_submit')
                self.add(c + timedelta(days=4), key, owner, 'task_review', decision='accept', feedback='')
            elif key == 'T008':
                self.add(c + timedelta(days=3), key, assignee, 'change_propose',
                         reason='补充活动背景，需要增加比较版本',
                         changes=dict(completion_criteria='2版300字以内文案', deadline=(e + timedelta(days=5)).isoformat()))
                self.add(c + timedelta(days=3, hours=1), key, owner, 'proposal_approve')
                self.add(e - timedelta(hours=2), key, assignee, 'change_propose',
                         reason='希望留出额外校对时间', changes=dict(deadline=(e + timedelta(days=7)).isoformat()))
            elif key == 'T009':
                self.add(c + timedelta(days=2), key, assignee, 'control_propose', control='pause', reason='等待模拟书目材料', amount=None)
                self.add(c + timedelta(days=2, hours=1), key, owner, 'proposal_approve')
                self.add(c + timedelta(days=3), key, owner, 'control_propose', control='resume', reason='模拟材料已补齐', amount=None)
                self.add(c + timedelta(days=3, hours=1), key, assignee, 'proposal_approve')
                self.add(c + timedelta(days=4), key, assignee, 'control_propose', control='pause', reason='等待目录分类确认', amount=None)
                self.add(c + timedelta(days=4, hours=1), key, owner, 'proposal_approve')
            elif key == 'T010':
                self.add(c + timedelta(days=3), key, assignee, 'control_propose', control='cancel',
                         reason='范围调整，双方按已完成整理结算', amount=2000)
                self.add(c + timedelta(days=3, hours=1), key, owner, 'proposal_approve')
                self.add(c + timedelta(days=4), key, owner, 'settlement')
            elif key == 'T011':
                self.add(c + timedelta(days=3), key, assignee, 'control_propose', control='cancel',
                         reason='范围调整，双方同意取消', amount=None)
                self.add(c + timedelta(days=3, hours=1), key, owner, 'proposal_approve')

    def stage_events(self, key, plan, c, owner, assignee, deadline):
        fields = [dict(title='范围核对', completion_criteria='列出本任务验收项及输入材料，逐项确认',
                       deadline=deadline - timedelta(days=3), responsible_role='assignee'),
                  dict(title='交付复核', completion_criteria='交付任务表验收栏全部内容并说明核对结果',
                       deadline=deadline, responsible_role='assignee')]
        self.add(c + timedelta(minutes=30), key, owner, 'stage_plan', stages=fields)
        if plan == 'S2':  # T004 阶段退回
            for days, verb, position in [(1, 'start', 1), (2, 'submit', 1)]:
                self.add(c + timedelta(days=days), key, assignee, 'stage_' + verb, position=position)
            self.add(c + timedelta(days=2, hours=1), key, owner, 'stage_review', position=1, decision='accept', feedback='')
            self.add(c + timedelta(days=3), key, assignee, 'stage_start', position=2)
            self.add(c + timedelta(days=4), key, assignee, 'stage_submit', position=2)
            self.add(c + timedelta(days=4, hours=1), key, owner, 'stage_review', position=2, decision='request_changes',
                     feedback='字幕第40秒人名为合成代号，请与说明表统一')
            return
        # S1（T003）：阶段顺序推进，阶段2 进行中
        self.add(c + timedelta(days=1), key, assignee, 'stage_start', position=1)
        self.add(c + timedelta(days=2), key, assignee, 'stage_submit', position=1)
        self.add(c + timedelta(days=2, hours=1), key, owner, 'stage_review', position=1, decision='accept', feedback='')
        self.add(c + timedelta(days=3), key, assignee, 'stage_start', position=2)

    # ---- 综素 / 志愿活动 ----
    def activities(self, kind):
        e = self.observation
        for row in self.spec.rows[kind]:
            key = row[0]
            n = int(key[1:])
            if kind == 'A':
                title_req, theme, tag_label, owner, location, capacity, mode, group, chain = row[1], row[2], row[3], row[4], row[5], int(row[6]), row[7], row[8], row[9]
                self.activity(key, n, theme, tag_label, owner, location, capacity, mode, group, chain, title_req)
            else:
                title, theme, owner, location, jobs_n, mode, group, chain = row[1], row[2], row[3], row[4], int(row[5]), row[6], row[7], row[8]
                self.volunteer(key, n, theme, owner, location, jobs_n, mode, group, chain, title)

    def activity(self, key, n, theme, tag_label, owner, location, capacity, mode, group, chain, title_req):
        e = self.observation
        title, req = title_req.split('/', 1)
        opens, start, closes, end = window(group, n, e, False, scheduled_start=self.calendar.get(key))
        background, style = ACTIVITY_THEMES[theme]
        free = style.startswith('开放时段')
        description = f'{background}现面向在校学生开展《{title}》，安排在{location}。{style}，{req}。'
        if free:
            participation_requirements = f'本校在读学生；开放时段内自主参观/到场，完成{req}后离场。'
        else:
            participation_requirements = f'本校在读学生；按时到场，遵守现场安排；{req}。'
        body = dict(title='【模拟】' + title, description=description, location=location,
                    starts_at=start, ends_at=end, opens_at=opens, closes_at=closes,
                    capacity=capacity, registration_mode=mode, recognition_tags=[TAG[tag_label]],
                    recognition_description=TAG_DESC[tag_label] + '，仅作活动方信息展示，不产生学校正式认定',
                    organization_name='模拟·' + ORGS[owner], information_source='模拟组织公告／' + key,
                    contact='演示联系代号' + owner + '（无真实联系方式）',
                    participation_requirements=participation_requirements)
        self.payloads[key] = body
        self.add(shift(n, e), key, owner, 'activity_create', body=body)
        b = e - timedelta(days=9)
        codes = chain_codes(chain)
        # 满额/热场补齐 registered 到名额（满额=容量，热=约 70%），补齐者取 U021-U050 未占用账号。
        registered_target = capacity if group == '满额' else max(0, int(capacity * 0.7)) if group.startswith('正在招募') and '热' in group else 0
        have = sum(1 for code, _ in codes if code == 'r')
        used = {u for _, u in codes} | STORY_PROSPECTS.get(key, set())
        fill = []
        if registered_target > have:
            for u in fill_pool(used):
                if len(fill) >= registered_target - have:
                    break
                fill.append(u)
                used.add(u)
        for i, (code, actor) in enumerate(codes + [('r', u) for u in fill]):
            at = b + timedelta(minutes=i * 10)
            self.add(at, key, actor, 'register')
            if mode == 'review' and code in ('r', 'w', 'j'):
                self.add(at + timedelta(minutes=2), key, owner, 'registration_review', participant=actor,
                         decision='reject' if code == 'j' else 'approve')
            if code == 'x':
                self.add(at + timedelta(minutes=3), key, actor, 'registration_cancel')
        if group == '取消':
            self.add(e - timedelta(days=1), key, owner, 'activity_cancel')

    def volunteer(self, key, n, theme, owner, location, jobs_n, mode, group, chain, title):
        e = self.observation
        opens, start, closes, end = window(group, n, e, True, scheduled_start=self.calendar.get(key))
        background, job_templates, extra_req = VOLUNTEER_THEMES[theme]
        description = f'{background}现招募志愿者参与《{title}》，安排在{location}，设{jobs_n}个岗位分工协作。参与同学须阅读岗位工作说明，按时到场，服务结束由活动方按实际参与核验分钟数。不使用真实服务对象资料。'
        jobs = []
        for j in range(jobs_n):
            jname, jwork = job_templates[j]
            if key == 'V036' and j == 2:
                jwork = '讲解模拟手作作品与设计说明'
            if key == 'V017' and j == 2:
                jwork = '整理匿名合成统计，完成数据处理与记录'
            jobs.append(dict(name=jname, description=jwork, requirements='本校在读学生，能全程参加；阅读岗位工作说明。' + extra_req,
                             location=location, starts_at=start, ends_at=end, capacity=3,
                             estimated_minutes=120, estimated_hours_description='预计120分钟，最终按实际参与由活动方核验'))
        body = dict(title='【模拟】' + title, description=description,
                    organization_name='模拟·' + ORGS[owner], information_source='模拟组织公告／' + key,
                    contact='演示联系代号' + owner + '（无真实联系方式）',
                    recognition_conditions='活动负责人根据实际参与登记核验分钟数；缺席为 0；活动方确认不等于学校认定',
                    starts_at=start, ends_at=end, opens_at=opens, closes_at=closes,
                    registration_mode=mode, jobs=jobs)
        self.payloads[key] = body
        self.add(shift(n, e), key, owner, 'activity_create', body=body)
        b = e - timedelta(days=9)
        codes = chain_codes(chain)
        per_job = 3
        used = {u for _, u in codes} | STORY_PROSPECTS.get(key, set())
        fill = []
        fill_per_job = per_job if group == '满额' else per_job - 1
        if jobs_n > 1 and (group == '满额' or '热' in group):
            fill_needed = fill_per_job * (jobs_n - 1)
            for u in fill_pool(used):
                if len(fill) >= fill_needed:
                    break
                fill.append(u)
                used.add(u)
        mapping = self.job_map.get(key, {})
        seq = 0
        for code, actor in codes:
            at = b + timedelta(minutes=seq * 10)
            job_idx = mapping.get(actor, 1)
            target = key + '-J' + str(job_idx)
            self.add(at, target, actor, 'register')
            if mode == 'review' and code in ('r', 'w', 'j'):
                self.add(at + timedelta(minutes=2), target, owner, 'registration_review', participant=actor,
                         decision='reject' if code == 'j' else 'approve')
            if code == 'x':
                self.add(at + timedelta(minutes=3), target, actor, 'registration_cancel')
            seq += 1
        fill_job = 2
        fill_count = 0
        for u in fill:
            at = b + timedelta(minutes=seq * 10)
            job_idx = fill_job
            fill_count += 1
            if fill_count >= fill_per_job:
                fill_job = min(fill_job + 1, jobs_n)
                fill_count = 0
            target = key + '-J' + str(job_idx)
            self.add(at, target, u, 'register')
            if mode == 'review':
                self.add(at + timedelta(minutes=2), target, owner, 'registration_review', participant=u, decision='approve')
            seq += 1
        # V008：U009 换岗退出 J1 后改报 J2（见故事1）。
        if key == 'V008':
            self.add(b + timedelta(hours=1), key + '-J1', 'U009', 'registration_cancel')
            self.add(b + timedelta(hours=1, minutes=5), key + '-J2', 'U009', 'register')
        if group == '取消':
            self.add(e - timedelta(days=1), key, owner, 'activity_cancel')
        elif group == '取消(服务中)':
            self.add(start + timedelta(minutes=50), key, owner, 'activity_cancel')

    # ---- 志愿参与登记与时长 ----
    def records(self):
        owners = {r[0]: r[3] for r in self.spec.rows['V']}
        for row in self.spec.minutes:
            job_user, actual_s, confirmed_s, version_status, note = row
            job, user = job_user.split('/')
            key = job[:4]
            version = int(version_status.split('/')[0])
            if version == 0:
                continue
            start = self.payloads[key]['starts_at']
            end = self.payloads[key]['ends_at']
            at = end + timedelta(minutes=10)
            if key in ('V030', 'V031'):
                at = self.observation - timedelta(minutes=10)
            elif key == 'V048':
                at = start + timedelta(minutes=60)
            owner = owners[key]
            absent = 'absent' in note
            attendance = 'absent' if absent else 'participated'
            # 更正行先登记初始值，再确认，最后更正。
            if key == 'V026' and user == 'U009':
                initial, confirm_value = 120, 120
            elif key == 'V032' and user == 'U007':
                initial, confirm_value = 100, 100
            else:
                initial = int(actual_s)
                confirm_value = None if confirmed_s == 'null' else int(confirmed_s)
            self.add(at, job, owner, 'participation', participant=user, actual=initial, attendance=attendance)
            if confirm_value is not None:
                self.add(at + timedelta(minutes=10), job, owner, 'hours', participant=user, minutes=confirm_value,
                         reason='未实际参与，不予计时' if confirm_value == 0 else '')
            if key == 'V026' and user == 'U009':
                self.add(at + timedelta(minutes=20), job, owner, 'participation', participant=user, actual=110,
                         attendance='participated', reason='核对后扣除10分钟非服务时间')
            if key == 'V032' and user == 'U007':
                self.add(at + timedelta(minutes=20), job, owner, 'hours', participant=user, minutes=90,
                         reason='扣除未实际服务的休息时间')

    # ---- 校园发现 12 条 ----
    def discoveries(self):
        for row in self.spec.rows['D']:
            key, title, category, owner, location, desc, comments, chain = row
            c = self.observation - timedelta(days=8) + timedelta(hours=(int(key[1:]) - 1) * 4)
            body = dict(title='【模拟】' + title, category=category, location=location,
                        description=desc.split('/')[0] + '。本条为模拟记录，状态由发布者自报',
                        discovered_at=c - timedelta(minutes=30), information_source='虚构校园观察／' + key + '，仅供模拟演示', image_ids=[])
            self.payloads[key] = body
            self.add(c, key, owner, 'discovery_create', body=body)
            commenters = re.findall(r'U\d{3}', comments)
            for i, actor in enumerate(commenters):
                self.add(c + timedelta(hours=i + 1), key, actor, 'comment',
                         content=desc.split('/')[1] + ('；补充观察，建议发布者复核' if i else ''))
            if '编辑' in chain:
                self.add(c + timedelta(hours=3), key, owner, 'discovery_edit')
            states = re.findall(r'(?<![a-z_])(?:unverified|verified|reported|in_progress|resolved|valid|invalid|visible|expired)(?![a-z_])', chain)
            for i, status in enumerate(states[1:]):
                self.add(c + timedelta(days=1, hours=i), key, owner, 'discovery_state', status=status)
            if '撤回' in chain:
                self.add(c + timedelta(days=2), key, owner, 'discovery_withdraw')


class Replay:
    def __init__(self, database, observation):
        self.db = database
        self.time = observation - timedelta(days=28)
        clock = lambda: self.time
        self.auth = AuthService(database)
        self.tasks = TaskService(database, clock)
        self.stages = StageService(self.tasks)
        self.activities = ActivityService(database, clock)
        self.volunteers = VolunteerService(database, clock)
        self.discoveries = DiscoveryService(database, clock)
        self.messages = NotificationService(database)
        self.assistance = AssistanceService(self.tasks, self.activities, self.volunteers)
        self.matching = MatchingService(self.tasks, semantics=None)
        self.refs = {}
        self.log = []

    def remember(self, prefix, identifier):
        attempt = 1
        while f'{prefix}/{attempt}' in self.refs:
            attempt += 1
        self.refs[f'{prefix}/{attempt}'] = identifier
        return identifier

    def run(self, event):
        self.time = event.at
        key, actor, action, data = event.resource, self.refs[event.actor], event.action, event.data
        identifier = self.refs.get(key)
        if action == 'task_create':
            self.refs[key] = self.tasks.create_task(TaskCreate(**data['body']), actor).id
        elif action == 'task_apply':
            r = self.tasks.apply(identifier, actor, reason='我愿意按本任务验收要求完成，可在截止前交付', experience='具备名册所列相关技能')
            self.refs[f'{key}/{event.actor}'] = r.id
            self.remember(f'{key}/{event.actor}', r.id)
        elif action == 'task_claim':
            self.tasks.claim(identifier, actor, confirmed=True)
            application = self.tasks.workspace(identifier, actor).applications[0]
            self.remember(f'{key}/{event.actor}', application.id)
        elif action == 'task_accept':
            self.tasks.accept_application(self.refs[f"{key}/{data['assignee']}"], actor)
        elif action == 'task_withdraw_application':
            self.tasks.withdraw_application(self.refs[f'{key}/{event.actor}'], actor)
        elif action == 'task_withdraw':
            self.tasks.withdraw(identifier, actor)
        elif action == 'task_submit':
            submitted = self.tasks.submit(identifier, actor, data.get('summary', '已完成：' + self.tasks.get_task(identifier).completion_criteria + '；请按约定核对'), self.tasks.get_task(identifier).collaboration_version)
            self.remember(f'{key}/submission/{event.actor}', submitted.id)
        elif action == 'task_review':
            self.tasks.review(identifier, actor, data['decision'], data.get('feedback', ''), self.tasks.get_task(identifier).collaboration_version)
        elif action == 'stage_plan':
            panel = self.stages.set_plan(identifier, actor, StagePlanInput(expected_version=0, stages=data['stages']))
            for i, stage in enumerate(panel.stages, 1):
                self.refs[f'{key}-S{i}'] = stage.id
        elif action in ('stage_start', 'stage_submit', 'stage_review'):
            stage = self.stages.read(identifier, actor).stages[data['position'] - 1]
            self.refs[key + f"-S{data['position']}"] = stage.id
            if action == 'stage_start':
                self.stages.start(identifier, stage.id, actor, stage.version)
            elif action == 'stage_submit':
                panel = self.stages.submit(identifier, stage.id, actor, StageSubmitInput(version=stage.version, summary='已完成本阶段约定要求，请按清单核对'))
                self.remember(f"{key}-S{data['position']}/submission/{event.actor}", panel.stages[data['position'] - 1].submissions[0].id)
            else:
                self.stages.review(identifier, stage.id, actor, StageReviewInput(version=stage.version, decision=data['decision'], feedback=data.get('feedback', '')))
        elif action in ('control_propose', 'change_propose'):
            task = self.tasks.get_task(identifier)
            if action == 'control_propose':
                body = CollaborationRequestInput(action=data['control'], version=task.terms_version, collaboration_version=task.collaboration_version,
                                                 reason=data['reason'], extend_deadline=False, cancellation_settlement_fen=data['amount'])
                self.tasks.terms.changes.propose_control(identifier, actor, body)
            else:
                self.tasks.terms.changes.propose(identifier, actor, ChangeInput(version=task.terms_version, reason=data['reason'], changes=data['changes']))
            proposal = next(r for r in self.tasks.terms.changes.read(identifier, actor)['items'] if r['status'] == 'pending')
            self.remember(key + '/change', proposal['id'])
        elif action == 'proposal_approve':
            pending = next(r for r in self.tasks.terms.changes.read(identifier, actor)['items'] if r['status'] == 'pending')
            self.tasks.terms.changes.decide(pending['id'], actor, ExtensionReviewInput(version=pending['version'], decision='approve'))
        elif action == 'settlement':
            self.tasks.terms.confirm(identifier, actor, SettlementInput(version=self.tasks.terms.settlement(identifier, actor)['version'], confirmed=True))
        elif action == 'activity_create':
            if key[0] == 'A':
                self.refs[key] = self.activities.create(ActivityCreate(**data['body']), actor)['id']
            else:
                created = self.volunteers.create(VolunteerCreate(**data['body']), actor)
                self.refs[key] = created['id']
                for i, job in enumerate(created['jobs'], 1):
                    self.refs[key + f'-J{i}'] = job['id']
        elif action == 'register':
            service = self.activities if key[0] == 'A' else self.volunteers
            r = service.register(identifier, actor, '我已阅读活动及岗位要求，愿按时参加并完成准备')
            latest = f'{key}/{event.actor}'
            self.refs[latest] = r['id']
            self.remember(latest, r['id'])
        elif action in ('registration_review', 'registration_cancel'):
            service = self.activities if key[0] == 'A' else self.volunteers
            participant = data.get('participant', event.actor)
            rid = self.refs[f'{key}/{participant}']
            if action == 'registration_cancel':
                service.cancel_registration(rid, actor)
            else:
                service.review(rid, actor, RegistrationReview(decision=data['decision'], reason='申请说明未满足本场准备要求' if data['decision'] == 'reject' else ''))
        elif action == 'activity_cancel':
            service = self.activities if key[0] == 'A' else self.volunteers
            service.cancel_activity(identifier, actor, '模拟场地临时关闭，提前结束' if key == 'V048' else '模拟场地调整，本场取消')
        elif action in ('participation', 'hours'):
            rid = self.refs[f"{key}/{data['participant']}"]
            with self.db.connect() as conn:
                row = conn.execute('SELECT version FROM volunteer_participation WHERE registration_id=?', (rid,)).fetchone()
            version = row[0] if row else 0
            body = ParticipationInput(version=version, attendance=data['attendance'], actual_minutes=data['actual'], description='按岗位工作说明登记实际服务／未到场', reason=data.get('reason', '')) if action == 'participation' else HoursInput(version=version, confirmed_minutes=data['minutes'], reason=data['reason'])
            self.volunteers.update_record(rid, actor, body)
        elif action == 'discovery_create':
            self.refs[key] = self.discoveries.create(DiscoveryCreate(**data['body']), actor)['id']
        elif action == 'comment':
            comment = self.discoveries.comment(identifier, actor, DiscoveryCommentInput(content=data['content']))
            self.remember(f'{key}/comment/{event.actor}', comment['id'])
        elif action in ('discovery_edit', 'discovery_state', 'discovery_withdraw'):
            old = self.discoveries.detail(identifier, actor)
            version = old['version']
            if action == 'discovery_edit':
                body = {k: old[k] for k in DiscoveryCreate.model_fields if k != 'category'}
                body['description'] += '；已补充具体位置'
                self.discoveries.edit(identifier, actor, DiscoveryEdit(version=version, **body))
            elif action == 'discovery_state':
                self.discoveries.state(identifier, actor, DiscoveryStateInput(version=version, status=data['status'], reason='根据模拟补充信息，发布者复核后更新'))
            else:
                self.discoveries.state(identifier, actor, DiscoveryWithdraw(version=version, reason='模拟地点说明有歧义，撤回原文'), withdraw=True)
        elif action == 'read_messages':
            self.messages.read(actor, through_id=self.messages.list(actor)['max_id'])
        else:
            raise ValueError(f'未知回放操作: {action}')
        self.log.append(dict(at=event.at.isoformat(), resource=key, actor=event.actor, action=action))

    def save_preferences(self):
        for user, fields in PREFERENCES.items():
            user_id = self.refs[user]
            data = dict(fields)
            if user == 'U011':
                start = (self.time + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                data['available_slots'] = [{'starts_at': start.isoformat(),
                                            'ends_at': (start + timedelta(hours=2)).isoformat()}]
            if user == 'U042':
                data['valid_until'] = (self.time - timedelta(hours=1)).isoformat()
            prefs = Preferences.model_validate(data)
            self.assistance.save_preferences(user_id, prefs.model_dump(mode='json'), 0)
            self.log.append(dict(at=self.time.isoformat(), resource=user, actor=user, action='save_preferences'))


def current_directory():
    pointer = SIMULATION_ROOT / 'current.json'
    if not pointer.exists():
        raise ValueError('尚未生成演示库，请先运行 generate 或一键启动脚本')
    directory = Path(json.loads(pointer.read_text(encoding='utf-8'))['directory'])
    if not directory.is_absolute():
        directory = SIMULATION_ROOT / directory
    directory = directory.resolve()
    if not directory.is_relative_to(SIMULATION_ROOT.resolve()):
        raise ValueError('演示库指针必须位于 .runtime/simulation 内')
    return directory


def generate(output=None, *, at=None, seed=20261017, publish_current=True, http_checks=True):
    observation = aware_time(at) if isinstance(at, str) else at or datetime.now(LOCAL_ZONE).replace(second=0, microsecond=0)
    if observation.utcoffset() is None:
        raise ValueError('观察时间须带时区')
    observation = observation.astimezone(LOCAL_ZONE)
    spec = Specification.load()
    scenario = Scenario(spec, observation)
    events = scenario.build()
    directory = Path(output).resolve() if output else SIMULATION_ROOT / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    if directory.exists():
        raise FileExistsError(f'目标目录已存在，不覆盖现有数据: {directory}')
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-', dir=directory.parent) as temp:
        staging = Path(temp) / 'dataset'
        staging.mkdir()
        db = Database(staging / 'demo.sqlite3')
        replay = Replay(db, observation)
        rng = random.Random(seed)
        with ExitStack() as stack:
            stack.enter_context(business_time(lambda: replay.time))
            for module in ('auth', 'service', 'stages', 'terms', 'changes', 'activities', 'volunteers', 'discoveries'):
                stack.enter_context(patch.object(importlib.import_module('campus.' + module), 'uuid4', lambda: UUID(int=rng.getrandbits(128), version=4)))
            db.initialize()
            replay.auth.provision_demo_accounts()
            credentials = []
            for i, name in enumerate(ROSTER, 1):
                key = f'U{i:03d}'
                password = secrets.token_urlsafe(14)
                body = RegisterInput(username='sim_u' + f'{i:03d}', display_name='模拟·' + name, password=password)
                token, user = replay.auth.register(**body.model_dump())
                replay.auth.logout(token)
                replay.refs[key] = user.id
                credentials.append(dict(key=key, username=user.username, display_name=user.display_name, password=password))
            for event in events:
                try:
                    replay.run(event)
                except Exception as exc:
                    raise RuntimeError(f'回放失败: {event.at.isoformat()} {event.resource} {event.actor} {event.action}: {exc}') from exc
            replay.time = observation
            replay.save_preferences()
            replay.matching.reconcile()
            with db.connect() as conn:
                recommendation_count = conn.execute("SELECT COUNT(*) FROM opportunity_recommendations WHERE status='recommended'").fetchone()[0]
        manifest = dict(format_version=FORMAT_VERSION, data_revision=DATA_REVISION, observation=observation.isoformat(), seed=seed,
                        spec_sha256=hashlib.sha256(spec.text.encode()).hexdigest(),
                        created_at=datetime.now(timezone.utc).isoformat(), database='demo.sqlite3', credentials='accounts.json',
                        ids=replay.refs, events=len(replay.log), simulated_users=50, builtin_users=3,
                        volunteer_jobs=sum(int(row[5]) for row in spec.rows['V']),
                        preference_users=len(PREFERENCES), recommendations=recommendation_count, minutes=len(spec.minutes))
        write_json(staging / 'manifest.json', manifest)
        write_json(staging / 'accounts.json', credentials)
        write_json(staging / 'events.json', replay.log)
        (staging / 'specification.md').write_text(spec.text, encoding='utf-8')
        write_json(staging / 'calendar.json', {key: {'starts_at': body['starts_at'], 'ends_at': body['ends_at']}
                                              for key, body in scenario.payloads.items() if key[0] in 'AV'})
        with db.connect() as conn:
            write_json(staging / 'snapshot.json', {table: [dict(row) for row in conn.execute('SELECT * FROM ' + table + ' ORDER BY id')]
                for table in ('tasks', 'activities', 'volunteer_activities', 'volunteer_jobs',
                              'activity_registrations', 'volunteer_registrations')})
        from .simulation_verify import verify
        verify(staging, http_checks=http_checks)
        staging.replace(directory)
    if publish_current and directory.is_relative_to(SIMULATION_ROOT.resolve()):
        SIMULATION_ROOT.mkdir(parents=True, exist_ok=True)
        pointer = SIMULATION_ROOT / 'current.json'
        temporary = pointer.with_suffix('.tmp')
        write_json(temporary, dict(directory=str(directory)))
        temporary.replace(pointer)
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('generate', help='生成新演示目录并验收，不覆盖已有目录')
    gen.add_argument('--output', type=Path)
    gen.add_argument('--at', help='带时区的观察时点，默认当前北京时间')
    gen.add_argument('--seed', type=int, default=20261017)
    check = sub.add_parser('verify', help='重新核对演示目录，以原观察时点验收')
    check.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if args.command == 'generate':
        directory = generate(args.output, at=args.at, seed=args.seed)
    else:
        directory = args.directory or current_directory()
        from .simulation_verify import verify
        verify(directory)
    print(f'演示目录: {directory}')
    print(f'验收报告: {directory / "acceptance.md"}')
    print(f'模拟账号: {directory / "accounts.json"}')


if __name__ == '__main__':
    main()
