# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库核心服务：设计文件的上传、检索、元数据、版本、回收站与引用保护。

[新增 2026-09-17] 需求：标识管理下新增「文件管理」，集中管理所有已上传的设计文件；
内置「标准设计文件」标记，被标记后可在标识表单中搜索选择复用。

关键设计：
- **引用共享**：标识通过 signages.design_file_id 引用文件（多标识可复用同一份标准文件）；
  signages.design_photo 保存路径快照，保证导出/详情等既有链路零改动；
- **引用保护**：文件被标识引用时不允许删除（软删与彻底删除都拦截），
  避免一条标识的设计文件被误删；
- **版本管理**：新版本上传后 stored_path 指向新文件，并**同步更新所有引用标识的
  design_photo**，保证引用者始终指向当前版本；旧文件留档在 design_file_versions；
- **回收站**：删除为软删（is_deleted），可恢复；彻底删除时才清理物理文件（含缩略图）。
"""

import hashlib
import io
import logging
import os
import uuid
import zipfile

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.design_file import (
    DesignFile, DesignFileTag, DesignFileVersion,
)
from app.models.signage import Signage
from app.services import file_taxonomy_service as tax
from app.services.upload_service import (
    MAX_FILE_SIZE, UPLOAD_ROOT, delete_file, detect_image_format,
    generate_thumbnail, get_thumbnail_path,
)
from app.utils import utc_now

logger = logging.getLogger("design_file")

# 文件库上传子目录（uploads/files/）
LIBRARY_SUBDIR = "files"

# 允许上传的文件类型：
#   图片（可预览缩略图）/ AI 与 PDF（与标识设计文件口径一致）/ 设计源文件与打包文件（仅下载）
# 说明：不放开 .svg/.html 等可内联执行的类型，避免 /uploads 静态服务带来的 XSS 风险。
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FILE_LIBRARY_EXTENSIONS = IMAGE_EXTENSIONS | {".ai", ".pdf", ".psd", ".cdr", ".eps", ".zip"}

# 各类文件的魔数特征（用于内容校验，避免改扩展名绕过）
_MAGIC_CHECKS = {
    ".pdf": [b"%PDF-"],
    ".ai": [b"%PDF-", b"%!PS"],   # 新版 AI 实为 PDF 容器，旧版为 PostScript
    ".eps": [b"%!PS", b"\xc5\xd0\xd3\xc6"],  # 含 EPS 二进制头
    ".psd": [b"8BPS"],
    ".zip": [b"PK\x03\x04"],
}


def _preview_type(ext: str | None) -> str:
    """预览能力：image（图片直显）/ pdf（浏览器内预览）/ none（仅下载）"""
    if not ext:
        return "none"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    return "none"


def _absolute_path(stored_path: str) -> str:
    return os.path.join(UPLOAD_ROOT, stored_path)


def _thumbnail_rel(stored_path: str) -> str | None:
    """图片类型：磁盘存在 thumb_ 派生文件时返回其相对路径（前端展示缩略图用）"""
    if not stored_path:
        return None
    thumb_rel = get_thumbnail_path(stored_path)
    return thumb_rel if os.path.exists(_absolute_path(thumb_rel)) else None


def _read_head(content: bytes, size: int = 16) -> bytes:
    return content[:size]


def validate_library_file(file: UploadFile, content: bytes) -> str:
    """校验文件库上传文件，返回规范化扩展名（失败抛 400）。"""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in FILE_LIBRARY_EXTENSIONS:
        allowed = "/".join(sorted(e.lstrip(".").upper() for e in FILE_LIBRARY_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，仅支持 {allowed}")
    if len(content) > MAX_FILE_SIZE:
        limit_mb = MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件大小超过限制，最大允许 {limit_mb}MB")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    head = _read_head(content)
    if ext in IMAGE_EXTENSIONS:
        real_format = detect_image_format(head)
        if real_format not in ("JPEG", "PNG", "WebP"):
            raise HTTPException(status_code=400, detail="图片格式校验失败（仅支持 JPG/PNG/WebP）")
    else:
        magics = _MAGIC_CHECKS.get(ext)
        if magics and not any(content.startswith(magic) for magic in magics):
            raise HTTPException(status_code=400, detail=f"文件内容与扩展名（{ext}）不符，已拒绝上传")
    return ext


def save_library_file(file: UploadFile) -> dict:
    """校验并落盘文件库文件，返回落盘信息（stored_path / size / ext / mime / content_hash）。"""
    content = file.file.read()
    ext = validate_library_file(file, content)

    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{timestamp}_{unique_id}{ext}"
    save_dir = os.path.join(UPLOAD_ROOT, LIBRARY_SUBDIR)
    os.makedirs(save_dir, exist_ok=True)
    absolute_path = os.path.join(save_dir, filename)
    with open(absolute_path, "wb") as fh:
        fh.write(content)

    # 路径穿越防护：落盘后再次确认文件位于上传根目录内
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_abs = os.path.realpath(absolute_path)
    if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="非法文件路径")

    stored_path = f"{LIBRARY_SUBDIR}/{filename}"
    # 图片生成缩略图（供列表卡片与详情预览使用，失败不影响上传）
    if ext in IMAGE_EXTENSIONS:
        generate_thumbnail(absolute_path)

    return {
        "stored_path": stored_path,
        "file_size": len(content),
        "file_ext": ext,
        "mime_type": file.content_type or None,
        "content_hash": hashlib.sha256(content).hexdigest(),
    }


# ==================== 序列化 ====================

def _reference_counts(db: Session, file_ids: list[int]) -> dict[int, int]:
    """批量统计每个文件被多少条标识引用（引用保护的判定依据）"""
    if not file_ids:
        return {}
    rows = (
        db.query(Signage.design_file_id, func.count(Signage.id))
        .filter(Signage.design_file_id.in_(file_ids))
        .group_by(Signage.design_file_id)
        .all()
    )
    return {int(fid): int(count) for fid, count in rows if fid is not None}


def _serialize(db: Session, record: DesignFile, ref_counts: dict[int, int] | None = None,
               version_counts: dict[int, int] | None = None) -> dict:
    """文件记录 → 列表/详情输出（含标签、分类名、引用数、预览信息）"""
    tags = [
        {
            "id": link.tag.id, "name": link.tag.name, "group_name": link.tag.group_name,
            "color": link.tag.color, "created_at": link.tag.created_at, "file_count": 0,
        }
        for link in record.tags if link.tag is not None
    ]
    ref_count = (ref_counts or {}).get(record.id, 0)
    return {
        "id": record.id,
        "name": record.name,
        "stored_path": record.stored_path,
        "file_ext": record.file_ext,
        "file_size": record.file_size,
        "mime_type": record.mime_type,
        "is_standard": bool(record.is_standard),
        "category_id": record.category_id,
        "category_name": record.category.name if record.category else None,
        "tags": tags,
        "remark": record.remark,
        "uploader_id": record.uploader_id,
        "uploader_name": record.uploader_name,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "current_version": (version_counts or {}).get(record.id, 1),
        "version_count": (version_counts or {}).get(record.id, 1),
        "ref_count": ref_count,
        "is_deleted": bool(record.is_deleted),
        "deleted_at": record.deleted_at,
        "deleted_by": record.deleted_by,
        "preview_type": _preview_type(record.file_ext),
        "thumbnail_path": _thumbnail_rel(record.stored_path) if _preview_type(record.file_ext) == "image" else None,
    }


def _version_counts(db: Session, file_ids: list[int]) -> dict[int, int]:
    if not file_ids:
        return {}
    rows = (
        db.query(DesignFileVersion.file_id, func.max(DesignFileVersion.version))
        .filter(DesignFileVersion.file_id.in_(file_ids))
        .group_by(DesignFileVersion.file_id)
        .all()
    )
    return {int(fid): int(ver or 1) for fid, ver in rows if fid is not None}


# ==================== 查询 ====================

def get_file(db: Session, file_id: int) -> DesignFile | None:
    return db.query(DesignFile).filter(DesignFile.id == file_id).first()


def list_files(db: Session, page: int = 1, page_size: int = 20, keyword: str | None = None,
               category_id: int | None = None, include_subcategory: bool = True,
               tag_ids: list[int] | None = None, start_date: str | None = None,
               end_date: str | None = None, is_standard: bool | None = None,
               only_deleted: bool = False, uncategorized: bool = False) -> tuple[list[dict], int]:
    """分页检索文件（关键词 / 分类 / 标签 / 上传时间 / 标准标记 / 回收站）。

    - keyword 同时匹配「显示名」与「引用该文件的标识编码/名称」，便于按标识反查设计文件；
    - tag_ids 为「同时包含全部标签」（AND），用于逐层收窄；
    - category_id 默认含子分类（树形分类按节点筛选时符合直觉）。
    """
    query = db.query(DesignFile).options(
        # 预加载分类与标签，避免列表逐行 N+1
        joinedload(DesignFile.category),
        selectinload(DesignFile.tags).joinedload(DesignFileTag.tag),
    )
    query = query.filter(DesignFile.is_deleted == only_deleted)

    if keyword:
        keyword_like = f"%{keyword.strip()}%"
        referenced_file_ids = db.query(Signage.design_file_id).filter(
            Signage.design_file_id.isnot(None),
            or_(Signage.code.like(keyword_like), Signage.name.like(keyword_like)),
        ).subquery()
        query = query.filter(
            or_(
                DesignFile.name.like(keyword_like),
                DesignFile.remark.like(keyword_like),
                DesignFile.id.in_(referenced_file_ids),
            )
        )

    if uncategorized:
        query = query.filter(DesignFile.category_id.is_(None))
    elif category_id:
        # [调整 2026-09-17] 分类已统一为标识分类（扁平结构，无子分类概念），直接精确匹配
        query = query.filter(DesignFile.category_id == category_id)

    for tag_id in (tag_ids or []):
        # 多标签为 AND 语义：逐个标签收窄「文件必须包含该标签」，用于多维度精确筛选
        subquery = db.query(DesignFileTag.file_id).filter(DesignFileTag.tag_id == tag_id)
        query = query.filter(DesignFile.id.in_(subquery))

    if is_standard is not None:
        query = query.filter(DesignFile.is_standard == is_standard)

    if start_date:
        query = query.filter(DesignFile.created_at >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(DesignFile.created_at <= f"{end_date} 23:59:59")

    total = query.count()
    rows = (
        query.order_by(DesignFile.created_at.desc(), DesignFile.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    file_ids = [r.id for r in rows]
    ref_counts = _reference_counts(db, file_ids)
    version_counts = _version_counts(db, file_ids)
    return [_serialize(db, r, ref_counts, version_counts) for r in rows], total


def get_file_detail(db: Session, file_id: int) -> dict | None:
    """文件详情（含版本列表与引用它的标识清单）"""
    record = get_file(db, file_id)
    if not record:
        return None
    ref_counts = _reference_counts(db, [file_id])
    version_counts = _version_counts(db, [file_id])
    detail = _serialize(db, record, ref_counts, version_counts)
    detail["versions"] = [
        {
            "id": v.id, "version": v.version, "stored_path": v.stored_path,
            "file_ext": v.file_ext, "file_size": v.file_size, "note": v.note,
            "uploaded_by": v.uploaded_by, "uploaded_by_name": v.uploaded_by_name,
            "created_at": v.created_at,
        }
        for v in sorted(record.versions, key=lambda item: item.version, reverse=True)
    ]
    detail["references"] = get_references(db, file_id)
    return detail


def get_references(db: Session, file_id: int) -> list[dict]:
    """引用该文件（作为设计文件）的标识清单 —— 引用保护与详情展示共用"""
    rows = db.query(Signage).filter(Signage.design_file_id == file_id).all()
    return [
        {"signage_id": s.id, "code": s.code, "name": s.name, "status": s.status}
        for s in rows
    ]


def list_standard_options(db: Session, keyword: str | None = None,
                          category_id: int | None = None, category_name: str | None = None,
                          limit: int = 200) -> list[dict]:
    """标准设计文件选项（标识表单「从标准库选择」用）。

    [新增 2026-09-17] 新增 category_name：标识表单传入**自身分类名**，
    只返回同分类的标准设计文件，从源头避免跨类别引用；
    分类名在标识分类表中不存在时返回空列表（宁可不给选，也不放开跨类别引用）。
    """
    query = db.query(DesignFile).options(
        joinedload(DesignFile.category),
        selectinload(DesignFile.tags).joinedload(DesignFileTag.tag),
    ).filter(
        DesignFile.is_deleted == False,  # noqa: E712
        DesignFile.is_standard == True,  # noqa: E712
    )
    if keyword:
        keyword_like = f"%{keyword.strip()}%"
        query = query.filter(DesignFile.name.like(keyword_like))
    if category_id:
        # [调整 2026-09-17] 同 list_files：分类为扁平结构，精确匹配
        query = query.filter(DesignFile.category_id == category_id)
    elif category_name:
        # [新增 2026-09-17] 按分类名筛选（标识表单的同分类约束）：
        # 名称解析不到时用 -1 过滤，结果为空 —— 保守优先，不放开跨类别引用
        matched = tax.get_category_by_name(db, category_name)
        query = query.filter(DesignFile.category_id == (matched.id if matched else -1))
    rows = query.order_by(DesignFile.created_at.desc()).limit(limit).all()
    ref_counts = _reference_counts(db, [r.id for r in rows])
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "name": r.name,
            "stored_path": r.stored_path,
            "file_ext": r.file_ext,
            "category_name": r.category.name if r.category else None,
            "tags": [
                {"id": link.tag.id, "name": link.tag.name, "group_name": link.tag.group_name,
                 "color": link.tag.color, "file_count": 0, "created_at": None}
                for link in r.tags if link.tag is not None
            ],
            "preview_type": _preview_type(r.file_ext),
            "thumbnail_path": _thumbnail_rel(r.stored_path) if _preview_type(r.file_ext) == "image" else None,
            "ref_count": ref_counts.get(r.id, 0),
        })
    return result


# ==================== 写入 ====================

def is_path_shared(db: Session, stored_path: str, exclude_signage_id: int | None = None) -> bool:
    """[新增 2026-09-17] 该路径是否仍被其它标识引用（共享引用保护）。

    标识设计文件支持引用共享（标准设计文件被多条标识复用），
    因此在「替换设计文件」或「删除标识」时，必须先确认没有其它标识仍在引用该路径，
    否则会误删他人正在使用的文件。
    """
    if not stored_path:
        return False
    query = db.query(Signage.id).filter(Signage.design_photo == stored_path)
    if exclude_signage_id:
        query = query.filter(Signage.id != exclude_signage_id)
    return db.query(query.exists()).scalar() or False


def register_uploaded_design_file(db: Session, stored_path: str, signage,
                                  operator: str | None = None,
                                  operator_name: str | None = None) -> DesignFile:
    """[新增 2026-09-17] 把标识页上传的设计文件登记到文件库（路径已存在则复用）。

    需求要求文件库「集中管理所有已上传的设计文件」，因此标识表单上传设计文件时
    同步登记一条文件库记录（未分类、非标准），用户可在文件库中改名、归类、
    打标签，或标记为「标准设计文件」供其它标识复用。
    """
    existing = db.query(DesignFile).filter(DesignFile.stored_path == stored_path).first()
    if existing:
        return existing
    ext = os.path.splitext(stored_path)[1].lower() or None
    absolute = _absolute_path(stored_path)
    try:
        size = os.path.getsize(absolute)
    except OSError:
        size = None
    code = getattr(signage, "code", None)
    name = getattr(signage, "name", None)
    display = f"{code}-{name}-设计文件" if code and name else (f"{code}-设计文件" if code else "设计文件")
    record = DesignFile(
        name=display[:200], stored_path=stored_path, file_ext=ext, file_size=size,
        is_standard=False, category_id=None, remark="由标识设计文件上传自动登记",
        uploader_id=operator, uploader_name=operator_name, updated_by=operator,
    )
    db.add(record)
    db.flush()
    db.add(DesignFileVersion(
        file_id=record.id, version=1, stored_path=stored_path, file_ext=ext, file_size=size,
        note="标识设计文件上传", uploaded_by=operator, uploaded_by_name=operator_name,
    ))
    return record


def create_file(db: Session, saved: dict, name: str | None, category_id: int | None,
                is_standard: bool, remark: str | None, operator: str | None,
                operator_name: str | None) -> DesignFile:
    """新建文件记录（含版本 1 留档）"""
    display_name = (name or "").strip() or os.path.basename(saved["stored_path"])
    record = DesignFile(
        name=display_name[:200],
        stored_path=saved["stored_path"],
        file_ext=saved["file_ext"],
        file_size=saved["file_size"],
        mime_type=saved["mime_type"],
        content_hash=saved["content_hash"],
        is_standard=bool(is_standard),
        category_id=category_id,
        remark=remark,
        uploader_id=operator,
        uploader_name=operator_name,
        updated_by=operator,
    )
    db.add(record)
    db.flush()
    # 版本 1：初始版本留档，保证「版本历史」从首版即完整
    db.add(DesignFileVersion(
        file_id=record.id, version=1, stored_path=saved["stored_path"],
        file_ext=saved["file_ext"], file_size=saved["file_size"],
        note="初始版本", uploaded_by=operator, uploaded_by_name=operator_name,
    ))
    db.commit()
    db.refresh(record)
    return record


def update_file(db: Session, file_id: int, payload: dict, tag_ids: list[int] | None,
                operator: str | None) -> DesignFile:
    """更新文件元数据（名称 / 分类 / 标准标记 / 备注）与标签"""
    record = get_file(db, file_id)
    if not record:
        raise ValueError("文件不存在")
    if payload.get("name"):
        record.name = payload["name"].strip()[:200]
    if "category_id" in payload:
        category_id = payload["category_id"] or None
        if category_id and not tax.get_category(db, category_id):
            raise ValueError("目标分类不存在")
        record.category_id = category_id
    if "is_standard" in payload and payload["is_standard"] is not None:
        record.is_standard = bool(payload["is_standard"])
    if "remark" in payload:
        record.remark = payload["remark"]
    record.updated_by = operator
    if tag_ids is not None:
        tax.set_file_tags(db, file_id, tag_ids)
    db.commit()
    db.refresh(record)
    return record


def add_version(db: Session, file_id: int, saved: dict, note: str | None,
                operator: str | None, operator_name: str | None) -> DesignFile:
    """上传新版本：当前文件留档，stored_path 指向新文件，并同步更新所有引用标识的路径。

    [引用一致性] 标识的 design_photo 是路径快照，因此新版本落库后必须把
    所有引用该文件的标识的 design_photo 一并更新，避免引用者仍指向旧文件。
    """
    record = get_file(db, file_id)
    if not record:
        raise ValueError("文件不存在")
    max_version = db.query(func.max(DesignFileVersion.version)).filter(
        DesignFileVersion.file_id == file_id,
    ).scalar() or 0

    record.stored_path = saved["stored_path"]
    record.file_ext = saved["file_ext"]
    record.file_size = saved["file_size"]
    record.mime_type = saved["mime_type"]
    record.content_hash = saved["content_hash"]
    record.updated_by = operator

    db.add(DesignFileVersion(
        file_id=file_id, version=max_version + 1, stored_path=saved["stored_path"],
        file_ext=saved["file_ext"], file_size=saved["file_size"],
        note=note, uploaded_by=operator, uploaded_by_name=operator_name,
    ))
    # 同步引用者路径
    db.query(Signage).filter(Signage.design_file_id == file_id).update(
        {"design_photo": saved["stored_path"]}, synchronize_session=False,
    )
    db.commit()
    db.refresh(record)
    return record


def restore_version(db: Session, file_id: int, version_id: int,
                    operator: str | None, operator_name: str | None) -> DesignFile:
    """回滚到指定版本（把该版本文件重新设为当前版本，并在版本历史中留痕）"""
    record = get_file(db, file_id)
    if not record:
        raise ValueError("文件不存在")
    version = db.query(DesignFileVersion).filter(
        DesignFileVersion.id == version_id, DesignFileVersion.file_id == file_id,
    ).first()
    if not version:
        raise ValueError("版本记录不存在")
    max_version = db.query(func.max(DesignFileVersion.version)).filter(
        DesignFileVersion.file_id == file_id,
    ).scalar() or 0

    record.stored_path = version.stored_path
    record.file_ext = version.file_ext
    record.file_size = version.file_size
    record.updated_by = operator
    db.add(DesignFileVersion(
        file_id=file_id, version=max_version + 1, stored_path=version.stored_path,
        file_ext=version.file_ext, file_size=version.file_size,
        note=f"回滚到版本 {version.version}", uploaded_by=operator, uploaded_by_name=operator_name,
    ))
    db.query(Signage).filter(Signage.design_file_id == file_id).update(
        {"design_photo": version.stored_path}, synchronize_session=False,
    )
    db.commit()
    db.refresh(record)
    return record


# ==================== 回收站 ====================

def soft_delete_files(db: Session, file_ids: list[int], operator: str | None) -> dict:
    """移入回收站（软删）。被标识引用的文件受引用保护，不允许删除。"""
    blocked: list[dict] = []
    deleted: list[int] = []
    ref_counts = _reference_counts(db, file_ids)
    for file_id in file_ids:
        record = get_file(db, file_id)
        if not record or record.is_deleted:
            continue
        ref_count = ref_counts.get(file_id, 0)
        if ref_count:
            blocked.append({"id": file_id, "name": record.name, "ref_count": ref_count})
            continue
        record.is_deleted = True
        record.deleted_at = utc_now()
        record.deleted_by = operator
        deleted.append(file_id)
    if deleted:
        db.commit()
    return {"deleted": len(deleted), "blocked": blocked}


def restore_files(db: Session, file_ids: list[int]) -> int:
    """从回收站恢复"""
    restored = 0
    for file_id in file_ids:
        record = get_file(db, file_id)
        if not record or not record.is_deleted:
            continue
        record.is_deleted = False
        record.deleted_at = None
        record.deleted_by = None
        restored += 1
    if restored:
        db.commit()
    return restored


def purge_files(db: Session, file_ids: list[int]) -> dict:
    """彻底删除（清理物理文件与版本留档）。被引用或被标识使用时拒绝。"""
    blocked: list[dict] = []
    purged: list[int] = []
    ref_counts = _reference_counts(db, file_ids)
    for file_id in file_ids:
        record = get_file(db, file_id)
        if not record:
            continue
        ref_count = ref_counts.get(file_id, 0)
        if ref_count:
            blocked.append({"id": file_id, "name": record.name, "ref_count": ref_count})
            continue
        # 清理物理文件：当前版本 + 全部历史版本（delete_file 会连带 thumb_/orig_）
        paths = {record.stored_path}
        for version in record.versions:
            paths.add(version.stored_path)
        for path in paths:
            if path:
                try:
                    delete_file(path)
                except Exception as exc:  # 物理文件清理失败不应阻断记录删除
                    logger.warning("文件库物理文件清理失败 path=%s err=%s", path, exc, exc_info=True)
        db.delete(record)
        purged.append(file_id)
    if purged:
        db.commit()
    return {"purged": len(purged), "blocked": blocked}


# ==================== 批量操作 ====================

def batch_set_category(db: Session, file_ids: list[int], category_id: int | None,
                       operator: str | None) -> int:
    if category_id and not tax.get_category(db, category_id):
        raise ValueError("目标分类不存在")
    count = db.query(DesignFile).filter(DesignFile.id.in_(file_ids)).update(
        {"category_id": category_id, "updated_by": operator}, synchronize_session=False,
    )
    db.commit()
    return int(count)


# ==================== 批量打包下载 ====================

# 上限：内存打包，避免一次勾选过多文件占用过大内存
DOWNLOAD_MAX_FILES = 100
DOWNLOAD_MAX_TOTAL_MB = 500


def _safe_zip_name(name: str, fallback: str) -> str:
    """把任意名称转成安全的 zip 路径片段。

    去掉路径分隔符与上跳（防 zip 路径穿越）、Windows 非法字符与首尾点/空格，
    避免解压时报错或写出到目标目录之外。
    """
    text = (name or "").strip() or fallback
    for ch in ("\\", "/", "..", ":", "*", "?", '"', "<", ">", "|"):
        text = text.replace(ch, "_")
    return text.strip(" .") or fallback


def _zip_entry_name(record: DesignFile) -> str:
    """zip 内文件名：优先用文件管理中的「使用名」，未带扩展名时补上。"""
    stem = _safe_zip_name(record.name, f"file-{record.id}")
    ext = (record.file_ext or os.path.splitext(record.stored_path or "")[1] or "").lower()
    if ext and not stem.lower().endswith(ext):
        stem = f"{stem}{ext}"
    return stem


def _unique_zip_name(candidate: str, used: set) -> str:
    """同一目录内保证条目名唯一：重名追加 _2、_3…（如两个文件都叫「三折页」）。"""
    if candidate not in used:
        used.add(candidate)
        return candidate
    stem, dot, ext = candidate.rpartition(".")
    index = 2
    while True:
        alt = f"{stem}_{index}.{ext}" if dot else f"{candidate}_{index}"
        if alt not in used:
            used.add(alt)
            return alt
        index += 1


def build_files_zip(db: Session, file_ids: list[int]) -> tuple:
    """把选中的文件打包成 zip（按分类建目录、以「使用名」命名）。

    [新增 2026-09-17] 需求（方案 A）：文件管理页支持勾选文件一键打包下载。
    此前只能逐个下载，而「标识导出」的附件包是按**标识**维度打包的
    （筛选条件为 signages.category），无法导出未被任何标识引用的文件库文件。

    规则：
    - 目录：以文件所属**标识分类**名建一级目录，未分类归入「未分类」；
    - 文件名：使用文件管理中的**使用名**（DesignFile.name），
      未带扩展名时补 file_ext，保证下载后可直接打开；
    - 重名：同目录内自动追加 _2、_3…；
    - 回收站中的文件不参与打包；磁盘缺失的文件跳过并在统计中返回明细；
    - 上限：一次最多 100 个、合计不超过 500MB（内存打包，防止占用过大）。

    返回 (zip 字节流已 seek(0), {"packed": n, "skipped": [...]})。
    """
    records = (
        db.query(DesignFile)
        .options(joinedload(DesignFile.category))
        .filter(DesignFile.id.in_(file_ids), DesignFile.is_deleted == False)  # noqa: E712
        .all()
    )
    if not records:
        raise ValueError("没有可打包的文件（可能已被删除或移入回收站）")

    if len(records) > DOWNLOAD_MAX_FILES:
        raise ValueError(f"一次最多打包 {DOWNLOAD_MAX_FILES} 个文件，请分批下载")
    total_bytes = sum(int(r.file_size or 0) for r in records)
    if total_bytes > DOWNLOAD_MAX_TOTAL_MB * 1024 * 1024:
        raise ValueError(
            f"所选文件合计约 {total_bytes / 1024 / 1024:.0f}MB，超过 "
            f"{DOWNLOAD_MAX_TOTAL_MB}MB 上限，请分批下载"
        )

    buffer = io.BytesIO()
    stats = {"packed": 0, "skipped": []}
    used_names: dict = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            absolute = os.path.join(UPLOAD_ROOT, record.stored_path or "")
            if not record.stored_path or not os.path.isfile(absolute):
                stats["skipped"].append({
                    "id": record.id, "name": record.name, "reason": "文件在服务器上不存在",
                })
                continue
            folder = _safe_zip_name(
                record.category.name if record.category else "", "未分类",
            )
            used = used_names.setdefault(folder, set())
            entry = _unique_zip_name(_zip_entry_name(record), used)
            archive.write(absolute, f"{folder}/{entry}")
            stats["packed"] += 1
    buffer.seek(0)
    return buffer, stats


def batch_set_standard(db: Session, file_ids: list[int], is_standard: bool,
                       operator: str | None) -> int:
    count = db.query(DesignFile).filter(DesignFile.id.in_(file_ids)).update(
        {"is_standard": bool(is_standard), "updated_by": operator}, synchronize_session=False,
    )
    db.commit()
    return int(count)


def count_summary(db: Session) -> dict:
    """文件库概览：文件数 / 标准文件数 / 回收站数 / 占用空间（供页面顶部统计）"""
    base = db.query(DesignFile)
    total = base.filter(DesignFile.is_deleted == False).count()  # noqa: E712
    standard = base.filter(DesignFile.is_deleted == False, DesignFile.is_standard == True).count()  # noqa: E712
    trashed = base.filter(DesignFile.is_deleted == True).count()  # noqa: E712
    size = db.query(func.coalesce(func.sum(DesignFile.file_size), 0)).filter(
        DesignFile.is_deleted == False,  # noqa: E712
    ).scalar() or 0
    uncategorized = base.filter(
        DesignFile.is_deleted == False, DesignFile.category_id.is_(None),  # noqa: E712
    ).count()
    return {
        "total": int(total), "standard": int(standard), "trashed": int(trashed),
        "uncategorized": int(uncategorized), "total_size": int(size),
    }
