"""志愿活动、岗位及按分钟核验的独立输入模型。"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VolunteerModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class VolunteerJob(VolunteerModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    requirements: str = Field(min_length=1, max_length=2000)
    location: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0, le=100000, strict=True)
    estimated_minutes: int = Field(gt=0, strict=True)
    estimated_hours_description: str = Field(min_length=1, max_length=2000)

    @field_validator('starts_at', 'ends_at')
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError('时间必须带时区')
        return value

    @model_validator(mode='after')
    def interval(self):
        if self.starts_at >= self.ends_at:
            raise ValueError('服务开始必须早于结束')
        if self.estimated_minutes > (self.ends_at-self.starts_at).total_seconds() // 60:
            raise ValueError('预计分钟数不能超过岗位服务时段')
        return self


class VolunteerCreate(VolunteerModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    organization_name: str = Field(min_length=1, max_length=200)
    information_source: str = Field(min_length=1, max_length=500)
    contact: str = Field(min_length=1, max_length=500)
    recognition_conditions: str = Field(min_length=1, max_length=2000)
    starts_at: datetime
    ends_at: datetime
    opens_at: datetime
    closes_at: datetime
    registration_mode: Literal['direct', 'review']
    jobs: list[VolunteerJob] = Field(min_length=1, max_length=30)

    @field_validator('starts_at', 'ends_at', 'opens_at', 'closes_at')
    @classmethod
    def aware(cls, value):
        return VolunteerJob.aware(value)

    @model_validator(mode='after')
    def intervals(self):
        if not self.opens_at < self.closes_at or self.starts_at >= self.ends_at:
            raise ValueError('报名开放须早于截止，活动开始须早于结束')
        for job in self.jobs:
            if not self.starts_at <= job.starts_at < job.ends_at <= self.ends_at:
                raise ValueError('岗位时段必须位于活动时段内')
            if self.closes_at > job.starts_at:
                raise ValueError('报名截止不能晚于任一岗位开始')
        return self


class ParticipationInput(VolunteerModel):
    version: int = Field(ge=0, strict=True)
    attendance: Literal['participated', 'absent']
    actual_minutes: int = Field(ge=0, strict=True)
    description: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def absent(self):
        if self.attendance == 'absent' and self.actual_minutes != 0:
            raise ValueError('未参与的实际分钟数必须为零')
        return self


class HoursInput(VolunteerModel):
    version: int = Field(ge=1, strict=True)
    confirmed_minutes: int = Field(ge=0, strict=True)
    reason: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def zero(self):
        if self.confirmed_minutes == 0 and not self.reason:
            raise ValueError('确认零分钟须说明不予计时的理由')
        return self
