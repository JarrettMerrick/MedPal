# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    # [修复] 增加 max_length 限制：超长输入会进入高成本 bcrypt 哈希与 DB 查询，
    # 可被用于 CPU 资源消耗放大（DoS）；工号、密码均设合理上限。
    employee_id: str = Field(..., min_length=1, max_length=20, description="工号")
    password: str = Field(..., min_length=1, max_length=128, description="密码")
    remember_me: bool = Field(default=False, description="记住我（7天/30天有效期）")

    # [新增] 登录账号只允许字母/数字/下划线，拒绝空格与标点符号
    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9_]+$", v):
            raise ValueError("登录账号不能包含空格或标点符号")
        return v


class LoginResponse(BaseModel):
    access_token: str
    # [修复/问题3] refresh_token 改由 HttpOnly Cookie 下发，响应体不再返回，
    # 避免长期凭据暴露给前端 JS（XSS 可直接读取并长期冒用）。
    refresh_token: str | None = None
    file_token: str = ""
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    employee_id: str
    name: str
    role: str
    department: str | None = None
    user_type: str
    must_change_password: bool
    permissions: list[str] = []
    managed_departments: list[str] = []
    work_type_scope: str = "all"
    # [改进] 前端需要 department_scope 来判断是否限制编辑科室名称/分类
    department_scope: str = "own"
    # [新增] 当前登录用户是否有关联的员工记录（staff）。
    # 用于前端决定「个人信息」卡片跳转到员工详情页还是个人资料页，
    # 并避免对无员工记录的账号（如纯管理员 admin）发起 getStaff 探测请求造成无害 404 噪音。
    has_staff_record: bool = False

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    # [修复] old_password 增加 max_length，避免超长输入进入 bcrypt 哈希放大资源消耗
    old_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=6, max_length=50)


class ChangePasswordResponse(BaseModel):
    """改密成功响应：一并返回为「当前会话」重新签发的令牌。

    [修复] 改密会推进 password_changed_at，使所有旧 token（含本机当前 access/refresh）
    失效；若不重新签发，用户改密成功即掉登录。refresh_token 仍走 HttpOnly Cookie 轮换，
    不在响应体暴露。
    """
    message: str = "密码修改成功"
    access_token: str
    file_token: str = ""
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    # [修复/问题3] refresh_token 优先从 HttpOnly Cookie 读取，
    # 请求体字段转为可选，仅为兼容尚未升级的旧客户端。
    refresh_token: str | None = Field(default=None, max_length=1024)


class LogoutRequest(BaseModel):
    # [修复/问题3] 同上：refresh_token 默认来自 HttpOnly Cookie
    refresh_token: str | None = None
    access_token: str | None = None
