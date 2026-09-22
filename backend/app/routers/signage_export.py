# [重构 2026-09-07] 标识导入导出路由（原文件为预警路由的重复副本，预警统一由 signage_alerts.py 提供）：
# - GET  /api/signage-export/xlsx|csv          按院区/楼栋/分类/状态/关键词筛选导出标识数据
# - GET  /api/signage-export/attachments       批量导出设计文件、安装现场照片及标识二维码（zip）
# - GET  /api/signage-export/import-template   下载导入模板
# - POST /api/signage-export/import            上传 xlsx 批量导入标识
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from app.database import get_db
from app.dependencies import (
    get_current_user, has_permission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_CREATE,
    # [修复 2026-09-17] 导出范围过滤 + 任务归属可见性所需的工具
    get_user_department_scope, _get_role_dept_scope,
)
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


def _allowed_scope(current_user: User, db: Session):
    """[新增 2026-09-17] 当前用户的导出科室范围：all 返回 None（不限），其余返回科室 ID 列表"""
    if _get_role_dept_scope(current_user) == "all":
        return None
    return get_user_department_scope(current_user, db)


def _task_visible(task: dict, current_user: User) -> bool:
    """[新增 2026-09-17] 导出任务是否对当前用户可见。

    all 范围（超管）可见全部；其余角色仅可见本人创建的任务。
    历史任务无 owner 字段，对非超管不可见（避免归属不明任务泄露）。
    """
    if _get_role_dept_scope(current_user) == "all":
        return True
    return task.get("owner") == current_user.employee_id


@router.get("/xlsx")
def export_xlsx(
    filters: dict = Depends(_common_filters),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[重构 2026-09-07] 导出标识台账 xlsx"""
    _check_view_perm(current_user)
    # [修复 2026-09-17] 导出范围与角色科室作用域一致（原先受限角色可导出全院台账）
    output = svc.export_signages_xlsx(db, allowed_department_ids=_allowed_scope(current_user, db), **filters)
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
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
    # [修复 2026-09-17] 导出范围与角色科室作用域一致（原先受限角色可导出全院台账）
    output = svc.export_signages_csv(db, allowed_department_ids=_allowed_scope(current_user, db), **filters)
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return _file_response(output, filename, "text/csv; charset=utf-8")


# ==================== [重构 2026-09-08] 附件批量导出：两步式（生成任务 → 下载） ====================
# 单个压缩包不超过 500MB，超限自动分卷；压缩包保留 24 小时，到期由定时任务自动清理

from fastapi import BackgroundTasks
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)


@router.post("/attachments/prepare", status_code=202)
def prepare_attachments(
    background_tasks: BackgroundTasks,
    include_design: bool = Query(True, description="包含设计文件"),
    include_photo: bool = Query(True, description="包含现场照片"),
    include_qrcode: bool = Query(True, description="包含标识二维码"),
    filters: dict = Depends(_common_filters),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    # [修复 2026-09-17] 补充 db 依赖：既用于计算创建者的导出科室范围，
    # 同时修复了下方审计调用因缺少 db 变量抛 NameError 被 except 静默吞掉的既有问题
    db: Session = Depends(get_db),
):
    """[新增 2026-09-08] 第一步：创建附件打包任务（后台执行），立即返回 task_id 供轮询"""
    _check_view_perm(current_user)
    # [修复 2026-09-17] 记录任务归属人 + 创建时的科室范围快照：
    # 归属用于任务可见性隔离，范围快照供后台打包任务沿用（防止越范围打包）
    task = svc.create_export_task(
        **filters,
        include_design=include_design, include_photo=include_photo, include_qrcode=include_qrcode,
        owner=current_user.employee_id,
        allowed_department_ids=_allowed_scope(current_user, db),
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return task


@router.get("/attachments/tasks")
def list_attachments_tasks(current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 列出最近的附件导出任务（含状态/分卷/过期时间）。

    [修复 2026-09-17] 补权限校验 + 任务归属过滤：原实现仅要求登录且返回全部用户的任务，
    任何登录账号都可枚举他人的导出行为（筛选条件 / 分卷文件名 / 统计数 / 过期时间）。
    """
    _check_view_perm(current_user)
    owner = None if _get_role_dept_scope(current_user) == "all" else current_user.employee_id
    return svc.list_export_tasks(owner=owner)


@router.get("/attachments/status/{task_id}")
def attachments_status(task_id: str, current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 第二步：轮询任务状态（processing/done/failed + 分卷列表）。

    [修复 2026-09-17] 补权限校验 + 任务归属校验（非本人任务按"不存在"处理，避免泄露存在性）。
    """
    _check_view_perm(current_user)
    m = svc.get_export_task(task_id)
    if not m or not _task_visible(m, current_user):
        raise HTTPException(status_code=404, detail="导出任务不存在或已过期")
    return m


@router.get("/attachments/download/{task_id}/{filename}")
def download_attachment_part(task_id: str, filename: str, current_user: User = Depends(get_current_user)):
    """[新增 2026-09-08] 第二步：下载指定分卷压缩包。

    [修复 2026-09-17] 补任务归属校验：原先任意 signage.view 用户可下载他人任务的分卷。
    """
    _check_view_perm(current_user)
    m = svc.get_export_task(task_id)
    if not m or not _task_visible(m, current_user):
        raise HTTPException(status_code=404, detail="导出任务不存在或已过期")
    path = svc.get_export_part_path(task_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="压缩包不存在或已过期清理")
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.delete("/attachments/{task_id}")
def delete_attachment_task(task_id: str, current_user: User = Depends(get_current_user)):
    """手动删除指定的附件导出任务（连同已生成的压缩包）。

    [新增 2026-09-22] 此前导出包只能等 24 小时保留期自动清理。用户若在生成后
    立刻发现筛选条件选错（导出包体积不小、含二维码与附件），只能干等一天。

    安全设计（与 status / download 两个只读接口保持一致的口径）：
      - 权限：复用 _check_view_perm，与查看导出任务的权限一致
        （能看就能删自己的，不额外抬高门槛）；
      - 归属：不可见的任务一律按 **404「不存在」** 处理，而不是 403 ——
        避免通过状态码差异试探出"某个 task_id 是否存在"；
      - 越权与路径安全由服务层 delete_export_task 兜底断言。
    """
    _check_view_perm(current_user)
    m = svc.get_export_task(task_id)
    if not m or not _task_visible(m, current_user):
        raise HTTPException(status_code=404, detail="导出任务不存在或已过期")

    # 与 list_attachments_tasks 同口径：不限科室范围的角色（scope=all）可删任意任务
    owner = None if _get_role_dept_scope(current_user) == "all" else current_user.employee_id
    ok, message = svc.delete_export_task(task_id, owner=owner)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


@router.get("/import-template")
def download_import_template(current_user: User = Depends(get_current_user)):
    """[新增 2026-09-07] 下载标识导入模板（含填写说明页）。

    [修复 2026-09-17] 补权限校验：模板虽无业务数据，但属标识模块功能，须登录且有标识查看权限。
    """
    _check_view_perm(current_user)
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
        except Exception:
            # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
            # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
            logger.warning(
                "旁路操作失败（已忽略，不影响主流程）", exc_info=True
            )
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
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return result
