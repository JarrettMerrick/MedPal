# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_department_scope import UserDepartmentScope
from app.services.auth_service import is_token_blacklisted
from app.utils import decode_token

security = HTTPBearer()

# 角色常量
ROLE_SUPER_ADMIN = "admin_manager"      # 旧 super_admin 被删除，admin_manager 接管
ROLE_DEPT_MANAGER = "dept_manager"
ROLE_EMPLOYEE = "employee"

# ==================== 权限名称常量（新版权限） ====================
# 人员管理
PERM_STAFF_VIEW = "staff.view"
PERM_STAFF_CREATE = "staff.create"
PERM_STAFF_EDIT = "staff.edit"
PERM_STAFF_DELETE = "staff.delete"
PERM_STAFF_STATUS = "staff.status"
# [新增 2026-09-11] 人员信息变更审核：审核人员信息修改（立即生效 + 追认/回滚）
# 科室管理员默认拥有（仅限管辖科室的「科室级」变更）；超级管理员审全部
PERM_STAFF_APPROVE = "staff.approve"
# 科室管理
PERM_DEPT_VIEW = "department.view"
PERM_DEPT_CREATE = "department.create"
PERM_DEPT_EDIT = "department.edit"
PERM_DEPT_DELETE = "department.delete"
# 制度管理
PERM_REGULATION_VIEW = "regulation.view"
PERM_REGULATION_CREATE = "regulation.create"
PERM_REGULATION_EDIT = "regulation.edit"
PERM_REGULATION_DELETE = "regulation.delete"
# 标识管理
PERM_SIGNAGE_VIEW = "signage.view"
PERM_SIGNAGE_CREATE = "signage.create"
PERM_SIGNAGE_EDIT = "signage.edit"
PERM_SIGNAGE_DELETE = "signage.delete"
PERM_SIGNAGE_EXPORT = "signage.export"
PERM_SIGNAGE_FLOORPLAN = "signage.floorplan"
# [新增 2026-09-07] 标识权限细化：拆分为「标识平面」与「标识设置」两大分类下的细粒度权限项
PERM_SIGNAGE_MARKER = "signage.marker"              # 标识平面 - 标识标记（平面图点位增删）
PERM_SIGNAGE_ALERT = "signage.alert"                # 标识平面 - 查看标识预警
PERM_SIGNAGE_INSPECTION = "signage.inspection"      # 标识平面 - 标识巡检（提交巡检结果/照片）
PERM_SIGNAGE_REPAIR = "signage.repair"              # 标识平面 - 维修记录（查看全部维修记录并导出）
PERM_SIGNAGE_CAMPUS = "signage.campus"              # 标识设置 - 院区管理（院区/楼栋/楼层/区域维护）
PERM_SIGNAGE_CATEGORY = "signage.category"          # 标识设置 - 标识分类设置
PERM_SIGNAGE_SUPPLIER = "signage.supplier"          # 标识设置 - 供应商设置
# 用户管理
PERM_USER_VIEW = "user.view"
PERM_USER_CREATE = "user.create"
PERM_USER_EDIT = "user.edit"
PERM_USER_DELETE = "user.delete"
PERM_USER_RESET_PWD = "user.reset_password"
# [新增 2026-09-10] 账号审核：审核登录页自助注册申请（科室管理员仅限管辖科室）
PERM_USER_APPROVE = "user.approve"
# 角色管理
PERM_ROLE_VIEW = "role.view"
PERM_ROLE_CREATE = "role.create"
PERM_ROLE_EDIT = "role.edit"
PERM_ROLE_DELETE = "role.delete"
# 数据管理
PERM_DATA_EXPORT = "data.export"
PERM_DATA_IMPORT = "data.import"
# 系统管理
PERM_SYSTEM_CONFIG = "system.config"
PERM_SYSTEM_BACKUP = "system.backup"
PERM_SYSTEM_AUDIT = "system.audit"
# 特殊功能
PERM_CARD_UPLOAD = "card.upload"
PERM_STAFF_VIEW_RESIGNED = "staff.view_resigned"
# [新增 2026-09-11] 站内信
PERM_MESSAGE_VIEW = "message.view"            # 查看本人站内信（所有角色默认拥有）
PERM_MESSAGE_SEND = "message.send"            # 私发给指定人员
PERM_MESSAGE_BROADCAST = "message.broadcast"  # 按全员/科室/角色/权限群发

SUPER_ROLES = (ROLE_SUPER_ADMIN,)  # now = admin_manager


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前登录用户"""
    token = credentials.credentials
    # 检查 token 是否在黑名单中
    if is_token_blacklisted(db, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证已失效，请重新登录",
        )
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )
    employee_id = payload.get("sub")
    if not employee_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )

    # 使用显式 joinedload 确保角色及其权限都在一次查询中加载
    from sqlalchemy.orm import joinedload
    from app.models.role import Role

    user = (
        db.query(User)
        .options(joinedload(User.role_obj).joinedload(Role.permissions))
        .filter(User.employee_id == employee_id)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 注意：此处不再自动修复 role_id 不一致问题。
    # 原实现会在只读依赖中执行 db.flush() 且未 commit，导致每次请求重复触发、
    # 并在会话关闭后回滚（修复从未持久化），且读路径产生写操作存在隐患。
    # 角色与 role_id 的一致性改由管理操作（用户/角色编辑接口）统一保证。

    # 检查 token 是否在密码修改之前签发
    pwd_changed_at = payload.get("pwd_changed_at")
    if pwd_changed_at and user.password_changed_at:
        token_time = datetime.fromtimestamp(pwd_changed_at, tz=timezone.utc)
        # SQLite返回不带时区的datetime，数据库统一存储UTC时间，直接比较即可
        pwd_changed = user.password_changed_at
        if pwd_changed.tzinfo is None:
            from app.utils import BEIJING_TZ
            pwd_changed = pwd_changed.replace(tzinfo=BEIJING_TZ).astimezone(timezone.utc)
        elif pwd_changed.tzinfo != timezone.utc:
            pwd_changed = pwd_changed.astimezone(timezone.utc)
        if token_time < pwd_changed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="密码已修改，请重新登录",
            )
    return user



def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    """可选获取当前用户（用于某些公开接口）"""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    employee_id = payload.get("sub")
    if not employee_id:
        return None
    return db.query(User).filter(User.employee_id == employee_id).first()


# ==================== 自定义角色权限检查 ====================

def has_permission(user: User, permission_name: str) -> bool:
    """检查用户是否拥有指定权限（基于 role_obj 的权限表，不再硬编码角色名绕过）"""
    # 通过 role_obj 关联的权限表检查（admin_manager 拥有全部权限，自动覆盖）
    if user.role_obj:
        for p in user.role_obj.permissions:
            if p.name == permission_name:
                return True
    return False


def has_any_permission(user: User, *permission_names: str) -> bool:
    """检查用户是否拥有任意一个指定权限"""
    return any(has_permission(user, name) for name in permission_names)


def require_permission(permission_name: str):
    """依赖注入：要求指定权限"""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, permission_name):
            raise HTTPException(
                status_code=403,
                detail=f"缺少权限: {permission_name}"
            )
        return current_user
    return checker


def require_any_permission(*permission_names: str):
    """依赖注入：要求拥有任意一个指定权限"""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if not has_any_permission(current_user, *permission_names):
            raise HTTPException(
                status_code=403,
                detail="权限不足"
            )
        return current_user
    return checker


# ==================== 数据范围检查（基于角色的 department_scope / work_type_scope） ====================

def _get_role_dept_scope(user: User) -> str:
    """获取用户角色的科室数据范围（统一以 role_obj.department_scope 为准）"""
    if user.role_obj and user.role_obj.department_scope:
        return user.role_obj.department_scope
    return "own"


def _get_role_work_type_scope(user: User) -> list[str]:
    """获取用户角色的工种数据范围（返回工种列表，统一以 role_obj.work_type_scope 为准）"""
    if user.role_obj and user.role_obj.work_type_scope:
        ws = user.role_obj.work_type_scope
        if ws == "all":
            return []
        return [w.strip() for w in ws.split(",") if w.strip()]
    return []


def get_user_department_scope(user: User, db: Session) -> list[int]:
    """获取用户可管理的科室ID列表（基于 role.department_scope）

    - own: 仅 user.department 对应的科室
    - managed: user.department + UserDepartmentScope 关联的科室
    - all: 所有科室
    """
    from app.models.department import Department
    from sqlalchemy import func

    scope = _get_role_dept_scope(user)

    if scope == "all":
        all_dept_ids = db.query(Department.id).all()
        return [dept.id for dept in all_dept_ids]

    if scope == "managed":
        managed_dept_ids = []
        # 用户自身所属科室（精确匹配 + 空白修剪降级）
        if user.department:
            # [修复/问题26] 改用索引友好的精确匹配（内部含降级与脏数据规范化）
            own_dept = _find_department_by_name(db, user.department)
            if own_dept:
                managed_dept_ids.append(own_dept.id)
        # 自定义关联科室
        custom_dept_ids = db.query(UserDepartmentScope.department_id).filter(
            UserDepartmentScope.employee_id == user.employee_id
        ).all()
        managed_dept_ids.extend([dept_id for dept_id, in custom_dept_ids])
        return list(set(managed_dept_ids))

    # scope == "own": 仅本科室（同样加空白修剪）
    if user.department:
        # [修复/问题26] 改用索引友好的精确匹配（内部含降级与脏数据规范化）
        own_dept = _find_department_by_name(db, user.department)
        if own_dept:
            return [own_dept.id]
    return []


def get_user_work_type_scope(user: User) -> list[str]:
    """获取用户可管理的工种范围

    返回空列表 = 所有工种，否则为限制的工种列表
    """
    return _get_role_work_type_scope(user)


def _find_department_by_name(db: Session, name: str | None):
    """按名称查找科室（对应审计问题 26）。

    原实现一律用 `func.trim(Department.name)` / `func.lower(func.trim(...))`
    把列包在函数里再比较，SQLite 无法对 `Department.name` 使用索引，
    每次都退化为全表扫描；而该查找位于 `get_user_department_scope` /
    `has_department_access` 中，几乎每个请求的权限校验都会触发，开销被显著放大。

    改为：优先做**可命中索引的精确匹配**；未命中时才降级到 trim / 大小写无关匹配
    （兼容历史脏数据）；降级命中后顺带把名称规范化回写，
    让后续查询重新走索引路径。
    """
    from app.models.department import Department

    key = (name or "").strip()
    if not key:
        return None

    dept = db.query(Department).filter(Department.name == key).first()
    if dept is not None:
        return dept

    # 降级匹配：兼容库里残留的首尾空格 / 大小写差异
    from sqlalchemy import func
    dept = db.query(Department).filter(func.trim(Department.name) == key).first()
    if dept is None:
        dept = db.query(Department).filter(
            func.lower(func.trim(Department.name)) == func.lower(key)
        ).first()

    if dept is not None and dept.name != key:
        # 顺带规范化脏数据，使后续查询可直接命中精确匹配（走索引）
        try:
            dept.name = key
            db.flush()
        except Exception:
            db.rollback()
    return dept


def has_department_access(user: User, department_name: str, db: Session) -> bool:
    """检查用户是否可以访问指定科室（基于 role.department_scope）
    
    使用空白修剪的部门名称进行匹配，避免因末端空格导致匹配失败。
    """
    from sqlalchemy import func

    scope = _get_role_dept_scope(user)

    if scope == "all":
        return True

    if scope == "owned" or scope == "own":
        return (user.department or "").strip() == department_name.strip()

    if scope == "managed":
        managed_dept_ids = get_user_department_scope(user, db)
        if not managed_dept_ids:
            return False
        from app.models.department import Department
        # [修复/问题26] 精确匹配优先，避免 func.trim 使索引失效
        target_dept = _find_department_by_name(db, department_name)
        if not target_dept:
            return False
        return target_dept.id in managed_dept_ids

    return False


def can_access_staff(user: User, staff_work_type: str, staff_department: str, db: Session) -> bool:
    """统一人员数据访问检查：检查用户是否可以访问指定人员的数据

    返回 True 需要同时满足：
    1. 科室范围匹配（department_scope）
    2. 工种范围匹配（work_type_scope）
    """
    # 科室范围检查
    if not has_department_access(user, staff_department, db):
        return False

    # 工种范围检查
    work_types = get_user_work_type_scope(user)
    if work_types and staff_work_type not in work_types:
        return False

    return True


def can_manage_department_scope(user: User, db: Session) -> bool:
    """检查用户是否可以管理科室权限范围（配置自定义关联科室）

    科室管理员和超级管理员可以配置
    """
    scope = _get_role_dept_scope(user)
    return scope in ("all", "managed")
