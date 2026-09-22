# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    has_permission,
    # [修复 2026-09-17] 工卡详情/删除补数据范围校验所需的权限常量与工具
    has_any_permission,
    PERM_CARD_UPLOAD,
    PERM_STAFF_VIEW, PERM_STAFF_EDIT, PERM_STAFF_PHOTO_UPLOAD,
)
from app.models.user import User
from app.schemas.staff_card import StaffCardCreate, StaffCardListResponse, StaffCardResponse, StaffCardUpdate
# [新增 2026-09-15] 可配置通知中心（工卡上传/确认/拒绝通知统一走事件规则）
from app.services import notification_center
from app.services.card_service import (
    confirm_card,
    create_card,
    delete_card,
    get_card,
    get_cards_by_entity,
    get_pending_cards,
    reject_card,
)
from app.services.upload_service import save_upload_file, delete_file
from app.services.staff_service import get_staff
from app.services.notification_service import create_notification
# [新增 2026-09-09] 卡片敏感操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cards", tags=["卡片管理"])


def _can_upload_card(user: User) -> bool:
    """是否有上传卡片权限（基于权限表）"""
    return has_permission(user, PERM_CARD_UPLOAD)


def _can_confirm_card(user: User, card, db: Session) -> bool:
    """是否有确认卡片权限"""
    # 员工本人可以确认自己的卡片
    if card.entity_id == user.employee_id:
        return True
    
    # 有卡片上传权限的用户，可以确认管辖范围内人员的卡片
    if has_permission(user, PERM_CARD_UPLOAD):
        staff = get_staff(db, card.entity_id)
        if staff:
            from app.dependencies import get_user_department_scope
            dept_ids = get_user_department_scope(user, db)
            if staff.department:
                from app.models.department import Department
                target_dept = db.query(Department).filter(Department.name == staff.department).first()
                if target_dept and target_dept.id in dept_ids:
                    return True
    
    return False


def _card_in_user_scope(user: User, card, db: Session) -> bool:
    """[新增 2026-09-17] 工卡归属人员是否处于用户的数据范围内。

    department_scope=all 直接放行；其余角色按人员所属科室走 has_department_access。
    人员档案缺失或未归属科室时保守返回 False（本人卡片由调用方单独放行，不走本函数）。
    """
    from app.dependencies import _get_role_dept_scope, has_department_access
    if _get_role_dept_scope(user) == "all":
        return True
    staff = get_staff(db, card.entity_id)
    if not staff or not staff.department:
        return False
    return has_department_access(user, staff.department, db)


def _can_view_card(user: User, card, db: Session) -> bool:
    """[新增 2026-09-17] 是否可查看指定工卡详情。

    本人始终允许；查看他人卡片需具备人员查看类权限之一
    （card.upload / staff.view / staff.edit / staff.photo_upload），
    且处于其科室数据范围内——与列表接口的数据范围过滤口径保持一致。
    """
    if card.entity_id == user.employee_id:
        return True
    if not has_any_permission(user, PERM_CARD_UPLOAD, PERM_STAFF_VIEW, PERM_STAFF_EDIT, PERM_STAFF_PHOTO_UPLOAD):
        return False
    return _card_in_user_scope(user, card, db)


@router.post("", response_model=StaffCardResponse, status_code=201)
async def upload_card(
    file: UploadFile = File(...),
    entity_type: str = Query(..., description="实体类型: doctor/nurse/technician/admin"),
    entity_id: str = Query(..., description="实体工号"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    # [改进] 前端裁剪照片后会把未裁剪的原文件随 original 字段一并上传，用于后端双存溯源
    original: UploadFile | None = File(None, description="原始照片（前端裁剪后附带，用于双存溯源）"),
):
    """
    上传卡片照片
    
    拥有卡片上传权限的用户可以上传卡片
    """
    VALID_WORK_TYPES = ("doctor", "nurse", "technician", "admin")
    WORK_TYPE_LABELS = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政"}
    
    # [改进] 卡片编辑权限收紧：仅持有 card.upload 权限者可上传（含本人）。
    # 实现「确认」与「编辑」权限分离——普通员工可确认自己的卡片，
    # 但上传/编辑卡片必须由管理员授予 card.upload 权限后才能自行操作。
    if not _can_upload_card(current_user):
        raise HTTPException(status_code=403, detail="无权上传卡片")

    # 验证实体类型
    if entity_type not in VALID_WORK_TYPES:
        raise HTTPException(status_code=400, detail=f"实体类型必须是 {', '.join(VALID_WORK_TYPES)} 之一")

    # 验证实体是否存在（使用统一的人员服务）
    staff = get_staff(db, entity_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")

    # 数据范围校验：非本人持卡上传须在其数据范围内（防越权覆盖他人卡片）
    if entity_id != current_user.employee_id:
        from app.dependencies import can_access_staff
        if not can_access_staff(current_user, staff.work_type, staff.department, db):
            raise HTTPException(status_code=403, detail="无权上传该人员的卡片")
    
    # 删除该实体下所有旧卡片（文件和数据库记录）
    from app.models.staff_card import StaffCard
    old_cards = db.query(StaffCard).filter(
        StaffCard.entity_type == entity_type,
        StaffCard.entity_id == entity_id,
    ).all()
    for old_card in old_cards:
        if old_card.card_photo:
            delete_file(old_card.card_photo)
        db.delete(old_card)
    
    # 保存文件
    try:
        file_path = await save_upload_file(file, "card", entity_id, "card", original=original)
    except HTTPException as e:
        raise e
    except Exception as e:
        # [修复/问题6] 内部异常详情不再返回客户端，仅写日志，对外统一文案
        logger.error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")
    
    # 创建卡片记录
    card = create_card(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        card_photo=file_path,
        uploaded_by=current_user.employee_id,
    )
    
    # 发送通知给相关人员
    entity_name = staff.name if staff else ""
    dept_name = staff.department or ""

    type_label = WORK_TYPE_LABELS.get(entity_type, entity_type)
    title = f"{entity_name}的卡片需要确认"
    content = f"{entity_name}（{entity_id}）上传了{type_label}卡片，请及时确认。"

    # 收件人 = 本人 + 有卡片上传权限的用户（基于权限系统，而非角色名硬编码），
    # 该范围即「工卡上传待确认」事件的业务内置默认收件人，管理员可在
    # 「通知设置 → 工卡上传待确认」中改为自定义范围
    recipients = [entity_id]
    all_active_users = db.query(User).filter(User.is_active == True).all()
    for u in all_active_users:
        if u.employee_id == entity_id:
            continue
        if not has_permission(u, PERM_CARD_UPLOAD):
            continue
        # 根据数据范围过滤
        from app.dependencies import get_user_department_scope
        from app.models.department import Department
        managed_dept_ids = get_user_department_scope(u, db)
        if managed_dept_ids and dept_name:
            target_dept = db.query(Department).filter(Department.name == dept_name).first()
            if not target_dept or target_dept.id not in managed_dept_ids:
                continue
        elif dept_name and not managed_dept_ids:
            continue
        recipients.append(u.employee_id)

    # [调整 2026-09-15] 统一交由通知中心发送（事件：card.uploaded，可开关 / 可改文案与收件人）
    notification_center.emit(
        db, "card.uploaded",
        context={"姓名": entity_name, "工号": entity_id, "人员类型": type_label},
        recipients=recipients,
        department=dept_name or None,
        related_type="card", related_id=card.id,
        fallback_title=title, fallback_content=content,
    )
    
    db.commit()
    db.refresh(card)
    
    # [新增 2026-09-09] 卡片上传审计留痕（含 PHI 照片，敏感操作）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "card_upload", current_user.employee_id,
                     detail=f"entity={entity_type}/{entity_id}, card_id={card.id}", target=str(card.id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    return card


@router.get("", response_model=StaffCardListResponse)
def list_cards(
    entity_type: str | None = Query(None, description="实体类型: doctor/nurse/technician/admin"),
    entity_id: str | None = Query(None, description="实体工号"),
    status: str | None = Query(None, description="卡片状态: pending/confirmed/rejected"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取卡片列表
    
    根据用户数据范围过滤可见的卡片
    """
    from app.models.staff_card import StaffCard
    query = db.query(StaffCard)

    # 根据科室数据范围过滤可见的卡片
    from app.dependencies import get_user_department_scope, _get_role_dept_scope
    from app.models.department import Department
    from app.models.staff import Staff
    
    dept_scope = _get_role_dept_scope(current_user)
    if dept_scope == "own":
        # 仅本科室：只显示自己所在科室人员的卡片
        if current_user.department:
            staff_ids_subq = db.query(Staff.employee_id).filter(
                Staff.department == current_user.department
            ).subquery()
            query = query.filter(StaffCard.entity_id.in_(staff_ids_subq))
        else:
            # 没有科室归属，只能看自己的卡片
            # [修复 2026-09-17] 原实现允许外部传入 entity_id 覆盖「本人」限制，
            # 无科室账号可用 ?entity_id=<他人工号> 越权查询他人卡片，现强制锁定为本人
            entity_id = current_user.employee_id
    elif dept_scope == "managed":
        # 管辖科室：显示管辖科室人员的卡片
        managed_dept_ids = get_user_department_scope(current_user, db)
        if not managed_dept_ids:
            return StaffCardListResponse(total=0, items=[], page=page, page_size=page_size)
        dept_names = [d.name for d in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
        if not dept_names:
            return StaffCardListResponse(total=0, items=[], page=page, page_size=page_size)
        staff_ids_subq = db.query(Staff.employee_id).filter(Staff.department.in_(dept_names)).subquery()
        query = query.filter(StaffCard.entity_id.in_(staff_ids_subq))
    # "all" scope：不做过滤，显示所有卡片

    # [修复 2026-09-11] 离职人员的工牌卡片不再出现在列表中
    # （用「排除已知离职者」而非「限定在职集合」，避免误伤没有 staff 档案的历史卡片）
    resigned_ids = db.query(Staff.employee_id).filter(Staff.status == "resigned").subquery()
    query = query.filter(~StaffCard.entity_id.in_(resigned_ids))

    if entity_type:
        query = query.filter(StaffCard.entity_type == entity_type)
    if entity_id:
        query = query.filter(StaffCard.entity_id == entity_id)
    if status:
        query = query.filter(StaffCard.status == status)
    total = query.count()
    items = query.order_by(StaffCard.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    # 补充确认人姓名
    confirmed_ids = set(c.confirmed_by for c in items if c.confirmed_by)
    if confirmed_ids:
        users = db.query(User.employee_id, User.name).filter(User.employee_id.in_(confirmed_ids)).all()
        name_map = {u.employee_id: u.name for u in users}
    else:
        name_map = {}
    
    result_items = []
    for c in items:
        item_dict = {
            "id": c.id,
            "entity_type": c.entity_type,
            "entity_id": c.entity_id,
            "card_photo": c.card_photo,
            "status": c.status,
            "uploaded_by": c.uploaded_by,
            "uploaded_at": c.uploaded_at,
            "confirmed_by": c.confirmed_by,
            "confirmed_by_name": name_map.get(c.confirmed_by) if c.confirmed_by else None,
            "confirmed_at": c.confirmed_at,
            "reject_reason": c.reject_reason,
            # [改进] 返回当前用户对该卡片的确认权限，前端据此渲染确认/拒绝按钮
            "can_confirm": _can_confirm_card(current_user, c, db),
        }
        result_items.append(item_dict)
    
    return StaffCardListResponse(total=total, items=result_items, page=page, page_size=page_size)


@router.get("/{card_id}", response_model=StaffCardResponse)
def get_card_detail(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取卡片详情"""
    card = get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    # [修复 2026-09-17] 原实现不校验任何权限与数据范围：任意登录用户可通过
    # 自增 card_id 枚举读取全员工卡详情（工号 / 照片路径 / 上传人与确认人），
    # 列表做了科室过滤而详情完全没做。现要求本人或具备人员查看类权限且在数据范围内。
    if not _can_view_card(current_user, card, db):
        raise HTTPException(status_code=403, detail="无权查看该卡片")
    # [改进] 返回当前用户对该卡片的确认权限，前端据此渲染确认/拒绝按钮
    return {
        "id": card.id,
        "entity_type": card.entity_type,
        "entity_id": card.entity_id,
        "card_photo": card.card_photo,
        "status": card.status,
        "uploaded_by": card.uploaded_by,
        "uploaded_at": card.uploaded_at,
        "confirmed_by": card.confirmed_by,
        "confirmed_by_name": None,
        "confirmed_at": card.confirmed_at,
        "reject_reason": card.reject_reason,
        "can_confirm": _can_confirm_card(current_user, card, db),
    }


@router.put("/{card_id}/confirm", response_model=StaffCardResponse)
def confirm_card_endpoint(
    card_id: int,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    确认卡片
    
    科室管理员、病区管理员或员工本人可以确认
    """
    card = get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    
    if card.status != "pending":
        raise HTTPException(status_code=400, detail="卡片已处理，无法重复确认")
    
    # 验证权限
    if not _can_confirm_card(current_user, card, db):
        raise HTTPException(status_code=403, detail="无权确认该卡片")
    
    # 确认卡片
    updated_card = confirm_card(db, card_id, current_user.employee_id)
    if not updated_card:
        raise HTTPException(status_code=500, detail="确认失败")

    # 通知卡片上传者：卡片已确认（[调整 2026-09-15] 走通知中心 card.confirmed 事件）
    if card.uploaded_by and card.uploaded_by != current_user.employee_id:
        staff = get_staff(db, card.entity_id)
        staff_name = staff.name if staff else card.entity_id
        notification_center.emit(
            db, "card.confirmed",
            context={"操作人": current_user.name, "姓名": staff_name, "工号": card.entity_id},
            recipients=[card.uploaded_by],
            department=(staff.department if staff else None) or None,
            related_type="card", related_id=card.id,
            fallback_title=f"{staff_name}的卡片照已确认",
            fallback_content=f"{current_user.name} 确认了 {staff_name}({card.entity_id}) 的卡片照",
        )

    db.commit()
    db.refresh(updated_card)

    # [新增 2026-09-09] 卡片确认审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "card_confirm", current_user.employee_id,
                     detail=f"card_id={card_id}, entity={card.entity_id}", target=str(card_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    return updated_card


@router.put("/{card_id}/reject", response_model=StaffCardResponse)
def reject_card_endpoint(
    card_id: int,
    update_data: StaffCardUpdate,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    拒绝卡片
    
    科室管理员、病区管理员或员工本人可以拒绝
    """
    card = get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    
    if card.status != "pending":
        raise HTTPException(status_code=400, detail="卡片已处理，无法重复操作")
    
    # 验证权限
    if not _can_confirm_card(current_user, card, db):
        raise HTTPException(status_code=403, detail="无权拒绝该卡片")
    
    # 拒绝卡片
    updated_card = reject_card(
        db,
        card_id,
        current_user.employee_id,
        update_data.reject_reason,
    )
    if not updated_card:
        raise HTTPException(status_code=500, detail="拒绝失败")

    # 通知卡片上传者：卡片被拒绝（[调整 2026-09-15] 走通知中心 card.rejected 事件）
    if card.uploaded_by and card.uploaded_by != current_user.employee_id:
        staff = get_staff(db, card.entity_id)
        staff_name = staff.name if staff else card.entity_id
        reason_text = f"，原因：{update_data.reject_reason}" if update_data.reject_reason else ""
        notification_center.emit(
            db, "card.rejected",
            context={
                "操作人": current_user.name,
                "姓名": staff_name,
                "工号": card.entity_id,
                "拒绝原因": reason_text,
            },
            recipients=[card.uploaded_by],
            department=(staff.department if staff else None) or None,
            related_type="card", related_id=card.id,
            fallback_title=f"{staff_name}的卡片照被拒绝",
            fallback_content=f"{current_user.name} 拒绝了 {staff_name}({card.entity_id}) 的卡片照{reason_text}",
        )

    db.commit()
    db.refresh(updated_card)

    # [新增 2026-09-09] 卡片拒绝审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "card_reject", current_user.employee_id,
                     detail=f"card_id={card_id}, entity={card.entity_id}, reason={update_data.reject_reason or '-'}", target=str(card_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    return updated_card


@router.delete("/{card_id}")
def delete_card_endpoint(
    card_id: int,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除卡片"""
    card = get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    
    # [改进] 删除卡片仅允许持有 card.upload 权限者（移除上传者本人例外），
    # 与上传权限收紧保持一致：普通员工只能确认卡片，不能编辑/删除
    if not has_permission(current_user, PERM_CARD_UPLOAD):
        raise HTTPException(status_code=403, detail="无权删除该卡片")
    # [修复 2026-09-17] 补科室数据范围校验：原实现任意 card.upload 持有者可删除
    # 其他科室人员的卡片，与上传/确认接口的 can_access_staff 范围校验口径不一致
    if card.entity_id != current_user.employee_id and not _card_in_user_scope(current_user, card, db):
        raise HTTPException(status_code=403, detail="无权删除其他科室人员的卡片")
    
    # 删除文件
    delete_file(card.card_photo)
    
    # 删除记录
    success = delete_card(db, card_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    
    db.commit()

    # [新增 2026-09-09] 卡片删除审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "card_delete", current_user.employee_id,
                     detail=f"card_id={card_id}, entity={card.entity_id}", target=str(card_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    return {"message": "卡片删除成功"}
