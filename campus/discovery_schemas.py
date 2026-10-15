from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

DiscoveryCategory=Literal['facility','safety','interesting','life']
DiscoveryStatus=Literal['unverified','verified','reported','in_progress','resolved','valid','invalid','visible','expired']
STATES={'facility':('unverified','verified','reported','in_progress','resolved'),
        'safety':('valid','invalid'),'interesting':('visible','expired'),'life':('visible','expired')}
TERMINAL=('resolved','invalid','expired')


class DiscoveryModel(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class DiscoveryFields(DiscoveryModel):
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(min_length=1,max_length=4000)
    location:str=Field(min_length=1,max_length=200)
    discovered_at:datetime
    information_source:str=Field(min_length=1,max_length=500)
    image_ids:list[str]=Field(default_factory=list,max_length=3)

    @field_validator('discovered_at')
    @classmethod
    def aware(cls,value):
        if value.utcoffset() is None:raise ValueError('发现时间必须带时区')
        return value

    @field_validator('image_ids')
    @classmethod
    def unique_images(cls,value):
        if len(value)!=len(set(value)):raise ValueError('图片不能重复')
        if any(len(v)!=32 or any(c not in '0123456789abcdef' for c in v) for v in value):
            raise ValueError('图片编号不正确')
        return value


class DiscoveryCreate(DiscoveryFields):
    category:DiscoveryCategory


class DiscoveryEdit(DiscoveryFields):
    version:int=Field(ge=1,strict=True)


class DiscoveryStateInput(DiscoveryModel):
    version:int=Field(ge=1,strict=True)
    status:DiscoveryStatus
    reason:str=Field(min_length=1,max_length=2000)


class DiscoveryWithdraw(DiscoveryModel):
    version:int=Field(ge=1,strict=True)
    reason:str=Field(min_length=1,max_length=2000)


class DiscoveryCommentInput(DiscoveryModel):
    content:str=Field(min_length=1,max_length=2000)
    image_ids:list[str]=Field(default_factory=list,max_length=3)

    @field_validator('image_ids')
    @classmethod
    def images(cls,value):return DiscoveryFields.unique_images(value)
