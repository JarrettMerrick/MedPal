# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base
from app.utils import utc_now


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="通知ID")
    user_id = Column(String(20), nullable=False, index=True, comment="接收人工号")
    title = Column(String(200), nullable=False, comment="通知标题")
    content = Column(Text, nullable=True, comment="通知内容")
    related_type = Column(String(20), nullable=True, comment="关联类型: card")
    related_id = Column(Integer, nullable=True, comment="关联ID")
    is_read = Column(Boolean, default=False, comment="是否已读")
    created_at = Column(DateTime, default=utc_now, comment="创建时间（UTC）")
