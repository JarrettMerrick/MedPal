# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timezone
from sqlalchemy.orm import Session, joinedload

from app.models.department import Department, DepartmentSpecialty, SpecialtyImage, DepartmentEquipment, EquipmentImage
from app.models.user_department_scope import UserDepartmentScope
from app.utils import utc_now
from app.services.upload_service import delete_file


def _sync_specialties(db: Session, department_id: int, specs: list) -> None:
    """增量同步特色技术：按 id 更新/新建，删除已移除项（含其图片与磁盘文件）。

    [改进] 旧实现整体 delete+recreate 并忽略 spec.id，会导致：
      - 所有绑定图片变为孤儿记录（介绍编辑后图片全部消失）
      - 磁盘图片文件永不清理（存储泄漏）
      - 特色技术 ID 改变，破坏后续引用
    现改为 upsert，仅删除真正被移除的项。
    """
    existing = {
        s.id: s for s in db.query(DepartmentSpecialty).filter(
            DepartmentSpecialty.department_id == department_id
        ).all()
    }
    incoming_ids = {getattr(s, "id", None) for s in specs if getattr(s, "id", None) is not None}

    # 删除被移除的特色技术：先清理其图片与磁盘文件，避免孤儿记录/文件
    for sid, s in existing.items():
        if sid not in incoming_ids:
            for img in db.query(SpecialtyImage).filter(SpecialtyImage.specialty_id == sid).all():
                delete_file(img.image_url)
            db.query(SpecialtyImage).filter(SpecialtyImage.specialty_id == sid).delete()
            db.delete(s)

    # 更新已存在项 / 新建项（保留原 id 与图片）
    for idx, spec in enumerate(specs):
        sid = getattr(spec, "id", None)
        sort_order = spec.sort_order if spec.sort_order is not None else idx
        if sid is not None and sid in existing:
            s = existing[sid]
            s.name = spec.name
            s.detail = spec.detail or ""
            s.sort_order = sort_order
        else:
            db.add(DepartmentSpecialty(
                department_id=department_id,
                name=spec.name,
                detail=spec.detail or "",
                sort_order=sort_order,
            ))


def _sync_equipments(db: Session, department_id: int, equips: list) -> None:
    """增量同步特色设备：逻辑同 _sync_specialties。

    [改进] 修复整体重建导致设备图片丢失/孤儿记录的问题。
    """
    existing = {
        e.id: e for e in db.query(DepartmentEquipment).filter(
            DepartmentEquipment.department_id == department_id
        ).all()
    }
    incoming_ids = {getattr(e, "id", None) for e in equips if getattr(e, "id", None) is not None}

    for eid, e in existing.items():
        if eid not in incoming_ids:
            for img in db.query(EquipmentImage).filter(EquipmentImage.equipment_id == eid).all():
                delete_file(img.image_url)
            db.query(EquipmentImage).filter(EquipmentImage.equipment_id == eid).delete()
            db.delete(e)

    for idx, equip in enumerate(equips):
        eid = getattr(equip, "id", None)
        sort_order = equip.sort_order if equip.sort_order is not None else idx
        if eid is not None and eid in existing:
            e = existing[eid]
            e.name = equip.name
            e.model = equip.model or ""
            e.function_description = equip.function_description or ""
            e.features = equip.features or ""
            e.sort_order = sort_order
        else:
            db.add(DepartmentEquipment(
                department_id=department_id,
                name=equip.name,
                model=equip.model or "",
                function_description=equip.function_description or "",
                features=equip.features or "",
                sort_order=sort_order,
            ))


def _load_relations(query):
    """加载科室及关联的特色技术、设备和图片"""
    return query.options(
        joinedload(Department.specialties).joinedload(DepartmentSpecialty.images),
        joinedload(Department.equipments).joinedload(DepartmentEquipment.images),
    )


def get_departments(
    db: Session, page: int = 1, page_size: int = 20, search: str = None
) -> dict:
    """获取科室列表（分页）"""
    query = db.query(Department)
    if search:
        query = query.filter(Department.name.ilike(f"%{search}%"))
    total = query.count()
    items = (
        _load_relations(query)
        .order_by(Department.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": items, "total": total}


def get_all_departments(db: Session, category: str = None) -> list:
    """获取所有科室（用于下拉选择），可按分类过滤"""
    query = db.query(Department).order_by(Department.id)
    if category:
        query = query.filter(Department.category == category)
    return query.all()


def get_department(db: Session, department_id: int) -> Department | None:
    """获取单个科室"""
    return (
        _load_relations(
            db.query(Department).filter(Department.id == department_id)
        )
        .first()
    )


def create_department(db: Session, name: str, description: str = "", category: str = "临床专科", allowed_work_types: str = None, specialties: list = None, equipments: list = None) -> Department:
    """创建科室"""
    # [修复 2026-09-01] 新增 allowed_work_types 参数，支持混合科室配置
    dept = Department(name=name, description=description, category=category, allowed_work_types=allowed_work_types)
    db.add(dept)
    db.flush()

    if specialties:
        for spec in specialties:
            s = DepartmentSpecialty(
                department_id=dept.id,
                name=spec.name,
                detail=spec.detail or "",
                sort_order=spec.sort_order or 0,
            )
            db.add(s)

    if equipments:
        for equip in equipments:
            e = DepartmentEquipment(
                department_id=dept.id,
                name=equip.name,
                model=equip.model or "",
                function_description=equip.function_description or "",
                features=equip.features or "",
                sort_order=equip.sort_order or 0,
            )
            db.add(e)

    db.flush()
    return dept


def update_department(db: Session, department_id: int, name: str = None, description: str = None, category: str = None, group_photo: str = None, allowed_work_types: str = None, specialties: list = None, equipments: list = None, updated_by: str = None) -> Department | None:
    """更新科室"""
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return None

    if name is not None:
        dept.name = name
    if description is not None:
        dept.description = description
    if category is not None:
        dept.category = category
    if group_photo is not None:
        dept.group_photo = group_photo if group_photo else None
    # [修复 2026-09-01] 新增 allowed_work_types 字段更新逻辑
    if allowed_work_types is not None:
        dept.allowed_work_types = allowed_work_types if allowed_work_types else None

    # [改进] 增量同步特色技术/设备（按 id upsert，保留图片，仅删真正移除项）
    if specialties is not None:
        _sync_specialties(db, department_id, specialties)

    if equipments is not None:
        _sync_equipments(db, department_id, equipments)

    dept.updated_by = updated_by
    dept.updated_at = utc_now()
    db.flush()
    return dept


def delete_department(db: Session, department_id: int) -> bool:
    """删除科室

    [改进/IO3] 删除前先清理磁盘上的关联图片文件，避免存储泄漏：
      - 科室合照 group_photo；
      - 防御性遍历特色技术/设备下的图片（正常调用方会先阻断存在关联的删除，
        此处兜底以防其他入口直接调用本函数造成孤儿文件）。
    """
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return False

    # 清理科室合照磁盘文件
    if dept.group_photo:
        delete_file(dept.group_photo)

    # 防御性清理关联图片磁盘文件
    spec_ids = [s.id for s in db.query(DepartmentSpecialty).filter(
        DepartmentSpecialty.department_id == department_id
    ).all()]
    if spec_ids:
        for img in db.query(SpecialtyImage).filter(SpecialtyImage.specialty_id.in_(spec_ids)).all():
            delete_file(img.image_url)
    equip_ids = [e.id for e in db.query(DepartmentEquipment).filter(
        DepartmentEquipment.department_id == department_id
    ).all()]
    if equip_ids:
        for img in db.query(EquipmentImage).filter(EquipmentImage.equipment_id.in_(equip_ids)).all():
            delete_file(img.image_url)

    # [修复/1.0.9] 删除科室前显式清理 user_department_scope 中引用该科室的授权记录。
    # 原实现未处理该关联，导致 SQLAlchemy ORM 在 db.delete(dept) 时尝试将
    # UserDepartmentScope.department_id 置 NULL（因为 Department.managed_by_users backref
    # 默认 cascade 仅为 save-update，不含 delete），而该列 NOT NULL，直接抛
    # IntegrityError → HTTP 500，任何角色（含 admin）均无法删除科室。
    db.query(UserDepartmentScope).filter(
        UserDepartmentScope.department_id == department_id
    ).delete(synchronize_session=False)

    db.delete(dept)
    db.flush()
    return True


def get_specialty_images(db: Session, specialty_id: int) -> list:
    """获取特色技术所有图片"""
    return (
        db.query(SpecialtyImage)
        .filter(SpecialtyImage.specialty_id == specialty_id)
        .order_by(SpecialtyImage.sort_order)
        .all()
    )


def create_specialty_image(db: Session, specialty_id: int, image_url: str, caption: str = "", sort_order: int = 0) -> SpecialtyImage:
    """创建特色技术图片"""
    img = SpecialtyImage(
        specialty_id=specialty_id,
        image_url=image_url,
        caption=caption,
        sort_order=sort_order,
    )
    db.add(img)
    db.flush()
    return img


def delete_specialty_image(db: Session, image_id: int) -> SpecialtyImage | None:
    """删除特色技术图片"""
    img = db.query(SpecialtyImage).filter(SpecialtyImage.id == image_id).first()
    if not img:
        return None
    db.delete(img)
    db.flush()
    return img


# ==================== 设备图片相关 ====================

def get_equipment_images(db: Session, equipment_id: int) -> list:
    """获取设备所有图片"""
    return (
        db.query(EquipmentImage)
        .filter(EquipmentImage.equipment_id == equipment_id)
        .order_by(EquipmentImage.sort_order)
        .all()
    )


def create_equipment_image(db: Session, equipment_id: int, image_url: str, caption: str = "", sort_order: int = 0) -> EquipmentImage:
    """创建设备图片"""
    img = EquipmentImage(
        equipment_id=equipment_id,
        image_url=image_url,
        caption=caption,
        sort_order=sort_order,
    )
    db.add(img)
    db.flush()
    return img


def delete_equipment_image(db: Session, image_id: int) -> EquipmentImage | None:
    """删除设备图片"""
    img = db.query(EquipmentImage).filter(EquipmentImage.id == image_id).first()
    if not img:
        return None
    db.delete(img)
    db.flush()
    return img
