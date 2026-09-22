# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""系统日志接口

[调整 2026-09-11] 「信息修改」功能整体下线
========================================
原 `/api/audit/modifications/*`（待确认 / 已确认 / 确认动作）与
`/api/audit/{entity_type}/{entity_id}`（实体变更历史）已全部删除，
相关能力统一由「站内信」承担：
    - 人员/科室等信息修改时，通过站内信把「变更摘要」推送给
      超级管理员 + 相关科室管理员（见 services/modification_notify.py）；
    - 收件人用站内信自带的已读 / 星标 / 归档 / 自定义标签完成"已知悉"标记。

本路由现保留**系统日志**相关接口（查询 / 导出 / 清理，权限 system.audit）。

[新增 2026-09-15] 追溯性查询回归
================================
新增 `GET /api/audit/history/{entity_type}/{entity_id}`：人员 / 科室详情页的
「修改历史」按钮用它读取最近三次修改的字段级前后对比。
与原 `/api/audit/{entity_type}/{entity_id}` 的区别：
    - 只读、不做「确认 / 知悉」动作，不恢复已被站内信替代的信息修改流程；
    - 只返回最近 3 条（需求指定），并按详情页的权限与数据范围校验访问资格。
字段级修改留痕仍由 services/audit_service.record_modification 写入（同时双写 SystemLog）。
"""

from datetime import timedelta
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

# [新增 2026-09-19] 导出/清理系统日志属敏感操作，需按日志规范留痕
from app.services.audit_service import record_audit
from app.utils import get_client_ip

from app.database import get_db
from app.dependencies import (
    get_current_user,
    has_permission,
    can_access_staff,
    has_department_access,
    PERM_SYSTEM_AUDIT,
    PERM_STAFF_VIEW,
    PERM_DEPT_VIEW,
    # [新增 2026-09-15] 修改历史独立权限（默认仅超级管理员拥有）
    PERM_STAFF_VIEW_HISTORY,
    PERM_DEPT_VIEW_HISTORY,
)
from app.models.department import Department
from app.models.staff import Staff
from app.models.system_log import SystemLog
from app.models.user import User
from app.services.audit_service import get_modification_history
# [统一时间口径] API 时间字段用 to_iso_utc；导出产物用 to_beijing_str；
# 日期筛选边界用 beijing_date_start_utc
from app.utils import utc_now, to_iso_utc, to_beijing_str, beijing_date_start_utc
from app.services.excel_safety import append_safe

router = APIRouter(prefix="/api/audit", tags=["系统日志"])

CATEGORY_LABELS = {"operation": "操作日志", "system": "系统日志", "error": "错误日志"}
LEVEL_LABELS = {"INFO": "信息", "WARN": "警告", "ERROR": "错误"}

#: [新增 2026-09-15] 修改历史返回条数：需求要求「只保留最近三次修改」，
#: 故默认值与上限同为 3（保留 limit 入参是为了让该口径有唯一可调入口）。
HISTORY_LIMIT = 3


@router.get("/history/{entity_type}/{entity_id}")
def get_entity_modification_history(
    entity_type: str,
    entity_id: str,
    limit: int = Query(HISTORY_LIMIT, ge=1, le=HISTORY_LIMIT, description="返回最近几条修改记录（最多 3 条）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询人员 / 科室的最近修改记录（含字段级修改前 / 修改后对比）

    [新增 2026-09-15] 供人员详情页、科室详情页的「修改历史」按钮调用。

    权限与数据范围：
        - staff：需 staff.view + staff.view_history（修改历史，默认仅超管），
          本人可查自己，查他人需在其科室 + 工种数据范围内；
        - department：需 department.view + department.view_history（修改历史，默认仅超管），
          且该科室在其数据范围内。
    固定只返回最近 3 条（按修改时间倒序），更早的记录请通过系统日志追溯。
    """
    if entity_type == "staff":
        if not has_permission(current_user, PERM_STAFF_VIEW):
            raise HTTPException(status_code=403, detail="权限不足")
        # [新增 2026-09-15] 「修改历史」独立权限（默认仅超级管理员拥有）：
        # 变更追溯属敏感能力，与查看详情分开授权，可在「角色管理 → 人员管理 → 修改历史」中配置。
        if not has_permission(current_user, PERM_STAFF_VIEW_HISTORY):
            raise HTTPException(status_code=403, detail="无「修改历史」查看权限")
        staff = db.query(Staff).filter(Staff.employee_id == entity_id).first()
        if not staff:
            raise HTTPException(status_code=404, detail="人员不存在")
        # 与 get_staff_detail 一致：本人可查看自己，他人需在数据范围内（防跨科室 PHI 泄露）
        if entity_id != current_user.employee_id and not can_access_staff(
            current_user, staff.work_type, staff.department, db
        ):
            raise HTTPException(status_code=403, detail="无权查看该人员信息")
    elif entity_type == "department":
        if not has_permission(current_user, PERM_DEPT_VIEW):
            raise HTTPException(status_code=403, detail="权限不足")
        # [新增 2026-09-15] 「修改历史」独立权限（默认仅超级管理员拥有），
        # 可在「角色管理 → 科室管理 → 修改历史」中按角色授予/回收。
        if not has_permission(current_user, PERM_DEPT_VIEW_HISTORY):
            raise HTTPException(status_code=403, detail="无「修改历史」查看权限")
        try:
            dept_id = int(entity_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="科室 ID 无效")
        dept = db.query(Department).filter(Department.id == dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="科室不存在")
        if not has_department_access(current_user, dept.name, db):
            raise HTTPException(status_code=403, detail="无权查看该科室信息")
    else:
        raise HTTPException(status_code=400, detail=f"不支持的实体类型: {entity_type}")

    result = get_modification_history(db, entity_type, entity_id, limit)
    return {**result, "limit": limit}


@router.get("/system-logs")
def list_system_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str = Query(None, description="日志类别: operation/system/error"),
    level: str = Query(None, description="日志级别: INFO/WARN/ERROR"),
    keyword: str = Query(None, description="关键字搜索"),
    start_date: str = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询系统日志（需要 system.audit 权限）"""
    if not has_permission(current_user, PERM_SYSTEM_AUDIT):
        raise HTTPException(status_code=403, detail="权限不足")

    query = db.query(SystemLog)
    if category:
        query = query.filter(SystemLog.category == category)
    if level:
        query = query.filter(SystemLog.level == level)
    if keyword:
        query = query.filter(SystemLog.content.contains(keyword))
    if start_date:
        # [统一时间口径] 按北京业务日期取 UTC 边界（当日 00:00 北京 = 前一日 16:00 UTC），
        # 原实现按 UTC 零点解释日期，会使北京 00:00-08:00 的日志漏筛
        query = query.filter(SystemLog.timestamp >= beijing_date_start_utc(start_date))
    if end_date:
        query = query.filter(SystemLog.timestamp < beijing_date_start_utc(end_date, end_of_day=True))

    total = query.count()
    items = query.order_by(SystemLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()

    operator_ids = {item.operator for item in items if item.operator}
    name_map = {}
    if operator_ids:
        users = db.query(User.employee_id, User.name).filter(User.employee_id.in_(operator_ids)).all()
        name_map = {u.employee_id: u.name for u in users}

    return {
        "items": [{
            "id": item.id,
            # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
            "timestamp": to_iso_utc(item.timestamp),
            "level": item.level,
            "level_label": LEVEL_LABELS.get(item.level, item.level),
            "category": item.category,
            "category_label": CATEGORY_LABELS.get(item.category, item.category),
            "operator": item.operator,
            "operator_name": name_map.get(item.operator, item.operator) if item.operator else "-",
            "content": item.content,
            "ip_address": item.ip_address or "-",
            "details": item.details,
        } for item in items],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/system-logs/export")
def export_system_logs(
    request: Request,
    category: str = Query(None),
    level: str = Query(None),
    keyword: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出系统日志为 Excel（需要 system.audit 权限）"""
    if not has_permission(current_user, PERM_SYSTEM_AUDIT):
        raise HTTPException(status_code=403, detail="权限不足")

    from openpyxl import Workbook
    from fastapi.responses import StreamingResponse

    query = db.query(SystemLog)
    if category:
        query = query.filter(SystemLog.category == category)
    if level:
        query = query.filter(SystemLog.level == level)
    if keyword:
        query = query.filter(SystemLog.content.contains(keyword))
    if start_date:
        # [统一时间口径] 按北京业务日期取 UTC 边界（当日 00:00 北京 = 前一日 16:00 UTC），
        # 原实现按 UTC 零点解释日期，会使北京 00:00-08:00 的日志漏筛
        query = query.filter(SystemLog.timestamp >= beijing_date_start_utc(start_date))
    if end_date:
        query = query.filter(SystemLog.timestamp < beijing_date_start_utc(end_date, end_of_day=True))

    items = query.order_by(SystemLog.timestamp.desc()).limit(10000).all()

    # [新增 2026-09-19] 导出系统日志是敏感操作（产物含操作人、IP、业务详情，
    # 单次可达 1 万条），按「核心业务动作需留痕」的规范补记审计。
    # 只记录筛选条件与条数，不复制日志内容本体。
    client_ip = get_client_ip(request)
    record_audit(
        db, "system_log_export", current_user.employee_id,
        detail=(
            f"ip={client_ip}, rows={len(items)}, "
            f"category={category or '*'}, level={level or '*'}, "
            f"keyword={keyword or '-'}, "
            f"range={start_date or '-'}~{end_date or '-'}"
        ),
        target="system_logs", ip_address=client_ip,
    )
    db.commit()

    wb = Workbook()
    ws = wb.active
    ws.title = "系统日志"
    append_safe(ws, ["时间", "级别", "类别", "操作人", "内容", "IP地址", "详情"])
    for item in items:
        append_safe(ws, [
            # [统一时间口径] 导出产物直接给人看，显式转北京时间
            to_beijing_str(item.timestamp),
            LEVEL_LABELS.get(item.level, item.level),
            CATEGORY_LABELS.get(item.category, item.category),
            item.operator or "-",
            item.content,
            item.ip_address or "-",
            item.details or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    # [统一时间口径] 文件名时间戳统一用北京时间（原为 datetime.now()，取的是服务器本地时区）
    filename = f"系统日志_{to_beijing_str(utc_now(), '%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.delete("/system-logs/cleanup")
def cleanup_system_logs(
    request: Request,
    days: int = Query(90, ge=1, le=365, description="保留最近N天的日志"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理过期系统日志（需要 system.audit 权限）"""
    if not has_permission(current_user, PERM_SYSTEM_AUDIT):
        raise HTTPException(status_code=403, detail="权限不足")

    # [修复 2026-09-08] 日志时间戳统一存 UTC，清理阈值也用 UTC 口径，
    # 避免服务器时区不同导致多删/少删 8 小时内的日志
    cutoff = utc_now() - timedelta(days=days)
    deleted = db.query(SystemLog).filter(SystemLog.timestamp < cutoff).delete()
    db.commit()

    # [新增 2026-09-19] 清理系统日志等于**删除审计痕迹**，是权限体系中最敏感的
    # 动作之一，必须留痕。此处记录「谁、从哪个 IP、保留了多久、删了多少条」。
    # 新增的审计记录时间戳为当前时刻，必然晚于 cutoff，故不会被本次清理波及。
    client_ip = get_client_ip(request)
    record_audit(
        db, "system_log_cleanup", current_user.employee_id,
        detail=f"ip={client_ip}, keep_days={days}, deleted={deleted}",
        target="system_logs", ip_address=client_ip,
    )
    db.commit()

    return {"message": f"已清理 {deleted} 条过期日志", "deleted": deleted}
