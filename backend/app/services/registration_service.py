# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""注册申请服务：登录页自助注册的提交、查询与审核。

设计要点：
- 申请密码仅保存 bcrypt 的 `password_hash`（**不存明文**），账号创建时直接复用 →
  注册时填写的密码即为最终登录密码，因此自助注册账号**不受**「账号设置」里
  默认口令模板的约束。
- [调整 2026-09-17] **注册成功即可登录系统**（查看/修改个人资料），
  审核通过后才获得所在角色的完整权限。因此提交注册时即单事务创建
  `User`（review_status=pending）+ `Staff` 人员档案 + 审核申请：
  - 待审核期间的接口访问范围由 main.py 中间件白名单限制（仅认证与本人资料）；
  - 审核通过（approve_request）置 approved 解除受限；
  - 审核驳回（reject_request）置 rejected 并禁用登录，可重新提交申请。
- 审核范围：超级管理员可审全部；科室管理员仅能审「管辖科室」的申请。
"""

import logging
import re

from sqlalchemy.orm import Session

from app.constants import (
    WORK_TYPE_TO_USER_TYPE,
    REVIEW_PENDING,
    REVIEW_APPROVED,
    REVIEW_REJECTED,
)
from app.models.department import Department
from app.models.registration_request import RegistrationRequest
from app.models.role import Role
from app.models.staff import Staff
from app.models.user import User
from app.services.system_config_service import REGISTRATION_ENABLED_KEY, get_config_value
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import hash_password, utc_now, to_iso_utc

logger = logging.getLogger("registration")

# 可选择工种（与 Staff.work_type 取值保持一致）
WORK_TYPE_OPTIONS = [
    {"value": "doctor", "label": "医生"},
    {"value": "nurse", "label": "护士"},
    {"value": "technician", "label": "技师"},
    {"value": "admin", "label": "行政"},
]
WORK_TYPES = {o["value"] for o in WORK_TYPE_OPTIONS}

# [调整 2026-09-17] 自助注册工号规则收紧为「6 位数字」（医院工号编码规范）。
# 注意：仅约束**注册**入口；登录接口与后台建号不限该格式，
# 历史账号（如 admin、含字母的工号）不受影响。
EMPLOYEE_ID_RE = re.compile(r"^\d{6}$")
NAME_MAX_LEN = 50
PASSWORD_MIN_LEN = 6
PASSWORD_MAX_LEN = 50
REJECT_REASON_MAX_LEN = 200

VALID_STATUSES = ("pending", "approved", "rejected")


def is_registration_enabled(db: Session) -> bool:
    """登录页注册开关是否开启（配置值 "1" 为开启）"""
    return get_config_value(db, REGISTRATION_ENABLED_KEY, "0") == "1"


def get_department_names(db: Session) -> list[str]:
    """可选科室名称列表"""
    return [d.name for d in db.query(Department).order_by(Department.name).all()]


def get_public_options(db: Session) -> dict:
    """公开注册选项（免登录）。

    只暴露「是否开放 / 工种枚举 / 科室名称」，不包含任何敏感配置。
    开关关闭时不下发选项，减少信息暴露。
    """
    enabled = is_registration_enabled(db)
    return {
        "enabled": enabled,
        "work_types": WORK_TYPE_OPTIONS if enabled else [],
        "departments": get_department_names(db) if enabled else [],
    }


def submit_registration(
    db: Session,
    *,
    employee_id: str,
    name: str,
    password: str,
    work_type: str,
    department: str,
    ip_address: str | None = None,
) -> dict:
    """提交注册申请。

    [调整 2026-09-17] **注册成功即可登录系统**（查看/修改个人资料），审核通过后
    才获得所在角色的完整权限。因此由原「只登记申请、审核通过才建号」改为
    **单事务创建账号 + 人员档案 + 审核申请**，账号以 review_status=pending 落库。

    校验不通过抛 ValueError（由路由转为 400）。
    """
    if not is_registration_enabled(db):
        raise ValueError("系统未开放自助注册，请联系管理员")

    emp = (employee_id or "").strip()
    nm = (name or "").strip()
    dept = (department or "").strip()

    # [调整 2026-09-17] 工号规则：6 位数字
    if not EMPLOYEE_ID_RE.match(emp):
        raise ValueError("工号必须为 6 位数字")
    if not nm or len(nm) > NAME_MAX_LEN:
        raise ValueError(f"请输入姓名（不超过 {NAME_MAX_LEN} 个字符）")
    if not password or len(password) < PASSWORD_MIN_LEN or len(password) > PASSWORD_MAX_LEN:
        raise ValueError(f"密码长度需为 {PASSWORD_MIN_LEN}~{PASSWORD_MAX_LEN} 位")
    if work_type not in WORK_TYPES:
        raise ValueError("请选择有效的工种")
    if dept not in get_department_names(db):
        raise ValueError("请选择有效的所属科室")

    # 曾被驳回的申请：允许重新提交，并把上次驳回原因回显给申请人
    last_rejected = (
        db.query(RegistrationRequest)
        .filter(RegistrationRequest.employee_id == emp, RegistrationRequest.status == "rejected")
        .order_by(RegistrationRequest.created_at.desc())
        .first()
    )

    existing_user = db.query(User).filter(User.employee_id == emp).first()
    if existing_user is not None:
        status = getattr(existing_user, "review_status", REVIEW_APPROVED)
        if status == REVIEW_PENDING:
            raise ValueError("该工号的注册申请正在审核中，请直接登录查看进度")
        if status == REVIEW_APPROVED:
            raise ValueError("该工号已存在，请直接登录或联系管理员")
        # reply_to_rejected: 被驳回的账号允许重新注册（下方重置密码与资料）

    staff = db.query(Staff).filter(Staff.employee_id == emp).first()
    pwd_hash = hash_password(password)

    if existing_user is None:
        # 新账号：按「普通员工」角色建档，立即具备登录能力（待审核受限）
        emp_role = db.query(Role).filter(Role.name == "employee").first()
        db.add(User(
            employee_id=emp,
            name=nm,
            password_hash=pwd_hash,
            role="employee",
            role_id=emp_role.id if emp_role else None,
            department=dept,
            user_type=WORK_TYPE_TO_USER_TYPE.get(work_type, "admin_user"),
            is_active=True,
            must_change_password=False,
            review_status=REVIEW_PENDING,
        ))
    else:
        # 曾被驳回的账号：重新进入待审核（重置密码与资料）
        existing_user.name = nm
        existing_user.password_hash = pwd_hash
        existing_user.department = dept
        existing_user.user_type = WORK_TYPE_TO_USER_TYPE.get(work_type, "admin_user")
        existing_user.review_status = REVIEW_PENDING
        existing_user.is_active = True
        existing_user.must_change_password = False
        # 推进密码变更时间，令该账号此前签发的令牌全部失效（强制重新登录）
        existing_user.password_changed_at = utc_now()
        logger.info("驳回账号重新提交注册: 工号=%s", emp)

    # 人员档案：不存在则新建；已存在（含离职档案）则按本次注册资料更新为在职
    if staff is None:
        db.add(Staff(
            employee_id=emp,
            name=nm,
            work_type=work_type,
            department=dept,
            status="active",
        ))
    else:
        staff.name = nm
        staff.work_type = work_type
        staff.department = dept
        staff.status = "active"

    req = RegistrationRequest(
        employee_id=emp,
        name=nm,
        password_hash=pwd_hash,
        work_type=work_type,
        department=dept,
        status="pending",
        ip_address=ip_address,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    logger.info("注册成功并创建待审核账号: 工号=%s, 科室=%s", emp, dept)
    return {
        "status": "pending",
        "id": req.id,
        # [新增 2026-09-17] 供前端提示「注册成功，可直接登录（审核通过后解锁完整权限）」
        "can_login": True,
        "last_reject_reason": last_rejected.reject_reason if last_rejected else None,
    }


def list_requests(
    db: Session,
    *,
    status: str = "pending",
    page: int = 1,
    page_size: int = 20,
    allowed_departments: list[str] | None = None,
) -> tuple[list[RegistrationRequest], int]:
    """查询注册申请。

    Args:
        allowed_departments: None 表示不限制范围（超级管理员）；
            传入列表则仅返回该科室集合内的申请（科室管理员）。
    """
    q = db.query(RegistrationRequest)
    if status and status in VALID_STATUSES:
        q = q.filter(RegistrationRequest.status == status)
    if allowed_departments is not None:
        if not allowed_departments:
            return [], 0
        q = q.filter(RegistrationRequest.department.in_(allowed_departments))

    total = q.count()
    items = (
        q.order_by(RegistrationRequest.created_at.desc())
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def pending_count(db: Session, allowed_departments: list[str] | None = None) -> int:
    """待审数量（供菜单红点）"""
    if allowed_departments is not None and not allowed_departments:
        return 0
    q = db.query(RegistrationRequest).filter(RegistrationRequest.status == "pending")
    if allowed_departments is not None:
        q = q.filter(RegistrationRequest.department.in_(allowed_departments))
    return q.count()


def approve_request(db: Session, req: RegistrationRequest, reviewer: str) -> User:
    """审核通过：解除账号受限，获得所属角色的完整权限。

    [调整 2026-09-17] 注册时已创建账号（review_status=pending），本函数将其置为
    approved 即完成授权；同时同步注册资料到账号与人员档案。
    兼容历史遗留申请（旧流程申请时未建号）—— 仍按原逻辑创建账号与档案。
    """
    if req.status != "pending":
        raise ValueError("该申请已被处理，请刷新后重试")

    user = db.query(User).filter(User.employee_id == req.employee_id).first()
    existing_staff = db.query(Staff).filter(Staff.employee_id == req.employee_id).first()

    if user is None:
        # ---------------- 兼容旧流程：申请时未创建账号 ----------------
        if existing_staff and existing_staff.status == "resigned":
            raise ValueError(
                "该工号存在离职档案（登录账号仍保留），请在「离职人员」页对其执行「恢复在职」，"
                "无需重新注册"
            )
        emp_role = db.query(Role).filter(Role.name == "employee").first()
        user = User(
            employee_id=req.employee_id,
            name=req.name,
            # 直接复用注册时填写的密码（bcrypt），因此自助注册不受默认口令模板约束
            password_hash=req.password_hash,
            role="employee",
            role_id=emp_role.id if emp_role else None,
            department=req.department,
            user_type=WORK_TYPE_TO_USER_TYPE.get(req.work_type, "admin_user"),
            is_active=True,
            must_change_password=False,
            review_status=REVIEW_APPROVED,
        )
        db.add(user)
    else:
        # ---------------- 新流程：账号已创建（待审核态），解除受限 ----------------
        user.review_status = REVIEW_APPROVED
        user.is_active = True
        if req.name:
            user.name = req.name
        if req.department:
            user.department = req.department

    # 同步人员档案：不存在则新建；存在「离职档案」时按**重新入职**处理
    # （账号此前已被管理员删除，仅档案残留在库中）
    if existing_staff is None:
        db.add(Staff(
            employee_id=req.employee_id,
            name=req.name,
            work_type=req.work_type,
            department=req.department,
            status="active",
        ))
    elif existing_staff.status == "resigned":
        # [新增 2026-09-11] 重新入职：复用离职档案并清空离职信息（含保留期提醒标记）
        existing_staff.status = "active"
        existing_staff.resigned_at = None
        existing_staff.resign_reason = None
        existing_staff.resigned_by = None
        existing_staff.account_notice_at = None
        if req.name:
            existing_staff.name = req.name
        if req.department:
            existing_staff.department = req.department
        logger.info("重新入职：复用离职档案 工号=%s", req.employee_id)
    else:
        # [新增 2026-09-17] 审核通过时按申请资料校正档案（注册→审核期间可能已修改资料）
        if req.name:
            existing_staff.name = req.name
        if req.work_type:
            existing_staff.work_type = req.work_type
        if req.department:
            existing_staff.department = req.department

    req.status = "approved"
    req.reviewed_by = reviewer
    req.reviewed_at = utc_now()
    db.commit()
    logger.info("注册申请通过: 工号=%s, 审核人=%s", req.employee_id, reviewer)
    return user


def reject_request(db: Session, req: RegistrationRequest, reviewer: str, reason: str) -> None:
    """驳回注册申请（必须填写原因，供申请人重新提交时查看）。

    [调整 2026-09-17] 注册时已创建账号，驳回需一并**禁用登录**并标记
    review_status=rejected；同时推进 password_changed_at 使该账号已签发的令牌
    立即失效（强制下线），避免被驳回的账号继续使用系统。
    """
    if req.status != "pending":
        raise ValueError("该申请已被处理，请刷新后重试")
    text = (reason or "").strip()
    if not text:
        raise ValueError("请填写驳回原因")
    req.status = "rejected"
    req.reject_reason = text[:REJECT_REASON_MAX_LEN]
    req.reviewed_by = reviewer
    req.reviewed_at = utc_now()

    user = db.query(User).filter(User.employee_id == req.employee_id).first()
    if user is not None and getattr(user, "review_status", REVIEW_APPROVED) != REVIEW_APPROVED:
        user.review_status = REVIEW_REJECTED
        user.is_active = False
        # 推进密码变更时间 → 已签发的 access/refresh token 立即失效
        user.password_changed_at = utc_now()

    db.commit()
    logger.info("注册申请驳回: 工号=%s, 审核人=%s", req.employee_id, reviewer)


def serialize(req: RegistrationRequest) -> dict:
    """对外序列化（**绝不包含 password_hash**）"""
    return {
        "id": req.id,
        "employee_id": req.employee_id,
        "name": req.name,
        "work_type": req.work_type,
        "department": req.department,
        "status": req.status,
        "reject_reason": req.reject_reason,
        "reviewed_by": req.reviewed_by,
        # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
        "reviewed_at": to_iso_utc(req.reviewed_at),
        "created_at": to_iso_utc(req.created_at),
    }
