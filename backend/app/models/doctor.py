# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    employee_id = Column(
        String(20),
        ForeignKey("users.employee_id", ondelete="CASCADE"),
        primary_key=True,
        comment="医生工号",
    )
    name = Column(String(50), nullable=False, comment="姓名")
    education = Column(String(50), comment="学历")
    title = Column(String(50), comment="职称")
    department = Column(String(50), comment="科室")
    work_type = Column(String(20), comment="工种: 医生/技师")
    position = Column(String(50), comment="职务")
    expertise_short = Column(Text, comment="专业擅长（短）")
    expertise_standard = Column(Text, comment="专业擅长（标准）")
    social_appointments = Column(Text, comment="社会任职")
    honors = Column(Text, comment="获得荣誉")
    remarks = Column(Text, comment="备注")
    front_photo = Column(String(500), nullable=True, comment="正面形象照路径")
    side_photo = Column(String(500), nullable=True, comment="侧面形象照路径")
    status = Column(String(20), nullable=False, default="active", comment="状态: active-在职, resigned-离职")
    updated_by = Column(String(20), nullable=True, comment="最后修改人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="最后修改时间")
