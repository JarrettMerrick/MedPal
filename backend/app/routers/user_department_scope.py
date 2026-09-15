# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    has_permission, PERM_STAFF_EDIT,
)
from app.models.user import User
from app.models.department import Department
from app.models.user_department_scope import UserDepartmentScope
from app.schemas.user_department_scope import (
    UserDepartmentScopeCreate,
    UserDepartmentScopeResponse,
    UserDepartmentScopeListResponse,
    DepartmentScopeUpdate,
)
# [新增 2026-09-09] 科室权限范围变更审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：科室管辖范围变更后通知管理方（超管 + 相关科室管理员）
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip

router = APIRouter(prefix="/api/user-department-scope", tags=["用户科室权限范围"])


def _check_scope_permission(user: User, target_employee_id: str, db: Session, action_label: str = "操作"):
    """统一权限检查：admin_manager（scope=all）可操作任意用户，dept_manager（scope=managed）仅可操作自己"""
    from app.dependencies import _get_role_dept_scope
    scope = _get_role_dept_scope(user)
    if scope == "all":
        return  # 全部通过
    if scope == "managed":
        if target_employee_id != user.employee_id:
            raise HTTPException(status_code=403, detail=f"只能{action_label}自己的科室权限范围")
        return
    raise HTTPException(status_code=403, detail="权限不足")


@router.get("/managed-by-me", response_model=list[str])
def get_managed_departments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户可管理的科室名称列表"""
    from app.dependencies import get_user_department_scope
    
    managed_dept_ids = get_user_department_scope(current_user, db)
    if not managed_dept_ids:
        return []
    
    dept_names = [dept.name for dept in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
    return dept_names


@router.get("/{employee_id}", response_model=UserDepartmentScopeListResponse)
def get_user_department_scope(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户科室权限范围
    
    权限规则：
    1. 超级管理员：可查看所有用户的科室权限范围
    2. 科室负责人/病区负责人：可查看自己的科室权限范围
    3. 普通员工：无权查看
    """
    _check_scope_permission(current_user, employee_id, db, "查看")
    
    scope_list = db.query(UserDepartmentScope).filter(
        UserDepartmentScope.employee_id == employee_id
    ).all()
    
    items = []
    for scope in scope_list:
        dept = db.query(Department).filter(Department.id == scope.department_id).first()
        if dept:
            items.append(UserDepartmentScopeResponse(
                id=scope.id,
                employee_id=scope.employee_id,
                department_id=scope.department_id,
                department_name=dept.name,
                created_at=scope.created_at,
            ))
    
    return UserDepartmentScopeListResponse(items=items, total=len(items))


@router.post("/{employee_id}", response_model=UserDepartmentScopeResponse, status_code=201)
def add_user_department_scope(
    employee_id: str,
    scope_in: UserDepartmentScopeCreate,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """添加用户科室关联
    
    权限规则：
    1. 超级管理员：可为任意用户添加科室关联
    2. 科室负责人/病区负责人：只能为自己添加科室关联
    """
    _check_scope_permission(current_user, employee_id, db, "添加")
    
    # 检查用户是否存在
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # [改进/U3] 被赋权用户必须处于启用状态：不给已停用的账号授予科室管辖权限，
    # 否则停用账号仍可能通过残留的 scope 关联访问对应科室数据。
    if not user.is_active:
        raise HTTPException(status_code=400, detail="该用户已停用，无法授予科室权限")

    # 检查科室是否存在
    dept = db.query(Department).filter(Department.id == scope_in.department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="科室不存在")

    # [改进/U2] 防止自助提权：managed 角色只能把"已管辖的科室"加入自身范围，
    # 不能新增任意科室，否则可通过 PUT /api/user-department-scope/{自己工号} 越权扩大管辖范围。
    from app.dependencies import _get_role_dept_scope, get_user_department_scope
    if _get_role_dept_scope(current_user) == "managed":
        allowed_ids = get_user_department_scope(current_user, db)
        if scope_in.department_id not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail="无权将该科室加入你的管辖范围（仅限你已管辖的科室）",
            )

    # 检查是否已存在关联
    existing = db.query(UserDepartmentScope).filter(
        UserDepartmentScope.employee_id == employee_id,
        UserDepartmentScope.department_id == scope_in.department_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该科室关联已存在")
    
    # 创建关联
    scope = UserDepartmentScope(
        employee_id=employee_id,
        department_id=scope_in.department_id,
    )
    db.add(scope)
    db.commit()
    db.refresh(scope)

    # [新增 2026-09-09] 科室权限授予审计留痕（敏感操作）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "dept_scope_add", current_user.employee_id,
                     detail=f"target={employee_id}, dept={dept.name}", target=employee_id, ip_address=client_ip)
        db.commit()
    except Exception: pass

    # [新增 2026-09-15] 科室管辖范围变更后补发站内信（事件：数据范围 / 科室管辖变更）：
    # 赋权直接影响账号能看到/能改的数据范围，是最需要知会的敏感操作之一，
    # 此前只写审计日志，超管与相关科室管理员不知情（默默扩大范围无人察觉）。
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="数据范围被调整",
            content=(
                f"{modifier_name} 为 {user.name}({employee_id}) "
                f"新增了管辖科室：{dept.name}"
            ),
            related_type="user",
            department=user.department or dept.name,
            exclude_user_id=current_user.employee_id,
            event_code="user.scope_changed",
            context={
                "操作人": modifier_name,
                "姓名": user.name,
                "工号": employee_id,
                "变更内容": f"新增管辖科室：{dept.name}",
            },
        )
        db.commit()
    except Exception: pass
    
    return UserDepartmentScopeResponse(
        id=scope.id,
        employee_id=scope.employee_id,
        department_id=scope.department_id,
        department_name=dept.name,
        created_at=scope.created_at,
    )


@router.delete("/{employee_id}/{scope_id}")
def delete_user_department_scope(
    employee_id: str,
    scope_id: int,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除用户科室关联"""
    _check_scope_permission(current_user, employee_id, db, "删除")
    
    # 查找关联
    scope = db.query(UserDepartmentScope).filter(
        UserDepartmentScope.id == scope_id,
        UserDepartmentScope.employee_id == employee_id,
    ).first()
    if not scope:
        raise HTTPException(status_code=404, detail="科室关联不存在")

    # [新增 2026-09-15] 删除前先取科室名与目标账号：关联删除后无法再读取，
    # 而站内信与审计需要写明「撤销了哪个科室的管辖」。
    removed_dept = db.query(Department).filter(Department.id == scope.department_id).first()
    removed_dept_name = removed_dept.name if removed_dept else f"ID {scope.department_id}"
    target_user = db.query(User).filter(User.employee_id == employee_id).first()
    
    # 删除关联
    db.delete(scope)
    db.commit()

    # [新增 2026-09-09] 科室权限撤销审计留痕（敏感操作）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "dept_scope_remove", current_user.employee_id,
                     detail=f"target={employee_id}, scope_id={scope_id}", target=employee_id, ip_address=client_ip)
        db.commit()
    except Exception: pass

    # [新增 2026-09-15] 撤销管辖后补发站内信（事件：数据范围 / 科室管辖变更）：
    # 收权同样需要留痕知会（防止「先赋权操作、再悄悄撤销」掩盖越权访问痕迹）。
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        target_name = target_user.name if target_user else employee_id
        notify_super_admins(
            db,
            title="数据范围被调整",
            content=(
                f"{modifier_name} 撤销了 {target_name}({employee_id}) "
                f"对科室「{removed_dept_name}」的管辖"
            ),
            related_type="user",
            department=(target_user.department if target_user else None) or removed_dept_name,
            exclude_user_id=current_user.employee_id,
            event_code="user.scope_changed",
            context={
                "操作人": modifier_name,
                "姓名": target_name,
                "工号": employee_id,
                "变更内容": f"移除管辖科室：{removed_dept_name}",
            },
        )
        db.commit()
    except Exception: pass
    
    return {"message": "科室关联已删除"}


@router.put("/{employee_id}", response_model=UserDepartmentScopeListResponse)
def update_user_department_scope(
    employee_id: str,
    scope_update: DepartmentScopeUpdate,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新用户科室权限范围
    
    权限规则：
    1. 超级管理员：可为任意用户更新科室权限范围
    2. 科室负责人/病区负责人：只能更新自己的科室权限范围
    """
    _check_scope_permission(current_user, employee_id, db, "更新")

    # 计算"原始管辖集合"（在删除现有关联之前，确保 managed 角色只能维持
    # 既有范围、不能借批量更新新增任意科室，防止自助提权）。
    from app.dependencies import _get_role_dept_scope, get_user_department_scope
    managed_scope = _get_role_dept_scope(current_user) == "managed"
    allowed_ids = get_user_department_scope(current_user, db) if managed_scope else []

    # 检查用户是否存在
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # [改进/U3] 被赋权用户必须处于启用状态：不给已停用的账号授予/刷新科室管辖权限。
    if not user.is_active:
        raise HTTPException(status_code=400, detail="该用户已停用，无法授予科室权限")

    # [新增 2026-09-15] 变更前快照：批量更新是「整体替换」语义，需对比出
    # 新增/移除的科室，站内信与留痕才能说清「范围是怎么变的」。
    old_dept_ids = {
        s.department_id for s in db.query(UserDepartmentScope).filter(
            UserDepartmentScope.employee_id == employee_id
        ).all()
    }
    new_dept_ids = set(scope_update.department_ids)

    # 删除现有所有关联
    db.query(UserDepartmentScope).filter(
        UserDepartmentScope.employee_id == employee_id
    ).delete()
    
    # 创建新关联
    for dept_id in scope_update.department_ids:
        # 检查科室是否存在
        dept = db.query(Department).filter(Department.id == dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail=f"科室ID {dept_id} 不存在")

        # [改进/U2] managed 角色只能写入其原始管辖集合内的科室
        if managed_scope and dept_id not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail=f"无权将科室ID {dept_id} 加入你的管辖范围（仅限你已管辖的科室）",
            )
        
        scope = UserDepartmentScope(
            employee_id=employee_id,
            department_id=dept_id,
        )
        db.add(scope)
    
    db.commit()

    # [新增 2026-09-09] 科室权限批量更新审计留痕（敏感操作）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "dept_scope_update", current_user.employee_id,
                     detail=f"target={employee_id}, depts={len(scope_update.department_ids)}", target=employee_id, ip_address=client_ip)
        db.commit()
    except Exception: pass

    # [新增 2026-09-15] 管辖范围调整后补发站内信（事件：数据范围 / 科室管辖变更）：
    # 仅在有实际增减时发送（避免「原样提交」也产生无信息量提醒）。
    added_ids = new_dept_ids - old_dept_ids
    removed_ids = old_dept_ids - new_dept_ids
    if added_ids or removed_ids:
        try:
            dept_name_map = {
                d.id: d.name
                for d in db.query(Department).filter(
                    Department.id.in_(added_ids | removed_ids)
                ).all()
            }

            def _dept_names(ids):
                """科室 ID 集合 → 顿号分隔的名称串（已删除的科室回退显示 ID）"""
                return "、".join(dept_name_map.get(i, f"ID {i}") for i in sorted(ids)) or "无"

            parts = []
            if added_ids:
                parts.append(f"新增管辖：{_dept_names(added_ids)}")
            if removed_ids:
                parts.append(f"移除管辖：{_dept_names(removed_ids)}")
            change_text = "；".join(parts)

            mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
            modifier_name = mod_user.name if mod_user else current_user.employee_id
            notify_super_admins(
                db,
                title="数据范围被调整",
                content=(
                    f"{modifier_name} 调整了 {user.name}({employee_id}) 的科室管辖范围：{change_text}"
                ),
                related_type="user",
                department=user.department or _dept_names(added_ids or removed_ids),
                exclude_user_id=current_user.employee_id,
                event_code="user.scope_changed",
                context={
                    "操作人": modifier_name,
                    "姓名": user.name,
                    "工号": employee_id,
                    "变更内容": change_text,
                },
            )
            db.commit()
        except Exception: pass

    # 返回更新后的列表
    scope_list = db.query(UserDepartmentScope).filter(
        UserDepartmentScope.employee_id == employee_id
    ).all()
    
    items = []
    for scope in scope_list:
        dept = db.query(Department).filter(Department.id == scope.department_id).first()
        if dept:
            items.append(UserDepartmentScopeResponse(
                id=scope.id,
                employee_id=scope.employee_id,
                department_id=scope.department_id,
                department_name=dept.name,
                created_at=scope.created_at,
            ))
    
    return UserDepartmentScopeListResponse(items=items, total=len(items))