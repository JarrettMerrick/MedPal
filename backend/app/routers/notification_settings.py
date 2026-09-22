# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""通知设置路由（系统设置 → 通知设置）

[新增 2026-09-15] 可配置通知中心的管理入口：

- `GET  /api/notification-settings`                   设置页汇总（事件清单 + 生效配置 + 默认值）
- `GET  /api/notification-settings/options`           自定义收件人的可选角色 / 科室 / 权限
- `PUT  /api/notification-settings/{code}`            保存某事件的开关 / 文案 / 收件人规则
- `POST /api/notification-settings/{code}/reset`      恢复某事件的默认配置
- `POST /api/notification-settings/{code}/preview`    干跑预览（不发送）
- `POST /api/notification-settings/{code}/test`       向本人发送一封测试站内信

权限：使用独立权限点 `feature.notification`（角色管理中位于「系统设置」分类下的
「通知设置」项；存量角色由启动初始化一次性回填，升级后访问范围不缩水）。
保存 / 恢复 / 测试均写入审计留痕。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PERM_FEATURE_NOTIFICATION, get_current_user, has_permission
from app.models.department import Department
from app.models.role import Permission, Role
from app.models.user import User
from app.schemas.notification import NotificationPreviewRequest, NotificationRuleUpdate
from app.services import notification_center
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：通知设置本身被修改后告知超管（防止悄悄关掉提醒）
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip

router = APIRouter(tags=["通知设置"])


def _ensure_permission(current_user: User) -> None:
    """统一权限校验：需 feature.notification（「系统设置 → 通知设置」权限项）"""
    if not has_permission(current_user, PERM_FEATURE_NOTIFICATION):
        raise HTTPException(status_code=403, detail="权限不足")


def _as_dict(model) -> dict | None:
    """pydantic 模型转 dict（兼容 v1 的 .dict() 与 v2 的 .model_dump()）"""
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _audit(db: Session, request: Request, current_user: User, code: str, detail: str) -> None:
    """写审计留痕（失败不影响业务结果，仅记录日志）"""
    try:
        record_audit(
            db, "config_update", current_user.employee_id,
            detail=detail, target=code, ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()

    # [新增 2026-09-15] 通知设置变更后补发站内信（事件：通知设置本身被修改）：
    # 防止「先悄悄关掉提醒、再执行敏感操作」——通知设置的每次改动都必须让超管看见。
    # 发送测试站内信属个人操作（只进本人收件箱），不触发该通知以避免噪音。
    if "测试" in (detail or ""):
        return
    try:
        event = notification_center.get_event(code)
        obj_label = (event or {}).get("label") or code
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"通知设置被修改：{obj_label}",
            content=f"{modifier_name} 修改了通知设置「{obj_label}」：{detail}",
            related_type="system_alert",
            exclude_user_id=current_user.employee_id,
            event_code="notification.settings_changed",
            context={
                "操作人": modifier_name,
                "对象": obj_label,
                "变更内容": detail or "更新通知配置",
            },
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("/api/notification-settings")
def get_notification_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通知设置汇总：全部事件 + 生效配置 + 注册表默认值（需「通知设置」权限）"""
    _ensure_permission(current_user)
    return {
        **notification_center.build_settings(db),
        "permission": PERM_FEATURE_NOTIFICATION,
    }


@router.get("/api/notification-settings/options")
def get_recipient_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自定义收件人规则的候选项：角色 / 科室 / 权限（需「通知设置」权限）"""
    _ensure_permission(current_user)

    roles = db.query(Role).order_by(Role.name).all()
    departments = db.query(Department).order_by(Department.name).all()
    permissions = db.query(Permission).order_by(Permission.category, Permission.name).all()

    return {
        "roles": [{"value": r.name, "label": r.display_name} for r in roles],
        "departments": [{"value": d.name, "label": d.name} for d in departments],
        "permissions": [
            {"value": p.name, "label": p.display_name, "category": p.category}
            for p in permissions
        ],
    }


@router.put("/api/notification-settings/{code}")
def update_notification_rule(
    code: str,
    data: NotificationRuleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存某事件的规则覆盖（开关 / 文案 / 收件人）；文案留空即恢复默认模板"""
    _ensure_permission(current_user)

    try:
        cfg = notification_center.save_rule(
            db, code,
            updated_by=current_user.employee_id,
            enabled=data.enabled,
            title_template=data.title_template,
            content_template=data.content_template,
            recipient_mode=data.recipient_mode,
            recipient_rules=_as_dict(data.recipient_rules),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    _audit(
        db, request, current_user, code,
        detail=f"通知规则更新：enabled={data.enabled} mode={data.recipient_mode}",
    )
    return {
        "ok": True,
        "event_code": code,
        "enabled": cfg["enabled"],
        "customized": cfg["customized"],
    }


@router.post("/api/notification-settings/{code}/reset")
def reset_notification_rule(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复某事件的默认配置（删除覆盖行，回到注册表默认）"""
    _ensure_permission(current_user)

    if not notification_center.get_event(code):
        raise HTTPException(status_code=404, detail="未知的通知事件")

    removed = notification_center.reset_rule(db, code)
    _audit(db, request, current_user, code, detail="恢复通知默认配置")
    return {"ok": True, "event_code": code, "removed": removed}


@router.post("/api/notification-settings/{code}/preview")
def preview_notification_rule(
    code: str,
    data: NotificationPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """干跑预览：按（可能的）未保存草稿渲染文案并解析收件人，不发送"""
    _ensure_permission(current_user)

    try:
        return notification_center.preview(
            db, code,
            title_template=data.title_template,
            content_template=data.content_template,
            recipient_mode=data.recipient_mode,
            recipient_rules=_as_dict(data.recipient_rules),
            department=data.department,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/notification-settings/{code}/test")
def send_test_notification(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向当前管理员本人发送一封测试站内信（忽略事件开关，便于开启前确认效果）"""
    _ensure_permission(current_user)

    try:
        result = notification_center.send_test(db, code, current_user.employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _audit(db, request, current_user, code, detail="发送通知测试站内信")
    return {"ok": True, **result}
