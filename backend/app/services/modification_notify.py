# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""修改提醒（站内信）工具

[调整 2026-09-11] 员工信息修改提醒改为通过**站内信**发送，收件人范围调整为
「超级管理员 + 相关科室管理员」（原先为所有拥有 staff.edit 权限者）：

    - 超级管理员：全部启用中的 admin_manager 账号；
    - 相关科室管理员：启用中的 dept_manager 账号，且其管辖科室范围
      （department_scope=managed，含本科室 + 关联科室）覆盖被修改人员所在科室；
    - 自动排除操作者本人（改动者本人无需收提醒），并自动去重；
    - 收件人规则由业务方传入 department（被修改人员所在科室）决定。

消息落库为站内信（msg_type=system），可在站内信收件箱中查看、标注与归档。
"""

from sqlalchemy.orm import Session

from app.dependencies import (
    ROLE_DEPT_MANAGER, ROLE_SUPER_ADMIN, has_department_access,
)
from app.models.user import User
from app.services import message_service


def resolve_modification_recipients(
    db: Session, department: str | None, exclude_user_id: str | None = None,
) -> list[str]:
    """解析「员工信息修改提醒」的收件人工号：超管 + 相关科室管理员"""
    users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    ids: list[str] = []
    for u in users:
        if u.role == ROLE_SUPER_ADMIN:
            ids.append(u.employee_id)
        elif u.role == ROLE_DEPT_MANAGER and department:
            # 管辖范围覆盖被修改人员所在科室（含 本科室 + 关联科室）
            if has_department_access(u, department, db):
                ids.append(u.employee_id)
    return message_service.normalize_recipients(ids, exclude_user_id)


def notify_super_admins(
    db: Session, title: str, content: str,
    related_type: str = None, related_id: int = None,
    department: str | None = None, exclude_user_id: str | None = None,
) -> int:
    """发送「信息修改」站内信，返回实际收件人数

    函数名保留（避免改动既有调用点），实际收件范围见模块 docstring。
    """
    recipients = resolve_modification_recipients(db, department, exclude_user_id)
    if not recipients:
        return 0
    message_service.create_message(
        db, title=title, content=content, recipients=recipients,
        sender_id=None, msg_type="system",
        related_type=related_type, related_id=related_id,
    )
    return len(recipients)
