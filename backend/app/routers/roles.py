# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    require_permission,
    PERM_ROLE_VIEW, PERM_ROLE_CREATE, PERM_ROLE_EDIT, PERM_ROLE_DELETE,
)
from app.models.role import Permission
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
# [新增 2026-09-15] 站内信提醒：角色 / 权限变更后通知超管
from app.services.modification_notify import notify_super_admins
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

   # [新增 2026-09-15] 新增角色后补发站内信（事件：角色 / 权限变更）：
   # 新角色的权限组合决定了持有者能做什么，属权限体系敏感变更，
   # 此前只写审计日志，超管无任何主动知会。
   try:
       mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
       modifier_name = mod_user.name if mod_user else current_user.employee_id
       notify_super_admins(
           db,
           title="新增角色",
           content=(
               f"{modifier_name} 新增了角色「{req.display_name}」"
               f"（权限点 {len(req.permission_ids or [])} 个）"
           ),
           related_type="role",
           exclude_user_id=current_user.employee_id,
           event_code="role.changed",
           context={
               "操作人": modifier_name,
               "角色": req.display_name,
               "变更内容": f"新增角色「{req.display_name}」，权限点 {len(req.permission_ids or [])} 个",
           },
       )
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
    # [新增 2026-09-15] 变更前快照：权限点是「整体替换」语义（permission_ids 为 None
    # 时表示不修改权限），须先取旧集合，才能对比出增减明细、说清「权限是怎么变的」。
    before_role = get_role(db, role_id)
    before_perm_ids = {p.id for p in before_role.permissions} if before_role else set()

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

    # [新增 2026-09-15] 角色变更后补发站内信（事件：角色 / 权限变更）：
    # 权限调整影响所有持有该角色的账号（可能是一次批量提权/降权），
    # 此前只写审计日志，超管无任何主动知会。
    try:
        changes = []
        if before_role and before_role.display_name != role.display_name:
            changes.append(f"角色名: {before_role.display_name} → {role.display_name}")
        if before_role and before_role.department_scope != role.department_scope:
            _scope_labels = {"own": "仅本科室", "managed": "管辖科室", "all": "所有科室"}
            changes.append(
                "数据范围: "
                f"{_scope_labels.get(before_role.department_scope, before_role.department_scope)}"
                f" → {_scope_labels.get(role.department_scope, role.department_scope)}"
            )
        if before_role and before_role.work_type_scope != role.work_type_scope:
            from app.schemas.staff import WORK_TYPE_LABELS

            def _wt_label(v):
                """工种范围值 → 中文（all/空 = 全部工种；否则按逗号翻译代码）"""
                if not v or v == "all":
                    return "全部工种"
                return "、".join(WORK_TYPE_LABELS.get(x, x) for x in str(v).split(",") if x)

            changes.append(
                f"工种范围: {_wt_label(before_role.work_type_scope)} → {_wt_label(role.work_type_scope)}"
            )
        if req.permission_ids is not None:
            new_perm_ids = set(req.permission_ids)
            added_ids = new_perm_ids - before_perm_ids
            removed_ids = before_perm_ids - new_perm_ids
            if added_ids or removed_ids:
                perm_name_map = {
                    p.id: (p.display_name or p.name)
                    for p in db.query(Permission).filter(
                        Permission.id.in_(added_ids | removed_ids)
                    ).all()
                }

                def _perm_names(ids, limit=5):
                    """权限 ID 集合 → 中文名称串（超出 limit 时截断并标注总数）"""
                    names = [perm_name_map.get(i, f"ID {i}") for i in sorted(ids)]
                    shown = "、".join(names[:limit])
                    return shown + (f" 等 {len(names)} 项" if len(names) > limit else "")

                if added_ids:
                    changes.append(f"新增权限：{_perm_names(added_ids)}")
                if removed_ids:
                    changes.append(f"移除权限：{_perm_names(removed_ids)}")

        change_text = "；".join(changes)
        if change_text:
            mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
            modifier_name = mod_user.name if mod_user else current_user.employee_id
            notify_super_admins(
                db,
                title="角色权限被修改",
                content=f"{modifier_name} 修改了角色「{role.display_name}」：{change_text}",
                related_type="role",
                exclude_user_id=current_user.employee_id,
                event_code="role.changed",
                context={
                    "操作人": modifier_name,
                    "角色": role.display_name or role.name,
                    "变更内容": change_text,
                },
            )
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
    # [新增 2026-09-15] 删除前记录角色显示名与原权限点数量：
    # 角色删除后无法再统计，站内信需要交代「删掉了什么、原有权限规模多大」
    _display_name = _role.display_name if _role else _name
    _perm_count = len(_role.permissions) if _role else 0
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

    # [新增 2026-09-15] 角色删除后补发站内信（事件：角色 / 权限变更）：
    # 删除角色会一并移除其权限组合，此前只写审计日志，超管不知情。
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="角色被删除",
            content=(
                f"{modifier_name} 删除了角色「{_display_name}」"
                f"（原含 {_perm_count} 个权限点）"
            ),
            related_type="role",
            exclude_user_id=current_user.employee_id,
            event_code="role.changed",
            context={
                "操作人": modifier_name,
                "角色": _display_name,
                "变更内容": f"删除角色「{_display_name}」（原含 {_perm_count} 个权限点）",
            },
        )
        db.commit()
    except Exception: pass
    return {"message": "删除成功"}
