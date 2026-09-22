# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""站内信接口（统一消息中心）

权限：
    - 查看/已读/标注：message.view（三种预设角色默认拥有）
    - 私发：message.send；群发：message.broadcast（默认仅超级管理员）
    - 所有收件人侧操作均按当前登录用户过滤，无法操作他人消息
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    PERM_MESSAGE_BROADCAST, PERM_MESSAGE_SEND,
    get_current_user, has_permission, require_permission, PERM_MESSAGE_VIEW,
)
from app.models.message import (
    MSG_TYPE_BROADCAST, MSG_TYPE_DIRECT, Message, MessageRecipient, MessageTag,
)
from app.models.user import User
from app.schemas.message import (
    MarkReadRequest, MessageFlagsRequest, MessageIdsRequest, MessageTagCreate,
    MessageTagUpdate, RecipientPreviewRequest, SendMessageRequest,
)
from app.services import message_service
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import to_iso_utc

router = APIRouter(prefix="/api/messages", tags=["站内信"])


# ==================== 序列化辅助 ====================

def _sender_names(db: Session, messages: list[Message]) -> dict[str, str]:
    """批量取发送人姓名，避免 N+1 查询"""
    ids = {m.sender_id for m in messages if m.sender_id}
    if not ids:
        return {}
    rows = db.query(User.employee_id, User.name).filter(User.employee_id.in_(ids)).all()
    return {r[0]: r[1] for r in rows}


def _serialize(
    m: Message, r: MessageRecipient | None,
    senders: dict[str, str], tags: dict[int, MessageTag],
) -> dict:
    tag = tags.get(r.tag_id) if (r and r.tag_id) else None
    return {
        "id": m.id,
        "title": m.title,
        "content": m.content,
        "msg_type": m.msg_type,
        "sender_id": m.sender_id,
        "sender_name": senders.get(m.sender_id) if m.sender_id else None,
        "related_type": m.related_type,
        "related_id": m.related_id,
        "created_at": to_iso_utc(m.created_at),
        "is_read": bool(r.is_read) if r else True,
        "is_starred": bool(r.is_starred) if r else False,
        "is_archived": bool(r.is_archived) if r else False,
        "tag_id": r.tag_id if r else None,
        "tag_name": tag.name if tag else None,
        "tag_color": tag.color if tag else None,
    }


def _tag_map(db: Session, user_id: str) -> dict[int, MessageTag]:
    return {t.id: t for t in message_service.list_tags(db, user_id)}


# ==================== 收件箱 ====================

@router.get("")
def list_inbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    box: str = Query("all", description="all / unread / starred / archived"),
    tag_id: int | None = Query(None),
    keyword: str | None = Query(None),
    msg_type: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """收件箱列表"""
    rows, total = message_service.list_inbox(
        db, current_user.employee_id, page=page, page_size=page_size,
        box=box, tag_id=tag_id, keyword=keyword, msg_type=msg_type,
    )
    senders = _sender_names(db, [m for _r, m in rows])
    tags = _tag_map(db, current_user.employee_id)
    return {
        "items": [_serialize(m, r, senders, tags) for r, m in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "unread": message_service.get_unread_count(db, current_user.employee_id),
    }


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """未读数量（顶栏铃铛角标）"""
    return {"count": message_service.get_unread_count(db, current_user.employee_id)}


@router.get("/sent")
def list_sent(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """发件箱列表（含收件人数与已读数）"""
    items, total, totals, reads = message_service.list_sent(
        db, current_user.employee_id, page=page, page_size=page_size, keyword=keyword,
    )
    return {
        "items": [
            {
                "id": m.id,
                "title": m.title,
                "content": m.content,
                "msg_type": m.msg_type,
                "created_at": to_iso_utc(m.created_at),
                "recipient_count": totals.get(m.id, 0),
                "read_count": reads.get(m.id, 0),
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/sent/{message_id}")
def get_sent_detail(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """发件详情（含收件人明细与已读情况）"""
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m or m.sender_id != current_user.employee_id:
        raise HTTPException(status_code=404, detail="消息不存在")
    rows = (
        db.query(MessageRecipient, User)
        .outerjoin(User, User.employee_id == MessageRecipient.user_id)
        .filter(MessageRecipient.message_id == message_id)
        .all()
    )
    return {
        "id": m.id,
        "title": m.title,
        "content": m.content,
        "msg_type": m.msg_type,
        "created_at": to_iso_utc(m.created_at),
        "recipient_count": len(rows),
        "read_count": sum(1 for r, _u in rows if r.is_read),
        "recipients": [
            {
                "employee_id": r.user_id,
                "name": u.name if u else None,
                "department": u.department if u else None,
                "is_read": bool(r.is_read),
                "read_at": to_iso_utc(r.read_at),
            }
            for r, u in rows
        ],
    }


# ==================== 标签字典（收件人自定义） ====================

@router.get("/tags")
def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """我的标签字典（含各标签下消息数）"""
    counts = message_service.count_by_tag(db, current_user.employee_id)
    return [
        {
            "id": t.id, "name": t.name, "color": t.color,
            "sort_order": t.sort_order, "count": counts.get(t.id, 0),
        }
        for t in message_service.list_tags(db, current_user.employee_id)
    ]


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(
    req: MessageTagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """新建标签"""
    try:
        t = message_service.create_tag(db, current_user.employee_id, req.name, req.color)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color, "count": 0}


@router.put("/tags/{tag_id}")
def update_tag(
    tag_id: int,
    req: MessageTagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """重命名/改色标签"""
    try:
        t = message_service.update_tag(
            db, current_user.employee_id, tag_id, req.name, req.color,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not t:
        raise HTTPException(status_code=404, detail="标签不存在")
    db.commit()
    return {"message": "已更新"}


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """删除标签（自动解除对该标签的引用）"""
    if not message_service.delete_tag(db, current_user.employee_id, tag_id):
        raise HTTPException(status_code=404, detail="标签不存在")
    db.commit()
    return {"message": "已删除"}


# ==================== 批量状态操作 ====================

@router.put("/read-all")
def read_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """全部标为已读"""
    count = message_service.mark_all_read(db, current_user.employee_id)
    db.commit()
    return {"message": f"已标记 {count} 条为已读", "count": count}


@router.put("/mark-read")
def mark_read_batch(
    req: MarkReadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """批量标记已读 / 未读"""
    count = message_service.mark_many_read(
        db, current_user.employee_id, req.ids, req.is_read,
    )
    db.commit()
    return {"message": f"已更新 {count} 条", "count": count}


@router.put("/flags")
def update_flags(
    req: MessageFlagsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """批量标注：星标 / 归档 / 自定义标签"""
    tag_id = None if req.clear_tag else (req.tag_id if req.tag_id is not None else message_service.UNSET)
    try:
        count = message_service.update_flags(
            db, current_user.employee_id, req.ids,
            is_starred=req.is_starred, is_archived=req.is_archived, tag_id=tag_id,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return {"message": f"已更新 {count} 条", "count": count}


@router.post("/bulk-delete")
def bulk_delete(
    req: MessageIdsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """批量删除（收件人侧软删除，不影响他人）"""
    count = message_service.soft_delete(db, current_user.employee_id, req.ids)
    db.commit()
    return {"message": f"已删除 {count} 条", "count": count}


@router.delete("/{message_id}")
def delete_one(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """删除单条（收件人侧软删除）"""
    count = message_service.soft_delete(db, current_user.employee_id, [message_id])
    if not count:
        raise HTTPException(status_code=404, detail="消息不存在")
    db.commit()
    return {"message": "已删除"}


# ==================== 发送 ====================

@router.post("/recipients/preview")
def preview_recipients(
    req: RecipientPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """群发前预览收件人（人数 + 前 20 条明细）"""
    if not (
        has_permission(current_user, PERM_MESSAGE_SEND)
        or has_permission(current_user, PERM_MESSAGE_BROADCAST)
    ):
        raise HTTPException(status_code=403, detail="权限不足")
    ids = message_service.resolve_recipients(
        db, req.target_type, req.target_values, exclude_user_id=current_user.employee_id,
    )
    return message_service.describe_recipients(db, ids)


@router.post("", status_code=status.HTTP_201_CREATED)
def send_message(
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送站内信（私发 / 群发）

    - 私发需 message.send，群发需 message.broadcast（默认仅超级管理员）；
    - 自动排除发送者本人，避免给自己发信；
    - 收件人上限 2000，超出部分忽略（防误选"全员"造成超大写入）。
    """
    if req.send_type == "broadcast":
        if not has_permission(current_user, PERM_MESSAGE_BROADCAST):
            raise HTTPException(status_code=403, detail="无群发站内信权限")
        recipients = message_service.resolve_recipients(
            db, req.target_type or "users", req.target_values,
            exclude_user_id=current_user.employee_id,
        )
        msg_type = MSG_TYPE_BROADCAST
    else:
        if not has_permission(current_user, PERM_MESSAGE_SEND):
            raise HTTPException(status_code=403, detail="无发送站内信权限")
        # 私发同样校验工号真实存在且启用
        recipients = message_service.resolve_recipients(
            db, "users", req.recipients, exclude_user_id=current_user.employee_id,
        )
        msg_type = MSG_TYPE_DIRECT

    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="没有匹配到有效收件人（可能账号已禁用，或只选中了你自己）",
        )

    msg = message_service.create_message(
        db, title=req.title, content=req.content or "", recipients=recipients,
        sender_id=current_user.employee_id, msg_type=msg_type,
    )
    db.commit()
    return {
        "message": f"已发送给 {len(recipients)} 人",
        "id": msg.id if msg else None,
        "recipient_count": len(recipients),
    }


# ==================== 详情与单条已读 ====================

@router.get("/{message_id}")
def get_message_detail(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """收件详情（打开即标记已读）"""
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="消息不存在")
    row = message_service.get_recipient_row(db, message_id, current_user.employee_id)
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在")
    if not row.is_read:
        message_service.mark_read(db, message_id, current_user.employee_id)
        db.commit()
    senders = _sender_names(db, [m])
    tags = _tag_map(db, current_user.employee_id)
    return _serialize(m, row, senders, tags)


@router.put("/{message_id}/read")
def read_one(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_MESSAGE_VIEW)),
):
    """标记单条已读"""
    if not message_service.mark_read(db, message_id, current_user.employee_id):
        raise HTTPException(status_code=404, detail="消息不存在")
    db.commit()
    return {"message": "已标记为已读"}
