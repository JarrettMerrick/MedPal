# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# [改进] 旧版角色名到新版角色名的映射，用于自动修正和友好提示
_LEGACY_ROLE_MAP = {
    "admin": "admin_manager",
    "super_admin": "admin_manager",
    "department_head": "dept_manager",
}


class UserCreate(BaseModel):
    employee_id: str = Field(..., description="工号（超级管理员可非6位数字，其余角色须为6位数字）")
    name: str = Field(..., description="姓名")
    # [改进] 修正文档：实际角色名为 admin_manager/dept_manager/employee
    role: str = Field(default="employee", description="角色: admin_manager/dept_manager/employee")
    role_id: Optional[int] = Field(None, description="关联的角色ID")
    department: Optional[str] = None
    user_type: str = Field(default="admin_user", description="用户类型: doctor/nurse/admin_user")

    @field_validator("role")
    @classmethod
    def check_role_valid(cls, v: str) -> str:
        """[改进] 校验角色名称，拒绝无效的旧版角色值并提供修正建议"""
        if v in _LEGACY_ROLE_MAP:
            corrected = _LEGACY_ROLE_MAP[v]
            raise ValueError(f"角色 '{v}' 已更名，请使用 '{corrected}'")
        return v

    @model_validator(mode='after')
    def check_employee_id(self):
        """[新增] 工号校验：超级管理员不受6位数字限制，其余角色须为6位数字"""
        import re
        if self.role == "admin_manager":
            return self
        if not re.match(r"^\d{6}$", self.employee_id):
            raise ValueError("工号必须为6位数字（超级管理员账号除外）")
        return self


class UserUpdate(BaseModel):
    name: Optional[str] = None
    # [改进] 修正文档并添加角色名校验
    role: Optional[str] = Field(None, description="角色: admin_manager/dept_manager/employee")
    role_id: Optional[int] = None
    department: Optional[str] = None
    user_type: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def check_role_valid(cls, v: Optional[str]) -> Optional[str]:
        """[改进] 校验角色名称，拒绝无效的旧版角色值"""
        if v and v in _LEGACY_ROLE_MAP:
            corrected = _LEGACY_ROLE_MAP[v]
            raise ValueError(f"角色 '{v}' 已更名，请使用 '{corrected}'")
        return v


class UserResponse(BaseModel):
    employee_id: str
    name: str
    role: str
    role_id: Optional[int] = None
    department: Optional[str] = None
    user_type: str
    is_active: bool
    must_change_password: bool
    # [新增 2026-09-10] 是否为「系统中最后一个超级管理员」。
    # 为 True 时前端禁用删除/禁用/角色降级操作（后端同样强制校验），
    # 保证系统始终保留至少一个超级管理员账号。
    is_last_super_admin: bool = False

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total: int
    items: list[UserResponse]
    page: int
    page_size: int


class ProfileUpdate(BaseModel):
    """本人自助资料更新（任何登录用户均可调用）

    [改进] 在原有 name/department 基础上，补充个人介绍字段，
    使员工可在「个人信息」页自助维护专业擅长/社会任职/荣誉/备注等，
    这些字段持久化到本人的 staff 记录（个人介绍的真实存储位置）。
    """
    name: Optional[str] = None
    department: Optional[str] = None
    education: Optional[str] = None
    title: Optional[str] = None
    position: Optional[str] = None
    expertise_short: Optional[str] = None
    expertise_standard: Optional[str] = None
    social_appointments: Optional[str] = None
    honors: Optional[str] = None
    remarks: Optional[str] = None
