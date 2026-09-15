from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_any_permission, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT
from app.models.user import User
from app.services.signage_batch_service import batch_generate_door_signs, batch_update_department
# [新增 2026-09-09] 批量操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：批量生成 / 批量改科室后通知管理方（此前只留痕不提醒）
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip

router = APIRouter(prefix="/api/signage-batch", tags=["标识批量操作"])


def _notify_batch_change(
    db: Session, current_user: User, obj_label: str, summary: str, department: str | None = None,
) -> None:
    """[新增 2026-09-15] 标识批量操作站内信（统一出口，失败静默）"""
    try:
        modifier_name = getattr(current_user, "name", None) or current_user.employee_id
        notify_super_admins(
            db,
            title=f"标识批量操作：{obj_label}",
            content=f"{modifier_name} {summary}",
            related_type="signage",
            department=department,
            exclude_user_id=current_user.employee_id,
            event_code="signage.changed",
            context={"操作人": modifier_name, "对象": obj_label, "变更内容": summary},
        )
        db.commit()
    except Exception:
        db.rollback()

class BatchGenerateRequest(BaseModel):
    building: str
    floor: str
    room_numbers: List[str]
    oa_number: str

class BatchUpdateDeptRequest(BaseModel):
    old_department: str
    new_department: str
    oa_number: str

@router.post("/generate-door-signs")
def generate_door_signs(req: BatchGenerateRequest, request: Request = None, current_user: User = Depends(require_any_permission(PERM_SIGNAGE_CREATE)), db: Session = Depends(get_db)):
    """[新增 2026-09-03] 批量生成门牌标识"""
    created = batch_generate_door_signs(db, req.building, req.floor, req.room_numbers, req.oa_number, current_user.employee_id)
    # [新增 2026-09-09] 批量生成审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_batch_generate", current_user.employee_id,
                     detail=f"building={req.building}, floor={req.floor}, count={len(created)}, oa={req.oa_number}",
                     target=f"{req.building}/{req.floor}", ip_address=client_ip)
        db.commit()
    except Exception: pass
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_batch_change(
        db, current_user, f"{req.building} {req.floor}",
        f"批量生成了 {len(created)} 个门牌标识（{req.building} {req.floor}）",
    )
    return {"message": f"成功创建{len(created)}个门牌标识", "count": len(created)}

@router.post("/update-department")
def update_department(req: BatchUpdateDeptRequest, request: Request = None, current_user: User = Depends(require_any_permission(PERM_SIGNAGE_EDIT)), db: Session = Depends(get_db)):
    """[新增 2026-09-03] 批量更新关联科室"""
    updated = batch_update_department(db, req.old_department, req.new_department, req.oa_number, current_user.employee_id)
    # [新增 2026-09-09] 批量改科室审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_batch_update_dept", current_user.employee_id,
                     detail=f"{req.old_department} → {req.new_department}, count={len(updated)}, oa={req.oa_number}",
                     target=req.new_department, ip_address=client_ip)
        db.commit()
    except Exception: pass
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_batch_change(
        db, current_user, req.new_department,
        f"批量将 {len(updated)} 个标识的关联科室由「{req.old_department}」调整为「{req.new_department}」",
        department=req.new_department,
    )
    return {"message": f"成功更新{len(updated)}个标识", "count": len(updated)}
