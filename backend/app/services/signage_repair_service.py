# [新增 2026-09-09] 标识维修记录查询/导出服务：
# - list_repairs：分页 + 多条件筛选（关键词/标识/日期范围/维修方/供应商/状态），JOIN 标识带出位置信息
# - export_repairs_xlsx / export_repairs_csv：与列表同一套筛选口径导出（列见 REPAIR_COLUMNS）
import io
import csv
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from openpyxl import Workbook

from app.models.signage import Signage, SignageRepair
from app.utils import beijing_now

# 维修方中文标签
REPAIR_PARTY_LABELS = {"vendor": "供应商维修", "engineering": "工程部维修"}
# 维修状态中文标签（derived：completed_at 是否为空）
REPAIR_STATUS_LABELS = {"in_progress": "维修处理中", "completed": "已完成"}

# 导出列（label 为表头）
REPAIR_COLUMNS = [
    ("code", "标识编码"),
    ("name", "标识名称"),
    ("category", "分类"),
    ("campus", "院区"),
    ("building", "楼栋"),
    ("floor", "楼层"),
    ("party_label", "维修方"),
    ("supplier_name", "供应商"),
    ("oa_number", "OA单号"),
    ("started_by", "发起人"),
    ("started_at", "发起时间"),
    ("completed_by", "完成人"),
    ("completed_at", "完成时间"),
    ("duration_hours", "维修时长(小时)"),
    ("status_label", "状态"),
    ("photo_before", "维修前照片"),
    ("photo_after", "维修后照片"),
]


def _parse_date(v: str | None, end_of_day: bool = False) -> datetime | None:
    """筛选日期字符串（YYYY-MM-DD）转 UTC datetime 边界：start 取当日 00:00（北京）对应 UTC，
    end 取次日 00:00（北京）对应 UTC（即包含 end 当天全天）。"""
    if not v:
        return None
    d = datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    if end_of_day:
        d = d + timedelta(days=1)
    utc_dt = datetime(d.year, d.month, d.day) - timedelta(hours=8)  # 北京 00:00 → UTC 前一日 16:00
    return utc_dt


def _filtered_query(db: Session, keyword=None, signage_id=None, start_date=None, end_date=None,
                    repair_party=None, supplier_id=None, status=None):
    """按条件构造维修记录查询（JOIN 标识，供列表与导出共用同一筛选口径）"""
    q = db.query(SignageRepair).options(joinedload(SignageRepair.signage)).join(
        Signage, SignageRepair.signage_id == Signage.id
    )
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.filter((Signage.code.like(kw)) | (Signage.name.like(kw)))
    if signage_id:
        q = q.filter(SignageRepair.signage_id == signage_id)
    start_utc = _parse_date(start_date)
    if start_utc:
        q = q.filter(SignageRepair.started_at >= start_utc)
    end_utc = _parse_date(end_date, end_of_day=True)
    if end_utc:
        q = q.filter(SignageRepair.started_at < end_utc)
    if repair_party in ("vendor", "engineering"):
        q = q.filter(SignageRepair.repair_party == repair_party)
    if supplier_id:
        q = q.filter(SignageRepair.supplier_id == supplier_id)
    if status == "in_progress":
        q = q.filter(SignageRepair.completed_at.is_(None))
    elif status == "completed":
        q = q.filter(SignageRepair.completed_at.isnot(None))
    return q.order_by(SignageRepair.started_at.desc(), SignageRepair.id.desc())


def _to_item(r: SignageRepair) -> dict:
    """维修记录 ORM → 展示/导出行（状态派生、时长计算）"""
    s = r.signage
    duration_hours = None
    if r.completed_at and r.started_at:
        duration_hours = round((r.completed_at - r.started_at).total_seconds() / 3600, 1)
    return {
        "id": r.id,
        "signage_id": r.signage_id,
        "code": s.code if s else None,
        "name": s.name if s else None,
        "category": s.category if s else None,
        "campus": s.campus if s else None,
        "building": s.building if s else None,
        "floor": s.floor if s else None,
        "repair_party": r.repair_party,
        "party_label": REPAIR_PARTY_LABELS.get(r.repair_party, r.repair_party),
        "supplier_name": r.supplier_name,
        "oa_number": r.oa_number,
        "repair_photo_before": r.repair_photo_before,
        "repair_photo": r.repair_photo,
        "started_by": r.started_by,
        "started_at": str(r.started_at) if r.started_at else None,
        "completed_by": r.completed_by,
        "completed_at": str(r.completed_at) if r.completed_at else None,
        "duration_hours": duration_hours,
        "status": "completed" if r.completed_at else "in_progress",
        "status_label": REPAIR_STATUS_LABELS["completed" if r.completed_at else "in_progress"],
    }


def list_repairs(db: Session, page: int = 1, page_size: int = 20, **filters) -> tuple[list[dict], int]:
    """分页查询维修记录，返回 (items, total)"""
    q = _filtered_query(db, **filters)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return [_to_item(r) for r in rows], total


def count_repairs(db: Session, **filters) -> int:
    """按筛选条件统计条数（导出前确认弹窗展示范围用）"""
    return _filtered_query(db, **filters).count()


def _export_rows(db: Session, **filters) -> list[list]:
    items = [_to_item(r) for r in _filtered_query(db, **filters).all()]
    rows = []
    for it in items:
        rows.append([
            it["code"] or "", it["name"] or "", it["category"] or "",
            it["campus"] or "", it["building"] or "", it["floor"] or "",
            it["party_label"], it["supplier_name"] or "", it["oa_number"] or "",
            it["started_by"] or "", it["started_at"] or "",
            it["completed_by"] or "", it["completed_at"] or "",
            it["duration_hours"] if it["duration_hours"] is not None else "",
            it["status_label"],
            "有" if it["repair_photo_before"] else "无",
            "有" if it["repair_photo"] else "无",
        ])
    return rows


def export_repairs_xlsx(db: Session, **filters) -> io.BytesIO:
    """导出维修记录 xlsx（列与页面对应，状态/维修方/照片有无均为中文）"""
    wb = Workbook()
    ws = wb.active
    ws.title = "维修记录"
    ws.append([label for _, label in REPAIR_COLUMNS])
    for row in _export_rows(db, **filters):
        ws.append(row)
    ws.freeze_panes = "A2"
    widths = [14, 22, 12, 14, 16, 10, 14, 18, 16, 10, 20, 10, 20, 14, 12, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_repairs_csv(db: Session, **filters) -> io.BytesIO:
    """导出维修记录 CSV（utf-8-sig 保证 Excel 中文不乱码）"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for _, label in REPAIR_COLUMNS])
    for row in _export_rows(db, **filters):
        writer.writerow(row)
    return io.BytesIO(output.getvalue().encode("utf-8-sig"))
