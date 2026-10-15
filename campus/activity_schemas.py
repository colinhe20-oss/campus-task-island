"""综素活动与普通任务使用独立模型。"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RecognitionTag = Literal['second_class', 'aesthetic', 'ideological']


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    location: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    opens_at: datetime
    closes_at: datetime
    capacity: int = Field(gt=0, le=100000, strict=True)
    registration_mode: Literal['direct', 'review']
    recognition_tags: list[RecognitionTag] = Field(min_length=1, max_length=3)
    recognition_description: str = Field(min_length=1, max_length=2000)
    organization_name: str = Field(min_length=1, max_length=200)
    information_source: str = Field(min_length=1, max_length=500)
    contact: str = Field(min_length=1, max_length=500)
    participation_requirements: str = Field(min_length=1, max_length=2000)

    @field_validator('starts_at', 'ends_at', 'opens_at', 'closes_at')
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError('时间必须带时区')
        return value

    @model_validator(mode='after')
    def ordered(self):
        if not self.opens_at < self.closes_at <= self.starts_at < self.ends_at:
            raise ValueError('须满足报名开放 < 报名截止 ≤ 活动开始 < 活动结束')
        if len(set(self.recognition_tags)) != len(self.recognition_tags):
            raise ValueError('认定标签不能重复')
        return self


class RegistrationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    application_note: str = Field(default='', max_length=2000)


class RegistrationReview(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    decision: Literal['approve', 'reject']
    reason: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def rejection_reason(self):
        if self.decision == 'reject' and not self.reason:
            raise ValueError('拒绝申请必须填写理由')
        return self


class ActivityCancel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=2000)
