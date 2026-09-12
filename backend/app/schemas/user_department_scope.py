# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from pydantic import BaseModel
from datetime import datetime


class UserDepartmentScopeCreate(BaseModel):
    """创建用户科室关联"""
    department_id: int


class UserDepartmentScopeResponse(BaseModel):
    """用户科室关联响应"""
    id: int
    employee_id: str
    department_id: int
    department_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserDepartmentScopeListResponse(BaseModel):
    """用户科室关联列表响应"""
    items: list[UserDepartmentScopeResponse]
    total: int


class DepartmentScopeUpdate(BaseModel):
    """更新用户科室权限范围"""
    department_ids: list[int]