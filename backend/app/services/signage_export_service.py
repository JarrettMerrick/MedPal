# [重构 2026-09-07] 标识导入导出服务：
# ① 数据导出（xlsx/csv）：支持按院区/楼栋/分类/状态/关键词筛选，列与导入模板保持一致；
# ② 附件批量导出（zip）：按同样筛选条件打包设计文件、安装现场照片及标识二维码（服务端生成 QR PNG）；
# ③ 导入：提供 xlsx 模板下载与解析导入（编码可空则自动生成，名称/分类必填，逐行校验并汇总错误）。
import io
import os
import re
import csv
import json
import uuid
import shutil
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from openpyxl import Workbook, load_workbook
from app.config import DATA_ROOT
from app.models.signage import Signage
from app.utils import beijing_now, utc_now
from app.services.upload_service import get_file_path, UPLOAD_ROOT

logger = logging.getLogger("hospital")

# 状态值 <-> 中文标签互转（与前端 constants/signageStatus.ts 口径一致）
# [修复 2026-09-09] 补充 repair_in_progress：导出台账不再输出英文原值
STATUS_LABELS = {
    "normal": "正常",
    "damaged": "轻微破损",
    "severely_damaged": "严重损坏",
    "repair_in_progress": "维修处理中",
    "removed": "已拆除",
}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABELS.items()}

# [新增 2026-09-09] 有效期类型导出中文（长期/临时），与导入口径对齐（导入兼容中英文）
VALIDITY_TYPE_LABELS = {"long_term": "长期", "temporary": "临时"}

# 导出列与导入模板列保持一致（field 与 Signage 模型字段对应；label 为表头）
SIGNAGE_COLUMNS = [
    ("code", "编码"),
    ("name", "名称"),
    ("category", "分类"),
    ("category_type", "类别"),
    ("material", "材质"),
    ("size_spec", "规格尺寸"),
    ("campus", "院区"),
    ("building", "楼栋"),
    ("floor", "楼层"),
    ("zone_type", "所属区域"),
    ("location_desc", "安装位置描述"),
    ("display_text_cn", "中文文本"),
    ("display_text_en", "英文文本"),
    ("status", "状态"),
    ("oa_number", "OA单号"),
    ("manufacturer", "厂商"),
    ("vendor_contact", "厂商联系方式"),
    ("install_date", "安装日期"),
    ("warranty_expire", "质保到期"),
    ("validity_type", "有效期类型"),
    ("validity_until", "有效期至"),
]

VALID_ZONE_TYPES = {"院区导视/宣传", "楼栋导视/宣传", "楼层导视/宣传"}
VALID_CATEGORY_TYPES = {"标识标牌", "平面宣传"}


def _filtered_signages(db: Session, campus=None, building=None, category=None, status=None, search=None):
    """[新增 2026-09-07] 按条件筛选标识，供数据导出与附件导出共用同一查询口径"""
    q = db.query(Signage)
    if campus:
        q = q.filter(Signage.campus == campus)
    if building:
        q = q.filter(Signage.building == building)
    if category:
        q = q.filter(Signage.category == category)
    if status:
        q = q.filter(Signage.status == status)
    if search:
        q = q.filter((Signage.name.like(f"%{search}%")) | (Signage.code.like(f"%{search}%")))
    return q.order_by(Signage.code).all()


def _fmt_date(v):
    return str(v) if v else ""


def _row_of(s: Signage):
    """[新增 2026-09-07] 将标识 ORM 对象转为导出行（状态输出中文标签，便于人工阅读/回填导入）"""
    row = []
    for field, _ in SIGNAGE_COLUMNS:
        val = getattr(s, field, None)
        if field == "status":
            row.append(STATUS_LABELS.get(val, val or ""))
        elif field in ("install_date", "warranty_expire", "validity_until"):
            row.append(_fmt_date(val))
        elif field == "validity_type":
            # [修复 2026-09-09] 有效期类型导出中文（长期/临时），与导入口径对齐
            row.append(VALIDITY_TYPE_LABELS.get(val or "", val or ""))
        else:
            row.append(val or "")
    return row


def export_signages_xlsx(db, campus=None, building=None, category=None, status=None, search=None):
    """[重构 2026-09-07] 导出标识台账 xlsx（列与导入模板一致，状态为中文名称）"""
    items = _filtered_signages(db, campus, building, category, status, search)

    wb = Workbook()
    ws = wb.active
    ws.title = "标识台账"
    headers = [label for _, label in SIGNAGE_COLUMNS]
    ws.append(headers)
    for s in items:
        ws.append(_row_of(s))
    # 冻结表头并加宽列，便于查看
    ws.freeze_panes = "A2"
    for i, w in enumerate([18, 22, 14, 12, 14, 18, 16, 16, 10, 16, 30, 30, 30, 12, 16, 20, 20, 12, 12, 12, 12], start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_signages_csv(db, campus=None, building=None, category=None, status=None, search=None):
    """[重构 2026-09-07] 导出标识台账 CSV（utf-8-sig 保证 Excel 中文不乱码）"""
    items = _filtered_signages(db, campus, building, category, status, search)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for _, label in SIGNAGE_COLUMNS])
    for s in items:
        writer.writerow(_row_of(s))
    return io.BytesIO(output.getvalue().encode("utf-8-sig"))


# ==================== 附件批量导出（zip） ====================

def _qr_png_bytes(s: Signage) -> bytes:
    """[修复 2026-09-08] 服务端生成标识二维码 PNG：只编码「纯标识编号」，
    扫码得到的就是编号本身，可与前端 by-code 精确匹配（去掉“标识编码：/院区：/位置：”等前缀）。
    院区/位置等说明信息不写入码内。"""
    try:
        import qrcode  # 延迟导入：未安装时在路由层返回友好提示
    except ImportError as e:
        raise RuntimeError("服务端未安装 qrcode 库，无法生成二维码（pip install qrcode）") from e
    content = s.code or f"标识ID：{s.id}"
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _safe_name(v: str) -> str:
    """[新增 2026-09-07] 文件名安全化：去除 zip 内非法字符与路径分隔符"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(v)).strip("_") or "未命名"


def _read_upload(rel_path: str) -> bytes | None:
    """[新增 2026-09-07] 读取上传目录内文件；防路径穿越，越界或不存在返回 None"""
    try:
        real_root = os.path.realpath(UPLOAD_ROOT)
        real_abs = os.path.realpath(get_file_path(rel_path))
        if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
            return None
        if not os.path.isfile(real_abs):
            return None
        with open(real_abs, "rb") as f:
            return f.read()
    except Exception:
        logger.warning("读取上传文件失败: %s", rel_path, exc_info=True)
        return None


# ==================== 附件批量导出（两步式：生成任务 → 下载） ====================
# [重构 2026-09-08] 打包改为后台任务：先生成（分卷，单卷 ≤500MB，超限自动分卷），
# 再按卷下载；压缩包保留 24 小时，过期由定时任务自动清理。

EXPORT_ROOT = os.path.join(str(DATA_ROOT), "exports")
MAX_ZIP_BYTES = 500 * 1024 * 1024   # 单个压缩包上限 500MB（按原始字节估算，压缩后实际更小）
EXPORT_RETENTION_HOURS = 24         # 压缩包保留时长


def _export_task_dir(task_id: str) -> str:
    return os.path.join(EXPORT_ROOT, task_id)


def _manifest_path(task_id: str) -> str:
    return os.path.join(_export_task_dir(task_id), "manifest.json")


def _read_manifest(task_id: str) -> dict | None:
    """读取任务清单；不存在/损坏返回 None"""
    try:
        with open(_manifest_path(task_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_manifest(task_id: str, **kwargs):
    """更新任务清单（合并写入，保留未指定字段）；task_id 始终写入清单"""
    data = _read_manifest(task_id) or {}
    data["task_id"] = task_id
    data.update(kwargs)
    os.makedirs(os.path.dirname(_manifest_path(task_id)), exist_ok=True)
    with open(_manifest_path(task_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_export_task(campus=None, building=None, category=None, status=None, search=None,
                       include_design=True, include_photo=True, include_qrcode=True) -> dict:
    """[新增 2026-09-08] 创建导出任务：登记清单（status=processing），打包由后台任务执行"""
    task_id = uuid.uuid4().hex
    created_at = utc_now().isoformat()
    os.makedirs(_export_task_dir(task_id), exist_ok=True)
    _write_manifest(
        task_id,
        status="processing",
        created_at=created_at,
        expires_at=beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
        filters={"campus": campus, "building": building, "category": category,
                 "status": status, "search": search},
        include={"design": include_design, "photo": include_photo, "qrcode": include_qrcode},
        parts=[], counts={}, total=0, error=None,
    )
    return {"task_id": task_id, "status": "processing"}


def run_export_task(task_id: str, campus=None, building=None, category=None, status=None, search=None,
                    include_design=True, include_photo=True, include_qrcode=True):
    """[新增 2026-09-08] 后台打包任务：独立 DB 会话，逐标识写入分卷 zip，单卷超限自动滚动"""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        items = _filtered_signages(db, campus, building, category, status, search)
        task_dir = _export_task_dir(task_id)
        counts = {"qrcode": 0, "design": 0, "photo": 0, "missing": 0}
        parts: list[dict] = []
        volume_idx = 0
        zf: zipfile.ZipFile | None = None
        volume_raw = 0  # 当前卷已写入的原始字节数（保守估算，压缩后实际更小）
        stamp = beijing_now().strftime("%Y%m%d_%H%M%S")

        def _close_volume():
            nonlocal zf
            if zf is not None:
                zf.close()
                zf = None

        def _open_volume():
            nonlocal zf, volume_idx, volume_raw
            volume_idx += 1
            volume_raw = 0
            fname = f"标识附件_{stamp}_part{volume_idx}.zip"
            zf = zipfile.ZipFile(os.path.join(task_dir, fname), "w", zipfile.ZIP_DEFLATED)
            parts.append({"filename": fname, "size": 0})
            # 每卷都放导出清单，保证单卷可独立核对
            zf.writestr("导出清单.txt", "\n".join([
                f"标识总数：{len(items)}",
                f"分卷：{volume_idx}（共见 manifest.json）",
                f"二维码：{counts['qrcode']} 个",
                f"设计文件：{counts['design']} 个",
                f"现场照片：{counts['photo']} 个",
                f"服务器缺失文件：{counts['missing']} 个",
                f"导出时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"保留至：{(beijing_now() + timedelta(hours=EXPORT_RETENTION_HOURS)).strftime('%Y-%m-%d %H:%M:%S')}",
            ]))

        for s in items:
            # 收集该标识的全部附件条目（name, data）
            entries: list[tuple[str, bytes]] = []
            code_dir = _safe_name(s.code or f"ID{s.id}")
            if include_qrcode and s.code:
                try:
                    entries.append((f"二维码/{code_dir}.png", _qr_png_bytes(s)))
                    counts["qrcode"] += 1
                except Exception:
                    logger.warning("生成二维码失败: %s", s.code, exc_info=True)
            if include_design and s.design_photo:
                data = _read_upload(s.design_photo)
                if data is None:
                    counts["missing"] += 1
                else:
                    entries.append((f"设计文件/{code_dir}_{_safe_name(os.path.basename(s.design_photo))}", data))
                    counts["design"] += 1
            if include_photo and s.installation_photo:
                data = _read_upload(s.installation_photo)
                if data is None:
                    counts["missing"] += 1
                else:
                    entries.append((f"现场照片/{code_dir}_{_safe_name(os.path.basename(s.installation_photo))}", data))
                    counts["photo"] += 1
            if not entries:
                continue

            entry_bytes = sum(len(d) for _, d in entries)
            # 分卷：当前卷写入后预计超限 → 先落卷再开新卷（超大单文件独占一卷）
            if zf is None or volume_raw + entry_bytes > MAX_ZIP_BYTES:
                _close_volume()
                _open_volume()
            for name, data in entries:
                zf.writestr(name, data)
            volume_raw += entry_bytes
            parts[-1]["size"] = os.path.getsize(os.path.join(task_dir, parts[-1]["filename"]))
        _close_volume()

        if not parts:
            # 无任何附件可导出
            _write_manifest(task_id, status="done", parts=[], counts=counts, total=len(items),
                            error="所选范围内没有可导出的附件")
        else:
            _write_manifest(task_id, status="done", parts=parts, counts=counts, total=len(items), error=None)
    except Exception as e:
        logger.exception("附件导出任务失败: %s", task_id)
        try:
            _write_manifest(task_id, status="failed", error=str(e))
        except Exception:
            pass
    finally:
        db.close()


def get_export_task(task_id: str) -> dict | None:
    """[新增 2026-09-08] 查询导出任务状态与分卷列表"""
    m = _read_manifest(task_id)
    if not m:
        return None
    # 附带分卷实际大小（打包过程中 size 可能滞后）
    for part in m.get("parts", []):
        p = os.path.join(_export_task_dir(task_id), part["filename"])
        if os.path.isfile(p):
            part["size"] = os.path.getsize(p)
    return m


def list_export_tasks(limit: int = 20) -> list[dict]:
    """[新增 2026-09-08] 列出最近的导出任务（按创建时间倒序）"""
    tasks = []
    if not os.path.isdir(EXPORT_ROOT):
        return tasks
    for tid in os.listdir(EXPORT_ROOT):
        m = get_export_task(tid)  # 复用查询逻辑，顺带刷新分卷实际大小
        if m:
            tasks.append(m)
    tasks.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return tasks[:limit]


def get_export_part_path(task_id: str, filename: str) -> str | None:
    """[新增 2026-09-08] 取分卷文件绝对路径（防路径穿越，仅允许任务目录内的 .zip）"""
    if not task_id or not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    if not filename.lower().endswith(".zip"):
        return None
    path = os.path.join(_export_task_dir(task_id), filename)
    real_root = os.path.realpath(EXPORT_ROOT)
    real_path = os.path.realpath(path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        return None
    return real_path if os.path.isfile(real_path) else None


def cleanup_expired_exports() -> int:
    """[新增 2026-09-08] 清理超过保留期（24 小时）的导出任务目录，返回清理数量"""
    if not os.path.isdir(EXPORT_ROOT):
        return 0
    now = utc_now()
    removed = 0
    for tid in os.listdir(EXPORT_ROOT):
        task_dir = _export_task_dir(tid)
        if not os.path.isdir(task_dir):
            continue
        m = _read_manifest(tid)
        expired = False
        if m and m.get("created_at"):
            try:
                created = datetime.fromisoformat(m["created_at"])
                expired = (now - created).total_seconds() > EXPORT_RETENTION_HOURS * 3600
            except ValueError:
                expired = False
        if not expired:
            # 无清单或解析失败时按目录修改时间兜底
            expired = (now - datetime.fromtimestamp(os.path.getmtime(task_dir), tz=timezone.utc).replace(tzinfo=None)).total_seconds() > EXPORT_RETENTION_HOURS * 3600
        if expired:
            try:
                shutil.rmtree(task_dir, ignore_errors=True)
                removed += 1
            except Exception:
                logger.warning("清理过期导出任务失败: %s", tid, exc_info=True)
    if removed:
        logger.info("已清理 %d 个过期附件导出任务（保留 %d 小时）", removed, EXPORT_RETENTION_HOURS)
    return removed


# ==================== 导入 ====================

IMPORT_EXAMPLE = [
    "", "门诊大厅指引牌", "道路指引", "标识标牌", "铝型材", "600x400mm",
    "南通瑞慈医院", "1号楼", "F1", "楼栋导视/宣传", "门诊大厅入口",
    "门诊大厅", "Outpatient Hall", "正常", "OA20260907001", "某某标识", "13800000000",
    "2026-09-07", "2027-09-07", "long_term", "",
]


def build_import_template() -> io.BytesIO:
    """[新增 2026-09-07] 生成导入模板 xlsx：表头 + 一行示例 + 说明页"""
    wb = Workbook()
    ws = wb.active
    ws.title = "标识导入"
    ws.append([label for _, label in SIGNAGE_COLUMNS])
    ws.append(IMPORT_EXAMPLE)
    ws.freeze_panes = "A2"
    for i, w in enumerate([18, 22, 14, 12, 14, 18, 16, 16, 10, 16, 30, 30, 30, 12, 16, 20, 20, 12, 12, 12, 12], start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    info = wb.create_sheet("填写说明")
    notes = [
        "1. 请勿修改表头顺序与名称，从第 2 行开始填写数据；模板第 2 行为示例，导入前请删除或覆盖。",
        "2. 「名称」「分类」为必填项；「编码」留空时系统按 院区代号-分类编码-楼栋-楼层-序号 规则自动生成。",
        "3. 「类别」仅支持：标识标牌 / 平面宣传；「所属区域」仅支持：院区导视/宣传、楼栋导视/宣传、楼层导视/宣传。",
        "4. 「状态」支持中文（正常/轻微破损/严重损坏/已拆除）或英文值（normal/damaged/severely_damaged/removed），留空默认「正常」。",
        "5. 「有效期类型」仅支持：long_term（长期）/ temporary（临时）；临时标识必须填写「有效期至」（YYYY-MM-DD）。",
        "6. 日期列格式：YYYY-MM-DD。",
        "7. 编码已存在时该行跳过并在导入结果中提示；设计文件与现场照片需在创建后于详情页单独上传。",
    ]
    for n in notes:
        info.append([n])
    info.column_dimensions["A"].width = 110

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _parse_date(v):
    """[新增 2026-09-07] 解析单元格日期：支持 date/datetime/常见字符串格式"""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期格式不正确：{s}（应为 YYYY-MM-DD）")


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def import_signages_xlsx(db: Session, contents: bytes, created_by: str):
    """[新增 2026-09-07] 解析 xlsx 并批量导入标识。

    Returns: {"total": 总行数, "created": 成功数, "skipped": 跳过数, "errors": [“第N行：原因”]}
    """
    from app.services.signage_service import generate_signage_code

    wb = load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("文件内容为空")

    # 表头校验：按列名定位，允许列顺序调整但列名必须齐全（必填列）
    header = [_clean(h) for h in rows[0]]
    labels = [label for _, label in SIGNAGE_COLUMNS]
    col_idx = {}
    for label in labels:
        if label in header:
            col_idx[label] = header.index(label)
    missing_required_headers = [labels[i] for i in (1, 2) if labels[i] not in col_idx]  # 名称/分类
    if missing_required_headers:
        raise ValueError(f"模板缺少必需列：{'、'.join(missing_required_headers)}，请下载最新模板")

    def cell(row, field):
        label = dict(SIGNAGE_COLUMNS)[field]
        idx = col_idx.get(label)
        return row[idx] if idx is not None and idx < len(row) else None

    created, skipped, errors = 0, 0, []
    total = 0
    for line_no, row in enumerate(rows[1:], start=2):
        if row is None or all(_clean(c) is None for c in row):
            continue  # 空行跳过
        total += 1
        try:
            name = _clean(cell(row, "name"))
            category = _clean(cell(row, "category"))
            if not name:
                raise ValueError("名称为必填项")
            if not category:
                raise ValueError("分类为必填项")

            code = _clean(cell(row, "code"))
            if code and db.query(Signage).filter(Signage.code == code).first():
                skipped += 1
                errors.append(f"第{line_no}行：编码 {code} 已存在，已跳过")
                continue

            category_type = _clean(cell(row, "category_type")) or "标识标牌"
            if category_type not in VALID_CATEGORY_TYPES:
                raise ValueError(f"类别仅支持 {'/'.join(VALID_CATEGORY_TYPES)}，收到：{category_type}")

            zone_type = _clean(cell(row, "zone_type")) or "院区导视/宣传"
            if zone_type not in VALID_ZONE_TYPES:
                raise ValueError(f"所属区域仅支持 {'、'.join(VALID_ZONE_TYPES)}，收到：{zone_type}")

            status_raw = _clean(cell(row, "status"))
            if not status_raw:
                status = "normal"
            elif status_raw in LABEL_TO_STATUS:
                status = LABEL_TO_STATUS[status_raw]  # 中文名转英文值入库
            elif status_raw in STATUS_LABELS:
                status = status_raw  # 已是英文值
            else:
                raise ValueError(f"状态不支持：{status_raw}")

            validity_type = _clean(cell(row, "validity_type")) or "long_term"
            if validity_type in ("长期", "long_term"):
                validity_type = "long_term"
            elif validity_type in ("临时", "temporary"):
                validity_type = "temporary"
            else:
                raise ValueError(f"有效期类型仅支持 long_term/temporary，收到：{validity_type}")
            validity_until = _parse_date(cell(row, "validity_until"))
            if validity_type == "temporary" and not validity_until:
                raise ValueError("临时标识必须填写有效期至")

            campus = _clean(cell(row, "campus"))
            building = _clean(cell(row, "building"))
            floor = _clean(cell(row, "floor"))

            s = Signage(
                code=code,
                name=name,
                category=category,
                category_type=category_type,
                material=_clean(cell(row, "material")),
                size_spec=_clean(cell(row, "size_spec")),
                campus=campus,
                building=building,
                floor=floor,
                zone_type=zone_type,
                location_desc=_clean(cell(row, "location_desc")),
                display_text_cn=_clean(cell(row, "display_text_cn")),
                display_text_en=_clean(cell(row, "display_text_en")),
                status=status,
                oa_number=_clean(cell(row, "oa_number")),
                manufacturer=_clean(cell(row, "manufacturer")),
                vendor_contact=_clean(cell(row, "vendor_contact")),
                install_date=_parse_date(cell(row, "install_date")),
                warranty_expire=_parse_date(cell(row, "warranty_expire")),
                validity_type=validity_type,
                validity_until=validity_until,
            )
            # 编码留空时按「院区代号-分类编码-楼栋-楼层-序号」自动生成
            if not s.code:
                s.code = generate_signage_code(db, campus, category, building, floor)
                # 极端情况下（并发/历史数据）自动编码仍可能重复，逐次递增兜底
                while db.query(Signage).filter(Signage.code == s.code).first():
                    seq = int(s.code.split("-")[-1]) + 1
                    s.code = "-".join(s.code.split("-")[:-1]) + f"-{seq:03d}"
            s.created_by = created_by
            s.updated_by = created_by
            db.add(s)
            db.flush()
            created += 1
        except ValueError as e:
            errors.append(f"第{line_no}行：{e}")
        except Exception as e:  # 单行失败不阻断整体导入
            logger.warning("导入第%s行失败", line_no, exc_info=True)
            errors.append(f"第{line_no}行：数据异常（{e}）")
    return {"total": total, "created": created, "skipped": skipped, "errors": errors}
