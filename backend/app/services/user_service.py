# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.models.role import Role
from app.schemas.user import UserCreate, UserUpdate
from app.utils import hash_password
# [修复/问题18] 强默认口令（配置值为弱口令时自动随机生成）
from app.services.auth_service import get_default_password


def get_user_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    role: Optional[str] = None,
    department_filter: Optional[str] = None,
    has_profile: Optional[bool] = None,
) -> tuple[list[User], int]:
    """获取用户列表（分页）。

    新增 has_profile 筛选：
    - True  → 只返回 staff 表中有对应记录的用户（有简介）
    - False → 只返回 staff 表中无对应记录的用户（无简介）
    """
    from app.models.staff import Staff
    query = db.query(User)
    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            User.employee_id.like(like_pattern) | User.name.like(like_pattern)
        )
    if role:
        query = query.filter(User.role == role)
    if department_filter:
        # department_filter 可能是逗号分隔的多个科室名称
        dept_list = [d.strip() for d in department_filter.split("||") if d.strip()]
        if dept_list:
            query = query.filter(User.department.in_(dept_list))
    # [新增] 按 staff 简介状态过滤
    if has_profile is not None:
        # 子查询：所有在 staff 表中有记录的 employee_id
        staff_ids = db.query(Staff.employee_id).subquery()
        if has_profile:
            query = query.filter(User.employee_id.in_(staff_ids))
        else:
            query = query.filter(User.employee_id.notin_(staff_ids))
    total = query.count()
    query = query.order_by(User.employee_id).offset(
        (page - 1) * page_size
    ).limit(page_size)
    return query.all(), total


def get_user(db: Session, employee_id: str) -> User | None:
    """按工号查询用户。

    [修复] 兼容工号含前后不可见字符（空格/制表符）的历史脏数据：
    1. 对输入工号 strip；
    2. 精确匹配未命中时，兜底用 trim(employee_id) 比较。
    """
    from sqlalchemy import func
    key = (employee_id or "").strip()
    if not key:
        return None
    row = db.query(User).filter(User.employee_id == key).first()
    if row:
        return row
    # 兜底：忽略存储值的前后空白匹配
    return db.query(User).filter(func.trim(User.employee_id) == key).first()


def create_user(db: Session, user_in: UserCreate) -> User:
    # [改进] 校验 role 名称是否对应真实的 Role 记录
    role_record = db.query(Role).filter(Role.name == user_in.role).first()
    if not role_record:
        raise ValueError(f"无效角色: '{user_in.role}'，数据库中不存在该角色")

    # [改进] 若未传 role_id，则按 role 名称反查，保证 role_id 与 role 一致
    role_id = user_in.role_id
    if role_id is None:
        role_id = role_record.id
    # [修复 2026-09-10] 兜底同步有效角色名：
    # ORM 的 @validates('role') 依据启动时同步的集合校验角色名，
    # 若角色是在本进程运行期间新建的，集合可能过期而把合法角色误判为
    # 「无效角色名」。这里按数据库实际角色重新同步一次，保证判定准确。
    from app.services.role_initializer import sync_valid_role_names
    sync_valid_role_names(db)

    user = User(
        employee_id=user_in.employee_id.strip(),
        name=user_in.name,
        # [调整 2026-09-10] 初始口令按「账号设置」中的模板生成（支持 {工号} 占位符）
        password_hash=hash_password(get_default_password(db, user_in.employee_id.strip())),
        role=user_in.role,
        role_id=role_id,
        department=user_in.department,
        user_type=user_in.user_type,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    
    # [移除] 不再自动创建 staff 记录（原"方案B：自动创建确保数据一致性"）。
    # 新逻辑：人员管理独立维护，用户管理创建账号时可手动勾选"同步到人员管理"。
    
    return user


def update_user(db: Session, employee_id: str, user_in: UserUpdate) -> User | None:
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        return None
    update_data = user_in.model_dump(exclude_unset=True)
    # [修复 2026-09-10] 涉及角色变更时兜底同步有效角色名（同 create_user）
    if update_data.get("role"):
        from app.services.role_initializer import sync_valid_role_names
        sync_valid_role_names(db)
    for field, value in update_data.items():
        setattr(user, field, value)
    # 如果更新了 role 但没传 role_id，自动解析对应的 role_id
    if "role" in update_data and "role_id" not in update_data:
        from app.models.role import Role
        # [改进] 校验更新的 role 名称是否存在
        role_record = db.query(Role).filter(Role.name == user.role).first()
        if not role_record:
            raise ValueError(f"无效角色: '{user.role}'，数据库中不存在该角色")
        user.role_id = role_record.id
    # 如果传了 role_id 但没传 role，自动反查 role 名称
    if "role_id" in update_data and "role" not in update_data:
        from app.models.role import Role
        role_record = db.query(Role).filter(Role.id == user.role_id).first()
        if role_record:
            user.role = role_record.name
    db.flush()
    return user
