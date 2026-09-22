# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy.orm import Session

from app.models.staff_card import StaffCard
from app.utils import utc_now


def create_card(
    db: Session,
    entity_type: str,
    entity_id: str,
    card_photo: str,
    uploaded_by: str,
) -> StaffCard:
    """创建卡片记录"""
    card = StaffCard(
        entity_type=entity_type,
        entity_id=entity_id,
        card_photo=card_photo,
        status="pending",
        uploaded_by=uploaded_by,
        uploaded_at=utc_now(),
    )
    db.add(card)
    db.flush()
    return card


def get_card(db: Session, card_id: int) -> StaffCard | None:
    """获取单个卡片"""
    return db.query(StaffCard).filter(StaffCard.id == card_id).first()


def get_cards_by_entity(
    db: Session,
    entity_type: str,
    entity_id: str,
    status: str | None = None,
) -> list[StaffCard]:
    """获取实体的所有卡片"""
    query = db.query(StaffCard).filter(
        StaffCard.entity_type == entity_type,
        StaffCard.entity_id == entity_id,
    )
    if status:
        query = query.filter(StaffCard.status == status)
    return query.order_by(StaffCard.uploaded_at.desc()).all()


def get_pending_cards(
    db: Session,
    entity_type: str | None = None,
    entity_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[StaffCard], int]:
    """获取待确认的卡片列表"""
    query = db.query(StaffCard).filter(StaffCard.status == "pending")
    
    if entity_type:
        query = query.filter(StaffCard.entity_type == entity_type)
    if entity_id:
        query = query.filter(StaffCard.entity_id == entity_id)
    
    total = query.count()
    items = query.order_by(StaffCard.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return items, total


def confirm_card(
    db: Session,
    card_id: int,
    confirmed_by: str,
) -> StaffCard | None:
    """确认卡片"""
    card = get_card(db, card_id)
    if not card:
        return None
    
    card.status = "confirmed"
    card.confirmed_by = confirmed_by
    card.confirmed_at = utc_now()
    
    db.flush()
    return card


def reject_card(
    db: Session,
    card_id: int,
    rejected_by: str,
    reject_reason: str | None = None,
) -> StaffCard | None:
    """拒绝卡片"""
    card = get_card(db, card_id)
    if not card:
        return None
    
    card.status = "rejected"
    card.confirmed_by = rejected_by
    card.confirmed_at = utc_now()
    card.reject_reason = reject_reason
    
    db.flush()
    return card


def delete_card(db: Session, card_id: int) -> bool:
    """删除卡片"""
    card = get_card(db, card_id)
    if not card:
        return False
    
    db.delete(card)
    db.flush()
    return True
