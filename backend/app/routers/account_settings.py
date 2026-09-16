# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""账号设置汇总接口 + 批量重置密码（全员 / 按科室定向）。

`GET  /api/account-settings`（需 system.config）
一次性返回「默认口令模板 + 注册开关 + 口令预览示例 + 可重置账号数 + 各科室账号数」。

`POST /api/account-settings/reset-all-passwords`（需 system.config + user.reset_password）
把「除超级管理员外」的账号口令批量重置为「默认密码规则（模板）」生成的口令，
需二次输入操作者本人的登录密码确认（详见该接口 docstring）。
[调整 2026-09-14] 支持通过 `departments` 单选 / 多选科室定向重置，
留空则沿用原语义（全员，除超级管理员外）。

说明：
- 默认口令模板属敏感配置（决定所有新建账号的初始口令），
  故不建议走「任意登录用户可读」的 `GET /api/system-config/{key}`；
- 保存仍复用现有 `PUT /api/system-config/{key}`（同样要求 system.config）。
- 账号的科室存于 `users.department`（科室名字符串），故按**名称**圈定范围，
  与 dependencies.has_department_access / services.user_service.get_user_list 口径一致。
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    PERM_SYSTEM_CONFIG,
    PERM_USER_RESET_PWD,
    SUPER_ROLES,
    get_current_user,
    has_permission,
)
from app.models.department import Department
from app.models.user import User
# [新增 2026-09-15] 批量重置任务（后台执行 + 前端进度条）
from app.models.password_reset_task import PasswordResetTask
from app.schemas.account_settings import ResetAllPasswordsRequest
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：批量重置密码后通知超管与相关科室管理员
from app.services.modification_notify import notify_super_admins
from app.services.auth_service import get_default_password_template, render_default_password
from app.services.system_config_service import (
    DEFAULT_PASSWORD_TEMPLATE_FALLBACK,
    DEFAULT_PASSWORD_TEMPLATE_KEY,
    REGISTRATION_ENABLED_KEY,
    get_config_value,
)
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import get_client_ip, hash_password, utc_now, verify_password, to_iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account-settings", tags=["账号设置"])

# 口令模板中代表「按人区分」的占位符；模板不含它时全员将得到同一个口令
EMPLOYEE_ID_PLACEHOLDER = "{工号}"


def _require_config_permission(current_user: User) -> None:
    """账号设置页统一权限校验（system.config）"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")


def _department_scope_filter(departments: list[str]):
    """构造「按科室圈定账号」的查询条件；科室列表为空时返回 None（= 不限科室）。

    账号的科室以**字符串名称**存在 `users.department`，故按名称精确匹配
    （不用 Department.id：科室被改名/删除后 ID 会与账号上的名称错配）。

    匹配前对数据库侧做 trim：历史数据中存在科室名带首尾空格的情况
    （参见 dependencies._find_department_by_name 的同类处理）；若不 trim，
    这类账号会被静默漏掉——批量改密场景下「漏改」比「多改」更难被发现。
    代价是 users.department 上的索引失效，但该查询只出现在低频的管理员批量操作中。
    """
    names = [d.strip() for d in departments if d and d.strip()]
    if not names:
        return None
    return func.trim(User.department).in_(names)


def _known_department_names(db: Session) -> set[str]:
    """系统已知科室名称 = 科室表 ∪ 账号实际使用值（均已 trim）。

    取并集而非只查科室表：账号上可能残留已被删除科室的历史名称，
    这些账号同样应当可被定向重置（保证「能选到」与「能重置」一致）。
    """
    names = {(name or "").strip() for (name,) in db.query(Department.name).all()}
    names |= {(name or "").strip() for (name,) in db.query(User.department).distinct().all()}
    names.discard("")
    return names


def _department_reset_stats(db: Session) -> tuple[list[dict], int]:
    """按科室统计「可重置账号数」（不含超级管理员），供前端展示并实时预估影响范围。

    返回 `(科室列表, 未分配科室的可重置账号数)`：
      - 以 `trim(department)` 分组，避免脏数据把一个科室拆成两条下拉项；
      - 排序沿用「科室管理」表的登记顺序（按 id），仅存在于账号上的历史科室名排在其后，
        且各自再按名称排序，保证下拉项顺序稳定、易查找；
      - 未分配科室（NULL / 空串）不进入科室列表而是单独计数：
        这类账号不属于任何科室，只有「不选科室」的全量重置才会覆盖它们。
    """
    rows = (
        db.query(func.trim(User.department), func.count(User.employee_id))
        .filter(~User.role.in_(SUPER_ROLES))
        .group_by(func.trim(User.department))
        .all()
    )

    # 科室表内的登记顺序，用于稳定排序
    table_order: dict[str, int] = {}
    for idx, (name,) in enumerate(db.query(Department.name).order_by(Department.id).all()):
        table_order.setdefault((name or "").strip(), idx)

    departments: list[dict] = []
    unassigned = 0
    for raw_name, count in rows:
        name = (raw_name or "").strip()
        if not name:
            unassigned += count
            continue
        departments.append({"name": name, "resettable_user_count": count})

    fallback_order = len(table_order)
    departments.sort(
        key=lambda d: (table_order.get(d["name"], fallback_order), d["name"])
    )
    return departments, unassigned


@router.get("")
def get_account_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """账号设置汇总（需系统配置权限）"""
    _require_config_permission(current_user)

    template = get_config_value(db, DEFAULT_PASSWORD_TEMPLATE_KEY, "")
    enabled = get_config_value(db, REGISTRATION_ENABLED_KEY, "0") == "1"
    effective = template.strip() or DEFAULT_PASSWORD_TEMPLATE_FALLBACK
    # [新增 2026-09-14] 科室维度的可重置账号数：前端据此渲染科室单选/多选下拉，
    # 并在勾选后**本地**实时预估影响人数（无需再打接口，避免连点造成范围显示滞后）
    departments, unassigned_count = _department_reset_stats(db)
    return {
        "default_password_template": template,
        "default_password_template_effective": effective,
        # 预览：把 {工号} 替换为示例工号，便于管理员确认规则效果
        "password_preview": effective.replace(EMPLOYEE_ID_PLACEHOLDER, "905182"),
        "registration_enabled": enabled,
        # [新增 2026-09-14] 供「批量重置密码」卡片展示影响范围（重置前后均可读）
        "resettable_user_count": db.query(User).filter(~User.role.in_(SUPER_ROLES)).count(),
        "super_admin_count": db.query(User).filter(User.role.in_(SUPER_ROLES)).count(),
        # 各科室可重置账号数（已按科室管理顺序排序）
        "departments": departments,
        # 未分配科室的可重置账号数：不选科室（全员）时才在范围内
        "unassigned_user_count": unassigned_count,
    }


@router.post("/reset-all-passwords")
def reset_all_passwords(
    req: ResetAllPasswordsRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量重置密码：全员，或按**单选 / 多选科室**定向重置。

    行为说明：
      1. **二次确认**：请求体须携带操作者本人的登录密码，校验失败直接 400 且不做任何改动；
      2. **范围**：`role` 属于超级管理员角色的账号一律跳过（含未启用的）；其余账号
         （含已停用账号）按 `departments` 圈定：
         - 传 1 个科室 = 单科室定向重置，传多个 = 多科室批量重置；
         - 留空 / 不传 = 不限科室，即原「除超级管理员外全员」语义；
         - 科室名须为系统已知（科室表或账号上实际使用的值），否则 400。
           这是为了避免前端缓存了「已被删除的科室」→ 接口报成功但 0 个账号命中，
           管理员误以为已重置的**静默漏改**；
         - 不在所选科室内的账号一律不动；未分配科室的账号仅在「不限科室」时才会被重置；
      3. **新口令**：按「账号设置 → 默认密码规则（模板）」生成，与新建账号口径一致。
         模板含 `{工号}` 时各人口令不同（如 MedPal@905182）；
         不含时全员口令相同，此时接口会回显该口令便于转告。
         模板为空或渲染结果不足 6 位时回退内置默认 `MedPal@2026`；
      4. **副作用**：置 `must_change_password=True`（首次登录强制改密）、
         清空登录失败计数与锁定、刷新 `password_changed_at`
         （使所有已签发 token 失效）→ 重置后全员需重新登录。

    权限：需同时具备 `system.config`（账号设置页）与 `user.reset_password`（重置密码），
    二者任一缺失即 403——批量改密属高危操作，故比单纯保存配置要求更严。

    [调整 2026-09-15] 改为**后台任务 + 进度轮询**：本接口只做校验并创建任务，
    **立即返回**任务信息（前端据此展示进度条），实际重置由后台分批执行，
    进度通过 `GET /reset-all-passwords/status/{task_id}` 轮询获取。
    同一时间只允许一个进行中的任务（重复提交返回 409 + 提示），
    避免用户在等待中重复点击 → 多个大事务并发写库（SQLite 写锁冲突）。
    """
    _require_config_permission(current_user)
    if not has_permission(current_user, PERM_USER_RESET_PWD):
        raise HTTPException(status_code=403, detail="权限不足：需要「重置密码」权限")

    client_ip = get_client_ip(request)
    # 审计/回显用的范围标识：沿用 users 列表筛选的 "||" 分隔约定，不限科室记为 "*"。
    # 在二次确认之前就算好，使「密码错误的失败审计」也能带上尝试的范围。
    scope_label = "||".join(req.departments) if req.departments else "*"

    # ---- 1) 二次确认：校验操作者本人的登录密码 ----
    if not verify_password(req.password, current_user.password_hash):
        # 与「修改密码」失败一致：留下审计痕迹，便于排查误触或口令猜测
        try:
            record_audit(
                db, "password_reset_all_failed", current_user.employee_id,
                detail=f"ip={client_ip}, reason=wrong_password, scope={scope_label}",
                target="*", ip_address=client_ip,
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=400, detail="登录密码错误，未执行任何重置")

    # ---- 2) 校验科室范围：只接受系统已知的科室名 ----
    # 前端下拉项来自 GET /api/account-settings，正常不会出现未知名称；
    # 若出现（页面长时间未刷新、科室刚被删除、或人为构造请求），宁可 400 也不能静默按错误范围执行：
    # 「以为重置了某科室、实际 0 个账号命中」在批量改密场景下是最危险的失败模式。
    known_names = _known_department_names(db)
    unknown = [d for d in req.departments if d not in known_names]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"科室不存在或已被删除：{'、'.join(unknown)}，请刷新页面后重试",
        )

    # ---- 3) 圈定范围：排除全部超级管理员角色；可按科室定向（空列表 = 不限科室）----
    scope_filter = _department_scope_filter(req.departments)
    base_query = db.query(User).filter(~User.role.in_(SUPER_ROLES))
    target_query = base_query if scope_filter is None else base_query.filter(scope_filter)
    targets = target_query.order_by(User.employee_id).all()

    # 被跳过的超级管理员也按同一科室范围统计，使回显的「跳过数」与实际视野一致
    super_admin_query = db.query(User).filter(User.role.in_(SUPER_ROLES))
    if scope_filter is not None:
        super_admin_query = super_admin_query.filter(scope_filter)
    super_admin_count = super_admin_query.count()

    # 定向重置时顺带统计「未分配科室」被跳过的账号数（仅用于结果说明，避免管理员疑惑是否漏改）
    unassigned_excluded = 0
    if scope_filter is not None:
        unassigned_excluded = base_query.filter(
            or_(User.department.is_(None), func.trim(User.department) == "")
        ).count()

    # ---- 4) 口令模板：只读一次，保证整批口径一致 ----
    template = get_default_password_template(db)
    is_uniform = EMPLOYEE_ID_PLACEHOLDER not in template

    # [新增 2026-09-15] 并发保护：同一时间只允许一个进行中的重置任务。
    # 用户重复点击 / 多标签页同时提交时，第 2 个请求会被 409 拦下，前端据此切换到
    # 「进行中任务」的进度展示——从根上避免多个大事务并发写库（SQLite 写锁冲突）。
    # 顺带把超时未完成（如服务重启中断）的僵尸任务标记为失败，避免永久阻塞后续操作。
    stale_cutoff = utc_now() - timedelta(hours=1)
    db.query(PasswordResetTask).filter(
        PasswordResetTask.status == "running",
        PasswordResetTask.created_at < stale_cutoff,
    ).update(
        {"status": "failed", "error": "任务超时未完成（可能因服务重启中断）", "finished_at": utc_now()},
        synchronize_session=False,
    )
    db.commit()
    running_task = (
        db.query(PasswordResetTask)
        .filter(PasswordResetTask.status == "running")
        .order_by(PasswordResetTask.id.desc())
        .first()
    )
    if running_task:
        raise HTTPException(
            status_code=409,
            detail="已有批量重置任务正在进行中，请等待其完成后再操作",
        )

    # ---- 5) 创建任务并交给后台执行（立即返回，前端按**实际进度**轮询展示）----
    inactive_count = sum(1 for u in targets if not u.is_active)
    self_included = any(u.employee_id == current_user.employee_id for u in targets)
    task = PasswordResetTask(
        status="running",
        total=len(targets),
        processed=0,
        inactive_count=inactive_count,
        super_admin_excluded=super_admin_count,
        unassigned_excluded=unassigned_excluded,
        departments="||".join(req.departments),
        is_all_departments=scope_filter is None,
        password_rule=template,
        is_uniform=is_uniform,
        uniform_password=render_default_password(template) if is_uniform else None,
        self_included=self_included,
        created_by=current_user.employee_id,
        created_by_name=current_user.name,
        created_at=utc_now(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    if task.total == 0:
        # 范围内没有可重置的账号（例如所选科室只剩超级管理员）：直接完成，不启动后台任务
        task.status = "completed"
        task.message = "范围内没有可重置的账号（超级管理员除外），未做任何改动"
        task.finished_at = utc_now()
        db.commit()
    else:
        background_tasks.add_task(
            _run_password_reset,
            task.id,
            [u.employee_id for u in targets],
            template,
            is_uniform,
            client_ip,
        )

    # 审计留痕与站内信提醒已随本批处理移至后台任务（_run_password_reset），
    # 在任务完成后按**实际结果**写入；此处直接返回任务信息供前端展示进度条。
    return _task_payload(task)


def _task_payload(task: PasswordResetTask) -> dict:
    """任务 → 前端载荷（字段与前端 ResetTask 类型一一对应）"""
    return {
        "task_id": task.id,
        "status": task.status,
        "total": task.total,
        "processed": task.processed,
        "inactive_count": task.inactive_count or 0,
        "super_admin_excluded": task.super_admin_excluded or 0,
        "unassigned_excluded": task.unassigned_excluded or 0,
        "departments": [d for d in (task.departments or "").split("||") if d],
        "is_all_departments": bool(task.is_all_departments),
        "password_rule": task.password_rule,
        "is_uniform": bool(task.is_uniform),
        "uniform_password": task.uniform_password,
        "self_included": bool(task.self_included),
        "message": task.message,
        "error": task.error,
        # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
        "created_at": to_iso_utc(task.created_at),
        "finished_at": to_iso_utc(task.finished_at),
    }


def _run_password_reset(
    task_id: int,
    employee_ids: list[str],
    template: str,
    is_uniform: bool,
    client_ip: str | None,
) -> None:
    """[新增 2026-09-15] 批量重置密码后台任务：分批处理 + 实时更新进度。

    设计要点：
    - 独立 Session（请求的 session 随响应结束已关闭）；
    - 每处理 BATCH_SIZE 个账号提交一次：进度可被前端轮询看到，且避免单个超长事务
      在 SQLite 上长时间持有写锁（这是此前"等待中重复操作 → 数据库错误"的根因之一）；
    - 统一口令（模板不含 {工号}）只计算一次 bcrypt 哈希并复用，整批毫秒级完成；
    - 通过 run_serial 与备份/导出打包等重量级任务串行，避免并发写库；
    - 完成后写审计 + 站内信通知（二者失败均不影响已生效的重置）。
    """
    from app.database import SessionLocal
    from app.services.task_queue import run_serial

    BATCH_SIZE = 20

    def _do_reset() -> None:
        db = SessionLocal()
        try:
            task = db.query(PasswordResetTask).filter(PasswordResetTask.id == task_id).first()
            if not task:
                logger.warning("批量重置任务不存在: task_id=%s", task_id)
                return

            changed_at = utc_now()
            # 统一口令时预计算一次哈希（bcrypt 约 0.2~0.3s/次）后整批复用
            uniform_hash = hash_password(render_default_password(template)) if is_uniform else None

            processed = 0
            for i in range(0, len(employee_ids), BATCH_SIZE):
                chunk = employee_ids[i:i + BATCH_SIZE]
                users = db.query(User).filter(User.employee_id.in_(chunk)).all()
                for user in users:
                    if uniform_hash is not None:
                        user.password_hash = uniform_hash
                    else:
                        user.password_hash = hash_password(
                            render_default_password(template, user.employee_id)
                        )
                    # 与新建账号一致：首次登录强制修改，避免长期沿用规则化口令
                    user.must_change_password = True
                    # 清空失败计数与锁定：口令已更换，此前的暴力破解进度自然失效
                    user.login_attempts = 0
                    user.locked_until = None
                    # 刷新时间戳使既有 token 全部失效（重置后须重新登录）
                    user.password_changed_at = changed_at
                processed += len(users)
                task.processed = processed
                db.commit()  # 分批提交：进度可见 + 缩短写锁持有时间

            # ---- 结果文案（区分「全员 / 单科室 / 多科室 / 空范围」四种情形）----
            departments = [d for d in (task.departments or "").split("||") if d]
            if task.total == 0:
                message = "范围内没有可重置的账号（超级管理员除外），未做任何改动"
            elif task.is_all_departments:
                message = f"已重置 {task.total} 个账号的密码"
            elif len(departments) == 1:
                message = f"已重置「{departments[0]}」共 {task.total} 个账号的密码"
            else:
                message = (
                    f"已重置「{departments[0]}」等 {len(departments)} 个科室"
                    f"共 {task.total} 个账号的密码"
                )
            task.message = message
            task.processed = task.total
            task.status = "completed"
            task.finished_at = utc_now()
            db.commit()

            # ---- 审计留痕（失败不影响已生效的重置）----
            # 动作名沿用 password_reset_all 不新增枚举，改为在 detail 里记录 scope：
            # 这样「全员重置」与「按科室重置」在同一条审计流里可比对。
            try:
                record_audit(
                    db, "password_reset_all", task.created_by,
                    detail=(
                        f"ip={client_ip}, reset={task.total}, "
                        f"scope={'||'.join(departments) if departments else '*'}, "
                        f"excluded_super_admins={task.super_admin_excluded}, "
                        f"excluded_unassigned={task.unassigned_excluded}, "
                        f"rule={template}"
                    ),
                    target="*", ip_address=client_ip,
                )
                db.commit()
            except Exception:
                db.rollback()

            # ---- 站内信提醒（事件：重置账号密码）----
            # 一次操作会使一批账号的登录态失效并换成规则化口令；此前只写审计日志，
            # 超管与相关科室管理员无从察觉。命中 0 个账号时不发（无信息量）。
            if task.total > 0:
                try:
                    if len(departments) == 1:
                        scope_desc = f"科室「{departments[0]}」"
                    elif departments:
                        scope_desc = f"「{departments[0]}」等 {len(departments)} 个科室"
                    else:
                        scope_desc = "全员（超级管理员除外）"
                    modifier_name = task.created_by_name or task.created_by
                    notify_super_admins(
                        db,
                        title="批量重置账号密码",
                        content=(
                            f"{modifier_name} 批量重置了{scope_desc}的 {task.total} 个账号密码，"
                            f"相关账号需重新登录"
                        ),
                        related_type="user",
                        # 仅单科室定向重置时才传 department（多科室无单一值；传 None 时收件人=全体超管）
                        department=departments[0] if len(departments) == 1 else None,
                        exclude_user_id=task.created_by,
                        event_code="user.password_reset",
                        context={
                            "操作人": modifier_name,
                            "姓名": f"批量（{task.total} 个账号）",
                            "工号": "批量",
                            "变更内容": f"批量重置{scope_desc}的 {task.total} 个账号密码",
                        },
                    )
                    db.commit()
                except Exception:
                    db.rollback()
        except Exception as e:
            logger.error("批量重置密码任务失败 task_id=%s: %s", task_id, e, exc_info=True)
            db.rollback()
            try:
                task = db.query(PasswordResetTask).filter(PasswordResetTask.id == task_id).first()
                if task:
                    task.status = "failed"
                    task.error = f"{type(e).__name__}: {str(e)[:180]}"
                    task.finished_at = utc_now()
                    db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()

    try:
        run_serial(_do_reset)
    except Exception:
        # run_serial 内部已记录日志；此处兜底避免后台任务异常外溢
        logger.error("批量重置密码串行任务异常 task_id=%s", task_id, exc_info=True)


@router.get("/reset-all-passwords/status")
def get_latest_reset_task(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """最近的批量重置任务。

    供前端在刷新页面 / 重新进入时恢复进度：若最近任务仍在运行，前端直接
    切回进度条展示，避免用户以为"没反应"而重复提交。
    """
    _require_config_permission(current_user)
    task = db.query(PasswordResetTask).order_by(PasswordResetTask.id.desc()).first()
    return {"task": _task_payload(task) if task else None}


@router.get("/reset-all-passwords/status/{task_id}")
def get_reset_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按 ID 查询批量重置任务进度（前端轮询用）"""
    _require_config_permission(current_user)
    task = db.query(PasswordResetTask).filter(PasswordResetTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": _task_payload(task)}
