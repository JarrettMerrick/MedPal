# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ModificationHistory(Base):
    """修改历史记录表"""
    __tablename__ = "modification_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(20), nullable=False, comment="实体类型: doctor/nurse/department")
    entity_id = Column(String(50), nullable=False, comment="实体ID")
    modified_by = Column(String(20), nullable=False, comment="修改人工号")
    modified_at = Column(DateTime, nullable=False, server_default=func.now(), comment="修改时间")
    change_summary = Column(Text, nullable=True, comment="修改内容摘要")
    acknowledged_by = Column(String(20), nullable=True, comment="确认人工号")
    acknowledged_at = Column(DateTime, nullable=True, comment="确认时间")
