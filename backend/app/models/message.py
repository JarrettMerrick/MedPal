# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""站内信（统一消息中心）模型

[新增 2026-09-11] 统一站内信
==========================
背景：原 `notifications` 表只支持「系统自动通知、单收件人、无标注」，无法承载
「超管群发 / 私发」「收件人自定义标签」等需求。现把「系统通知 + 人工消息」
合并为一套表，避免两套收件箱并存：

    messages             消息主体（一次发送 = 一行）
    message_recipients   收件人及个人状态（已读 / 星标 / 归档 / 自定义标签 / 删除）
    message_tags         收件人自定义标签字典（每个用户一套）

设计取舍（写扩散）：
    发送时按收件人一次性写入 N 行 `message_recipients`。本项目为 SQLite、
    账号规模数百、群发属低频操作，写扩散下读路径无需联表计算可见范围，
    读性能最好，且「已读 / 星标 / 标签」天然按人独立。

兼容：旧 `notifications` 表暂不删除（保留一个版本周期以便回滚），
启动时会把历史数据一次性迁移进本套表（见 services/message_service.py）。
"""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utc_now

# 消息类型
MSG_TYPE_SYSTEM = "system"        # 系统自动通知（人员变更、工卡、磁盘告警等）
MSG_TYPE_BROADCAST = "broadcast"  # 人工群发
MSG_TYPE_DIRECT = "direct"        # 人工私发


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="消息ID")
    title = Column(String(200), nullable=False, comment="标题")
    content = Column(Text, nullable=True, comment="正文（富文本 HTML）")
    sender_id = Column(String(20), nullable=True, index=True, comment="发送人工号；NULL 表示系统自动消息")
    msg_type = Column(
        String(20), nullable=False, default=MSG_TYPE_SYSTEM,
        comment="消息类型：system 系统通知 / broadcast 群发 / direct 私发",
    )
    related_type = Column(String(20), nullable=True, comment="关联业务类型（供前端跳转）")
    related_id = Column(Integer, nullable=True, comment="关联业务ID")
    created_at = Column(DateTime, default=utc_now, index=True, comment="创建时间（UTC）")

    recipients = relationship(
        "MessageRecipient", back_populates="message", cascade="all, delete-orphan",
    )


class MessageRecipient(Base):
    """收件人及其个人状态（一人一行）"""

    __tablename__ = "message_recipients"
    __table_args__ = (
        # 未读角标查询：user_id + is_read
        Index("ix_message_recipient_user_read", "user_id", "is_read"),
        # 同一消息同一收件人只允许一行（写扩散时去重）
        UniqueConstraint("message_id", "user_id", name="uq_message_recipient"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    message_id = Column(
        Integer, ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="消息ID",
    )
    user_id = Column(String(20), nullable=False, index=True, comment="收件人工号")
    is_read = Column(Boolean, nullable=False, default=False, comment="是否已读")
    read_at = Column(DateTime, nullable=True, comment="已读时间（UTC）")
    is_starred = Column(Boolean, nullable=False, default=False, comment="标注：星标/重要")
    is_archived = Column(Boolean, nullable=False, default=False, comment="标注：归档")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="标注：收件人侧删除（软删）")
    tag_id = Column(
        Integer, ForeignKey("message_tags.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="标注：收件人自定义标签ID",
    )
    created_at = Column(DateTime, default=utc_now, comment="创建时间（UTC）")

    message = relationship("Message", back_populates="recipients")


class MessageTag(Base):
    """收件人自定义标签字典（每个用户独立一套）"""

    __tablename__ = "message_tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_message_tag_user_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="标签ID")
    user_id = Column(String(20), nullable=False, index=True, comment="标签所属用户工号")
    name = Column(String(30), nullable=False, comment="标签名称")
    color = Column(String(20), nullable=True, default="#5C6B7A", comment="标签颜色")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序（小的在前）")
    created_at = Column(DateTime, default=utc_now, comment="创建时间（UTC）")
