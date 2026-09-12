# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger("database")


def ensure_sqlite_dir(url: str) -> None:
    """确保 SQLite 数据库文件所在目录存在。

    [新增 2026-09-10] 首次部署时 data/ 目录可能尚不存在，
    若不预先创建，引擎建立连接时会直接报 "unable to open database file"。
    此处只负责建目录；数据库文件本身由 SQLAlchemy 首次连接时自动创建。
    """
    if not url.startswith("sqlite:///"):
        return
    db_path = url[len("sqlite:///"):]
    if not db_path or db_path == ":memory:":
        return
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir and not os.path.isdir(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info("数据库目录不存在，已自动创建: %s", db_dir)


ensure_sqlite_dir(settings.database_url)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
    # [改进/1.0.9] SQLite 连接池优化参数
    #   - pool_size: 连接池常驻连接数（SQLite 写操作串行化，5-10 足够）
    #   - max_overflow: 峰值时可额外创建的连接数
    #   - pool_timeout: 获取连接的最大等待时间（秒），防止请求无限阻塞
    #   - pool_recycle: 连接回收时间（秒），防止 stale connection 导致的查询异常
    #   - pool_pre_ping: 使用连接前自动检测有效性，避免因 SQLite 锁导致的静默失败
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)


# [改进] 使用 connect 事件监听器，确保每个新连接都自动设置 PRAGMA
# 原方案仅在启动时设置一次，busy_timeout/synchronous/foreign_keys 等会话级参数不会继承
@event.listens_for(engine, "connect")
def _set_connection_pragma(dbapi_connection, connection_record):
    """每个新数据库连接自动设置 SQLite PRAGMA 参数

    [改进/部署] journal_mode 由 settings.sqlite_wal_enabled 控制：
    - 开启：WAL 模式（Linux 生产环境）
    - 关闭：DELETE 模式（Windows Docker Desktop 挂载卷，WAL 会报 disk I/O error）
    """
    cursor = dbapi_connection.cursor()
    if settings.sqlite_wal_enabled:
        cursor.execute("PRAGMA journal_mode=WAL")        # 持久化，显式设置无害
    else:
        cursor.execute("PRAGMA journal_mode=DELETE")     # Windows Docker 挂载卷回退模式
    cursor.execute("PRAGMA busy_timeout=5000")        # 写锁等待 5 秒而非立即报 database is locked
    cursor.execute("PRAGMA synchronous=NORMAL")       # 平衡速度与安全性
    cursor.execute("PRAGMA foreign_keys=ON")          # 外键约束
    cursor.execute("PRAGMA cache_size=-8000")         # 缓存 8MB（默认 -2000=2MB）
    cursor.execute("PRAGMA temp_store=MEMORY")        # 临时表放内存，减少磁盘 I/O
    cursor.close()


def register_engine_pragma_events(target_engine):
    """为指定引擎注册 connect 事件，确保每个连接都应用 PRAGMA。
    
    适用场景：restore_backup 重建引擎后需重新注册事件监听器。
    
    Args:
        target_engine: SQLAlchemy Engine 对象
    """
    @event.listens_for(target_engine, "connect")
    def _pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # [改进/部署] 与 _set_connection_pragma 保持一致，受 sqlite_wal_enabled 控制
        if settings.sqlite_wal_enabled:
            cursor.execute("PRAGMA journal_mode=WAL")
        else:
            cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=-8000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


def init_database():
    """启动时数据库初始化：确保 journal 模式持久化并创建表结构

    [改进/部署] journal 模式由 settings.sqlite_wal_enabled 决定，
    与 connect 事件监听器保持一致。
    """
    journal_mode = "WAL" if settings.sqlite_wal_enabled else "DELETE"
    with engine.connect() as conn:
        conn.execute(text(f"PRAGMA journal_mode={journal_mode}"))
        conn.commit()
    logger.info("SQLite PRAGMA 已通过 connect 事件监听器自动应用到所有连接")
    logger.info(f"SQLite 配置: {journal_mode}模式, busy_timeout=5000ms, synchronous=NORMAL, cache_size=8MB, temp_store=MEMORY")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
