# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""站内信服务（统一消息中心）

职责：
    - 发送：系统通知 / 私发 / 群发（写扩散）
    - 查询：收件箱（按未读/星标/归档/标签/关键字筛选）、发件箱（含送达与已读统计）
    - 状态：已读、全部已读、标注（星标 / 归档 / 收件人自定义标签）、收件人侧软删除
    - 收件人解析：全员 / 按科室 / 按角色 / 按权限 / 指定工号
    - 迁移：把历史 `notifications` 数据一次性并入站内信

约定：
    - 所有写操作只 `add/flush`，**不 commit**，由调用方（路由或启动流程）统一提交，
      便于与业务修改同事务提交（避免"业务回滚但消息已发出"）。
    - 收件人侧操作一律带 `user_id` 过滤，防止越权操作他人消息。
"""

import logging
from typing import Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.message import (
    MSG_TYPE_BROADCAST, MSG_TYPE_DIRECT, MSG_TYPE_SYSTEM,
    Message, MessageRecipient, MessageTag,
)
from app.models.user import User
from app.utils import utc_now

logger = logging.getLogger("message_service")

# 单次发送的收件人上限（防误操作：如误选"全员"造成超大写入）
MAX_FANOUT = 2000
# 标签名长度上限（与 MessageTag.name 的 String(30) 对应）
MAX_TAG_NAME_LEN = 30
# 旧通知迁移完成标记（存放于 system_configs，保证迁移只执行一次）
MIGRATION_FLAG_KEY = "_migrated_notifications_v1"
# "未传入"哨兵：用于区分「不改标签」与「清空标签」
UNSET = object()


# ==================== 发送 ====================

def normalize_recipients(
    recipients, exclude_user_id: str | None = None, limit: int = MAX_FANOUT,
) -> list[str]:
    """归一化收件人工号：去空、去重、可排除指定人（通常是操作者本人）"""
    ids = [recipients] if isinstance(recipients, str) else list(recipients or [])
    out: list[str] = []
    seen: set[str] = set()
    for uid in ids:
        u = (uid or "").strip()
        if not u or u in seen or (exclude_user_id and u == exclude_user_id):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def create_message(
    db: Session,
    *,
    title: str,
    content: str | None = None,
    recipients,
    sender_id: str | None = None,
    msg_type: str = MSG_TYPE_SYSTEM,
    related_type: str | None = None,
    related_id: int | None = None,
    exclude_user_id: str | None = None,
) -> Message | None:
    """创建站内信（写扩散：一次发送写入一行 messages + N 行 message_recipients）。

    `recipients` 支持单个工号字符串或工号列表。无有效收件人时返回 None（不产生空消息）。
    """
    uids = normalize_recipients(recipients, exclude_user_id)
    if not uids:
        return None
    now = utc_now()
    msg = Message(
        title=(title or "").strip()[:200],
        content=content,
        sender_id=sender_id,
        msg_type=msg_type,
        related_type=related_type,
        related_id=related_id,
        created_at=now,
    )
    db.add(msg)
    db.flush()
    for uid in uids:
        db.add(MessageRecipient(
            message_id=msg.id, user_id=uid,
            is_read=False, is_starred=False, is_archived=False, is_deleted=False,
            created_at=now,
        ))
    db.flush()
    return msg


def create_notification(
    db: Session, user_id, title: str, content: str | None = None,
    related_type: str | None = None, related_id: int | None = None,
) -> Message | None:
    """[兼容旧调用] 系统通知：内部转写为站内信（msg_type=system）。

    保持与原 notification_service.create_notification 相同的调用签名，
    使既有通知写入点无需改动即自动并入站内信；`user_id` 亦支持传工号列表。
    """
    return create_message(
        db, title=title, content=content, recipients=user_id, sender_id=None,
        msg_type=MSG_TYPE_SYSTEM, related_type=related_type, related_id=related_id,
    )


# ==================== 收件人解析（群发用） ====================

def resolve_recipients(
    db: Session, target_type: str, values: Sequence[str] | None = None,
    exclude_user_id: str | None = None,
) -> list[str]:
    """解析群发收件人（仅返回**启用**账号）

    target_type：
        all         全员
        departments 指定科室（按账号的所属科室匹配）
        roles       指定角色（roles.name）
        permissions 拥有指定权限的账号（任一命中即可）
        users       指定工号
    """
    vals = [str(v).strip() for v in (values or []) if str(v).strip()]

    if target_type == "users":
        if not vals:
            return []
        rows = (
            db.query(User.employee_id)
            .filter(User.employee_id.in_(vals), User.is_active == True)  # noqa: E712
            .all()
        )
        return normalize_recipients([r[0] for r in rows], exclude_user_id)

    users = db.query(User).filter(User.is_active == True).all()  # noqa: E712

    if target_type == "all":
        picked = users
    elif target_type == "departments":
        wanted = set(vals)
        picked = [u for u in users if (u.department or "").strip() in wanted]
    elif target_type == "roles":
        wanted = set(vals)
        picked = [u for u in users if u.role in wanted]
    elif target_type == "permissions":
        from app.dependencies import has_permission
        picked = [u for u in users if any(has_permission(u, p) for p in vals)]
    else:
        picked = []

    return normalize_recipients([u.employee_id for u in picked], exclude_user_id)


def describe_recipients(db: Session, employee_ids: Sequence[str], preview: int = 20) -> dict:
    """收件人预览：返回总数与前若干条「工号 · 姓名 · 科室」摘要"""
    ids = list(employee_ids)
    if not ids:
        return {"total": 0, "preview": []}
    rows = (
        db.query(User.employee_id, User.name, User.department)
        .filter(User.employee_id.in_(ids[:preview]))
        .all()
    )
    return {
        "total": len(ids),
        "preview": [
            {"employee_id": r[0], "name": r[1], "department": r[2]} for r in rows
        ],
    }


# ==================== 查询：收件箱 / 发件箱 ====================

def list_inbox(
    db: Session, user_id: str, *, page: int = 1, page_size: int = 20,
    box: str = "all", tag_id: int | None = None,
    keyword: str | None = None, msg_type: str | None = None,
) -> tuple[list, int]:
    """收件箱查询（返回 (MessageRecipient, Message) 行 + 总数）

    box：all（默认，不含归档）/ unread / starred / archived
    """
    q = (
        db.query(MessageRecipient, Message)
        .join(Message, Message.id == MessageRecipient.message_id)
        .filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.is_deleted == False,  # noqa: E712
        )
    )
    if box == "unread":
        q = q.filter(MessageRecipient.is_read == False)  # noqa: E712
    elif box == "starred":
        q = q.filter(MessageRecipient.is_starred == True)  # noqa: E712
    elif box == "archived":
        q = q.filter(MessageRecipient.is_archived == True)  # noqa: E712
    else:
        q = q.filter(MessageRecipient.is_archived == False)  # noqa: E712

    if tag_id:
        q = q.filter(MessageRecipient.tag_id == tag_id)
    if msg_type:
        q = q.filter(Message.msg_type == msg_type)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(Message.title.like(like), Message.content.like(like)))

    total = q.count()
    rows = (
        q.order_by(Message.created_at.desc(), Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def list_sent(
    db: Session, user_id: str, *, page: int = 1, page_size: int = 20,
    keyword: str | None = None,
) -> tuple[list[Message], int, dict, dict]:
    """发件箱查询（返回消息列表、总数、以及每条消息的收件人数/已读数映射）"""
    q = db.query(Message).filter(Message.sender_id == user_id)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(Message.title.like(like), Message.content.like(like)))
    total = q.count()
    items = (
        q.order_by(Message.created_at.desc(), Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [m.id for m in items]
    totals: dict[int, int] = {}
    reads: dict[int, int] = {}
    if ids:
        totals = dict(
            db.query(MessageRecipient.message_id, func.count(MessageRecipient.id))
            .filter(MessageRecipient.message_id.in_(ids))
            .group_by(MessageRecipient.message_id)
            .all()
        )
        reads = dict(
            db.query(MessageRecipient.message_id, func.count(MessageRecipient.id))
            .filter(
                MessageRecipient.message_id.in_(ids),
                MessageRecipient.is_read == True,  # noqa: E712
            )
            .group_by(MessageRecipient.message_id)
            .all()
        )
    return items, total, totals, reads


def get_recipient_row(db: Session, message_id: int, user_id: str) -> MessageRecipient | None:
    """取某人在某条消息中的收件记录（带归属过滤，越权返回 None）"""
    return (
        db.query(MessageRecipient)
        .filter(
            MessageRecipient.message_id == message_id,
            MessageRecipient.user_id == user_id,
            MessageRecipient.is_deleted == False,  # noqa: E712
        )
        .first()
    )


def get_unread_count(db: Session, user_id: str) -> int:
    """未读站内信数量（铃铛角标）"""
    return (
        db.query(MessageRecipient)
        .filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.is_read == False,  # noqa: E712
            MessageRecipient.is_deleted == False,  # noqa: E712
        )
        .count()
    )


def count_by_tag(db: Session, user_id: str) -> dict[int, int]:
    """各标签下的未删除消息数（标签栏计数）"""
    rows = (
        db.query(MessageRecipient.tag_id, func.count(MessageRecipient.id))
        .filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.is_deleted == False,  # noqa: E712
            MessageRecipient.tag_id.isnot(None),
        )
        .group_by(MessageRecipient.tag_id)
        .all()
    )
    return {tag_id: cnt for tag_id, cnt in rows}


# ==================== 状态：已读 / 标注 / 删除 ====================

def mark_read(db: Session, message_id: int, user_id: str) -> MessageRecipient | None:
    """标记单条已读（仅本人）"""
    row = get_recipient_row(db, message_id, user_id)
    if not row:
        return None
    if not row.is_read:
        row.is_read = True
        row.read_at = utc_now()
    db.flush()
    return row


def mark_many_read(db: Session, user_id: str, message_ids: Sequence[int], is_read: bool = True) -> int:
    """批量标记已读 / 未读（仅本人）"""
    ids = [int(i) for i in (message_ids or [])]
    if not ids:
        return 0
    count = (
        db.query(MessageRecipient)
        .filter(MessageRecipient.user_id == user_id, MessageRecipient.message_id.in_(ids))
        .update(
            {"is_read": is_read, "read_at": utc_now() if is_read else None},
            synchronize_session=False,
        )
    )
    db.flush()
    return count


def mark_all_read(db: Session, user_id: str) -> int:
    """全部标为已读（仅本人）"""
    count = (
        db.query(MessageRecipient)
        .filter(
            MessageRecipient.user_id == user_id,
            MessageRecipient.is_read == False,  # noqa: E712
            MessageRecipient.is_deleted == False,  # noqa: E712
        )
        .update({"is_read": True, "read_at": utc_now()}, synchronize_session=False)
    )
    db.flush()
    return count


def update_flags(
    db: Session, user_id: str, message_ids: Sequence[int], *,
    is_starred: bool | None = None,
    is_archived: bool | None = None,
    tag_id=UNSET,
) -> int:
    """批量更新标注（星标 / 归档 / 自定义标签），仅本人

    `tag_id` 三态：不传=不改；传 None=清除标签；传整数=设置标签（校验标签归属）。
    """
    ids = [int(i) for i in (message_ids or [])]
    if not ids:
        return 0
    values: dict = {}
    if is_starred is not None:
        values["is_starred"] = bool(is_starred)
    if is_archived is not None:
        values["is_archived"] = bool(is_archived)
    if tag_id is not UNSET:
        if tag_id is not None:
            own = (
                db.query(MessageTag)
                .filter(MessageTag.id == int(tag_id), MessageTag.user_id == user_id)
                .first()
            )
            if not own:
                raise ValueError("标签不存在或不属于当前用户")
            values["tag_id"] = own.id
        else:
            values["tag_id"] = None
    if not values:
        return 0
    count = (
        db.query(MessageRecipient)
        .filter(MessageRecipient.user_id == user_id, MessageRecipient.message_id.in_(ids))
        .update(values, synchronize_session=False)
    )
    db.flush()
    return count


def soft_delete(db: Session, user_id: str, message_ids: Sequence[int]) -> int:
    """收件人侧软删除（仅本人收件箱，不影响其他收件人与发送者）"""
    ids = [int(i) for i in (message_ids or [])]
    if not ids:
        return 0
    count = (
        db.query(MessageRecipient)
        .filter(MessageRecipient.user_id == user_id, MessageRecipient.message_id.in_(ids))
        .update({"is_deleted": True}, synchronize_session=False)
    )
    db.flush()
    return count


# ==================== 自定义标签字典 ====================

def list_tags(db: Session, user_id: str) -> list[MessageTag]:
    return (
        db.query(MessageTag)
        .filter(MessageTag.user_id == user_id)
        .order_by(MessageTag.sort_order.asc(), MessageTag.id.asc())
        .all()
    )


def create_tag(db: Session, user_id: str, name: str, color: str | None = None) -> MessageTag:
    clean = (name or "").strip()
    if not clean:
        raise ValueError("标签名称不能为空")
    if len(clean) > MAX_TAG_NAME_LEN:
        raise ValueError(f"标签名称过长（最多 {MAX_TAG_NAME_LEN} 个字符）")
    dup = (
        db.query(MessageTag)
        .filter(MessageTag.user_id == user_id, MessageTag.name == clean)
        .first()
    )
    if dup:
        raise ValueError("同名标签已存在")
    count = db.query(MessageTag).filter(MessageTag.user_id == user_id).count()
    tag = MessageTag(
        user_id=user_id, name=clean, color=color or "#5C6B7A",
        sort_order=count, created_at=utc_now(),
    )
    db.add(tag)
    db.flush()
    return tag


def update_tag(
    db: Session, user_id: str, tag_id: int,
    name: str | None = None, color: str | None = None,
) -> MessageTag | None:
    tag = db.query(MessageTag).filter(MessageTag.id == tag_id, MessageTag.user_id == user_id).first()
    if not tag:
        return None
    if name is not None:
        clean = name.strip()
        if not clean:
            raise ValueError("标签名称不能为空")
        if len(clean) > MAX_TAG_NAME_LEN:
            raise ValueError(f"标签名称过长（最多 {MAX_TAG_NAME_LEN} 个字符）")
        dup = (
            db.query(MessageTag)
            .filter(
                MessageTag.user_id == user_id, MessageTag.name == clean,
                MessageTag.id != tag_id,
            )
            .first()
        )
        if dup:
            raise ValueError("同名标签已存在")
        tag.name = clean
    if color is not None:
        tag.color = color
    db.flush()
    return tag


def delete_tag(db: Session, user_id: str, tag_id: int) -> bool:
    """删除标签（先把引用该标签的收件记录解除引用，避免外键约束报错）"""
    tag = db.query(MessageTag).filter(MessageTag.id == tag_id, MessageTag.user_id == user_id).first()
    if not tag:
        return False
    (
        db.query(MessageRecipient)
        .filter(MessageRecipient.user_id == user_id, MessageRecipient.tag_id == tag_id)
        .update({"tag_id": None}, synchronize_session=False)
    )
    db.delete(tag)
    db.flush()
    return True


# ==================== 旧通知迁移 ====================

def migrate_notifications_to_messages(db: Session) -> int:
    """把历史 `notifications` 数据一次性并入站内信（幂等）

    - 幂等：以 system_configs 中的标记位控制，只执行一次；
    - 合并：同一批「同标题 + 同内容 + 同关联 + 同一秒」的通知合并为一条消息
      （原 notify_super_admins 等场景会对每个管理员各写一行，直接迁移会让
      收件箱出现大量重复条目）；
    - 旧表保留不删，便于回滚。
    """
    from app.models.notification import Notification
    from app.models.system_config import SystemConfig

    flag = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key == MIGRATION_FLAG_KEY)
        .first()
    )
    if flag and (flag.config_value or "") == "1":
        return 0
    if flag is None:
        flag = SystemConfig(
            config_key=MIGRATION_FLAG_KEY,
            config_value="0",
            description="[系统] 旧通知迁移到站内信的标记（请勿删除）",
            updated_by="system",
        )
        db.add(flag)

    rows = db.query(Notification).order_by(Notification.id).all()
    migrated = 0
    if rows:
        groups: dict[tuple, list] = {}
        for n in rows:
            created = n.created_at.replace(microsecond=0) if n.created_at else None
            key = (n.title, n.content, n.related_type, n.related_id, created)
            groups.setdefault(key, []).append(n)

        for (title, content, rtype, rid, created), items in groups.items():
            msg = Message(
                title=title, content=content, sender_id=None, msg_type=MSG_TYPE_SYSTEM,
                related_type=rtype, related_id=rid, created_at=created or utc_now(),
            )
            db.add(msg)
            db.flush()
            merged: dict[str, bool] = {}
            for n in items:
                # 同一收件人在同一批里可能出现多次：合并为一行，已读取「或」
                merged[n.user_id] = merged.get(n.user_id, False) or bool(n.is_read)
            for uid, is_read in merged.items():
                db.add(MessageRecipient(
                    message_id=msg.id, user_id=uid,
                    is_read=is_read, is_starred=False, is_archived=False, is_deleted=False,
                    created_at=created or utc_now(),
                ))
            migrated += len(merged)
        db.flush()

    flag.config_value = "1"
    db.flush()
    if migrated:
        logger.info("旧通知已并入站内信：%d 条收件记录（%d 条消息）", migrated, len(rows) and len(groups))
    return migrated
