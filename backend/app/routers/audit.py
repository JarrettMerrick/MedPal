# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
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

本路由现仅保留**系统日志**相关接口（查询 / 导出 / 清理，权限 system.audit）。
字段级修改留痕仍由 services/audit_service.record_modification 写入
（同时双写 SystemLog），仅不再提供专门的查询界面。
"""

from datetime import datetime, timedelta
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, has_permission, PERM_SYSTEM_AUDIT
from app.models.system_log import SystemLog
from app.models.user import User
from app.utils import utc_now

router = APIRouter(prefix="/api/audit", tags=["系统日志"])

CATEGORY_LABELS = {"operation": "操作日志", "system": "系统日志", "error": "错误日志"}
LEVEL_LABELS = {"INFO": "信息", "WARN": "警告", "ERROR": "错误"}


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
        query = query.filter(SystemLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(SystemLog.timestamp < datetime.fromisoformat(end_date) + timedelta(days=1))

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
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
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
        query = query.filter(SystemLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(SystemLog.timestamp < datetime.fromisoformat(end_date) + timedelta(days=1))

    items = query.order_by(SystemLog.timestamp.desc()).limit(10000).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "系统日志"
    ws.append(["时间", "级别", "类别", "操作人", "内容", "IP地址", "详情"])
    for item in items:
        ws.append([
            item.timestamp.strftime("%Y-%m-%d %H:%M:%S") if item.timestamp else "",
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
    filename = f"系统日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.delete("/system-logs/cleanup")
def cleanup_system_logs(
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
    return {"message": f"已清理 {deleted} 条过期日志", "deleted": deleted}
