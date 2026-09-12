# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.system_config import SystemConfig

logger = logging.getLogger("system_config")

# ── 品牌（单位信息）配置 key ──────────────────────────────────────
# [新增 2026-09-10] 系统设置模块：单位名称（中/英）、系统名称与单位 Logo 公开访问路径。
# 数据仍复用 system_configs 表（key/value），无需新建表与数据迁移。
ORG_NAME_CN_KEY = "org_name_cn"
ORG_NAME_EN_KEY = "org_name_en"
SYSTEM_NAME_KEY = "system_name"
ORG_LOGO_URL_KEY = "org_logo_url"
BRANDING_NAME_KEYS = frozenset({ORG_NAME_CN_KEY, ORG_NAME_EN_KEY, SYSTEM_NAME_KEY})
BRANDING_CONFIG_KEYS = frozenset({
    ORG_NAME_CN_KEY, ORG_NAME_EN_KEY, SYSTEM_NAME_KEY, ORG_LOGO_URL_KEY,
})

# ── 账号设置配置 key ──────────────────────────────────────────────
# [新增 2026-09-10] 账号设置模块：新建账号默认口令模板 + 登录页注册开关。
DEFAULT_PASSWORD_TEMPLATE_KEY = "default_password_template"
REGISTRATION_ENABLED_KEY = "registration_enabled"
# 口令模板为空时的内置回退值（未配置即使用它）
DEFAULT_PASSWORD_TEMPLATE_FALLBACK = "MedPal@2026"
# 口令模板长度上限
DEFAULT_PASSWORD_TEMPLATE_MAX_LEN = 50
# 读取需 system.config 权限的敏感配置项：
# 口令模板直接决定所有新建账号的初始口令，不能对任意登录用户开放读取。
SENSITIVE_READ_KEYS = frozenset({DEFAULT_PASSWORD_TEMPLATE_KEY})

# [改进/S1] 系统配置 key 白名单：唯一的合法配置项来源，防止凭空创建任意 key
# 污染业务逻辑或制造无限行。新增配置项时需在此登记。
ALLOWED_CONFIG_KEYS = frozenset({
    "data_sync_notice",  # 数据同步说明（首页展示文案）
    ORG_NAME_CN_KEY,     # 单位名称（中文）
    ORG_NAME_EN_KEY,     # 单位名称（英文）
    SYSTEM_NAME_KEY,     # 系统名称（登录页/首页展示，可自定义）
    ORG_LOGO_URL_KEY,    # 单位 Logo 公开访问路径
    DEFAULT_PASSWORD_TEMPLATE_KEY,  # 新建账号默认口令模板
    REGISTRATION_ENABLED_KEY,       # 登录页注册开关
})

# [新增 2026-09-10] 按 key 的长度上限（未列出者使用 MAX_CONFIG_VALUE_LEN）
KEY_MAX_LENGTH = {
    ORG_NAME_CN_KEY: 100,
    ORG_NAME_EN_KEY: 150,
    SYSTEM_NAME_KEY: 100,
    ORG_LOGO_URL_KEY: 255,
    DEFAULT_PASSWORD_TEMPLATE_KEY: DEFAULT_PASSWORD_TEMPLATE_MAX_LEN,
}

# 名称类配置需剔除 HTML 标签与控制字符（防止在页面/标题中注入标签）
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# [改进/S1] 配置值最大长度，防止写入超长字符串造成存储/渲染 DoS
# [改进/2026-07-15] 2000 对于富文本编辑器生成的 HTML 源码（含标签）偏小，
# 公告栏富文本内容易超限导致保存失败。上调至 5000，兼顾安全与可用性。
# [改进/2026-09-10] 公告栏需承载长篇内容，5000 仍频繁超限，按需求上调至 50000。
# 注意：该上限作用于 **所有** 系统配置项（config_value 为 TEXT 列，无数据库层限制），
# 若后续需要对特定项单独限流，请在此处按 config_key 分支判断。
MAX_CONFIG_VALUE_LEN = 50000


def is_allowed_config_key(key: str) -> bool:
    """判断配置 key 是否在白名单内"""
    return key in ALLOWED_CONFIG_KEYS


def validate_config_value(key: str, value: Optional[str]) -> str:
    """按配置 key 规范化并校验取值，返回清洗后的值；不合规抛 ValueError。

    [新增 2026-09-10] 供 PUT /api/system-config/{key} 调用：
      - 单位名称（中/英）：剔除 HTML 标签与控制字符、去首尾空白，再按 key 限长；
      - Logo 路径 / 其他配置（如公告富文本）：保持原样，仅做总长度上限校验。
    """
    raw = "" if value is None else str(value)
    if key in BRANDING_NAME_KEYS:
        cleaned = _CONTROL_CHAR_RE.sub("", _HTML_TAG_RE.sub("", raw)).strip()
        limit = KEY_MAX_LENGTH[key]
        if len(cleaned) > limit:
            raise ValueError(f"名称长度超过限制（最多 {limit} 字符）")
        return cleaned
    if key == DEFAULT_PASSWORD_TEMPLATE_KEY:
        # 口令模板：允许为空（表示使用内置默认），支持 {工号} 占位符
        cleaned = _CONTROL_CHAR_RE.sub("", _HTML_TAG_RE.sub("", raw)).strip()
        if len(cleaned) > DEFAULT_PASSWORD_TEMPLATE_MAX_LEN:
            raise ValueError(f"口令模板长度超过限制（最多 {DEFAULT_PASSWORD_TEMPLATE_MAX_LEN} 字符）")
        # 生成结果不足 6 位会让新账号得到弱口令，直接拒绝
        if cleaned and len(cleaned.replace("{工号}", "000000")) < 6:
            raise ValueError("口令模板过短：生成的口令至少需要 6 个字符")
        return cleaned
    if key == REGISTRATION_ENABLED_KEY:
        # 开关：统一规范化为 "1"/"0"
        return "1" if raw.strip().lower() in ("1", "true", "on", "yes") else "0"
    if len(raw) > MAX_CONFIG_VALUE_LEN:
        raise ValueError(f"配置值长度超过限制（最多 {MAX_CONFIG_VALUE_LEN} 字符）")
    return raw


def get_config(db: Session, key: str) -> Optional[SystemConfig]:
    """获取配置"""
    return db.query(SystemConfig).filter(SystemConfig.config_key == key).first()


def get_config_value(db: Session, key: str, default: str = "") -> str:
    """获取配置值"""
    config = get_config(db, key)
    return config.config_value if config and config.config_value else default


def update_config(db: Session, key: str, value: str, updated_by: str, description: str = "") -> SystemConfig:
    """更新配置"""
    config = get_config(db, key)
    if config:
        config.config_value = value
        config.updated_by = updated_by
    else:
        config = SystemConfig(
            config_key=key,
            config_value=value,
            description=description,
            updated_by=updated_by,
        )
        db.add(config)
    db.flush()
    db.commit()
    return config


def init_default_configs(db: Session):
    """初始化默认配置"""
    defaults = [
        # [调整 2026-09-10] 「数据同步说明」不再预置任何文案：
        # 原「每月最后一个工作日快照 + 次月10日前迁移至 HIS 系统」的默认公告已按要求删除。
        # 为空时首页公告栏显示占位文案「暂无公告」，由管理员按需自行填写。
        {"key": "data_sync_notice", "value": "", "description": "数据同步说明"},
        # [新增 2026-09-10] 品牌配置项：名称类默认留空，前端在为空时回退到内置默认文案；
        # 系统名称默认取 settings.app_name（即原有固定值），保证改造前后显示一致。
        {"key": ORG_NAME_CN_KEY, "value": "", "description": "单位名称（中文）"},
        {"key": ORG_NAME_EN_KEY, "value": "", "description": "单位名称（英文）"},
        {"key": SYSTEM_NAME_KEY, "value": settings.app_name, "description": "系统名称"},
        {"key": ORG_LOGO_URL_KEY, "value": "", "description": "单位 Logo 公开访问路径"},
        # [新增 2026-09-10] 账号设置：默认口令模板（预置为内置默认值，便于管理员查看/修改）
        # 与登录页注册开关（默认关闭，避免改变现有登录页行为）
        {"key": DEFAULT_PASSWORD_TEMPLATE_KEY, "value": DEFAULT_PASSWORD_TEMPLATE_FALLBACK,
         "description": "新建账号默认口令模板（支持 {工号} 占位符）"},
        {"key": REGISTRATION_ENABLED_KEY, "value": "0", "description": "登录页注册开关（1 开 / 0 关）"},
    ]
    for item in defaults:
        existing = get_config(db, item["key"])
        if not existing:
            config = SystemConfig(
                config_key=item["key"],
                config_value=item["value"],
                description=item["description"],
                updated_by="system",
            )
            db.add(config)
    db.flush()

    # [调整 2026-09-10] 清理历史遗留的默认公告：早期版本启动时会自动写入
    # 「每月末快照 / 次月10日前迁移至 HIS 系统」文案。该文案已按要求删除，
    # 此处仅在取值与旧默认文案**完全一致**时清空（即从未被人工编辑过），
    # 不会覆盖管理员已自行填写或修改过的公告内容。
    _LEGACY_DEFAULT_NOTICE = (
        "系统将于每月最后一个工作日对数据进行快照，"
        "并于次月10日前完成数据迁移至HIS系统。此过程无需您手动联系信息部更改。"
    )
    notice_cfg = get_config(db, "data_sync_notice")
    if notice_cfg is not None and (notice_cfg.config_value or "").strip() == _LEGACY_DEFAULT_NOTICE:
        notice_cfg.config_value = ""
        notice_cfg.updated_by = "system"
        logger.info("已清空历史默认公告（原 HIS 数据迁移说明），公告栏将显示「暂无公告」")