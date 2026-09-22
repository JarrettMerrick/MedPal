# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库的组织层服务：分类（沿用标识分类）与标签（按维度分组）。

[调整 2026-09-17] 需求：文件管理中的分类**沿用「标识设置 → 标识分类」**。

原实现为文件库自建的一套树形分类（file_categories 表 + 增删改入口），
与标识分类（signage_categories）各维护一份，容易出现两处口径不一致。
现统一为：
  - 数据源：SignageCategory（标识分类），**扁平结构**（标识分类本身无层级）；
  - 本模块的分类部分**只读**：仅提供列表与文件数统计，
    分类的增删改统一在「标识设置 → 标识分类」页面完成（文件管理页无入口）；
  - 原 file_categories 表不再使用（模型已移除，表本身保留在库中不删除）。

标签部分保持原样：仍按 group_name 分维度（项目 / 类型 / 状态…），
同维度内同名唯一、可着色，可在文件管理页维护。
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.design_file import DesignFile, DesignFileTag, FileTag
from app.models.signage_settings import SignageCategory
from app.schemas.design_file import FileTagCreate, FileTagUpdate


# ==================== 分类（沿用标识分类，只读） ====================

def get_all_categories(db: Session) -> list[SignageCategory]:
    """全部标识分类（启用的排在前面，其余按名称）"""
    return (
        db.query(SignageCategory)
        .order_by(SignageCategory.is_active.desc(), SignageCategory.name)
        .all()
    )


def get_category(db: Session, category_id: int) -> SignageCategory | None:
    """按 ID 取标识分类（文件归属校验用）"""
    return db.query(SignageCategory).filter(SignageCategory.id == category_id).first()


def get_category_by_name(db: Session, name: str) -> SignageCategory | None:
    """按名称取标识分类（文件按分类名筛选时使用）。

    [新增 2026-09-17] 标识表存的是**分类名称**（signages.category），
    文件表存的是**分类 ID**（design_files.category_id）；
    标识表单传入自身分类名做同分类筛选时，需要一次名称到 ID 的解析。
    名称不存在时返回 None，由调用方决定「宁可不给选」的保守行为。
    """
    keyword = (name or "").strip()
    if not keyword:
        return None
    return db.query(SignageCategory).filter(SignageCategory.name == keyword).first()


def build_category_list(db: Session) -> list[dict]:
    """分类列表（含每个分类下的文件数），数据源为标识分类。

    已禁用（is_active=False）的分类同样返回：历史文件可能仍挂在该分类下，
    筛选栏需要能看到，前端以弱化样式区分。
    """
    categories = get_all_categories(db)
    counts = dict(
        db.query(DesignFile.category_id, func.count(DesignFile.id))
        .filter(DesignFile.is_deleted == False, DesignFile.category_id.isnot(None))  # noqa: E712
        .group_by(DesignFile.category_id)
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "color": c.color,
            "description": c.description,
            "is_active": bool(c.is_active),
            "file_count": counts.get(c.id, 0),
        }
        for c in categories
    ]


# ==================== 标签（按维度分组） ====================

def get_all_tags(db: Session, group_name: str | None = None) -> list[dict]:
    """全部标签（含使用计数，回收站文件不计入）"""
    query = db.query(FileTag)
    if group_name:
        query = query.filter(FileTag.group_name == group_name)
    tags = query.order_by(FileTag.group_name, FileTag.name).all()
    counts = dict(
        db.query(DesignFileTag.tag_id, func.count(DesignFileTag.id))
        .join(DesignFile, DesignFile.id == DesignFileTag.file_id)
        .filter(DesignFile.is_deleted == False)  # noqa: E712
        .group_by(DesignFileTag.tag_id)
        .all()
    )
    return [
        {
            "id": t.id, "name": t.name, "group_name": t.group_name, "color": t.color,
            "created_at": t.created_at, "file_count": counts.get(t.id, 0),
        }
        for t in tags
    ]


def get_tag(db: Session, tag_id: int) -> FileTag | None:
    return db.query(FileTag).filter(FileTag.id == tag_id).first()


def create_tag(db: Session, data: FileTagCreate, operator: str | None) -> FileTag:
    name = (data.name or "").strip()
    group = (data.group_name or "通用").strip()
    if not name:
        raise ValueError("标签名不能为空")
    duplicated = db.query(FileTag).filter(
        FileTag.name == name, FileTag.group_name == group,
    ).first()
    if duplicated:
        raise ValueError(f"「{group}」维度下已存在同名标签")
    tag = FileTag(name=name, group_name=group, color=data.color, created_by=operator)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(db: Session, tag_id: int, data: FileTagUpdate) -> FileTag:
    tag = get_tag(db, tag_id)
    if not tag:
        raise ValueError("标签不存在")
    payload = data.model_dump(exclude_unset=True)
    name = (payload.get("name") or tag.name).strip()
    group = (payload.get("group_name") or tag.group_name).strip()
    duplicated = db.query(FileTag).filter(
        FileTag.name == name, FileTag.group_name == group, FileTag.id != tag_id,
    ).first()
    if duplicated:
        raise ValueError(f"「{group}」维度下已存在同名标签")
    tag.name = name
    tag.group_name = group
    if "color" in payload:
        tag.color = payload["color"]
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag_id: int) -> dict:
    """删除标签：同时解除其与文件的关联（不影响文件本身）"""
    tag = get_tag(db, tag_id)
    if not tag:
        raise ValueError("标签不存在")
    db.query(DesignFileTag).filter(DesignFileTag.tag_id == tag_id).delete(
        synchronize_session=False,
    )
    db.delete(tag)
    db.commit()
    return {"ok": True}


def set_file_tags(db: Session, file_id: int, tag_ids: list[int] | None) -> None:
    """全量替换某文件的标签（传空数组即清空）"""
    db.query(DesignFileTag).filter(DesignFileTag.file_id == file_id).delete(
        synchronize_session=False,
    )
    for tag_id in set(tag_ids or []):
        db.add(DesignFileTag(file_id=file_id, tag_id=tag_id))
    db.flush()


def add_file_tags(db: Session, file_ids: list[int], tag_ids: list[int]) -> int:
    """批量追加标签（自动去重），返回新增关联数"""
    if not file_ids or not tag_ids:
        return 0
    existing = set(
        db.query(DesignFileTag.file_id, DesignFileTag.tag_id)
        .filter(DesignFileTag.file_id.in_(file_ids))
        .all()
    )
    added = 0
    for file_id in file_ids:
        for tag_id in set(tag_ids):
            if (file_id, tag_id) not in existing:
                db.add(DesignFileTag(file_id=file_id, tag_id=tag_id))
                added += 1
    db.flush()
    return added


def remove_file_tags(db: Session, file_ids: list[int], tag_ids: list[int]) -> int:
    """批量移除标签，返回解除关联数"""
    if not file_ids or not tag_ids:
        return 0
    return db.query(DesignFileTag).filter(
        DesignFileTag.file_id.in_(file_ids), DesignFileTag.tag_id.in_(tag_ids),
    ).delete(synchronize_session=False)
