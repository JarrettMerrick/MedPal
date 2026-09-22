# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship, validates

from app.database import Base

logger = logging.getLogger("user_model")

# [改进] 已知有效的角色名集合（由 role_initializer 维护），
# 用于 @validates 层兜底校验，防止脏角色名写入数据库
_VALID_ROLE_NAMES: set[str] = set()


def set_valid_role_names(names: set[str]) -> None:
    """由 role_initializer 在启动时调用，设置当前有效的角色名集合"""
    _VALID_ROLE_NAMES.clear()
    _VALID_ROLE_NAMES.update(names)


class User(Base):
    __tablename__ = "users"

    employee_id = Column(String(20), primary_key=True, comment="工号")
    name = Column(String(50), nullable=False, comment="姓名")
    password_hash = Column(String(128), nullable=False, comment="密码哈希")
    role = Column(
        String(20),
        nullable=False,
        default="employee",
        comment="角色名称，必须匹配 roles.name",
    )
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True, comment="关联角色ID")
    department = Column(String(50), nullable=True, comment="所属科室（部门负责人）")
    user_type = Column(
        String(20), nullable=False, default="admin_user",
        comment="【已废弃 v1.0.6】请使用 staff 表的 work_type 字段。当前保留用于向后兼容，将在 v1.1 移除"
    )
    is_active = Column(Boolean, default=True, comment="是否启用")
    must_change_password = Column(Boolean, default=True, comment="首次登录需修改密码")
    # [新增 2026-09-17] 注册审核状态（app.constants.REVIEW_*）：
    # 自助注册创建的账号为 pending（可登录，但仅能查看/修改个人资料），审核通过置 approved，
    # 驳回置 rejected 并禁用登录。管理员创建/批量导入/存量账号默认 approved，不受影响。
    review_status = Column(
        String(20), nullable=False, default="approved",
        comment="注册审核状态: pending-待审核(受限), approved-已通过, rejected-已驳回",
    )
    login_attempts = Column(Integer, default=0, comment="连续登录失败次数")
    locked_until = Column(DateTime, nullable=True, comment="锁定截止时间")
    password_changed_at = Column(DateTime, nullable=True, comment="密码最后修改时间")

    # 关联角色对象
    # [改进] 原关联依赖 role_id 外键（User.role_id → roles.id），但用户表实际仅以
    # role 字符串存储角色名（如 'employee'），role_id 长期为 NULL，导致 role_obj 恒为 None、
    # has_permission 恒返回 False（普通员工被 list_staff 的 staff.view 检查挡成空列表）。
    # 改为按 role 名称直接关联 Role.name，自愈合、不再依赖 role_id 填充。
    role_obj = relationship(
        "Role",
        primaryjoin="User.role == Role.name",
        foreign_keys="[User.role]",
        backref="users",
        lazy="joined",
    )

    # [改进] ORM 层角色名校验 — 最后一道防线，防止脏角色名写入数据库
    @validates("role")
    def validate_role(self, key, value):
        if _VALID_ROLE_NAMES and value not in _VALID_ROLE_NAMES:
            # 如果是已知旧版值，自动修正
            legacy_map = {"admin": "admin_manager", "super_admin": "admin_manager", "department_head": "dept_manager"}
            if value in legacy_map:
                corrected = legacy_map[value]
                logger.warning(
                    "ORM 自动修正角色名: '%s' → '%s' (employee_id=%s)",
                    value, corrected, getattr(self, "employee_id", "?"),
                )
                return corrected
            raise ValueError(
                f"无效角色名: '{value}'，有效值为: {sorted(_VALID_ROLE_NAMES)}"
            )
        return value
