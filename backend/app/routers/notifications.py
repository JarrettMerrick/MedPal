# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""通知接口（兼容层）

[调整 2026-09-11] 「统一站内信」改造后，系统通知已并入站内信表。
本路由保留原有 URL 与响应结构（供旧前端/书签平滑过渡），
内部全部代理到 `services/message_service`，新前端请使用 `/api/messages`。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import message_service

router = APIRouter(prefix="/api/notifications", tags=["通知（兼容层）"])


@router.get("")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户的站内信列表（兼容旧通知响应结构）"""
    rows, total = message_service.list_inbox(
        db, current_user.employee_id, page=page, page_size=page_size, box="all",
    )
    return {
        "items": [
            {
                "id": m.id,
                "title": m.title,
                "content": m.content,
                "related_type": m.related_type,
                "related_id": m.related_id,
                "is_read": bool(r.is_read),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for r, m in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/unread-count")
def get_unread(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """未读数量"""
    return {"count": message_service.get_unread_count(db, current_user.employee_id)}


@router.put("/{notification_id}/read")
def read_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """标记单条已读（按归属校验，越权返回 404）"""
    if not message_service.mark_read(db, notification_id, current_user.employee_id):
        raise HTTPException(status_code=404, detail="通知不存在")
    db.commit()
    return {"message": "已标记为已读"}


@router.put("/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """全部标为已读"""
    count = message_service.mark_all_read(db, current_user.employee_id)
    db.commit()
    return {"message": f"已标记 {count} 条通知为已读"}
