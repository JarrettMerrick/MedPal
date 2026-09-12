# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""数据导入、导出、备份路由（仅管理员）"""
import io
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import urllib.parse
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile, File, Request
# [修复 2026-08-28] 补充 Query 导入，供图片导出接口接收 photo_types 多值查询参数
from fastapi import Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from openpyxl import Workbook, load_workbook
# [修复 2026-08-28] 补充 Optional/List 导入，供 photo_types 参数类型注解使用
from typing import Optional, List

from app.database import get_db
from app.dependencies import (
    get_current_user, get_current_user_optional, require_permission, has_permission,
    get_user_department_scope, get_user_work_type_scope,
    PERM_DATA_EXPORT, PERM_DATA_IMPORT, PERM_SYSTEM_BACKUP,
    # [新增 2026-09-11] 导出离职人员需额外权限
    PERM_STAFF_VIEW_RESIGNED,
    ROLE_EMPLOYEE,
)
from app.models.user import User
from app.models.department import Department, DepartmentSpecialty, SpecialtyImage, DepartmentEquipment, EquipmentImage
from app.models.staff_card import StaffCard
from app.models.export_package import ExportPackage
from app.models.regulation import Regulation, RegulationCategory, RegulationHistory
from app.config import settings, DATA_ROOT
from app.utils import decode_token, utc_now, to_beijing, get_client_ip
from app.services.audit_service import record_audit, audit_action
from app.services.auth_service import is_token_blacklisted
# [修复 2026-09-01] 将 StaffVerifyResponse 等提升为模块级导入：
# verify_staff 路由的 response_model 在装饰器处（模块加载时）即被求值，
# 原导入仅存在于函数内部导致 NameError，后端无法启动。
from app.schemas.staff import (
    StaffVerifyResponse, StaffVerifyItem,
    WORK_TYPE_DOCTOR, WORK_TYPE_NURSE, WORK_TYPE_TECHNICIAN,
)

router = APIRouter(prefix="/api/data", tags=["数据管理"])

# [修复] Excel 导入文件校验：大小上限 + 文件头魔数。
# 原先仅靠扩展名判断，伪造扩展名的大文件/畸形文件可触发 load_workbook 内存/解析 DoS。
EXCEL_MAX_SIZE_MB = 20
EXCEL_MAX_SIZE_BYTES = EXCEL_MAX_SIZE_MB * 1024 * 1024
XLSX_MAGIC = b"PK\x03\x04"          # .xlsx 本质为 ZIP 容器
XLS_MAGIC = b"\xd0\xcf\x11\xe0"     # .xls 为 OLE2 复合文档

REGULATION_COLUMNS = [
    ("name", "制度名称"), ("category_name", "所属类别"), ("category_code", "类别代码"),
    ("version", "版本"), ("content", "制度内容"),
    ("created_by", "创建人"), ("updated_by", "最后修改人"),
    ("created_at", "创建时间"), ("updated_at", "最后修改时间"),
]

# [改进] 科室导出列增加分类（临床专科/护理病区/行政科室）
DEPARTMENT_COLUMNS = [
    ("name", "科室名称"), ("category", "分类"), ("description", "科室介绍"),
]

# 备份目录 - 统一存放在数据根目录下的 data/backups（与 backend 完全隔离）
BACKUP_DIR = DATA_ROOT / "backups"


def _ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _write_rows_to_xlsx(columns, rows):
    """将数据写入 Excel 并返回 BytesIO"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # 写表头（中文列名）
    headers = [label for _, label in columns]
    ws.append(headers)

    # 写数据行
    for row in rows:
        ws.append([row.get(field, "") for field, _ in columns])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# ==================== 导出 ====================

def _delete_temp_file(path: str):
    """后台任务：删除临时文件"""
    try:
        if os.path.exists(path):
            os.unlink(path)
            logger = logging.getLogger(__name__)
            logger.debug(f"已清理导出临时文件: {path}")
    except OSError as e:
        logging.getLogger(__name__).warning(f"清理临时文件失败 {path}: {e}")


# [改进/1.0.9] 导出临时文件专用目录，便于启动时统一清理残留
TEMP_EXPORT_DIR = DATA_ROOT / "temp_exports"


def _ensure_temp_export_dir():
    """确保临时导出目录存在"""
    TEMP_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_stale_temp_files():
    """[改进/1.0.9] 应用启动时清理超过1小时的残留临时导出文件。

    正常情况下 BackgroundTasks 会在响应发送后删除临时文件，但以下场景可能导致残留：
      - 服务器崩溃/重启（BackgroundTasks 未执行）
      - 客户端提前断开连接（FileResponse 未完成传输）
      - 文件系统只读（unlink 失败但静默忽略）

    此函数在应用启动时调用，清理上一次运行残留的临时文件。
    """
    import time as _time
    logger = logging.getLogger(__name__)
    _ensure_temp_export_dir()
    cleaned_count = 0
    cutoff_age = 3600  # 1小时
    try:
        for f in TEMP_EXPORT_DIR.iterdir():
            if f.is_file() and f.suffix in (".xlsx", ".zip"):
                try:
                    age = _time.time() - f.stat().st_mtime
                    if age > cutoff_age:
                        size = f.stat().st_size
                        f.unlink()
                        cleaned_count += 1
                        logger.info(f"清理残留临时文件: {f.name} ({size} bytes, 存留 {age / 60:.0f} 分钟)")
                except OSError as e:
                    logger.warning(f"清理残留临时文件失败 {f.name}: {e}")
        if cleaned_count:
            logger.info(f"共清理 {cleaned_count} 个残留临时导出文件")
    except Exception as e:
        logger.warning(f"扫描临时导出目录失败（非致命）: {e}")


def _export_to_file(columns, rows, prefix, background_tasks: BackgroundTasks = None):
    """通用导出：生成 xlsx 临时文件并返回 FileResponse"""
    _ensure_temp_export_dir()  # [改进/1.0.9] 确保目录存在
    buf = _write_rows_to_xlsx(columns, rows)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=str(TEMP_EXPORT_DIR))
    tmp.write(buf.getvalue())
    tmp.close()
    filename = f"{prefix}_{utc_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if background_tasks:
        background_tasks.add_task(_delete_temp_file, tmp.name)
    return FileResponse(
        path=tmp.name,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/export/departments")
def export_departments(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """导出科室信息为 Excel（包含特色技术和特色设备）"""
    departments = db.query(Department).order_by(Department.id).all()
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "科室信息"
    ws1.append(["科室名称", "分类", "科室介绍"])
    for d in departments:
        ws1.append([d.name, d.category, d.description or ""])

    ws2 = wb.create_sheet("特色技术")
    # [改进] 增加"备注"列（对应卡片图片 caption），导入后可直接在列表编辑备注
    ws2.append(["科室名称", "特色技术名称", "详细简介", "排序", "备注"])
    for d in departments:
        for s in d.specialties:
            ws2.append([d.name, s.name, s.detail or "", s.sort_order, s.caption or ""])

    ws3 = wb.create_sheet("特色设备")
    # [改进] 增加"备注"列（caption）
    ws3.append(["科室名称", "设备名称", "设备型号", "功能描述", "设备特点", "排序", "备注"])
    for d in departments:
        for e in d.equipments:
            ws3.append([d.name, e.name, e.model or "", e.function_description or "", e.features or "", e.sort_order, e.caption or ""])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=str(TEMP_EXPORT_DIR))
    wb.save(tmp.name)
    tmp.close()
    background_tasks.add_task(_delete_temp_file, tmp.name)
    filename = f"科室信息_{utc_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return FileResponse(
        path=tmp.name,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/export/regulations")
def export_regulations(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """导出所有制度信息"""
    regulations = db.query(Regulation).order_by(Regulation.updated_at.desc()).all()
    rows = []
    for r in regulations:
        row = {}
        for field, _ in REGULATION_COLUMNS:
            if field == "category_code":
                val = r.category_rel.code if r.category_rel else ""
            else:
                val = getattr(r, field, "")
            if isinstance(val, datetime):
                val = val.strftime("%Y-%m-%d %H:%M")
            row[field] = val
        rows.append(row)
    return _export_to_file(REGULATION_COLUMNS, rows, "制度信息", background_tasks)


# [修复 2026-08-28] 新增 photo_types 参数，支持按照片类型（正面照/侧面照/卡片照）筛选导出；
# 同时调整 ZIP 内目录结构：不再为每个人单独建文件夹，改为同一科室所有人员扁平放置，
# 文件命名为 "工号_姓名_图片类型"。卡片照多张时追加序号（如 卡片照1、卡片照2）。
PHOTO_TYPE_LABELS = {"front": "正面照", "side": "侧面照", "card": "卡片照"}


@router.get("/export/images")
def export_images(
    background_tasks: BackgroundTasks,
    department_id: int,
    photo_types: Optional[List[str]] = Query(None, description="照片类型筛选：front/side/card，可多选，缺省为全部"),
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """打包下载指定科室的图片（支持按照片类型筛选）"""
    from app.services.upload_service import UPLOAD_ROOT

    # 归一化筛选类型：缺省或空表示全部三种
    valid_types = {"front", "side", "card"}
    if not photo_types:
        selected_types = valid_types
    else:
        selected_types = {t for t in photo_types if t in valid_types}

    # [修复/问题17] 原先先在 io.BytesIO 中构建整个压缩包、再一次性 getvalue() 落盘，
    # 大科室导出时内存峰值可达数百 MB。改为直接流式写入临时文件，
    # 压缩包不再驻留内存。
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir=str(TEMP_EXPORT_DIR))
    # [修复/问题22] 先登记删除任务，确保中间步骤抛异常时临时文件也能被回收
    background_tasks.add_task(_delete_temp_file, tmp.name)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        dept_filter = db.query(Department).filter(Department.id == department_id).first()
        if not dept_filter:
            raise HTTPException(404, "科室不存在")
        target_depts = [dept_filter]

        processed_staff = set()
        from app.models.staff import Staff

        for dept in target_depts:
            # 取该科室全部员工（不按科室类别过滤工种，避免混合科室漏打包）
            # [修复 2026-09-11] 仅打包在职人员照片：离职人员不再计入科室宣传照片包
            staff_list = db.query(Staff).filter(
                Staff.department == dept.name, Staff.status == "active",
            ).all()

            for s in staff_list:
                processed_staff.add(s.employee_id)
                person_prefix = s.employee_id

                # 正面照（[改进] 优先打包原始照片源文件 orig_ 副本，回退正式图）
                if "front" in selected_types and s.front_photo:
                    fp = _resolve_package_photo(s.front_photo)
                    if fp:
                        zf.write(fp[0], f"{person_prefix}_front{fp[1]}")
                # 侧面照
                if "side" in selected_types and s.side_photo:
                    fp = _resolve_package_photo(s.side_photo)
                    if fp:
                        zf.write(fp[0], f"{person_prefix}_side{fp[1]}")

                # 人员卡片（[修复 2026-08-28] 每人仅保留一张卡片照，只导出最新一条，文件名固定为 卡片照）
                if "card" in selected_types:
                    card = db.query(StaffCard).filter(
                        StaffCard.entity_type == s.work_type,
                        StaffCard.entity_id == s.employee_id,
                    ).order_by(StaffCard.uploaded_at.desc(), StaffCard.id.desc()).first()
                    # B1：将卡片照片一并写入压缩包，避免备份缺失
                    if card and card.card_photo:
                        fp = _resolve_package_photo(card.card_photo)
                        if fp:
                            zf.write(fp[0], f"{person_prefix}_card{fp[1]}")

            # 科室特色技术图片
            # [修复/问题17] 预先批量取出特色技术名称建字典，
            # 避免循环内对每张图再查一次库（N+1），查询量随图片数线性膨胀
            spec_names = {
                sp.id: sp.name for sp in db.query(DepartmentSpecialty).filter(
                    DepartmentSpecialty.department_id == dept.id,
                ).all()
            }
            images = db.query(SpecialtyImage).join(DepartmentSpecialty).filter(
                DepartmentSpecialty.department_id == dept.id,
            ).all()
            for img in images:
                spec_name = spec_names.get(img.specialty_id) or f"技术{img.specialty_id}"
                sanitized = "".join(c if c.isalnum() or c in " _-" else "_" for c in spec_name)
                img_name = (img.caption or f"图片{img.id}").strip()
                img_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in img_name)
                fp = _resolve_package_photo(img.image_url)
                if fp:
                    zf.write(fp[0], f"科室特色技术/{dept.name}/{sanitized}/{img_name}{fp[1]}")

            # 科室特色设备图片
            # [修复/问题17] 同上：批量预取设备名称，消除 N+1
            equip_names = {
                eq.id: eq.name for eq in db.query(DepartmentEquipment).filter(
                    DepartmentEquipment.department_id == dept.id,
                ).all()
            }
            equip_images = db.query(EquipmentImage).join(DepartmentEquipment).filter(
                DepartmentEquipment.department_id == dept.id,
            ).all()
            for img in equip_images:
                equip_name = equip_names.get(img.equipment_id) or f"设备{img.equipment_id}"
                sanitized = "".join(c if c.isalnum() or c in " _-" else "_" for c in equip_name)
                img_name = (img.caption or f"图片{img.id}").strip()
                img_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in img_name)
                fp = _resolve_package_photo(img.image_url)
                if fp:
                    zf.write(fp[0], f"科室特色设备/{dept.name}/{sanitized}/{img_name}{fp[1]}")

    # tmp 已在上方创建并登记删除任务，这里只需关闭句柄
    tmp.close()
    filename = f"图片打包_{utc_now().strftime('%Y%m%d_%H%M%S')}.zip"
    return FileResponse(
        path=tmp.name,
        filename=filename,
        media_type="application/zip",
    )


# ==================== 图片打包（异步） ====================

# 导出目录 - 统一存放在数据根目录下的 data/exports（与 backend 完全隔离，
# 与 backup_service.BACKUP_DIR 同源于 app.config.DATA_ROOT）
EXPORT_DIR = DATA_ROOT / "exports"
PACKAGE_RETENTION_DAYS = 1


def _ensure_export_dir():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_zip_name(name: str) -> str:
    """将名称中的特殊字符替换为下划线，确保 ZIP 内路径安全"""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name)


def _resolve_package_photo(rel_path: str) -> tuple[str, str] | None:
    """[改进] 解析照片打包用路径：优先返回原始照片源文件（orig_ 前缀副本），
    不存在时回退正式图（兼容旧数据/无独立原文件的场景）。

    需求：照片打包下载的图片应为用户上传的照片源文件，而非前端裁剪后的正式图。
    上传时原始文件以 orig_ 前缀同目录另存（见 upload_service.save_upload_file），
    其扩展名可能与正式图不同（原文件为 PNG/WebP 时保留原格式），故按
    "正式图原扩展名 → jpg → jpeg → png → webp" 顺序探测（与前端 getOriginalPreferredCandidates 一致）。

    Returns:
        (绝对路径, 实际文件扩展名含点)；文件不存在返回 None
    """
    from app.services.upload_service import UPLOAD_ROOT, ORIG_PREFIX
    main_path = os.path.join(UPLOAD_ROOT, rel_path)
    if not os.path.exists(main_path):
        return None

    dir_name = os.path.dirname(main_path)
    stem = os.path.splitext(os.path.basename(main_path))[0]
    primary_ext = os.path.splitext(rel_path)[1].lstrip(".").lower()
    # 候选扩展名去重：正式图原扩展名优先，其次常见原图格式
    orig_exts = list(dict.fromkeys(
        e for e in [primary_ext, "jpg", "jpeg", "png", "webp"] if e
    ))
    for ext in orig_exts:
        candidate = os.path.join(dir_name, f"{ORIG_PREFIX}{stem}.{ext}")
        if os.path.exists(candidate):
            return candidate, f".{ext}"

    # 无 orig_ 副本（旧数据）时回退正式图
    return main_path, os.path.splitext(main_path)[1] or ".jpg"


# [修复 2026-08-28] 新增 photo_types 参数，支持按照片类型筛选导出；
# ZIP 内目录结构改为同一科室扁平放置（科室/工号_姓名_类型），不再为个人单独建文件夹。
def _build_package_background(package_id: int, department_id: int, photo_types: Optional[set] = None):
    """[改进] 后台打包任务 — 分三阶段执行以最小化数据库写锁占用时间：
    Phase 1: 收集所有 ZIP 条目（短只读事务）
    Phase 2: 构建 ZIP 文件（无数据库操作）
    Phase 3: 更新打包状态（短写事务）
    整个过程通过串行锁保护，防止多个打包任务或备份任务并发。"""
    from app.database import SessionLocal
    from app.services.task_queue import run_serial

    def _do_pack():
        import logging as _logging
        _logger = _logging.getLogger("hospital")

        # === Phase 1: 收集所有需要打包的文件路径 ===
        db = SessionLocal()
        try:
            pkg = db.query(ExportPackage).filter(ExportPackage.id == package_id).first()
            if not pkg:
                return

            filename = pkg.filename  # 在 session 关闭前提取值

            # 收集目标科室
            dept_filter = db.query(Department).filter(Department.id == department_id).first()
            if not dept_filter:
                return
            target_depts = [dept_filter]

            # [修复 2026-08-28] 解析照片类型筛选：优先用入参，其次用记录字段，缺省为全部
            valid_types = {"front", "side", "card"}
            if photo_types:
                selected_types = {t for t in photo_types if t in valid_types}
            elif getattr(pkg, "photo_types", None):
                selected_types = {t.strip() for t in pkg.photo_types.split(",") if t.strip() in valid_types}
            else:
                selected_types = valid_types
            if not selected_types:
                selected_types = valid_types

            # 预先收集所有人员及其卡片（批量查询，避免 N+1）
            from app.models.staff import Staff
            from sqlalchemy import or_

            WORK_TYPE_LABELS = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政"}

            # 收集科室→人员列表
            dept_staff_map = {}       # dept.id -> [Staff]
            all_staff_keys = []       # [(work_type, employee_id), ...]

            for dept in target_depts:
                # 取该科室全部员工（不按科室类别过滤工种，避免混合科室漏打包）
                # [修复 2026-09-11] 仅打包在职人员照片（离职人员不计入科室照片包）
                staff_list = db.query(Staff).filter(
                    Staff.department == dept.name, Staff.status == "active",
                ).all()
                dept_staff_map[dept.id] = staff_list
                for s in staff_list:
                    all_staff_keys.append((s.work_type, s.employee_id))

            # 批量查询所有卡片
            # [修复 2026-08-28] 每人仅保留一张卡片照：按最新上传时间取唯一一条存入 card_map
            card_map = {}  # (entity_type, entity_id) -> StaffCard（仅最新一张）
            if all_staff_keys:
                conditions = [
                    (StaffCard.entity_type == wt) & (StaffCard.entity_id == eid)
                    for wt, eid in all_staff_keys
                ]
                all_cards = db.query(StaffCard).filter(or_(*conditions)).all()
                for c in all_cards:
                    key = (c.entity_type, c.entity_id)
                    existing = card_map.get(key)
                    if existing is None or (c.uploaded_at, c.id) > (existing.uploaded_at, existing.id):
                        card_map[key] = c

            # 收集所有 ZIP 条目：(本地文件绝对路径, ZIP内路径)
            zip_entries = []

            for dept in target_depts:
                # [修复 2026-08-28] 扁平命名：仅保留科室层，不再按工种/个人建文件夹
                folder = dept.name
                for s in dept_staff_map.get(dept.id, []):
                    person_prefix = s.employee_id
                    if "front" in selected_types and s.front_photo:
                        fp = _resolve_package_photo(s.front_photo)
                        if fp:
                            zip_entries.append((fp[0], f"{person_prefix}_front{fp[1]}"))
                    if "side" in selected_types and s.side_photo:
                        fp = _resolve_package_photo(s.side_photo)
                        if fp:
                            zip_entries.append((fp[0], f"{person_prefix}_side{fp[1]}"))
                    # [修复 2026-08-28] 每人仅导出最新一张卡片照，文件名固定为 卡片照
                    card = card_map.get((s.work_type, s.employee_id))
                    if "card" in selected_types and card and card.card_photo:
                        fp = _resolve_package_photo(card.card_photo)
                        if fp:
                            zip_entries.append((fp[0], f"{person_prefix}_card{fp[1]}"))

                # 科室特色技术图片
                images = db.query(SpecialtyImage).join(DepartmentSpecialty).filter(
                    DepartmentSpecialty.department_id == dept.id,
                ).all()
                for img in images:
                    spec = db.query(DepartmentSpecialty).filter(
                        DepartmentSpecialty.id == img.specialty_id
                    ).first()
                    spec_name = spec.name if spec else f"技术{img.specialty_id}"
                    sanitized_spec = _sanitize_zip_name(spec_name)
                    img_caption = _sanitize_zip_name((img.caption or f"图片{img.id}").strip())
                    fp = _resolve_package_photo(img.image_url)
                    if fp:
                        zip_entries.append((
                            fp[0],
                            f"科室特色技术/{dept.name}/{sanitized_spec}/{img_caption}{fp[1]}",
                        ))

                # 科室特色设备图片
                equip_images = db.query(EquipmentImage).join(DepartmentEquipment).filter(
                    DepartmentEquipment.department_id == dept.id,
                ).all()
                for img in equip_images:
                    equip = db.query(DepartmentEquipment).filter(
                        DepartmentEquipment.id == img.equipment_id
                    ).first()
                    equip_name = equip.name if equip else f"设备{img.equipment_id}"
                    sanitized_equip = _sanitize_zip_name(equip_name)
                    img_caption = _sanitize_zip_name((img.caption or f"图片{img.id}").strip())
                    fp = _resolve_package_photo(img.image_url)
                    if fp:
                        zip_entries.append((
                            fp[0],
                            f"科室特色设备/{dept.name}/{sanitized_equip}/{img_caption}{fp[1]}",
                        ))
        finally:
            db.close()

        # === Phase 2: 构建 ZIP（无数据库操作） ===
        _ensure_export_dir()
        zip_path = EXPORT_DIR / filename

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in zip_entries:
                zf.write(file_path, arcname)

        file_size = zip_path.stat().st_size

        # === Phase 3: 更新状态（短写事务，毫秒级） ===
        db2 = SessionLocal()
        try:
            pkg2 = db2.query(ExportPackage).filter(ExportPackage.id == package_id).first()
            if pkg2:
                pkg2.status = "completed"
                pkg2.file_size = file_size
                pkg2.expires_at = utc_now() + timedelta(days=PACKAGE_RETENTION_DAYS)
                db2.commit()
        except Exception as e:
            _logger.error(f"更新打包状态失败 package_id={package_id}: {e}", exc_info=True)
        finally:
            db2.close()

    try:
        run_serial(_do_pack)
    except Exception as e:
        # 异常时更新为失败状态
        _logger = logging.getLogger("hospital")
        _logger.error(f"打包失败 package_id={package_id}: {e}", exc_info=True)
        db_fail = SessionLocal()
        try:
            pkg_fail = db_fail.query(ExportPackage).filter(ExportPackage.id == package_id).first()
            if pkg_fail:
                pkg_fail.status = "failed"
                db_fail.commit()
        finally:
            db_fail.close()


@router.post("/export/packages")
def create_package(
    department_id: int,
    photo_types: Optional[List[str]] = Query(None, description="照片类型筛选：front/side/card，可多选，缺省为全部"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """创建图片打包任务（后台异步执行，仅支持按科室打包，支持按照片类型筛选）"""
    # [修复 2026-08-28] 归一化照片类型筛选参数
    valid_types = {"front", "side", "card"}
    if photo_types:
        selected_types = sorted(t for t in photo_types if t in valid_types)
    else:
        selected_types = sorted(valid_types)
    photo_types_str = ",".join(selected_types)

    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        raise HTTPException(404, "科室不存在")
    dept_name = dept.name

    _ensure_export_dir()
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    # 替换科室名中的特殊字符，避免文件路径问题
    safe_dept_name = dept_name.replace("/", "_").replace("\\", "_")
    filename = f"图片打包_{safe_dept_name}_{timestamp}.zip"

    pkg = ExportPackage(
        department_id=department_id,
        department_name=dept_name,
        photo_types=photo_types_str,  # [修复 2026-08-28] 持久化筛选类型，便于列表展示
        filename=filename,
        file_size=0,
        status="packing",
        created_at=utc_now(),
        expires_at=utc_now() + timedelta(days=PACKAGE_RETENTION_DAYS),
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)

    # [改进] 后台打包不再传递 db session，由任务内部自行管理连接生命周期
    # [修复 2026-08-28] 透传 photo_types 集合，供后台任务按类型筛选
    background_tasks.add_task(
        _build_package_background,
        pkg.id,
        department_id,
        set(selected_types),
    )

    return {
        "id": pkg.id,
        "department_name": dept_name,
        "photo_types": photo_types_str,
        "status": "packing",
        "created_at": pkg.created_at.isoformat(),
        "message": "打包任务已创建，请在后台列表中查看进度",
    }


@router.get("/export/packages")
def list_packages(
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """获取打包记录列表"""
    pkgs = db.query(ExportPackage).order_by(ExportPackage.created_at.desc()).limit(50).all()
    return [
        {
            "id": p.id,
            "department_name": p.department_name,
            "filename": p.filename,
            "file_size": p.file_size,
            "status": p.status,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            "expires_at": p.expires_at.strftime("%Y-%m-%d %H:%M:%S") if p.expires_at else "",
        }
        for p in pkgs
    ]


@router.get("/export/packages/{package_id}/download")
def download_package(
    package_id: int,
    request: Request,
    ftoken: str | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """下载打包文件（支持断点续传/Range请求）

    [修复/问题19] 移除 `?token=<完整 JWT>` 查询参数鉴权路径。
    完整 JWT 出现在 URL 会被浏览器历史、反向代理/服务器访问日志、Referer 头记录，
    显著扩大令牌泄露面。现仅保留两种鉴权方式：
      1) Authorization 头（推荐；前端已改为 fetch + Blob 下载，见问题12）
      2) 短期文件访问令牌 ftoken（仅在无法携带 Header 的场景兜底）
    """
    if not current_user:
        # 短期文件访问令牌（仅用于无法带 Header 的场景，如 <img>/新窗口直接打开）
        if ftoken:
            from app.utils import decode_file_access_token
            emp_id = decode_file_access_token(ftoken)
            if emp_id:
                candidate = db.query(User).filter(User.employee_id == emp_id).first()
                if candidate and candidate.is_active:
                    current_user = candidate
        if not current_user:
            raise HTTPException(401, "未登录")
    
    if not has_permission(current_user, PERM_DATA_EXPORT):
        raise HTTPException(403, "无权限下载")

    # [改进/A2] 导出包下载留痕（可能涉及批量 PHI 导出，需可追溯）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "export_download", current_user.employee_id,
                     detail=f"package_id={package_id}", target=str(package_id), ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    
    pkg = db.query(ExportPackage).filter(ExportPackage.id == package_id).first()
    if not pkg:
        raise HTTPException(404, "打包记录不存在")
    if pkg.status != "completed":
        raise HTTPException(400, "打包尚未完成，请稍候")
    if pkg.expires_at and utc_now() > pkg.expires_at:
        raise HTTPException(410, "打包文件已过期，请重新打包")

    zip_path = EXPORT_DIR / pkg.filename
    if not zip_path.exists():
        raise HTTPException(404, "打包文件不存在")

    file_size = zip_path.stat().st_size

    # 处理 Range 请求（断点续传）
    range_header = request.headers.get("range")
    if range_header:
        start, end = 0, file_size - 1
        try:
            range_val = range_header.replace("bytes=", "")
            if "-" in range_val:
                parts = range_val.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if parts[1] else file_size - 1
        except (ValueError, IndexError):
            start, end = 0, file_size - 1

        if start >= file_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        end = min(end, file_size - 1)
        content_length = end - start + 1

        with open(zip_path, "rb") as f:
            f.seek(start)
            body = f.read(content_length)

        encoded_filename = urllib.parse.quote(pkg.filename)
        return Response(
            content=body,
            status_code=206,
            media_type="application/zip",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
        )

    # 全量下载（FileResponse 自动处理 Content-Disposition）
    return FileResponse(
        path=zip_path,
        filename=pkg.filename,
        media_type="application/zip",
        headers={"Accept-Ranges": "bytes"},
    )


@router.delete("/export/packages/{package_id}")
def delete_package(
    package_id: int,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """删除打包记录及文件"""
    pkg = db.query(ExportPackage).filter(ExportPackage.id == package_id).first()
    if not pkg:
        raise HTTPException(404, "打包记录不存在")

    zip_path = EXPORT_DIR / pkg.filename
    if zip_path.exists():
        os.remove(zip_path)

    db.delete(pkg)
    db.commit()
    return {"message": "已删除"}


# ==================== 导入模板 ====================

@router.get("/template/departments")
def template_departments(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
):
    """下载科室导入模板（包含特色技术和特色设备工作表）"""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "科室信息"
    ws1.append(["科室名称", "分类", "科室介绍"])

    ws2 = wb.create_sheet("特色技术")
    ws2.append(["科室名称", "特色技术名称", "详细简介", "排序", "备注"])

    ws3 = wb.create_sheet("特色设备")
    ws3.append(["科室名称", "设备名称", "设备型号", "功能描述", "设备特点", "排序", "备注"])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", dir=str(TEMP_EXPORT_DIR))
    wb.save(tmp.name)
    tmp.close()
    background_tasks.add_task(_delete_temp_file, tmp.name)
    filename = "科室导入模板.xlsx"
    return FileResponse(
        path=tmp.name,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ==================== 导入 ====================

@router.post("/import/departments")
async def import_departments(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission(PERM_DATA_IMPORT)),
    db: Session = Depends(get_db),
):
    """从 Excel 导入科室信息（包含特色技术和特色设备）"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    # [修复] 校验文件头魔数与大小，防止伪造扩展名/超大文件触发解析 DoS
    contents = await file.read()
    if len(contents) > EXCEL_MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"文件超过 {EXCEL_MAX_SIZE_MB}MB 限制")
    if contents[:4] != XLSX_MAGIC and contents[:8] != XLS_MAGIC:
        raise HTTPException(status_code=400, detail="文件内容不是有效的 Excel 文件")

    wb = load_workbook(io.BytesIO(contents), read_only=True)

    # Sheet1: 科室基本信息
    if "科室信息" not in wb.sheetnames:
        raise HTTPException(status_code=400, detail='缺少"科室信息"工作表')

    ws1 = wb["科室信息"]
    header_row = next(ws1.iter_rows(values_only=True), None)
    if not header_row:
        raise HTTPException(status_code=400, detail="科室信息工作表为空")

    # 科室分类合法值集合
    VALID_CATEGORIES = {"临床专科", "护理病区", "行政科室"}

    headers1 = [str(h).strip() if h else "" for h in header_row]
    name_idx = headers1.index("科室名称") if "科室名称" in headers1 else -1
    category_idx = headers1.index("分类") if "分类" in headers1 else -1
    desc_idx = headers1.index("科室介绍") if "科室介绍" in headers1 else -1

    if name_idx == -1:
        raise HTTPException(status_code=400, detail='缺少"科室名称"列')

    added = 0
    skipped_dept = 0

    # 读取科室（含分类）
    dept_rows = []
    for row in ws1.iter_rows(min_row=2, values_only=True):
        row_list = list(row)
        if name_idx >= len(row_list):
            continue
        name = str(row_list[name_idx]).strip() if row_list[name_idx] else ""
        if not name:
            continue
        desc = str(row_list[desc_idx]).strip() if desc_idx >= 0 and desc_idx < len(row_list) and row_list[desc_idx] else ""
        # [改进] 读取分类列，无效值降级为默认值"临床专科"
        raw_cat = str(row_list[category_idx]).strip() if category_idx >= 0 and category_idx < len(row_list) and row_list[category_idx] else ""
        category = raw_cat if raw_cat in VALID_CATEGORIES else "临床专科"
        dept_rows.append((name, desc, category))

    # 读取特色技术（如果有）
    specialties_map = {}
    if "特色技术" in wb.sheetnames:
        ws2 = wb["特色技术"]
        h2 = next(ws2.iter_rows(values_only=True), None)
        if h2:
            h2_labels = [str(c).strip() if c else "" for c in h2]
            dept_name_idx = h2_labels.index("科室名称") if "科室名称" in h2_labels else -1
            spec_name_idx = h2_labels.index("特色技术名称") if "特色技术名称" in h2_labels else -1
            spec_detail_idx = h2_labels.index("详细简介") if "详细简介" in h2_labels else -1
            sort_idx = h2_labels.index("排序") if "排序" in h2_labels else -1
            # [改进] 读取备注（caption）列，可选兼容旧模板无此列
            caption_idx = h2_labels.index("备注") if "备注" in h2_labels else -1

            for row in ws2.iter_rows(min_row=2, values_only=True):
                r = list(row)
                if dept_name_idx < 0 or spec_name_idx < 0:
                    continue
                dept = str(r[dept_name_idx]).strip() if dept_name_idx < len(r) and r[dept_name_idx] else ""
                spec_name = str(r[spec_name_idx]).strip() if spec_name_idx < len(r) and r[spec_name_idx] else ""
                if not dept or not spec_name:
                    continue
                detail = str(r[spec_detail_idx]).strip() if spec_detail_idx >= 0 and spec_detail_idx < len(r) and r[spec_detail_idx] else ""
                sort_order = int(r[sort_idx]) if sort_idx >= 0 and sort_idx < len(r) and r[sort_idx] else 0
                caption = str(r[caption_idx]).strip() if caption_idx >= 0 and caption_idx < len(r) and r[caption_idx] else ""

                if dept not in specialties_map:
                    specialties_map[dept] = []
                specialties_map[dept].append({"name": spec_name, "detail": detail, "sort_order": sort_order, "caption": caption})

    # 读取特色设备（如果有）
    equipments_map = {}
    if "特色设备" in wb.sheetnames:
        ws3 = wb["特色设备"]
        h3 = next(ws3.iter_rows(values_only=True), None)
        if h3:
            h3_labels = [str(c).strip() if c else "" for c in h3]
            dept_name_idx = h3_labels.index("科室名称") if "科室名称" in h3_labels else -1
            equip_name_idx = h3_labels.index("设备名称") if "设备名称" in h3_labels else -1
            model_idx = h3_labels.index("设备型号") if "设备型号" in h3_labels else -1
            function_idx = h3_labels.index("功能描述") if "功能描述" in h3_labels else -1
            features_idx = h3_labels.index("设备特点") if "设备特点" in h3_labels else -1
            sort_idx = h3_labels.index("排序") if "排序" in h3_labels else -1
            # [改进] 读取备注（caption）列，可选兼容旧模板无此列
            caption_idx = h3_labels.index("备注") if "备注" in h3_labels else -1

            for row in ws3.iter_rows(min_row=2, values_only=True):
                r = list(row)
                if dept_name_idx < 0 or equip_name_idx < 0:
                    continue
                dept = str(r[dept_name_idx]).strip() if dept_name_idx < len(r) and r[dept_name_idx] else ""
                equip_name = str(r[equip_name_idx]).strip() if equip_name_idx < len(r) and r[equip_name_idx] else ""
                if not dept or not equip_name:
                    continue
                model = str(r[model_idx]).strip() if model_idx >= 0 and model_idx < len(r) and r[model_idx] else ""
                function_desc = str(r[function_idx]).strip() if function_idx >= 0 and function_idx < len(r) and r[function_idx] else ""
                features = str(r[features_idx]).strip() if features_idx >= 0 and features_idx < len(r) and r[features_idx] else ""
                sort_order = int(r[sort_idx]) if sort_idx >= 0 and sort_idx < len(r) and r[sort_idx] else 0
                caption = str(r[caption_idx]).strip() if caption_idx >= 0 and caption_idx < len(r) and r[caption_idx] else ""

                if dept not in equipments_map:
                    equipments_map[dept] = []
                equipments_map[dept].append({
                    "name": equip_name,
                    "model": model,
                    "function_description": function_desc,
                    "features": features,
                    "sort_order": sort_order,
                    "caption": caption,
                })

    # 导入科室
    for name, desc, category in dept_rows:
        existing = db.query(Department).filter(Department.name == name).first()
        if existing:
            skipped_dept += 1
            continue

        department = Department(name=name, description=desc or None, category=category)
        db.add(department)
        db.flush()

        # 添加特色技术
        specs = specialties_map.get(name, [])
        for sp in specs:
            spec = DepartmentSpecialty(
                department_id=department.id,
                name=sp["name"],
                detail=sp["detail"] or None,
                caption=sp.get("caption") or None,
                sort_order=sp.get("sort_order", 0),
            )
            db.add(spec)

        # 添加特色设备
        equips = equipments_map.get(name, [])
        for eq in equips:
            equip = DepartmentEquipment(
                department_id=department.id,
                name=eq["name"],
                model=eq["model"] or None,
                function_description=eq["function_description"] or None,
                features=eq["features"] or None,
                caption=eq.get("caption") or None,
                sort_order=eq.get("sort_order", 0),
            )
            db.add(equip)

        added += 1

    db.commit()
    # [改进/A2] 科室批量导入留痕
    # [修复/问题25] 改用统一审计助手，消除重复样板
    audit_action(db, "import_departments", current_user.employee_id, request,
                 detail=f"added={added}, skipped={skipped_dept}", target="departments")
    return {"message": f"导入完成，成功 {added} 条，跳过 {skipped_dept} 条", "added": added, "skipped": skipped_dept}


# ==================== 统一员工导出/导入/模板 ====================

STAFF_COLUMNS = [
    ("employee_id", "工号"), ("name", "姓名"), ("work_type", "工种"),
    ("education", "学历"), ("title", "职称"), ("department", "所属部门"),
    ("position", "职务"), ("status", "状态"),
    ("expertise_short", "专业擅长（短）"),
    ("expertise_standard", "专业擅长（标准）"),
    ("social_appointments", "社会任职"), ("honors", "获得荣誉"), ("remarks", "备注"),
]


@router.get("/export/staff")
def export_staff(
    background_tasks: BackgroundTasks,
    work_type: str | None = None,
    department: str | None = None,
    status: str | None = "active",
    fields: str | None = None,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """导出人员信息（支持按工种/科室/状态筛选，支持自定义字段选择）"""
    from app.models.staff import Staff

    # [修复 2026-09-11] 导出离职人员需额外具备 staff.view_resigned，
    # 否则可绕过「离职人员」页面的门禁批量导出离职名单
    if status == "resigned" and not has_permission(current_user, PERM_STAFF_VIEW_RESIGNED):
        raise HTTPException(status_code=403, detail="无权导出离职人员")

    query = db.query(Staff)
    if work_type:
        query = query.filter(Staff.work_type == work_type)
    if department:
        query = query.filter(Staff.department == department)
    if status:
        query = query.filter(Staff.status == status)
    staff_list = query.order_by(Staff.work_type, Staff.employee_id).all()

    # 字段选择
    if fields:
        selected_fields = [f.strip() for f in fields.split(",") if f.strip()]
        export_columns = [(f, next((l for fl, l in STAFF_COLUMNS if fl == f), f)) for f in selected_fields]
    else:
        export_columns = STAFF_COLUMNS

    rows = [{field: getattr(s, field, "") or "" for field, _ in export_columns} for s in staff_list]

    prefix = "人员信息"
    if work_type:
        type_names = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政"}
        prefix = f"{type_names.get(work_type, work_type)}信息"
    return _export_to_file(export_columns, rows, prefix, background_tasks)


@router.get("/template/staff")
def template_staff(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
):
    """下载员工导入模板"""
    return _export_to_file(STAFF_COLUMNS, [], "员工导入模板", background_tasks)


@router.get("/template/regulations")
def template_regulations(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
):
    """下载制度导入模板"""
    # [改进] 去掉「版本」列（版本号由后端自动生成），增加「类别代码」（3位大写字母）和「制度内容」
    columns = [("name", "制度名称"), ("category_name", "所属类别"), ("category_code", "类别代码"), ("content", "制度内容")]
    return _export_to_file(columns, [], "制度导入模板", background_tasks)


@router.post("/import/staff")
async def import_staff(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission(PERM_DATA_IMPORT)),
    db: Session = Depends(get_db),
):
    """统一导入人员信息"""
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "仅支持 .xlsx/.xls 格式")

    from app.models.staff import Staff
    from app.models.user import User as UserModel

    contents = await file.read()
    # [修复] 校验文件头魔数与大小，防止伪造扩展名/超大文件触发解析 DoS
    if len(contents) > EXCEL_MAX_SIZE_BYTES:
        raise HTTPException(400, f"文件超过 {EXCEL_MAX_SIZE_MB}MB 限制")
    if contents[:4] != XLSX_MAGIC and contents[:8] != XLS_MAGIC:
        raise HTTPException(400, "文件内容不是有效的 Excel 文件")
    wb = load_workbook(io.BytesIO(contents), read_only=True)
    ws = wb.active
    rows_list = list(ws.iter_rows(values_only=True))
    if not rows_list:
        raise HTTPException(400, "文件为空")
    headers = [str(h).strip() if h else "" for h in rows_list[0]]

    if "工号" not in headers:
        raise HTTPException(400, "缺少'工号'列")

    col_map = {}
    for i, h in enumerate(headers):
        for field, label in STAFF_COLUMNS:
            if h == label:
                col_map[field] = i
                break

    added, skipped = 0, 0
    details = []  # 行级处理详情
    warnings = []  # 截断警告

    # 字段长度限制定义
    _MAX_LENGTHS = {
        "employee_id": 20, "name": 50, "work_type": 20,
        "education": 50, "title": 50, "department": 100,
        "position": 50, "status": 20,
    }

    # 工种合法值映射
    VALID_WORK_TYPES = {"doctor", "nurse", "technician", "admin"}
    WORK_TYPE_MAP = {"医生": "doctor", "护士": "nurse", "技师": "technician", "行政": "admin"}

    # 状态合法值映射
    VALID_STATUSES = {"active", "resigned"}
    STATUS_MAP = {"在职": "active", "离职": "resigned"}

    pending_emp_ids = set()  # 跟踪本批次已添加的工号，避免重复

    for row_idx, row in enumerate(rows_list[1:], start=2):
        emp_col = headers.index("工号") if "工号" in headers else None
        if emp_col is None or emp_col >= len(row):
            details.append({"row": row_idx, "status": "skipped", "reason": "行数据缺少工号列或单元格"})
            skipped += 1
            continue
        emp_id_raw = row[emp_col]
        emp_id = str(emp_id_raw).strip()
        if not emp_id:
            details.append({"row": row_idx, "status": "skipped", "reason": "工号为空"})
            skipped += 1
            continue
        # 检查数据库中是否已存在（含批量内重复检查）
        if emp_id in pending_emp_ids:
            details.append({"row": row_idx, "employee_id": emp_id, "status": "skipped", "reason": "本批次内工号重复"})
            skipped += 1
            continue
        existing = db.query(Staff).filter(Staff.employee_id == emp_id).first()
        if existing:
            details.append({"row": row_idx, "employee_id": emp_id, "status": "skipped", "reason": "工号已存在"})
            skipped += 1
            continue
        pending_emp_ids.add(emp_id)

        data = {"employee_id": emp_id}
        for field, idx in col_map.items():
            if field == "employee_id":
                continue
            val = row[idx] if idx < len(row) else None
            data[field] = str(val).strip() if val is not None else ""

        if "name" not in data or not data.get("name"):
            details.append({"row": row_idx, "employee_id": emp_id, "status": "skipped", "reason": "姓名为空"})
            skipped += 1
            continue

        # I2: 工种值校验与映射
        raw_work_type = data.get("work_type", "")
        if raw_work_type and raw_work_type not in VALID_WORK_TYPES:
            mapped_wt = WORK_TYPE_MAP.get(raw_work_type)
            if mapped_wt:
                data["work_type"] = mapped_wt
                warnings.append(f"第{row_idx}行 工种'{raw_work_type}'已自动映射为'{mapped_wt}'")
            else:
                data["work_type"] = "doctor"
                warnings.append(f"第{row_idx}行 工种'{raw_work_type}'无法识别，已默认设为'doctor'")

        # I3: 状态值校验与映射
        raw_status = data.get("status", "")
        if raw_status and raw_status not in VALID_STATUSES:
            mapped_status = STATUS_MAP.get(raw_status)
            if mapped_status:
                data["status"] = mapped_status
                warnings.append(f"第{row_idx}行 状态'{raw_status}'已自动映射为'{mapped_status}'")
            else:
                data["status"] = "active"
                warnings.append(f"第{row_idx}行 状态'{raw_status}'无法识别，已默认设为'active'")

        # I1: 字段长度校验 — 截断时记录警告，避免用户数据丢失无感知
        for field, max_len in _MAX_LENGTHS.items():
            if field in data and isinstance(data[field], str) and len(data[field]) > max_len:
                original = data[field]
                data[field] = data[field][:max_len]
                warnings.append(f"第{row_idx}行 {field}超过{max_len}字符限制，已截断")

        # 默认值
        data.setdefault("work_type", "doctor")
        data.setdefault("department", data.get("department", ""))
        data.setdefault("status", "active")

        staff = Staff(**data)
        db.add(staff)
        added += 1
        details.append({"row": row_idx, "employee_id": emp_id, "name": data.get("name", ""), "status": "success"})

        # 自动创建用户账号
        existing_user = db.query(UserModel).filter(UserModel.employee_id == emp_id).first()
        if not existing_user:
            from app.services.auth_service import get_default_password
            from app.utils import hash_password
            user = UserModel(
                employee_id=emp_id,
                name=data["name"],
                # [调整 2026-09-10] 初始口令按「账号设置」中的模板生成（支持 {工号} 占位符）
                password_hash=hash_password(get_default_password(db, emp_id)),
                role=ROLE_EMPLOYEE,
                department=data.get("department", ""),
                # [改进] user_type 映射与前端一致：doctor→doctor, nurse→nurse, technician/admin→admin_user
                user_type="doctor" if data.get("work_type") == "doctor" else "nurse" if data.get("work_type") == "nurse" else "admin_user",
                # [修复 2026-09-11] 导入「离职」人员时账号不得启用（原先漏设，离职者仍可登录）
                is_active=(data.get("status") != "resigned"),
                must_change_password=True,
            )
            db.add(user)

    db.commit()
    result = {
        "message": f"导入完成，成功 {added} 条新增，跳过 {skipped} 条",
        "added": added,
        "skipped": skipped,
        "details": details,
    }
    if warnings:
        result["warnings"] = warnings
        result["message"] += f"，{len(warnings)} 条警告（请查看 warnings 字段）"
    # [改进/A2] 人员批量导入留痕
    # [修复/问题25] 改用统一审计助手，消除重复样板
    audit_action(db, "import_staff", current_user.employee_id, request,
                 detail=f"added={added}, skipped={skipped}", target="staff")
    return result


@router.post("/import/regulations")
async def import_regulations(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission(PERM_DATA_IMPORT)),
    db: Session = Depends(get_db),
):
    """导入制度信息"""
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "仅支持 .xlsx/.xls 格式")

    contents = await file.read()
    # [修复] 校验文件头魔数与大小，防止伪造扩展名/超大文件触发解析 DoS
    if len(contents) > EXCEL_MAX_SIZE_BYTES:
        raise HTTPException(400, f"文件超过 {EXCEL_MAX_SIZE_MB}MB 限制")
    if contents[:4] != XLSX_MAGIC and contents[:8] != XLS_MAGIC:
        raise HTTPException(400, "文件内容不是有效的 Excel 文件")
    wb = load_workbook(io.BytesIO(contents), read_only=True)
    ws = wb.active
    rows_list = list(ws.iter_rows(values_only=True))
    if not rows_list:
        raise HTTPException(400, "文件为空")
    headers = [str(h).strip() if h else "" for h in rows_list[0]]

    if "制度名称" not in headers:
        raise HTTPException(400, "缺少'制度名称'列")

    editor = current_user.employee_id or current_user.name
    added, skipped = 0, 0

    # 辅助：从 Excel 行中安全取值
    def _val(col: str, default: str = "") -> str:
        if col not in headers: return default
        idx = headers.index(col)
        return str(row[idx]).strip() if idx < len(row) and row[idx] else default

    for row in rows_list[1:]:
        name = _val("制度名称")
        if not name:
            continue

        if db.query(Regulation).filter(Regulation.name == name).first():
            skipped += 1
            continue

        # —— 类别：按名称查已有，否则新建（含类别代码） ——
        cat_name = _val("所属类别", "通用")
        category = db.query(RegulationCategory).filter(RegulationCategory.name == cat_name).first()
        if not category:
            cat_code = _val("类别代码", "").upper()
            # [改进] 类别代码须为3位大写字母，缺或非法则从类别名称自动生成
            if not re.match(r'^[A-Z]{3}$', cat_code):
                cat_code = cat_name[:3].upper().ljust(3, 'X')  # 取前3字母补X
                if not re.match(r'^[A-Z]{3}$', cat_code):
                    # 中文名称等极端情况，纯字母取不到则用 "GEN" + 全局自增序号兜底
                    base_code = "GEN"
                    exist_codes = {c[0] for c in db.query(RegulationCategory.code).filter(
                        RegulationCategory.code.like(f"{base_code}%")
                    ).all() if c[0]}
                    seq = 0
                    while f"{base_code}{seq:02d}"[:3] in exist_codes:
                        seq += 1
                    cat_code = f"{base_code}{seq:03d}"[:3]
            # 唯一性兜底
            if db.query(RegulationCategory).filter(RegulationCategory.code == cat_code).first():
                base = cat_code[:2]
                for seq in range(0, 100):
                    alt = f"{base}{seq:01d}"
                    if alt not in {c[0] for c in db.query(RegulationCategory.code).filter(
                        RegulationCategory.code.like(f"{base}%")
                    ).all() if c[0]}:
                        cat_code = alt
                        break
            category = RegulationCategory(name=cat_name, code=cat_code, sort_order=0)
            db.add(category)
            db.flush()

        # —— 制度内容 ——
        content = _val("制度内容", "")

        # [改进] 版本号自动生成：V01_{类别代码}_{年月日}
        version = f"V01_{category.code or 'XXX'}_{utc_now().strftime('%y%m%d')}"

        reg = Regulation(
            name=name,
            category_id=category.id,
            category_name=cat_name,
            version=version,
            content=content,
            created_by=editor,
            updated_by=editor,
        )
        db.add(reg)
        db.flush()

        # [改进] 创建历史版本记录（含内容快照）
        hist = RegulationHistory(
            regulation_id=reg.id,
            version=version,
            content=content,
            edited_by=editor,
            change_summary="批量导入",
        )
        db.add(hist)
        added += 1

    db.commit()
    # [改进/A2] 制度批量导入留痕
    # [修复/问题25] 改用统一审计助手，消除重复样板
    audit_action(db, "import_regulations", current_user.employee_id, request,
                 detail=f"added={added}, skipped={skipped}", target="regulations")
    return {"message": f"导入完成，成功 {added} 条新增，跳过 {skipped} 条已存在", "added": added, "skipped": skipped}


@router.post("/import/photos")
async def import_photos(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission(PERM_DATA_IMPORT)),
    db: Session = Depends(get_db),
):
    """批量导入照片。上传 ZIP，文件命名：{工号}_{front|side|card}.{ext}"""
    from app.models.staff import Staff
    from app.models.staff_card import StaffCard
    from app.services.upload_service import ensure_upload_dirs, detect_image_format, UPLOAD_ROOT, generate_thumbnail, save_original_copy, convert_to_rgb

    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(400, "仅支持 .zip 格式")
    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(400, "ZIP 文件超过 100MB 限制")
    try:
        zf = zipfile.ZipFile(io.BytesIO(contents))
    except Exception:
        raise HTTPException(400, "无法解析 ZIP 文件")

    ensure_upload_dirs()
    PHOTO_MAP = {'front': 'front_photo', 'side': 'side_photo', 'card': 'card_photo'}
    ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
    FMT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".jpg"}
    imported, skipped, errors = 0, 0, []

    for zi in zf.infolist():
        if zi.is_dir() or zi.filename.startswith(('__', '.')):
            continue
        fname = os.path.basename(zi.filename)
        if not fname:
            continue
        name_no_ext, ext = os.path.splitext(fname)
        ext = ext.lower()
        if ext not in ALLOWED_EXT:
            errors.append(f"跳过 {fname}: 格式不支持"); skipped += 1; continue
        parts = name_no_ext.rsplit('_', 1)
        if len(parts) != 2 or parts[1].lower() not in PHOTO_MAP:
            errors.append(f"跳过 {fname}: 应为 {{工号}}_{{front|side|card}}.{{ext}}")
            skipped += 1; continue
        emp_id, ptype = parts[0], parts[1].lower()

        staff = db.query(Staff).filter(Staff.employee_id == emp_id).first()
        if not staff:
            errors.append(f"跳过 {fname}: 工号 {emp_id} 不存在"); skipped += 1; continue

        file_bytes = zf.read(zi.filename)
        if len(file_bytes) > 20 * 1024 * 1024:
            errors.append(f"跳过 {fname}: 超过 20MB"); skipped += 1; continue

        real_fmt = detect_image_format(file_bytes)
        if real_fmt and real_fmt not in ('JPEG', 'PNG', 'WebP'):
            errors.append(f"跳过 {fname}: 格式 {real_fmt} 不支持"); skipped += 1; continue

        # 生成保存路径
        save_ext = FMT_EXT.get(real_fmt, ".jpg") if real_fmt else ext
        ts = utc_now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]
        save_name = f"{emp_id}_{ptype}_{ts}_{uid}{save_ext}"
        entity_type = "card" if ptype == "card" else staff.work_type
        save_dir = os.path.join(UPLOAD_ROOT, entity_type)
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, save_name)

        # 保存文件
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        # [修复] 与正常上传流程一致：CMYK转RGB、生成缩略图
        convert_to_rgb(save_path)
        generate_thumbnail(save_path)

        # 更新数据库
        relative_path = f"{entity_type}/{save_name}"
        field = PHOTO_MAP[ptype]
        if ptype == 'card':
            card = db.query(StaffCard).filter(
                StaffCard.entity_id == emp_id,
                StaffCard.entity_type == staff.work_type,
            ).first()
            if card:
                card.card_photo = relative_path
            else:
                db.add(StaffCard(
                    entity_type=staff.work_type,
                    entity_id=emp_id,
                    card_photo=relative_path,
                    uploaded_by=current_user.employee_id,
                ))
        else:
            setattr(staff, field, relative_path)
        imported += 1

    # [修复/问题9] 显式关闭 zip 句柄并释放内存缓冲。
    # 原实现在整个导入循环结束后从未调用 close，完全依赖 GC 回收，
    # 重复/高并发导入会累积文件描述符与内存（单次上限 100MB）。
    zf.close()
    del contents

    db.commit()
    # 审计日志
    # [修复/问题25] 改用统一审计助手，内部处理 IP 获取、落库提交与异常回滚，
    # 消除重复的 try/commit/rollback 样板
    audit_action(db, "import_photos", current_user.employee_id, request,
                 detail=f"imported={imported}, skipped={skipped}", target="photos")

    msg = f"导入完成，成功 {imported} 张，跳过 {skipped} 张"
    if errors:
        msg += f"（{len(errors)} 条警告）"
    return {"message": msg, "imported": imported, "skipped": skipped, "errors": errors[:10]}
@router.post("/backup")
def backup_database(
    request: Request,
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
    db: Session = Depends(get_db),
):
    """手动备份数据库"""
    from app.services.backup_service import create_backup
    result = create_backup()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "备份失败"))
    # [改进/A2] 备份操作留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "backup", current_user.employee_id,
                     detail=f"filename={result['filename']}", target=result["filename"], ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    return {"message": "备份成功", "filename": result["filename"], "size": result["size"]}


@router.get("/backups")
def list_backups(
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
):

    """获取备份文件列表"""
    from app.services.backup_service import get_backup_list
    return get_backup_list()


@router.delete("/backups")
def delete_backup(
    filename: str,
    request: Request,
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
    db: Session = Depends(get_db),
):
    """删除指定备份文件"""
    from app.services.backup_service import delete_backup as _delete_backup
    result = _delete_backup(filename)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    # [改进/A2] 删除备份留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "backup_delete", current_user.employee_id,
                     detail=f"filename={filename}", target=filename, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    return {"message": result["message"]}


@router.post("/restore")
def restore_database(
    filename: str,
    request: Request,
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
    db: Session = Depends(get_db),
):
    """从备份文件恢复数据库"""
    # [改进/A2 + 修复/问题10a] 此处写入的是「发起恢复」的留痕，
    # 它会随数据库被备份覆盖而丢失（但仍保留在 prerestore 预防性备份中）；
    # 真正的「恢复完成」留痕由 backup_service._restore_backup_impl 在恢复成功
    # 之后写入恢复后的新库，避免审计记录被自己发起的恢复操作覆盖掉。
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "restore_request", current_user.employee_id,
                     detail=f"filename={filename}", target=filename, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    from app.services.backup_service import restore_backup
    # [修复] 恢复会重建引擎并替换数据库文件；Windows 下若请求级 session
    # 仍 checkout 持有 medical.db 句柄，文件删除/替换将失败（WinError 32，
    # engine.dispose() 不会关闭正在使用中的连接）。先关闭当前 session
    # 释放连接，再执行恢复。
    db.close()
    # 文件名净化在 backup_service.restore_backup 内部完成（IO2）
    result = restore_backup(filename, current_user.employee_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "恢复失败"))
    return {"message": result["message"]}


@router.get("/download-backup")
def download_backup(
    filename: str,
    request: Request,
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
    db: Session = Depends(get_db),
):
    """下载备份文件"""
    from app.services.backup_service import _resolve_backup_path
    # [改进/IO2] 净化文件名，防止 ?filename=../../ 下载任意文件
    try:
        backup_path = _resolve_backup_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法的备份文件名")
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    # [改进/A2] 下载备份（含完整数据库）留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "backup_download", current_user.employee_id,
                     detail=f"filename={filename}", target=filename, ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    return FileResponse(
        path=str(backup_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@router.post("/restore/upload")
async def restore_upload_database(
    file: UploadFile = File(...),
    confirm_password: str = Form(None),
    current_user: User = Depends(require_permission(PERM_SYSTEM_BACKUP)),
):
    # [修复] 移除未使用的 db 依赖：恢复会重建引擎并替换 medical.db，
    # Windows 下请求级 session 会 checkout 连接锁住文件（WinError 32）。
    # 本接口不需要数据库访问，去掉依赖避免创建连接。
    """从上传的备份文件恢复数据库（需 system.backup 权限，并二次密码确认）

    [修复]
    1. 权限判断由硬编码角色名 'admin_manager' 改为统一权限点 require_permission(PERM_SYSTEM_BACKUP)，
       与 restore_database 接口保持一致，避免自定义角色名导致校验失效。
    2. 增加上传文件大小限制与 SQLite 文件头（魔数）校验，原先仅靠 .db 扩展名且无大小上限，
       管理员可上传超大文件耗尽磁盘或上传畸形文件替换生产数据库。
    """
    # [修复] 恢复上传大小上限（200MB，备份库规模通常远小于此）
    MAX_RESTORE_UPLOAD_MB = 200
    MAX_RESTORE_UPLOAD_BYTES = MAX_RESTORE_UPLOAD_MB * 1024 * 1024
    # SQLite 数据库文件头魔数（前 16 字节）
    SQLITE_MAGIC = b"SQLite format 3\x00"

    from app.utils import verify_password
    if not confirm_password or not verify_password(confirm_password, current_user.password_hash):
        raise HTTPException(status_code=403, detail="恢复操作需要输入正确的登录密码进行二次确认")
    if not file.filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="请上传 .db 备份文件")

    # [修复] 校验文件头确认为真实 SQLite 数据库，防止伪造扩展名的任意文件
    head = await file.read(16)
    await file.seek(0)
    if head[:16] != SQLITE_MAGIC:
        raise HTTPException(status_code=400, detail="上传文件不是有效的 SQLite 数据库备份")

    from app.services.backup_service import restore_backup, BACKUP_DIR as _BACKUP_DIR

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    filename = f"upload_{timestamp}.db"
    file_path = _BACKUP_DIR / filename

    # [修复] 逐块复制并统计大小，超过上限中断并清理，防止超大文件耗尽磁盘
    total = 0
    try:
        with open(file_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESTORE_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"备份文件超过 {MAX_RESTORE_UPLOAD_MB}MB 限制",
                    )
                buffer.write(chunk)

        result = restore_backup(filename)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "恢复失败"))

        return {"message": result["message"]}
    except HTTPException:
        # [修复] 清理已写入的残留文件（超限/恢复失败等场景）
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 数据核对 ====================

@router.get("/verify-staff", response_model=StaffVerifyResponse)
def verify_staff(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    work_type: str | None = Query(None, description="按工种核对: doctor-医生/nurse-护士/technician-技师"),
    department: str | None = Query(None, description="按部门筛选"),
    status: str | None = Query("active", description="状态筛选: active-在职, resigned-离职"),
    only_missing: bool = Query(False, description="仅返回信息不完整的人员（total 此时为缺失人数）"),
    current_user: User = Depends(require_permission(PERM_DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """数据核对：筛选出信息未填写完整的人员（医生/护士/技师）。

    [修复 2026-09-11] 该接口同样可按 status=resigned 列出离职人员，需与列表/导出口径一致，
    额外要求 staff.view_resigned 权限。

    [修复 2026-09-01] 新增数据核对功能：
    - 核对范围：医生(doctor)/护士(nurse)/技师(technician)，行政不参与核对；
    - 核对项：
      医生：姓名、职称、专业擅长（短）、专业擅长（标准）、个人照片、卡片照片；
      护士/技师：姓名、职称、照片、卡片照片（不审核专业擅长）；
    - [修复 2026-09-02] 专业擅长审核规则：医生拆分为“专业擅长（短）”(expertise_short)
      与“专业擅长（标准）”(expertise_standard)两项分别核对；护士/技师不审核专业擅长；
    - 卡片照片是否填写依据 staff_cards 表是否存在该工号的记录（任意状态均视为已填写）；
    - 个人照片/照片对应 staff.front_photo（正面形象照）或 staff.side_photo（侧面形象照），任一非空即视为已填写；
    - 权限：需要 data.export 权限，并复用人员列表的科室/工种数据范围过滤
      （department_scope / work_type_scope），防止越权查看范围外人员信息。
    """
    from app.models.staff import Staff

    # [修复 2026-09-11] 核对离职人员需额外具备 staff.view_resigned（与列表/导出口径一致）
    if status == "resigned" and not has_permission(current_user, PERM_STAFF_VIEW_RESIGNED):
        raise HTTPException(status_code=403, detail="无权核对离职人员")

    VERIFY_WORK_TYPES = (WORK_TYPE_DOCTOR, WORK_TYPE_NURSE, WORK_TYPE_TECHNICIAN)
    if work_type and work_type not in VERIFY_WORK_TYPES:
        raise HTTPException(status_code=400, detail="仅支持核对医生/护士/技师")

    empty_response = StaffVerifyResponse(
        total=0, missing_total=0, items=[], page=page, page_size=page_size
    )

    # —— 数据范围过滤（复用人员列表 list_staff 的权限逻辑）——
    department_filter = None
    from app.dependencies import _get_role_dept_scope
    scope = _get_role_dept_scope(current_user)
    if scope == "all":
        if department:
            department_filter = department
    else:
        managed_dept_ids = get_user_department_scope(current_user, db)
        if managed_dept_ids:
            dept_names = [d.name for d in db.query(Department).filter(Department.id.in_(managed_dept_ids)).all()]
            if dept_names:
                if department:
                    if department not in dept_names:
                        raise HTTPException(status_code=403, detail="无权访问该科室")
                    department_filter = department
                else:
                    department_filter = "||".join(dept_names)
            else:
                return empty_response
        else:
            return empty_response

    work_type_filter = None
    from app.dependencies import _get_role_work_type_scope
    wt_scope = _get_role_work_type_scope(current_user)
    if wt_scope and "all" not in wt_scope:
        allowed_work_types = get_user_work_type_scope(current_user)
        if allowed_work_types:
            if work_type:
                if work_type not in allowed_work_types:
                    return empty_response
                work_type_filter = work_type
            else:
                work_type_filter = ",".join(allowed_work_types)

    # —— 查询核对范围内的人员 ——
    query = db.query(Staff)
    if status:
        query = query.filter(Staff.status == status)
    if work_type:
        query = query.filter(Staff.work_type == work_type)
    else:
        query = query.filter(Staff.work_type.in_(list(VERIFY_WORK_TYPES)))
    if work_type_filter and not work_type:
        wt_list = [w.strip() for w in work_type_filter.split(",") if w.strip()]
        if wt_list:
            query = query.filter(Staff.work_type.in_(wt_list))
    if department_filter:
        dept_list = [d.strip() for d in department_filter.split("||") if d.strip()]
        if dept_list:
            query = query.filter(Staff.department.in_(dept_list))
    elif department == "__none__":
        query = query.filter(Staff.department.is_(None))

    staff_all = query.order_by(Staff.work_type, Staff.employee_id).all()

    # 一次性查询范围内人员的卡片照片记录（避免 N+1）
    card_ids = set()
    if staff_all:
        emp_ids = [s.employee_id for s in staff_all]
        for c in db.query(StaffCard.entity_id).filter(StaffCard.entity_id.in_(emp_ids)).all():
            card_ids.add(c[0])

    def _missing(r: Staff) -> tuple[list[str], list[str]]:
        fields, labels = [], []
        if not (r.name or "").strip():
            fields.append("name")
            labels.append("姓名")
        if not (r.title or "").strip():
            fields.append("title")
            labels.append("职称")
        # [修复 2026-09-02] 专业擅长审核规则调整：
        # 护士/技师不审核专业擅长；医生按“专业擅长（短）”与“专业擅长（标准）”分别审核。
        if r.work_type == WORK_TYPE_DOCTOR:
            if not (r.expertise_short or "").strip():
                fields.append("expertise_short")
                labels.append("专业擅长（短）")
            if not (r.expertise_standard or "").strip():
                fields.append("expertise_standard")
                labels.append("专业擅长（标准）")
        # 护士/技师不审核专业擅长（不加入缺失项）
        # [修复 2026-09-01] 正面照或侧面照只要有一张即认定有个人照片
        if not ((r.front_photo or "").strip() or (r.side_photo or "").strip()):
            fields.append("photo")
            labels.append("个人照片" if r.work_type == WORK_TYPE_DOCTOR else "照片")
        if r.employee_id not in card_ids:
            fields.append("card")
            labels.append("卡片照片")
        return fields, labels

    all_items = []
    for s in staff_all:
        missing_fields, missing_labels = _missing(s)
        all_items.append(StaffVerifyItem(
            employee_id=s.employee_id,
            name=s.name or "",
            work_type=s.work_type,
            department=s.department,
            missing_fields=missing_fields,
            missing_labels=missing_labels,
        ))

    missing_total = sum(1 for i in all_items if i.missing_fields)
    if only_missing:
        # 仅返回信息不完整的人员，total 即为缺失人数（保证前端分页总数准确）
        all_items = [i for i in all_items if i.missing_fields]
        total = len(all_items)
    else:
        total = len(all_items)
    start = (page - 1) * page_size
    return StaffVerifyResponse(
        total=total,
        missing_total=missing_total,
        items=all_items[start:start + page_size],
        page=page,
        page_size=page_size,
    )
