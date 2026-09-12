# [重构 2026-09-05] 标识预警路由：
# - 删除「质保即将到期」「已过质保期」
# - 新增「状态异常标识」
# - 巡检预警按分类巡检周期计算，分为「7天内到期」「已超期」
# - 新增「临时标识有效期」预警（基于 validity_until）
# [新增 2026-09-08] 预警处理：维修流程（发起维修/维修处理中/完成维修）与巡检临期跳转
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid
import logging

logger = logging.getLogger(__name__)

from app.database import get_db
from app.config import settings
# [修复 2026-09-07] 预警接口改用 signage.alert（标识平面 - 查看标识预警）
# [新增 2026-09-09] 维修记录查询接口供详情页使用，与巡检历史一致采用标识查看权限 PERM_SIGNAGE_VIEW
from app.dependencies import get_current_user, has_permission, PERM_SIGNAGE_ALERT, PERM_SIGNAGE_VIEW
from app.models.user import User
from app.services.signage_alert_service import (
    get_abnormal_status, get_inspections_due_soon, get_inspections_overdue,
    get_expiring_validity, get_all_alerts,
    # [新增 2026-09-08] 维修流程服务；[新增 2026-09-09] 按标识查询维修记录
    get_repairs_in_progress, start_repair, complete_repair, get_repairs_by_signage,
)
# [新增 2026-09-08] 维修完成照片上传：复用图片校验与落盘逻辑（与巡检照片一致）
# [新增 2026-09-09] 维修流程审计留痕 + 统一 IP 获取
from app.utils import utc_now, get_client_ip
from app.services.audit_service import record_audit
from app.services.upload_service import (
    validate_image_file, detect_image_format, MAX_FILE_SIZE, UPLOAD_ROOT,
)

router = APIRouter(prefix="/api/signage-alerts", tags=["标识预警"])


def _save_repair_photo(file: UploadFile) -> str:
    """[新增 2026-09-08] 校验并保存维修完成照片，返回相对路径（如 repair/xxx.jpg）"""
    validate_image_file(file)
    content = file.file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制，最大允许 {settings.upload_max_size_mb}MB",
        )
    real_format = detect_image_format(content)
    if real_format not in ("JPEG", "PNG", "WebP"):
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式")
    ext = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}[real_format]
    dir_path = os.path.join(UPLOAD_ROOT, "repair")
    os.makedirs(dir_path, exist_ok=True)
    filename = f"repair_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    with open(os.path.join(dir_path, filename), "wb") as f:
        f.write(content)
    # 路径穿越防护：assert 解析后仍位于上传根目录内
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_abs = os.path.realpath(os.path.join(dir_path, filename))
    if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="非法文件路径")
    return f"repair/{filename}"


class RepairStartRequest(BaseModel):
    """[新增 2026-09-08] 发起维修请求"""
    signage_id: int
    # vendor=供应商维修 / engineering=工程部维修
    repair_party: str
    # 供应商维修时的 OA 单号（可选）
    oa_number: Optional[str] = None
    # 供应商维修时必选的供应商 ID
    supplier_id: Optional[int] = None


class RepairCompleteRequest(BaseModel):
    """[新增 2026-09-08] 完成维修请求（维修完成照片可选）"""
    photo: Optional[str] = None


@router.get("/summary")
def alert_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    return get_all_alerts(db)


@router.get("/abnormal-status")
def abnormal_status_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """[新增 2026-09-05] 状态异常标识（轻微破损/严重损坏）"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    items = get_abnormal_status(db)
    return [{"id": s.id, "code": s.code, "name": s.name, "status": s.status} for s in items]


@router.get("/inspection/due-soon")
def inspection_due_soon(days_ahead: int = Query(7, ge=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """[新增 2026-09-05] 7天内巡检到期（按分类巡检周期计算）"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    items = get_inspections_due_soon(db, days_ahead)
    return [{
        "id": d["signage"].id, "code": d["signage"].code, "name": d["signage"].name,
        "category": d["category"], "cycle_days": d["cycle_days"],
        "last_inspection_date": str(d["last_inspection_date"]) if d["last_inspection_date"] else None,
        "due_date": str(d["due_date"]), "days_left": d["days_left"],
    } for d in items]


@router.get("/inspection/overdue")
def inspection_overdue(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """[新增 2026-09-05] 巡检已超期（按分类巡检周期计算）"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    items = get_inspections_overdue(db)
    return [{
        "id": d["signage"].id, "code": d["signage"].code, "name": d["signage"].name,
        "category": d["category"], "cycle_days": d["cycle_days"],
        "last_inspection_date": str(d["last_inspection_date"]) if d["last_inspection_date"] else None,
        "due_date": str(d["due_date"]), "days_overdue": -d["days_left"],
    } for d in items]


@router.get("/validity/expiring")
def validity_expiring(days_ahead: int = Query(7, ge=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """[新增 2026-09-05] 临时标识有效期预警（含已过期）"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    items = get_expiring_validity(db, days_ahead)
    return [{"id": s.id, "code": s.code, "name": s.name, "validity_until": str(s.validity_until)} for s in items]


# ============================================================
# [新增 2026-09-08] 预警处理：维修流程
#   状态异常 --发起维修--> 维修处理中 --完成维修(可选上传照片)--> 正常
# ============================================================
@router.get("/repairs/in-progress")
def repairs_in_progress(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """维修处理中的预警列表（未完成的维修记录）"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    rows = get_repairs_in_progress(db)
    return [{
        "id": r.id, "signage_id": s.id, "code": s.code, "name": s.name,
        "repair_party": r.repair_party, "supplier_name": r.supplier_name,
        "oa_number": r.oa_number,
        "started_at": str(r.started_at) if r.started_at else None,
    } for r, s in rows]


@router.get("/repairs")
def list_signage_repairs(
    signage_id: int = Query(..., description="标识ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-09] 查询指定标识的全部维修记录（含维修前/后照片路径）。

    供标识详情页「维修记录」弹窗调用。权限与「巡检历史」一致采用标识查看权限，
    保证能查看标识详情的用户均可查看该标识的维修记录。
    """
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    return get_repairs_by_signage(db, signage_id)


@router.post("/repairs/start")
def start_signage_repair(body: RepairStartRequest, request: Request = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """发起维修：状态异常（轻微破损/严重损坏）→ 维修处理中。

    - 供应商维修（vendor）：必须选择供应商，OA 单号可选；
    - 工程部维修（engineering）：可直接确认。
    """
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    rec, err = start_repair(db, body.signage_id, body.repair_party, current_user.employee_id, body.oa_number, body.supplier_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db.commit()
    # [新增 2026-09-09] 维修发起审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_start", current_user.employee_id,
                     detail=f"signage_id={rec.signage_id}, party={rec.repair_party}, supplier={rec.supplier_name or '-'}, oa={rec.oa_number or 'N/A'}",
                     target=str(rec.signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {
        "id": rec.id, "signage_id": rec.signage_id, "repair_party": rec.repair_party,
        "supplier_name": rec.supplier_name, "oa_number": rec.oa_number,
        "status": "repair_in_progress",
    }


@router.post("/repairs/photo")
async def upload_repair_photo(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-08] 上传维修完成照片（客户端已压缩），返回相对路径；完成维修前调用"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        file_path = _save_repair_photo(file)
    except Exception as e:
        logger.error(f"上传维修完成照片失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"照片保存失败: {str(e)}")
    db.commit()
    # [新增 2026-09-09] 维修照片上传审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_photo", current_user.employee_id,
                     detail=f"file={file.filename}", target=file_path, ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {"file_path": file_path}


@router.post("/repairs/{repair_id}/complete")
def complete_signage_repair(repair_id: int, body: RepairCompleteRequest, request: Request = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """完成维修：维修处理中 → 正常。

    若上传维修完成照片，则同步替换标识详情页的安装现场照片（installation_photo）。
    """
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    rec, err = complete_repair(db, repair_id, current_user.employee_id, body.photo)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db.commit()
    # [新增 2026-09-09] 维修完成审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_complete", current_user.employee_id,
                     detail=f"repair_id={repair_id}, signage_id={rec.signage_id}, photo={'有' if rec.repair_photo else '无'}",
                     target=str(rec.signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {
        "id": rec.id, "signage_id": rec.signage_id,
        "repair_photo": rec.repair_photo, "status": "normal",
    }
