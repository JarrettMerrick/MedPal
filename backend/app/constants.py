# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""项目中共享的常量定义"""

from app.schemas.staff import (
    WORK_TYPE_DOCTOR,
    WORK_TYPE_NURSE,
    WORK_TYPE_TECHNICIAN,
    WORK_TYPE_ADMIN,
)

# 工种到用户类型的映射（staff.py 和 users.py 共用）
WORK_TYPE_TO_USER_TYPE = {
    WORK_TYPE_DOCTOR: "doctor",
    WORK_TYPE_NURSE: "nurse",
    WORK_TYPE_TECHNICIAN: "technician",
    WORK_TYPE_ADMIN: "admin_user",
}

# [新增 2026-09-17] 账号注册审核状态（User.review_status）
# 背景：自助注册改为「注册成功即可登录，审核通过后才拥有角色完整权限」。
#   - pending ：待审核。账号可登录，但仅能查看/修改个人资料（由 main.py 中间件白名单限制）
#   - approved：审核通过。按所属角色获得完整权限（管理员创建/批量导入/存量账号均为该值）
#   - rejected：审核驳回。禁止登录，可重新提交注册申请
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = (REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)
