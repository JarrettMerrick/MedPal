# [新增 2026-09-05] 标识巡检路由：移动端巡检打卡与巡检历史查询
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.dependencies import (
    get_current_user, has_permission, require_any_permission,
    # [修复 2026-09-07] 巡检提交/照片上传改用 signage.inspection（标识平面 - 标识巡检）
    PERM_SIGNAGE_VIEW, PERM_SIGNAGE_INSPECTION,
    # [新增 2026-09-08] 巡检越权科室校验：基于角色科室作用域
    get_user_department_scope, _get_role_dept_scope,
)
from app.models.user import User
from app.models.department import Department
from app.services import signage_service
# [新增 2026-09-09] 巡检操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
from app.utils import utc_now, get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage-inspections", tags=["标识巡检"])

# [新增 2026-09-05] 巡检结果直接复用标识现有 status 字段的取值，保证口径一致
ALLOWED_RESULTS = {"normal", "damaged", "severely_damaged", "removed"}

# [新增 2026-09-07] 巡检照片上传：复用图片校验与落盘逻辑
import os
import uuid
from fastapi import File, UploadFile
from app.utils import utc_now
from app.services.upload_service import (
    validate_image_file, detect_image_format, MAX_FILE_SIZE, UPLOAD_ROOT,
)


def _save_inspection_photo(signage_code: str, file: UploadFile) -> str:
    """校验并保存巡检照片，返回可访问的相对路径（如 /uploads/inspection/xxx.jpg）"""
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
    dir_path = os.path.join(UPLOAD_ROOT, "inspection")
    os.makedirs(dir_path, exist_ok=True)
    filename = f"{signage_code}_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    with open(os.path.join(dir_path, filename), "wb") as f:
        f.write(content)
    # 路径穿越防护：assert 解析后仍位于上传根目录内
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_abs = os.path.realpath(os.path.join(dir_path, filename))
    if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="非法文件路径")
    # [修复 2026-09-07] 返回相对路径不带 uploads/ 前缀，与 getOriginalUrl 的 /uploads/{path} 约定一致
    return f"inspection/{filename}"


class InspectionCreate(BaseModel):
    code: str
    result: str
    notes: Optional[str] = None
    # [新增 2026-09-07] 现场照片路径（客户端压缩后上传，可选）
    photo: Optional[str] = None

    @field_validator("result")
    @classmethod
    def validate_result(cls, v):
        if v not in ALLOWED_RESULTS:
            raise ValueError("无效的标识状态")
        return v


@router.post("", status_code=201)
def create_inspection(
    data: InspectionCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_INSPECTION)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-05] 提交巡检：按编码定位标识，记录巡检结果并同步更新标识状态"""
    s = signage_service.get_signage_by_code(db, data.code.strip())
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在，请检查编号是否正确")
    # [新增 2026-09-08] 巡检越权科室校验：受限角色仅可巡检其所属科室的标识；
    # 若扫描到非授权科室的标识，返回友好提示（不记录巡检），由前端弹窗告知用户。
    scope = _get_role_dept_scope(current_user)
    if scope != "all" and s.department_id:
        allowed = get_user_department_scope(current_user, db)
        if s.department_id not in allowed:
            dept = db.query(Department).filter(Department.id == s.department_id).first()
            dept_name = dept.name if dept else "未知科室"
            # [新增 2026-09-09] 越权巡检尝试记入系统日志（WARN）
            try:
                client_ip = get_client_ip(request)
                record_audit(db, "signage_inspection_denied", current_user.employee_id,
                             detail=f"code={s.code}, dept={dept_name}", target=str(s.id), ip_address=client_ip)
                db.commit()
            except Exception: pass
            return {
                "ok": False,
                "warning": True,
                "message": f"此标识归属于{dept_name}管理，非您本次所需巡检标识，若确为您所在区域标识，请联系管理员修正。",
            }
    rec = signage_service.create_inspection(db, s.id, data.result, current_user.employee_id, data.notes, data.photo)
    db.commit()
    # [新增 2026-09-09] 巡检提交审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_inspection_submit", current_user.employee_id,
                     detail=f"code={s.code}, result={rec.result}, photo={'有' if rec.photo else '无'}",
                     target=str(s.id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {
        "ok": True,
        "id": rec.id,
        "signage_id": s.id,
        "signage_code": s.code,
        "signage_name": s.name,
        "result": rec.result,
        "inspection_date": str(rec.inspection_date) if rec.inspection_date else None,
        "inspector": rec.inspector,
        "notes": rec.notes,
        "photo": rec.photo,
        "created_at": rec.created_at,
    }


# [新增 2026-09-07] 巡检照片上传接口：先上传压缩后的现场照片获取路径，再随巡检结果一并提交
@router.post("/photo/{signage_code}")
async def upload_inspection_photo(
    signage_code: str,
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_INSPECTION)),
    db: Session = Depends(get_db),
):
    """上传巡检现场照片（客户端已压缩），返回相对路径"""
    if not signage_service.get_signage_by_code(db, signage_code):
        raise HTTPException(status_code=404, detail="标识不存在，请检查编号是否正确")
    try:
        file_path = _save_inspection_photo(signage_code, file)
    except Exception as e:
        logger.error(f"上传巡检照片失败: code={signage_code}, {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"照片保存失败: {str(e)}")
    # [新增 2026-09-09] 巡检照片上传审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_inspection_photo", current_user.employee_id,
                     detail=f"code={signage_code}, file={file.filename}", target=signage_code, ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {"file_path": file_path}


@router.get("")
def list_inspections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    code: Optional[str] = Query(None, description="标识编号（模糊匹配）"),
    inspector: Optional[str] = Query(None, description="巡检人员（模糊匹配）"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-05] 巡检历史查询：支持时间范围、标识编号、巡检人员筛选"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None
    items, total = signage_service.get_inspections(db, page, page_size, code, inspector, start, end)
    out = []
    for r in items:
        s = r.signage
        out.append({
            "id": r.id,
            "signage_id": r.signage_id,
            "signage_code": s.code if s else None,
            "signage_name": s.name if s else None,
            "signage_status": s.status if s else None,
            "result": r.result,
            "inspection_date": str(r.inspection_date) if r.inspection_date else None,
            "inspector": r.inspector,
            "notes": r.notes,
            "photo": r.photo,
            "created_at": r.created_at,
        })
    return {"total": total, "items": out, "page": page, "page_size": page_size}
