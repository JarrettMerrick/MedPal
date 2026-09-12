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
from app.utils import get_client_ip

router = APIRouter(prefix="/api/signage-batch", tags=["标识批量操作"])

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
    return {"message": f"成功更新{len(updated)}个标识", "count": len(updated)}
