# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""单位品牌信息（单位名称 / 单位 Logo）服务。

设计要点：
- 数据复用现有 `system_configs` 表（key/value），**无需新建表与数据迁移**；
- Logo 文件落在**公开**静态目录 `data/public/brand`（挂载为 `/public`）：
  登录页是未认证页面，而 `/uploads` 受鉴权中间件保护，复用会导致 403/404；
- 文件名 = 内容哈希 + 时间戳，内容变化即换名，天然规避浏览器缓存；
- 单位名称在写入侧已由 `system_config_service.validate_config_value`
  剔除 HTML 标签与控制字符，读取侧无需再处理。
"""

import hashlib
import io
import logging
import os
import re

from fastapi import HTTPException
from PIL import Image
from sqlalchemy.orm import Session

from app.config import DATA_ROOT, settings
from app.models.system_config import SystemConfig
from app.services.system_config_service import (
    BRANDING_CONFIG_KEYS,
    ORG_LOGO_URL_KEY,
    ORG_NAME_CN_KEY,
    ORG_NAME_EN_KEY,
    ORG_SLOGAN_KEY,
    SYSTEM_NAME_KEY,
    get_config_value,
    update_config,
)
from app.services.upload_service import detect_image_format
# [统一时间口径] API 时间字段统一用 to_iso_utc（带 Z 的 UTC），前端按浏览器时区转换显示
from app.utils import utc_now, to_iso_utc

logger = logging.getLogger("branding")

# 公开静态目录：data/public → 挂载为 /public（见 main.py）
PUBLIC_URL_PREFIX = "/public"
BRAND_SUB_DIR = "brand"
BRAND_DIR = os.path.join(str(DATA_ROOT), "public", BRAND_SUB_DIR)

# Logo 约束（与需求确认一致）：仅位图、≤2MB、最小边 ≥64px
LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MIN_EDGE = 64
# 真实格式 → 落盘扩展名（由魔数检测结果决定，杜绝从原始文件名带入危险后缀）
LOGO_FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}

# 仅允许删除本服务生成的文件（防路径穿越/误删）
_LOGO_FILENAME_RE = re.compile(r"^logo_[0-9a-f]{8,64}_\d{14}\.(jpg|png|webp)$")


def ensure_brand_dir() -> None:
    """确保公开品牌目录存在（供启动时调用与保存前兜底）"""
    os.makedirs(BRAND_DIR, exist_ok=True)


def get_branding(db: Session) -> dict:
    """聚合读取品牌信息（公开接口使用）。

    返回：
        org_name_cn / org_name_en：单位名称，未配置为空字符串；
        system_name：系统名称（固定取 `settings.app_name`，不落库）；
        logo_url：Logo 公开路径，未配置为空字符串；
        slogan：宣传标语，未配置（或已被管理员清空）为空字符串，前端不渲染；
        updated_at：品牌配置最近更新时间（ISO 字符串，可能为 None）。
    """
    return {
        "org_name_cn": get_config_value(db, ORG_NAME_CN_KEY, ""),
        "org_name_en": get_config_value(db, ORG_NAME_EN_KEY, ""),
        # [调整 2026-09-10] 系统名称改为可在「系统设置」中自定义；
        # 未配置（为空）时回退到内置默认 settings.app_name，行为与改造前一致。
        "system_name": get_config_value(db, SYSTEM_NAME_KEY, "") or settings.app_name,
        "logo_url": get_config_value(db, ORG_LOGO_URL_KEY, ""),
        # [新增 2026-09-12] 宣传标语：空字符串表示管理员主动清空，前端据此隐藏。
        "slogan": get_config_value(db, ORG_SLOGAN_KEY, ""),
        "updated_at": _latest_updated_at(db),
    }


def _latest_updated_at(db: Session):
    """品牌相关配置项的最近更新时间"""
    rows = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key.in_(list(BRANDING_CONFIG_KEYS)))
        .all()
    )
    latest = max((r.updated_at for r in rows if r.updated_at), default=None)
    # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
    return to_iso_utc(latest)


def _probe_logo(content: bytes) -> str:
    """校验 Logo 文件并返回真实格式。不合规抛 HTTPException(400)。"""
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > LOGO_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Logo 文件过大，最大允许 {LOGO_MAX_BYTES // (1024 * 1024)}MB",
        )

    # 魔数校验（以内容真实格式为准，不信任 content_type / 扩展名）
    real_format = detect_image_format(content[:16])
    if real_format not in LOGO_FORMAT_EXT:
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPG / WebP 格式的图片")

    # 尺寸校验：verify 校验完整性（会失效句柄，故用两次 open）
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Logo 解析失败: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail="图片文件已损坏或无法解析")

    if min(width, height) < LOGO_MIN_EDGE:
        raise HTTPException(
            status_code=400,
            detail=f"图片尺寸过小，最小边需不小于 {LOGO_MIN_EDGE}px（当前 {width}×{height}）",
        )
    return real_format


def save_logo(db: Session, content: bytes, updated_by: str) -> dict:
    """保存单位 Logo：落盘公开目录 → 更新配置 → 清理旧文件（best-effort）。"""
    real_format = _probe_logo(content)
    ext = LOGO_FORMAT_EXT[real_format]

    ensure_brand_dir()
    digest = hashlib.sha256(content).hexdigest()[:16]
    stamp = utc_now().strftime("%Y%m%d%H%M%S")
    filename = f"logo_{digest}_{stamp}{ext}"
    abs_path = os.path.join(BRAND_DIR, filename)

    old_url = get_config_value(db, ORG_LOGO_URL_KEY, "")
    try:
        with open(abs_path, "wb") as f:
            f.write(content)
    except OSError as e:
        logger.error(f"Logo 落盘失败: {abs_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Logo 保存失败，请联系管理员")

    logo_url = f"{PUBLIC_URL_PREFIX}/{BRAND_SUB_DIR}/{filename}"
    update_config(
        db, ORG_LOGO_URL_KEY, logo_url,
        updated_by=updated_by, description="单位 Logo 公开访问路径",
    )
    # 新文件写入成功后再清理旧文件，失败不影响本次保存
    if old_url and old_url != logo_url:
        delete_logo_file(old_url)
    return {"logo_url": logo_url, "updated_at": _latest_updated_at(db)}


def reset_logo(db: Session, updated_by: str) -> dict:
    """重置为单位内置默认 Logo：清空配置并尽力删除已上传文件。"""
    old_url = get_config_value(db, ORG_LOGO_URL_KEY, "")
    update_config(
        db, ORG_LOGO_URL_KEY, "",
        updated_by=updated_by, description="单位 Logo 公开访问路径",
    )
    if old_url:
        delete_logo_file(old_url)
    return {"logo_url": "", "updated_at": _latest_updated_at(db)}


def delete_logo_file(logo_url: str) -> None:
    """尽力删除品牌目录下的 Logo 文件（best-effort，失败仅记日志）。

    安全：仅接受本服务生成的 `/public/brand/logo_<hash>_<ts>.<ext>` 路径，
    文件名经正则校验，杜绝通过构造路径删除任意文件。
    """
    if not logo_url or not logo_url.startswith(f"{PUBLIC_URL_PREFIX}/{BRAND_SUB_DIR}/"):
        return
    name = logo_url.rsplit("/", 1)[-1]
    if not _LOGO_FILENAME_RE.match(name):
        logger.warning(f"跳过删除非本服务生成的 Logo 文件: {logo_url}")
        return
    abs_path = os.path.join(BRAND_DIR, name)
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except OSError as e:
        logger.warning(f"删除旧 Logo 文件失败（非致命）: {abs_path}: {e}")
