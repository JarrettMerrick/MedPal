# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""账号注册路由：免登录的注册入口（选项/提交）+ 需权限的审核（列表/通过/驳回）。

- `GET  /api/public/registration/options`  免登录：返回开关、工种、科室选项
- `POST /api/public/registration`          免登录：提交注册申请（IP 限流）
- `GET  /api/registration-requests`              需 user.approve：待审/已审列表
- `GET  /api/registration-requests/pending-count` 需 user.approve：待审数量
- `POST /api/registration-requests/{id}/approve`  需 user.approve：通过
- `POST /api/registration-requests/{id}/reject`   需 user.approve：驳回

审核范围：超级管理员（department_scope=all）可审全部；科室管理员仅能审管辖科室。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    PERM_USER_APPROVE,
    get_current_user,
    get_user_department_scope,
    has_permission,
)
from app.models.department import Department
from app.models.registration_request import RegistrationRequest
from app.models.user import User
from app.schemas.registration import RegistrationReject, RegistrationSubmit
from app.services import registration_service
from app.services.audit_service import audit_action
from app.services.auth_service import is_rate_limited, record_rate_attempt
from app.utils import get_client_ip

router = APIRouter(tags=["账号注册"])


# ---------------- 内部工具 ----------------

def _allowed_departments(db: Session, user: User) -> list[str] | None:
    """审核可见的科室范围：None=不限（超管）；[]=无任何科室。"""
    scope = user.role_obj.department_scope if user.role_obj else "own"
    if scope == "all":
        return None
    dept_ids = get_user_department_scope(user, db)
    if not dept_ids:
        return []
    return [d.name for d in db.query(Department).filter(Department.id.in_(dept_ids)).all()]


def _require_review_permission(user: User) -> None:
    if not has_permission(user, PERM_USER_APPROVE):
        raise HTTPException(status_code=403, detail="权限不足")


def _get_request_or_404(db: Session, req_id: int) -> RegistrationRequest:
    req = db.query(RegistrationRequest).filter(RegistrationRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="申请不存在")
    return req


def _check_in_scope(req: RegistrationRequest, allowed: list[str] | None) -> None:
    if allowed is not None and req.department not in allowed:
        raise HTTPException(status_code=403, detail="无权审核其他科室的申请")


# ---------------- 公开接口（免登录） ----------------

@router.get("/api/public/registration/options")
def get_registration_options(db: Session = Depends(get_db)):
    """登录页注册入口所需的公开选项（是否开放 / 工种 / 科室名称）。"""
    return registration_service.get_public_options(db)


@router.post("/api/public/registration")
def submit_registration(
    payload: RegistrationSubmit,
    request: Request,
    db: Session = Depends(get_db),
):
    """提交注册申请（免登录）。带 IP 限流，防批量灌水。"""
    ip = get_client_ip(request)
    if is_rate_limited(db, ip, "registration"):
        raise HTTPException(status_code=429, detail="提交过于频繁，请稍后再试")
    record_rate_attempt(db, ip, "registration")

    try:
        result = registration_service.submit_registration(
            db,
            employee_id=payload.employee_id,
            name=payload.name,
            password=payload.password,
            work_type=payload.work_type,
            department=payload.department,
            ip_address=ip,
        )
    except ValueError as e:
        db.commit()  # 保留本次限流计数
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "registration_submit", payload.employee_id, request,
                 detail=f"dept={payload.department}, work_type={payload.work_type}",
                 target=payload.employee_id)
    return result


# ---------------- 审核接口（需 user.approve） ----------------

@router.get("/api/registration-requests")
def list_registration_requests(
    status: str = Query("pending", description="pending/approved/rejected，空表示全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """注册申请列表（受科室数据范围限制）"""
    _require_review_permission(current_user)
    allowed = _allowed_departments(db, current_user)
    items, total = registration_service.list_requests(
        db, status=status, page=page, page_size=page_size, allowed_departments=allowed,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [registration_service.serialize(i) for i in items],
    }


@router.get("/api/registration-requests/pending-count")
def get_pending_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """待审数量（供菜单角标）"""
    _require_review_permission(current_user)
    allowed = _allowed_departments(db, current_user)
    return {"count": registration_service.pending_count(db, allowed)}


@router.post("/api/registration-requests/{req_id}/approve")
def approve_registration_request(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审核通过：创建可登录账号 + 人员档案"""
    _require_review_permission(current_user)
    req = _get_request_or_404(db, req_id)
    _check_in_scope(req, _allowed_departments(db, current_user))
    try:
        registration_service.approve_request(db, req, current_user.employee_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "registration_approve", current_user.employee_id, request,
                 detail=f"employee_id={req.employee_id}, dept={req.department}",
                 target=req.employee_id)
    return {"message": "已通过，账号已启用", "employee_id": req.employee_id}


@router.post("/api/registration-requests/{req_id}/reject")
def reject_registration_request(
    req_id: int,
    payload: RegistrationReject,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """驳回注册申请（需填写原因）"""
    _require_review_permission(current_user)
    req = _get_request_or_404(db, req_id)
    _check_in_scope(req, _allowed_departments(db, current_user))
    try:
        registration_service.reject_request(db, req, current_user.employee_id, payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit_action(db, "registration_reject", current_user.employee_id, request,
                 detail=f"employee_id={req.employee_id}, reason={payload.reason}",
                 target=req.employee_id)
    return {"message": "已驳回"}
