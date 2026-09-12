# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.department import Department
from app.models.staff import Staff
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    TokenRefreshRequest,
    UserInfo,
)
from app.schemas.user import ProfileUpdate, UserResponse
from app.services.auth_service import authenticate_user, change_password, blacklist_token, is_token_revoked
from app.services.audit_service import record_audit
# [新增 2026-09-11] 个人中心自助修改纳入「立即生效 + 追认审核」，
# 避免个人中心成为绕过人员信息审核的后门（详见 staff_change_service）
from app.models.staff_change import SOURCE_SELF
from app.services.staff_change_service import submit_change
from app.utils import (
    utc_now,
    create_access_token_with_password_info,
    create_refresh_token_with_password_info,
    decode_token,
    get_client_ip,
)
from sqlalchemy import func

router = APIRouter(prefix="/api/auth", tags=["认证"])


# [修复/问题3] refresh_token 改由 HttpOnly Cookie 承载，前端 JS 无法读取，
# 从根本上杜绝 XSS 窃取长期凭据后反复换发 access_token（原三令牌均存 localStorage）。
REFRESH_COOKIE_NAME = "refresh_token"
# 会话提示 Cookie（**非** HttpOnly，前端可读）
# 用途：refresh_token 因 HttpOnly 无法被 JS 读取，前端无从判断"是否可能已登录"，
# 只能每次开页面都无条件调一次 /auth/refresh，在登录页产生必然的 401 噪音。
# 该 Cookie 只存常量 "1"，不含任何凭据，泄露无风险。
SESSION_HINT_COOKIE = "mp_session"


def _cookie_secure_flag(request: Request) -> bool:
    """仅在实际为 HTTPS（含反代透传 X-Forwarded-Proto）时加 Secure 标记。

    内网 HTTP 部署下若强制 Secure，浏览器会拒绝写入 Cookie 导致完全无法登录，
    因此这里按请求协议自适应。
    """
    proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    return str(proto).lower() == "https"


def _set_refresh_cookie(
    request: Request,
    response: Response,
    token: str,
    remember_me: bool,
    max_age: int | None = None,
) -> None:
    if max_age is None:
        max_age = (
            settings.remember_me_refresh_token_expire_days * 86400
            if remember_me
            else settings.refresh_token_expire_minutes * 60
        )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure_flag(request),
        samesite="lax",
        path="/api/auth",
    )
    # 同时下发会话提示 Cookie：path=/ 便于前端在任意页面读取
    response.set_cookie(
        key=SESSION_HINT_COOKIE,
        value="1",
        max_age=max_age,
        httponly=False,
        secure=_cookie_secure_flag(request),
        samesite="lax",
        path="/",
    )


def _clear_refresh_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=_cookie_secure_flag(request),
        samesite="lax",
        path="/api/auth",
    )
    response.delete_cookie(
        key=SESSION_HINT_COOKIE,
        httponly=False,
        secure=_cookie_secure_flag(request),
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    user, error = authenticate_user(db, req.employee_id, req.password, client_ip)
    if error == "登录尝试过于频繁，请稍后再试":
        # [改进/A3 修复] 原 CONTACT_ADMIN 分支为死代码（authenticate_user 永不返回该值）。
        # 真实「被限流/锁定」场景即 IP 级失败次数超限，对应 error 文案为上述字符串。
        # 此处记录登录失败审计（reason=locked），便于发现暴力破解，呼应 A2 留痕策略。
        try:
            record_audit(db, "login_failed", req.employee_id,
                         detail=f"ip={client_ip}, reason=locked", target=req.employee_id, ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后再试",
        )
    if not user:
        # [改进/A2] 登录失败留痕
        try:
            record_audit(db, "login_failed", req.employee_id,
                         detail=f"ip={client_ip}, reason={error or 'bad_credentials'}",
                         target=req.employee_id, ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error or "工号或密码错误",
        )

    # 重新查询用户以正确加载角色及其权限关系
    from sqlalchemy.orm import joinedload
    from app.models.role import Role
    user = (
        db.query(User)
        .options(joinedload(User.role_obj).joinedload(Role.permissions))
        .filter(User.employee_id == req.employee_id)
        .first()
    )

    refresh_token = create_refresh_token_with_password_info(
        data={"sub": user.employee_id},
        password_changed_at=user.password_changed_at,
        remember_me=req.remember_me,
    )
    access_token = create_access_token_with_password_info(
        data={"sub": user.employee_id, "role": user.role},
        password_changed_at=user.password_changed_at
    )
    # 获取用户权限列表
    perm_names = [p.name for p in user.role_obj.permissions] if user.role_obj else []
    
    # 获取用户可管理的部门列表
    from app.dependencies import get_user_department_scope, get_user_work_type_scope
    managed_dept_ids = get_user_department_scope(user, db)
    managed_dept_names = []
    if managed_dept_ids:
        dept_names = [dept.name for dept in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
        managed_dept_names = dept_names

    work_types = get_user_work_type_scope(user)
    work_type_scope_val = ",".join(work_types) if work_types else "all"
    # [改进] 获取用户角色的科室数据范围，前端用于科室名称/分类编辑权限判断
    from app.dependencies import _get_role_dept_scope
    dept_scope = _get_role_dept_scope(user)
    
    from app.utils import create_file_access_token
    file_token = create_file_access_token(user.employee_id)

    # [新增] 判断当前用户是否有关联的员工记录，用于前端决定个人信息跳转路径，
    # 并对无员工记录的账号（如纯管理员 admin）避免发 getStaff 探测请求造成 404 噪音。
    has_staff = db.query(Staff).filter(Staff.employee_id == user.employee_id).first() is not None

    # [改进/A2] 登录成功留痕
    try:
        record_audit(db, "login", user.employee_id, detail=f"ip={client_ip}",
                     target=user.employee_id, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()

    # [修复/问题3 回归] 登录时必须把 refresh_token 写入 HttpOnly Cookie，
    # 否则前端刷新页面后内存令牌丢失、又无 Cookie 可换新，必然掉登录。
    # 同时响应体不再返回明文 refresh_token（原实现返回了但从未下发 Cookie）。
    _set_refresh_cookie(request, response, refresh_token, req.remember_me)

    return LoginResponse(
        access_token=access_token,
        file_token=file_token,
        user=UserInfo(
            employee_id=user.employee_id,
            name=user.name,
            role=user.role,
            department=user.department,
            user_type=user.user_type,
            must_change_password=user.must_change_password,
            permissions=perm_names,
            managed_departments=managed_dept_names,
            work_type_scope=work_type_scope_val,
            department_scope=dept_scope,
            has_staff_record=has_staff,
        ),
    )


@router.post("/refresh")
def refresh_token(
    request: Request,
    response: Response,
    req: TokenRefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """刷新令牌：以 HttpOnly Cookie 中的 refresh_token 换发新的 access/file token。

    [修复/问题3 回归] refresh_token 改为 Cookie 承载后，本接口此前仍只读请求体，
    导致前端刷新页面时必然 401 → 掉登录。现改为：
      1) 优先从 Cookie 读取（前端不再持有明文），并兼容请求体传入（旧客户端）；
      2) 每次刷新轮换 refresh_token（旧令牌进黑名单 reason=rotated），
         复用时被拒绝，防止长期凭据被盗后反复使用；
      3) 滑动会话：每次刷新按原策略（记住我 / 普通）续满有效期，活跃用户不掉线；
      4) 并发/多标签页的瞬时重复提交由 60s 轮换宽限期兜底（见 is_token_revoked）。
    """
    token = (req.refresh_token if req else None) or request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供刷新令牌",
        )
    payload = decode_token(token)
    if payload is None:
        _clear_refresh_cookie(request, response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的刷新令牌",
        )
    # 黑名单校验：登出/改密/禁用立即拒绝；轮换令牌在宽限期内放行
    if is_token_revoked(db, token):
        _clear_refresh_cookie(request, response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌已失效，请重新登录",
        )
    employee_id = payload.get("sub")
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user or not user.is_active:
        _clear_refresh_cookie(request, response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )
    # 检查 token 是否在密码修改之前签发（统一使用 UTC 比较）
    pwd_changed_at = payload.get("pwd_changed_at")
    if pwd_changed_at and user.password_changed_at:
        from app.utils import BEIJING_TZ
        token_time = datetime.fromtimestamp(pwd_changed_at, tz=BEIJING_TZ).replace(tzinfo=None)
        if token_time < user.password_changed_at:
            _clear_refresh_cookie(request, response)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="密码已修改，请重新登录",
            )

    new_access_token = create_access_token_with_password_info(
        data={"sub": user.employee_id, "role": user.role},
        password_changed_at=user.password_changed_at
    )
    # 刷新时一并续发短期文件访问令牌，避免登录后超过 file_token 有效期（1h）图片失效
    from app.utils import create_file_access_token
    new_file_token = create_file_access_token(user.employee_id)

    # [滑动会话] 每次刷新都按原策略（记住我 / 普通）续满有效期，活跃用户不掉线。
    # 安全性由 HttpOnly Cookie + 每次轮换（旧令牌立即入黑名单 reason=rotated）保障；
    # remember_me 取自令牌声明，保证续期时长与登录时选择的策略一致。
    remember_me = bool(payload.get("remember_me", False))
    blacklist_token(db, token, token_type="refresh", employee_id=user.employee_id, reason="rotated")
    new_refresh_token = create_refresh_token_with_password_info(
        data={"sub": user.employee_id},
        password_changed_at=user.password_changed_at,
        remember_me=remember_me,
    )
    db.commit()
    _set_refresh_cookie(request, response, new_refresh_token, remember_me=remember_me)
    return {"access_token": new_access_token, "file_token": new_file_token, "token_type": "bearer"}


@router.post("/logout")
def logout(
    req: LogoutRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """登出：将 refresh token 与 access token 均加入黑名单，避免登出后令牌仍可用"""
    # [修复/问题3] refresh_token 现位于 HttpOnly Cookie，请求体通常不再携带；
    # 登出时必须从 Cookie 兜底读取并加入黑名单，否则登出后该令牌仍能换发 access_token。
    refresh_tok = req.refresh_token or request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_tok:
        blacklist_token(db, refresh_tok, token_type="refresh", reason="logout")
    if req.access_token:
        blacklist_token(db, req.access_token, token_type="access", reason="logout")

    # [改进/A2] 登出留痕（从令牌解析操作人，无有效令牌则记为 unknown）
    actor = "unknown"
    try:
        tok = req.access_token or refresh_tok
        if tok:
            payload = decode_token(tok)
            if payload and payload.get("sub"):
                actor = payload["sub"]
        client_ip = get_client_ip(request)
        record_audit(db, "logout", actor, target=actor, ip_address=client_ip)
    except Exception as e:
        # [修复] 原先静默吞掉审计异常，登出可能无审计记录且难以排查；
        # 改为记录日志，保证登出留痕失败可被追踪
        import logging
        logging.getLogger("auth").warning(f"登出审计留痕失败: {type(e).__name__}: {e}")

    db.commit()
    # [修复] 原先登出只把令牌加入黑名单，却没有清除 refresh_token Cookie，
    # 浏览器会一直带着已失效的 Cookie 请求 /auth/refresh 并持续 401。
    # 这里主动清除 Cookie（含会话提示），使前端不再发起无谓的刷新探测。
    _clear_refresh_cookie(request, response)
    return {"message": "登出成功"}


@router.post("/change-password")
def change_user_password(
    req: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # [修复 2026-09-01] 记录密码修改失败审计
    client_ip = get_client_ip(request)
    success = change_password(db, current_user, req.old_password, req.new_password)
    if not success:
        try:
            record_audit(db, "password_change_failed", current_user.employee_id,
                         detail=f"ip={client_ip}, reason=wrong_old_password",
                         target=current_user.employee_id, ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )
    # [修复 2026-09-01] 记录密码修改成功审计
    try:
        record_audit(db, "password_change", current_user.employee_id,
                     detail=f"ip={client_ip}", target=current_user.employee_id, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    return {"message": "密码修改成功"}


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perm_names = [p.name for p in current_user.role_obj.permissions] if current_user.role_obj else []
    
    # 获取用户可管理的部门列表
    from app.dependencies import get_user_department_scope, get_user_work_type_scope
    managed_dept_ids = get_user_department_scope(current_user, db)
    managed_dept_names = []
    if managed_dept_ids:
        dept_names = [dept.name for dept in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
        managed_dept_names = dept_names

    work_types = get_user_work_type_scope(current_user)
    work_type_scope_val = ",".join(work_types) if work_types else "all"
    # [改进] 获取用户角色的科室数据范围，前端用于科室名称/分类编辑权限判断
    from app.dependencies import _get_role_dept_scope
    dept_scope = _get_role_dept_scope(current_user)

    # [新增] 判断当前用户是否有关联的员工记录（与 login 保持一致的语义）
    has_staff = db.query(Staff).filter(Staff.employee_id == current_user.employee_id).first() is not None

    return UserInfo(
        employee_id=current_user.employee_id,
        name=current_user.name,
        role=current_user.role,
        department=current_user.department,
        user_type=current_user.user_type,
        must_change_password=current_user.must_change_password,
        permissions=perm_names,
        managed_departments=managed_dept_names,
        work_type_scope=work_type_scope_val,
        department_scope=dept_scope,
        has_staff_record=has_staff,
    )


@router.put("/profile", response_model=UserResponse)
def update_profile(
    profile_in: ProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """允许任何登录用户自助修改自己的姓名、所属部门及个人介绍。

    [改进] 旧实现静默丢弃 department 且仅持久化 name，导致：
      - 员工在「个人信息」页设置的科室不生效 → user.department 为空 →
        get_user_department_scope 返回 [] → 无法查看本科室同事（症状①）；
      - 完全没有个人介绍（专业擅长/社会任职/荣誉/备注）字段 → 员工无从编辑（症状②）。
    现改为：name 直接更新；department 仅接受「已存在的科室名称」防止脏数据/越权放大；
    个人介绍字段写入本人 staff 记录（无则按 user_type 自动建记录）。
    """
    update_data = profile_in.model_dump(exclude_unset=True)

    # 个人介绍等字段的真实存储位置是本人 staff 记录
    bio_fields = (
        "education", "title", "position",
        "expertise_short", "expertise_standard",
        "social_appointments", "honors", "remarks",
    )

    # 所属部门：允许本人自助设置。仅当为已存在的科室名称时才接受，
    # 既避免末端空格/脏值，也防止「范围逃逸」到不存在的科室。
    dept_name = None
    if update_data.get("department"):
        raw_dept = update_data["department"].strip()
        if raw_dept:
            # [修复/问题26] 精确匹配优先（内部含降级与脏数据规范化），避免索引失效
            from app.dependencies import _find_department_by_name
            match = _find_department_by_name(db, raw_dept)
            if match:
                dept_name = match.name  # 用规范名称，消除末端空格

    staff = db.query(Staff).filter(
        Staff.employee_id == current_user.employee_id
    ).first()
    # 本人尚无 staff 记录时按 user_type 自动创建，确保个人介绍/审核任务可落地
    if staff is None and (
        any(f in update_data for f in bio_fields) or dept_name or update_data.get("name")
    ):
        from app.constants import WORK_TYPE_TO_USER_TYPE
        wt = {v: k for k, v in WORK_TYPE_TO_USER_TYPE.items()}.get(
            current_user.user_type, "admin"
        )
        staff = Staff(
            employee_id=current_user.employee_id,
            name=current_user.name,
            work_type=wt,
            department=current_user.department or "未分配",
        )
        db.add(staff)
        db.flush()

    # ---------------- 变更前快照（供审核驳回/撤回时回滚） ----------------
    before: dict = {"name": current_user.name, "department": current_user.department}
    if staff is not None:
        for f in bio_fields:
            before[f] = getattr(staff, f, None)
        if staff.name:
            before["name"] = staff.name
        if staff.department:
            before["department"] = staff.department

    payload: dict = {}
    if update_data.get("name"):
        payload["name"] = update_data["name"]
    if dept_name:
        payload["department"] = dept_name
    for f in bio_fields:
        if update_data.get(f) is not None:
            payload[f] = update_data[f]

    # ---------------- 立即生效（延迟生效字段除外） ----------------
    # 姓名/科室属「延迟生效字段」中的 department 与 admin 级字段：
    # 科室决定数据可见范围，立即生效会造成越权窗口，故等审核通过后由审核服务写入。
    if payload.get("name"):
        current_user.name = payload["name"]
        if staff is not None:
            staff.name = payload["name"]
    if staff is not None:
        for f in bio_fields:
            if f in payload:
                setattr(staff, f, payload[f])
        if payload:
            staff.updated_by = current_user.employee_id
            staff.updated_at = utc_now()

    # ---------------- 登记审核任务 ----------------
    # 姓名/科室 → 超管审；学历/职称/职务 → 科室负责人审（无负责人升级超管）；
    # 备注/擅长/社会任职/荣誉 → 免审直接生效。
    if staff is not None and payload:
        _change_req, reviewers = submit_change(
            db, staff=staff, before=before, payload=payload,
            submitter=current_user, source=SOURCE_SELF,
        )
        del reviewers, _change_req  # 通知已由服务内部派发（站内信直达审核人）

    db.commit()

    # [修复 2026-09-01] 个人信息修改留痕
    try:
        client_ip = get_client_ip(request)
        changed_fields = [k for k in update_data.keys() if k not in ("password",)]
        record_audit(db, "profile_update", current_user.employee_id,
                     detail=f"fields={','.join(changed_fields)}" if changed_fields else None,
                     target=current_user.employee_id, ip_address=client_ip)
        db.commit()
    except Exception:
        pass

    db.refresh(current_user)
    return current_user
