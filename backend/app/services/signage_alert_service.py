# [重构 2026-09-05] 标识预警服务：
# - 删除「质保即将到期」「已过质保期」预警
# - 新增「状态异常标识」预警（轻微破损/严重损坏）
# - 巡检预警改为按分类配置的巡检周期（inspection_cycle_days）计算，分「7天内到期」「已超期」两种
# - 新增「临时标识有效期」预警（基于新增的 validity_type/validity_until 字段）
import logging
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.signage import Signage, SignageInspection, SignageRepair
from app.models.signage_settings import SignageCategory, Supplier
# [修复 2026-09-08] 预警"今天"统一为北京日期：原 date.today() 取服务器本地时区，
# 部署在 UTC 时区（如阿里云 Docker 默认）时到期/超期判定会偏移一天
from app.utils import beijing_today, to_beijing_date, utc_now

logger = logging.getLogger("hospital")

# [新增 2026-09-05] 状态异常取值：轻微破损/严重损坏（已拆除属于正常流程，不计异常）
ABNORMAL_STATUSES = ("damaged", "severely_damaged")
# [新增 2026-09-08] 维修处理中：发起维修后标识的过渡状态，完成维修后回到 normal
REPAIR_IN_PROGRESS = "repair_in_progress"


def get_abnormal_status(db):
    """[新增 2026-09-05] 状态异常标识预警：状态为轻微破损/严重损坏的标识"""
    return db.query(Signage).filter(Signage.status.in_(ABNORMAL_STATUSES)).all()


def _inspection_deadline_rows(db):
    """[新增 2026-09-05] 按分类巡检周期计算每个标识的巡检到期日。

    规则：
    - 周期取标识所属分类（按分类名称关联）的 inspection_cycle_days；
    - 未配置周期或已拆除的标识不参与预警；
    - 无巡检记录时，以标识创建日为巡检基准日。
    """
    today = beijing_today()
    rows = (
        db.query(Signage, SignageCategory.inspection_cycle_days)
        .outerjoin(SignageCategory, Signage.category == SignageCategory.name)
        .filter(Signage.status != "removed", SignageCategory.inspection_cycle_days.isnot(None))
        .all()
    )
    if not rows:
        return []
    # 一次性取每个标识的最近一次巡检日期，避免 N+1 查询
    last_dates = dict(
        db.query(SignageInspection.signage_id, func.max(SignageInspection.inspection_date))
        .group_by(SignageInspection.signage_id)
        .all()
    )
    out = []
    for s, cycle in rows:
        last = last_dates.get(s.id)
        # [修复 2026-09-08] created_at 为 UTC，基准日需转北京日期，否则基准偏移一天
        base = last or (to_beijing_date(s.created_at) if s.created_at else today)
        due = base + timedelta(days=int(cycle))
        out.append({
            "signage": s,
            "category": s.category,
            "cycle_days": int(cycle),
            "last_inspection_date": last,
            "due_date": due,
            "days_left": (due - today).days,
        })
    return out


def get_inspections_due_soon(db, days_ahead=7):
    """[新增 2026-09-05] 7天内巡检到期（尚未超期）"""
    today = beijing_today()
    deadline = today + timedelta(days=days_ahead)
    return [d for d in _inspection_deadline_rows(db) if today < d["due_date"] <= deadline]


def get_inspections_overdue(db):
    """[新增 2026-09-05] 巡检已超期（到期日早于等于今天）"""
    today = beijing_today()
    return [d for d in _inspection_deadline_rows(db) if d["due_date"] <= today]


def get_expiring_validity(db, days_ahead=7):
    """[新增 2026-09-05] 临时标识有效期预警：有效期在 days_ahead 天内（含已过期）"""
    today = beijing_today()
    deadline = today + timedelta(days=days_ahead)
    return db.query(Signage).filter(
        Signage.validity_type == "temporary",
        Signage.validity_until.isnot(None),
        Signage.validity_until <= deadline,
        Signage.status != "removed",
    ).order_by(Signage.validity_until).all()


# ============================================================
# [新增 2026-09-08] 预警处理：标识维修流程
#   状态异常（轻微破损/严重损坏）--发起维修--> 维修处理中 --完成维修--> 正常
# ============================================================
def get_repairs_in_progress(db):
    """维修处理中的预警：未完成的维修记录（关联标识信息）"""
    return (
        db.query(SignageRepair, Signage)
        .join(Signage, SignageRepair.signage_id == Signage.id)
        .filter(SignageRepair.completed_at.is_(None))
        .order_by(SignageRepair.started_at.desc())
        .all()
    )


def get_repairs_by_signage(db, signage_id: int) -> list[dict]:
    """[新增 2026-09-09] 查询某标识的全部维修记录（含维修前/后照片），按发起时间倒序。

    供标识详情页「维修记录」弹窗展示：
    - repair_photo_before：维修前照片（发起维修时自动取自最近一次巡检上传的现场照片）；
    - repair_photo：维修后照片（完成维修时上传）。
    """
    rows = (
        db.query(SignageRepair)
        .filter(SignageRepair.signage_id == signage_id)
        .order_by(SignageRepair.started_at.desc(), SignageRepair.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "signage_id": r.signage_id,
            "repair_party": r.repair_party,
            "supplier_name": r.supplier_name,
            "oa_number": r.oa_number,
            "repair_photo_before": r.repair_photo_before,
            "repair_photo": r.repair_photo,
            "started_by": r.started_by,
            "started_at": str(r.started_at) if r.started_at else None,
            "completed_by": r.completed_by,
            "completed_at": str(r.completed_at) if r.completed_at else None,
        }
        for r in rows
    ]


def start_repair(db, signage_id, repair_party, started_by, oa_number=None, supplier_id=None):
    """发起维修：状态异常标识 → 维修处理中。

    规则：
    - 仅状态异常（轻微破损/严重损坏）的标识可发起维修；
    - 供应商维修（vendor）必须选择供应商，OA 单号可选；
    - 工程部维修（engineering）可直接确认。
    返回 (维修记录, 错误信息)。
    """
    s = db.query(Signage).filter(Signage.id == signage_id).first()
    if not s:
        return None, "标识不存在"
    if s.status not in ABNORMAL_STATUSES:
        return None, "该标识当前不是状态异常（轻微破损/严重损坏），无需发起维修"
    if repair_party not in ("vendor", "engineering"):
        return None, "无效的维修方"
    supplier_name = None
    sid = None
    if repair_party == "vendor":
        if not supplier_id:
            return None, "选择供应商维修时必须选择供应商"
        sup = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.is_active.is_(True)).first()
        if not sup:
            return None, "供应商不存在或未启用"
        sid, supplier_name = sup.id, sup.name
    # [新增 2026-09-09] 维修前照片自动取自该标识最近一次巡检上传的现场照片（巡检已上传则无需另外上传）
    last_photo_inspection = (
        db.query(SignageInspection)
        .filter(
            SignageInspection.signage_id == signage_id,
            SignageInspection.photo.isnot(None),
            SignageInspection.photo != "",
        )
        .order_by(SignageInspection.created_at.desc(), SignageInspection.id.desc())
        .first()
    )
    rec = SignageRepair(
        signage_id=signage_id,
        repair_party=repair_party,
        supplier_id=sid,
        supplier_name=supplier_name,
        oa_number=(oa_number or None),
        repair_photo_before=(last_photo_inspection.photo if last_photo_inspection else None),
        started_by=started_by,
    )
    db.add(rec)
    db.flush()
    s.status = REPAIR_IN_PROGRESS
    s.updated_by = started_by
    # [修复 2026-09-09] 维修流程不再写入历史版本（SignageHistory）：
    # 历史版本仅由详情页「版本更新」入口产生，维修记录独立保存前后照片对比
    db.flush()
    return rec, None


def complete_repair(db, repair_id, completed_by, photo=None):
    """完成维修：维修处理中 → 正常。

    若上传维修完成照片，则同步替换标识详情页的安装现场照片（installation_photo）。
    返回 (维修记录, 错误信息)。
    """
    rec = db.query(SignageRepair).filter(
        SignageRepair.id == repair_id, SignageRepair.completed_at.is_(None)
    ).first()
    if not rec:
        return None, "维修记录不存在或已完成维修"
    s = db.query(Signage).filter(Signage.id == rec.signage_id).first()
    if not s:
        return None, "标识不存在"
    rec.completed_by = completed_by
    rec.completed_at = utc_now()
    rec.repair_photo = photo or None
    s.status = "normal"
    s.updated_by = completed_by
    if rec.repair_photo:
        # [需求] 上传维修完成照片时替换标识详情页的安装现场照片（仅字段更新，不写入历史版本）
        s.installation_photo = rec.repair_photo
    # [修复 2026-09-09] 维修流程不再写入历史版本（SignageHistory）：
    # 维修前/后照片均保存在维修记录（SignageRepair）中，供详情页「维修记录」查询展示
    db.flush()
    return rec, None


def get_all_alerts(db):
    """[重构 2026-09-05] 预警汇总：状态异常 / 7天内巡检到期 / 巡检已超期 / 临时标识即将过期 / 维修处理中"""
    abnormal = get_abnormal_status(db)
    due_soon = get_inspections_due_soon(db)
    overdue = get_inspections_overdue(db)
    expiring = get_expiring_validity(db)
    # [新增 2026-09-08] 维修处理中预警（未完成的维修记录）
    repairs = get_repairs_in_progress(db)
    return {
        "abnormal_status": len(abnormal),
        "inspection_due_soon": len(due_soon),
        "inspection_overdue": len(overdue),
        "temporary_expiring": len(expiring),
        "repair_in_progress": len(repairs),
        "total": len(abnormal) + len(due_soon) + len(overdue) + len(expiring) + len(repairs),
        "details": {
            "abnormal_status": [
                {"id": s.id, "code": s.code, "name": s.name, "status": s.status} for s in abnormal[:10]
            ],
            "repair_in_progress": [
                {
                    # 注意：维修处理中行的 id 为维修记录 id（完成维修时使用），signage_id 用于跳转详情
                    "id": r.id, "signage_id": s.id, "code": s.code, "name": s.name,
                    "repair_party": r.repair_party, "supplier_name": r.supplier_name,
                    "oa_number": r.oa_number,
                    "started_at": str(r.started_at) if r.started_at else None,
                } for r, s in repairs[:10]
            ],
            "inspection_due_soon": [
                {
                    "id": d["signage"].id, "code": d["signage"].code, "name": d["signage"].name,
                    "category": d["category"], "cycle_days": d["cycle_days"],
                    "last_inspection_date": str(d["last_inspection_date"]) if d["last_inspection_date"] else None,
                    "due_date": str(d["due_date"]), "days_left": d["days_left"],
                } for d in due_soon[:10]
            ],
            "inspection_overdue": [
                {
                    "id": d["signage"].id, "code": d["signage"].code, "name": d["signage"].name,
                    "category": d["category"], "cycle_days": d["cycle_days"],
                    "last_inspection_date": str(d["last_inspection_date"]) if d["last_inspection_date"] else None,
                    "due_date": str(d["due_date"]), "days_overdue": -d["days_left"],
                } for d in overdue[:10]
            ],
            "temporary_expiring": [
                {"id": s.id, "code": s.code, "name": s.name, "validity_until": str(s.validity_until)}
                for s in expiring[:10]
            ],
        },
    }
