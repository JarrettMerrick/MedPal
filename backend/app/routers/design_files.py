# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库路由：设计文件的集中管理（检索 / 上传 / 元数据 / 版本 / 回收站 / 批量）。

[新增 2026-09-17] 需求：标识管理下新增「文件管理」，集中管理所有已上传的设计文件；
内置「标准设计文件」标记，被标记后可在标识表单中搜索选择复用。

权限：
    file.view    浏览 / 预览 / 下载 / 查看详情与统计
    file.upload  上传文件、上传新版本
    file.edit    改名 / 改分类 / 打标签 / 标记标准 / 版本回滚
    file.delete  删除（软删）、恢复、彻底删除（含批量）

说明：
- 列表与详情的「引用数」来自 signages.design_file_id；被引用文件受引用保护，不可删除；
- 预览仅对图片与 PDF 开放，其余类型（AI/PSD/CDR/EPS/ZIP）走下载；
- 所有文件访问都经过后端鉴权，不直接依赖 /uploads 静态路由。
"""

import logging
import os

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user, require_any_permission,
    PERM_FILE_DELETE, PERM_FILE_EDIT, PERM_FILE_UPLOAD, PERM_FILE_VIEW,
)
from app.models.user import User
from app.schemas.design_file import (
    BatchCategoryRequest, BatchIdsRequest, BatchStandardRequest, BatchTagsRequest,
    DesignFileUpdate,
)
from app.services import design_file_service as svc
from app.services import file_taxonomy_service as tax
from app.services.audit_service import record_audit
from app.services.upload_service import UPLOAD_ROOT
from app.utils import beijing_now, get_client_ip

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["文件库"])

# 预览用 MIME（仅图片与 PDF 内联展示）
_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
}


def _media_type(ext: str | None) -> str:
    if ext == ".pdf":
        return "application/pdf"
    return _IMAGE_MEDIA_TYPES.get(ext or "", "application/octet-stream")


def _get_or_404(db: Session, file_id: int):
    record = svc.get_file(db, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    return record


# ==================== 列表与统计（静态路径需定义在 /{file_id} 之前） ====================

@router.get("")
def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    keyword: str | None = Query(None, description="关键词：显示名 / 备注 / 引用该文件的标识编码与名称"),
    # [调整 2026-09-17] 分类统一为「标识设置 → 标识分类」（扁平结构），不再有「含子分类」的层级语义
    category_id: int | None = Query(None, description="分类ID（标识分类）"),
    tag_ids: str | None = Query(None, description="标签ID（逗号分隔，多个为「同时包含」）"),
    start_date: str | None = Query(None, description="上传时间起（YYYY-MM-DD）"),
    end_date: str | None = Query(None, description="上传时间止（YYYY-MM-DD）"),
    is_standard: bool | None = Query(None, description="是否只看标准设计文件"),
    uncategorized: bool = Query(False, description="只看未分类文件"),
    only_deleted: bool = Query(False, description="只看回收站"),
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """文件库分页检索（关键词 / 分类 / 标签 / 上传时间 / 标准标记 / 回收站）"""
    parsed_tag_ids: list[int] = []
    if tag_ids:
        for chunk in tag_ids.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                parsed_tag_ids.append(int(chunk))
    items, total = svc.list_files(
        db, page=page, page_size=page_size, keyword=keyword, category_id=category_id,
        tag_ids=parsed_tag_ids,
        start_date=start_date, end_date=end_date, is_standard=is_standard,
        only_deleted=only_deleted, uncategorized=uncategorized,
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/summary")
def file_summary(
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """文件库概览：总数 / 标准文件数 / 未分类数 / 回收站数 / 占用空间"""
    return svc.count_summary(db)


@router.get("/standard-options")
def standard_options(
    keyword: str | None = Query(None, description="按文件名搜索"),
    category_id: int | None = Query(None, description="按标识分类 ID 过滤"),
    category_name: str | None = Query(
        None, description="按标识分类名过滤（标识表单传自身分类，实现同分类引用约束）",
    ),
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """标准设计文件选项（标识表单「从标准库选择」使用）"""
    return {"items": svc.list_standard_options(
        db, keyword=keyword, category_id=category_id, category_name=category_name,
    )}


# ==================== 上传 ====================

@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(..., description="待上传文件（支持多选）"),
    category_id: int | None = Form(None),
    is_standard: bool = Form(False),
    remark: str | None = Form(None),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_UPLOAD)),
    db: Session = Depends(get_db),
):
    """上传文件到文件库（支持多文件；单个失败不影响其余文件）"""
    if category_id and not tax.get_category(db, category_id):
        raise HTTPException(status_code=400, detail="目标分类不存在")

    created: list[dict] = []
    errors: list[dict] = []
    for upload in files:
        try:
            saved = svc.save_library_file(upload)
            record = svc.create_file(
                db, saved, name=upload.filename, category_id=category_id,
                is_standard=is_standard, remark=remark,
                operator=current_user.employee_id, operator_name=current_user.name,
            )
            created.append({"id": record.id, "name": record.name, "file_ext": record.file_ext})
        except HTTPException as exc:
            errors.append({"filename": upload.filename, "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001 单个文件异常不阻断其余上传
            logger.warning("文件库上传失败 filename=%s err=%s", upload.filename, exc, exc_info=True)
            errors.append({"filename": upload.filename, "detail": "上传失败，请重试"})

    if created:
        record_audit(
            db, "file_upload", current_user.employee_id,
            f"上传文件库文件 {len(created)} 个：{'、'.join(i['name'] for i in created[:5])}",
            target=str(created[0]["id"]),
            ip_address=get_client_ip(request) if request else None,
        )
    return {"created": created, "errors": errors, "total": len(created)}


# ==================== 详情与元数据 ====================

@router.get("/{file_id}")
def get_file_detail(
    file_id: int,
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """文件详情：元数据 + 标签 + 版本历史 + 引用它的标识清单"""
    detail = svc.get_file_detail(db, file_id)
    if not detail:
        raise HTTPException(status_code=404, detail="文件不存在")
    return detail


@router.patch("/{file_id}")
def update_file(
    file_id: int,
    payload: DesignFileUpdate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """更新文件元数据与标签（含「标准设计文件」标记）"""
    data = payload.model_dump(exclude_unset=True)
    tag_ids = data.pop("tag_ids", None)
    try:
        svc.update_file(db, file_id, data, tag_ids, current_user.employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_update", current_user.employee_id,
        f"更新文件库文件：{data.get('name') or file_id}", target=str(file_id),
        ip_address=get_client_ip(request) if request else None,
    )
    detail = svc.get_file_detail(db, file_id)
    return detail


# ==================== 下载与预览 ====================

@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """下载文件（以原始显示名作为下载文件名）"""
    record = _get_or_404(db, file_id)
    absolute_path = os.path.join(UPLOAD_ROOT, record.stored_path)
    if not os.path.exists(absolute_path):
        raise HTTPException(status_code=404, detail="文件已丢失，请联系管理员")
    filename = record.name
    if record.file_ext and not filename.lower().endswith(record.file_ext):
        filename = f"{filename}{record.file_ext}"
    return FileResponse(absolute_path, media_type="application/octet-stream", filename=filename)


@router.get("/{file_id}/preview")
def preview_file(
    file_id: int,
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """在线预览（图片 / PDF 内联展示；其余类型返回 400，请走下载）"""
    record = _get_or_404(db, file_id)
    preview_type = svc._preview_type(record.file_ext)
    if preview_type == "none":
        raise HTTPException(status_code=400, detail="该文件类型不支持在线预览，请下载后查看")
    absolute_path = os.path.join(UPLOAD_ROOT, record.stored_path)
    if not os.path.exists(absolute_path):
        raise HTTPException(status_code=404, detail="文件已丢失，请联系管理员")
    return FileResponse(
        absolute_path, media_type=_media_type(record.file_ext),
        headers={"Content-Disposition": "inline"},
    )


# ==================== 版本管理 ====================

@router.post("/{file_id}/versions")
async def upload_new_version(
    file_id: int,
    file: UploadFile = File(..., description="新版本文件"),
    note: str | None = Form(None, description="版本说明"),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """上传新版本：旧版本留档，当前版本指向新文件，并同步所有引用标识的路径"""
    _get_or_404(db, file_id)
    saved = svc.save_library_file(file)
    try:
        svc.add_version(
            db, file_id, saved, note=note,
            operator=current_user.employee_id, operator_name=current_user.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_version_add", current_user.employee_id,
        f"上传文件新版本：{note or '未填写说明'}", target=str(file_id),
        ip_address=get_client_ip(request) if request else None,
    )
    return svc.get_file_detail(db, file_id)


@router.post("/{file_id}/versions/{version_id}/restore")
def restore_file_version(
    file_id: int,
    version_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """回滚到指定版本（回滚动作本身也会记入版本历史）"""
    try:
        svc.restore_version(
            db, file_id, version_id,
            operator=current_user.employee_id, operator_name=current_user.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_version_restore", current_user.employee_id,
        f"回滚文件版本：version_id={version_id}", target=str(file_id),
        ip_address=get_client_ip(request) if request else None,
    )
    return svc.get_file_detail(db, file_id)


# ==================== 删除 / 恢复（含批量） ====================

@router.delete("/{file_id}")
def delete_file(
    file_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """移入回收站（软删）。被标识引用的文件受引用保护，无法删除。"""
    result = svc.soft_delete_files(db, [file_id], current_user.employee_id)
    if result["blocked"]:
        blocked = result["blocked"][0]
        raise HTTPException(
            status_code=400,
            detail=f"该文件正被 {blocked['ref_count']} 条标识引用，无法删除；请先在标识中解除引用",
        )
    record_audit(
        db, "file_delete", current_user.employee_id,
        "移入回收站", target=str(file_id),
        ip_address=get_client_ip(request) if request else None,
    )
    return {"ok": True, "deleted": result["deleted"]}


@router.post("/{file_id}/restore")
def restore_file(
    file_id: int,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """从回收站恢复"""
    restored = svc.restore_files(db, [file_id])
    if not restored:
        raise HTTPException(status_code=400, detail="文件不在回收站中")
    return {"ok": True, "restored": restored}


@router.delete("/{file_id}/purge")
def purge_file(
    file_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """彻底删除（清理物理文件与历史版本）。被标识引用时拒绝。"""
    result = svc.purge_files(db, [file_id])
    if result["blocked"]:
        blocked = result["blocked"][0]
        raise HTTPException(
            status_code=400,
            detail=f"该文件正被 {blocked['ref_count']} 条标识引用，无法彻底删除",
        )
    record_audit(
        db, "file_purge", current_user.employee_id,
        "彻底删除文件（含物理文件）", target=str(file_id),
        ip_address=get_client_ip(request) if request else None,
    )
    return {"ok": True, "purged": result["purged"]}


# ==================== 批量操作 ====================

@router.post("/batch/category")
def batch_category(
    payload: BatchCategoryRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """批量移动分类"""
    try:
        count = svc.batch_set_category(
            db, payload.ids, payload.category_id, current_user.employee_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "updated": count}


@router.post("/batch/standard")
def batch_standard(
    payload: BatchStandardRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """批量标记 / 取消标准设计文件"""
    count = svc.batch_set_standard(
        db, payload.ids, payload.is_standard, current_user.employee_id,
    )
    return {"ok": True, "updated": count}


@router.post("/batch/tags")
def batch_tags(
    payload: BatchTagsRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_EDIT)),
    db: Session = Depends(get_db),
):
    """批量打标签 / 移除标签"""
    added = tax.add_file_tags(db, payload.ids, payload.add_tag_ids)
    removed = tax.remove_file_tags(db, payload.ids, payload.remove_tag_ids)
    db.commit()
    return {"ok": True, "added": added, "removed": removed}


@router.post("/batch/delete")
def batch_delete(
    payload: BatchIdsRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """批量移入回收站（被引用的文件会被跳过并返回明细）"""
    result = svc.soft_delete_files(db, payload.ids, current_user.employee_id)
    return {"ok": True, "deleted": result["deleted"], "blocked": result["blocked"]}


@router.post("/batch/restore")
def batch_restore(
    payload: BatchIdsRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """批量从回收站恢复"""
    return {"ok": True, "restored": svc.restore_files(db, payload.ids)}


@router.post("/batch/purge")
def batch_purge(
    payload: BatchIdsRequest,
    current_user: User = Depends(require_any_permission(PERM_FILE_DELETE)),
    db: Session = Depends(get_db),
):
    """批量彻底删除（被引用的文件会被跳过并返回明细）"""
    result = svc.purge_files(db, payload.ids)
    return {"ok": True, "purged": result["purged"], "blocked": result["blocked"]}


@router.post("/batch/download")
def batch_download(
    payload: BatchIdsRequest,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_FILE_VIEW)),
    db: Session = Depends(get_db),
):
    """批量打包下载（zip：按分类建目录、以「使用名」命名）。

    [新增 2026-09-17] 需求（方案 A）：文件管理页勾选文件一键打包下载。
    「标识导出」的附件包是按**标识**维度打包的（筛选 signages.category），
    无法导出未被任何标识引用的文件库文件，故在文件库侧补上该能力。

    响应头 X-Packed-Count / X-Skipped-Count 供前端提示打包结果
    （skipped = 记录存在但磁盘文件缺失，已在 zip 中跳过）。
    """
    try:
        buffer, stats = svc.build_files_zip(db, payload.ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db, "file_batch_download", current_user.employee_id,
        f"打包下载文件 {stats['packed']} 个"
        + (f"，跳过服务器缺失 {len(stats['skipped'])} 个" if stats["skipped"] else ""),
        target=",".join(str(i) for i in payload.ids[:20]),
        ip_address=get_client_ip(request) if request else None,
    )
    filename = f"文件库_{beijing_now().strftime('%Y%m%d_%H%M%S')}.zip"
    headers = {
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
        "X-Packed-Count": str(stats["packed"]),
        "X-Skipped-Count": str(len(stats["skipped"])),
    }
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)
