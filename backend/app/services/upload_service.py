# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import os
import uuid
import re
from pathlib import Path

from app.utils import utc_now

from fastapi import UploadFile, HTTPException
from PIL import Image
import io

from app.config import DATA_ROOT, settings

# 允许的图片类型
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

# 最大文件大小 [改进/F3] 由配置 upload_max_size_mb 驱动（默认 20MB），
# 原先是硬编码常量，config.py 的 upload_max_size_mb 从未被引用。
MAX_FILE_SIZE = settings.upload_max_size_mb * 1024 * 1024

# 最小分辨率
MIN_WIDTH = 700
MIN_HEIGHT = 700

# [改进] 使用 DATA_ROOT 确保上传目录指向数据根目录的 data/uploads，
# 与 backend 完全隔离（源码布局=项目根/data/uploads；Docker=/app/data/uploads）。
UPLOAD_ROOT = os.path.join(str(DATA_ROOT), "uploads")

# 安全：entity_id 允许的字符（字母、数字、下划线、连字符）
VALID_ENTITY_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# [改进/F5] 允许的文件扩展名白名单（与 ALLOWED_IMAGE_TYPES 对应）。
# 仅用于生成落盘文件名的后缀，杜绝从 filename 带入 .php/.svg 等危险后缀
# 或含斜杠导致的路径穿越；扩展名一律小写后比对。
ALLOWED_FILE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_FILE_EXTENSION = ".jpg"

# [修复 2026-09-03] 标识设计文件允许的扩展名（支持.ai和.pdf）
SIGNAGE_DESIGN_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".ai", ".pdf"}
SIGNAGE_DESIGN_TYPES = {"image/jpeg", "image/png", "image/webp", "application/postscript", "application/pdf"}

# [修复 2026-09-04] 标识编码允许中文字符（标识编码如"南-XX-0-001"可含中文），
# 仅禁止路径遍历字符（斜杠、反斜杠、点），防止构造恶意路径
SIGNAGE_CODE_PATTERN = re.compile(r'^[^/\\.\x00]+$')


def ensure_upload_dirs():
    """确保上传目录存在"""
    for sub_dir in ("doctor", "nurse", "technician", "admin", "card", "dept", "floor_plan", "signage"):
        os.makedirs(os.path.join(UPLOAD_ROOT, sub_dir), exist_ok=True)


def validate_image_file(file: UploadFile) -> None:
    """验证上传的图片文件（基于魔数检测，支持 RGB/CMYK 等编码）"""
    # 读取文件头检测真实格式（比 content_type 更可靠，支持 CMYK/ProPhoto 等变体编码的 JPEG）
    head = b""
    try:
        # 尝试 peek 方式读取，不影响后续读取
        if hasattr(file, 'file') and hasattr(file.file, 'peek'):
            head = file.file.peek(16)[:16]
        else:
            head_bytes = file.file.read(16) if hasattr(file, 'file') else b""
            if hasattr(file, 'seek'):
                file.file.seek(0)
            head = head_bytes
    except Exception:
        pass

    if head:
        real_format = detect_image_format(head)
        if real_format and real_format not in ('JPEG', 'PNG', 'WebP'):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {real_format}，仅支持 JPG/PNG/WebP"
            )
    else:
        # 回退到 content_type 检查（兼容无法 peek 的场景）
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 JPG/PNG/WebP 格式"
            )


# [修复 2026-09-03] 验证标识设计文件（支持.ai和.pdf）
def validate_design_file(file: UploadFile) -> None:
    """验证上传的标识设计文件（支持图片、AI和PDF）"""
    # 检查文件扩展名
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    
    # 如果有扩展名，检查是否在允许列表中
    if file_ext in SIGNAGE_DESIGN_EXTENSIONS:
        return  # 扩展名有效，直接通过
    
    # 如果没有扩展名或不在列表中，通过content_type检查
    if file.content_type in SIGNAGE_DESIGN_TYPES:
        return  # content_type有效
    
    # 最后尝试通过文件头检测
    head = b""
    try:
        if hasattr(file, 'file') and hasattr(file.file, 'peek'):
            head = file.file.peek(16)[:16]
        else:
            head_bytes = file.file.read(16) if hasattr(file, 'file') else b""
            if hasattr(file, 'seek'):
                file.file.seek(0)
            head = head_bytes
    except Exception:
        pass
    
    if head:
        real_format = detect_image_format(head)
        if real_format and real_format not in ('JPEG', 'PNG', 'WebP'):
            # 非图片格式，检查是否为PDF或AI
            if head[:5] == b'%PDF-':
                return  # PDF文件
            if head[:2] == b'%!':
                return  # PostScript/AI文件
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {real_format}，支持 JPG/PNG/WebP/AI/PDF 格式"
            )
    
    raise HTTPException(
        status_code=400,
        detail=f"不支持的文件类型: {file.content_type}，支持 JPG/PNG/WebP/AI/PDF 格式"
    )


def detect_image_format(content: bytes) -> str | None:
    """通过文件头魔数检测图片真实格式"""
    if len(content) < 12:
        return None
    # JPEG: FF D8 FF
    if content[:3] == b'\xff\xd8\xff':
        return 'JPEG'
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if content[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    # WebP: RIFF....WEBP
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'WebP'
    # HEIC/HEIF: ....ftyp
    if content[4:8] == b'ftyp':
        brand = content[8:12]
        if brand in (b'heic', b'heix', b'mif1', b'msf1'):
            return 'HEIC'
        if brand in (b'qt  ', b'mqt '):
            return 'MOV'
    # BMP
    if content[:2] == b'BM':
        return 'BMP'
    # GIF
    if content[:6] in (b'GIF87a', b'GIF89a'):
        return 'GIF'
    # TIFF
    if content[:2] in (b'II', b'MM'):
        return 'TIFF'
    return None


def _looks_like_svg(file: UploadFile) -> bool:
    """[修复 2026-09-05] 通过 content_type 或扩展名判断是否为 SVG 文件"""
    if file.content_type == "image/svg+xml":
        return True
    name = (file.filename or "").lower()
    return name.endswith(".svg")


def _is_svg_content(content: bytes) -> bool:
    """[修复 2026-09-05] 通过文件头判断字节内容是否为合法 SVG（XML 声明或 <svg 标签）"""
    head = content[:512].lstrip()
    return head[:5] == b'<?xml' or head[:4].lower() == b'<svg'


def convert_to_rgb(file_path: str) -> None:
    """将图片转为 RGB 色空间后原地覆盖保存（CMYK 等非 RGB 编码 → RGB）。

    浏览器不支持 CMYK 等非 RGB 编码的 JPEG 直接解码（会偏色/过暗），
    统一转为 RGB 保证展示与预览颜色正确。扩展名保持不变，仅重编码像素色空间：
    - 已是 RGB 模式则直接跳过，避免无谓的二次压缩；
    - RGBA/LA/P 等含透明通道的图先合成到纯白底（与缩略图逻辑一致）。
    转换失败仅记日志，不阻断上传主流程（保留原文件）。
    """
    try:
        with Image.open(file_path) as img:
            if img.mode == 'RGB':
                return
            if img.mode in ('RGBA', 'LA', 'P'):
                # 透明通道合成纯白底（避免转 RGB 后透明变黑）
                img = img.convert('RGBA')
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                rgb_img = background
            else:
                # CMYK 等模式直接转换
                rgb_img = img.convert('RGB')
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.png':
            rgb_img.save(file_path, optimize=True)
        elif ext == '.webp':
            rgb_img.save(file_path, quality=90, method=6)
        else:
            # JPEG 用较高质量重编码，避免 CMYK→RGB 后画质损失
            rgb_img.save(file_path, quality=92, optimize=True)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"RGB 色空间转换失败，保留原文件: {e}")


async def save_upload_file(
    file: UploadFile,
    entity_type: str,
    entity_id: str,
    photo_type: str = "photo",
    min_width: int = MIN_WIDTH,
    min_height: int = MIN_HEIGHT,
    original: UploadFile | None = None,
    allow_svg: bool = False,
) -> str:
    """
    保存上传的文件
    
    Args:
        file: 上传的文件
        entity_type: 实体类型 (doctor/nurse/card)
        entity_id: 实体ID (工号)
        photo_type: 照片类型 (front/side/card)
        original: 前端裁剪后附带的原始照片（未裁剪则不传）；用于 orig_ 双存溯源
    
    Returns:
        保存后的文件相对路径
    """
    # 验证文件类型（SVG 由 allow_svg 控制，跳过位图格式校验）
    # [修复 2026-09-05] 平面图支持 SVG 上传
    is_svg = allow_svg and _looks_like_svg(file)
    if not is_svg:
        validate_image_file(file)
    # SVG 内容合法性校验推迟到读取文件内容之后（content 尚未读取）
    
    # 安全：验证 entity_id 防止路径遍历
    if not VALID_ENTITY_ID_PATTERN.match(entity_id):
        raise HTTPException(
            status_code=400,
            detail="无效的实体ID，仅支持字母、数字、下划线和连字符"
        )
    
    # 确保上传目录存在
    ensure_upload_dirs()
    
    # 读取文件内容以检查大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制: {len(content) / 1024 / 1024:.2f}MB，最大允许 20MB"
        )

    # [修复 2026-09-05] SVG 内容合法性兜底校验（平面图允许 SVG 上传）
    if is_svg and not _is_svg_content(content):
        raise HTTPException(status_code=400, detail="文件内容不是合法的 SVG 格式")

    # 通过文件头检测真实格式，防止格式不匹配（如HEIC伪装为PNG）
    real_format = detect_image_format(content)
    if real_format and real_format not in ('JPEG', 'PNG', 'WebP'):
        format_hints = {
            'HEIC': '检测到HEIC/HEIF格式（苹果设备常见），请先在手机"设置→照片→传输到Mac或PC"中转换，或使用格式转换工具转为JPG/PNG',
            'BMP': '检测到BMP格式，请转换为JPG/PNG格式后重新上传',
            'GIF': '检测到GIF格式，请转换为JPG/PNG格式后重新上传',
            'TIFF': '检测到TIFF格式，请转换为JPG/PNG格式后重新上传',
            'MOV': '检测到MOV视频格式，请上传静态图片（JPG/PNG/WebP）',
        }
        hint = format_hints.get(real_format, f'不支持的格式: {real_format}')
        raise HTTPException(status_code=400, detail=hint)

    # 验证分辨率（卡片照片不限制分辨率，支持 RGB/CMYK 等编码；SVG 无位图尺寸，跳过）
    # [修复 2026-09-05] SVG 跳过 Pillow 分辨率校验
    if photo_type != 'card' and not is_svg:
        try:
            # [修复/问题21] 用 with 确保 Pillow 解码缓冲及时释放。
            # 原实现打开后只读 size 便丢弃引用，依赖 GC 回收，
            # 批量上传场景会加剧内存波动。
            with Image.open(io.BytesIO(content)) as img:
                # CMYK 等特殊色空间先转为 RGB 再获取尺寸
                if img.mode == 'CMYK':
                    img = img.convert('RGB')
                width, height = img.size
            if width < min_width or height < min_height:
                raise HTTPException(
                    status_code=400,
                    detail=f"分辨率 {width}x{height} 不满足要求，最小需要 {min_width}x{min_height}"
                )
        except HTTPException:
            raise
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"PIL无法解析图片文件 (filename={file.filename}, content_type={file.content_type}, "
                         f"size={len(content)}bytes): {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"无法读取图片文件，请确保图片未损坏且为JPG/PNG/WebP格式（支持RGB/CMYK编码）（错误: {type(e).__name__}）"
            )
    
    # 生成唯一文件名
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    # [改进/F6] 扩展名判定改为以魔数真实格式为准，而非依赖上传文件名后缀。
    # 原因：部分客户端（微信/手机相册导出、前端 FormData 改写 name）上传的 PNG 文件
    # 不带 .png 后缀，旧逻辑会回退为 .jpg，导致"上传 PNG、下载变 JPG"的表象。
    # 仅允许白名单内的真实格式（JPEG/PNG/WebP），其余（含无法识别）回退为 .jpg。
    # [修复 2026-09-05] SVG 使用 .svg 扩展名落盘，不做 RGB 转换与缩略图生成。
    FORMAT_TO_EXT = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}
    if is_svg:
        file_ext = ".svg"
    else:
        real_fmt = detect_image_format(content)
        file_ext = FORMAT_TO_EXT.get(real_fmt) if real_fmt in FORMAT_TO_EXT else DEFAULT_FILE_EXTENSION
    filename = f"{entity_id}_{photo_type}_{timestamp}_{unique_id}{file_ext}"

    # 构建保存路径
    save_dir = os.path.join(UPLOAD_ROOT, entity_type)
    save_path = os.path.join(save_dir, filename)

    # [改进/F5] 二次防御：断言最终写入路径仍在 UPLOAD_ROOT 之内，
    # 即使上游 entity_type/entity_id 校验被绕过也不会脱离上传根目录。
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_save = os.path.realpath(save_path)
    if real_save != real_root and not real_save.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="非法的文件保存路径")

    # 重置文件指针并保存
    await file.seek(0)
    with open(save_path, "wb") as f:
        f.write(content)

    # [改进] 正式图统一转 RGB 色空间：浏览器不支持 CMYK 等编码的 JPEG 直接解码
    # （会偏色/过暗），转 RGB 后展示与预览颜色正确。仅重编码像素色空间，
    # 已是 RGB 则跳过（不无谓二次压缩）；orig_ 原始副本保留用户上传原样内容供溯源。
    # [修复 2026-09-05] SVG 无法被 Pillow 解析，跳过 RGB 转换与缩略图生成。
    if not is_svg:
        convert_to_rgb(save_path)

    # [改进] 原始照片双存：正式图入库用于统一展示；原始照片以 orig_ 前缀同目录另存，
    # 供"下载原图"溯源。前端裁剪照片后会把未裁剪的原文件随 original 字段一并上传；
    # 若未提供（未裁剪直传/分片上传/部门图片等），则复制正式图作为 orig_ 副本，
    # 保证前端 orig_ 优先回退路径始终可用（旧数据无 orig_ 时回退正式图）。
    if original is not None:
        original_bytes = await original.read()
        # [改进] orig_ 副本使用原文件自身真实扩展名（如 PNG/WebP），
        # 不复用正式图（裁剪 JPEG）的 .jpg 后缀，保证原图格式不被改变。
        # [修复 2026-09-05] SVG 原图副本同样使用 .svg 扩展名。
        if is_svg:
            orig_ext = ".svg"
        else:
            orig_ext = FORMAT_TO_EXT.get(detect_image_format(original_bytes)) or DEFAULT_FILE_EXTENSION
        orig_name = f"{ORIG_PREFIX}{os.path.splitext(filename)[0]}{orig_ext}"
        with open(os.path.join(save_dir, orig_name), "wb") as f:
            f.write(original_bytes)
    else:
        # [修复] 原先引用未定义的 original_bytes 导致 NameError（部门图片上传等
        # 不传 original 的场景必然 500 崩溃），改为复用正式图内容作为 orig_ 副本
        save_original_copy(save_path, content)

    # [改进] 原图保持用户上传时的原始格式与内容，不做任何改动（如透明背景合成白底）。
    # 系统展示用的白底缩略图由 generate_thumbnail 单独生成（thumb_ 前缀，独立文件），不污染原图。
    # [修复 2026-09-05] SVG 不生成缩略图（矢量图无需位图缩略图）。
    if not is_svg:
        generate_thumbnail(save_path)
    
    # 返回相对路径
    return f"{entity_type}/{filename}"


# [修复 2026-09-03] 保存标识设计文件的专用函数（支持.ai和.pdf）
async def save_signage_design_file(
    file: UploadFile,
    signage_code: str,
    photo_type: str = "design",
) -> str:
    """
    保存标识设计文件（支持.ai和.pdf格式）
    
    Args:
        file: 上传的文件
        signage_code: 标识编码
        photo_type: 照片类型 (design/installation)
    
    Returns:
        保存后的文件相对路径
    """
    # 验证文件类型
    validate_design_file(file)
    
    # [修复 2026-09-04] 安全：验证标识编码防止路径遍历
    # 标识编码可能包含中文（如"南-XX-0-001"），使用 SIGNAGE_CODE_PATTERN 允许中文
    # 但禁止斜杠、反斜杠、点等路径遍历字符
    if not signage_code or not SIGNAGE_CODE_PATTERN.match(signage_code):
        raise HTTPException(
            status_code=400,
            detail="无效的标识编码"
        )
    
    # 确保上传目录存在
    ensure_upload_dirs()
    
    # 读取文件内容以检查大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制: {len(content) / 1024 / 1024:.2f}MB，最大允许 20MB"
        )
    
    # 生成唯一文件名
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    
    # 确定文件扩展名
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in SIGNAGE_DESIGN_EXTENSIONS:
        # 尝试通过文件头检测
        if content[:5] == b'%PDF-':
            file_ext = ".pdf"
        elif content[:2] == b'%!':
            file_ext = ".ai"
        else:
            file_ext = DEFAULT_FILE_EXTENSION
    
    filename = f"{signage_code}_{photo_type}_{timestamp}_{unique_id}{file_ext}"
    
    # 构建保存路径
    save_dir = os.path.join(UPLOAD_ROOT, "signage")
    save_path = os.path.join(save_dir, filename)
    
    # 二次防御：断言最终写入路径仍在 UPLOAD_ROOT 之内
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_save = os.path.realpath(save_path)
    if real_save != real_root and not real_save.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="非法的文件保存路径")
    
    # 重置文件指针并保存
    await file.seek(0)
    with open(save_path, "wb") as f:
        f.write(content)
    
    # 对于图片文件，进行RGB转换和缩略图生成
    if file_ext in ('.jpg', '.jpeg', '.png', '.webp'):
        convert_to_rgb(save_path)
        generate_thumbnail(save_path)
    
    # 返回相对路径
    return f"signage/{filename}"


def get_file_path(relative_path: str) -> str:
    """获取文件的绝对路径"""
    return os.path.join(UPLOAD_ROOT, relative_path)


def delete_file(relative_path: str) -> bool:
    """删除文件（联动删除缩略图 thumb_ 与原始副本 orig_，防孤儿文件残留）"""
    try:
        file_path = get_file_path(relative_path)
        if os.path.exists(file_path):
            os.remove(file_path)
            # 同时删除缩略图（与正式图同扩展名）
            thumb_path = get_prefixed_path(file_path, "thumb_")
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            # [改进] 原始副本扩展名可能与正式图不同（原文件为 PNG/WebP 时），
            # 按 "orig_ + 正式图文件名主干" 前缀匹配删除所有扩展名。
            dir_name = os.path.dirname(file_path)
            base_stem = os.path.splitext(os.path.basename(file_path))[0]
            for fname in os.listdir(dir_name):
                if (
                    fname.startswith(f"{ORIG_PREFIX}{base_stem}")
                    # [修复 2026-09-07] 补充 .svg：SVG 原图副本此前不在清理范围，删除主文件时会残留
                    and os.path.splitext(fname)[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".svg")
                ):
                    os.remove(os.path.join(dir_name, fname))
            return True
        return False
    except Exception:
        return False


# [改进] 原始照片双存前缀：正式图（前端裁剪后的统一 3:4 图或原图）入库统一展示；
# 原始照片以 orig_ 前缀同目录另存，供"下载原图"溯源。
ORIG_PREFIX = "orig_"


def get_prefixed_path(file_path: str, prefix: str) -> str:
    """获取带前缀的关联文件路径（如缩略图 thumb_、原始副本 orig_）"""
    dir_name = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)
    return os.path.join(dir_name, f"{prefix}{base_name}")


def get_thumbnail_path(file_path: str) -> str:
    """获取缩略图路径"""
    return get_prefixed_path(file_path, "thumb_")


def save_original_copy(main_path: str, content: bytes) -> str:
    """将原始图片字节保存为 orig_ 前缀副本，返回副本绝对路径。"""
    orig_path = get_prefixed_path(main_path, ORIG_PREFIX)
    with open(orig_path, "wb") as f:
        f.write(content)
    return orig_path


def create_original_copy(main_path: str) -> str:
    """将主文件复制为 orig_ 前缀副本（用于分片合并等无独立原文件的场景）"""
    import shutil
    orig_path = get_prefixed_path(main_path, ORIG_PREFIX)
    shutil.copy2(main_path, orig_path)
    return orig_path


def generate_thumbnail(file_path: str):
    """生成缩略图（最大宽度1000px，质量递减确保 < 1MB，CMYK 转 RGB）。

    [改进] 宽度由 500px 提升至 1000px、质量起点由 50 提升至 75：
    工卡照片展示框最大 400px，在 2x~3x 高 DPI 屏（Retina）上需要 800~1200px 才清晰，
    旧 500px 缩略图放大显示明显模糊。
    """
    try:
        thumb_path = get_thumbnail_path(file_path)
        with Image.open(file_path) as img:
            # CMYK 色空间转 RGB
            if img.mode == 'CMYK':
                img = img.convert('RGB')
            # PNG 透明背景处理：先合成到纯白色底图上再压缩（冗余处理，但调用处可能跳过白底转换）
            elif img.mode == 'RGBA':
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])  # 用 alpha 通道作为蒙版
                img = background
            elif img.mode == 'P':
                img = img.convert('RGBA')
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            if img.width > 1000:
                ratio = 1000 / img.width
                new_height = int(img.height * ratio)
                img = img.resize((1000, new_height), Image.LANCZOS)
            # 递减质量确保缩略图 < 1MB（起点 75 保证清晰度）
            for quality in (75, 55, 35):
                img.save(thumb_path, quality=quality, optimize=True)
                if os.path.getsize(thumb_path) < 1024 * 1024:
                    break
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"缩略图生成失败: {e}")


# ====== 孤儿图片清理 ======

def build_referenced_set(db) -> set[str]:
    """构建数据库中所有表引用的图片路径集合。
    
    用于备份恢复后清理"磁盘有、数据库无"的孤儿图片。
    遍历所有涉及图片存储的模型字段，收集非空的相对路径。
    
    Returns:
        被引用的相对路径集合（如 {"doctor/xxx.jpg", "dept/yyy.jpg"}）
    """
    from app.models.staff import Staff
    from app.models.doctor import Doctor
    from app.models.nurse import Nurse
    from app.models.department import Department
    from app.models.staff_card import StaffCard

    referenced: set[str] = set()

    # 1. 人员表（Staff、Doctor、Nurse）的正面/侧面照
    for model in (Staff, Doctor, Nurse):
        for row in db.query(model.front_photo, model.side_photo).all():
            if row.front_photo:
                referenced.add(row.front_photo)
            if row.side_photo:
                referenced.add(row.side_photo)

    # 2. 科室合照
    for row in db.query(Department.group_photo).all():
        if row.group_photo:
            referenced.add(row.group_photo)

    # 3. 员工卡片照
    for row in db.query(StaffCard.card_photo).all():
        if row.card_photo:
            referenced.add(row.card_photo)

    # 4. 特色技术图片 / 设备图片（通过 department 关系的 image_url）
    try:
        from app.models.department import SpecialtyImage, EquipmentImage
        for row in db.query(SpecialtyImage.image_url).all():
            if row.image_url:
                referenced.add(row.image_url)
        for row in db.query(EquipmentImage.image_url).all():
            if row.image_url:
                referenced.add(row.image_url)
    except ImportError:
        pass

    # [修复 2026-09-03] 5. 标识设计文件和现场照片
    from app.models.signage import Signage
    for row in db.query(Signage.design_photo, Signage.installation_photo).all():
        if row.design_photo:
            referenced.add(row.design_photo)
        if row.installation_photo:
            referenced.add(row.installation_photo)

    # [修复 2026-09-07] 6. 平面图图片（FloorPlan.image_url，存于 floor_plan/ 目录）与
    # 标识历史照片记录（SignagePhoto.photo_url）：此前未纳入引用集合，
    # 每日 19:15 的孤儿清理任务（backup_service.clean_orphan_images）会把在用的
    # 平面图图片当作孤儿误删。此处一并收集，防止误删。
    from app.models.signage import FloorPlan, SignagePhoto
    for row in db.query(FloorPlan.image_url).all():
        if row.image_url:
            referenced.add(row.image_url)
    for row in db.query(SignagePhoto.photo_url).all():
        if row.photo_url:
            referenced.add(row.photo_url)

    return referenced


def delete_orphan_files(referenced: set[str]) -> dict:
    """删除磁盘上存在但数据库不引用的孤儿图片及对应缩略图。
    
    [改进] 关联文件孤儿清理：扫描所有 thumb_* / orig_* 文件，若其对应的正式图路径
    不在 referenced 集合中，则一并删除。解决备份恢复后缩略图/原始副本残留的问题。
    
    Args:
        referenced: 数据库引用的相对路径集合（由 build_referenced_set 生成）
    
    Returns:
        清理统计信息 {deleted: int, thumbs_deleted: int, total_orphans: int, total_bytes_freed: int}
    """
    import logging
    logger = logging.getLogger(__name__)
    
    orphan_count = 0
    orphan_thumb_count = 0
    orphan_orig_count = 0
    freed_bytes = 0
    
    upload_root = Path(UPLOAD_ROOT)
    if not upload_root.is_dir():
        return {"deleted": 0, "thumbs_deleted": 0, "total_orphans": 0, "total_bytes_freed": 0}

    for file_path in upload_root.rglob("*"):
        if not file_path.is_file():
            continue
        # 跳过 _chunks（分片上传临时）与 richtext（富文本正文图片，HTML 内引用、
        # 无法纳入引用集合）目录，避免误删
        relative = str(file_path.relative_to(upload_root))
        if relative.startswith("_chunks") or relative.startswith("richtext"):
            continue

        # 只处理图片类型文件（跳过 .gitkeep 等非图片）
        ext = file_path.suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            continue

        # [改进] 前缀判断基于文件名（缩略图/原始副本与正式图同目录），
        # 旧实现用 relative.startswith 判断，对 doctor/thumb_x.jpg 这类带目录前缀的文件不命中，
        # 导致缩略图被当孤儿误删、orig_ 副本也会被误删。现按 basename 前缀识别并正确派生主图相对路径。
        name = file_path.name
        dir_part = os.path.dirname(relative).replace("\\", "/")
        rel_prefix = f"{dir_part}/" if dir_part else ""

        # 处理缩略图文件：其对应正式图被引用则保留，否则删除
        if name.startswith("thumb_"):
            main_relative = f"{rel_prefix}{name[len('thumb_'):]}"
            if main_relative not in referenced:
                try:
                    size = file_path.stat().st_size
                    file_path.unlink()
                    orphan_thumb_count += 1
                    freed_bytes += size
                    logger.info(f"已删除孤儿缩略图: {relative} ({size} bytes)")
                except OSError as e:
                    logger.warning(f"删除孤儿缩略图失败 {relative}: {e}")
            continue  # 缩略图已处理，跳过后续逻辑

        # 处理原始副本文件（orig_ 前缀）：其对应正式图被引用则保留，否则删除
        # [改进] orig_ 扩展名可能与正式图不同（原图 PNG/WebP），按文件名主干匹配 referenced
        if name.startswith(ORIG_PREFIX):
            main_stem = os.path.splitext(name[len(ORIG_PREFIX):])[0]
            main_prefix = f"{rel_prefix}{main_stem}"
            is_referenced = any(
                r == main_prefix or r.startswith(main_prefix + ".") for r in referenced
            )
            if not is_referenced:
                try:
                    size = file_path.stat().st_size
                    file_path.unlink()
                    orphan_orig_count += 1
                    freed_bytes += size
                    logger.info(f"已删除孤儿原始副本: {relative} ({size} bytes)")
                except OSError as e:
                    logger.warning(f"删除孤儿原始副本失败 {relative}: {e}")
            continue  # 原始副本已处理，跳过后续逻辑

        if relative not in referenced:
            try:
                size = file_path.stat().st_size
                file_path.unlink()
                orphan_count += 1
                freed_bytes += size
                logger.info(f"已删除孤儿图片: {relative} ({size} bytes)")

                # 同时删除对应的缩略图和原始副本
                thumb = file_path.parent / f"thumb_{file_path.name}"
                if thumb.exists():
                    thumb.unlink()
                    orphan_thumb_count += 1
                    logger.info(f"已删除对应缩略图: thumb_{relative}")
                orig = file_path.parent / f"{ORIG_PREFIX}{file_path.name}"
                if orig.exists():
                    orig.unlink()
                    orphan_orig_count += 1
                    logger.info(f"已删除对应原始副本: {ORIG_PREFIX}{relative}")
            except OSError as e:
                logger.warning(f"删除孤儿图片失败 {relative}: {e}")

    total_deleted = orphan_count + orphan_thumb_count + orphan_orig_count
    logger.info(
        f"孤儿图片清理完成: 删除 {orphan_count} 张原图 + {orphan_thumb_count} 张缩略图 "
        f"+ {orphan_orig_count} 张原始副本, 释放 {freed_bytes} bytes"
    )
    return {
        "deleted": orphan_count,
        "thumbs_deleted": orphan_thumb_count,
        "origs_deleted": orphan_orig_count,
        "total_orphans": total_deleted,
        "total_bytes_freed": freed_bytes,
    }
