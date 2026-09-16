# [重构 2026-09-07] 标识导入导出路由（原文件为预警路由的重复副本，预警统一由 signage_alerts.py 提供）：
# - GET  /api/signage-export/xlsx|csv          按院区/楼栋/分类/状态/关键词筛选导出标识数据
# - GET  /api/signage-export/attachments       批量导出设计文件、安装现场照片及标识二维码（zip）
# - GET  /api/signage-export/import-template   下载导入模板
# - POST /api/signage-export/import            上传 xlsx 批量导入标识
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from app.database import get_db
from app.dependencies import get_current_user, has_permission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_CREATE
from app.models.user import User
from app.services import signage_export_service as svc
# [新增 2026-09-09] 导入/导出审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
from app.utils import utc_now, get_client_ip

router = APIRouter(prefix="/api/signage-export", tags=["标识导入导出"])

XLSX_MAGIC = b"PK\x03\x04"  # .xlsx 本质为 ZIP 容器（与 data_io.py 校验口径一致）


def _file_response(buf, filename: str, media_type: str, extra_headers: dict | None = None):
    """[新增 2026-09-07] 统一的文件下载响应（RFC 5987 中文文件名编码）"""
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    if extra_headers:
        headers.update(extra_headers)
    return StreamingResponse(buf, media_type=media_type, headers=headers)


def _common_filters(
    campus: str | None = Query(None, description="院区名称"),
    building: str | None = Query(None, description="楼栋名称"),
    category: str | None = Query(None, description="标识分类"),
    status: str | None = Query(None, description="标识状态值"),
    search: str | None = Query(None, description="编码/名称关键词"),
):
    return {"campus": campus, "building": building, "category": category, "status": status, "search": search}


def _check_view_perm(current_user: User):
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")


@router.get("/xlsx")
def export_xlsx(
    filters: dict = Depends(_common_filters),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[重构 2026-09-07] 导出标识台账 xlsx"""
    _check_view_perm(current_user)
    output = svc.export_signages_xlsx(db, **filters)
    # [统一时间口径] 下载文件名时间戳统一用北京时间（与维修记录导出等保持一致）
    from app.utils import beijing_now
    filename = f"标识台账_{beijing_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    # [新增 2026-09-09] 导出审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_export", current_user.employee_id,
                     detail=f"format=xlsx, campus={filters.get('campus')}, building={filters.get('building')}, category={filters.get('category')}, status={filters.get('status')}, search={filters.get('search')}",
                     target="xlsx", ip_address=client_ip)
        db.commit()
    except Exception: pass
    return _file_response(
        output,
        filename,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/csv")
def export_csv(
    filters: dict = Depends(_common_filters),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[重构 2026-09-07] 导出标识台账 CSV（utf-8-sig）"""
    _check_view_perm(current_user)
    output = svc.export_signages_csv(db, **filters)
    # [统一时间口径] 下载文件名时间戳统一用北京时间（与 xlsx 导出口径一致）
    from app.utils import beijing_now
    filename = f"标识台账_{beijing_now().strftime('%Y%m%d_%H%M%S')}.csv"
    # [新增 2026-09-09] 导出审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_export", current_user.employee_id,
                     detail=f"format=csv, campus={filters.get('campus')}, building={filters.get('building')}, category={filters.get('category')}, status={filters.get('status')}, search={filters.get('search')}",
                     target="csv", ip_address=client_ip)
        db.commit()
    except Exception: pass
    return _file_response(output, filename, "text/csv; charset=utf-8")


# ==================== [重构 2026-09-08] 附件批量导出：两步式（生成任务 → 下载） ====================
# 单个压缩包不超过 500MB，超限自动分卷；压缩包保留 24 小时，到期由定时任务自动清理

from fastapi import BackgroundTasks
from fastapi.responses import FileResponse


@router.post("/attachments/prepare", status_code=202)
def prepare_attachments(
    background_tasks: BackgroundTasks,
    include_design: bool = Query(True, description="包含设计文件"),
    include_photo: bool = Query(True, description="包含现场照片"),
    include_qrcode: bool = Query(True, description="包含标识二维码"),
    filters: dict = Depends(_common_filters),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    """[新增 2026-09-08] 第一步：创建附件打包任务（后台执行），立即返回 task_id 供轮询"""
    _check_view_perm(current_user)
    task = svc.create_export_task(
        **filters,
        include_design=include_design, include_photo=include_photo, include_qrcode=include_qrcode,
    )
    # [修复/问题4] 原实现直接把同步重任务交给 BackgroundTasks，
    # FastAPI 会在响应返回后于**事件循环线程内**调用它；run_export_task 内含大量
    # I/O 与 CPU 工作（逐个生成二维码、读取设计/现场照片、分卷写 zip），
    # 会长时间独占事件循环，导致期间所有其它请求（含健康检查）全部停滞。
    # 改为交给线程池执行，事件循环立即释放；串行锁 run_serial 已保证 SQLite 写安全，
    # 迁移到线程池不会破坏互斥。
    from fastapi.concurrency import run_in_threadpool
    background_tasks.add_task(
        run_in_threadpool,
        svc.run_export_task, task["task_id"], **filters,
        include_design=include_design, include_photo=include_photo, include_qrcode=include_qrcode,
    )
    # [新增 2026-09-09] 附件导出任务创建审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_export_attachments", current_user.employee_id,
                     detail=f"task_id={task.get('task_id')}, design={include_design}, photo={include_photo}, qrcode={include_qrcode}",
                     target=task.get("task_id"), ip_address=client_ip)
        db.commit()
    except Exception: pass
    return task


@router.get("/attachments/tasks")
def list_attachments_tasks(current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 列出最近的附件导出任务（含状态/分卷/过期时间）"""
    return svc.list_export_tasks()


@router.get("/attachments/status/{task_id}")
def attachments_status(task_id: str, current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 第二步：轮询任务状态（processing/done/failed + 分卷列表）"""
    m = svc.get_export_task(task_id)
    if not m:
        raise HTTPException(status_code=404, detail="导出任务不存在或已过期")
    return m


@router.get("/attachments/download/{task_id}/{filename}")
def download_attachment_part(task_id: str, filename: str, current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 第二步：下载指定分卷压缩包"""
    _check_view_perm(current_user)
    path = svc.get_export_part_path(task_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="压缩包不存在或已过期清理")
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.get("/import-template")
def download_import_template(current_user: User = Depends(get_current_user)):
    """[新增 2026-09-07] 下载标识导入模板（含填写说明页）"""
    output = svc.build_import_template()
    return _file_response(
        output,
        "标识导入模板.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/import")
async def import_signages(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-07] 上传 xlsx 批量导入标识，返回成功/跳过与逐行错误明细"""
    if not has_permission(current_user, PERM_SIGNAGE_CREATE):
        raise HTTPException(status_code=403, detail="权限不足")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式文件")
    contents = await file.read()
    if contents[:4] != XLSX_MAGIC:
        raise HTTPException(status_code=400, detail="文件格式不正确，请上传 .xlsx 文件（可先下载导入模板）")
    try:
        result = svc.import_signages_xlsx(db, contents, current_user.employee_id)
    except ValueError as e:
        # [新增 2026-09-09] 导入失败记入系统日志（ERROR）
        try:
            client_ip = get_client_ip(request)
            record_audit(db, "error", current_user.employee_id,
                         detail=f"signage_import_failed: {str(e)}", target="signage_import", ip_address=client_ip)
            db.commit()
        except Exception: pass
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    # [新增 2026-09-09] 导入审计留痕
    try:
        client_ip = get_client_ip(request)
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        record_audit(db, "signage_import", current_user.employee_id,
                     detail=f"file={file.filename}, imported={summary.get('imported')}, skipped={summary.get('skipped')}, errors={summary.get('errors')}",
                     target=file.filename, ip_address=client_ip)
        db.commit()
    except Exception: pass
    return result
