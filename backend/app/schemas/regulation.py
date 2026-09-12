# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional
import re

from pydantic import BaseModel, field_validator


# [新增] 类别代码格式：恰好3位大写英文字母
CATEGORY_CODE_PATTERN = re.compile(r'^[A-Z]{3}$')


# ==================== 类别相关 ====================

class CategoryBase(BaseModel):
    name: str
    code: Optional[str] = None
    sort_order: int = 0


class CategoryCreate(CategoryBase):
    # [新增] 创建类别时 code 必填，且必须为3位大写英文字母
    code: str

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        if not CATEGORY_CODE_PATTERN.match(v or ''):
            raise ValueError('类别代码必须为3位大写英文字母')
        return v


class CategoryUpdate(BaseModel):
    """[新增] 编辑制度类别：名称与代码均可改；code 若提供则校验格式"""
    name: Optional[str] = None
    code: Optional[str] = None

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        if v is not None and not CATEGORY_CODE_PATTERN.match(v):
            raise ValueError('类别代码必须为3位大写英文字母')
        return v


class CategoryOut(CategoryBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ==================== 制度历史 ====================

class RegulationHistoryOut(BaseModel):
    id: int
    regulation_id: int
    version: Optional[str] = None
    edited_by: Optional[str] = None
    edited_at: Optional[datetime] = None
    change_summary: Optional[str] = None

    model_config = {"from_attributes": True}


class RegulationHistoryDetailOut(RegulationHistoryOut):
    """[新增] 历史版本详情（含该版本的完整制度内容快照）"""
    content: Optional[str] = None

    model_config = {"from_attributes": True}


# ==================== 制度相关 ====================

class RegulationBase(BaseModel):
    name: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None


class RegulationCreate(RegulationBase):
    pass


class RegulationUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None


class RegulationOut(RegulationBase):
    id: int
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RegulationDetailOut(RegulationOut):
    history: list[RegulationHistoryOut] = []

    model_config = {"from_attributes": True}


class RegulationListOut(BaseModel):
    items: list[RegulationOut]
    total: int
