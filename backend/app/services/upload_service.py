# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
import os
import time as _time
import uuid
import re
from pathlib import Path

from app.utils import utc_now

from fastapi import UploadFile, HTTPException
from PIL import Image
import io

from app.config import DATA_ROOT, settings

logger = logging.getLogger(__name__)

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

# ---- 孤儿清理的两道安全阀（见 delete_orphan_files 文档） ----

# 安全阀①：新文件保护期（小时）。mtime 在此窗口内的文件一律不清理。
# 取值 24 的理由：覆盖"上传落盘 → 数据库提交"的正常窗口（秒级）绰绰有余，
# 同时给误判留出人工发现的缓冲 —— 即便某天清理逻辑出问题，
# 也有一整天时间在数据被删前发现（照片类数据的清理并不要求及时性）。
NEW_FILE_GRACE_HOURS = 24

# 安全阀②：目录级异常保护的触发下限。
# 某目录待删数 ≥ 该值、且待删数占比过半时，判定为异常并跳过整个目录。
# 取 10 的理由：小目录（如只有 2~3 个废弃文件）的比例天然容易过半，
# 若不加数量下限，这类目录会被永久跳过而无法回收；
# 而真正的"漏登记字段"误判通常是整批（几十上百个），必然远超 10。
_ABNORMAL_DIR_MIN_COUNT = 10


def ensure_upload_dirs():
    """确保上传目录存在。

    [新增 2026-09-17] 追加 files 子目录：文件库（设计文件集中管理）的落盘位置。
    """
    for sub_dir in (
        "doctor", "nurse", "technician", "admin", "card", "dept", "floor_plan",
        "signage", "files",
    ):
        os.makedirs(os.path.join(UPLOAD_ROOT, sub_dir), exist_ok=True)


def save_validated_photo(file: UploadFile, subdir: str, name_prefix: str | None = None) -> str:
    """校验并保存一张上传照片，返回相对 uploads 的路径（如 "inspection/xxx.jpg"）。

    [新增 2026-09-21 / 代码质量审计 Q-7] 此前"校验 + 落盘 + 路径穿越断言 + 生成缩略图"
    这套流程在四处各写了一遍（约 30 行/处）：
        routers/signage_inspections.py  _save_inspection_photo
        routers/signage_alerts.py       _save_repair_photo
        routers/departments.py          科室图片（两处）

    这不是"看着重复"而已 —— **它已经造成过实际缺陷**：这些实现中只有部分
    调用了 generate_thumbnail，导致巡检/维修照片长期没有缩略图（前端 SafeImage
    先 404 再回退原图，既刷控制台噪声又多下载一张大图）。当时正是因为
    "改了一处、漏了另一处"。收敛到本函数后，缩略图等步骤不可能再被漏掉。

    参数:
        file:        上传文件对象
        subdir:      落盘子目录（如 "inspection" / "repair" / "dept"）
        name_prefix: 文件名前缀；省略时用子目录名（如 repair_2026...jpg）
                     巡检照片会传入标识编码作为前缀，便于人工排查时辨认归属

    返回:
        相对 uploads 的路径（不含前导斜杠），与 getOriginalUrl 的 /uploads/{path} 约定一致。

    抛出:
        HTTPException 400 —— 文件类型不受支持、超限、或落盘后路径越界。
    """
    validate_image_file(file)
    content = file.file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制，最大允许 {settings.upload_max_size_mb}MB",
        )

    # 按魔数判断真实格式（比 content_type 可靠，能识别 CMYK/ProPhoto 等变体编码）
    real_format = detect_image_format(content)
    if real_format not in ("JPEG", "PNG", "WebP"):
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式")
    ext = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}[real_format]

    dir_path = os.path.join(UPLOAD_ROOT, subdir)
    os.makedirs(dir_path, exist_ok=True)
    prefix = name_prefix or subdir
    filename = f"{prefix}_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    absolute_path = os.path.join(dir_path, filename)

    with open(absolute_path, "wb") as f:
        f.write(content)

    # 路径穿越防护：断言解析后的真实路径仍位于上传根目录内
    real_root = os.path.realpath(UPLOAD_ROOT)
    real_abs = os.path.realpath(absolute_path)
    if real_abs != real_root and not real_abs.startswith(real_root + os.sep):
        # 落盘已发生，先清理再报错，避免留下一个越界文件
        try:
            os.remove(absolute_path)
        except OSError as rm_err:
            logger.warning("清理越界文件失败: %s", rm_err, exc_info=True)
        raise HTTPException(status_code=400, detail="非法文件路径")

    # 生成展示用缩略图（thumb_ 前缀）：前端 SafeImage 统一请求缩略图路径
    generate_thumbnail(absolute_path)

    return f"{subdir}/{filename}"


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
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

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
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    
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
        logger.warning(f"RGB 色空间转换失败，保留原文件: {e}", exc_info=True)


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
            # [修正 2026-09-19] ERROR → WARN：用户上传损坏或不受支持的图片属**入参错误**，
            # 已通过下方 HTTP 400 明确反馈给调用方，不是服务端故障。
            # 按规范「用户输入参数错误」应记 WARN，打 ERROR 会污染告警通道。
            logger.warning(f"PIL无法解析图片文件 (filename={file.filename}, content_type={file.content_type}, "
                           f"size={len(content)}bytes): {type(e).__name__}: {e}", exc_info=True)
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
        logger.warning(f"缩略图生成失败: {e}", exc_info=True)


def ensure_missing_thumbnails() -> dict:
    """为主图补齐缺失的缩略图（幂等）。

    [新增 2026-09-17] 背景：维修照片（repair/）与巡检照片（inspection/）的上传接口
    早期只把原图写盘、未生成 thumb_ 缩略图；而前端 SafeImage 统一按 thumb_ 路径请求，
    于是每次展示都要「先 404 → 再回退原图」，既产生控制台噪声，又白白多下载一张大图。

    上传接口已修复（新增照片会一并生成缩略图），本函数用于**补齐存量文件**。

    规则：
    - 跳过 thumb_ / orig_ 派生文件（它们自身不是主图）；
    - 跳过 _chunks（分片上传临时目录）与 richtext（富文本正文图片，
      由 HTML 直接引用原图，无缩略图诉求）；
    - 只处理位图扩展名；SVG 为矢量图，按既有约定不生成位图缩略图；
    - 幂等：已有缩略图的主图只做一次 stat 判断，不会重复生成、不产生写入；
    - 单张失败不影响其它文件（generate_thumbnail 内部已兜底，此处再加一层）。

    返回 {"scanned": 扫描的主图数, "generated": 补齐数, "failed": 失败数}
    """
    stats = {"scanned": 0, "generated": 0, "failed": 0}
    upload_root = Path(UPLOAD_ROOT)
    if not upload_root.is_dir():
        return stats

    for file_path in upload_root.rglob("*"):
        if not file_path.is_file():
            continue
        name = file_path.name
        if name.startswith("thumb_") or name.startswith(ORIG_PREFIX):
            continue
        # 跳过临时/正文目录（与孤儿清理口径保持一致）
        rel_parts = file_path.relative_to(upload_root).parts
        if rel_parts and rel_parts[0] in ("_chunks", "richtext"):
            continue
        if file_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue  # 含 .svg：矢量图不生成位图缩略图

        stats["scanned"] += 1
        absolute = str(file_path)
        if os.path.exists(get_thumbnail_path(absolute)):
            continue
        try:
            generate_thumbnail(absolute)
            if os.path.exists(get_thumbnail_path(absolute)):
                stats["generated"] += 1
            else:
                stats["failed"] += 1
        except Exception as e:
            stats["failed"] += 1
            logger.warning(f"补齐缩略图失败 {file_path}: {e}", exc_info=True)
    return stats


# ====== 孤儿图片清理 ======

def build_referenced_set(db) -> set[str]:
    """构建数据库中所有表引用的图片路径集合。
    
    用于备份恢复后清理"磁盘有、数据库无"的孤儿图片。
    遍历所有涉及图片存储的模型字段，收集非空的相对路径。
    
    Returns:
        被引用的相对路径集合（如 {"doctor/xxx.jpg", "dept/yyy.jpg"}）
    """
    from app.models.staff import Staff
    from app.models.department import Department
    from app.models.staff_card import StaffCard

    referenced: set[str] = set()

    # 1. 人员正面/侧面照
    #
    # [修正 2026-09-22] 原先这里遍历 `(Staff, Doctor, Nurse)` 三个模型 ——
    # Doctor / Nurse 是项目早期的**独立人员模型**，后来人员已统一到 staff 表，
    # 这两个模型不再被 models/__init__.py 导出（属废弃代码），但此处仍在引用。
    #
    # 后果具有欺骗性：`from app.models.doctor import Doctor` 本身能成功（文件还在），
    # 而**老库里恰好留有历史表** doctors/nurses，于是查询也能跑通 —— 直到在
    # 不含这两张表的库（如新建的测试库）上运行，才抛 `no such table: nurses`。
    # 表现为"删除员工失败 / 图片清理任务失败"，但错误信息完全指向不了真正的原因。
    #
    # 现在只查 staff 表 —— 它是人员数据的唯一来源，前两者已无数据写入。
    for row in db.query(Staff.front_photo, Staff.side_photo).all():
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

    # [修复 2026-09-21 / 存储审计 D-1] 7. 补齐四类此前遗漏的图片引用。
    #
    # ⚠️ 这是一个**已造成数据丢失**的缺陷，不是潜在风险：
    #    清理任务按「磁盘有、引用集合无 → 删除」判定孤儿，而下面这些字段此前
    #    不在引用集合中，于是它们引用的文件**每天凌晨都会被当作孤儿物理删除**，
    #    且 uploads/ 不在备份范围内（见存储审计 D-4），删后无法恢复。
    #
    #    受影响目录与字段：
    #      uploads/inspection/ ← SignageInspection.photo（巡检现场照片）
    #      uploads/repair/     ← SignageRepair.repair_photo / repair_photo_before
    #                            （维修完成照 / 维修前照）
    #      uploads/files/      ← DesignFile.stored_path（文件库当前版本）
    #                            DesignFileVersion.stored_path（历史版本）
    #
    # ⚠️ 维护提示：**今后任何新增「存图片/文件相对路径」的模型字段，都必须在此登记**，
    #    否则会重现本问题。下方 delete_orphan_files 中的「目录级异常保护」是为此
    #    类遗漏准备的兜底防线（大批量误判时会拒绝执行并告警），但它只是保险，
    #    不能替代正确登记。
    from app.models.signage import SignageInspection, SignageRepair
    for row in db.query(SignageInspection.photo).all():
        if row.photo:
            referenced.add(row.photo)
    for row in db.query(SignageRepair.repair_photo, SignageRepair.repair_photo_before).all():
        if row.repair_photo:
            referenced.add(row.repair_photo)
        if row.repair_photo_before:
            referenced.add(row.repair_photo_before)

    # 文件库（设计文件）当前版本与历史版本。stored_path 存的是相对 uploads 的路径，
    # 与 referenced 集合口径一致（如 signage/南-XX-0-001_design_2026...ai）。
    from app.models.design_file import DesignFile, DesignFileVersion
    for row in db.query(DesignFile.stored_path).all():
        if row.stored_path:
            referenced.add(row.stored_path)
    for row in db.query(DesignFileVersion.stored_path).all():
        if row.stored_path:
            referenced.add(row.stored_path)

    return referenced


def delete_orphan_files(referenced: set[str]) -> dict:
    """删除磁盘上存在但数据库不引用的孤儿图片及对应缩略图。

    [改进] 关联文件孤儿清理：扫描所有 thumb_* / orig_* 文件，若其对应的正式图路径
    不在 referenced 集合中，则一并删除。解决备份恢复后缩略图/原始副本残留的问题。

    [重构 2026-09-21 / 存储审计 D-1] 由「边扫边删」改为「三阶段：收集 → 审查 → 删除」，
    并加两道安全阀。原因是该函数此前**已造成数据丢失**：build_referenced_set 漏登记
    几个图片字段，导致它们引用的文件每天被当作孤儿删除，而 uploads 不在备份范围内。

    两道安全阀（都是为「引用集合不完整」这一根本脆弱性准备的兜底，不能替代正确登记）：

      ① 新文件保护期（NEW_FILE_GRACE_HOURS）：跳过 mtime 在 24 小时内的文件。
         上传流程是「文件先落盘、数据库记录后提交」，清理恰在窗口内运行会删掉
         刚上传的照片；保护期同时给"误判"留出人工发现的缓冲（存储审计 D-9）。

      ② 目录级异常保护（_abnormal_dirs）：若某目录下**过半**待删且待删数 ≥ 10，
         判定为异常，**整个目录跳过不删**并告警。
         理由：漏登记字段的典型表现就是"某一类文件被整批误判"。单看总量不易察觉，
         但按目录看会非常明显（如 uploads/repair/ 下 30 个文件全被判为孤儿）。
         此时宁可少清理（残留占磁盘）也不能错删（数据不可恢复）。

    Args:
        referenced: 数据库引用的相对路径集合（由 build_referenced_set 生成）

    Returns:
        清理统计信息 {deleted, thumbs_deleted, origs_deleted, total_orphans,
        total_bytes_freed, skipped_dirs, skipped_by_age}
    """
    upload_root = Path(UPLOAD_ROOT)
    if not upload_root.is_dir():
        return {
            "deleted": 0, "thumbs_deleted": 0, "origs_deleted": 0,
            "total_orphans": 0, "total_bytes_freed": 0,
            "skipped_dirs": [], "skipped_by_age": 0,
        }

    # 保护期阈值：24 小时。用时间戳比较，避免依赖文件系统时区处理。
    grace_seconds = NEW_FILE_GRACE_HOURS * 3600
    now_ts = _time.time()

    # ── 阶段 1：扫描并收集待删候选（此阶段不删除任何文件）──
    # 元组结构：(相对路径, 绝对路径 Path, 类别, 文件大小)
    #   类别取值 "main" | "thumb" | "orig"
    candidates: list[tuple[str, Path, str, int]] = []
    dir_total: dict[str, int] = {}  # 各目录下的图片文件总数（用于计算待删比例）
    skipped_by_age = 0

    for file_path in upload_root.rglob("*"):
        if not file_path.is_file():
            continue

        relative = str(file_path.relative_to(upload_root)).replace("\\", "/")
        # 跳过 _chunks（分片上传临时）与 richtext（富文本正文图片，HTML 内引用、
        # 无法纳入引用集合）目录，避免误删
        if relative.startswith("_chunks") or relative.startswith("richtext"):
            continue

        # 只处理图片类型文件（跳过 .gitkeep、设计文件库里的 .ai/.psd 等非图片 ——
        # 那些由数据库引用直接管理，不参与图片孤儿判定）
        ext = file_path.suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            continue

        dir_part = os.path.dirname(relative) or "."
        dir_total[dir_part] = dir_total.get(dir_part, 0) + 1

        # ── 安全阀 ①：新文件保护期 ──
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            continue  # 取不到状态就跳过（宁可少清理）
        if now_ts - mtime < grace_seconds:
            skipped_by_age += 1
            continue

        name = file_path.name
        rel_prefix = f"{dir_part}/" if dir_part != "." else ""

        # [改进] 前缀判断基于文件名（缩略图/原始副本与正式图同目录），
        # 旧实现用 relative.startswith 判断，对 doctor/thumb_x.jpg 这类带目录前缀的文件不命中，
        # 导致缩略图被当孤儿误删、orig_ 副本也会被误删。现按 basename 前缀识别并正确派生主图相对路径。
        kind: str | None = None
        if name.startswith("thumb_"):
            # 缩略图：其对应正式图被引用则保留
            main_relative = f"{rel_prefix}{name[len('thumb_'):]}"
            if main_relative not in referenced:
                kind = "thumb"
        elif name.startswith(ORIG_PREFIX):
            # 原始副本：扩展名可能与正式图不同（原图 PNG/WebP），按文件名主干匹配
            main_stem = os.path.splitext(name[len(ORIG_PREFIX):])[0]
            main_prefix = f"{rel_prefix}{main_stem}"
            is_referenced = any(
                r == main_prefix or r.startswith(main_prefix + ".") for r in referenced
            )
            if not is_referenced:
                kind = "orig"
        elif relative not in referenced:
            kind = "main"

        if kind is None:
            continue  # 被正常引用，保留

        try:
            size = file_path.stat().st_size
        except OSError:
            size = 0
        candidates.append((relative, file_path, kind, size))

    # ── 阶段 2：目录级异常保护 ──
    # 按目录分组统计，识别"整批被判定为孤儿"的可疑目录。
    from collections import defaultdict
    by_dir: dict[str, list[tuple[str, Path, str, int]]] = defaultdict(list)
    for item in candidates:
        by_dir[os.path.dirname(item[0]) or "."].append(item)

    skipped_dirs: list[str] = []
    to_delete: list[tuple[str, Path, str, int]] = []
    for dir_name, items in by_dir.items():
        total = dir_total.get(dir_name, len(items))
        # 触发条件：待删数 ≥ 10 且占比过半。两个条件同时满足才认定异常，
        # 避免把"某目录本来就只有两三个废弃文件"误判为异常而长期不清理。
        if len(items) >= _ABNORMAL_DIR_MIN_COUNT and len(items) * 2 > total:
            skipped_dirs.append(f"{dir_name}({len(items)}/{total})")
            logger.warning(
                "孤儿清理：目录 %s 中 %d/%d 个文件被判定为孤儿，比例异常，"
                "已跳过该目录以避免误删。请核查 build_referenced_set 是否漏登记了"
                "引用该目录文件的模型字段。",
                dir_name, len(items), total,
            )
            continue
        to_delete.extend(items)

    # ── 阶段 3：执行删除 ──
    orphan_count = orphan_thumb_count = orphan_orig_count = 0
    freed_bytes = 0

    for relative, file_path, kind, size in to_delete:
        try:
            file_path.unlink()
        except OSError as e:
            logger.warning(f"删除孤儿文件失败 {relative}: {e}", exc_info=True)
            continue

        freed_bytes += size
        if kind == "thumb":
            orphan_thumb_count += 1
            logger.debug(f"已删除孤儿缩略图: {relative} ({size} bytes)")
        elif kind == "orig":
            orphan_orig_count += 1
            logger.debug(f"已删除孤儿原始副本: {relative} ({size} bytes)")
        else:
            orphan_count += 1
            logger.debug(f"已删除孤儿图片: {relative} ({size} bytes)")

            # 同时删除对应的缩略图和原始副本（它们可能已在候选列表中，
            # 此处用 unlink(missing_ok=True) 兼容两种情形，避免重复计数）
            for companion in (
                file_path.parent / f"thumb_{file_path.name}",
                file_path.parent / f"{ORIG_PREFIX}{file_path.name}",
            ):
                try:
                    if companion.exists():
                        companion.unlink()
                except OSError as e:
                    logger.warning(f"删除关联文件失败 {companion.name}: {e}", exc_info=True)

    total_deleted = orphan_count + orphan_thumb_count + orphan_orig_count
    # [适配 新增] 循环内降为 DEBUG，此处汇总一条 INFO（含安全阀触发情况）
    if total_deleted or skipped_dirs or skipped_by_age:
        logger.info(
            f"孤儿图片清理完成: 删除 {orphan_count} 张原图 + {orphan_thumb_count} 张缩略图 "
            f"+ {orphan_orig_count} 张原始副本, 释放 {freed_bytes} bytes"
            + (f"; 保护期内跳过 {skipped_by_age} 个新文件" if skipped_by_age else "")
            + (f"; ⚠️ 因比例异常跳过目录 {skipped_dirs}" if skipped_dirs else "")
        )
    return {
        "deleted": orphan_count,
        "thumbs_deleted": orphan_thumb_count,
        "origs_deleted": orphan_orig_count,
        "total_orphans": total_deleted,
        "total_bytes_freed": freed_bytes,
        "skipped_dirs": skipped_dirs,
        "skipped_by_age": skipped_by_age,
    }
