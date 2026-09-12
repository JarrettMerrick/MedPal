# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class StaffCard(Base):
    """医护人员卡片管理模型"""
    __tablename__ = "staff_cards"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="卡片ID")
    entity_type = Column(String(20), nullable=False, comment="实体类型: doctor/nurse")
    entity_id = Column(String(20), nullable=False, comment="实体工号")
    card_photo = Column(String(500), nullable=False, comment="卡片照片路径")
    status = Column(String(20), default="pending", nullable=False, comment="卡片状态: pending/confirmed/rejected")
    uploaded_by = Column(String(20), nullable=False, comment="上传人工号")
    uploaded_at = Column(DateTime, server_default=func.now(), comment="上传时间")
    confirmed_by = Column(String(20), nullable=True, comment="确认人工号")
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")
    reject_reason = Column(Text, nullable=True, comment="拒绝原因")
