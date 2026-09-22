# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库组织层路由：分类（只读，沿用标识分类）与标签（按维度分组）。

[调整 2026-09-17] 需求：文件管理中的分类**沿用「标识设置 → 标识分类」**，
且文件管理页**不提供分类的增删改入口** —— 分类维护统一在标识分类设置页
（/api/signage-categories）完成。因此本模块只保留分类的**只读**列表接口，
原 POST / PATCH / DELETE /api/file-categories 已移除。

权限：
    file.view  查看分类列表 / 标签列表
    file.edit  标签的创建、编辑、删除
               （分类维护已移至标识分类设置，需 signage.category 权限）
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user, require_any_permission, PERM_FILE_EDIT, PERM_FILE_VIEW,
)
from app.models.user import User
from app.schemas.design_file import FileTagCreate, FileTagUpdate
from app.services import file_taxonomy_service as tax
from app.services.audit_service import record_audit
from app.utils import get_client_ip

category_router = APIRouter(prefix="/api/file-categories", tags=["文件库-分类"])
tag_router = APIRouter(prefix="/api/file-tags", tags=["文件库-标签"])


# ==================== 分类（只读，数据源为标识分类） ====================

@category_router.get("")
def list_categories(
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """分类列表（含每个分类下的文件数）。

    数据源为「标识设置 → 标识分类」（signage_categories）；本接口只读：
    分类的增删改请在标识分类设置页维护（/api/signage-categories）。
    """
    return {"items": tax.build_category_list(db)}


# ==================== 标签 ====================

@tag_router.get("")
def list_tags(
    group_name: str | None = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """全部标签（可按维度过滤），含使用计数"""
    return {"items": tax.get_all_tags(db, group_name)}


@tag_router.post("")
def create_tag(
    payload: FileTagCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """新建标签（同一维度内不允许重名）"""
    try:
        tag = tax.create_tag(db, payload, current_user.employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_tag_create", current_user.employee_id,
        f"新建文件标签：{tag.group_name}/{tag.name}", target=str(tag.id),
        ip_address=get_client_ip(request) if request else None,
    )
    return {"id": tag.id, "name": tag.name, "group_name": tag.group_name, "color": tag.color}


@tag_router.patch("/{tag_id}")
def update_tag(
    tag_id: int,
    payload: FileTagUpdate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """编辑标签（重命名 / 改维度 / 改颜色）"""
    try:
        tag = tax.update_tag(db, tag_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_tag_update", current_user.employee_id,
        f"编辑文件标签：{tag.group_name}/{tag.name}", target=str(tag.id),
        ip_address=get_client_ip(request) if request else None,
    )
    return {"id": tag.id, "name": tag.name, "group_name": tag.group_name, "color": tag.color}


@tag_router.delete("/{tag_id}")
def delete_tag(
    tag_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """删除标签（同时解除其与文件的关联，不影响文件本身）"""
    try:
        result = tax.delete_tag(db, tag_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_tag_delete", current_user.employee_id,
        "删除文件标签", target=str(tag_id),
        ip_address=get_client_ip(request) if request else None,
    )
    return result
