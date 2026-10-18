"""任务 API 数据契约。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# SQLite 的 LIMIT/OFFSET 参数使用有符号 64 位整数。
MAX_TASK_OFFSET = (1 << 63) - 1

TASK_CREATE_EXAMPLE = {
    "title": "校园活动摄影",
    "category": "creative",
    "description": "寻找同学协助拍摄社团活动照片",
    "completion_criteria": "交付10张清晰照片",
    "location": "学生活动中心",
    "deadline": "2099-10-20T18:00:00+08:00",
    "reward_type": "mutual",
    "reward": "互助",
}


class Category(str, Enum):
    learning = "learning"
    creative = "creative"
    music = "music"
    daily = "daily"


class ApplicationRequirements(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: Literal['disabled','optional','required'] = 'required'
    experience: Literal['disabled','optional','required'] = 'disabled'
    supplement: Literal['disabled','optional','required'] = 'disabled'


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    acceptance_mode: Literal['approval','direct'] = 'approval'
    application_requirements: ApplicationRequirements = Field(default_factory=ApplicationRequirements)

    @field_validator('application_requirements', mode='before')
    @classmethod
    def decode_requirements(cls, value):
        import json
        value = json.loads(value) if isinstance(value, str) else value
        if isinstance(value, dict) and set(value) != {'reason','experience','supplement'}:
            raise ValueError('请完整设置申请理由、技能经验和补充说明的填写规则')
        return value

    title: str = Field(min_length=1, max_length=100, description="任务标题，必填")
    category: Category = Field(description="任务分类，必填：learning 学习、creative 创作、music 音乐、daily 生活互助")
    description: str = Field(min_length=1, max_length=4000, description="需求说明，必填")
    completion_criteria: str = Field(min_length=1, max_length=2000, description="完成和验收标准，必填")
    location: str = Field(min_length=1, max_length=200, description="任务地点，必填")
    deadline: datetime = Field(description="截止时间，必填且须带时区，如 2026-10-20T18:00:00+08:00")
    reward_type: Literal['mutual','paid']
    reward_amount_fen: int | None = Field(default=None, strict=True, gt=0, le=9007199254740991)
    reward: str | None = Field(default=None, min_length=1, max_length=500, description="回报说明，可省略或填写 null")

    @model_validator(mode='after')
    def reward_rules(self):
        if self.reward_type == 'mutual' and self.reward_amount_fen is not None:
            raise ValueError('无偿互助不能填写金额')
        if self.reward_type == 'paid' and (not self.reward or self.reward_amount_fen is None):
            raise ValueError('有偿任务必须填写明确金额和回报说明')
        return self

    @field_validator("deadline")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("截止时间必须带时区，例如 2026-10-20T18:00:00+08:00")
        return value


class TaskRead(TaskCreate):
    # 历史记录保留原值；新增发布使用更严格的 TaskCreate。
    location: str | None = Field(default=None, min_length=1, max_length=200)
    deadline: datetime | None = None
    reward_type: Literal['mutual','paid','legacy'] = 'legacy'
    terms_version: int = 1
    collaboration_version: int = 1
    paused_from_status: str | None = None
    pause_reason: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancellation_settlement_fen: int | None = None
    cancellation_settlement_reason: str | None = None
    is_expired: bool = False
    is_overdue: bool = False
    can_apply: bool = False
    can_claim: bool = False
    can_accept_application: bool = False
    server_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    next_boundary: datetime | None = None
    id: str
    status: str
    created_at: datetime
    publisher_id: str | None = None
    publisher_name: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    is_listed: bool = True

    @model_validator(mode='after')
    def listing_status(self):
        if not self.is_listed:
            self.status = 'withdrawn'
        expired = bool(self.deadline and self.deadline <= self.server_time)
        self.is_expired = self.status == 'published' and expired
        self.is_overdue = self.status in ('in_progress','pending_review') and expired
        available = self.is_listed and self.status == 'published' and not expired
        self.can_apply = self.can_accept_application = available and self.acceptance_mode == 'approval'
        self.can_claim = available and self.acceptance_mode == 'direct'
        boundaries=[value for value in (self.deadline,self.next_boundary) if value and value>self.server_time]
        self.next_boundary=min(boundaries) if self.status in ('published','in_progress','pending_review') and boundaries else None
        return self


class TaskList(BaseModel):
    server_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    next_boundary: datetime | None = None
    items: list[TaskRead]
    total: int
    limit: int
    offset: int


class TaskStatus(str, Enum):
    published = 'published'
    in_progress = 'in_progress'
    pending_review = 'pending_review'
    completed = 'completed'
    paused = 'paused'
    cancelled = 'cancelled'
    withdrawn = 'withdrawn'


class UserRead(BaseModel):
    can_publish_volunteers: bool = False
    can_publish_activities: bool = False
    id: str
    username: str
    display_name: str


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=6, max_length=128)

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value: str) -> str:
        import re
        normalized = value.strip().lower()
        if not re.fullmatch(r'[a-z0-9._-]{3,32}', normalized):
            raise ValueError('账号需为 3–32 位字母、数字、点、下划线或连字符')
        return normalized

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 40:
            raise ValueError('昵称为 1–40 个字符')
        return value

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 6 or len(value) > 128 or not value.strip():
            raise ValueError('密码需为 6–128 个字符，且不能全为空白')
        return value


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(default='', max_length=2000)
    experience: str = Field(default='', max_length=2000)
    supplement: str = Field(default='', max_length=2000)
    request_id: str | None = Field(default=None, pattern='^[a-fA-F0-9-]{16,64}$')


class ClaimInput(ApplicationInput):
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def strict_confirmation(cls, value):
        if value is not True:
            raise ValueError('请确认已阅读任务条件')
        return value


class ApplicationRead(BaseModel):
    id: str
    task_id: str
    applicant_id: str
    applicant_name: str
    experience: str = ''
    supplement: str = ''
    reason: str
    status: str
    created_at: datetime
    withdrawn_at: datetime | None = None


class SubmissionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=4000)
    collaboration_version: int = Field(default=1, ge=1)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    decision: str = Field(pattern='^(accept|request_changes)$')
    feedback: str = Field(default='', max_length=2000, validate_default=True)
    collaboration_version: int = Field(default=1, ge=1)

    @field_validator('feedback')
    @classmethod
    def require_feedback(cls, value: str, info) -> str:
        if info.data.get('decision') == 'request_changes' and not value:
            raise ValueError('退回补充时必须说明需要修改的内容')
        return value


class SubmissionRead(BaseModel):
    terms_version: int | None = None
    id: str
    task_id: str
    author_id: str
    summary: str
    status: str
    feedback: str | None
    created_at: datetime
    reviewed_at: datetime | None


class WorkspaceRead(BaseModel):
    applications: list[ApplicationRead]
    submissions: list[SubmissionRead]
    uses_stages: bool = False


class MyTasks(BaseModel):
    published: list[TaskRead]
    assigned: list[TaskRead]
    applied: list[TaskRead]
    application_history: list[TaskRead] = Field(default_factory=list)


class TodoItem(BaseModel):
    task_id: str
    title: str
    role: str
    task_status: TaskStatus
    action: str
    action_label: str
    href: str


class PersonalState(BaseModel):
    published: list[TaskRead]
    assigned: list[TaskRead]
    applied: list[TaskRead]
    todos: list[TodoItem]
    waiting: list[TodoItem]
    completed_count: int


class GuideInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')
    task_id: str | None = Field(default=None, min_length=1, max_length=100)
    draft_version: int | None = Field(default=None, ge=1)
    purpose: Literal['chat', 'stage_plan', 'activity_review'] = 'chat'
    expected_assistance_version: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def stage_context(self):
        if self.purpose == 'activity_review' and not self.conversation_id:
            raise ValueError('活动评估必须指定草稿对话')
        if self.purpose == 'stage_plan' and not self.task_id:
            raise ValueError('阶段建议必须指定任务')
        return self


class StageFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=80)
    completion_criteria: str = Field(min_length=1, max_length=1000)
    deadline: datetime
    responsible_role: Literal['publisher','assignee'] = 'assignee'
    require_timezone = field_validator('deadline')(TaskCreate.require_timezone.__func__)


class StageProposalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stages: list[StageFields] = Field(min_length=1, max_length=8)


class StagePlanInput(StageProposalInput):
    expected_version: int = Field(ge=0)
    suggestion_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')


class RewardChange(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reward_type: Literal['mutual','paid']
    reward_amount_fen: int | None = Field(default=None, strict=True, gt=0, le=9007199254740991)
    reward: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def valid_reward(self):
        if self.reward_type == 'mutual' and self.reward_amount_fen is not None:
            raise ValueError('无偿互助不能填写金额')
        if self.reward_type == 'paid' and (self.reward_amount_fen is None or not self.reward):
            raise ValueError('有偿任务必须填写金额和说明')
        return self


class StageChange(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str
    version: int = Field(ge=1)
    deadline: datetime | None = None
    completion_criteria: str | None = Field(default=None, min_length=1, max_length=1000)
    require_timezone = field_validator('deadline')(lambda value: TaskCreate.require_timezone(value) if value is not None else value)


class AgreementPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    deadline: datetime | None = None
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    completion_criteria: str | None = Field(default=None, min_length=1, max_length=2000)
    reward: RewardChange | None = None
    stages: list[StageChange] | None = Field(default=None, min_length=1, max_length=8)
    initial_stages: list[StageFields] | None = Field(default=None, min_length=1, max_length=8)
    require_timezone = field_validator('deadline')(lambda value: TaskCreate.require_timezone(value) if value is not None else value)


class ChangeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    changes: AgreementPatch
    suggestion_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')


class StageActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)


class StageSubmitInput(StageActionInput):
    summary: str = Field(min_length=1, max_length=4000)
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class StageReviewInput(ReviewInput):
    version: int = Field(ge=1)


class StageSubmissionRead(SubmissionRead):
    stage_id: str
    author_name: str
    reviewer_id: str | None = None
    reviewer_name: str | None = None


class StageRead(StageFields):
    id: str
    position: int
    status: Literal['not_started','in_progress','submitted','changes_requested','confirmed']
    version: int
    is_overdue: bool = False
    responsible_id: str | None = None
    responsible_name: str | None = None
    reviewer_id: str | None = None
    reviewer_name: str | None = None
    submissions: list[StageSubmissionRead] = []


class StagePlanVersionRead(BaseModel):
    version: int
    created_at: datetime
    stages: list[StageFields]


class StagePanelRead(BaseModel):
    task_id: str
    plan_version: int
    can_edit: bool
    can_propose_plan: bool = False
    edit_reason: str | None = None
    stages: list[StageRead]
    versions: list[StagePlanVersionRead] = []
    suggestion: StageSuggestionRead | None = None


class StageSuggestionRead(StageProposalInput):
    id: str
    task_id: str
    conversation_id: str
    base_version: int
    model: str | None = None
    applied_version: int | None = None


class DraftFields(TaskCreate):
    reward_type: Literal['mutual','paid'] | None = None

    @model_validator(mode='after')
    def reward_rules(self):
        if self.reward_type == 'mutual' and self.reward_amount_fen is not None:
            raise ValueError('无偿互助不能填写金额')
        return self

    title: str | None = Field(default=None, min_length=1, max_length=100)
    category: Category | None = None
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    completion_criteria: str | None = Field(default=None, min_length=1, max_length=2000)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    deadline: datetime | None = None


class TaskDraftRead(BaseModel):
    conversation_id: str
    version: int
    status: Literal['draft', 'published', 'cancelled']
    fields: DraftFields
    missing_fields: list[str]
    ready: bool
    published_task_id: str | None = None
    href: str | None = None


class DraftActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)


class ChatHistoryRead(BaseModel):
    role: Literal['user', 'assistant']
    content: str


class GuideConversationRead(BaseModel):
    conversation_id: str
    messages: list[ChatHistoryRead]
    draft: TaskDraftRead | None = None
    stage_suggestion: StageSuggestionRead | None = None
    assistance: dict | None = None


class CampusReference(BaseModel):
    content_type: Literal['ordinary', 'activity', 'volunteer', 'discovery']
    resource_id: str
    title: str
    href: str
    # 保留普通任务旧字段，便于旧前端和已保存运行记录读取。
    task_id: str | None = None


class ToolActivity(BaseModel):
    name: str
    success: bool


class GuideReply(BaseModel):
    run_id: str | None = None
    conversation_id: str
    answer: str
    references: list[CampusReference]
    tools_used: list[ToolActivity]
    mode: str = 'model'
    draft: TaskDraftRead | None = None
    stage_suggestion: StageSuggestionRead | None = None
    assistance: dict | None = None


class DeadlineInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    deadline: datetime
    reason: str = Field(min_length=1,max_length=2000)
    version: int = Field(ge=1)
    require_timezone = field_validator('deadline')(TaskCreate.require_timezone.__func__)


class ExtensionReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    decision: Literal['approve','reject']
    reason: str = Field(default='',max_length=2000)
    version: int = Field(ge=1)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)


class CollaborationRequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    action: Literal['pause','resume','cancel']
    version: int = Field(ge=1)
    collaboration_version: int = Field(ge=1)
    reason: str = Field(min_length=1,max_length=2000)
    extend_deadline: bool
    deadline: datetime | None = None
    cancellation_settlement_fen: int | None = Field(default=None,strict=True,ge=0,le=9007199254740991)

    @field_validator('deadline')
    @classmethod
    def require_deadline_timezone(cls,value):
        return TaskCreate.require_timezone(value)


class SettlementInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    confirmed: bool = Field(strict=True)
    version: int = Field(ge=0)
    reason: str = Field(default='',max_length=2000)
