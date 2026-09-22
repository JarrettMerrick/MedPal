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
    # [修复 2026-09-17] 巡检照片上传补科室范围校验
    check_signage_department_access,
)
from app.models.user import User
from app.models.department import Department
from app.services import signage_service
# [新增 2026-09-09] 巡检操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：巡检提交后通知管理方（此前只留痕不提醒）
from app.services.modification_notify import notify_super_admins
# [统一时间口径] API 时间字段用 to_iso_utc；日期范围边界用 beijing_date_start_utc
from app.utils import utc_now, get_client_ip, to_iso_utc, beijing_date_start_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage-inspections", tags=["标识巡检"])


# [新增 2026-09-15] 巡检结果中文映射（与标识状态取值口径一致）
INSPECTION_RESULT_LABELS = {
    "normal": "正常", "damaged": "轻微破损",
    "severely_damaged": "严重损坏", "removed": "已拆除",
}


def _notify_inspection(db: Session, current_user: User, s, rec) -> None:
    """[新增 2026-09-15] 巡检提交站内信（事件：signage.inspection_submitted，失败静默）"""
    try:
        inspector_name = getattr(current_user, "name", None) or current_user.employee_id
        result_label = INSPECTION_RESULT_LABELS.get(rec.result, rec.result)
        summary = f"巡检结果: {result_label}"
        if rec.notes:
            summary += f"（备注: {str(rec.notes)[:50]}）"
        if rec.photo:
            summary += "（含现场照片）"
        dept_name = getattr(getattr(s, "department", None), "name", None)
        notify_super_admins(
            db,
            title=f"标识巡检提交：{s.code}",
            content=f"{inspector_name} 提交了标识 {s.code}「{s.name}」的巡检记录：{summary}",
            related_type="signage",
            related_id=s.id,
            department=dept_name,
            exclude_user_id=current_user.employee_id,
            event_code="signage.inspection_submitted",
            context={"操作人": inspector_name, "标识": s.code, "变更内容": summary},
        )
        db.commit()
    except Exception:
        db.rollback()

# [新增 2026-09-05] 巡检结果直接复用标识现有 status 字段的取值，保证口径一致
ALLOWED_RESULTS = {"normal", "damaged", "severely_damaged", "removed"}

# [新增 2026-09-07] 巡检照片上传：复用图片校验与落盘逻辑
import os
import uuid
from fastapi import File, UploadFile
from app.utils import utc_now
from app.services.upload_service import (
    # [重构 2026-09-21 / Q-7] 照片的校验与保存统一走公共实现
    # （校验类型/大小/魔数 + 落盘 + 路径穿越断言 + 生成缩略图）
    save_validated_photo,
    validate_image_file, detect_image_format, MAX_FILE_SIZE, UPLOAD_ROOT,
    generate_thumbnail,
)


def _save_inspection_photo(signage_code: str, file: UploadFile) -> str:
    """校验并保存巡检照片，返回可访问的相对路径（如 inspection/xxx.jpg）。

    [重构 2026-09-21 / 代码质量审计 Q-7] 原实现把「校验 + 落盘 + 路径穿越断言 +
    生成缩略图」整段写在函数内，与 signage_alerts 的维修照片保存逐行重复（约 30 行）。
    该重复此前已造成过实际缺陷：缩略图只在其中一处补上，另一处漏了。
    现改为调用公共实现 upload_service.save_validated_photo —— 保留本函数名是为了
    不触动既有调用点，同时保证"缩略图"这类步骤今后不可能被单边遗漏。

    文件名前缀沿用标识编码（如 RC-QYBS-01-01-001_20260917_...jpg），便于人工排查时
    从文件名直接看出照片属于哪个标识。
    """
    return save_validated_photo(file, subdir="inspection", name_prefix=signage_code)


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
            except Exception:
                # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
                # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
                logger.warning(
                    "旁路操作失败（已忽略，不影响主流程）", exc_info=True
                )
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.inspection_submitted）
    _notify_inspection(db, current_user, s, rec)
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
    """上传巡检现场照片（客户端已压缩），返回相对路径。

    [修复 2026-09-17] 补科室数据范围校验（与提交巡检的科室判定一致）：
    原先任意持有 signage.inspection 的账号可为其他科室标识上传照片并落盘，
    而提交巡检端点对非本科室标识已有拦截，两者口径不一致。
    """
    s = signage_service.get_signage_by_code(db, signage_code)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在，请检查编号是否正确")
    check_signage_department_access(db, current_user, s)
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
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
    # [统一时间口径] 按北京业务日期换算 UTC 边界（原型直接用 UTC 零点，北京 00:00-08:00 的巡检会漏筛）
    try:
        start = beijing_date_start_utc(start_date) if start_date else None
        end = beijing_date_start_utc(end_date, end_of_day=True) if end_date else None
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")
    # [修复 2026-09-17] 按角色科室作用域过滤巡检历史（原先受限角色可检索全院巡检记录及照片路径）
    allowed = None
    if _get_role_dept_scope(current_user) != "all":
        allowed = get_user_department_scope(current_user, db)
    items, total = signage_service.get_inspections(db, page, page_size, code, inspector, start, end,
                                                   allowed_department_ids=allowed)
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
            # [统一时间口径] 带 Z 的 UTC ISO（原样返回 datetime 会被序列化为无时区串，前端易按本地时区误解析）
            "created_at": to_iso_utc(r.created_at),
        })
    return {"total": total, "items": out, "page": page, "page_size": page_size}
