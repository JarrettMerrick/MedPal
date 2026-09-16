# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""人员信息变更审核服务（立即生效 + 追认 + 可回滚）。

业务规则（2026-09-11 定稿）
--------------------------
1. **立即生效**：提交即写入主表，页面立刻显示最新值（满足「修改后立即显示最新」）；
   同时在显著位置提示「待 XX 审核」。审核通过 = 追认；审核驳回 = 回滚到提交前旧值。
2. **字段分级**（不是所有字段都要审，避免审批疲劳）：

   | 级别 | 字段 | 审核人 |
   |---|---|---|
   | none  | 备注、专业擅长（短/标准）、社会任职、荣誉 | 免审，直接生效 |
   | dept  | 学历、职称、职务、正面照、侧面照 | 本科室负责人（或签），无负责人时升级超管 |
   | admin | 姓名、科室、工种 | 仅超级管理员 |

3. **审核人**：同科室多个负责人 = **或签**（任一通过即生效）；科室无人负责 →
   自动升级全部超管；**禁止自审**（提交人不在审核人范围内）；**超级管理员提交免审**
   （仅留痕，不产生待审任务）。
4. **越权防护**：`department` / `work_type` 决定数据可见范围，若立即生效会出现
   「先拿到新科室数据权限、后被驳回」的越权窗口，故列为**延迟生效字段**——
   审核通过后才写入主表（其余字段仍为立即生效）。如需改为全部立即生效，
   只需把 `DEFERRED_FIELDS` 置空。
5. **冲突检测**：基于字段值比对（不依赖时间戳）。审核时若发现该字段在提交后
   又被他人改动，则**拒绝自动回滚**，仅提示人工核对，避免覆盖他人的合法修改。
6. **超时**：24 小时未审 → 站内信提醒审核人；72 小时未审 → 升级给全部超管
   （升级后超管可接管审核）。由 `sweep_overdue()` 惰性扫描 + 启动时各执行一次。
"""

import json
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.dependencies import (
    ROLE_DEPT_MANAGER, ROLE_SUPER_ADMIN, has_department_access,
)
from app.models.department import Department
from app.models.staff import Staff
from app.models.staff_change import (
    LEVEL_ADMIN, LEVEL_DEPT, LEVEL_NONE, SOURCE_ADMIN,
    STATUS_APPROVED, STATUS_CANCELLED, STATUS_PENDING, STATUS_REJECTED,
    StaffChangeRequest,
)
from app.models.user import User
from app.services import message_service
# [新增 2026-09-15] 可配置通知中心（待审核 / 审核结果 / 超时提醒统一走事件规则）
from app.services import notification_center
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import utc_now, to_iso_utc

logger = logging.getLogger("staff_change")

# ==================== 字段分级 ====================

#: 字段 → 审核级别（未登记的字段按最严：仅超管审）
FIELD_LEVELS: dict[str, str] = {
    # 低风险（自我介绍类）：免审，直接生效
    "remarks": LEVEL_NONE,
    "expertise_short": LEVEL_NONE,
    "expertise_standard": LEVEL_NONE,
    "social_appointments": LEVEL_NONE,
    "honors": LEVEL_NONE,
    # 资质类：科室负责人审核
    "education": LEVEL_DEPT,
    "title": LEVEL_DEPT,
    "position": LEVEL_DEPT,
    "front_photo": LEVEL_DEPT,
    "side_photo": LEVEL_DEPT,
    # 影响数据范围/身份的口径：仅超级管理员审核
    "name": LEVEL_ADMIN,
    "department": LEVEL_ADMIN,
    "work_type": LEVEL_ADMIN,
}

FIELD_LABELS: dict[str, str] = {
    "name": "姓名", "work_type": "工种", "education": "学历", "title": "职称",
    "department": "所属科室", "position": "职务",
    "expertise_short": "专业擅长（短）", "expertise_standard": "专业擅长（标准）",
    "social_appointments": "社会任职", "honors": "获得荣誉", "remarks": "备注",
    "front_photo": "正面照", "side_photo": "侧面照",
}

#: 延迟生效字段：审核通过后才写入主表（见模块 docstring 第 4 条）
DEFERRED_FIELDS: frozenset[str] = frozenset({"department", "work_type"})

#: 超时阈值（小时）
REMIND_AFTER_HOURS = 24
ESCALATE_AFTER_HOURS = 72

MAX_REASON_LEN = 200
MAX_SUMMARY_LEN = 500


def field_level(field: str) -> str:
    """字段的审核级别；未登记字段按最严处理（仅超管审）"""
    return FIELD_LEVELS.get(field, LEVEL_ADMIN)


def resolve_level(fields) -> str:
    """一组字段的最终审核级别（取最高）"""
    level = LEVEL_NONE
    for f in fields:
        lv = field_level(f)
        if lv == LEVEL_ADMIN:
            return LEVEL_ADMIN
        if lv == LEVEL_DEPT:
            level = LEVEL_DEPT
    return level


def level_label(level: str) -> str:
    """审核层级的展示文案"""
    return {LEVEL_DEPT: "科室负责人", LEVEL_ADMIN: "超级管理员"}.get(level, "免审")


def is_super_admin(user: User | None) -> bool:
    return bool(user and user.role == ROLE_SUPER_ADMIN)


# ==================== 工具 ====================


def diff_fields(before: dict, payload: dict) -> dict:
    """挑出真正发生变化的（可审核）字段：只关心已登记分级的字段"""
    changed: dict = {}
    for key, new_value in payload.items():
        if key not in FIELD_LEVELS:
            continue
        old_value = before.get(key)
        if (old_value or None) != (new_value or None):
            changed[key] = new_value
    return changed


def build_summary(before: dict, changed: dict) -> str:
    """生成「职称: 住院医师 → 主治医师」式摘要（供审核人一眼判断）"""
    parts = []
    for field, new_value in changed.items():
        label = FIELD_LABELS.get(field, field)
        old_value = before.get(field) or "(空)"
        parts.append(f"{label}: {old_value} → {new_value or '(空)'}")
    summary = "；".join(parts)
    if len(summary) > MAX_SUMMARY_LEN:
        summary = summary[:MAX_SUMMARY_LEN] + "..."
    return summary or "更新操作"


def _managed_department_names(db: Session, user: User) -> list[str]:
    """用户管辖的科室名称列表（超管在调用前已另行处理）"""
    from app.dependencies import get_user_department_scope

    dept_ids = get_user_department_scope(user, db)
    if not dept_ids:
        return []
    return [d.name for d in db.query(Department).filter(Department.id.in_(dept_ids)).all()]


# ==================== 审核人解析 ====================


def resolve_reviewers(
    db: Session, *, department: str | None, level: str, submitter_id: str,
) -> list[str]:
    """解析审核人工号（或签）。

    返回空列表表示**无需审核**（level=none、超管提交免审、或无可用审核人）。
    """
    if level == LEVEL_NONE:
        return []

    submitter = db.query(User).filter(User.employee_id == submitter_id).first()
    if is_super_admin(submitter):
        return []  # 超级管理员免审（仅留痕）

    def _super_admin_ids() -> list[str]:
        return [
            u.employee_id
            for u in db.query(User).filter(
                User.is_active == True, User.role == ROLE_SUPER_ADMIN,  # noqa: E712
            ).all()
            # 禁止自审：提交人本人不进入审核人范围
            if u.employee_id != submitter_id
        ]

    ids: list[str] = []
    if level == LEVEL_DEPT and department:
        for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
            if (
                u.role == ROLE_DEPT_MANAGER
                and u.employee_id != submitter_id  # 禁止自审（含「负责人自己提交」）
                and has_department_access(u, department, db)
            ):
                ids.append(u.employee_id)

    if not ids:
        # level=admin，或该科室没有负责人，或负责人本人就是提交人 → 升级给全部超管
        ids = _super_admin_ids()

    return message_service.normalize_recipients(ids)


def can_review(db: Session, req: StaffChangeRequest, reviewer: User | None) -> bool:
    """当前用户是否为该变更的合法审核人（或签：任一审核人即可）"""
    if not reviewer or req.status != STATUS_PENDING:
        return False
    if req.submitted_by == reviewer.employee_id:
        return False  # 禁止自审
    if is_super_admin(reviewer):
        return True  # 超管可接管任何待审变更
    if req.review_level != LEVEL_DEPT:
        return False
    return has_department_access(reviewer, req.department or "", db)


# ==================== 提交 ====================


def _reviewers_of(db: Session, req: StaffChangeRequest) -> list[str]:
    """还原某条待审变更的审核人列表（供去重命中时返回，保持调用方语义一致）。

    仅在记录仍为 pending 时才有意义（终态记录不再需要派发任务，返回空列表）。
    这里复用 resolve_reviewers 重算，而非新增字段存储：审核人解析规则
    （科室负责人 / 无负责人升级超管 / 禁止自审）是纯函数式且幂等的。
    """
    if req.status != STATUS_PENDING:
        return []
    return resolve_reviewers(
        db, department=req.department, level=req.review_level,
        submitter_id=req.submitted_by,
    )


def _find_duplicate(
    db: Session, *, employee_id: str, changed: dict,
) -> StaffChangeRequest | None:
    """查找同一人员、同一批字段的**待审**重复变更（幂等去重）。

    [新增 2026-09-15] 修复「上传一张正面照却产生 2 条待审记录」：
    前端 PhotoUpload 上传成功后会把 file_path 写入表单，用户再点「保存」时
    `PUT /api/staff/{id}` 又带上了同一个新路径，于是同一次上传被登记两次
    （source=photo + source=admin）。此处按「同一人员 + 待审中 + 变更字段集合
    与新值完全一致」判定为同一次变更，复用已有记录、不重复派发审核任务。

    判定条件（三者同时满足才视为重复）：
      1. 同一 employee_id 且状态为 pending；
      2. changed_fields 集合完全相同（不多不少）；
      3. 各字段的新值（payload）完全一致。
    """
    candidates = (
        db.query(StaffChangeRequest)
        .filter(
            StaffChangeRequest.employee_id == employee_id,
            StaffChangeRequest.status == STATUS_PENDING,
        )
        .all()
    )
    target_keys = set(changed.keys())
    for req in candidates:
        try:
            keys = set(json.loads(req.changed_fields or "[]"))
            if keys != target_keys:
                continue
            prev_payload = json.loads(req.payload or "{}")
        except (ValueError, TypeError):
            continue
        if all((prev_payload.get(k) or None) == (changed[k] or None) for k in target_keys):
            return req
    return None


def submit_change(
    db: Session, *, staff: Staff, before: dict, payload: dict,
    submitter: User, source: str = SOURCE_ADMIN,
) -> tuple[StaffChangeRequest | None, list[str]]:
    """登记一次变更并派发审核任务。

    **调用前提**：调用方已按「立即生效」写入 `payload` 中**非延迟字段**的值
    （延迟字段保持旧值，等审核通过时由 `approve_request` 写入）。

    Returns:
        (变更申请 或 None, 审核人工号列表)。返回 None 表示本次改动免审。
    """
    changed = diff_fields(before, payload)
    if not changed:
        return None, []

    # [新增 2026-09-15] 幂等去重：同一次上传/保存被登记两次时复用已有待审记录，
    # 避免审核列表出现重复条目（并返回原审核人，保证调用方行为不变）。
    duplicate = _find_duplicate(db, employee_id=staff.employee_id, changed=changed)
    if duplicate is not None:
        logger.info(
            "人员信息变更去重：复用已有待审记录 id=%s, 工号=%s, 字段=%s（本次来源=%s）",
            duplicate.id, staff.employee_id, list(changed.keys()), source,
        )
        return duplicate, _reviewers_of(db, duplicate)

    level = resolve_level(changed.keys())
    reviewers = resolve_reviewers(
        db, department=staff.department, level=level, submitter_id=submitter.employee_id,
    )
    now = utc_now()
    if reviewers:
        status, note = STATUS_PENDING, None
    else:
        status = STATUS_APPROVED
        if is_super_admin(submitter):
            note = "超管免审"
        elif level == LEVEL_NONE:
            note = "低风险字段免审"
        else:
            note = "无可用审核人，自动通过"

    req = StaffChangeRequest(
        employee_id=staff.employee_id,
        staff_name=staff.name,
        department=staff.department,
        payload=json.dumps(changed, ensure_ascii=False),
        before_snapshot=json.dumps(
            {k: before.get(k) for k in changed}, ensure_ascii=False, default=str,
        ),
        changed_fields=json.dumps(list(changed.keys()), ensure_ascii=False),
        change_summary=build_summary(before, changed),
        review_level=level,
        status=status,
        source=source,
        submitted_by=submitter.employee_id,
        submitted_by_name=submitter.name,
        submitted_at=now,
        applied_at=now,
        review_note=note,
    )
    if not reviewers:
        req.reviewed_by = submitter.employee_id
        req.reviewed_by_name = submitter.name
        req.reviewed_at = now
    db.add(req)
    db.flush()

    if not reviewers:
        # [修复 2026-09-11] 免审（超管提交 / 低风险 / 无可用审核人）时，**延迟生效字段
        # 必须此刻写入主表**——否则没有后续审核动作来触发写入，科室/工种会永远停在旧值。
        deferred = [f for f in changed if f in DEFERRED_FIELDS]
        if deferred:
            values = {f: changed[f] for f in deferred}
            for field, value in values.items():
                setattr(staff, field, value)
            staff.updated_by = submitter.employee_id
            staff.updated_at = utc_now()
            _sync_user_fields(db, staff.employee_id, values)
            db.flush()
            logger.info("免审变更的延迟字段已直接生效: id=%s, 字段=%s", req.id, deferred)

    if reviewers:
        notify_reviewers(db, req, reviewers)
    elif level == LEVEL_NONE and submitter.employee_id != staff.employee_id:
        # [新增 2026-09-15] 免审的个人介绍类变更（改他人）：无需审核，仅通知被修改人
        _notify_intro_updated(db, req, submitter)
    logger.info(
        "人员信息变更已登记: id=%s, 工号=%s, 级别=%s, 审核人=%s, 字段=%s",
        req.id, staff.employee_id, level, reviewers or note, list(changed.keys()),
    )
    return req, reviewers


def notify_reviewers(db: Session, req: StaffChangeRequest, reviewers: list[str]) -> None:
    """站内信通知审核人（带跳转到审核页）

    [调整 2026-09-15] 统一走通知中心（事件：staff_change.submitted），
    管理员可在「通知设置」中开关该提醒、改写文案或调整收件人范围。
    """
    try:
        # 姓名兜底：主表姓名为空时用工号，避免渲染出 "None"
        staff_name = req.staff_name or req.employee_id
        submitter = req.submitted_by_name or req.submitted_by
        level_text = level_label(req.review_level)
        notification_center.emit(
            db, "staff_change.submitted",
            context={
                "提交人": submitter,
                "姓名": staff_name,
                "工号": req.employee_id,
                "科室": req.department,
                "审核级别": level_text,
                "变更内容": req.change_summary,
            },
            recipients=reviewers,
            department=req.department,
            # related_type=staff_change：站内信详情页据此渲染「去审核」按钮
            related_type="staff_change",
            related_id=req.id,
            fallback_title=f"待审核：{staff_name} 的信息变更",
            fallback_content=(
                f"{submitter} 提交了 "
                f"{staff_name}（{req.employee_id} · {req.department}）的信息变更，"
                f"需由{level_text}审核：<br/>{req.change_summary}<br/>"
                f"<b>该变更已立即生效</b>，审核不通过将回滚为修改前的值。"
            ),
        )
    except Exception as e:  # 通知失败不影响主流程
        logger.warning("变更审核通知发送失败 id=%s: %s", req.id, e)


def _notify_intro_updated(db: Session, req: StaffChangeRequest, submitter: User) -> None:
    """[新增 2026-09-15] 个人介绍类字段被**他人**修改后，直接通知被修改人（免审，不派发审核任务）。

    需求：科室管理员等任何有编辑权限的人员修改他人的「个人介绍」
    （备注 / 专业擅长短·标准 / 社会任职 / 荣誉，即 LEVEL_NONE 免审字段）时，
    无需审核、仅通知被修改人知悉（此前该场景完全静默，本人不知自己的介绍被改动）。

    - 改自己：操作人即被修改人，不发送（避免自我打扰）；
    - 走通知中心（事件：staff.intro_updated），可在「通知设置」中开关 / 改文案。
    """
    try:
        operator_name = submitter.name or submitter.employee_id
        staff_name = req.staff_name or req.employee_id
        notification_center.emit(
            db, "staff.intro_updated",
            context={
                "操作人": operator_name,
                "姓名": staff_name,
                "工号": req.employee_id,
                "变更内容": req.change_summary,
            },
            # 显式收件人 = 被修改人本人（explicit 模式）
            recipients=[req.employee_id],
            department=req.department,
            related_type="staff",
            # 站内信详情页据此跳转到人员详情（Staff 主键即工号，无独立 id 字段）
            related_id=int(req.employee_id) if req.employee_id.isdigit() else None,
            fallback_title="您的个人介绍已被修改",
            fallback_content=(
                f"{operator_name} 修改了您的个人介绍"
                f"（{staff_name} · {req.employee_id}）：<br/>{req.change_summary}"
            ),
        )
    except Exception as e:  # 通知失败不影响主流程
        logger.warning("个人介绍修改通知发送失败 id=%s: %s", req.id, e)


def _notify_result(db: Session, req: StaffChangeRequest, *, ok: bool) -> None:
    """审核结果通知提交人 + 被修改人

    [调整 2026-09-15] 统一走通知中心：通过 = staff_change.approved，
    驳回 = staff_change.rejected（含「回滚说明」变量），可分别开关与改文案。
    """
    recipients = {req.submitted_by, req.employee_id}
    recipients.discard(None)
    if not recipients:
        return
    try:
        staff_name = req.staff_name or req.employee_id
        reviewer = req.reviewed_by_name or req.reviewed_by
        related_id = int(req.employee_id) if req.employee_id.isdigit() else None

        if ok:
            notification_center.emit(
                db, "staff_change.approved",
                context={
                    "审核人": reviewer,
                    "姓名": staff_name,
                    "工号": req.employee_id,
                    "变更内容": req.change_summary,
                },
                recipients=list(recipients),
                department=req.department,
                related_type="staff", related_id=related_id,
                fallback_title=f"信息变更已通过：{staff_name}",
                fallback_content=(
                    f"{reviewer} 已通过 "
                    f"{staff_name}（{req.employee_id}）的信息变更：<br/>{req.change_summary}"
                ),
            )
        else:
            rollback = (
                "相关信息已回滚为修改前的值。"
                if req.rolled_back else
                "（该信息在审核期间已被再次修改，未自动回滚，请联系管理员核对）"
            )
            notification_center.emit(
                db, "staff_change.rejected",
                context={
                    "审核人": reviewer,
                    "姓名": staff_name,
                    "工号": req.employee_id,
                    "变更内容": req.change_summary,
                    "驳回原因": req.reject_reason,
                    "回滚说明": rollback,
                },
                recipients=list(recipients),
                department=req.department,
                related_type="staff", related_id=related_id,
                fallback_title=f"信息变更被驳回：{staff_name}",
                fallback_content=(
                    f"{reviewer} 驳回了 "
                    f"{staff_name}（{req.employee_id}）的信息变更：<br/>{req.change_summary}<br/>"
                    f"驳回原因：{req.reject_reason}<br/>{rollback}"
                ),
            )
    except Exception as e:
        logger.warning("变更审核结果通知失败 id=%s: %s", req.id, e)


def _sync_user_fields(db: Session, employee_id: str, fields: dict) -> None:
    """主表回滚时同步 users 表中的姓名/科室（两处都有存储）"""
    if not fields:
        return
    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        return
    if "name" in fields and fields["name"]:
        user.name = fields["name"]
    if "department" in fields and fields["department"]:
        user.department = fields["department"]


# ==================== 冲突检测 ====================


def detect_conflict(req: StaffChangeRequest, staff: Staff | None) -> list[str]:
    """检测「提交后又被他人改动」的字段。

    立即生效字段：当前值应等于提交的新值；
    延迟生效字段：当前值应仍等于提交前的旧值。
    """
    if not staff:
        return []
    payload = json.loads(req.payload or "{}")
    before = json.loads(req.before_snapshot or "{}")
    conflict: list[str] = []
    for field in json.loads(req.changed_fields or "[]"):
        current = getattr(staff, field, None)
        expected = before.get(field) if field in DEFERRED_FIELDS else payload.get(field)
        if (current or None) != (expected or None):
            conflict.append(field)
    return conflict


def _cleanup_photos(req: StaffChangeRequest, *, restored: bool) -> None:
    """照片变更的磁盘文件清理（尽力而为，失败不影响主流程）。

    - 通过/追认（restored=False）→ 删除被替换掉的**旧**照片文件（before_snapshot）；
    - 驳回/撤回回滚（restored=True）→ 删除被驳回的**新**照片文件（payload），
      旧文件在上传时已刻意保留，此刻仍需留在磁盘上供页面显示。
    """
    try:
        fields = json.loads(req.changed_fields or "[]")
        photos = [f for f in fields if f in ("front_photo", "side_photo")]
        if not photos:
            return
        # 回滚后要丢弃的是「新」文件；追认后要丢弃的是「旧」文件
        stale_raw = req.payload if restored else req.before_snapshot
        stale = json.loads(stale_raw or "{}")
        from app.services.upload_service import delete_file
        for f in photos:
            path = stale.get(f)
            if path:
                delete_file(path)
    except Exception as e:
        logger.warning("照片文件清理失败 id=%s: %s", req.id, e)


# ==================== 审核 ====================


def _apply_deferred(db: Session, req: StaffChangeRequest, staff: Staff, actor: User) -> list[str]:
    """把延迟生效字段写入主表（审核通过时调用）"""
    fields = json.loads(req.changed_fields or "[]")
    deferred = [f for f in fields if f in DEFERRED_FIELDS]
    if not deferred:
        return []
    payload = json.loads(req.payload or "{}")
    values = {f: payload.get(f) for f in deferred}
    for field, value in values.items():
        setattr(staff, field, value)
    staff.updated_by = actor.employee_id
    staff.updated_at = utc_now()
    _sync_user_fields(db, staff.employee_id, values)
    return deferred


def approve_request(db: Session, req: StaffChangeRequest, reviewer: User) -> dict:
    """审核通过（追认）：延迟生效字段此刻写入主表。"""
    if req.status != STATUS_PENDING:
        raise ValueError("该变更已被处理，请刷新后重试")
    if not can_review(db, req, reviewer):
        raise ValueError("无权审核该变更")

    staff = db.query(Staff).filter(Staff.employee_id == req.employee_id).first()
    if not staff:
        raise ValueError("人员不存在，无法审核")

    conflict = detect_conflict(req, staff)
    applied = _apply_deferred(db, req, staff, reviewer)

    req.status = STATUS_APPROVED
    req.reviewed_by = reviewer.employee_id
    req.reviewed_by_name = reviewer.name
    req.reviewed_at = utc_now()
    req.conflict_fields = json.dumps(conflict, ensure_ascii=False) if conflict else None
    if conflict:
        req.rollback_note = (
            "审核时检测到以下字段在提交后又被修改：" +
            "、".join(FIELD_LABELS.get(f, f) for f in conflict)
        )
    db.flush()
    _cleanup_photos(req, restored=False)
    _notify_result(db, req, ok=True)
    logger.info("变更审核通过: id=%s, 审核人=%s, 追认字段=%s", req.id, reviewer.employee_id, applied)
    return {"message": "已通过", "applied_deferred": applied, "conflict_fields": conflict}


def reject_request(db: Session, req: StaffChangeRequest, reviewer: User, reason: str) -> dict:
    """审核驳回：回滚到提交前旧值（冲突时仅提示，不覆盖他人改动）。"""
    text = (reason or "").strip()
    if not text:
        raise ValueError("请填写驳回原因")
    if req.status != STATUS_PENDING:
        raise ValueError("该变更已被处理，请刷新后重试")
    if not can_review(db, req, reviewer):
        raise ValueError("无权审核该变更")

    staff = db.query(Staff).filter(Staff.employee_id == req.employee_id).first()
    conflict = detect_conflict(req, staff)
    rolled_back: list[str] = []

    if staff:
        fields = json.loads(req.changed_fields or "[]")
        before = json.loads(req.before_snapshot or "{}")
        # 冲突字段跳过（避免覆盖他人在提交后的合法修改）；延迟字段未生效，无需回滚
        rollback = [f for f in fields if f not in conflict and f not in DEFERRED_FIELDS]
        values = {f: before.get(f) for f in rollback}
        for field, value in values.items():
            setattr(staff, field, value)
        if rollback:
            staff.updated_by = reviewer.employee_id
            staff.updated_at = utc_now()
            _sync_user_fields(db, staff.employee_id, values)
        rolled_back = rollback

    req.status = STATUS_REJECTED
    req.reject_reason = text[:MAX_REASON_LEN]
    req.reviewed_by = reviewer.employee_id
    req.reviewed_by_name = reviewer.name
    req.reviewed_at = utc_now()
    req.rolled_back = bool(rolled_back)
    req.conflict_fields = json.dumps(conflict, ensure_ascii=False) if conflict else None
    if conflict:
        req.rollback_note = (
            "以下字段在提交后已被再次修改，未自动回滚，请人工核对：" +
            "、".join(FIELD_LABELS.get(f, f) for f in conflict)
        )
    db.flush()
    if rolled_back:
        _cleanup_photos(req, restored=True)
    _notify_result(db, req, ok=False)
    logger.info("变更审核驳回: id=%s, 审核人=%s, 回滚字段=%s, 冲突=%s",
                req.id, reviewer.employee_id, rolled_back, conflict)
    return {"message": "已驳回", "rolled_back": rolled_back, "conflict_fields": conflict}


def cancel_request(db: Session, req: StaffChangeRequest, actor: User) -> dict:
    """提交人撤回：与驳回同等的回滚语义（无需审核人）。"""
    if req.status != STATUS_PENDING:
        raise ValueError("该变更已被处理，无法撤回")
    if req.submitted_by != actor.employee_id and not is_super_admin(actor):
        raise ValueError("只能撤回自己提交的变更")

    staff = db.query(Staff).filter(Staff.employee_id == req.employee_id).first()
    conflict = detect_conflict(req, staff)
    rolled_back: list[str] = []
    if staff:
        fields = json.loads(req.changed_fields or "[]")
        before = json.loads(req.before_snapshot or "{}")
        rollback = [f for f in fields if f not in conflict and f not in DEFERRED_FIELDS]
        values = {f: before.get(f) for f in rollback}
        for field, value in values.items():
            setattr(staff, field, value)
        if rollback:
            staff.updated_by = actor.employee_id
            staff.updated_at = utc_now()
            _sync_user_fields(db, staff.employee_id, values)
        rolled_back = rollback

    req.status = STATUS_CANCELLED
    req.reviewed_by = actor.employee_id
    req.reviewed_by_name = actor.name
    req.reviewed_at = utc_now()
    req.review_note = "提交人撤回"
    req.rolled_back = bool(rolled_back)
    if conflict:
        req.rollback_note = (
            "以下字段在提交后已被再次修改，未自动回滚，请人工核对：" +
            "、".join(FIELD_LABELS.get(f, f) for f in conflict)
        )
    db.flush()
    if rolled_back:
        _cleanup_photos(req, restored=True)
    logger.info("变更已撤回: id=%s, 操作人=%s, 回滚字段=%s", req.id, actor.employee_id, rolled_back)
    return {"message": "已撤回", "rolled_back": rolled_back}


# ==================== 查询 ====================


def serialize(req: StaffChangeRequest, viewer: User | None = None, db: Session | None = None) -> dict:
    """对外序列化（不下发原始 payload 全量，仅摘要 + 字段名）"""
    can = bool(viewer and db and can_review(db, req, viewer))
    return {
        "id": req.id,
        "employee_id": req.employee_id,
        "staff_name": req.staff_name,
        "department": req.department,
        "change_summary": req.change_summary,
        "changed_fields": json.loads(req.changed_fields or "[]"),
        "changed_labels": [FIELD_LABELS.get(f, f) for f in json.loads(req.changed_fields or "[]")],
        "review_level": req.review_level,
        "level_label": level_label(req.review_level),
        "status": req.status,
        "source": req.source,
        "submitted_by": req.submitted_by,
        "submitted_by_name": req.submitted_by_name,
        # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
        "submitted_at": to_iso_utc(req.submitted_at),
        "reviewed_by": req.reviewed_by,
        "reviewed_by_name": req.reviewed_by_name,
        "reviewed_at": to_iso_utc(req.reviewed_at),
        "reject_reason": req.reject_reason,
        "review_note": req.review_note,
        "rolled_back": req.rolled_back,
        "rollback_note": req.rollback_note,
        "conflict_fields": json.loads(req.conflict_fields) if req.conflict_fields else [],
        # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
        "reminded_at": to_iso_utc(req.reminded_at),
        "escalated_at": to_iso_utc(req.escalated_at),
        "can_review": can,
    }


def list_reviewable(
    db: Session, user: User, *, status: str = STATUS_PENDING, page: int = 1, page_size: int = 20,
) -> tuple[list[StaffChangeRequest], int]:
    """待我审核的变更列表（超管=全部；科室管理员=管辖科室 & 科室级）

    - 「待审核」页签排除自己提交的（禁止自审）；
    - 已处理页签作为历史台账，不做该排除，便于超管查看全量留痕（含超管免审记录）。
    """
    q = db.query(StaffChangeRequest)
    if status:
        q = q.filter(StaffChangeRequest.status == status)
    if status == STATUS_PENDING:
        q = q.filter(StaffChangeRequest.submitted_by != user.employee_id)
    if not is_super_admin(user):
        allowed = _managed_department_names(db, user)
        if not allowed:
            return [], 0
        q = q.filter(
            StaffChangeRequest.review_level == LEVEL_DEPT,
            StaffChangeRequest.department.in_(allowed),
        )
    total = q.count()
    items = (
        q.order_by(StaffChangeRequest.submitted_at.desc())
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def pending_count(db: Session, user: User) -> int:
    """待审数量（菜单角标）"""
    _, total = list_reviewable(db, user, status=STATUS_PENDING, page=1, page_size=1)
    return total


def list_mine(
    db: Session, user: User, *, status: str | None = None, page: int = 1, page_size: int = 20,
) -> tuple[list[StaffChangeRequest], int]:
    """我提交的变更（个人中心「我的提交」）"""
    q = db.query(StaffChangeRequest).filter(
        StaffChangeRequest.submitted_by == user.employee_id,
    )
    if status:
        q = q.filter(StaffChangeRequest.status == status)
    total = q.count()
    items = (
        q.order_by(StaffChangeRequest.submitted_at.desc())
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def pending_map(db: Session, employee_ids: list[str]) -> dict[str, list[StaffChangeRequest]]:
    """批量取待审变更（人员列表/详情页的「待审核」提示用）"""
    ids = [i for i in employee_ids if i]
    if not ids:
        return {}
    rows = (
        db.query(StaffChangeRequest)
        .filter(
            StaffChangeRequest.status == STATUS_PENDING,
            StaffChangeRequest.employee_id.in_(ids),
        )
        .order_by(StaffChangeRequest.submitted_at.desc())
        .all()
    )
    out: dict[str, list[StaffChangeRequest]] = {}
    for r in rows:
        out.setdefault(r.employee_id, []).append(r)
    return out


def pending_badge(db: Session, rows: list[StaffChangeRequest]) -> dict | None:
    """把某人的多条待审变更压缩为前端展示用的一段提示"""
    if not rows:
        return None
    latest = rows[0]
    return {
        "count": len(rows),
        "id": latest.id,
        "review_level": latest.review_level,
        "level_label": level_label(latest.review_level),
        "change_summary": latest.change_summary,
        "changed_labels": [FIELD_LABELS.get(f, f) for f in json.loads(latest.changed_fields or "[]")],
        "submitted_by_name": latest.submitted_by_name,
        # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
        "submitted_at": to_iso_utc(latest.submitted_at),
        "escalated": bool(latest.escalated_at),
    }


# ==================== 超时提醒 / 升级 ====================


def sweep_overdue(db: Session) -> dict:
    """扫描超时未审的变更：24h 提醒审核人，72h 升级全部超管。

    惰性执行（列表/角标接口调用时触发一次 + 启动时一次），
    避免为低频内部系统引入常驻调度线程。
    """
    now = utc_now()
    remind_line = now - timedelta(hours=REMIND_AFTER_HOURS)
    escalate_line = now - timedelta(hours=ESCALATE_AFTER_HOURS)
    pending = db.query(StaffChangeRequest).filter(
        StaffChangeRequest.status == STATUS_PENDING,
    ).all()
    reminded = escalated = 0

    for req in pending:
        if not req.submitted_at or req.escalated_at:
            continue
        if req.submitted_at <= escalate_line:
            req.review_level = LEVEL_ADMIN
            req.escalated_at = now
            reviewers = resolve_reviewers(
                db, department=req.department, level=LEVEL_ADMIN,
                submitter_id=req.submitted_by,
            )
            if reviewers:
                try:
                    # [调整 2026-09-15] 走通知中心（事件：staff_change.overdue_escalated）
                    _name = req.staff_name or req.employee_id
                    _submitter = req.submitted_by_name or req.submitted_by
                    notification_center.emit(
                        db, "staff_change.overdue_escalated",
                        context={
                            "提交人": _submitter,
                            "姓名": _name,
                            "工号": req.employee_id,
                            "科室": req.department,
                            "超时小时": ESCALATE_AFTER_HOURS,
                            "变更内容": req.change_summary,
                        },
                        recipients=reviewers,
                        department=req.department,
                        related_type="staff_change",
                        related_id=req.id,
                        fallback_title=f"审核超时升级：{_name} 的信息变更",
                        fallback_content=(
                            f"{_submitter} 提交的 "
                            f"{_name}（{req.employee_id} · {req.department}）信息变更"
                            f"已超过 {ESCALATE_AFTER_HOURS} 小时未审核，现升级由超级管理员处理："
                            f"<br/>{req.change_summary}"
                        ),
                    )
                except Exception as e:
                    logger.warning("超时升级通知失败 id=%s: %s", req.id, e)
            escalated += 1
        elif not req.reminded_at and req.submitted_at <= remind_line:
            req.reminded_at = now
            reviewers = resolve_reviewers(
                db, department=req.department, level=req.review_level,
                submitter_id=req.submitted_by,
            )
            if reviewers:
                try:
                    # [调整 2026-09-15] 走通知中心（事件：staff_change.overdue_reminder）
                    notification_center.emit(
                        db, "staff_change.overdue_reminder",
                        context={
                            "姓名": req.staff_name or req.employee_id,
                            "超时小时": REMIND_AFTER_HOURS,
                            "变更内容": req.change_summary,
                        },
                        recipients=reviewers,
                        department=req.department,
                        related_type="staff_change",
                        related_id=req.id,
                        fallback_title=f"待审核提醒：{req.staff_name or req.employee_id} 的信息变更",
                        fallback_content=(
                            f"您有一项待审核的人员信息变更已超过 {REMIND_AFTER_HOURS} 小时："
                            f"<br/>{req.change_summary}"
                        ),
                    )
                except Exception as e:
                    logger.warning("超时提醒通知失败 id=%s: %s", req.id, e)
            reminded += 1

    if reminded or escalated:
        db.commit()
        logger.info("变更审核超时扫描：提醒 %s 条，升级 %s 条", reminded, escalated)
    return {"reminded": reminded, "escalated": escalated}
