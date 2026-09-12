# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""注册申请模型（登录页自助注册 → 科室管理员审核）。

[新增 2026-09-10]
- 登录页开启「注册开关」后，访客可提交注册申请；审核通过才建立可登录账号。
- 表中只保存 bcrypt 的 `password_hash`（**不存明文**），审核通过时直接复用为
  `users.password_hash`，因此注册时填写的密码即为最终密码。
- 同一工号允许多次申请（被驳回后可重新提交），故 `employee_id` 不加唯一约束，
  重复性校验以「同工号 + status=pending」为准。
"""

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base
from app.utils import utc_now


class RegistrationRequest(Base):
    """注册申请"""
    __tablename__ = "registration_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), nullable=False, index=True, comment="申请工号（登录账号）")
    name = Column(String(50), nullable=False, comment="姓名")
    password_hash = Column(String(128), nullable=False, comment="注册密码（bcrypt，通过时直接复用）")
    work_type = Column(String(20), nullable=False, comment="工种: doctor/nurse/technician/admin")
    department = Column(String(100), nullable=False, comment="所属科室名称")
    status = Column(String(20), nullable=False, default="pending", index=True,
                    comment="审核状态: pending/approved/rejected")
    reject_reason = Column(String(200), nullable=True, comment="驳回原因")
    reviewed_by = Column(String(20), nullable=True, comment="审核人工号")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间（UTC）")
    created_at = Column(DateTime, default=utc_now, index=True, comment="提交时间（UTC）")
    ip_address = Column(String(45), nullable=True, comment="提交来源 IP（风控/审计）")
