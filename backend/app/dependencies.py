# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_department_scope import UserDepartmentScope
from app.services.auth_service import is_token_blacklisted
from app.utils import decode_token

# [新增 2026-09-21] 本模块此前**完全没有日志**：权限/范围校验是安全关键路径，
# 出现异常却无任何痕迹可查（代码质量审计曾指出 users.py / auth_service.py /
# dependencies.py 三个安全相关模块缺日志）。此处补齐模块级 logger。
import logging

logger = logging.getLogger(__name__)

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
# [新增 2026-09-15] 照片上传：控制能否上传人员形象照（正面 front / 侧面 side）。
# 适用范围：
#  - 本人上传自己的照片始终允许（基础能力，接口中单独放行，不校验本权限）；
#  - 为他人上传需本权限，且需通过 can_access_staff 科室/工种数据范围校验
#    （随角色的 department_scope / work_type_scope 生效：own=仅本人 / managed=管辖科室 / all=全部人员）；
#  - 删除照片不属于上传范畴，仍由 PERM_STAFF_EDIT 控制。
# 默认启用：超级管理员自动拥有；科室管理员默认拥有（存量角色由启动初始化一次性回填）。
PERM_STAFF_PHOTO_UPLOAD = "staff.photo_upload"
# [新增 2026-09-15] 修改历史（人员）：人员详情页「修改历史」入口与
# /api/audit/history/staff/* 接口的访问权限；默认仅超级管理员拥有，
# 可在「角色管理 → 人员管理」中按角色授予/回收（回收后入口与接口同时关闭）。
PERM_STAFF_VIEW_HISTORY = "staff.view_history"
# 科室管理
PERM_DEPT_VIEW = "department.view"
PERM_DEPT_CREATE = "department.create"
PERM_DEPT_EDIT = "department.edit"
PERM_DEPT_DELETE = "department.delete"
# [新增 2026-09-15] 修改历史（科室）：科室详情页「修改历史」入口与
# /api/audit/history/department/* 接口的访问权限；默认仅超级管理员拥有，
# 可在「角色管理 → 科室管理」中按角色授予/回收。
PERM_DEPT_VIEW_HISTORY = "department.view_history"
# 制度管理
PERM_REGULATION_VIEW = "regulation.view"
PERM_REGULATION_CREATE = "regulation.create"
PERM_REGULATION_EDIT = "regulation.edit"
PERM_REGULATION_DELETE = "regulation.delete"
# 标识管理
PERM_SIGNAGE_VIEW = "signage.view"
# [新增 2026-09-18] 标识总览：独立于 signage.view 的权限点。
# 需求：默认仅「科室管理员」与「超级管理员」拥有，普通员工不可见（导航菜单与页面访问一并受控）。
PERM_SIGNAGE_OVERVIEW = "signage.overview"
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
# [新增 2026-09-17] 文件库（设计文件集中管理：分类 / 标签 / 版本 / 回收站 / 标准设计文件）
PERM_FILE_VIEW = "file.view"                        # 文件库 - 浏览 / 预览 / 下载
PERM_FILE_UPLOAD = "file.upload"                    # 文件库 - 上传文件
PERM_FILE_EDIT = "file.edit"                        # 文件库 - 编辑（改名/分类/标签/标准标记、维护分类与标签）
PERM_FILE_DELETE = "file.delete"                    # 文件库 - 删除（含批量与彻底删除）
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
# [新增 2026-09-14] 功能级权限点：控制该角色能否访问对应功能。
# 与「系统设置 → 功能开关」构成两层控制，两者都通过才放行：
#   1) 功能开关（单位级）：整个单位是否启用该功能；
#   2) 本权限点（角色级）：该角色是否可访问该功能。
# 功能内部的具体操作仍由原有细粒度权限（message.send / signage.create 等）控制。
# [调整 2026-09-14] 由逐功能拆分（feature.messages / feature.signage / feature.regulation）
# 合并为**单一**权限点：一个角色要么可访问全部受功能开关管控的模块，要么全部不可访问。
# 具体模块的启停仍由「系统设置 → 功能开关」的单位级开关分别控制。
PERM_FEATURE_ACCESS = "feature.access"
# [新增 2026-09-15] 通知设置权限点：控制角色能否访问「系统设置 → 通知设置」
# （配置系统站内信的事件开关 / 文案模板 / 收件人范围）。
# 与 PERM_FEATURE_ACCESS 同属「系统设置」分类；此前通知设置复用 system.config，
# 现拆分为独立权限项，便于按角色单独授权；存量角色由启动初始化一次性回填，
# 保证升级后访问范围不缩水。
PERM_FEATURE_NOTIFICATION = "feature.notification"

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
    # [修复] 统一走 is_token_stale_after_password_change（UTC 比较 + 缺失内嵌值按失效处理），
    # 原实现存在漏判与 8 小时时区偏移，详见 utils 中该函数说明。
    from app.utils import is_token_stale_after_password_change
    if is_token_stale_after_password_change(payload.get("pwd_changed_at"), user.password_changed_at):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码已修改，请重新登录",
        )
    return user



def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    """可选获取当前用户（用于某些公开接口）。

    [修复] 与 get_current_user 口径保持一致：黑名单 / 账号启用 / 改密失效校验。
    原实现只解析 token 就返回用户，导致「已登出的 access token」与「改密前签发的旧
    token」在依赖本函数的接口（如导出包下载 download_package）上仍被视为有效，
    改密/登出后仍可继续下载导出包等敏感数据，直至令牌自然过期。
    """
    if credentials is None:
        return None
    token = credentials.credentials
    if is_token_blacklisted(db, token):
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    employee_id = payload.get("sub")
    if not employee_id:
        return None
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user or not user.is_active:
        return None
    from app.utils import is_token_stale_after_password_change
    if is_token_stale_after_password_change(payload.get("pwd_changed_at"), user.password_changed_at):
        return None
    return user


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


def require_feature_enabled(feature: str):
    """依赖注入：要求指定功能已被管理员启用（系统设置 → 功能开关）。

    [新增 2026-09-14] 功能开关是**单位级**控制，与角色级权限点（feature.*）互为两层：
    功能一旦关闭，全单位均不可用（接口直接 403），与该角色的权限配置无关；
    且关闭后功能内部的后台任务产生的数据只是暂不可见，不会丢失。

    用法：挂在 APIRouter 上整体生效，避免逐个接口漏挂——
        router = APIRouter(prefix="/api/messages",
                           dependencies=[Depends(require_feature_enabled("messages"))])
    """
    from app.services.system_config_service import FEATURE_LABELS, get_feature_flags

    def checker(db: Session = Depends(get_db)) -> None:
        if not get_feature_flags(db).get(feature, True):
            label = FEATURE_LABELS.get(feature, feature)
            raise HTTPException(status_code=403, detail=f"「{label}」功能已被管理员关闭")

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


def resolve_department_filter(user: User, db: Session) -> tuple[str | None, bool]:
    """解析用户的科室数据范围，生成列表查询用的过滤串。

    [新增 2026-09-21 / 代码质量审计 Q-6] 此前这套「取 department_scope →
    查用户关联科室 → 拼 "||" 过滤串 → 无科室则返回空结果」的逻辑在
    **四处各写了一遍**：routers/staff.py（列表、离职列表）、routers/users.py（用户列表）、
    routers/data_io.py（数据核对）。

    这是**安全相关**的重复：过滤逻辑一旦在某处漏改（如新增了一种 scope 取值、
    或改用新的关联表），那一处就会静默越权或漏查。且每新增一个列表接口都会
    继续复制第五份。故统一收敛到本函数，供各列表类接口复用。

    返回:
        (department_filter, is_empty)
        - department_filter: "内科||外科" 形式的过滤串；None 表示**不限科室**
          （role.department_scope == "all"）。
        - is_empty: True 表示该用户**没有任何可访问的科室** ——
          调用方应直接返回空列表（而不是不加过滤地查全量，那会造成越权）。

    说明:
        返回值刻意用「过滤串」而非科室 ID 列表 —— 因为 staff.department 是自由
        文本字段，历史数据中可能存在 departments 表中没有的名称（如"普外科/甲乳外科"），
        按 ID 过滤会漏掉这些人。用 "||" 拼接的名称串由 service 层按文本 LIKE 匹配，
        与既有行为一致。
    """
    scope = _get_role_dept_scope(user)
    if scope == "all":
        return None, False

    managed_dept_ids = get_user_department_scope(user, db)
    if not managed_dept_ids:
        return None, True

    from app.models.department import Department
    dept_names = [
        d.name for d in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()
    ]
    if not dept_names:
        return None, True

    return "||".join(dept_names), False


def check_signage_department_access(db: Session, user: User, signage) -> None:
    """校验用户是否位于目标标识的科室数据范围内（越界抛 403）。

    [新增 2026-09-17] 由 routers/signages.py 中的同名私有函数提取为公共函数：
    标识列表接口早就按 allowed_department_ids 做了科室过滤，但详情 / 历史 / 照片 /
    巡检 / 维修等读路径普遍只校验权限点、漏挂科室范围，导致受限角色（如
    department_scope=own 的科室账号）可通过 ID/编码枚举读取其他科室的标识数据。
    统一收敛到本函数，供 signages / signage_alerts / 其它标识模块复用，避免再次漏挂。

    未归属科室的标识不做范围限制（保持原有行为）。

    [修正 2026-09-21 / 代码质量审计 Q-1] 原实现在校验抛异常时**静默 return 放行**
    （fail-open），并附注"由端点的权限点兜底"。这条附注是不成立的：
    权限点只回答"这个角色能不能用标识模块"，**不回答"能不能看这个科室的数据"**
    —— 后者正是本函数唯一的职责。因此校验异常等于范围限制被整体跳过，
    受限角色（department_scope=own/managed）可借由触发异常读取其他科室数据。

    现改为 **fail-safe**：异常时记 ERROR 日志并按拒绝处理。
    代价是数据库异常期间相关接口会返回 403 而非"勉强可用"，
    但这个代价是必要的 —— 数据范围校验被绕过属于越权，其严重性高于可用性。
    真正需要可用性时应当修复异常的根因，而不是让校验失效。
    """
    dept = getattr(signage, "department", None)
    dept_name = getattr(dept, "name", None) if dept is not None else None
    if not dept_name:
        return
    try:
        if has_department_access(user, dept_name, db):
            return
    except Exception as e:
        # 拒绝优先：校验无法完成时不得放行
        logger.error(
            "签名标识科室范围校验异常，已按拒绝处理（fail-safe）: "
            "signage_id=%s, dept=%s, operator=%s, err=%s: %s",
            getattr(signage, "id", None), dept_name,
            getattr(user, "employee_id", None), type(e).__name__, e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="数据范围校验失败，已拒绝访问",
        )
    raise HTTPException(status_code=403, detail="无权访问其他科室的标识")


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
