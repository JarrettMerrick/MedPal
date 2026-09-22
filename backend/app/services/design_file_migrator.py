# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""存量设计文件迁移：把现有设计文件纳入文件库统一管理（幂等）。

[新增 2026-09-17] 需求：现有设计文件纳入文件库统一管理（决策 6）。

迁移范围与规则：
  1) `signages.design_photo` 非空的标识 → 按路径创建（或复用）DesignFile 记录，
     并回填 `signages.design_file_id`。**同路径的多条标识复用同一条文件记录**，
     与文件库「引用共享」模型一致（标准设计文件被多条标识共用）；
  2) 扫描 `uploads/signage/` 下的设计文件（文件名含 `_design_`）：
     未被任何标识引用的历史文件同样纳入文件库，避免"磁盘有文件、文件库看不到"；
  3) 迁移记录若存在同名标识分类（「存量设计文件」）则归入该分类，并打上「待整理」标签：
     原始文件名在旧落盘规则（`{编码}_design_{时间戳}_{随机}.ext`）中已不可考，
     需要人工核对后重命名；
  4) 时间与上传人取对应标识的 updated_at / updated_by（近似值，仅作参考）。

幂等：已存在（按 stored_path 匹配）的文件不会重复创建；重启可安全重跑。
由 app.main 启动流程调用，无存量数据时不产生任何写入。
"""

import logging
import os

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.design_file import DesignFile, DesignFileTag, DesignFileVersion, FileTag
from app.models.signage import Signage
from app.models.signage_settings import SignageCategory
from app.services.upload_service import UPLOAD_ROOT

logger = logging.getLogger("design_file_migration")

# 迁移文件统一归入的分类名称与标签（便于人工整理后重新归类）
# [调整 2026-09-17] 分类统一为「标识设置 → 标识分类」：此处按**名称匹配**已有标识分类，
# 不存在时留空（不再自动创建分类，避免绕过标识分类设置页私自建分类）。
MIGRATION_CATEGORY_NAME = "存量设计文件"
MIGRATION_TAG_NAME = "待整理"
MIGRATION_TAG_GROUP = "整理状态"

# 旧落盘命名中的设计文件标识段（{编码}_design_{时间戳}_{随机}.ext）
_DESIGN_MARKER = "_design_"

# 跳过的前缀（缩略图 / 原始副本）
_SKIP_PREFIXES = ("thumb_", "orig_")


def _ensure_tag(db: Session, name: str, group: str, color: str | None = None) -> FileTag:
    """按「维度 + 名称」查找或创建标签（幂等）"""
    tag = db.query(FileTag).filter(FileTag.name == name, FileTag.group_name == group).first()
    if tag:
        return tag
    tag = FileTag(name=name, group_name=group, color=color, created_by="system")
    db.add(tag)
    db.flush()
    return tag


def _absolute(stored_path: str) -> str:
    return os.path.join(UPLOAD_ROOT, stored_path or "")


def _file_size(stored_path: str) -> int | None:
    try:
        return os.path.getsize(_absolute(stored_path))
    except OSError:
        return None


def _guess_name(stored_path: str, signage: Signage | None) -> str:
    """推断显示名：优先用标识信息，其次用落盘文件名中的编码段"""
    if signage is not None and signage.code:
        base = f"{signage.code}-{signage.name}" if signage.name else str(signage.code)
        return f"{base}-设计文件"
    basename = os.path.basename(stored_path or "")
    code_part = basename.split(_DESIGN_MARKER)[0] if _DESIGN_MARKER in basename else os.path.splitext(basename)[0]
    return f"{code_part}-设计文件" if code_part else "设计文件"


def _ensure_record(db: Session, stored_path: str, category_id: int | None,
                   signage: Signage | None, extension_tag: FileTag) -> tuple[DesignFile, bool]:
    """按路径查找或创建 DesignFile 记录；返回 (记录, 是否新建)"""
    existing = db.query(DesignFile).filter(DesignFile.stored_path == stored_path).first()
    if existing:
        return existing, False

    ext = os.path.splitext(stored_path)[1].lower() or None
    record = DesignFile(
        name=_guess_name(stored_path, signage)[:200],
        stored_path=stored_path,
        file_ext=ext,
        file_size=_file_size(stored_path),
        mime_type=None,
        content_hash=None,  # 存量文件体积较大，迁移阶段跳过哈希计算
        is_standard=False,
        category_id=category_id,
        remark="由存量设计文件自动纳入文件库",
        uploader_id=getattr(signage, "updated_by", None),
        uploader_name=None,
        updated_by="system",
    )
    db.add(record)
    db.flush()
    db.add(DesignFileVersion(
        file_id=record.id, version=1, stored_path=stored_path,
        file_ext=ext, file_size=record.file_size,
        note="存量文件迁移", uploaded_by="system", uploaded_by_name="系统迁移",
    ))
    db.add(DesignFileTag(file_id=record.id, tag_id=extension_tag.id))
    return record, True


def migrate_design_files(db: Session) -> dict:
    """执行存量设计文件迁移（幂等）。返回各项计数。"""
    stats = {
        "linked_signages": 0,   # 回填了 design_file_id 的标识数
        "files_created": 0,     # 新建文件记录数
        "files_reused": 0,      # 复用已有记录数（引用共享）
        "orphans_added": 0,     # 纳入的孤儿文件（磁盘有、无人引用）
        "missing_files": 0,     # 记录存在但磁盘缺失
    }

    # 第一步：判断是否需要迁移（无存量设计文件时直接返回，不产生任何写入）
    has_any = db.query(Signage.id).filter(
        Signage.design_photo.isnot(None), Signage.design_photo != "",
    ).first()
    signage_dir = os.path.join(UPLOAD_ROOT, "signage")
    has_dir_files = os.path.isdir(signage_dir) and any(
        _DESIGN_MARKER in name and not name.startswith(_SKIP_PREFIXES)
        for name in os.listdir(signage_dir)
    )
    if not has_any and not has_dir_files:
        return stats

    # [调整 2026-09-17] 分类统一为标识分类：按名称匹配，不存在时留空
    category = (
        db.query(SignageCategory)
        .filter(SignageCategory.name == MIGRATION_CATEGORY_NAME)
        .first()
    )
    category_id = category.id if category else None
    extension_tag = _ensure_tag(db, MIGRATION_TAG_NAME, MIGRATION_TAG_GROUP, color="#FAAD14")

    # 第二步：按标识回填（同路径的多条标识复用同一记录 = 引用共享）
    signages = db.query(Signage).filter(
        Signage.design_photo.isnot(None), Signage.design_photo != "",
    ).all()
    for signage in signages:
        stored_path = (signage.design_photo or "").strip()
        if not stored_path:
            continue
        if not os.path.exists(_absolute(stored_path)):
            stats["missing_files"] += 1
            continue
        record, created = _ensure_record(db, stored_path, category_id, signage, extension_tag)
        stats["files_created" if created else "files_reused"] += 1
        if signage.design_file_id != record.id:
            signage.design_file_id = record.id
            stats["linked_signages"] += 1

    # 第三步：纳入未被引用的历史设计文件（磁盘有、数据库无人引用）
    known_paths = {
        path for (path,) in db.query(DesignFile.stored_path).all() if path
    }
    if os.path.isdir(signage_dir):
        for name in os.listdir(signage_dir):
            if name.startswith(_SKIP_PREFIXES) or _DESIGN_MARKER not in name:
                continue
            stored_path = f"signage/{name}"
            if stored_path in known_paths:
                continue
            if not os.path.isfile(os.path.join(signage_dir, name)):
                continue
            _, created = _ensure_record(db, stored_path, category_id, None, extension_tag)
            if created:
                stats["orphans_added"] += 1
                stats["files_created"] += 1

    changed = any(stats[key] for key in (
        "linked_signages", "files_created", "files_reused", "orphans_added",
    ))
    if changed:
        db.commit()
        logger.info("存量设计文件迁移完成：%s", stats)
    return stats


def migrate_category_foreign_key(db: Session) -> bool:
    """把 design_files.category_id 的外键由 file_categories 迁到 signage_categories（幂等）。

    [新增 2026-09-17] 背景：文件分类口径统一为「标识设置 → 标识分类」后，模型层的
    外键已改指 signage_categories；但 **SQLite 的表结构是建表时固化的**，
    磁盘上 design_files 的外键仍指向已废弃的 file_categories 表。由于项目在每个连接上
    开启了 `PRAGMA foreign_keys=ON`，给文件设置分类时会直接抛出：
        IntegrityError: FOREIGN KEY constraint failed
    （业务校验已通过 —— 分类在 signage_categories 中确实存在，是旧外键把它拒绝了）

    SQLite 不支持修改既有表的外键，按官方推荐做法重建表：
        CREATE 新表 → 复制数据 → DROP 旧表 → RENAME 新表 → 重建索引

    注意事项：
    - `PRAGMA foreign_keys` 只能在**事务外**修改，且仅对当前连接生效 → 使用独立连接；
    - 迁移期间必须关闭外键：design_file_tags / design_file_versions 有数据行引用本表，
      否则 DROP TABLE 会被外键约束拒绝；
    - DDL 放在显式事务中（BEGIN IMMEDIATE … COMMIT），失败可整体回滚；
    - 索引随 DROP TABLE 一并消失，按模型定义重建；
    - 幂等：表结构已指向 signage_categories（或表不存在）时直接返回 False，不产生写入。
    """
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return False  # 其它方言交由各自的迁移机制处理

    row = db.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='design_files'"
    )).fetchone()
    if not row or not row[0] or "file_categories" not in row[0]:
        return False  # 表不存在（新库由 create_all 直接建为新结构）或已是新结构

    columns = [c.name for c in DesignFile.__table__.columns]
    column_list = ", ".join(columns)
    # 由模型定义生成新表 DDL 与索引 DDL，保证结构与模型完全一致
    new_table_ddl = str(CreateTable(DesignFile.__table__).compile(bind)).replace(
        "CREATE TABLE design_files", "CREATE TABLE design_files__fk_migration", 1,
    )
    index_ddls = [str(CreateIndex(index).compile(bind)) for index in DesignFile.__table__.indexes]

    db.commit()  # 释放会话持有的写锁，避免与迁移连接互锁

    raw = bind.raw_connection()
    driver = getattr(raw, "driver_connection", None) or raw
    previous_isolation = getattr(driver, "isolation_level", None)
    try:
        # sqlite3 需在自动提交模式下执行 PRAGMA / 显式事务控制
        driver.isolation_level = None
        cursor = driver.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("BEGIN IMMEDIATE")
            try:
                cursor.execute(new_table_ddl)
                cursor.execute(
                    f"INSERT INTO design_files__fk_migration ({column_list}) "
                    f"SELECT {column_list} FROM design_files"
                )
                cursor.execute("DROP TABLE design_files")
                cursor.execute(
                    "ALTER TABLE design_files__fk_migration RENAME TO design_files"
                )
                for index_ddl in index_ddls:
                    cursor.execute(index_ddl)
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
            finally:
                cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    finally:
        # 归还连接前恢复隔离级别，避免影响连接池中的后续使用
        if previous_isolation is not None:
            driver.isolation_level = previous_isolation
        raw.close()

    logger.info("design_files 外键迁移完成：file_categories → signage_categories")
    return True


def cleanup_orphan_category_refs(db: Session) -> int:
    """清理指向「已不存在的标识分类」的文件分类引用（幂等）。

    [新增 2026-09-17] 背景：文件分类口径统一为「标识设置 → 标识分类」
    （signage_categories）之前，design_files.category_id 指向的是文件库自建的
    file_categories 表。升级后这些 ID 在标识分类中通常不存在，若不清理，
    列表会出现"有分类 ID 但取不到分类名"的悬空引用（前端显示「未分类」但数据不干净）。

    处理：category_id 不在 signage_categories 中的记录一律置空（= 未分类）；
    无悬空引用时不产生任何写入。
    """
    valid_ids = {cid for (cid,) in db.query(SignageCategory.id).all()}
    rows = db.query(DesignFile).filter(DesignFile.category_id.isnot(None)).all()
    cleared = 0
    for row in rows:
        if row.category_id not in valid_ids:
            row.category_id = None
            cleared += 1
    if cleared:
        db.commit()
        logger.info("清理悬空文件分类引用：%d 条", cleared)
    return cleared
