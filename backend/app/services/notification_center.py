# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""可配置通知中心（事件注册表 + 规则引擎）

[新增 2026-09-15]
==================
把此前散落在各业务调用点（notify_super_admins / create_notification）的
「系统通知」统一收敛到一个出口 `emit()`，并让管理员可在
「系统设置 → 通知设置」中按**业务事件**配置：

    - 是否发送（事件级开关）
    - 标题 / 正文文案（支持 {变量}，正文允许简单 HTML）
    - 收件人范围（沿用业务内置默认，或自定义规则）

分层：
    1. 事件注册表（`notification_events.py`）：代码维护的**默认值**；
    2. 规则覆盖（`notification_rules` 表）：只存管理员**改过的部分**。

因此：未配置任何规则时，通知的文案与收件人与改造前逐字一致；管理员可只调
其中一项，其余自动继承默认。新增事件只需在注册表登记，设置页自动出现该项。

安全约定：
    - 变量值默认 `html.escape` 后再插入模板（业务值来自数据库，防注入）；
    - 注册表可将个别变量标记为 raw（如系统告警正文），此时保留 HTML 但过滤
      危险片段（script / iframe / on* 等）；
    - 模板本体同样过滤危险片段；标题额外剥除全部 HTML 标签；
    - 渲染后残留未解析的 `{变量}`（拼写错误 / 变量缺失）时记录 warning，
      并在调用点提供兜底文案时自动回退，避免发出半成品文案。

写入约定：与其他服务一致，本模块只 `add/flush` **不 commit**，
由调用方统一提交，保证「业务回滚则通知也不发出」。
"""

import html
import json
import logging
import re

from sqlalchemy.orm import Session

from app.dependencies import (
    ROLE_DEPT_MANAGER, ROLE_SUPER_ADMIN, has_department_access,
)
from app.models.notification_rule import (
    RECIPIENT_MODE_CUSTOM, RECIPIENT_MODE_DEFAULT, NotificationRule,
)
from app.models.user import User
from app.services import message_service
from app.services.notification_events import (
    MODE_MODIFICATION, MODULE_ORDER, actor_fallback_enabled, get_event,
    keep_actor_enabled, list_events,
)
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import utc_now, to_iso_utc

logger = logging.getLogger("notification_center")

# 变量占位符：{中文/字母数字下划线}，长度上限 32（防止恶意超长串）
_TEMPLATE_VAR_RE = re.compile(r"\{([^{}]{1,32})\}")
# 模板本体 / raw 变量需要过滤的危险片段
_DANGEROUS_TEMPLATE_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|style|link|meta|form|input)\b[^>]*>"
    r"|javascript\s*:"
    r"|\son\w+\s*=",
    re.IGNORECASE,
)
# 标题为纯文本：剥除全部标签
_ANY_TAG_RE = re.compile(r"<[^>]*>")

# 模板长度上限（与系统配置的量级保持一致）
MAX_TITLE_LEN = 200
MAX_CONTENT_LEN = 2000

# "未传入"哨兵：区分「不改动」与「清空 / 恢复默认」
UNSET = object()


# ==================== 模板渲染 ====================

def sanitize_template(template: str | None, *, allow_html: bool) -> str:
    """清洗模板本体：过滤危险片段；标题不允许任何 HTML。"""
    raw = "" if template is None else str(template)
    raw = _DANGEROUS_TEMPLATE_RE.sub("", raw)
    if not allow_html:
        raw = _ANY_TAG_RE.sub("", raw)
    return raw.strip()


def render_template(
    template: str, variables: dict | None, raw_keys: set[str] | None = None,
) -> str:
    """把 `{变量}` 替换为取值；未知变量原样保留（便于管理员发现拼写错误）。

    `raw_keys` 中的变量按 HTML 原样插入（仅过滤危险片段），其余一律转义。
    """
    values = variables or {}
    raw = set(raw_keys or ())

    def _sub(match: re.Match) -> str:
        key = match.group(1).strip()
        if key not in values:
            return match.group(0)
        val = values[key]
        text = "" if val is None else str(val)
        if key in raw:
            return _DANGEROUS_TEMPLATE_RE.sub("", text)
        return html.escape(text)

    return _TEMPLATE_VAR_RE.sub(_sub, template or "")


def has_unresolved(text: str) -> bool:
    """渲染结果中是否残留未解析的变量占位符"""
    return bool(_TEMPLATE_VAR_RE.search(text or ""))


# ==================== 规则读写 ====================

def _parse_rules(raw: str | None) -> dict | None:
    """解析规则 JSON（脏数据一律视为 None，退化为默认行为）"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("通知规则 JSON 解析失败，已按默认收件人处理")
        return None
    return data if isinstance(data, dict) else None


def get_rule(db: Session, code: str) -> NotificationRule | None:
    """取事件对应的规则覆盖行（不存在返回 None）"""
    return (
        db.query(NotificationRule)
        .filter(NotificationRule.event_code == (code or "").strip())
        .first()
    )


def effective_config(db: Session, code: str) -> dict:
    """合并「注册表默认」与「规则覆盖」，得到该事件的生效配置"""
    event = get_event(code) or {}
    rule = get_rule(db, code)
    return {
        "event_code": (code or "").strip(),
        "exists": bool(event),
        "enabled": rule.enabled if rule else bool(event.get("default_enabled", True)),
        "title_template": (
            rule.title_template
            if rule and rule.title_template
            else event.get("default_title", "")
        ),
        "content_template": (
            rule.content_template
            if rule and rule.content_template
            else event.get("default_content", "")
        ),
        "recipient_mode": (
            (rule.recipient_mode or RECIPIENT_MODE_DEFAULT) if rule else RECIPIENT_MODE_DEFAULT
        ),
        "recipient_rules": _parse_rules(rule.recipient_rules) if rule else None,
        "customized": rule is not None,
        "is_custom_title": bool(rule and rule.title_template),
        "is_custom_content": bool(rule and rule.content_template),
        "is_custom_recipients": bool(
            rule and (rule.recipient_mode or RECIPIENT_MODE_DEFAULT) == RECIPIENT_MODE_CUSTOM
            and rule.recipient_rules
        ),
        "raw_keys": set(event.get("raw_variables") or ()),
    }


def _serialize_rules(rules: dict | None) -> str | None:
    return json.dumps(rules, ensure_ascii=False) if rules else None


def save_rule(
    db: Session, code: str, *, updated_by: str,
    enabled: bool, title_template: str | None, content_template: str | None,
    recipient_mode: str, recipient_rules: dict | None,
) -> dict:
    """保存（或更新）某事件的规则覆盖。文案传空 = 恢复默认模板。

    校验失败抛 ValueError，由接口层转为 400。
    """
    event = get_event(code)
    if not event:
        raise ValueError("未知的通知事件")
    if recipient_mode not in (RECIPIENT_MODE_DEFAULT, RECIPIENT_MODE_CUSTOM):
        raise ValueError("收件人模式不合法")

    title = sanitize_template(title_template, allow_html=False)
    content = sanitize_template(content_template, allow_html=True)
    if len(title) > MAX_TITLE_LEN:
        raise ValueError(f"标题模板过长（最多 {MAX_TITLE_LEN} 字符）")
    if len(content) > MAX_CONTENT_LEN:
        raise ValueError(f"正文模板过长（最多 {MAX_CONTENT_LEN} 字符）")

    rules = None
    if recipient_mode == RECIPIENT_MODE_CUSTOM:
        rules = validate_recipient_rules(recipient_rules)

    rule = get_rule(db, code)
    if rule is None:
        rule = NotificationRule(event_code=code)
        db.add(rule)
    rule.enabled = bool(enabled)
    rule.title_template = title or None
    rule.content_template = content or None
    rule.recipient_mode = recipient_mode
    rule.recipient_rules = _serialize_rules(rules)
    rule.updated_by = updated_by
    rule.updated_at = utc_now()
    db.flush()
    return effective_config(db, code)


def reset_rule(db: Session, code: str) -> bool:
    """恢复某事件的默认配置（删除覆盖行）"""
    rule = get_rule(db, code)
    if rule is None:
        return False
    db.delete(rule)
    db.flush()
    return True


# ==================== 收件人规则 ====================
#
# 规则结构（存 notification_rules.recipient_rules 的 JSON）：
#     {
#       "include": [
#         {"type": "super_admins"},
#         {"type": "dept_managers", "scope": "event_department"},
#         {"type": "permissions", "value": ["card.upload"], "scope": "all"},
#         {"type": "users", "value": ["060101"]},
#         {"type": "actor"}
#       ],
#       "exclude_actor": true
#     }
# scope="event_department" 表示「仅限与本次事件相关科室（department 参数）
# 有数据范围交集的人」，复用 dependencies.has_department_access，避免越权打扰。

# 供设置页渲染的规则类型清单（needs_value=True 的需前端提供取值）
RECIPIENT_RULE_TYPES = [
    {"type": "super_admins", "label": "超级管理员", "needs_value": False, "scope": False},
    {"type": "dept_managers", "label": "科室管理员", "needs_value": False, "scope": True},
    {"type": "permissions", "label": "拥有指定权限的账号", "needs_value": True,
     "value_kind": "permissions", "scope": True},
    {"type": "roles", "label": "指定角色的账号", "needs_value": True,
     "value_kind": "roles", "scope": False},
    {"type": "departments", "label": "指定科室的账号", "needs_value": True,
     "value_kind": "departments", "scope": False},
    {"type": "users", "label": "指定工号", "needs_value": True,
     "value_kind": "users", "scope": False},
    {"type": "actor", "label": "操作者本人（回执）", "needs_value": False, "scope": False},
]

_VALID_RULE_TYPES = {r["type"] for r in RECIPIENT_RULE_TYPES}
_NEEDS_VALUE_TYPES = {r["type"] for r in RECIPIENT_RULE_TYPES if r["needs_value"]}
# 单条规则最多选择的取值个数（防止误操作把全员塞进自定义规则）
MAX_RULE_VALUES = 200


def validate_recipient_rules(rules: dict | None) -> dict:
    """校验自定义收件人规则，返回归一化结果；不合法抛 ValueError"""
    if not isinstance(rules, dict):
        raise ValueError("收件人规则格式不正确")
    include = rules.get("include")
    if not isinstance(include, list) or not include:
        raise ValueError("请至少添加一条收件人规则")

    normalized: list[dict] = []
    for item in include:
        if not isinstance(item, dict):
            raise ValueError("收件人规则条目格式不正确")
        rtype = str(item.get("type") or "").strip()
        if rtype not in _VALID_RULE_TYPES:
            raise ValueError(f"不支持的收件人规则类型：{rtype or '(空)'}")
        entry: dict = {"type": rtype}
        if rtype in _NEEDS_VALUE_TYPES:
            vals = item.get("value")
            vals = [str(v).strip() for v in vals] if isinstance(vals, list) else (
                [str(vals).strip()] if vals else []
            )
            vals = [v for v in vals if v]
            if not vals:
                raise ValueError("该收件人规则需要选择具体取值")
            if len(vals) > MAX_RULE_VALUES:
                raise ValueError(f"单条规则最多选择 {MAX_RULE_VALUES} 个取值")
            entry["value"] = vals
        if item.get("scope") == "event_department":
            entry["scope"] = "event_department"
        normalized.append(entry)

    return {
        "include": normalized,
        "exclude_actor": bool(rules.get("exclude_actor", True)),
    }


def _scope_filter(
    db: Session, ids: list[str], department: str | None, scope: str | None,
) -> list[str]:
    """按「数据范围覆盖事件相关科室」过滤工号（scope=event_department 时生效）"""
    if scope != "event_department" or not department or not ids:
        return ids
    users = (
        db.query(User)
        .filter(User.employee_id.in_(ids), User.is_active == True)  # noqa: E712
        .all()
    )
    return [u.employee_id for u in users if has_department_access(u, department, db)]


def resolve_custom_recipients(
    db: Session, rules: dict, *,
    department: str | None = None, actor_id: str | None = None,
) -> tuple[list[str], bool]:
    """按自定义规则解析收件人，返回 (工号列表, 是否包含操作者本人)

    任何时候都只包含**启用中**的账号；解析异常按空处理（宁可不发也不越权发）。
    """
    include = (rules or {}).get("include") or []
    collected: list[str] = []
    includes_actor = False

    for item in include:
        rtype = (item or {}).get("type")
        scope = (item or {}).get("scope")
        values = [str(v).strip() for v in ((item or {}).get("value") or [])]
        try:
            if rtype == "super_admins":
                rows = (
                    db.query(User.employee_id)
                    .filter(User.is_active == True, User.role == ROLE_SUPER_ADMIN)  # noqa: E712
                    .all()
                )
                collected += [r[0] for r in rows]
            elif rtype == "dept_managers":
                rows = (
                    db.query(User)
                    .filter(User.is_active == True, User.role == ROLE_DEPT_MANAGER)  # noqa: E712
                    .all()
                )
                ids = [u.employee_id for u in rows]
                if scope == "event_department" and department:
                    ids = [u.employee_id for u in rows if has_department_access(u, department, db)]
                collected += ids
            elif rtype == "permissions":
                ids = message_service.resolve_recipients(db, "permissions", values)
                collected += _scope_filter(db, ids, department, scope)
            elif rtype == "roles":
                collected += message_service.resolve_recipients(db, "roles", values)
            elif rtype == "departments":
                collected += message_service.resolve_recipients(db, "departments", values)
            elif rtype == "users":
                collected += message_service.resolve_recipients(db, "users", values)
            elif rtype == "actor":
                includes_actor = True
                if actor_id:
                    collected.append(actor_id)
        except Exception:  # pragma: no cover - 防御：单条规则异常不影响整体
            logger.exception("解析通知收件人规则失败：type=%s", rtype)

    deduped = message_service.normalize_recipients(collected)
    if (rules or {}).get("exclude_actor", True) and not includes_actor and actor_id:
        deduped = [u for u in deduped if u != actor_id]
    return deduped, includes_actor


def _default_recipients(
    db: Session, event: dict, *,
    recipients, department: str | None, actor_id: str | None,
) -> list[str]:
    """事件「业务内置默认」收件人（未自定义收件人时使用，即改造前的行为）"""
    if event.get("default_recipients_mode") == MODE_MODIFICATION:
        # 延迟导入：modification_notify 的 notify_super_admins 会反向调用本模块
        from app.services.modification_notify import resolve_modification_recipients

        return resolve_modification_recipients(db, department, actor_id)
    return list(recipients or [])


def _actor_fallback_recipients(
    db: Session, event: dict, actor_id: str | None,
) -> list[str]:
    """[新增 2026-09-15] 收件人解析为空时的兜底：回落给操作者本人作为操作回执

    仅在「按默认/自定义规则都没解析出任何收件人」时调用，且要求：
        - 事件允许兜底（actor_fallback_enabled，修改提醒类默认允许）；
        - 操作者本人是**启用中**的账号（离职/停用账号不投递）。
    返回空列表表示仍不发送（与改造前行为一致）。
    """
    if not actor_id or not actor_fallback_enabled(event):
        return []
    exists = (
        db.query(User.employee_id)
        .filter(User.employee_id == actor_id, User.is_active == True)  # noqa: E712
        .first()
    )
    if not exists:
        return []
    # [修正 2026-09-19] INFO → DEBUG：正常的业务回落分支（每次事件发送都可能触发），
    # 不属系统关键信息，降级避免稀释 INFO 通道。
    logger.debug("通知事件 %s 无其他收件人，回落给操作者本人 %s 作为操作回执",
                 event.get("code"), actor_id)
    return [actor_id]


def _drop_excluded(uids: list[str], exclude_ids: list[str] | None) -> list[str]:
    """[新增 2026-09-15] 从收件人中剔除指定工号

    用于「已经通过其他渠道单独收到通知」的去重场景，例如人员信息变更派发了
    审核任务时：审核人收到的「待审核」是任务型通知，而给管理者补发的
    「谁改了什么」是报备型通知，两者语义不同但收件人可能重叠，此处按需剔除。
    """
    if not exclude_ids:
        return list(uids)
    blocked = {str(x) for x in exclude_ids if x}
    return [u for u in uids if str(u) not in blocked]


# ==================== 发送出口 ====================

def emit(
    db: Session,
    event_code: str,
    *,
    context: dict | None = None,
    recipients=None,
    department: str | None = None,
    actor_id: str | None = None,
    exclude_ids: list[str] | None = None,
    related_type: str | None = None,
    related_id: int | None = None,
    fallback_title: str | None = None,
    fallback_content: str | None = None,
) -> int:
    """发送一条业务事件通知，返回实际收件人数（0 = 未发送）

    参数：
        context        模板变量（按注册表 variables 提供）
        recipients     业务内置默认收件人（default_recipients_mode="explicit" 时使用）
        department     事件相关科室（决定「相关科室管理员」范围与数据范围过滤）
        actor_id       操作者工号（用于排除本人打扰）
        exclude_ids    额外剔除的收件人工号（[新增 2026-09-15] 用于去重：例如审核人
                       已单独收到「待审核」任务通知，再补发给管理者的报备通知就
                       不应重复打扰审核人）
        fallback_*     调用点原文案：仅在「事件未登记」或「模板变量缺失」时兜底，
                       保证任何异常都不会把半成品文案发出去

    说明：事件级开关关闭时直接返回 0（业务数据不受影响，仅不产生通知）；
    本函数只 flush 不 commit，与调用方事务保持一致。

    [调整 2026-09-15] 收件人为空时不再直接丢弃：修改提醒类事件会回落给操作者
    本人作为操作回执（见 `_actor_fallback_recipients`），避免「唯一超管操作」
    导致所有修改提醒静默消失。
    """
    code = (event_code or "").strip()
    event = get_event(code)

    # ---- 未登记事件：不静默丢弃，按调用点原文案直接发送 ----
    if not event:
        logger.warning("通知事件未在注册表登记（%s），已按调用点文案直接发送", code)
        targets = _drop_excluded(
            message_service.normalize_recipients(recipients, actor_id), exclude_ids,
        )
        if not targets or not fallback_title:
            return 0
        message_service.create_message(
            db, title=fallback_title, content=fallback_content, recipients=targets,
            msg_type=message_service.MSG_TYPE_SYSTEM,
            related_type=related_type, related_id=related_id,
        )
        return len(targets)

    cfg = effective_config(db, code)
    if not cfg["enabled"]:
        # [修正 2026-09-19] INFO → DEBUG：事件被管理员关闭属正常业务分支
        logger.debug("通知事件 %s 已关闭，未发送", code)
        return 0

    variables = dict(context or {})
    raw_keys = cfg["raw_keys"]

    # ---- 文案渲染（含拼写错误 / 变量缺失兜底）----
    title = render_template(cfg["title_template"], variables, raw_keys)
    content = render_template(cfg["content_template"], variables, raw_keys)
    if has_unresolved(title) or has_unresolved(content):
        logger.warning(
            "通知事件 %s 渲染后仍有未解析变量（请检查模板拼写）：title=%r", code, title,
        )
        if fallback_title is not None:
            title = fallback_title
            content = fallback_content if fallback_content is not None else content

    # ---- 收件人解析 ----
    # keep_actor: 事件声明「不排除操作者本人」（如本人账号安全提醒需回执给本人）。
    # 仅作用于默认收件人分支；自定义规则以 {"type":"actor"} 规则表达同一诉求。
    exclude_actor = None if keep_actor_enabled(event) else actor_id
    if cfg["recipient_mode"] == RECIPIENT_MODE_CUSTOM and cfg["recipient_rules"]:
        targets, _ = resolve_custom_recipients(
            db, cfg["recipient_rules"], department=department, actor_id=actor_id,
        )
        uids = message_service.normalize_recipients(targets)  # 规则内已排除操作者
    else:
        targets = _default_recipients(
            db, event, recipients=recipients, department=department, actor_id=actor_id,
        )
        uids = message_service.normalize_recipients(targets, exclude_actor)

    # ---- 去重：剔除已通过其他渠道单独收到通知的人（如审核人已收到「待审核」） ----
    uids = _drop_excluded(uids, exclude_ids)

    # ---- 兜底：无人可收时回落给操作者本人作为操作回执 ----
    # [修复 2026-09-15] 原实现此处直接丢弃，导致「唯一超管操作」时改动完全无提醒
    if not uids:
        uids = _actor_fallback_recipients(db, event, actor_id)

    if not uids:
        # [修正 2026-09-19] INFO → DEBUG：无有效收件人属正常业务分支
        logger.debug("通知事件 %s 解析后无有效收件人，未发送", code)
        return 0

    message_service.create_message(
        db, title=(title or event.get("label") or "")[:MAX_TITLE_LEN],
        content=content, recipients=uids,
        msg_type=message_service.MSG_TYPE_SYSTEM,
        related_type=related_type or event.get("related_type"),
        related_id=related_id,
    )
    return len(uids)


def preview(
    db: Session,
    code: str,
    *,
    variables: dict | None = None,
    title_template: str | None = None,
    content_template: str | None = None,
    recipient_mode: str | None = None,
    recipient_rules: dict | None = None,
    department: str | None = None,
    actor_id: str | None = None,
) -> dict:
    """干跑预览（不发送）：用于设置页实时查看文案与收件人

    传入模板 / 收件人参数时按「未保存的草稿」试算，便于保存前确认效果。
    """
    event = get_event(code)
    if not event:
        raise ValueError("未知的通知事件")
    cfg = effective_config(db, code)

    vars_ = dict(variables) if variables is not None else dict(event.get("sample") or {})
    title_tpl = (
        cfg["title_template"] if title_template is None
        else sanitize_template(title_template, allow_html=False)
    )
    content_tpl = (
        cfg["content_template"] if content_template is None
        else sanitize_template(content_template, allow_html=True)
    )
    mode = recipient_mode or cfg["recipient_mode"]
    rules = cfg["recipient_rules"] if recipient_rules is None else recipient_rules

    raw_keys = cfg["raw_keys"]
    title = render_template(title_tpl, vars_, raw_keys)[:MAX_TITLE_LEN]
    content = render_template(content_tpl, vars_, raw_keys)

    if mode == RECIPIENT_MODE_CUSTOM and rules:
        try:
            targets, _ = resolve_custom_recipients(
                db, validate_recipient_rules(rules), department=department, actor_id=None,
            )
        except ValueError as exc:
            return {"title": title, "content": content, "error": str(exc),
                    "recipients": {"total": 0, "preview": []}}
    else:
        targets = _default_recipients(
            db, event, recipients=None, department=department, actor_id=None,
        )
    targets = message_service.normalize_recipients(targets)
    return {
        "title": title,
        "content": content,
        "recipients": message_service.describe_recipients(db, targets),
        "mode": mode,
    }


def send_test(db: Session, code: str, user_id: str) -> dict:
    """向当前管理员本人发送一条测试站内信（忽略事件开关，便于开启前先看效果）"""
    event = get_event(code)
    if not event:
        raise ValueError("未知的通知事件")
    cfg = effective_config(db, code)
    variables = dict(event.get("sample") or {})
    title = render_template(cfg["title_template"], variables, cfg["raw_keys"])
    content = render_template(cfg["content_template"], variables, cfg["raw_keys"])
    title = f"[测试] {title}"[:MAX_TITLE_LEN]
    message_service.create_message(
        db, title=title, content=content, recipients=[user_id],
        msg_type=message_service.MSG_TYPE_SYSTEM,
        related_type=event.get("related_type"),
    )
    return {"title": title, "content": content}


def build_settings(db: Session) -> dict:
    """设置页数据：全部事件 + 生效配置 + 默认值 + 可选规则类型"""
    items: list[dict] = []
    for event in list_events():
        cfg = effective_config(db, event["code"])
        rule = get_rule(db, event["code"])
        # [新增 2026-09-15] 默认收件人口径需说明「无人可收时的兜底」，否则管理员会以为
        # 「只有一个超管账号」时这类通知注定发不出去
        hint = event["default_recipient_hint"]
        if actor_fallback_enabled(event):
            hint = f"{hint}；无人可收时回落给操作者本人（操作回执）"
        items.append({
            "code": event["code"],
            "module": event["module"],
            "label": event["label"],
            "description": event["description"],
            "default_enabled": event["default_enabled"],
            "enabled": cfg["enabled"],
            "customized": cfg["customized"],
            "is_custom_title": cfg["is_custom_title"],
            "is_custom_content": cfg["is_custom_content"],
            "is_custom_recipients": cfg["is_custom_recipients"],
            "default_recipient_hint": hint,
            "actor_fallback": actor_fallback_enabled(event),
            "default_title": event["default_title"],
            "default_content": event["default_content"],
            "title_template": cfg["title_template"],
            "content_template": cfg["content_template"],
            "recipient_mode": cfg["recipient_mode"],
            "recipient_rules": cfg["recipient_rules"],
            "variables": [
                {"name": name, "desc": desc}
                for name, desc in (event.get("variables") or {}).items()
            ],
            "sample": event.get("sample") or {},
            "updated_by": rule.updated_by if rule else None,
            # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
            "updated_at": to_iso_utc(rule.updated_at) if rule else None,
        })
    return {
        "events": items,
        "modules": MODULE_ORDER,
        "rule_types": RECIPIENT_RULE_TYPES,
        "limits": {"title": MAX_TITLE_LEN, "content": MAX_CONTENT_LEN},
    }
