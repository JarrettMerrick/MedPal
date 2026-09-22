# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
import re
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.audit_log import ModificationHistory
from app.models.user import User
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import utc_now, to_iso_utc

# [修复 2026-09-19] Logger 提升为模块级常量。
# 原先在 record_audit 内反复执行 `import logging` + `logging.getLogger("audit")`，
# 既不符合「Logger 应为模块级」的规范，也在异常路径上产生不必要的导入开销。
logger = logging.getLogger("audit")

# 审计详情中的敏感字段脱敏。
# audit detail 由各调用方自由拼接（如 f"rule={template}"），无法保证不含口令等机密，
# 故在**落库与打日志之前**统一兜底脱敏，作为最后一道防线。
_SENSITIVE_RE = re.compile(
    r"(password|passwd|pwd|token|secret|口令|密码)\s*[=:]\s*[^\s,;]+",
    re.IGNORECASE,
)


def mask_sensitive(text: str | None) -> str | None:
    """把 detail 中「password=xxx」一类的片段替换为「password=***」。

    仅做格式级兜底：命中「关键字 + 分隔符 + 非空白值」即脱敏，
    正常业务字段（如 ip=、filename=）不受影响。
    """
    if not text:
        return text
    return _SENSITIVE_RE.sub(lambda m: f"{m.group(1)}=***", text)


def record_modification(
    db: Session,
    entity_type: str,
    entity_id: str,
    modified_by: str,
    change_summary: str = None,
    ip_address: str = None,
) -> ModificationHistory:
    """记录一次修改操作"""
    record = ModificationHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        modified_by=modified_by,
        modified_at=utc_now(),
        change_summary=change_summary,
    )
    db.add(record)
    db.flush()

    # [修复 2026-09-01] 双写到 SystemLog 表，使数据修改记录在系统日志中可查
    try:
        from app.models.system_log import SystemLog as SystemLogModel
        ENTITY_TYPE_LABELS = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政", "staff": "人员", "department": "科室"}
        entity_label = ENTITY_TYPE_LABELS.get(entity_type, entity_type)
        content = f"[{entity_label}修改] {entity_id}: {change_summary}" if change_summary else f"[{entity_label}修改] {entity_id}"
        if len(content) > 500:
            content = content[:500] + "..."
        sys_log = SystemLogModel(
            level="INFO",
            category="operation",
            operator=modified_by,
            content=content,
            ip_address=ip_address,
        )
        db.add(sys_log)
        db.flush()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass。写 SystemLog 失败不应影响主流程
        # （审计属旁路），但完全不留痕会让「审计缺失」无从发现，
        # 故降级为 warning 并带堆栈，兼顾「不阻断」与「可定位」。
        logger.warning(
            "写入系统日志失败（已忽略，不影响主流程）: entity_type=%s",
            entity_type, exc_info=True,
        )

    return record


# [改进/A2] 系统级审计域标识。复用 ModificationHistory 表存放"登录/导出/导入/
# 备份/恢复/制度增删/配置变更"等敏感操作的留痕，entity_type 统一为该值，
# 便于与业务字段级修改历史区分，并在审核列表中过滤掉，避免污染人工确认流程。
AUDIT_ENTITY_TYPE = "audit"


def record_audit(
    db: Session,
    action: str,
    actor: str,
    detail: str = None,
    target: str = None,
    ip_address: str = None,
) -> ModificationHistory:
    """记录一次系统级敏感操作审计（A2）。

    参数：
      - action: 操作类型标识（如 login/login_failed/logout/export/import/backup/
        restore/regulation_create/regulation_delete/config_update）。
      - actor: 操作人工号；匿名/未知时传占位值。
      - detail: 操作详情（目标、IP、结果等），会与 action 一并写入摘要。
      - target: 操作目标标识（如备份文件名、制度ID），写入 entity_id 便于检索。
      - ip_address: 客户端 IP 地址，直接写入 SystemLog 的 ip_address 字段。

    说明：复用 ModificationHistory，字段长度受限（entity_id<=50, modified_by<=20），
    故做截断保护；写入后同时输出到应用日志，保证即使数据库被篡改仍有日志留痕。
    """
    # [修复 2026-09-19] 删除函数内的 `import logging`（logger 已提升为模块级常量）。
    # 同时统一脱敏：detail 由各调用方自由拼接，无法保证不含口令等机密，
    # 在**拼接摘要、落库、打日志之前**做一次兜底，避免三处各漏一次。
    detail = mask_sensitive(detail)

    entity_id_val = (target or action or "")[:50]
    actor_val = (actor or "anonymous")[:20]
    summary = f"[{action}] {detail}" if detail else f"[{action}]"
    if len(summary) > 500:
        summary = summary[:500] + "..."

    record = ModificationHistory(
        entity_type=AUDIT_ENTITY_TYPE,
        entity_id=entity_id_val,
        modified_by=actor_val,
        modified_at=utc_now(),
        change_summary=summary,
    )
    db.add(record)
    db.flush()
    # 双写日志，便于实时监控与事后追溯。
    # [修复 2026-09-19] ① 改用模块级 logger（原先每次调用都 import + getLogger）；
    # ② detail 截断到 500 字，与入库口径一致，避免超长内容拖大日志体积
    #    （detail 已在上文统一脱敏）。
    logger.info(
        "AUDIT %s by=%s target=%s detail=%s",
        action, actor_val, entity_id_val, (detail or "")[:500],
    )

    # [修复 2026-09-01] 双写到 SystemLog 表，支持系统日志查询/导出功能
    try:
        from app.models.system_log import SystemLog as SystemLogModel
        # 优先使用传入的 ip_address 参数，其次从 detail 中解析（兼容旧调用）
        ip_val = ip_address
        if not ip_val and detail and "ip=" in detail:
            try:
                ip_val = detail.split("ip=")[1].split()[0]
            except (IndexError, AttributeError) as e:
                # [修正 2026-09-21 / 代码质量审计 Q-3] 原为静默 pass。
                # 这是"从 detail 文本里尽力抽取 IP"的**可选**动作，失败后 ip_val
                # 保持 None，不影响审计记录本身 —— 因此不需要警告级日志。
                # 但完全静默会让"IP 为什么是空"无从解释，故降为 debug 留痕。
                logger.debug("从 detail 中解析 IP 失败（不影响留痕）: %s: %s", type(e).__name__, e)

        log_level = "INFO"
        log_category = "operation"
        if action in ("login_failed", "restore_failed", "error"):
            log_level = "ERROR"
            log_category = "error"
        elif action in ("disk_warning", "db_warning", "wal_warning"):
            log_level = "WARN"
            log_category = "system"
        elif action.startswith("system_") or action.startswith("auto_"):
            log_category = "system"

        sys_log = SystemLogModel(
            level=log_level,
            category=log_category,
            operator=actor_val if actor_val != "anonymous" else None,
            content=summary,
            ip_address=ip_val,
            details=detail,
        )
        db.add(sys_log)
        db.flush()
    except Exception:
        # [修复 2026-09-19] 同上：审计写入失败不应阻断主流程，但必须留痕
        logger.warning(
            "写入系统日志失败（已忽略，不影响主流程）: action=%s", action,
            exc_info=True,
        )

    return record


def audit_action(
    db: Session,
    action: str,
    actor: str,
    request=None,
    detail: str = None,
    target: str = None,
) -> bool:
    """审计留痕统一助手（对应审计问题 25）。

    项目内大量重复如下样板代码：
        try:
            client_ip = request.client.host if request and request.client else None
            record_audit(db, action, actor, detail=..., target=..., ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()

    该样板容易漏掉统一的 IP 获取（确有 5 处直接手写 request.client.host，
    反向代理后记录成代理 IP 而失真，见问题24），且异常被静默吞掉难以排查。

    本助手统一封装：IP 统一走 get_client_ip、detail 自动附带 ip=、
    异常统一记日志并 rollback。返回是否写入成功。
    """
    import logging
    from app.utils import get_client_ip

    client_ip = get_client_ip(request)
    composed = f"{detail}, ip={client_ip}" if detail else f"ip={client_ip}"
    try:
        record_audit(db, action, actor, detail=composed, target=target, ip_address=client_ip)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        # [修正 2026-09-19] 统一使用模块级 audit logger（原先此处临时 getLogger(__name__)，
        # 会落到 app.services.audit_service 名下，与本模块其他审计日志分散在两个 logger 中）
        logger.warning(
            f"审计留痕失败 action={action} actor={actor}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return False


def build_change_summary(old_data: dict, new_data: dict, field_labels: dict = None) -> str:
    """比较新旧数据，生成修改内容摘要"""
    if field_labels is None:
        field_labels = {}

    changes = []
    for key, new_value in new_data.items():
        if key in old_data and old_data[key] != new_value:
            label = field_labels.get(key, key)
            old_val = old_data[key] or '(空)'
            new_val = new_value or '(空)'
            changes.append(f"{label}: {old_val} → {new_val}")

    if not changes:
        return "更新操作"

    # 如果修改内容太长，截断
    summary = "；".join(changes)
    if len(summary) > 500:
        summary = summary[:500] + "..."
    return summary


# ==================== 修改历史查询（人员详情页 / 科室详情页「修改历史」入口） ====================
# [新增 2026-09-15] 需求：两个详情页在「编辑」左侧提供修改历史查询，展示所修改的字段
# 及修改前/修改后的对比，只展示最近三次修改。
#
# 数据来源保持单一：仍读取 record_modification 写入的 modification_history 表，
# 仅做「读取 + 解析」，不改变任何写入逻辑。
# 之所以解析 change_summary 而不是新增结构化列：该表已有历史数据，
# 解析方案对存量记录同样生效，避免引入数据库结构变更与历史数据空白。

#: 摘要中各字段变更之间的分隔符（与 build_change_summary 保持同源）
_CHANGE_SEP = "；"
#: 字段名与值之间的冒号（半角/全角均兼容），旧值用一个非贪婪匹配到第一个箭头
_FIELD_CHANGE_RE = re.compile(
    r"^(?P<label>[^:：]+)[:：]\s*(?P<before>.*?)\s*→\s*(?P<after>.*)$",
    re.S,
)
#: build_change_summary 对空值使用的占位文案
_EMPTY_PLACEHOLDER = "(空)"
#: 无任何字段变化时的占位摘要，对使用者无信息量，直接过滤
_NO_CHANGE_TEXT = "更新操作"


def parse_change_summary(change_summary: str):
    """把 change_summary 文本拆成「字段级前后对比」与「说明性文字」两部分。

    build_change_summary 生成的格式为「标签: 旧值 → 新值；标签2: 旧值 → 新值」，
    但同一个字段里也可能写入「新增人员: xxx(100001) 工种=doctor」这类没有箭头、
    或「特色技术(新增1/删除0/修改2)」这类整体性描述，因此这里做二分处理：

    - 能匹配「标签: 旧 → 新」的，作为字段级对比返回，供前端渲染三列表格；
    - 匹配不上的，归入 notes 原样展示，避免丢失信息；
    - 返回值中的空值统一转为空字符串，由前端决定显示为「（空）」，
      避免把 '(空)' 这个内部占位文案透出到界面上。

    返回 (fields, notes)：
        fields: [{"label": "姓名", "before": "张三", "after": "李四"}, ...]
        notes:  ["新增人员: 张三(100001) 工种=doctor", ...]
    """
    if not change_summary:
        return [], []

    fields = []
    notes = []
    for part in str(change_summary).split(_CHANGE_SEP):
        text = part.strip()
        if not text:
            continue

        matched = _FIELD_CHANGE_RE.match(text)
        if matched:
            before = matched.group("before").strip()
            after = matched.group("after").strip()
            fields.append({
                "label": matched.group("label").strip(),
                "before": "" if before == _EMPTY_PLACEHOLDER else before,
                "after": "" if after == _EMPTY_PLACEHOLDER else after,
            })
        elif text != _NO_CHANGE_TEXT:
            notes.append(text)

    return fields, notes


def get_modification_history(
    db: Session,
    entity_type: str,
    entity_id: str,
    limit: int = 3,
) -> dict:
    """查询某实体的最近 N 次修改记录（按修改时间倒序），并解析为字段级前后对比。

    entity_type 与 record_modification 的取值保持一致：'staff' / 'department'；
    entity_id 统一按字符串比较（人员为工号，科室为数字 ID 的字符串形式）。

    返回值：
        {
          "items": [{
              "id": 1,
              "modified_at": "2026-09-15T02:30:00",   # UTC，前端按本地时区转换显示
              "modified_by": "100001",                 # 操作人工号
              "modified_by_name": "张三",               # 操作人姓名（查不到时回落为工号）
              "fields": [{"label": ..., "before": ..., "after": ...}],
              "notes": ["..."],
              "summary": "原始摘要文本",
          }, ...],
          "total": 12,   # 该实体累计修改次数（用于提示「仅显示最近 3 次」）
        }
    """
    base_query = db.query(ModificationHistory).filter(
        ModificationHistory.entity_type == entity_type,
        ModificationHistory.entity_id == str(entity_id),
    )

    # 总条数用于前端提示「共 N 条，仅显示最近 limit 条」
    total = base_query.count()

    rows = (
        base_query
        # 同一时刻可能写入多条（如批量操作），用 id 兜底保证顺序稳定
        .order_by(ModificationHistory.modified_at.desc(), ModificationHistory.id.desc())
        .limit(limit)
        .all()
    )

    # 操作人姓名批量解析：modified_by 存的是工号，直接展示工号对使用者不友好
    operator_ids = {row.modified_by for row in rows if row.modified_by}
    name_map = {}
    if operator_ids:
        users = (
            db.query(User.employee_id, User.name)
            .filter(User.employee_id.in_(operator_ids))
            .all()
        )
        name_map = {employee_id: name for employee_id, name in users}

    items = []
    for row in rows:
        fields, notes = parse_change_summary(row.change_summary)
        items.append({
            "id": row.id,
            # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
            "modified_at": to_iso_utc(row.modified_at),
            "modified_by": row.modified_by,
            "modified_by_name": name_map.get(row.modified_by) or row.modified_by or "系统",
            "fields": fields,
            "notes": notes,
            "summary": row.change_summary or "",
        })

    return {"items": items, "total": total}
