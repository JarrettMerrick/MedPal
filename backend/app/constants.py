# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
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
