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
# [新增 2026-09-15] 站内信提醒：账号增删改 / 重置密码后通知管理方（超管 + 相关科室管理员）
from app.services.modification_notify import notify_super_admins
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

router = APIRouter(prefix="/api/users", tags=["用户管理"])


def _fmt_user_value(field: str, value, role_labels: dict) -> str:
    """把账号字段值转成可读文本（None 视为空）

    [新增 2026-09-15] 修改历史与站内信直接展示 build_change_summary 生成的摘要，
    若摘要里保留 role 代码（employee/dept_manager）或布尔原值（True/False），
    使用者无法理解「被改成了什么」，因此统一在此转成中文可读文本。
    """
    if value is None:
        return ""
    if field == "role":
        return role_labels.get(str(value), str(value))
    if field == "is_active":
        return "启用" if value else "停用"
    if field == "must_change_password":
        return "需改密" if value else "免改密"
    return str(value)


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

   # [新增 2026-09-15] 新增账号后补发站内信（事件：新增用户账号）：

   # 此前仅写系统日志/审计，管理方（超管 + 该账号所属科室的管理员）无任何主动知会。
   # 自动排除操作者本人；若无人可收（如唯一超管自己建号），回落给操作者本人作为操作回执。
   try:
       operator = get_user(db, current_user.employee_id)
       operator_name = operator.name if operator else current_user.employee_id
       role_row = None
       if user_in.role_id:
           role_row = db.query(Role).filter(Role.id == user_in.role_id).first()
       if role_row is None:
           role_row = db.query(Role).filter(Role.name == user_in.role).first()
       role_disp = (role_row.display_name or role_row.name) if role_row else user_in.role
       notify_super_admins(
           db,
           title="新增账号",
           content=(
               f"{operator_name} 新增了用户账号 {user_in.name}({user_in.employee_id})，"
               f"角色={role_disp}，科室={user_in.department or '未设置'}"
           ),
           related_type="user",
           department=user_in.department,
           exclude_user_id=current_user.employee_id,
           event_code="user.created",
           context={
               "操作人": operator_name,
               "姓名": user_in.name,
               "工号": user_in.employee_id,
               "角色": role_disp,
               "变更内容": f"新增用户账号 {user_in.name}({user_in.employee_id})，角色={role_disp}",
           },
       )
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

   # [新增 2026-09-15] 变更前快照必须在「更新之前」取值：
   # 原实现把 old_data 放在 update_user 之后构建，而 get_user / update_user
   # 查询到的是同一 ORM 实例（identity map），快照读到的其实是新值，
   # build_change_summary 因此恒判「无差异」→ 修改历史与站内信永远只有
   # 「更新操作」，等于「改了却查不到改了什么」。现改为更新前先做快照，更新后取新值对比。
   from app.services.audit_service import record_modification, build_change_summary
   USER_FIELD_LABELS = {
       "name": "姓名", "role": "角色", "department": "所属科室",
       "is_active": "启用状态", "must_change_password": "需改密",
       "user_type": "用户类型", "role_id": "角色ID",
   }
   # 摘要值可读化所需的角色显示名映射（employee → 普通员工 等）
   role_labels = {r.name: (r.display_name or r.name) for r in db.query(Role).all()}
   before_values = {k: getattr(old_user, k, None) for k in USER_FIELD_LABELS}

   # [改进] 捕获角色名称无效的错误
   try:
       user = update_user(db, employee_id, user_in)
   except ValueError as e:
       raise HTTPException(status_code=400, detail=str(e))
   if not user:
       raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

   # 记录用户编辑审计日志
   old_data = {k: _fmt_user_value(k, v, role_labels) for k, v in before_values.items()}
   update_data = user_in.model_dump(exclude_unset=True)
   filtered_updates = {
       k: _fmt_user_value(k, getattr(user, k, None), role_labels)
       for k in update_data if k in USER_FIELD_LABELS
   }
   if filtered_updates:
       change_summary = build_change_summary(old_data, filtered_updates, USER_FIELD_LABELS)
       # [修复 2026-09-01] 传递客户端 IP 到 record_modification，记录到系统日志
       client_ip = get_client_ip(request)
       record_modification(
           db, entity_type="user", entity_id=employee_id,
           modified_by=current_user.employee_id, change_summary=change_summary,
           ip_address=client_ip,
       )
       # [新增 2026-09-15] 账号信息 / 状态变更后补发站内信（事件：账号信息 / 状态变更）：
       # 角色调整、启用停用、科室变动均属高敏感操作，此前只写修改历史，
       # 管理方（超管 + 相关科室管理员）无任何主动知会。
       if change_summary and change_summary != "更新操作":
           try:
               mod_user = get_user(db, current_user.employee_id)
               modifier_name = mod_user.name if mod_user else current_user.employee_id
               notify_super_admins(
                   db,
                   title="账号被修改",
                   content=(
                       f"{modifier_name} 修改了用户账号 "
                       f"{old_user.name}({employee_id})：{change_summary}"
                   ),
                   related_type="user",
                   # 科室可能被改动：新旧科室的管理员都应知情，此处以新科室为准、
                   # 空值回退旧科室（不再额外通知旧科室，避免收件人范围失控）。
                   department=user.department or old_user.department,
                   exclude_user_id=current_user.employee_id,
                   event_code="user.updated",
                   context={
                       "操作人": modifier_name,
                       "姓名": old_user.name,
                       "工号": employee_id,
                       "变更内容": change_summary,
                   },
               )
           except Exception:
               pass

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

   # [新增 2026-09-15] 重置他人密码后补发站内信（事件：重置账号密码）：
   # 管理端重置口令属账号安全敏感操作，此前只写审计日志，账号所属科室的管理员
   # 与超管无任何主动知会（若有人盗用管理员账号批量改密，受害者与管理者都不会察觉）。
   try:
       mod_user = get_user(db, current_user.employee_id)
       modifier_name = mod_user.name if mod_user else current_user.employee_id
       notify_super_admins(
           db,
           title="账号密码被重置",
           content=f"{modifier_name} 重置了用户账号 {user.name}({employee_id}) 的登录密码",
           related_type="user",
           department=user.department,
           exclude_user_id=current_user.employee_id,
           event_code="user.password_reset",
           context={
               "操作人": modifier_name,
               "姓名": user.name,
               "工号": employee_id,
               "变更内容": f"重置用户账号 {user.name}({employee_id}) 的登录密码",
           },
       )
       db.commit()
   except Exception:
       pass
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

    # [新增 2026-09-15] 删除账号后补发站内信（事件：删除用户账号）：
    # 账号删除不可逆（连带清理 Staff / 工牌 / 照片 / 收件记录），此前只写审计日志。
    # 收件人 = 超管 + 该账号所属科室的管理员，自动排除操作者本人与被删账号本身；
    # 无人可收时回落给操作者本人作为操作回执。
    try:
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="删除账号",
            content=(
                f"{modifier_name} 删除了用户账号 {user.name}({employee_id})，"
                f"科室={user.department or '未设置'}"
            ),
            related_type="user",
            department=user.department,
            exclude_user_id=current_user.employee_id,
            # 被删账号本身不再接收通知（否则会收到「自己已被删除」的通知）
            exclude_ids=[employee_id],
            event_code="user.deleted",
            context={
                "操作人": modifier_name,
                "姓名": user.name,
                "工号": employee_id,
                "变更内容": f"删除用户账号 {user.name}({employee_id})",
            },
        )
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

   # [新增 2026-09-15] 批量建号后补发站内信（事件：新增用户账号）：
   # 一次操作可能新增数十个账号，此前只写审计日志，管理方不知情。
   # 批量场景没有单一「相关科室」，故不传 department（收件人 = 全体超管，排除操作者本人）。
   if created:
       try:
           operator = get_user(db, current_user.employee_id)
           operator_name = operator.name if operator else current_user.employee_id
           notify_super_admins(
               db,
               title="批量新建账号",
               content=(
                   f"{operator_name} 批量新建了 {created} 个员工账号"
                   + (f"（跳过 {skipped} 个已存在账号）" if skipped else "")
               ),
               related_type="user",
               exclude_user_id=current_user.employee_id,
               event_code="user.created",
               context={
                   "操作人": operator_name,
                   "姓名": f"批量新建 {created} 个账号",
                   "工号": "批量",
                   "角色": "普通员工",
                   "变更内容": f"批量新建 {created} 个员工账号（跳过 {skipped} 个已存在账号）",
               },
           )
           db.commit()
       except Exception:
           pass

   return {"created": created, "skipped": skipped, "message": f"成功创建 {created} 个账号，跳过 {skipped} 个已存在的账号"}


@router.put("/profile/me")
def update_my_profile(
    profile_in: ProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # [新增 2026-09-15] 姓名变更留痕：此前该接口直接改字段、无任何审计记录
    # （「改了却查不到」）。通知层面姓名变更走 auth.py /auth/profile 的审核派发路径，
    # 此处不重复发信，仅补系统日志。
    old_name = current_user.name
    if profile_in.name is not None:
        current_user.name = profile_in.name
    db.commit()
    if profile_in.name is not None and profile_in.name != old_name:
        try:
            client_ip = get_client_ip(request)
            record_audit(db, "profile_update", current_user.employee_id,
                         detail=f"姓名: {old_name} → {profile_in.name}",
                         target=current_user.employee_id, ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
    return {"message": "修改成功"}
