# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
from sqlalchemy.orm import Session

from app.models.role import Role, Permission
from app.models.user import User
# [修复 2026-09-10] 角色增删后同步刷新 User 模型的 ORM 有效角色名校验集合，
# 否则本次运行内新角色无法被分配给用户（详见 role_initializer.sync_valid_role_names）。
from app.services.role_initializer import sync_valid_role_names

# 有效的数据范围值
VALID_DEPT_SCOPES = ("own", "managed", "all")
VALID_WORK_TYPE_SCOPES = ("all",)  # "all" 或逗号分隔的工种列表如 "doctor,nurse"

logger = logging.getLogger("role_service")


def _validate_scopes(department_scope: str = None, work_type_scope: str = None):
    """校验 department_scope 和 work_type_scope 的有效性"""
    if department_scope is not None and department_scope not in VALID_DEPT_SCOPES:
        raise ValueError(f"无效的科室范围: {department_scope}，有效值: {VALID_DEPT_SCOPES}")
    if work_type_scope is not None and work_type_scope != "all":
        # 允许 "all" 或逗号分隔的工种列表
        types = [w.strip() for w in work_type_scope.split(",") if w.strip()]
        valid_types = {"doctor", "nurse", "technician", "admin"}
        invalid = [t for t in types if t not in valid_types]
        if invalid:
            raise ValueError(f"无效的工种范围值: {invalid}，有效工种: {valid_types}")


def get_roles(db: Session, page: int = 1, page_size: int = 20, search: str = None) -> dict:
    """获取角色列表"""
    query = db.query(Role)
    if search:
        query = query.filter(
            Role.name.ilike(f"%{search}%") | Role.display_name.ilike(f"%{search}%")
        )
    total = query.count()
    items = query.order_by(Role.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total}


def get_all_roles(db: Session) -> list:
    """获取所有角色（用于下拉选择）"""
    return db.query(Role).order_by(Role.id).all()


def get_role(db: Session, role_id: int) -> Role | None:
    """获取单个角色"""
    return db.query(Role).filter(Role.id == role_id).first()


def get_role_by_name(db: Session, name: str) -> Role | None:
    """根据标识获取角色"""
    return db.query(Role).filter(Role.name == name).first()


def create_role(db: Session, name: str, display_name: str, description: str = None,
                department_scope: str = "own", work_type_scope: str = "all",
                permission_ids: list = None, current_user: User = None) -> Role:
   """创建角色"""
   _validate_scopes(department_scope, work_type_scope)
   
   # 安全校验：防止权限提升攻击
   if current_user:
       from app.dependencies import PERM_ROLE_CREATE, PERM_ROLE_EDIT, has_permission, _get_role_dept_scope
       scope = _get_role_dept_scope(current_user)
       # 如果操作者的 department_scope 不是 all，则不允许创建拥有 role.create + role.edit 权限的角色
       if scope != "all" and permission_ids:
           # 检查是否包含 role.create 和 role.edit 权限
           dangerous_permissions = {"role.create", "role.edit"}
           if has_permission(current_user, PERM_ROLE_CREATE) and has_permission(current_user, PERM_ROLE_EDIT):
               # 操作者拥有角色管理权限，但数据范围有限，需要检查新角色是否会被赋予危险权限
               # 获取新角色将拥有的权限名称
               new_permissions = db.query(Permission.name).filter(Permission.id.in_(permission_ids)).all()
               new_perm_names = {p[0] for p in new_permissions}
               if dangerous_permissions.issubset(new_perm_names):
                   raise ValueError("数据范围受限，不允许创建同时拥有 '角色创建' 和 '角色编辑' 权限的角色")
   
   role = Role(
       name=name, display_name=display_name, description=description,
       department_scope=department_scope, work_type_scope=work_type_scope,
   )
   if permission_ids:
       permissions = db.query(Permission).filter(Permission.id.in_(permission_ids)).all()
       role.permissions = permissions
   db.add(role)
   db.flush()
   # [修复 2026-09-10] 新角色落库后立即同步 ORM 校验集合，
   # 使本次运行内即可把该角色分配给用户，无需重启
   sync_valid_role_names(db)
   return role


def update_role(db: Session, role_id: int, display_name: str = None, description: str = None,
                department_scope: str = None, work_type_scope: str = None,
                permission_ids: list = None) -> Role | None:
    """更新角色"""
    _validate_scopes(department_scope, work_type_scope)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return None
    if display_name is not None:
        role.display_name = display_name
    if description is not None:
        role.description = description
    if department_scope is not None:
        role.department_scope = department_scope
    if work_type_scope is not None:
        role.work_type_scope = work_type_scope
    if permission_ids is not None:
        permissions = db.query(Permission).filter(Permission.id.in_(permission_ids)).all()
        role.permissions = permissions
    db.flush()
    return role


def delete_role(db: Session, role_id: int) -> bool:
    """删除角色（系统预设角色不可删除；仍被账号使用的角色不可删除）

    [修复 2026-09-10] 增加「在用角色不可删除」前置校验：
      1) 语义上不应删除仍被账号引用的角色（否则那些账号会失去角色、权限全无）；
      2) 直接 db.delete 时，ORM 会尝试把关联用户的 User.role 置空
         （role_obj 关系以 User.role 作为外键），该写入会被
         @validates('role') 拦截成 ValueError，最终表现为 500 服务器内部错误。
    命中时抛 ValueError，由路由层转换为 400 并回显明确原因。
    """
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role or role.is_system:
        return False
    in_use = db.query(User).filter(
        (User.role == role.name) | (User.role_id == role.id)
    ).count()
    if in_use:
        raise ValueError(f"该角色仍被 {in_use} 个账号使用，请先调整这些账号的角色后再删除")
    db.delete(role)
    db.flush()
    # [修复 2026-09-10] 角色删除后同步刷新校验集合，避免已删角色名仍被视为有效
    sync_valid_role_names(db)
    return True


def get_all_permissions(db: Session) -> list:
    """获取所有权限"""
    return db.query(Permission).order_by(Permission.category, Permission.id).all()


def get_permissions_by_category(db: Session) -> list[dict]:
    """按分类获取权限"""
    permissions = db.query(Permission).order_by(Permission.category, Permission.id).all()

    category_labels = {
        "staff": "人员管理",
        "department": "科室管理",
        "regulation": "制度管理",
        # [修复 2026-09-07] 标识权限拆分为两大分类
        "signage_workspace": "标识平面",
        "signage_settings": "标识设置",
        "user": "用户管理",
        "role": "角色管理",
        "data": "数据管理",
        "system": "系统管理",
        # [新增 2026-09-15] 功能类权限分类命名为「系统设置」：
        # 该分类下为「系统设置」相关入口的访问权限（功能开关 / 通知设置）。
        # 此前未登记 label，角色管理中直接显示英文 category（feature）且排序落在最后，
        # 既不易理解也与其余中文分类不一致。
        "feature": "系统设置",
        "card": "特殊功能",
        # [新增 2026-09-11] 站内信权限分类
        "message": "站内信",
        # [新增 2026-09-17] 文件库（设计文件集中管理）
        "file_library": "文件库",
    }

    categories = {}
    for p in permissions:
        if p.category not in categories:
            categories[p.category] = {
                "category": p.category,
                "category_label": category_labels.get(p.category, p.category),
                "permissions": [],
            }
        categories[p.category]["permissions"].append(p)

    # 按 category_label 排序
    return sorted(categories.values(), key=lambda c: list(category_labels.keys()).index(c["category"]) if c["category"] in category_labels else 999)
