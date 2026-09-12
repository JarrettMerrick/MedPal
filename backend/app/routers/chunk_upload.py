# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import os
import uuid
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from PIL import Image

from app.database import get_db
from app.dependencies import get_current_user, has_permission, PERM_CARD_UPLOAD, PERM_STAFF_EDIT
from app.models.user import User
from app.models.upload_session import UploadSession
from app.models.staff_card import StaffCard
from app.services.upload_service import (
    UPLOAD_ROOT, MAX_FILE_SIZE, ensure_upload_dirs, delete_file, generate_thumbnail,
)
from app.services.notification_service import create_notification
from app.services.staff_service import get_staff, update_staff
from app.schemas.staff import StaffUpdate
from app.utils import utc_now

router = APIRouter(prefix="/api/upload", tags=["分片上传"])

# 分片临时目录
CHUNKS_DIR = os.path.join(UPLOAD_ROOT, "_chunks")
# 每片 2MB
CHUNK_SIZE = 2 * 1024 * 1024

# [改进/1.0.9] 单用户最大并发上传会话数，防止恶意或误操作创建大量孤儿目录
MAX_CONCURRENT_UPLOADS_PER_USER = 3

# [改进/1.0.9] _chunks 目录总大小上限（500MB），超过后拒绝创建新会话
MAX_CHUNKS_TOTAL_SIZE = 500 * 1024 * 1024


def _check_chunks_disk_quota() -> None:
    """检查 _chunks 目录总大小是否超限，超限则拒绝新上传会话。

    防止大量未完成的分片上传占满磁盘空间。
    """
    if not os.path.isdir(CHUNKS_DIR):
        return
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(CHUNKS_DIR):
        for fn in filenames:
            try:
                total_size += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    if total_size > MAX_CHUNKS_TOTAL_SIZE:
        raise HTTPException(
            status_code=507,
            detail=f"服务器临时存储空间不足（当前 {total_size / 1024 / 1024:.0f}MB），请稍后重试或联系管理员清理"
        )


def _check_upload_permission(current_user: User, entity_type: str, entity_id: str, db: Session) -> None:
    """校验当前用户是否有权为指定实体上传图片（权限 + 数据范围）。

    [改进/F2] 原实现仅在 complete_upload 阶段校验权限，导致 init_upload 阶段
    任何登录用户都能为任意 entity_id 建会话/写 _chunks 目录（磁盘耗尽风险）。
    现将校验抽取为公共函数，init 与 complete 均调用，无权限直接 403。
    无权限或超出数据范围时抛 HTTPException。
    """
    # --- 权限验证（基于权限表）---
    if entity_type in ("specialty", "equipment"):
        from app.dependencies import PERM_DEPT_EDIT, has_permission as has_perm
        can_upload = has_perm(current_user, PERM_DEPT_EDIT)
    else:
        can_upload = (
            has_permission(current_user, PERM_CARD_UPLOAD) or
            entity_id == current_user.employee_id or
            has_permission(current_user, PERM_STAFF_EDIT)
        )
    if not can_upload:
        raise HTTPException(403, "无权上传该类型的图片")

    # --- 数据范围校验（防止越权上传/覆盖他人科室/人员图片）---
    if entity_type in ("specialty", "equipment"):
        from app.dependencies import has_department_access
        from app.models.department import Department, DepartmentSpecialty, DepartmentEquipment
        if entity_type == "specialty":
            ent = db.query(DepartmentSpecialty).filter(DepartmentSpecialty.id == entity_id).first()
        else:
            ent = db.query(DepartmentEquipment).filter(DepartmentEquipment.id == entity_id).first()
        target_dept_id = ent.department_id if ent else None
        if target_dept_id is not None:
            dept = db.query(Department).filter(Department.id == target_dept_id).first()
            if dept and not has_department_access(current_user, dept.name, db):
                raise HTTPException(403, "无权上传该科室的图片")
    else:
        # 人员照片/卡片：非本人需 staff.edit 且在数据范围内
        if entity_id != current_user.employee_id:
            from app.dependencies import can_access_staff
            entity = get_staff(db, entity_id)
            if not entity or not can_access_staff(current_user, entity.work_type, entity.department, db):
                raise HTTPException(403, "无权上传该人员的图片")


@router.post("/init")
def init_upload(
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    photo_type: str = Form(...),
    file_name: str = Form(...),
    file_size: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """初始化分片上传会话"""
    if entity_type not in ("doctor", "nurse", "technician", "admin", "specialty", "equipment"):
        raise HTTPException(400, "实体类型必须是 doctor / nurse / technician / admin / specialty / equipment")
    if photo_type not in ("front", "side", "card", "image"):
        raise HTTPException(400, "照片类型必须是 front / side / card / image")
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            400, f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)"
        )
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "仅支持 JPG/PNG/WebP 格式")

    # [改进/F2] 建会话前即校验权限与数据范围，无权者无法创建 _chunks 目录（防磁盘耗尽）
    _check_upload_permission(current_user, entity_type, entity_id, db)

    # [改进/1.0.9] 检查单工号并发上传数限制，防止滥用
    # UploadSession 模型无 user_id 字段，按 entity_id 统计活跃会话（覆盖同一人员重复上传的场景）
    active_count = db.query(UploadSession).filter(
        UploadSession.entity_id == entity_id,
        UploadSession.status == "active"
    ).count()
    if active_count >= MAX_CONCURRENT_UPLOADS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"同时上传数已达上限（{MAX_CONCURRENT_UPLOADS_PER_USER}个），请等待当前上传完成后再试"
        )

    # [改进/1.0.9] 检查 _chunks 目录总配额
    _check_chunks_disk_quota()

    upload_id = str(uuid.uuid4())
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

    session = UploadSession(
        upload_id=upload_id,
        entity_type=entity_type,
        entity_id=entity_id,
        photo_type=photo_type,
        original_filename=file_name,
        file_size=file_size,
        chunk_size=CHUNK_SIZE,
        total_chunks=total_chunks,
        received_chunks="[]",
        status="active",
    )
    db.add(session)
    db.commit()

    # 创建分片临时目录
    os.makedirs(os.path.join(CHUNKS_DIR, upload_id), exist_ok=True)

    return {
        "upload_id": upload_id,
        "chunk_size": CHUNK_SIZE,
        "total_chunks": total_chunks,
        "received_chunks": [],
    }


@router.get("/{upload_id}")
def get_upload_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询上传状态（用于断点续传，需登录）"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_id == upload_id
    ).first()
    if not session:
        raise HTTPException(404, "上传会话不存在或已过期")
    received = session.get_received()
    return {
        "upload_id": session.upload_id,
        "chunk_size": session.chunk_size,
        "total_chunks": session.total_chunks,
        "received_chunks": received,
        "progress": int(len(received) / session.total_chunks * 100) if session.total_chunks > 0 else 0,
        "status": session.status,
    }


@router.post("/{upload_id}/chunk/{chunk_index}")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传单个分片（需登录，避免未授权写入）"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_id == upload_id,
        UploadSession.status == "active",
    ).first()
    if not session:
        raise HTTPException(404, "上传会话不存在或已过期")

    if chunk_index < 0 or chunk_index >= session.total_chunks:
        raise HTTPException(400, f"分片索引 {chunk_index} 无效，范围 0-{session.total_chunks - 1}")

    # 跳过已上传的分片（断点续传）
    if chunk_index in session.get_received():
        received = session.get_received()
        return {
            "chunk_index": chunk_index,
            "status": "skipped",
            "received_chunks": received,
            "progress": int(len(received) / session.total_chunks * 100),
        }

    # 保存分片
    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_path = os.path.join(chunk_dir, str(chunk_index))

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "空分片")

    # [改进/F3] 累加已落盘分片的真实字节总量并拒绝超限：
    # 原实现只在 init 校验前端声明的 file_size，攻击者可伪造很小的 file_size
    # 再上传超大分片绕过限制。此处按磁盘实际大小累加校验。
    existing_bytes = 0
    if os.path.isdir(chunk_dir):
        for fn in os.listdir(chunk_dir):
            fp = os.path.join(chunk_dir, fn)
            if os.path.isfile(fp):
                existing_bytes += os.path.getsize(fp)
    if existing_bytes + len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            400,
            f"累计上传大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)",
        )

    with open(chunk_path, "wb") as f:
        f.write(content)

    # 更新数据库
    session.add_received(chunk_index)
    session.updated_at = utc_now()
    db.commit()

    received = session.get_received()
    return {
        "chunk_index": chunk_index,
        "status": "ok",
        "received_chunks": received,
        "progress": int(len(received) / session.total_chunks * 100),
    }


@router.post("/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """完成上传：合并分片、保存文件、更新数据库"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_id == upload_id,
        UploadSession.status == "active",
    ).first()
    if not session:
        raise HTTPException(404, "上传会话不存在或已过期")

    received = session.get_received()
    if len(received) != session.total_chunks:
        raise HTTPException(
            400,
            f"分片未完整接收: {len(received)}/{session.total_chunks}，无法合并",
        )

    entity_type = session.entity_type
    entity_id = session.entity_id
    photo_type = session.photo_type

    # --- 权限验证 + 数据范围校验（与 init_upload 复用同一逻辑）---
    _check_upload_permission(current_user, entity_type, entity_id, db)

    # --- 验证实体存在 ---
    if entity_type in ("specialty", "equipment"):
        # 验证 specialty 或 equipment 存在
        from app.models.department import DepartmentSpecialty, DepartmentEquipment
        if entity_type == "specialty":
            entity = db.query(DepartmentSpecialty).filter(DepartmentSpecialty.id == entity_id).first()
            if not entity:
                raise HTTPException(404, "特色技术不存在")
        else:  # equipment
            entity = db.query(DepartmentEquipment).filter(DepartmentEquipment.id == entity_id).first()
            if not entity:
                raise HTTPException(404, "特色设备不存在")
    else:
        # 验证 Staff 存在
        entity = get_staff(db, entity_id)
        if not entity:
            work_type_names = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政人员"}
            entity_name = work_type_names.get(entity_type, "人员")
            raise HTTPException(404, f"{entity_name}不存在")

    # --- 合并分片 ---
    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    ext = os.path.splitext(session.original_filename)[1] or ".jpg"
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{entity_id}_{photo_type}_{timestamp}_{unique_id}{ext}"

    ensure_upload_dirs()
    if photo_type == "card":
        save_sub_dir = "card"
    elif entity_type in ("specialty", "equipment"):
        save_sub_dir = f"{entity_type}_images"
    else:
        save_sub_dir = entity_type
    save_dir = os.path.join(UPLOAD_ROOT, save_sub_dir)
    os.makedirs(save_dir, exist_ok=True)
    final_path = os.path.join(save_dir, filename)

    # 按顺序写入所有分片
    with open(final_path, "wb") as outfile:
        for i in range(session.total_chunks):
            chunk_path = os.path.join(chunk_dir, str(i))
            if not os.path.exists(chunk_path):
                # 清理并报错
                shutil.rmtree(chunk_dir, ignore_errors=True)
                session.status = "expired"
                db.commit()
                raise HTTPException(500, f"分片 {i} 丢失，合并失败")
            with open(chunk_path, "rb") as infile:
                outfile.write(infile.read())

    # [改进/F3] 合并后复检最终文件大小，兜底防止绕过分片累加校验
    if os.path.getsize(final_path) > MAX_FILE_SIZE:
        os.remove(final_path)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        session.status = "expired"
        db.commit()
        raise HTTPException(400, f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)")

    # --- 验证文件格式（魔数检测） ---
    try:
        with open(final_path, 'rb') as f:
            header = f.read(16)
        from app.services.upload_service import detect_image_format
        real_format = detect_image_format(header)
        if real_format and real_format not in ('JPEG', 'PNG', 'WebP'):
            os.remove(final_path)
            shutil.rmtree(chunk_dir, ignore_errors=True)
            session.status = "expired"
            db.commit()
            format_hints = {
                'HEIC': '检测到HEIC/HEIF格式（苹果设备常见），请先转换为JPG/PNG格式后重新上传',
                'BMP': '检测到BMP格式，请转换为JPG/PNG格式后重新上传',
                'GIF': '检测到GIF格式，请转换为JPG/PNG格式后重新上传',
                'TIFF': '检测到TIFF格式，请转换为JPG/PNG格式后重新上传',
                'MOV': '检测到MOV视频格式，请上传静态图片（JPG/PNG/WebP）',
            }
            raise HTTPException(400, format_hints.get(real_format, f'不支持的格式: {real_format}'))
    except HTTPException:
        raise
    except Exception:
        pass  # 格式检测失败不阻止后续验证

    # --- 验证文件（非卡片检查分辨率） ---
    if photo_type != "card":
        try:
            with Image.open(final_path) as img:
                w, h = img.size
                min_w, min_h = 700, 700
                if w < min_w or h < min_h:
                    os.remove(final_path)
                    shutil.rmtree(chunk_dir, ignore_errors=True)
                    session.status = "expired"
                    db.commit()
                    raise HTTPException(
                        400,
                        f"分辨率 {w}x{h} 不满足要求，最小需要 {min_w}x{min_h}",
                    )
        except HTTPException:
            raise
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"PIL无法解析图片文件 (filename={session.original_filename}, path={final_path}, "
                         f"size={os.path.getsize(final_path) if os.path.exists(final_path) else 'N/A'}): "
                         f"{type(e).__name__}: {e}")
            os.remove(final_path)
            shutil.rmtree(chunk_dir, ignore_errors=True)
            session.status = "expired"
            db.commit()
            raise HTTPException(
                400,
                f"无法读取图片文件，请确保图片未损坏且为JPG/PNG/WebP格式（错误: {type(e).__name__}）"
            )

    # --- 删除旧照片 ---
    if photo_type in ("front", "side"):
        old_photo = entity.front_photo if photo_type == "front" else entity.side_photo
        if old_photo:
            delete_file(old_photo)

    # --- 更新数据库 ---
    relative_path = f"{save_sub_dir}/{filename}"

    if photo_type in ("front", "side"):
        # 统一使用 Staff 模型更新照片
        upd = StaffUpdate()
        if photo_type == "front":
            upd.front_photo = relative_path
        else:
            upd.side_photo = relative_path
        update_staff(db, entity_id, upd, updated_by=current_user.employee_id)
        db.commit()
        result = {"file_path": relative_path}
    elif entity_type in ("specialty", "equipment"):
        # specialty 或 equipment 图片：创建对应的图片记录
        from app.models.department import SpecialtyImage, EquipmentImage
        caption = session.original_filename.split('.')[0] if session.original_filename else f"图片{unique_id}"
        if entity_type == "specialty":
            new_image = SpecialtyImage(
                specialty_id=entity_id,
                image_url=relative_path,
                caption=caption[:20],  # 限制20字
                sort_order=0,
            )
        else:  # equipment
            new_image = EquipmentImage(
                equipment_id=entity_id,
                image_url=relative_path,
                caption=caption[:20],  # 限制20字
                sort_order=0,
            )
        db.add(new_image)
        db.commit()
        db.refresh(new_image)
        result = {"image_url": relative_path, "image_id": new_image.id}
    else:
        # card: 创建 StaffCard 记录
        new_card = StaffCard(
            entity_type=entity_type,
            entity_id=entity_id,
            card_photo=relative_path,
            status="pending",
            uploaded_by=current_user.employee_id,
            uploaded_at=utc_now(),
        )
        db.add(new_card)
        db.commit()
        db.refresh(new_card)

        # 发送通知（与 staff_cards.py 一致）
        try:
            entity_name = entity.name if hasattr(entity, 'name') else entity_id
            dept_name = entity.department or ""

            work_type_names = {"doctor": "医生", "nurse": "护士", "technician": "技师", "admin": "行政人员"}
            work_type_label = work_type_names.get(entity_type, "人员")

            title = f"{entity_name}的卡片需要确认"
            content = f"{entity_name}（{entity_id}）上传了{work_type_label}卡片，请及时确认。"

            # 通知本人
            create_notification(db, entity_id, title, content, "card", new_card.id)
            # 通知有卡片上传权限的用户（基于权限系统，而非角色名硬编码）
            all_active_users = db.query(User).filter(User.is_active == True).all()
            for u in all_active_users:
                if u.employee_id == entity_id:
                    continue
                if not has_permission(u, PERM_CARD_UPLOAD):
                    continue
                # 根据数据范围过滤
                from app.dependencies import get_user_department_scope
                from app.models.department import Department
                managed_dept_ids = get_user_department_scope(u, db)
                if managed_dept_ids and dept_name:
                    target_dept = db.query(Department).filter(Department.name == dept_name).first()
                    if not target_dept or target_dept.id not in managed_dept_ids:
                        continue
                elif dept_name and not managed_dept_ids:
                    continue
                create_notification(db, u.employee_id, title, content, "card", new_card.id)

            db.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"发送卡片通知失败: {e}")

        result = {"card_photo": relative_path, "card_id": new_card.id}

    # [改进] 原图保持用户上传时的原始格式与内容，不做任何改动（如透明背景合成白底）。
    # 系统展示用的白底缩略图由 generate_thumbnail 单独生成（thumb_ 前缀，独立文件）。

    # [改进] 分片路径无独立原文件：复制合并后的正式图作为 orig_ 原始副本，统一双存策略
    try:
        from app.services.upload_service import create_original_copy
        create_original_copy(final_path)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"生成原始副本失败: {e}")

    # [改进] 正式图统一转 RGB 色空间：浏览器不支持 CMYK 等编码的 JPEG 直接解码
    # （会偏色/过暗），转 RGB 后展示与预览颜色正确；orig_ 副本保留原始编码供溯源。
    try:
        from app.services.upload_service import convert_to_rgb
        convert_to_rgb(final_path)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"RGB 色空间转换失败: {e}")

    # --- 生成缩略图 ---
    try:
        generate_thumbnail(final_path)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"缩略图生成失败: {e}")

    # --- 清理分片和会话 ---
    shutil.rmtree(chunk_dir, ignore_errors=True)
    session.status = "completed"
    db.commit()

    # [改进] 上传完成后一并续发 file_token（图片访问令牌，有效期 1h）。
    # 原因：图片请求由 <img> 发起，只带 ?ftoken= 不带 Bearer；若上传时恰逢 file_token 过期，
    # 刚上传的照片及页面所有图片都会 403 显示"文件已丢失"，且不会触发全局静默刷新。
    # 随上传响应返回新 file_token，前端写入后立即可用。
    from app.utils import create_file_access_token
    result["file_token"] = create_file_access_token(current_user.employee_id)

    return result


@router.delete("/{upload_id}")
def cancel_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消上传并清理分片（需登录并校验会话归属）"""
    # [改进/F1] 原实现完全无鉴权（仅 Depends(get_db)），匿名请求即可将任意会话
    # 标记 expired 并 rmtree 他人分片目录，中断上传。现补登录 + 归属/权限校验。
    session = db.query(UploadSession).filter(
        UploadSession.upload_id == upload_id,
        UploadSession.status == "active",
    ).first()
    if session:
        # 仅允许对目标实体有上传权限者取消（复用与创建一致的权限校验）
        _check_upload_permission(current_user, session.entity_type, session.entity_id, db)
        session.status = "expired"
        db.commit()

    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    shutil.rmtree(chunk_dir, ignore_errors=True)

    return {"message": "上传已取消"}
