# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""通知服务（兼容层）

[调整 2026-09-11] 「统一站内信」改造
================================
系统通知已统一并入站内信（见 `services/message_service.py`）：
原 `notifications` 表只支持「系统通知、单收件人、无标注」，无法承载
「超管群发/私发 + 收件人自定义标签」等需求，故把两者合并为一套表。

本模块保留为**兼容层**，仅保留 `create_notification` 且签名不变，
内部转写站内信（msg_type=system），使既有通知写入点（uploads / staff_cards /
chunk_upload / backup_service 等）无需改动即自动并入统一收件箱。

新代码请直接使用 `app.services.message_service`。
"""

from sqlalchemy.orm import Session

from app.services import message_service


def create_notification(
    db: Session, user_id, title: str, content: str | None = None,
    related_type: str | None = None, related_id: int | None = None,
):
    """[兼容旧调用] 创建系统通知 → 转写为站内信

    `user_id` 同时支持单个工号字符串与工号列表（后者为一次写入多条收件记录）。
    """
    return message_service.create_notification(
        db, user_id, title, content, related_type, related_id,
    )
