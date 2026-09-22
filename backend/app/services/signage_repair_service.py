# [新增 2026-09-09] 标识维修记录查询/导出服务：
# - list_repairs：分页 + 多条件筛选（关键词/标识/日期范围/维修方/供应商/状态），JOIN 标识带出位置信息
# - export_repairs_xlsx / export_repairs_csv：与列表同一套筛选口径导出（列见 REPAIR_COLUMNS）
import io
import csv
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from openpyxl import Workbook

from app.models.signage import Signage, SignageRepair
# [新增 2026-09-17] 维修记录需展示发起/完成人姓名（记录中存的是工号，需回查人员姓名）
from app.models.user import User
# [统一时间口径] API 输出用 to_iso_utc（带 Z 的 UTC，前端按浏览器时区转换显示）；
# 导出文件用 to_beijing_str（离线产物不经前端转换，直接呈现北京时间）
from app.utils import to_iso_utc, to_beijing_str
from app.services.excel_safety import append_safe

# 维修方中文标签
REPAIR_PARTY_LABELS = {"vendor": "供应商维修", "engineering": "工程部维修"}
# 维修状态中文标签（derived：completed_at 是否为空）
# [调整 2026-09-17] 新增 pending（待维修）：标识状态为轻微破损 / 严重损坏、尚未发起维修，
# 由「标识维修」页直接展示并可发起维修（原先只存在于「标识预警」页，该页已下线）
REPAIR_STATUS_LABELS = {"pending": "待维修", "in_progress": "维修处理中", "completed": "已完成"}

# [新增 2026-09-17] 需要维修的标识状态（待维修行来源）：轻微破损 / 严重损坏
SIGNAGE_DAMAGE_LABELS = {"damaged": "轻微破损", "severely_damaged": "严重损坏"}

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
    elif status == "pending":
        # [新增 2026-09-17] 「待维修」只存在于标识侧（尚未发起维修），维修记录中不含该状态 → 空集
        q = q.filter(SignageRepair.id.is_(None))
    return q.order_by(SignageRepair.started_at.desc(), SignageRepair.id.desc())


def _user_name_map(db: Session, employee_ids) -> dict:
    """[新增 2026-09-17] 批量查询「工号 → 姓名」映射。

    维修记录的 started_by / completed_by 存的是工号，列表需要同时展示
    「员工姓名 + 工号」。这里一次性查出全部相关工号，避免逐行查询（N+1）。
    """
    ids = {str(i).strip() for i in employee_ids if i}
    if not ids:
        return {}
    rows = db.query(User.employee_id, User.name).filter(User.employee_id.in_(ids)).all()
    return {str(eid): name for eid, name in rows if eid}


def _to_item(r: SignageRepair, name_map: dict | None = None) -> dict:
    """维修记录 ORM → 展示/导出行（状态派生、时长计算）。

    [调整 2026-09-17] 新增 name_map（工号 → 姓名）参数：
    额外输出 started_by_name / completed_by_name，供列表展示「姓名 + 工号」；
    查不到姓名时为空值，前端回退为只显示工号。
    """
    s = r.signage
    name_map = name_map or {}
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
        # [新增 2026-09-17] 发起人 / 完成人姓名（工号回查人员表；查不到则为空）
        "started_by_name": name_map.get(str(r.started_by or "").strip()) or None,
        # [新增 2026-09-17] 标识当前状态（与「待维修」行保持统一结构，便于前端可选展示）
        "signage_status": s.status if s else None,
        # [统一时间口径] 带 Z 的 UTC ISO，前端一律经 utils/time.ts 转本地时区显示
        "started_at": to_iso_utc(r.started_at),
        "completed_by": r.completed_by,
        "completed_by_name": name_map.get(str(r.completed_by or "").strip()) or None,
        "completed_at": to_iso_utc(r.completed_at),
        "duration_hours": duration_hours,
        "status": "completed" if r.completed_at else "in_progress",
        "status_label": REPAIR_STATUS_LABELS["completed" if r.completed_at else "in_progress"],
    }


def _pending_signages(db: Session, keyword=None, signage_id=None, start_date=None, end_date=None,
                      repair_party=None, supplier_id=None, status=None) -> list[Signage]:
    """[新增 2026-09-17] 待维修标识：状态为轻微破损 / 严重损坏、尚未发起维修。

    这类标识没有维修记录，但需要在「标识维修」列表中体现（可直接发起维修）。

    筛选语义：维修相关条件（发起日期范围 / 维修方 / 供应商）与「进行中 / 已完成」
    状态对"尚未发起维修"的行不适用，此时返回空列表，避免出现语义矛盾的结果。
    """
    if status and status != "pending":
        return []
    if start_date or end_date or repair_party or supplier_id:
        return []
    q = db.query(Signage).filter(Signage.status.in_(tuple(SIGNAGE_DAMAGE_LABELS.keys())))
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.filter((Signage.code.like(kw)) | (Signage.name.like(kw)))
    if signage_id:
        q = q.filter(Signage.id == signage_id)
    return q.order_by(Signage.code).all()


def _pending_to_item(s: Signage) -> dict:
    """[新增 2026-09-17] 待维修标识 → 列表行（结构对齐维修记录行，维修字段留空）。

    id 复用标识 id：前端按 status 区分 rowKey（待维修行与维修记录行不会混淆）。
    """
    return {
        "id": s.id,
        "signage_id": s.id,
        "code": s.code, "name": s.name, "category": s.category,
        "campus": s.campus, "building": s.building, "floor": s.floor,
        "repair_party": None,
        "party_label": None,
        "supplier_name": None,
        "oa_number": None,
        "repair_photo_before": None,
        "repair_photo": None,
        "started_by": None, "started_by_name": None, "started_at": None,
        "completed_by": None, "completed_by_name": None, "completed_at": None,
        "duration_hours": None,
        "status": "pending",
        "status_label": REPAIR_STATUS_LABELS["pending"],
        # 标识当前状态：damaged / severely_damaged（列表用于区分损坏等级）
        "signage_status": s.status,
        "signage_status_label": SIGNAGE_DAMAGE_LABELS.get(s.status, s.status),
    }


def list_repairs(db: Session, page: int = 1, page_size: int = 20, **filters) -> tuple[list[dict], int]:
    """分页查询维修列表，返回 (items, total)。

    [调整 2026-09-17] 列表改为「待维修标识 + 维修记录」的统一视图（需求）：
    - 待维修：标识状态为轻微破损 / 严重损坏（尚未发起维修），按标识编码升序排在前面；
    - 维修记录：已发起的维修（进行中 / 已完成），按发起时间倒序；
    - 分页在数据库侧完成：待维修行数量有限，先占用当前页位置，剩余位置由维修记录补齐，
      避免为合并两类数据而全量加载维修记录；
    - 发起 / 完成人姓名批量补齐（工号 → 姓名），无 N+1。
    """
    pending_items = [_pending_to_item(s) for s in _pending_signages(db, **filters)]
    pending_total = len(pending_items)
    total = pending_total + _filtered_query(db, **filters).count()

    offset = (page - 1) * page_size
    items: list[dict] = []
    if offset < pending_total:
        items.extend(pending_items[offset:offset + page_size])

    need = page_size - len(items)
    if need > 0:
        record_offset = max(0, offset - pending_total)
        rows = _filtered_query(db, **filters).offset(record_offset).limit(need).all()
        name_map = _user_name_map(db, [x for r in rows for x in (r.started_by, r.completed_by)])
        items.extend([_to_item(r, name_map) for r in rows])
    return items, total


def count_repairs(db: Session, **filters) -> int:
    """按筛选条件统计条数（导出前确认弹窗展示范围用）。

    [调整 2026-09-17] 与列表口径一致：含待维修标识。
    """
    return len(_pending_signages(db, **filters)) + _filtered_query(db, **filters).count()


def _export_rows(db: Session, **filters) -> list[list]:
    """导出用行数据：时间列统一为**北京时间**可读格式。

    [统一时间口径] 导出的 Excel/CSV 不经过前端时区转换、直接给人看，
    因此这里不能用接口的 ISO UTC 值（会显示少 8 小时），必须显式转北京时间。
    """
    records = _filtered_query(db, **filters).all()
    # [调整 2026-09-17] 导出同样批量补齐姓名映射（导出列仍保持原样，仅避免逐行查询）
    name_map = _user_name_map(db, [x for r in records for x in (r.started_by, r.completed_by)])
    rows = []
    # [新增 2026-09-17] 待维修标识（状态异常、尚未发起维修）同样纳入导出：
    # 维修方列显示「未发起」，其余维修字段留空，与列表口径保持一致
    for it in [_pending_to_item(x) for x in _pending_signages(db, **filters)]:
        rows.append([
            it["code"] or "", it["name"] or "", it["category"] or "",
            it["campus"] or "", it["building"] or "", it["floor"] or "",
            "未发起", "", "",
            "", "", "", "", "",
            it["status_label"], "无", "无",
        ])
    for r in records:
        it = _to_item(r, name_map)
        rows.append([
            it["code"] or "", it["name"] or "", it["category"] or "",
            it["campus"] or "", it["building"] or "", it["floor"] or "",
            it["party_label"], it["supplier_name"] or "", it["oa_number"] or "",
            it["started_by"] or "", to_beijing_str(r.started_at),
            it["completed_by"] or "", to_beijing_str(r.completed_at),
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
    append_safe(ws, [label for _, label in REPAIR_COLUMNS])
    for row in _export_rows(db, **filters):
        append_safe(ws, row)
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
