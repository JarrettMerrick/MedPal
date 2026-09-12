# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    require_permission,
    PERM_ROLE_VIEW, PERM_ROLE_CREATE, PERM_ROLE_EDIT, PERM_ROLE_DELETE,
)
from app.models.user import User
from app.schemas.role import (
    PermissionCategoryOut,
    RoleCreate,
    RoleListResponse,
    RoleOut,
    RoleUpdate,
)
from app.services.role_service import (
    create_role,
    delete_role,
    get_all_permissions,
    get_permissions_by_category,
    get_role,
    get_roles,
    update_role,
)
# [新增 2026-09-09] 角色/权限变更审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
from app.utils import get_client_ip

router = APIRouter(prefix="/api/roles", tags=["角色管理"])


@router.get("", response_model=RoleListResponse)
def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_VIEW)),
):
    result = get_roles(db, page, page_size, search)
    return RoleListResponse(
        total=result["total"],
        items=result["items"],
        page=page,
        page_size=page_size,
    )


@router.get("/all")
def list_all_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_VIEW)),
):
    roles = get_roles(db)["items"]
    return [{"id": r.id, "name": r.name, "display_name": r.display_name} for r in roles]


@router.get("/permissions")
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_VIEW)),
):
    return get_permissions_by_category(db)


@router.get("/permissions/all")
def list_all_permissions_flat(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_VIEW)),
):
    return get_all_permissions(db)


@router.get("/{role_id}", response_model=RoleOut)
def get_role_detail(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_VIEW)),
):
    role = get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role_api(
   req: RoleCreate,
   request: Request = None,
   db: Session = Depends(get_db),
   current_user: User = Depends(require_permission(PERM_ROLE_CREATE)),
):
   from app.services.role_service import get_role_by_name
   existing = get_role_by_name(db, req.name)
   if existing:
       raise HTTPException(status_code=400, detail=f"角色标识 '{req.name}' 已存在")
   try:
       role = create_role(db, req.name, req.display_name, req.description,
                           req.department_scope, req.work_type_scope, req.permission_ids, current_user)
   except ValueError as e:
       raise HTTPException(status_code=400, detail=str(e))
   db.commit()
   # [新增 2026-09-09] 角色创建审计留痕
   try:
       client_ip = get_client_ip(request)
       record_audit(db, "role_create", current_user.employee_id,
                    detail=f"name={req.name}, display_name={req.display_name}, perms={len(req.permission_ids or [])}",
                    target=req.name, ip_address=client_ip)
       db.commit()
   except Exception: pass
   return role


@router.put("/{role_id}", response_model=RoleOut)
def update_role_api(
    role_id: int,
    req: RoleUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_EDIT)),
):
    role = update_role(db, role_id, req.display_name, req.description,
                        req.department_scope, req.work_type_scope, req.permission_ids)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 保护系统关键角色：仅超级管理员可修改 admin_manager 角色，防止降权逃逸
    if role.name == "admin_manager" and current_user.role != "admin_manager":
        db.rollback()
        raise HTTPException(status_code=403, detail="无权修改系统管理员角色")

    db.commit()
    # [新增 2026-09-09] 角色更新审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "role_update", current_user.employee_id,
                     detail=f"name={role.name}, perms={len(req.permission_ids or [])}",
                     target=role.name, ip_address=client_ip)
        db.commit()
    except Exception: pass
    return role


@router.delete("/{role_id}")
def delete_role_api(
    role_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_ROLE_DELETE)),
):
    # [新增 2026-09-09] 删除前查询名称用于审计详情
    _role = get_role(db, role_id)
    _name = _role.name if _role else str(role_id)
    # [修复 2026-09-10] 捕获「角色仍被账号使用」等业务校验错误，返回 400 而非 500
    try:
        success = delete_role(db, role_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    if not success:
        raise HTTPException(status_code=400, detail="角色不存在或为系统预设角色，不可删除")
    db.commit()
    # [新增 2026-09-09] 角色删除审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "role_delete", current_user.employee_id,
                     detail=f"name={_name}", target=_name, ip_address=client_ip)
        db.commit()
    except Exception: pass
    return {"message": "删除成功"}
