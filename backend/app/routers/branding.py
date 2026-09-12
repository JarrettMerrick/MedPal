# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""品牌设置路由：公开品牌读取 + 单位 Logo 上传/重置。

- `GET  /api/public/branding`  免登录：供登录页与前端全局读取单位名称/Logo；
- `POST /api/branding/logo`    需 system.config：上传/更换 Logo（multipart）；
- `DELETE /api/branding/logo`  需 system.config：重置为内置默认 Logo。

单位名称的保存复用现有 `PUT /api/system-config/{key}`（见 system_config.py），
不再新增冗余写端点。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PERM_SYSTEM_CONFIG, get_current_user, has_permission
from app.models.user import User
from app.services import branding_service
from app.services.audit_service import audit_action

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
    return result
