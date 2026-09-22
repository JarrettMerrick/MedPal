# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import os
import secrets
import logging
from pydantic_settings import BaseSettings
from pathlib import Path

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# 项目根目录（config.py → app → backend → 项目根）
# [改进] 使用 __file__ 计算绝对路径，确保不依赖当前工作目录(CWD)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# backend 目录（源码布局与镜像布局一致：源码 <根>/backend，镜像 /app/backend）
BACKEND_DIR = Path(__file__).resolve().parent.parent

# [数据分离存储] 所有数据文件（数据库 / 上传附件 / 打包图片 / 备份 / 日志）
# 必须统一且独立地存放在「项目根目录下的 data 文件夹」，严禁写入 backend 文件夹。
#
# 布局自适应：
#   - 源码/本地开发布局：backend/ 与 data/ 同级 → DATA_ROOT = PROJECT_ROOT/data
#   - 镜像布局（Dockerfile）：代码位于 /app/backend（PROJECT_ROOT = /app），
#       数据由卷挂载在 /app/data → 同上规则命中 PROJECT_ROOT/data
#   - 兜底：若 backend 被压平到 /app（PROJECT_ROOT = 根目录）→ DATA_ROOT = BACKEND_DIR/data
# 亦支持通过环境变量 DATA_ROOT 显式覆盖（docker-compose 已设为 /app/data）。
_ENV_DATA_ROOT = os.getenv("DATA_ROOT")
if _ENV_DATA_ROOT:
    DATA_ROOT = Path(_ENV_DATA_ROOT)
elif (PROJECT_ROOT / "backend").is_dir():
    DATA_ROOT = PROJECT_ROOT / "data"      # 源码/本地开发布局
else:
    DATA_ROOT = BACKEND_DIR / "data"       # Docker 容器布局（/app/data）


class Settings(BaseSettings):
    """应用配置，所有值均可通过环境变量或 .env 文件覆盖"""

    # [品牌统一 2026-09-16] 默认应用名称统一为 MedPal；
    # 与 .env.example / README 中 APP_NAME 的默认值保持一致
    app_name: str = "MedPal信息管理系统"

    # 数据库 - 默认指向数据根目录下的 medical.db（与 backend 完全隔离）
    # 镜像中由 DATA_ROOT（/app/data）推导为 /app/data/medical.db；
    # 如需指向其它位置，可用环境变量 DATABASE_URL 覆盖
    database_url: str = f"sqlite:///{(DATA_ROOT / 'medical.db').as_posix()}"

    # [改进/部署] SQLite WAL 模式开关（默认开启）
    # - True：启用 WAL 模式（Linux 生产环境推荐，读写并发好）
    # - False：回退为 DELETE 日志模式（Windows Docker Desktop 挂载 NTFS 卷时
    #    WAL 会触发 "disk I/O error"，必须关闭；本地 compose 已设置该变量）
    sqlite_wal_enabled: bool = True

    # JWT 认证
    secret_key: str = "your-secret-key-change-in-production-2024"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60
    remember_me_refresh_token_expire_days: int = 3

    # 新建账号初始口令
    # [调整 2026-09-10] 初始口令改为由「账号设置」中的模板生成
    # （配置项 default_password_template，见 services/system_config_service.py；
    #  auth_service.get_default_password 读取并支持 {工号} 占位符），
    # 未配置时回退 MedPal@2026。保留本字段仅为兼容 .env 中既有的
    # DEFAULT_PASSWORD 键（避免历史配置引发解析错误）。
    default_password: str = "MedPal@2026"

    # CORS 跨域（逗号分隔的字符串，运行时解析为列表）
    cors_origins: str = "http://localhost:3000"

    # 文件上传
    # [改进/F3] 默认值由 10 改为 20，与 upload_service 实际生效的限制一致；
    # 该值现已被 upload_service.MAX_FILE_SIZE 真正引用（原先是死配置）。
    upload_max_size_mb: int = 20
    upload_allowed_types: str = "image/jpeg,image/png,image/gif,image/webp"

    # 日志 - 默认路径，实际使用时会在main.py中动态计算
    log_level: str = "INFO"
    log_file: str = ""  # 留空，由main.py动态设置为data/logs/hospital.log

    # 备份（每日凌晨一次；[修复] backup_max_count 已被 backup_service.MAX_BACKUPS 真正引用，
    # 运维可通过 .env 的 BACKUP_MAX_COUNT 调整保留数量，默认 7 个 = 最近 7 天）
    backup_enabled: bool = True
    backup_max_count: int = 7

    # 环境
    environment: str = "development"

    class Config:
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origins_list(self) -> list[str]:
        """将逗号分隔的 CORS 来源字符串解析为列表"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_allowed_types_list(self) -> list[str]:
        """将逗号分隔的允许文件类型字符串解析为列表"""
        return [t.strip() for t in self.upload_allowed_types.split(",") if t.strip()]


settings = Settings()

# 安全检查（C1 修复）：无论何种环境，只要 SECRET_KEY 仍是代码内置的公开默认值，
# 一律禁止启动，强制通过 .env 的 SECRET_KEY 注入真实随机密钥。
# 原实现仅在 environment != "development" 时拦截，而 .env 默认 ENVIRONMENT=development，
# 导致安全网形同虚设——漏配强密钥时会用公开默认密钥静默启动，token 可被任意伪造。
DEFAULT_SECRET_KEY = "your-secret-key-change-in-production-2024"
if settings.secret_key == DEFAULT_SECRET_KEY:
    raise RuntimeError(
        "JWT SECRET_KEY 仍为代码内置的公开默认值，禁止启动。"
        " 请在项目根目录的 .env 文件中设置随机密钥："
        "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

if settings.environment == "development":
    logger.warning(
        "⚠ 当前以 development 环境运行（仅供本地开发）。"
        " 生产部署请将 .env 中的 ENVIRONMENT 改为 production。"
    )
