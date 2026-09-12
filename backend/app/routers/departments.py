# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 添加 Request 导入，用于获取客户端 IP 地址记录到系统日志
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    has_permission, has_any_permission,
    PERM_DEPT_VIEW, PERM_DEPT_CREATE, PERM_DEPT_EDIT, PERM_DEPT_DELETE,
    has_department_access, get_user_department_scope,
)
from app.models.user import User
from app.services.user_service import get_user
from app.schemas.department import DepartmentCreate, DepartmentListOut, DepartmentOut, DepartmentUpdate, SpecialtyImageOut, SpecialtyImageUpdate, EquipmentImageOut, EquipmentImageUpdate
from app.services.department_service import (
    create_department, delete_department, get_all_departments, get_department,
    get_departments, update_department, get_specialty_images,
    create_specialty_image, delete_specialty_image,
    get_equipment_images, create_equipment_image, delete_equipment_image,
)
from app.services.audit_service import record_modification, build_change_summary
from app.services.modification_notify import notify_super_admins
from app.services.upload_service import save_upload_file, delete_file
from app.models.department import DepartmentSpecialty, SpecialtyImage, DepartmentEquipment, EquipmentImage
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

router = APIRouter(prefix="/api/departments", tags=["科室管理"])

DEPT_FIELD_LABELS = {
    "name": "科室名称", "description": "科室介绍",
}


def _can_manage_dept_category(user: User, category: str) -> bool:
    """判断用户是否有权管理指定分类的科室（基于权限表，admin_manager 自动通过）"""
    return has_permission(user, PERM_DEPT_CREATE)


def _specialty_in_department(db: Session, specialty_id: int, department_id: int) -> bool:
    """[改进/D3] 校验特色技术是否属于指定科室（防跨科室越权改/删图片）"""
    return db.query(DepartmentSpecialty).filter(
        DepartmentSpecialty.id == specialty_id,
        DepartmentSpecialty.department_id == department_id,
    ).first() is not None


def _equipment_in_department(db: Session, equipment_id: int, department_id: int) -> bool:
    """[改进/D3] 校验设备是否属于指定科室（防跨科室越权改/删图片）"""
    return db.query(DepartmentEquipment).filter(
        DepartmentEquipment.id == equipment_id,
        DepartmentEquipment.department_id == department_id,
    ).first() is not None


def _can_edit_dept(user: User, dept, db: Session = None) -> bool:
    """判断用户是否有权编辑指定科室（基于权限表 + 数据范围，admin_manager 自动通过）"""
    if not has_permission(user, PERM_DEPT_EDIT):
        return False
    if db:
        return has_department_access(user, dept.name, db)
    if hasattr(dept, "name") and user.department == dept.name:
        return True
    return False


@router.get("", response_model=DepartmentListOut)
def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_departments(db, page, page_size, search)


@router.get("/all")
def list_all_departments(
    category: str = Query(None, description="按分类过滤: 临床专科/护理病区/行政科室"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    depts = get_all_departments(db, category=category)
    # [修复 2026-09-01] 返回数据中添加 allowed_work_types 字段，支持混合科室配置
    return [{"id": d.id, "name": d.name, "category": d.category, "allowed_work_types": d.allowed_work_types} for d in depts]


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department_detail(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    return dept


@router.get("/{department_id}/staff-stats")
def get_department_staff_stats(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取科室人员统计数据（按职称，仅统计在职人员）"""
    from app.models.staff import Staff

    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")

    staffs = db.query(Staff.title, Staff.employee_id).filter(
        Staff.department == dept.name,
        Staff.status == "active",
    ).all()
    title_counts: dict[str, int] = {}
    for s in staffs:
        t = s.title or "未知"
        title_counts[t] = title_counts.get(t, 0) + 1
    return {
        "category": dept.category,
        "titles": title_counts,
        "total": len(staffs),
    }


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department_api(
    req: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _can_manage_dept_category(current_user, req.category):
        raise HTTPException(status_code=403, detail="无权限创建该分类的科室")
    # [修复 2026-09-02] 修复 create_department 调用参数错位：allowed_work_types 被遗漏，
    # 导致 specialties 列表被误传为 allowed_work_types 字符串，保存时 422 校验失败。
    dept = create_department(db, req.name, req.description, req.category, req.allowed_work_types, req.specialties, req.equipments)
    db.commit()
    return dept


@router.put("/{department_id}", response_model=DepartmentOut)
def update_department_api(
    department_id: int,
    req: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")

    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限修改该科室")

    # 科室管理员不能修改科室名称和分类
    # [改进] 仅当 name/category 实际发生变更时才拦截，避免"仅编辑介绍但前端仍传了原值"被误拒。
    # 比较时先去除首尾空白，防止存储值/传入值含空白导致「未改却被判定为已改」的误拒（CASE D）。
    from app.dependencies import _get_role_dept_scope
    if _get_role_dept_scope(current_user) == "managed":
        name_changed = req.name is not None and req.name.strip() != (dept.name or "").strip()
        category_changed = req.category is not None and req.category.strip() != (dept.category or "").strip()
        if name_changed or category_changed:
            raise HTTPException(status_code=403, detail="仅管理员可修改科室名称和分类")

    old_data = {"name": dept.name, "description": dept.description}
    update_data = {}
    if req.name is not None:
        update_data["name"] = req.name
    if req.description is not None:
        update_data["description"] = req.description
    change_summary = build_change_summary(old_data, update_data, DEPT_FIELD_LABELS)

    # [改进] 追加特色技术/设备的增删改摘要，使审计记录覆盖全部关联变更
    summary_parts = []
    if req.specialties is not None:
        old_spec_ids = {s.id for s in dept.specialties}
        new_spec_ids = {s.id for s in req.specialties if s.id is not None}
        added = sum(1 for s in req.specialties if s.id is None)
        removed = len(old_spec_ids - new_spec_ids)
        changed = len(old_spec_ids & new_spec_ids)
        if added or removed or changed:
            summary_parts.append(f"特色技术(新增{added}/删除{removed}/修改{changed})")
    if req.equipments is not None:
        old_equip_ids = {e.id for e in dept.equipments}
        new_equip_ids = {e.id for e in req.equipments if e.id is not None}
        added = sum(1 for e in req.equipments if e.id is None)
        removed = len(old_equip_ids - new_equip_ids)
        changed = len(old_equip_ids & new_equip_ids)
        if added or removed or changed:
            summary_parts.append(f"特色设备(新增{added}/删除{removed}/修改{changed})")
    if summary_parts:
        extra = "；".join(summary_parts)
        change_summary = extra if change_summary == "更新操作" else change_summary + "；" + extra

    # [修复 2026-09-02] 修复 update_department 调用参数错位：补充漏传的 allowed_work_types 参数，
    # 与 create 保持一致，解决编辑科室保存混合工种配置时 allowed_work_types 丢失的问题。
    dept = update_department(db, department_id, req.name, req.description, req.category, req.group_photo, req.allowed_work_types, req.specialties, req.equipments, updated_by=current_user.employee_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")

    # [修复 2026-09-01] 传递客户端 IP 到 record_modification，记录到系统日志
    client_ip = get_client_ip(request)
    mod_record = record_modification(db, entity_type="department", entity_id=str(department_id),
                                     modified_by=current_user.employee_id, change_summary=change_summary,
                                     ip_address=client_ip)
    # [调整 2026-09-11] 站内信提醒：超管 + 该科室的相关科室管理员（自动排除操作者本人）
    if change_summary != "更新操作":
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(db,
            title="科室信息被修改",
            content=f"{modifier_name} 修改了科室 {dept.name}(ID:{department_id}) 的{change_summary}",
            related_type="department",
            related_id=department_id,
            department=dept.name,
            exclude_user_id=current_user.employee_id)
    db.commit()
    return dept


@router.post("/{department_id}/specialties/{specialty_id}/images", response_model=SpecialtyImageOut, status_code=201)
async def upload_specialty_image(
    department_id: int,
    specialty_id: int,
    caption: str = Form("", max_length=20),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传特色技术图片（每个特色技术最多6张，分辨率不低于500x500）"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # 验证特色技术属于该科室
    specialty = db.query(DepartmentSpecialty).filter(
        DepartmentSpecialty.id == specialty_id,
        DepartmentSpecialty.department_id == department_id,
    ).first()
    if not specialty:
        raise HTTPException(status_code=404, detail="特色技术不存在或不属于该科室")

    # 检查图片数量限制
    existing = get_specialty_images(db, specialty_id)
    if len(existing) >= 6:
        raise HTTPException(status_code=400, detail="每个特色技术最多6张图片")

    # 保存文件
    try:
        file_path = await save_upload_file(file, "dept", f"spec_{specialty_id}", photo_type="dept", min_width=500, min_height=500)
    except HTTPException as e:
        raise e
    except Exception as e:
        # [修复/问题6] 内部异常详情不再返回客户端，仅写日志，对外统一文案
        import logging
        logging.getLogger(__name__).error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")

    # 创建图片记录
    img = create_specialty_image(db, specialty_id, file_path, caption, sort_order=len(existing))
    db.commit()
    db.refresh(img)
    return img


@router.put("/{department_id}/specialties/{specialty_id}/images/{image_id}", response_model=SpecialtyImageOut)
def update_specialty_image_caption(
    department_id: int,
    specialty_id: int,
    image_id: int,
    req: SpecialtyImageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新特色技术图片备注"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # [改进/D3] 校验特色技术确实属于该科室，防止携带本科室 department_id
    # 但传入他科室 specialty_id/image_id 实现跨科室越权改图。
    if not _specialty_in_department(db, specialty_id, department_id):
        raise HTTPException(status_code=404, detail="特色技术不存在或不属于该科室")

    img = db.query(SpecialtyImage).filter(
        SpecialtyImage.id == image_id,
        SpecialtyImage.specialty_id == specialty_id,
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")

    if req.caption is not None:
        if len(req.caption) > 20:
            raise HTTPException(status_code=400, detail="备注不能超过20字")
        img.caption = req.caption

    db.commit()
    db.refresh(img)
    return img


@router.delete("/{department_id}/specialties/{specialty_id}/images/{image_id}")
def delete_specialty_image_api(
    department_id: int,
    specialty_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除特色技术图片"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # [改进/D3] 先校验特色技术归属该科室 + 图片归属该特色技术，
    # 杜绝仅凭 image_id 删除他科室图片（原实现直接按 image_id 删除）。
    if not _specialty_in_department(db, specialty_id, department_id):
        raise HTTPException(status_code=404, detail="特色技术不存在或不属于该科室")
    img = db.query(SpecialtyImage).filter(
        SpecialtyImage.id == image_id,
        SpecialtyImage.specialty_id == specialty_id,
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")

    image_url = img.image_url
    delete_specialty_image(db, image_id)
    delete_file(image_url)
    db.commit()
    return {"message": "图片删除成功"}


# ==================== 设备图片接口 ====================

@router.post("/{department_id}/equipments/{equipment_id}/images", response_model=EquipmentImageOut, status_code=201)
async def upload_equipment_image(
    department_id: int,
    equipment_id: int,
    caption: str = Form("", max_length=20),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传设备图片（每个设备最多6张，分辨率不低于500x500）"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # 验证设备属于该科室
    equipment = db.query(DepartmentEquipment).filter(
        DepartmentEquipment.id == equipment_id,
        DepartmentEquipment.department_id == department_id,
    ).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="设备不存在或不属于该科室")

    # 检查图片数量限制
    existing = get_equipment_images(db, equipment_id)
    if len(existing) >= 6:
        raise HTTPException(status_code=400, detail="每个设备最多6张图片")

    # 保存文件
    try:
        file_path = await save_upload_file(file, "dept", f"equip_{equipment_id}", photo_type="dept", min_width=500, min_height=500)
    except HTTPException as e:
        raise e
    except Exception as e:
        # [修复/问题6] 内部异常详情不再返回客户端，仅写日志，对外统一文案
        import logging
        logging.getLogger(__name__).error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")

    # 创建图片记录
    img = create_equipment_image(db, equipment_id, file_path, caption, sort_order=len(existing))
    db.commit()
    db.refresh(img)
    return img


@router.put("/{department_id}/equipments/{equipment_id}/images/{image_id}", response_model=EquipmentImageOut)
def update_equipment_image_caption(
    department_id: int,
    equipment_id: int,
    image_id: int,
    req: EquipmentImageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新设备图片备注"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # [改进/D3] 校验设备确实属于该科室，防止跨科室越权改图。
    if not _equipment_in_department(db, equipment_id, department_id):
        raise HTTPException(status_code=404, detail="设备不存在或不属于该科室")

    img = db.query(EquipmentImage).filter(
        EquipmentImage.id == image_id,
        EquipmentImage.equipment_id == equipment_id,
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")

    if req.caption is not None:
        if len(req.caption) > 20:
            raise HTTPException(status_code=400, detail="备注不能超过20字")
        img.caption = req.caption

    db.commit()
    db.refresh(img)
    return img


@router.delete("/{department_id}/equipments/{equipment_id}/images/{image_id}")
def delete_equipment_image_api(
    department_id: int,
    equipment_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除设备图片"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    # [改进/D3] 先校验设备归属该科室 + 图片归属该设备，
    # 杜绝仅凭 image_id 删除他科室设备图片。
    if not _equipment_in_department(db, equipment_id, department_id):
        raise HTTPException(status_code=404, detail="设备不存在或不属于该科室")
    img = db.query(EquipmentImage).filter(
        EquipmentImage.id == image_id,
        EquipmentImage.equipment_id == equipment_id,
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="图片不存在")

    image_url = img.image_url
    delete_equipment_image(db, image_id)
    delete_file(image_url)
    db.commit()
    return {"message": "图片删除成功"}


# ==================== 科室合照 ====================

@router.post("/{department_id}/group-photo")
async def upload_group_photo(
    department_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传科室合照（覆盖旧照片）"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    try:
        file_path = await save_upload_file(file, "dept", f"group_{department_id}", photo_type="dept", min_width=0, min_height=0)
    except HTTPException as e:
        raise e
    except Exception as e:
        # [修复/问题6] 内部异常详情不再返回客户端，仅写日志，对外统一文案
        import logging
        logging.getLogger(__name__).error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")

    # 删除旧照片
    if dept.group_photo:
        delete_file(dept.group_photo)

    dept.group_photo = file_path
    dept.updated_by = current_user.employee_id
    db.commit()
    return {"group_photo": file_path, "message": "合照上传成功"}


@router.delete("/{department_id}/group-photo")
def delete_group_photo(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除科室合照"""
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    if not _can_edit_dept(current_user, dept, db):
        raise HTTPException(status_code=403, detail="无权限操作")

    if dept.group_photo:
        delete_file(dept.group_photo)
        dept.group_photo = None
        dept.updated_by = current_user.employee_id
        db.commit()

    return {"message": "合照已删除"}


@router.delete("/{department_id}")
def delete_department_api(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dept = get_department(db, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")
    # [改进/D1] 删除科室应使用独立的"删除"权限点(PERM_DEPT_DELETE)，而非"创建"权限。
    # 原实现用 _can_manage_dept_category(仅校验 PERM_DEPT_CREATE)，导致任何有建科室权限者
    # 都能删科室，与 user/staff 删除接口使用独立删除权限点的设计不一致。
    if not has_permission(current_user, PERM_DEPT_DELETE):
        raise HTTPException(status_code=403, detail="无权限删除科室")
    if not has_department_access(current_user, dept.name, db):
        raise HTTPException(status_code=403, detail="无权删除该科室（超出数据范围）")

    # 删除前校验关联数据，避免产生孤儿记录
    from app.models.staff import Staff
    # [修复 2026-09-11] 仅在职人员阻止删除科室：离职人员不应长期占用科室（其档案保留在「离职人员」页）
    if db.query(Staff).filter(Staff.department == dept.name, Staff.status == "active").first():
        raise HTTPException(status_code=400, detail="该科室下仍有在职人员，无法删除")
    if db.query(DepartmentSpecialty).filter(DepartmentSpecialty.department_id == department_id).first():
        raise HTTPException(status_code=400, detail="该科室下仍有特色技术，无法删除")
    if db.query(DepartmentEquipment).filter(DepartmentEquipment.department_id == department_id).first():
        raise HTTPException(status_code=400, detail="该科室下仍有设备，无法删除")

    if not delete_department(db, department_id):
        raise HTTPException(status_code=404, detail="科室不存在")
    db.commit()
    return {"message": "删除成功"}
