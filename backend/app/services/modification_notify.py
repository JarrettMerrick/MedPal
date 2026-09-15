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

[调整 2026-09-15] 接入可配置通知中心（系统设置 → 通知设置）：
调用点通过 event_code + context 声明「这属于哪个业务事件、文案里的变量是什么」，
实际文案与收件人由 `notification_center.emit` 按管理员配置决定；未配置时使用
注册表默认模板（= 本模块改造前的原文案）与 `resolve_modification_recipients`
的默认收件人，行为与改造前逐字一致。未传 event_code 的旧调用保持原样直发。
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
    event_code: str | None = None, context: dict | None = None,
    exclude_ids: list[str] | None = None,
    recipients: list[str] | None = None,
) -> int:
    """发送「信息修改」站内信，返回实际收件人数

    函数名保留（避免改动既有调用点），实际收件范围见模块 docstring。

    [调整 2026-09-15] 传入 event_code（+ context 模板变量）时统一走
    `notification_center.emit`：文案模板、事件开关、收件人规则均可由管理员在
    「系统设置 → 通知设置」中调整；`title` / `content` 作为变量缺失时的兜底文案。

    [新增 2026-09-15] exclude_ids：额外剔除的收件人工号，用于与「任务型通知」
    去重（例如审核人已收到「待审核」，报备通知就不再打扰他们）。

    [新增 2026-09-15] recipients：显式收件人工号，供「default_recipients_mode
    为 explicit」的事件使用（如本人改密后给本人的安全回执）；未传时由事件配置决定。
    """
    # ---- 兼容分支：未声明事件的旧调用，保持改造前行为 ----
    if not event_code:
        recipients = resolve_modification_recipients(db, department, exclude_user_id)
        if exclude_ids:
            blocked = {str(x) for x in exclude_ids if x}
            recipients = [r for r in recipients if str(r) not in blocked]
        if not recipients:
            return 0
        message_service.create_message(
            db, title=title, content=content, recipients=recipients,
            sender_id=None, msg_type="system",
            related_type=related_type, related_id=related_id,
        )
        return len(recipients)

    # 延迟导入：notification_center 在默认收件人解析时反向依赖本模块
    from app.services import notification_center

    return notification_center.emit(
        db, event_code,
        context=context or {},
        recipients=recipients,
        department=department,
        actor_id=exclude_user_id,
        exclude_ids=exclude_ids,
        related_type=related_type,
        related_id=related_id,
        fallback_title=title,
        fallback_content=content,
    )
