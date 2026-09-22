# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""人员信息变更审核路由。

[新增 2026-09-11] 人员信息「立即生效 + 追认审核」的审核侧接口：

- `GET  /api/staff-changes`                    需 staff.approve：待我审核的变更
- `GET  /api/staff-changes/pending-count`      需 staff.approve：待审数量（菜单角标）
- `POST /api/staff-changes/{id}/approve`       需 staff.approve：通过（追认）
- `POST /api/staff-changes/{id}/reject`        需 staff.approve：驳回（回滚）
- `GET  /api/staff-changes/mine`               登录即可：我提交的变更（可撤回）
- `POST /api/staff-changes/{id}/cancel`        登录即可：撤回自己提交的变更
- `GET  /api/staff-changes/by-staff/{工号}`     需 staff.view + 数据范围：某人的待审提示

审核范围：超级管理员可审全部（含超时升级件）；科室管理员仅审核**管辖科室**的
「科室级」变更，且任何情况下都不能审核自己提交的变更（禁止自审）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    PERM_STAFF_APPROVE, PERM_STAFF_VIEW,
    can_access_staff, get_current_user, has_permission,
)
from app.models.staff_change import STATUS_PENDING, StaffChangeRequest
from app.models.user import User
from app.schemas.staff_change import StaffChangeReject
from app.services import staff_change_service
from app.services.audit_service import audit_action
from app.services.staff_service import get_staff

router = APIRouter(prefix="/api/staff-changes", tags=["人员信息变更审核"])


def _require_review_permission(user: User) -> None:
    if not has_permission(user, PERM_STAFF_APPROVE):
        raise HTTPException(status_code=403, detail="权限不足，无法审核人员信息变更")


def _get_or_404(db: Session, change_id: int) -> StaffChangeRequest:
    req = db.query(StaffChangeRequest).filter(StaffChangeRequest.id == change_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="变更申请不存在")
    return req


# ---------------- 审核列表 ----------------


@router.get("")
def list_staff_changes(
    status: str = Query(STATUS_PENDING, description="pending/approved/rejected/cancelled，空表示全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """待我审核的人员信息变更（超管=全部；科室管理员=管辖科室的科室级变更）"""
    _require_review_permission(current_user)
    staff_change_service.sweep_overdue(db)  # 惰性扫描超时件（提醒/升级）
    items, total = staff_change_service.list_reviewable(
        db, current_user, status=status, page=page, page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [staff_change_service.serialize(i, current_user, db) for i in items],
    }


@router.get("/pending-count")
def get_pending_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """待审数量（供菜单角标）"""
    _require_review_permission(current_user)
    staff_change_service.sweep_overdue(db)
    return {"count": staff_change_service.pending_count(db, current_user)}


@router.get("/mine")
def list_my_changes(
    status: str | None = Query(None, description="不传表示全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我提交的变更（个人中心「我的提交」，可在此撤回待审变更）"""
    items, total = staff_change_service.list_mine(
        db, current_user, status=status, page=page, page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [staff_change_service.serialize(i, current_user, db) for i in items],
    }


@router.get("/by-staff/{employee_id}")
def list_changes_by_staff(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """某人员的待审变更（详情页/列表页「待审核」提示）。

    仅需 staff.view + 数据范围：未审核提示与审核按钮对**所有可见者**展示，
    但 `can_review` 为 false 时前端只提示、不给操作。
    """
    if not has_permission(current_user, PERM_STAFF_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    if employee_id != current_user.employee_id:
        staff = get_staff(db, employee_id)
        if not staff:
            raise HTTPException(status_code=404, detail="人员不存在")
        if not can_access_staff(current_user, staff.work_type, staff.department, db):
            raise HTTPException(status_code=403, detail="无权查看该人员信息")

    rows = staff_change_service.pending_map(db, [employee_id]).get(employee_id, [])
    return {
        "total": len(rows),
        "items": [staff_change_service.serialize(i, current_user, db) for i in rows],
    }


# ---------------- 审核操作 ----------------


@router.post("/{change_id}/approve")
def approve_staff_change(
    change_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审核通过（追认）：延迟生效字段此刻写入主表"""
    _require_review_permission(current_user)
    req = _get_or_404(db, change_id)
    try:
        result = staff_change_service.approve_request(db, req, current_user)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "staff_change_approve", current_user.employee_id, request,
                 detail=f"change_id={change_id}, employee_id={req.employee_id}",
                 target=req.employee_id)
    return result


@router.post("/{change_id}/reject")
def reject_staff_change(
    change_id: int,
    payload: StaffChangeReject,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """驳回（回滚到提交前旧值；若期间他人又改过则只提示、不覆盖）"""
    _require_review_permission(current_user)
    req = _get_or_404(db, change_id)
    try:
        result = staff_change_service.reject_request(db, req, current_user, payload.reason)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "staff_change_reject", current_user.employee_id, request,
                 detail=f"change_id={change_id}, employee_id={req.employee_id}, "
                        f"reason={payload.reason}, rolled_back={result.get('rolled_back')}",
                 target=req.employee_id)
    return result


@router.post("/{change_id}/cancel")
def cancel_staff_change(
    change_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """撤回自己提交的待审变更（回滚语义与驳回一致）"""
    req = _get_or_404(db, change_id)
    try:
        result = staff_change_service.cancel_request(db, req, current_user)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "staff_change_cancel", current_user.employee_id, request,
                 detail=f"change_id={change_id}, employee_id={req.employee_id}",
                 target=req.employee_id)
    return result
