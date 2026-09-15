# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 添加 Request 导入，用于获取客户端 IP 地址记录到系统日志
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, has_permission, require_permission, PERM_SYSTEM_CONFIG
from app.models.user import User
from app.schemas.system_config import SystemConfigOut, SystemConfigUpdate
from app.services.system_config_service import (
    get_config, update_config, is_allowed_config_key, validate_config_value,
    SENSITIVE_READ_KEYS,
)
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：系统配置变更后通知超管
from app.services.modification_notify import notify_super_admins
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

router = APIRouter(prefix="/api/system-config", tags=["系统配置"])


@router.get("/{key}", response_model=SystemConfigOut)
def get_system_config(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取系统配置（所有登录用户可读；敏感项需 system.config）"""
    # [新增 2026-09-10] 默认口令模板等敏感配置仅对有系统配置权限者可见，
    # 否则任意登录用户都能读到「新建账号初始口令」的生成规则。
    if key in SENSITIVE_READ_KEYS and not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")
    config = get_config(db, key)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    return config


@router.put("/{key}", response_model=SystemConfigOut)
def update_system_config(
    key: str,
    data: SystemConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新系统配置（需要系统配置权限）"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")

    # [改进/S1] key 白名单校验：禁止创建/写入白名单外的任意配置项，
    # 防止凭空创建无限 key 干扰业务逻辑。
    if not is_allowed_config_key(key):
        raise HTTPException(status_code=400, detail=f"不支持的配置项: {key}")

    # [改进/S1 + 新增 2026-09-10] 按 key 校验并清洗配置值：
    # 名称类（org_name_cn/en）剔除 HTML 标签与控制字符并限长；
    # 其他（公告富文本等）仅做总长度上限校验，保持原有行为。
    try:
        normalized_value = validate_config_value(key, data.config_value)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    config = get_config(db, key)
    # [新增 2026-09-15] 变更前快照：config 是 ORM 实例，update_config 会就地改写字段，
    # 快照必须在更新前取值，否则站内信与留痕只能显示「新值 → 新值」。
    old_value = config.config_value if config else None

    if not config:
        config = update_config(
            db=db,
            key=key,
            value=normalized_value,
            updated_by=current_user.employee_id,
            description=data.description,
        )
    else:
        config = update_config(
            db=db,
            key=key,
            value=normalized_value,
            updated_by=current_user.employee_id,
        )

    # [改进/A2] 配置变更留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "config_update", current_user.employee_id,
                     detail=f"key={key}", target=key, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()

    # [新增 2026-09-15] 系统配置变更后补发站内信（事件：系统参数变更）：
    # 配置误改会全局生效（例如关掉注册审核开关、改默认口令生成规则），
    # 此前只写审计日志，超管无任何主动知会。
    try:
        def _clip(v, limit=80):
            """值摘要截断：公告富文本等长内容不能原样塞进站内信"""
            s = "" if v is None else str(v)
            return s if len(s) <= limit else s[:limit] + "…"

        new_value = config.config_value
        if old_value is None:
            change_text = f"新增配置项，值：{_clip(new_value)}"
        elif str(old_value) != str(new_value):
            change_text = f"{_clip(old_value)} → {_clip(new_value)}"
        else:
            change_text = "重复提交（值未变化）"

        obj_label = config.description or key
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"系统配置变更：{obj_label}",
            content=f"{modifier_name} 修改了系统配置「{obj_label}」：{change_text}（key: {key}）",
            related_type="system_alert",
            exclude_user_id=current_user.employee_id,
            event_code="system.config_changed",
            context={"操作人": modifier_name, "对象": obj_label, "变更内容": change_text},
        )
        db.commit()
    except Exception:
        db.rollback()
    return config