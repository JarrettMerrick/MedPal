# [新增 2026-09-09] 标识总览聚合服务：
# 供「标识总览」页一次拉取全部统计数据（KPI / 分布 / 维修概况 / 最近动态），
# 避免前端拼装多个接口；巡检趋势单独提供（支持自定义日期区间，最多 90 天）。
from datetime import date, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.signage import Signage, SignageInspection, SignageRepair
from app.services.signage_alert_service import (
    get_abnormal_status, get_inspections_due_soon, get_inspections_overdue,
    get_expiring_validity, get_repairs_in_progress,
)
# [修复 2026-09-17] 补 beijing_now 导入：build_overview 用它计算「本月」起点，
# 原文件未导入该函数，导致 GET /api/signages/overview 一直抛 NameError（HTTP 500）
from app.utils import to_iso_utc, to_beijing_date, utc_now, beijing_now

# 标识状态中文标签（与前端 constants/signageStatus.ts 口径一致）
STATUS_LABELS = {
    "normal": "正常",
    "damaged": "轻微破损",
    "severely_damaged": "严重损坏",
    "repair_in_progress": "维修处理中",
    "removed": "已拆除",
}

REPAIR_PARTY_LABELS = {"vendor": "供应商维修", "engineering": "工程部维修"}

# 趋势查询最大跨度（天）
TREND_MAX_DAYS = 90


def build_overview(db: Session) -> dict:
    """[新增 2026-09-09] 标识总览聚合数据（一次返回全部区块）"""
    # ===== ① KPI 状态分布 =====
    status_rows = db.query(Signage.status, sa_func.count(Signage.id)).group_by(Signage.status).all()
    status_counts = {(s or ""): c for s, c in status_rows}
    kpi = {
        "total": sum(status_counts.values()),
        "normal": status_counts.get("normal", 0),
        "damaged": status_counts.get("damaged", 0),
        "severely_damaged": status_counts.get("severely_damaged", 0),
        "repair_in_progress": status_counts.get("repair_in_progress", 0),
        "removed": status_counts.get("removed", 0),
        "inspection_due_soon": len(get_inspections_due_soon(db)),
        "inspection_overdue": len(get_inspections_overdue(db)),
        "temporary_expiring": len(get_expiring_validity(db)),
    }

    # ===== ② 分布图（排除已拆除，反映在用标识构成） =====
    active_filter = Signage.status != "removed"
    category_rows = (
        db.query(Signage.category, sa_func.count(Signage.id))
        .filter(active_filter, Signage.category.isnot(None), Signage.category != "")
        .group_by(Signage.category).order_by(sa_func.count(Signage.id).desc()).all()
    )
    campus_rows = (
        db.query(Signage.campus, sa_func.count(Signage.id))
        .filter(active_filter, Signage.campus.isnot(None), Signage.campus != "")
        .group_by(Signage.campus).order_by(sa_func.count(Signage.id).desc()).all()
    )
    building_rows = (
        db.query(Signage.campus, Signage.building, sa_func.count(Signage.id))
        .filter(active_filter, Signage.campus.isnot(None), Signage.campus != "")
        .group_by(Signage.campus, Signage.building).all()
    )
    building_all = [
        {"name": " ".join(x for x in (campus, building) if x) or "未分配", "count": c}
        for campus, building, c in building_rows
    ]
    building_top = sorted(building_all, key=lambda x: x["count"], reverse=True)[:10]

    # ===== ③ 维修概况 =====
    month_start_bj = beijing_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_bj - timedelta(hours=8)  # 北京月初对应 UTC
    month_started = db.query(SignageRepair).filter(SignageRepair.started_at >= month_start_utc).count()
    month_completed = db.query(SignageRepair).filter(
        SignageRepair.completed_at.isnot(None), SignageRepair.completed_at >= month_start_utc
    ).count()
    in_progress = db.query(SignageRepair).filter(SignageRepair.completed_at.is_(None)).count()
    completed_rows = (
        db.query(SignageRepair.started_at, SignageRepair.completed_at)
        .filter(SignageRepair.completed_at.isnot(None), SignageRepair.started_at.isnot(None)).all()
    )
    total_hours = sum((c - s).total_seconds() for s, c in completed_rows if c and s)
    avg_hours = round(total_hours / 3600 / len(completed_rows), 1) if completed_rows else 0
    party_rows = (
        db.query(SignageRepair.repair_party, sa_func.count(SignageRepair.id))
        .group_by(SignageRepair.repair_party).all()
    )
    repair_summary = {
        "month_started": month_started,
        "month_completed": month_completed,
        "in_progress": in_progress,
        "avg_hours": avg_hours,
        "party_vendor": sum(c for p, c in party_rows if p == "vendor"),
        "party_engineering": sum(c for p, c in party_rows if p == "engineering"),
    }

    # ===== ④ 最近维修 Top10 =====
    repair_rows = (
        db.query(SignageRepair, Signage)
        .join(Signage, SignageRepair.signage_id == Signage.id)
        .order_by(SignageRepair.started_at.desc(), SignageRepair.id.desc())
        .limit(10).all()
    )
    recent_repairs = [
        {
            "id": r.id, "signage_id": s.id, "code": s.code, "name": s.name,
            "repair_party": r.repair_party, "party_label": REPAIR_PARTY_LABELS.get(r.repair_party, r.repair_party),
            "supplier_name": r.supplier_name, "oa_number": r.oa_number,
            "status": "completed" if r.completed_at else "in_progress",
            # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
            "started_at": to_iso_utc(r.started_at),
            "completed_at": to_iso_utc(r.completed_at),
        }
        for r, s in repair_rows
    ]

    # ===== ⑤ 最近巡检 Top10 =====
    inspection_rows = (
        db.query(SignageInspection, Signage)
        .join(Signage, SignageInspection.signage_id == Signage.id)
        .order_by(SignageInspection.created_at.desc(), SignageInspection.id.desc())
        .limit(10).all()
    )
    recent_inspections = [
        {
            "id": i.id, "signage_id": s.id, "code": s.code, "name": s.name,
            "result": i.result, "result_label": STATUS_LABELS.get(i.result, i.result),
            "inspector": i.inspector,
            # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
            "created_at": to_iso_utc(i.created_at),
            "photo": i.photo,
        }
        for i, s in inspection_rows
    ]

    # ===== ⑥ 最新预警（合并状态异常 / 维修处理中 / 巡检超期，截取 10 条） =====
    alerts: list[dict] = []
    for s in get_abnormal_status(db):
        alerts.append({"type": "状态异常", "id": s.id, "code": s.code, "name": s.name,
                       "info": STATUS_LABELS.get(s.status, s.status)})
    for r, s in get_repairs_in_progress(db):
        party = REPAIR_PARTY_LABELS.get(r.repair_party, r.repair_party)
        info = f"{party}{'（' + r.supplier_name + '）' if r.supplier_name else ''}"
        alerts.append({"type": "维修处理中", "id": s.id, "code": s.code, "name": s.name, "info": info})
    for d in get_inspections_overdue(db):
        alerts.append({"type": "巡检已超期", "id": d["signage"].id, "code": d["signage"].code,
                       "name": d["signage"].name, "info": f"已超期 {-d['days_left']} 天"})
    recent_alerts = alerts[:10]

    return {
        "kpi": kpi,
        "category_distribution": [{"name": n or "未分类", "count": c} for n, c in category_rows],
        "campus_distribution": [{"name": n or "未分配", "count": c} for n, c in campus_rows],
        "building_top": building_top,
        "repair_summary": repair_summary,
        "recent_repairs": recent_repairs,
        "recent_inspections": recent_inspections,
        "recent_alerts": recent_alerts,
        # [统一时间口径] 原为 str(beijing_now())：北京时间串不带时区标记，
        # 前端按 UTC 解析会多加 8 小时。现统一输出带 Z 的 UTC，由前端转本地。
        "generated_at": to_iso_utc(utc_now()),
    }


def inspection_trend(db: Session, start_date: date, end_date: date) -> list[dict]:
    """[新增 2026-09-09] 巡检提交量趋势（按北京日期统计每天巡检条数）。

    - created_at 为 UTC 存储，按 to_beijing_date 归属业务日期；
    - 区间跨度最多 90 天，超限抛 ValueError；起止颠倒时自动交换；
    - 返回区间内每一天的数据（无巡检的日期补 0），便于折线图连续展示。
    """
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days > TREND_MAX_DAYS:
        raise ValueError(f"最多可查询 {TREND_MAX_DAYS} 天数据")

    # 宽松取 UTC 边界（前一天起、后两天止），精确归属在 Python 侧按北京日期过滤
    range_start_utc = start_date - timedelta(days=1)
    range_end_utc_exclusive = end_date + timedelta(days=2)
    rows = (
        db.query(SignageInspection.created_at)
        .filter(
            SignageInspection.created_at.isnot(None),
            SignageInspection.created_at >= range_start_utc,
            SignageInspection.created_at < range_end_utc_exclusive,
        )
        .all()
    )
    counts: dict[date, int] = {}
    for (created_at,) in rows:
        if not created_at:
            continue
        d = to_beijing_date(created_at)
        if start_date <= d <= end_date:
            counts[d] = counts.get(d, 0) + 1

    out = []
    cursor = start_date
    while cursor <= end_date:
        out.append({"date": str(cursor), "count": counts.get(cursor, 0)})
        cursor += timedelta(days=1)
    return out
