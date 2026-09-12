# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utc_now


class UserDepartmentScope(Base):
    """用户科室权限范围关联表
    
    用于科室负责人/病区负责人自定义关联管理多个科室。
    例如：某科室负责人除了默认管理本科室外，还可以关联管理其他科室。
    """
    __tablename__ = "user_department_scope"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="ID")
    employee_id = Column(
        String(20),
        ForeignKey("users.employee_id", ondelete="CASCADE"),
        nullable=False,
        comment="用户工号",
    )
    department_id = Column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        comment="科室ID",
    )
    created_at = Column(DateTime, default=utc_now, comment="创建时间（UTC）")

    # 关联
    user = relationship("User", backref="managed_departments")
    department = relationship("Department", backref="managed_by_users")
