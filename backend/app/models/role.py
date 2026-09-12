# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# 角色-权限关联表
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    """角色表"""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, comment="角色标识: admin/department_head/employee")
    display_name = Column(String(50), nullable=False, comment="角色显示名称")
    description = Column(Text, nullable=True, comment="角色描述")
    is_system = Column(Boolean, default=False, comment="是否系统预设角色（不可删除）")
    # 数据范围控制
    department_scope = Column(String(20), nullable=False, default="own", comment="科室数据范围: own-仅本科室, managed-管辖科室, all-所有科室")
    work_type_scope = Column(String(200), nullable=False, default="all", comment="工种数据范围: all 或逗号分隔的工种列表如 doctor,nurse")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联权限
    permissions = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
        lazy="joined",
    )


class Permission(Base):
    """权限表"""
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="权限标识: staff.view, department.view等")
    display_name = Column(String(100), nullable=False, comment="权限显示名称")
    category = Column(String(50), nullable=False, comment="权限分类: staff/department/regulation/user/role/data/system/card/staff_rest_area")
    description = Column(Text, nullable=True, comment="权限描述")

    # 关联角色
    roles = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
    )
