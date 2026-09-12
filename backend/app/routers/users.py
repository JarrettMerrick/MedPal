# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 添加 Request 导入，用于获取客户端 IP 地址记录到系统日志
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
   get_current_user,
   ROLE_SUPER_ADMIN, ROLE_DEPT_MANAGER, ROLE_EMPLOYEE,
   has_permission, require_any_permission,
   get_user_department_scope, has_department_access,
   PERM_USER_VIEW, PERM_USER_CREATE, PERM_USER_EDIT, PERM_USER_DELETE, PERM_USER_RESET_PWD, PERM_ROLE_EDIT,
)
from app.models.user import User
from app.models.role import Role
from app.schemas.user import (
    ProfileUpdate,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.services.auth_service import reset_password, get_default_password
from app.services.user_service import create_user, get_user, get_user_list, update_user
# [修复 2026-09-01] 添加 record_audit 导入，用于记录密码重置等操作的审计日志
from app.services.audit_service import record_audit
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.get("", response_model=UserListResponse)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="搜索工号或姓名"),
    role: str | None = Query(None, description="按角色筛选"),
    has_profile: str | None = Query(None, description="筛选人员简介状态：true=有简介 / false=无简介"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户列表
    
    权限规则：
    1. 超级管理员/医务部管理员/护理部管理员：可查看所有用户
    2. 科室负责人/病区负责人：可查看本科室及关联科室的用户
    """
    # 权限检查
    if not has_permission(current_user, PERM_USER_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    
    # 基于数据范围过滤科室（department_scope=all 时不过滤）
    department_filter = None
    scope = current_user.role_obj.department_scope if current_user.role_obj else "own"
    if scope != "all":
        managed_dept_ids = get_user_department_scope(current_user, db)
        if managed_dept_ids:
            from app.models.department import Department
            dept_names = [dept.name for dept in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
            if dept_names:
                department_filter = "||".join(dept_names)
        else:
            # 无科室访问权限，返回空列表
            return UserListResponse(total=0, items=[], page=page, page_size=page_size)
    
    # 解析 has_profile 参数
    has_profile_bool = None
    if has_profile is not None:
        has_profile_bool = has_profile.lower() == "true"
    
    items, total = get_user_list(db, page=page, page_size=page_size, search=search, role=role, department_filter=department_filter, has_profile=has_profile_bool)
    # [新增 2026-09-10] 标记「系统中最后一个超级管理员」：
    # 该账号不允许删除/禁用/降级（后端强制校验，此处供前端置灰按钮 + 提示文案）。
    from app.services.admin_initializer import count_super_admins
    super_admin_count = count_super_admins(db)
    resp_items: list[UserResponse] = []
    for u in items:
        resp = UserResponse.model_validate(u)
        resp.is_last_super_admin = (u.role == ROLE_SUPER_ADMIN and super_admin_count <= 1)
        resp_items.append(resp)
    return UserListResponse(total=total, items=resp_items, page=page, page_size=page_size)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
   user_in: UserCreate,
   request: Request,
   current_user: User = Depends(require_any_permission(PERM_USER_CREATE)),
   db: Session = Depends(get_db),
):
   existing = get_user(db, user_in.employee_id)
   if existing:
       raise HTTPException(
           status_code=status.HTTP_400_BAD_REQUEST,
           detail=f"工号 {user_in.employee_id} 已存在",
       )
   if user_in.department and not has_department_access(current_user, user_in.department, db):
       raise HTTPException(status_code=403, detail="无权为该科室创建用户")
   try:
       user = create_user(db, user_in)
   except ValueError as e:
       raise HTTPException(status_code=400, detail=str(e))
   db.commit()

   # [修复 2026-09-01] 新增用户留痕
   try:
       client_ip = get_client_ip(request)
       record_audit(db, "user_create", current_user.employee_id,
                    detail=f"name={user_in.name} dept={user_in.department} role={user_in.role}",
                    target=user_in.employee_id, ip_address=client_ip)
       db.commit()
   except Exception:
       pass

   return user


@router.put("/{employee_id}", response_model=UserResponse)
def update_user_endpoint(
   employee_id: str,
   user_in: UserUpdate,
   request: Request,
   current_user: User = Depends(require_any_permission(PERM_USER_EDIT)),
   db: Session = Depends(get_db),
):
   # 获取修改前的用户信息用于审计
   old_user = get_user(db, employee_id)
   if not old_user:
       raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

   # 数据范围检查：检查是否有权修改该用户（基于用户当前科室）
   if not has_department_access(current_user, old_user.department or "", db):
       raise HTTPException(status_code=403, detail="无权修改该用户")

   update_data = user_in.model_dump(exclude_unset=True)

   # 防止自我提权：不能修改自己的角色/科室/启用状态
   if current_user.employee_id == employee_id:
       for _f in ("role", "role_id", "department", "is_active"):
           if _f in update_data:
               raise HTTPException(status_code=403, detail="不能修改自己的角色、科室或启用状态")

   # 新科室必须在操作者数据范围内
   if "department" in update_data and update_data["department"]:
       if not has_department_access(current_user, update_data["department"], db):
           raise HTTPException(status_code=403, detail="无权将该用户移动到该科室")

   # 角色/权限变更需 role.edit 权限（防止普通 user.edit 用户提权）
   if ("role" in update_data and update_data["role"] is not None) or \
      ("role_id" in update_data and update_data["role_id"] is not None):
       if not has_permission(current_user, PERM_ROLE_EDIT):
           raise HTTPException(status_code=403, detail="无权修改用户角色，需要角色管理权限")

   # [新增 2026-09-10] 「至少保留一个超级管理员」：
   # 最后一个超级管理员不允许被降级为其他角色，也不允许被禁用。
   from app.services.admin_initializer import count_super_admins
   if old_user.role == ROLE_SUPER_ADMIN and count_super_admins(db) <= 1:
       new_role = update_data.get("role")
       if new_role is not None and new_role != ROLE_SUPER_ADMIN:
           raise HTTPException(
               status_code=400,
               detail="系统必须保留至少一个超级管理员账号，无法变更最后一个超级管理员的角色",
           )
       if update_data.get("is_active") is False:
           raise HTTPException(
               status_code=400,
               detail="系统必须保留至少一个超级管理员账号，无法禁用最后一个超级管理员",
           )

   # [改进] 捕获角色名称无效的错误
   try:
       user = update_user(db, employee_id, user_in)
   except ValueError as e:
       raise HTTPException(status_code=400, detail=str(e))
   if not user:
       raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

   # 记录用户编辑审计日志
   from app.services.audit_service import record_modification, build_change_summary
   USER_FIELD_LABELS = {
       "name": "姓名", "role": "角色", "department": "所属科室",
       "is_active": "启用状态", "must_change_password": "需改密",
       "user_type": "用户类型", "role_id": "角色ID",
   }
   old_data = {k: str(getattr(old_user, k, "")) for k in USER_FIELD_LABELS}
   update_data = user_in.model_dump(exclude_unset=True)
   filtered_updates = {k: v for k, v in update_data.items() if k in USER_FIELD_LABELS}
   if filtered_updates:
       change_summary = build_change_summary(old_data, filtered_updates, USER_FIELD_LABELS)
       # [修复 2026-09-01] 传递客户端 IP 到 record_modification，记录到系统日志
       client_ip = get_client_ip(request)
       record_modification(
           db, entity_type="user", entity_id=employee_id,
           modified_by=current_user.employee_id, change_summary=change_summary,
           ip_address=client_ip,
       )

   db.commit()
   return user


@router.post("/{employee_id}/reset-password")
def reset_user_password(
   employee_id: str,
   request: Request,
   current_user: User = Depends(require_any_permission(PERM_USER_RESET_PWD)),
   db: Session = Depends(get_db),
):
   user = get_user(db, employee_id)
   if not user:
       raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
   if not has_department_access(current_user, user.department or "", db):
       raise HTTPException(status_code=403, detail="无权重置该用户密码")
   # [修复/问题18 回归] reset_password 现在返回随机生成的强口令明文，
   # 必须回显给管理员以便转告使用者。原实现丢弃返回值、只回一句
   # "密码已重置为默认密码"，前端又硬编码提示 123456，
   # 导致提示的密码与库里实际写入的随机口令不一致，使用者始终无法登录。
   new_password = reset_password(db, user)
   # [修复 2026-09-01] 记录密码重置审计日志
   try:
       client_ip = get_client_ip(request)
       record_audit(db, "password_reset", current_user.employee_id,
                    detail=f"ip={client_ip}, target_user={employee_id}",
                    target=employee_id, ip_address=client_ip)
       db.commit()
   except Exception:
       db.rollback()
   return {"message": "密码已重置", "password": new_password}


@router.delete("/{employee_id}")
def delete_user_endpoint(
    employee_id: str,
    request: Request,
    current_user: User = Depends(require_any_permission(PERM_USER_DELETE)),
    db: Session = Depends(get_db),
):
    """删除用户账号

    [调整 2026-09-10] 不再无条件禁止删除 admin：任何账号（含超级管理员）均可删除，
    但系统必须**始终保留至少一个超级管理员**，因此删除「最后一个超级管理员」会被拒绝。
    若 admin 被删除，只要系统内还有其他超级管理员即可正常删除；
    若超管数量意外归零，下次启动会由 admin_initializer 自动补齐。
    """
    from app.services.user_service import get_user
    user = get_user(db, employee_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # [新增 2026-09-10] 「至少保留一个超级管理员」校验
    from app.services.admin_initializer import count_super_admins
    if user.role == ROLE_SUPER_ADMIN and count_super_admins(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="系统必须保留至少一个超级管理员账号，无法删除最后一个超级管理员",
        )

    # 级联删除关联记录，避免孤儿数据（悬空引用）
    from app.models.staff import Staff
    from app.models.staff_card import StaffCard
    from app.models.user_department_scope import UserDepartmentScope
    from app.models.notification import Notification
    # [新增 2026-09-11] 站内信：删除用户时清理其收件记录与自定义标签
    from app.models.message import MessageRecipient, MessageTag
    from app.models.audit_log import ModificationHistory

    # [修复] 删除前收集磁盘照片路径（人员照 + 工牌照），
    # 数据库记录删除后同步清理磁盘文件，避免孤儿文件长期残留占盘
    from app.services.upload_service import delete_file as _delete_upload_file
    from app.services.staff_service import get_staff
    photos_to_delete: list[str] = []
    staff = get_staff(db, employee_id)
    actual_id = staff.employee_id if staff else employee_id
    if staff:
        for p in (staff.front_photo, staff.side_photo):
            if p:
                photos_to_delete.append(p)
    card_photos = [
        c.card_photo
        for c in db.query(StaffCard).filter(StaffCard.entity_id == actual_id).all()
        if c.card_photo
    ]
    photos_to_delete.extend(card_photos)

    db.query(StaffCard).filter(StaffCard.entity_id == actual_id).delete()
    db.query(UserDepartmentScope).filter(UserDepartmentScope.employee_id == actual_id).delete()
    db.query(Notification).filter(Notification.user_id == actual_id).delete()
    # [新增 2026-09-11] 站内信：清理该用户的收件记录与自定义标签（先收件人、后标签，避免外键约束）
    db.query(MessageRecipient).filter(MessageRecipient.user_id == actual_id).delete()
    db.query(MessageTag).filter(MessageTag.user_id == actual_id).delete()
    db.query(ModificationHistory).filter(ModificationHistory.entity_id == actual_id).delete()
    db.query(Staff).filter(Staff.employee_id == actual_id).delete()

    # [修复 2026-09-01] 删除用户留痕（在 db.delete 之前记录，避免 user 对象失效）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "user_delete", current_user.employee_id,
                     detail=f"name={user.name} dept={user.department}",
                     target=employee_id, ip_address=client_ip)
    except Exception:
        pass

    db.delete(user)
    db.commit()

    # 删除磁盘照片文件（delete_file 联动清理 thumb_/orig_ 副本）
    for p in photos_to_delete:
        try:
            _delete_upload_file(p)
        except Exception:
            pass
    return {"message": "用户已删除", "employee_id": employee_id}


@router.post("/batch-create-from-staff")
def batch_create_users(
   request: Request,
   current_user: User = Depends(require_any_permission(PERM_USER_CREATE)),
   db: Session = Depends(get_db),
):
   """从统一人员表中批量创建员工账号（仅限操作者数据范围内的员工）"""
   from app.models.staff import Staff
   from app.config import settings
   from app.utils import hash_password
   from app.constants import WORK_TYPE_TO_USER_TYPE

   # 基于数据范围过滤员工（department_scope=all 时不过滤）
   scope = current_user.role_obj.department_scope if current_user.role_obj else "own"
   if scope == "all":
       # 获取所有在职工号
       all_staff = db.query(Staff.employee_id, Staff.name, Staff.department, Staff.work_type).filter(
           Staff.status == "active"
       ).all()
   else:
       # 获取操作者可访问的科室名称列表
       managed_dept_ids = get_user_department_scope(current_user, db)
       if not managed_dept_ids:
           return {"created": 0, "skipped": 0, "message": "无科室访问权限，批量创建中止"}
       from app.models.department import Department
       dept_names = [dept.name for dept in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
       if not dept_names:
           return {"created": 0, "skipped": 0, "message": "无匹配科室，批量创建中止"}
       # 获取管辖科室内的在职工号
       all_staff = db.query(Staff.employee_id, Staff.name, Staff.department, Staff.work_type).filter(
           Staff.status == "active",
           Staff.department.in_(dept_names)
       ).all()

   # 获取已有账号的工号
   existing_ids = set(row[0] for row in db.query(User.employee_id).all())

   created = 0
   skipped = 0

   for emp_id, name, dept, work_type in all_staff:
       if emp_id in existing_ids:
           skipped += 1
           continue
       user_type = WORK_TYPE_TO_USER_TYPE.get(work_type, "admin_user")
       # [改进] 反查 employee 角色 id，保证 role_id 与 role 一致
       emp_role = db.query(Role).filter(Role.name == ROLE_EMPLOYEE).first()
       user = User(
           employee_id=emp_id,
           name=name,
           # [调整 2026-09-10] 初始口令按「账号设置」中的模板生成（支持 {工号} 占位符）
           password_hash=hash_password(get_default_password(db, emp_id)),
           role=ROLE_EMPLOYEE,
           role_id=emp_role.id if emp_role else None,
           department=dept,
           user_type=user_type,
           must_change_password=True,
       )
       db.add(user)
       created += 1

   db.commit()

   # [修复 2026-09-01] 批量创建用户留痕
   try:
       client_ip = get_client_ip(request)
       record_audit(db, "user_batch_create", current_user.employee_id,
                    detail=f"created={created}, skipped={skipped}",
                    target="batch", ip_address=client_ip)
       db.commit()
   except Exception:
       pass

   return {"created": created, "skipped": skipped, "message": f"成功创建 {created} 个账号，跳过 {skipped} 个已存在的账号"}


@router.put("/profile/me")
def update_my_profile(
    profile_in: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if profile_in.name is not None:
        current_user.name = profile_in.name
    db.commit()
    return {"message": "修改成功"}
