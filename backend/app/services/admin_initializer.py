# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""默认管理员账号初始化 + 「系统必须始终保留至少一个超级管理员」保障

业务背景：
    - 系统预设了 admin_manager / dept_manager / employee 三个角色及全部权限，
      但未创建任何与角色绑定的用户，导致首次部署后无账号可登录。
    - 本模块负责在每次启动时保证「系统中至少存在一个超级管理员」：
        · 首次部署 / 库中无任何超级管理员 → 自动创建 admin 账号；
        · 已存在超级管理员 → 直接跳过，绝不覆盖或改动既有账号。
    - 超级管理员账号（含 admin）允许被删除（见 routers/users.py），但删除
      「最后一个超级管理员」会被拒绝，因此本模块的「补齐」只作为兜底场景：
      从旧备份恢复、DBA 手工改库、角色被误改等导致超管数量归零时，重启即自动修复。

数据流向：
    main.py startup() → init_default_roles()（先建角色/权限）
    → init_default_configs() → init_default_admin()（确保至少一个超级管理员）
    → 登录后 enforce_password_change 中间件强制其修改密码

注意事项：
    - 幂等：已有超级管理员时不创建、不修改任何账号，重复启动无副作用。
    - 首次创建的账号为 admin / MedPal@admin，且 must_change_password=True，
      首次登录强制修改密码，避免初始口令长期暴露。
    - 工号 admin 已被占用（但其角色不是超级管理员）时，就地将该账号提升为
      超级管理员，且**不重置其密码**——避免静默改掉使用者已知口令导致无法登录。
"""

import logging

from sqlalchemy.orm import Session

from app.dependencies import ROLE_SUPER_ADMIN
from app.models.user import User
from app.utils import hash_password

logger = logging.getLogger("admin_initializer")

# 默认管理员账号信息（硬编码兜底值，配合首登强制改密收敛风险）
DEFAULT_ADMIN_ID = "admin"                  # 工号（登录账号）
DEFAULT_ADMIN_NAME = "系统管理员"           # 显示名称
DEFAULT_ADMIN_PASSWORD = "MedPal@admin"     # 初始口令（首次登录强制修改）


def count_super_admins(db: Session) -> int:
    """统计系统中的超级管理员账号数量（不区分启用状态）。

    供「至少保留一个超级管理员」的删除/禁用/降级校验复用。
    """
    return db.query(User).filter(User.role == ROLE_SUPER_ADMIN).count()


def init_default_admin(db: Session) -> bool:
    """确保系统中至少存在一个超级管理员账号（幂等）。

    返回是否发生了「创建 / 补齐」动作。
    """
    existing = count_super_admins(db)
    if existing > 0:
        logger.info("已存在 %d 个超级管理员账号，跳过默认管理员创建", existing)
        return False

    from app.models.role import Role

    admin_role = db.query(Role).filter(Role.name == ROLE_SUPER_ADMIN).first()
    if not admin_role:
        logger.warning("%s 角色不存在，无法创建默认管理员", ROLE_SUPER_ADMIN)
        return False

    # 场景一：工号 admin 已被占用（但其角色不是超级管理员）
    # → 就地提升为超级管理员，不重置密码（避免静默改掉使用者已知口令）
    occupied = db.query(User).filter(User.employee_id == DEFAULT_ADMIN_ID).first()
    if occupied is not None:
        occupied.role = ROLE_SUPER_ADMIN
        occupied.role_id = admin_role.id
        occupied.is_active = True
        logger.warning(
            "系统中已无超级管理员，已将既有账号 %s 提升为超级管理员（密码保持不变）",
            DEFAULT_ADMIN_ID,
        )
        return True

    # 场景二：正常创建全新管理员账号
    admin = User(
        employee_id=DEFAULT_ADMIN_ID,
        name=DEFAULT_ADMIN_NAME,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        role=ROLE_SUPER_ADMIN,
        role_id=admin_role.id,
        must_change_password=True,   # 首登强制改密，避免初始口令长期暴露
        is_active=True,
    )
    db.add(admin)
    logger.info(
        "已自动创建默认管理员: 工号=%s，初始口令=%s（首次登录须修改密码）",
        DEFAULT_ADMIN_ID, DEFAULT_ADMIN_PASSWORD,
    )
    return True
