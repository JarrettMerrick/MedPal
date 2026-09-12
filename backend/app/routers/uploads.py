# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.dependencies import (
    get_current_user,
    has_permission,
    PERM_STAFF_EDIT,
    get_user_department_scope,
)
from app.models.user import User
from app.models.department import Department
from app.services.staff_service import get_staff, update_staff
from app.services.upload_service import (
    save_upload_file, delete_file, get_file_path, UPLOAD_ROOT,
    validate_image_file, detect_image_format, MAX_FILE_SIZE,
)
from app.schemas.staff import StaffUpdate
from app.config import settings
from app.utils import utc_now, get_client_ip
from app.services.audit_service import record_audit
from app.services.notification_service import create_notification
from app.services.modification_notify import notify_super_admins
# [新增 2026-09-11] 照片变更纳入「立即生效 + 追认审核」（科室负责人审）
from app.models.staff_change import SOURCE_PHOTO
from app.services.staff_change_service import submit_change

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["文件上传"])


@router.post("/photo/{entity_type}/{entity_id}")
async def upload_photo(
    entity_type: str,
    entity_id: str,
    file: UploadFile = File(...),
    photo_type: str = Query("front", description="照片类型: front/side"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    # [改进] 前端裁剪照片后会把未裁剪的原文件随 original 字段一并上传，用于后端双存溯源
    original: UploadFile | None = File(None, description="原始照片（前端裁剪后附带，用于双存溯源）"),
):
    """
    上传个人形象照
    
    Args:
        entity_type: 实体类型 (保留兼容，实际使用统一 staff 服务)
        entity_id: 实体工号
        file: 上传的图片文件
    """
    # 验证实体类型
    if entity_type not in ("doctor", "nurse", "technician", "admin"):
        raise HTTPException(status_code=400, detail="实体类型必须是 doctor/nurse/technician/admin")

    # 验证权限：只有本人、有staff.edit权限的用户可以上传照片
    if entity_id == current_user.employee_id:
        pass  # 本人可以上传自己的照片
    elif has_permission(current_user, PERM_STAFF_EDIT):
        # 有 staff.edit 权限的用户（含科室管理员、自定义角色），需在数据范围内
        staff = get_staff(db, entity_id)
        if not staff or not staff.department:
            raise HTTPException(status_code=403, detail="无权上传该人员的照片")
        from app.dependencies import can_access_staff
        if not can_access_staff(current_user, staff.work_type, staff.department, db):
            raise HTTPException(status_code=403, detail="无权上传该人员的照片")
    else:
        raise HTTPException(status_code=403, detail="无权上传该人员的照片")
    
    # 检查实体是否存在（使用统一的人员服务）
    staff = get_staff(db, entity_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")
    
    # 验证 photo_type 参数
    if photo_type not in ("front", "side"):
        photo_type = "front"
    # 兼容旧版：如果前端未传 photo_type，根据文件名猜测
    if photo_type == "front" and file.filename:
        filename_lower = file.filename.lower()
        if "side" in filename_lower or "侧面" in filename_lower:
            photo_type = "side"
    
    # 旧照片文件：先记下路径，**暂不删除**——照片变更需科室负责人审核，
    # 驳回时要回滚到旧照片，故延后到「审核通过/免审」后再删（见函数末尾）。
    old_photo = staff.front_photo if photo_type == "front" else staff.side_photo

    # 保存文件
    try:
        file_path = await save_upload_file(file, entity_type, entity_id, photo_type, original=original)
    except HTTPException:
        raise
    except Exception as e:
        # [新增 2026-09-09] 照片保存失败记入运行日志（ERROR），根因可查
        logger.error(f"上传个人形象照失败: entity={entity_type}/{entity_id}, type={photo_type}, {e}", exc_info=True)
        # [修复/问题6] 内部异常详情（磁盘绝对路径、SQLite 错误信息等）不再返回客户端，
        # 仅写入服务端日志，对外统一文案
        import logging
        logging.getLogger(__name__).error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")
    
    # 更新数据库（使用统一的 staff 服务）
    staff_update = StaffUpdate()
    photo_label = "正面照" if photo_type == "front" else "侧面照"
    if photo_type == "front":
        staff_update.front_photo = file_path
    else:
        staff_update.side_photo = file_path
    update_staff(db, entity_id, staff_update, updated_by=current_user.employee_id)
    photo_field = "front_photo" if photo_type == "front" else "side_photo"

    # [新增 2026-09-11] 照片属「科室负责人审核」级别：登记审核任务（立即生效 + 追认）。
    # 驳回时会回滚为旧照片路径，因此旧文件必须保留——通过/免审时再删除。
    staff = get_staff(db, entity_id)
    _change_req, reviewers = submit_change(
        db, staff=staff,
        before={photo_field: old_photo}, payload={photo_field: file_path},
        submitter=current_user, source=SOURCE_PHOTO,
    )
    if old_photo and old_photo != file_path and not reviewers:
        # 免审（超管提交）→ 旧照片已无保留价值，立即清理
        delete_file(old_photo)

    # 发送通知：照片已更新（已派发审核任务时改由审核通知承载，避免重复打扰）
    if staff and current_user.employee_id != entity_id and not reviewers:
        from app.services.user_service import get_user
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"{staff.name}的照片已更新",
            content=f"{modifier_name} 更新了 {staff.name}({entity_id}) 的{photo_label}",
            related_type="photo",
        )

    db.commit()

    # [新增 2026-09-09] 个人形象照上传审计留痕（含 PHI 照片，敏感操作）
    try:
        record_audit(db, "photo_upload", current_user.employee_id,
                     detail=f"entity={entity_type}/{entity_id}, type={photo_type}, file={file.filename}",
                     target=entity_id, ip_address=get_client_ip(request))
        db.commit()
    except Exception: pass

    return {
        "message": "照片上传成功",
        "file_path": file_path,
        "photo_type": photo_type,
    }


@router.delete("/photo/{entity_type}/{entity_id}/{photo_type}")
async def delete_photo(
    entity_type: str,
    entity_id: str,
    photo_type: str,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除个人形象照
    
    Args:
        entity_type: 实体类型 (保留兼容)
        entity_id: 实体工号
        photo_type: 照片类型 (front/side)
    """
    # 验证参数
    if entity_type not in ("doctor", "nurse", "technician", "admin"):
        raise HTTPException(status_code=400, detail="实体类型必须是 doctor/nurse/technician/admin")
    if photo_type not in ("front", "side"):
        raise HTTPException(status_code=400, detail="照片类型必须是 front 或 side")
    
    # 验证权限（与上传照片规则一致）
    if entity_id == current_user.employee_id:
        pass  # 本人可以删除自己的照片
    elif has_permission(current_user, PERM_STAFF_EDIT):
        staff = get_staff(db, entity_id)
        if not staff or not staff.department:
            raise HTTPException(status_code=403, detail="无权删除该人员的照片")
        from app.dependencies import can_access_staff
        if not can_access_staff(current_user, staff.work_type, staff.department, db):
            raise HTTPException(status_code=403, detail="无权删除该人员的照片")
    else:
        raise HTTPException(status_code=403, detail="无权删除该人员的照片")
    
    # 获取实体信息
    entity = get_staff(db, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="人员不存在")
    photo_path = entity.front_photo if photo_type == "front" else entity.side_photo
    
    if not photo_path:
        raise HTTPException(status_code=404, detail="照片不存在")
    
    # 删除文件
    delete_file(photo_path)
    
    # 更新数据库（使用统一的 staff 服务）
    staff_update = StaffUpdate()
    photo_label = "正面照" if photo_type == "front" else "侧面照"
    if photo_type == "front":
        staff_update.front_photo = None
    else:
        staff_update.side_photo = None
    update_staff(db, entity_id, staff_update, updated_by=current_user.employee_id)

    # 发送通知：照片已删除
    if current_user.employee_id != entity_id:
        from app.services.user_service import get_user
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"{entity.name}的照片被删除",
            content=f"{modifier_name} 删除了 {entity.name}({entity_id}) 的{photo_label}",
            related_type="photo",
        )

    db.commit()

    # [新增 2026-09-09] 个人形象照删除审计留痕（含 PHI 照片，敏感操作）
    try:
        record_audit(db, "photo_delete", current_user.employee_id,
                     detail=f"entity={entity_type}/{entity_id}, type={photo_type}", target=entity_id,
                     ip_address=get_client_ip(request))
        db.commit()
    except Exception: pass

    return {"message": "照片删除成功"}


@router.post("/richtext", tags=["文件上传"])
async def upload_richtext_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """富文本编辑器图片上传：保存后返回可引用的 /uploads/richtext/ 相对 URL。

    [修复] 原先前端富文本编辑器将图片转 base64 内嵌进 HTML 内容，导致内容体积
    暴涨并存储于数据库；现改为上传服务器落盘、内容中引用 URL。
    图片存放于 data/uploads/richtext/，孤儿图片清理会排除该目录（正文 HTML 内
    引用的图片无法纳入引用集合，避免误删）。
    """
    import uuid as _uuid

    # 魔数校验 + 大小校验（与 save_upload_file 一致的安全基线）
    validate_image_file(file)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制，最大允许 {settings.upload_max_size_mb}MB",
        )
    real_format = detect_image_format(content)
    if real_format not in ("JPEG", "PNG", "WebP"):
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式")

    # 落盘到 uploads/richtext/{时间戳}_{随机}.{真实扩展名}
    fmt_ext = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}[real_format]
    rich_dir = os.path.join(UPLOAD_ROOT, "richtext")
    os.makedirs(rich_dir, exist_ok=True)
    filename = f"{utc_now().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:8]}{fmt_ext}"
    with open(os.path.join(rich_dir, filename), "wb") as f:
        f.write(content)

    return {"url": f"/uploads/richtext/{filename}"}


class FileCheckRequest(BaseModel):
    """文件存在性检查请求"""
    paths: list[str]


@router.post("/check", tags=["文件上传"])
async def check_files_exist(
    request: FileCheckRequest,
    current_user: User = Depends(get_current_user),
):
    """批量检查文件是否存在（用于前端判断图片是否丢失）"""
    import os
    result: dict[str, bool] = {}
    for path in request.paths:
        if not isinstance(path, str) or not path:
            result[path] = False
            continue
        abs_path = get_file_path(path)
        # [修复] 路径穿越防护：断言解析后的真实路径仍在上传根目录之内，
        # 防止通过 ../../ 探测服务器任意文件是否存在（布尔型信息泄露）。
        # 仅返回上传目录内的文件存在性，越界路径一律视为不存在。
        real_root = os.path.realpath(UPLOAD_ROOT)
        real_abs = os.path.realpath(abs_path)
        if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
            result[path] = False
            continue
        result[path] = os.path.isfile(real_abs)
    return {"exists": result}
