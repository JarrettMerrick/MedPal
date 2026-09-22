# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""品牌设置路由：公开品牌读取 + 单位 Logo 上传/重置。

- `GET  /api/public/branding`  免登录：供登录页与前端全局读取单位名称/Logo；
- `POST /api/branding/logo`    需 system.config：上传/更换 Logo（multipart）；
- `DELETE /api/branding/logo`  需 system.config：重置为内置默认 Logo。

单位名称的保存复用现有 `PUT /api/system-config/{key}`（见 system_config.py），
不再新增冗余写端点。
"""

import logging
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PERM_SYSTEM_CONFIG, get_current_user, has_permission
from app.models.user import User
from app.services import branding_service
from app.services.audit_service import audit_action
# [新增 2026-09-15] 站内信提醒：品牌设置（Logo）变更后通知超管
from app.services.modification_notify import notify_super_admins

logger = logging.getLogger(__name__)

router = APIRouter(tags=["品牌设置"])


@router.get("/api/public/branding")
def get_public_branding(db: Session = Depends(get_db)):
    """公开品牌信息（免登录）。

    登录页在未认证状态下即需要展示单位 Logo 与名称，而现有
    `GET /api/system-config/{key}` 需要登录、`/uploads` 亦受鉴权保护，
    故单独提供本公开只读接口（仅暴露单位名称与 Logo 路径，无敏感信息）。
    """
    return branding_service.get_branding(db)


@router.post("/api/branding/logo")
async def upload_brand_logo(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传/更换单位 Logo（需系统配置权限）。"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")

    content = await file.read()
    result = branding_service.save_logo(db, content, current_user.employee_id)

    # [A2] 品牌变更留痕
    audit_action(
        db, "brand_logo_upload", current_user.employee_id, request,
        detail=f"url={result.get('logo_url')}", target="org_logo",
    )

    # [新增 2026-09-15] 品牌变更后补发站内信（事件：品牌设置变更）：
    # 单位 Logo 会出现在登录页与全局页头（对外可见），被替换属重大外观变更，
    # 此前只写审计日志，超管无任何主动知会。
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        logo_url = str(result.get("logo_url") or "")
        file_name = logo_url.rsplit("/", 1)[-1] or "未知文件"
        notify_super_admins(
            db,
            title="品牌设置变更",
            content=f"{modifier_name} 上传/更换了单位 Logo（{file_name}）",
            related_type="system_alert",
            exclude_user_id=current_user.employee_id,
            event_code="branding.changed",
            context={
                "操作人": modifier_name,
                "对象": "Logo",
                "变更内容": f"上传/更换 Logo（{file_name}）",
            },
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return result


@router.delete("/api/branding/logo")
def reset_brand_logo(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重置单位 Logo 为内置默认图（需系统配置权限）。"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")

    result = branding_service.reset_logo(db, current_user.employee_id)

    # [A2] 品牌变更留痕
    audit_action(
        db, "brand_logo_reset", current_user.employee_id, request,
        detail="恢复内置默认 Logo", target="org_logo",
    )

    # [新增 2026-09-15] Logo 重置后补发站内信（事件：品牌设置变更）
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="品牌设置变更",
            content=f"{modifier_name} 将单位 Logo 重置为内置默认图",
            related_type="system_alert",
            exclude_user_id=current_user.employee_id,
            event_code="branding.changed",
            context={
                "操作人": modifier_name,
                "对象": "Logo",
                "变更内容": "重置为内置默认 Logo",
            },
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return result
