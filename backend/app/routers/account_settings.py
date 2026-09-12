# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""账号设置汇总接口。

`GET /api/account-settings`（需 system.config）
一次性返回「默认口令模板 + 注册开关 + 口令预览示例」。

说明：
- 默认口令模板属敏感配置（决定所有新建账号的初始口令），
  故不建议走「任意登录用户可读」的 `GET /api/system-config/{key}`；
- 保存仍复用现有 `PUT /api/system-config/{key}`（同样要求 system.config）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PERM_SYSTEM_CONFIG, get_current_user, has_permission
from app.models.user import User
from app.services.system_config_service import (
    DEFAULT_PASSWORD_TEMPLATE_FALLBACK,
    DEFAULT_PASSWORD_TEMPLATE_KEY,
    REGISTRATION_ENABLED_KEY,
    get_config_value,
)

router = APIRouter(prefix="/api/account-settings", tags=["账号设置"])


@router.get("")
def get_account_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """账号设置汇总（需系统配置权限）"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")

    template = get_config_value(db, DEFAULT_PASSWORD_TEMPLATE_KEY, "")
    enabled = get_config_value(db, REGISTRATION_ENABLED_KEY, "0") == "1"
    effective = template.strip() or DEFAULT_PASSWORD_TEMPLATE_FALLBACK
    return {
        "default_password_template": template,
        "default_password_template_effective": effective,
        # 预览：把 {工号} 替换为示例工号，便于管理员确认规则效果
        "password_preview": effective.replace("{工号}", "905182"),
        "registration_enabled": enabled,
    }
