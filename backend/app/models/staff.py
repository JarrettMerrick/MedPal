# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Staff(Base):
    """统一人员模型 — 合并医生、护士、技师、行政人员"""
    __tablename__ = "staff"

    employee_id = Column(
        String(20),
        ForeignKey("users.employee_id", ondelete="CASCADE"),
        primary_key=True,
        comment="人员工号",
    )
    name = Column(String(50), nullable=False, comment="姓名")
    # 工种: doctor-医生, nurse-护士, technician-技师, admin-行政
    work_type = Column(String(20), nullable=False, comment="工种")
    education = Column(String(50), comment="学历")
    title = Column(String(50), comment="职称")
    department = Column(String(100), nullable=False, comment="所属科室/病区/部门")
    position = Column(String(50), comment="职务")
    expertise_short = Column(Text, comment="专业擅长（短）")
    expertise_standard = Column(Text, comment="专业擅长（标准）")
    social_appointments = Column(Text, comment="社会任职")
    honors = Column(Text, comment="获得荣誉")
    remarks = Column(Text, comment="备注")
    front_photo = Column(String(500), nullable=True, comment="正面形象照路径")
    side_photo = Column(String(500), nullable=True, comment="侧面形象照路径")
    status = Column(String(20), nullable=False, default="active", comment="状态: active-在职, resigned-离职")
    # [新增 2026-09-11] 离职档案字段（离职 ≠ 删除：保留档案，标记状态与时间）
    resigned_at = Column(DateTime, nullable=True, comment="离职时间（UTC）")
    resign_reason = Column(String(200), nullable=True, comment="离职原因（可选）")
    resigned_by = Column(String(20), nullable=True, comment="办理离职的操作人工号")
    # [新增 2026-09-11] 保留期提醒：离职满 6 个月后已私信超管「请手动删除登录账号」的时间
    # （UTC；为空表示尚未提醒，避免重复打扰）
    account_notice_at = Column(DateTime, nullable=True, comment="账号清理提醒时间（UTC）")
    updated_by = Column(String(20), nullable=True, comment="最后修改人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="最后修改时间")

    # 关联用户信息
    user = relationship("User", backref="staff_info", lazy="joined")
