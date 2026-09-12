# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.audit_log import ModificationHistory
from app.models.user import User
from app.utils import utc_now


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
        pass  # 不影响主流程

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
    import logging

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
    # 双写日志，便于实时监控与事后追溯
    logging.getLogger("audit").info("AUDIT %s by=%s target=%s detail=%s",
                                    action, actor_val, entity_id_val, detail or "")

    # [修复 2026-09-01] 双写到 SystemLog 表，支持系统日志查询/导出功能
    try:
        from app.models.system_log import SystemLog as SystemLogModel
        # 优先使用传入的 ip_address 参数，其次从 detail 中解析（兼容旧调用）
        ip_val = ip_address
        if not ip_val and detail and "ip=" in detail:
            try:
                ip_val = detail.split("ip=")[1].split()[0]
            except (IndexError, AttributeError):
                pass

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
        pass  # 不影响主流程

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
        logging.getLogger(__name__).warning(
            f"审计留痕失败 action={action} actor={actor}: {type(e).__name__}: {e}"
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
