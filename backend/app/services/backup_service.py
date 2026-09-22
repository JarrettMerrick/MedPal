# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""定时备份服务"""
import logging
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text

from app.config import settings, DATA_ROOT

logger = logging.getLogger("backup_service")

# 北京时区（UTC+8）：用于备份文件时间展示
BEIJING_TZ = timezone(timedelta(hours=8))

# 备份目录 - 统一存放在数据根目录下的 data/backups（与 backend 完全隔离）
BACKUP_DIR = DATA_ROOT / "backups"

# [改进] 备份保留策略改为「按天保留」而非固定大数量，防止数据库增长后
# 100 个完整副本占满磁盘。每日凌晨备份一次，保留 N 个 = 最近 N 天。
# [修复] 保留数量改为读取 config.py 的 backup_max_count（由 .env 的
# BACKUP_MAX_COUNT 环境变量覆盖），原先硬编码 7 导致运维配置不生效，
# 与 README 承诺「可通过 .env 调整」不符。
BACKUP_RETENTION_DAYS = settings.backup_max_count
MAX_BACKUPS = BACKUP_RETENTION_DAYS  # 兼容既有引用：每日 1 个，保留最近 N 天

# [改进] 预恢复备份（prerestore_*.db）保留天数：作为恢复失败时的回滚点，
# 超时自动清理，避免每次 restore 累积完整数据库副本永不释放。
PRERESTORE_RETENTION_DAYS = 7

# [改进] 孤儿分片保留时长（小时）：上传会话 init 后未完成/未取消的分片目录，
# 超时清理，避免前端关页/断网导致 _chunks 目录永久残留占用磁盘。
ORPHAN_CHUNK_RETENTION_HOURS = 24

def utc_now():
    """获取当前 UTC 时间（naive），与 app.utils.utc_now() 保持一致"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bj_fmt(dt=None, fmt="%Y%m%d_%H%M%S"):
    """格式化 datetime 为字符串（用于备份文件名等）"""
    if dt is None:
        dt = utc_now()
    return dt.strftime(fmt)


def _ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# [改进/IO2] 备份文件名白名单：仅允许字母/数字/下划线/连字符/点，且必须以 .db 结尾。
# 备份文件名由系统生成（backup_YYYYmmdd_HHMMSS.db / prerestore_*.db），无需其它字符。
_SAFE_BACKUP_NAME = re.compile(r"^[A-Za-z0-9_\-.]+\.db$")


def _resolve_backup_path(filename: str) -> Path:
    """校验并解析备份文件的绝对路径，防止路径穿越（IO2）。

    校验规则：
      1. 文件名必须匹配白名单（禁止 '/'、'\\'、'..' 等穿越字符）；
      2. 解析后的绝对路径必须仍位于 BACKUP_DIR 目录之内。
    任一不满足则抛 ValueError，由调用方转为错误响应。
    """
    if not filename or not _SAFE_BACKUP_NAME.match(filename):
        raise ValueError("非法的备份文件名")
    _ensure_backup_dir()
    base = BACKUP_DIR.resolve()
    target = (base / filename).resolve()
    # 断言目标路径仍在备份目录内（Windows/Linux 均适用）
    if base != target.parent:
        raise ValueError("非法的备份文件路径")
    return target


def _get_db_path() -> Path:
    db_path = settings.database_url.replace("sqlite:///", "")
    return Path(db_path)


def _verify_sqlite_integrity(path: Path) -> tuple[bool, str]:
    """校验 SQLite 文件的物理与逻辑完整性。返回 (是否通过, 说明文本)。

    [新增 2026-09-21 / 存储审计 D-2、D-3] 备份体系此前**从不校验完整性**：
    备份可能因磁盘坏道、写入中断、传输损坏而产生一个"存在但已损坏"的文件，
    而要等到真正恢复时才发现 —— 那时通常已经没有别的可用备份了。

    这是备份体系最危险的失效模式：**静默失效**（文件在、看起来正常、实际不可用）。
    因此校验必须前置到「生成时」与「恢复前」两个节点：

      - 生成时校验（D-3）：及时发现损坏，当场重试或告警，不至于让当天没有可用备份；
      - 恢复前校验（D-2）：避免把一个损坏的备份写进正在使用的数据库。

    实现要点：
      - 以**只读 URI** 打开（`mode=ro`），确保校验动作本身不会修改文件
        （SQLite 在普通连接下可能触发 WAL 恢复等写操作）；
      - `PRAGMA integrity_check` 全表扫描校验 B 树结构与索引一致性，
        正常返回单行 "ok"，异常时返回具体的损坏描述；
      - 该校验是**全库扫描**，对大库有一定耗时，因此只在上述两个关键节点调用。
    """
    import sqlite3

    if not path.exists():
        return False, "文件不存在"
    if path.stat().st_size == 0:
        return False, "文件大小为 0"

    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            result = (row[0] if row else "") or "unknown"
        finally:
            conn.close()
    except Exception as e:
        return False, f"校验异常: {type(e).__name__}: {e}"

    if result.lower() == "ok":
        return True, "ok"
    # 损坏时 integrity_check 会给出多行描述，取首行即可（完整内容过长且无助于决策）
    return False, result.splitlines()[0] if result else "未知损坏"


def create_backup() -> dict:
    """执行一次备份，返回备份信息。
    
    [改进] 通过串行锁保护，防止与导出打包等重量级操作并发执行。"""
    from app.services.task_queue import run_serial
    return run_serial(_do_create_backup)


def _do_create_backup() -> dict:
    """实际执行备份的内部函数（由 run_serial 调度）"""
    import sqlite3
    _ensure_backup_dir()
    db_path = _get_db_path()
    if not db_path.exists():
        logger.error(f"数据库文件不存在: {db_path}")
        return {"success": False, "error": "数据库文件不存在"}

    timestamp = _bj_fmt()
    filename = f"backup_{timestamp}.db"
    backup_path = BACKUP_DIR / filename

    try:
        # [改造 2026-09-21 / 存储审计 D-3] 备份 + 完整性校验，最多尝试 2 次。
        #
        # 原实现只做 backup 就宣告成功，从不校验 —— 磁盘坏道、写入中断、文件系统
        # 异常都可能产出一个"存在但已损坏"的备份文件，而**要等到真正恢复时才会发现**。
        # 那时通常已没有别的可用备份，等于备份体系静默失效。
        #
        # 现改为：每次备份后立即 integrity_check；不通过则删除该文件并重试一次。
        # 两次都失败说明不是偶发问题，记 ERROR + 通知管理员（而不是悄悄返回失败）。
        verified = False
        verify_detail = ""
        for attempt in (1, 2):
            source_conn = sqlite3.connect(str(db_path))
            dest_conn = sqlite3.connect(str(backup_path))
            try:
                # 使用SQLite的.backup命令进行安全备份，确保数据一致性
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                source_conn.close()

            verified, verify_detail = _verify_sqlite_integrity(backup_path)
            if verified:
                logger.info(f"使用SQLite backup命令完成备份并通过完整性校验: {filename}")
                break

            logger.warning(
                f"备份完整性校验未通过（第 {attempt}/2 次）: {filename}, 原因: {verify_detail}"
            )
            try:
                backup_path.unlink(missing_ok=True)  # 不留损坏的备份，避免被误认为可用
            except OSError as rm_err:
                logger.warning(f"删除损坏备份失败: {rm_err}", exc_info=True)

        if not verified:
            # 两次均失败 → 这不是偶发问题，必须让管理员知道「今天没有可用备份」
            logger.error(
                f"[CRITICAL] 备份完整性校验连续 2 次失败，本次备份未生成: {filename}, "
                f"原因: {verify_detail}"
            )
            try:
                _notify_system_admins(
                    "数据库备份失败",
                    f"本次备份连续 2 次未通过完整性校验（{verify_detail}），"
                    "当前没有生成可用备份，请尽快检查磁盘与文件系统状态。",
                    "critical",
                )
            except Exception as notify_err:
                logger.warning(f"备份失败告警通知未发出: {notify_err}", exc_info=True)
            return {"success": False, "error": f"备份完整性校验失败: {verify_detail}"}

        size = backup_path.stat().st_size

        # [修复] 清理旧备份：按日期去重，保留最近 N 天每天 1 份（每日保留最新一份）。
        # 原先按文件名排序取前 N 个（backup_YYYYmmdd_HHMMSS.db），同日多次备份
        # （定时+手动）会挤占天数窗口，导致实际保留天数不足 N 天。
        all_backups = sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True)
        seen_dates: set[str] = set()
        to_delete: list[Path] = []
        for b in all_backups:
            m = re.match(r"^backup_(\d{8})_\d{6}\.db$", b.name)
            if not m:
                continue  # 非标准命名（prerestore_/upload_ 等）不参与去重
            date = m.group(1)
            if date not in seen_dates and len(seen_dates) < MAX_BACKUPS:
                seen_dates.add(date)  # 保留该日最新一份
            else:
                to_delete.append(b)  # 同日旧份 或 超出天数窗口的旧备份
        for old in to_delete:
            old.unlink()
            # [修正 2026-09-19] 循环内逐条 INFO → DEBUG：符合「禁止在循环中打 INFO」，
            # 数量已在下方汇总日志中体现，逐条输出只会稀释有用信息。
            logger.debug(f"已清理旧备份: {old.name}")

        # [改进] 清理过期的预恢复备份，避免每次恢复累积完整副本
        _clean_prerestore_backups()

        logger.info(f"备份成功: {filename}, 大小: {size} bytes")
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "created_at": timestamp,
        }
    except Exception as e:
        logger.error(f"备份失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _clean_prerestore_backups():
    """[改进] 清理超过保留天数的预恢复备份文件（prerestore_*.db）。

    每次 restore_backup 都会生成一份完整数据库副本作为回滚点，若不清
    理，管理员多次恢复会无限累积、占满磁盘。此处按 mtime 超时删除。"""
    try:
        cutoff = utc_now().timestamp() - PRERESTORE_RETENTION_DAYS * 86400
        for f in BACKUP_DIR.glob("prerestore_*.db"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    logger.debug(f"已清理过期预恢复备份: {f.name}")  # [修正 2026-09-19] 循环内 INFO → DEBUG
            except OSError as rm_err:
                # [修正 2026-09-19] 原为静默 pass：单个备份文件删除失败虽不影响整体，
                # 但完全不留痕会让残留文件无从解释，故降级为 warning 留痕。
                logger.warning(
                    "删除过期预恢复备份失败（已忽略，不影响主流程）: %s", f,
                    exc_info=True,
                )
    except Exception as e:
        logger.warning(f"清理预恢复备份失败（非致命）: {e}", exc_info=True)


def clean_orphan_chunks():
    """[改进] 清理上传会话超时未完成的孤儿分片目录（data/uploads/_chunks/{upload_id}）。

    分片上传在 init 后，若前端未调用 complete 也未调用 cancel（刷新、断网、
    关闭页面），对应 _chunks 目录会永久残留，需定时清理释放磁盘。"""
    try:
        from app.database import SessionLocal
        from app.models.upload_session import UploadSession
        from app.services.upload_service import UPLOAD_ROOT

        chunk_root = Path(UPLOAD_ROOT) / "_chunks"
        if not chunk_root.is_dir():
            return

        db = SessionLocal()
        try:
            # 取出所有 active 会话及其最后更新时间，用于判定孤儿
            active = db.query(UploadSession).filter(
                UploadSession.status == "active"
            ).all()
            active_map = {s.upload_id: s.updated_at for s in active}
        finally:
            db.close()

        # 统一用 UTC 时间戳比较，避免时区歧义（updated_at 存的是 UTC）
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff_ts = now_ts - ORPHAN_CHUNK_RETENTION_HOURS * 3600
        for d in chunk_root.iterdir():
            if not d.is_dir():
                continue
            upload_id = d.name
            sess = active_map.get(upload_id)
            # 会话已不存在，或最后更新超过保留时长 → 判定为孤儿，清理
            is_orphan = True
            if sess is not None:
                try:
                    sess_ts = sess.replace(tzinfo=timezone.utc).timestamp()
                    if sess_ts > cutoff_ts:
                        is_orphan = False
                except Exception:
                    is_orphan = True
            if is_orphan:
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    logger.debug(f"已清理孤儿分片目录: {upload_id}")  # [修正 2026-09-19] 循环内 INFO → DEBUG
                except Exception:
                    # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
                    # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
                    logger.warning(
                        "旁路操作失败（已忽略，不影响主流程）", exc_info=True
                    )
    except Exception as e:
        # [修正 2026-09-19] 等级由 ERROR 降为 WARN：属每日定时清理任务，
        # 失败多为文件占用一类可预知情况，次日会重跑；打 ERROR 会持续刷新告警、
        # 淹没真正的严重问题（ERROR 在配置了告警的系统中会触发通知甚至电话）。
        logger.warning(f"清理孤儿分片失败: {e}", exc_info=True)


def clean_orphan_images():
    """[改进] 清理磁盘上有但数据库中无引用的孤儿图片。

    备份恢复后，附件与数据库记录可能不一致。定期清理这些"磁盘有、
    数据库无"的孤立图片，避免永久占用磁盘空间。

    执行流程：
      1. 连接数据库，遍历所有模型的所有图片字段，收集被引用的路径
      2. 扫描 data/uploads/ 目录，删除不在引用集合中的文件及缩略图
      3. 记录清理统计

    频率：每日北京时间 3:15 自动执行（原先每周一次，回收不及时，
    现提高为每日一次，删除/恢复产生的孤儿图片最迟 24 小时内回收）。
    """
    try:
        from app.database import SessionLocal
        from app.services.upload_service import build_referenced_set, delete_orphan_files

        db = SessionLocal()
        try:
            referenced = build_referenced_set(db)
            result = delete_orphan_files(referenced)
        finally:
            db.close()

        # [修正 2026-09-21] 原先此处再打一条「孤儿图片清理完成」汇总 ——
        # 与 delete_orphan_files 内部的汇总日志内容重叠，属「同一事件双层记录」。
        # 现由内部统一输出（含保护期跳过数与异常目录告警），此处仅在
        # **实际发生跳过/删除**时补一条简短的调度侧摘要，便于定时任务的日志检索。
        if result.get("total_orphans") or result.get("skipped_dirs") or result.get("skipped_by_age"):
            logger.info(
                f"孤儿清理任务摘要: 删除 {result.get('total_orphans', 0)} 个文件, "
                f"释放 {result.get('total_bytes_freed', 0)} bytes"
                + (f", ⚠️ 跳过异常目录 {result.get('skipped_dirs')}" if result.get("skipped_dirs") else "")
            )
    except Exception as e:
        # [修正 2026-09-19] ERROR → WARN：见「清理孤儿分片失败」同因（定时任务，可重跑）
        logger.warning(f"孤儿图片清理失败: {e}", exc_info=True)


def delete_backup(filename: str) -> dict:
    """删除指定备份文件"""
    _ensure_backup_dir()
    # [改进/IO2] 净化文件名，防止 ?filename=../../ 路径穿越删除任意文件
    try:
        backup_path = _resolve_backup_path(filename)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not backup_path.exists():
        return {"success": False, "error": "备份文件不存在"}
    if not backup_path.is_file():
        return {"success": False, "error": "路径不是文件"}
    try:
        backup_path.unlink()
        logger.info(f"已删除备份文件: {filename}")
        return {"success": True, "message": f"已删除备份文件: {filename}"}
    except Exception as e:
        logger.error(f"删除备份文件失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def get_backup_list() -> list[dict]:
    """获取备份文件列表"""
    _ensure_backup_dir()
    backups = []
    for f in sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True):
        stat = f.stat()
        # 从文件名解析时间
        name = f.name
        ts = name.replace("backup_", "").replace(".db", "")
        backups.append({
            "filename": name,
            "size": stat.st_size,
            "created_at": ts,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return backups


def restore_backup(filename: str, operator: str | None = None) -> dict:
    """从备份文件恢复数据库。

    [修复] 通过串行任务队列执行：备份任务（create_backup/_do_create_backup）会用
    sqlite3 连接长时间持有 medical.db，若恢复与其并发，Windows 下删除文件会持续
    报 WinError 32（dispose/重试都无法释放其他任务的连接）。与备份/打包共用串行锁，
    保证同一时间只有一个重量级数据库操作。

    Args:
        operator: 发起恢复的操作者工号，用于恢复成功后的审计留痕（问题10a）。
    """
    from app.services.task_queue import run_serial
    return run_serial(_restore_backup_impl, filename, operator)


def _restore_backup_impl(filename: str, operator: str | None = None) -> dict:
    """restore_backup 的实际实现（在串行锁保护下执行）"""
    # [改进/IO2] 净化文件名，防止路径穿越恢复非备份目录内的任意文件
    try:
        backup_path = _resolve_backup_path(filename)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not backup_path.exists():
        return {"success": False, "error": "备份文件不存在"}

    # ── [新增 2026-09-21 / 存储审计 D-2] 恢复前校验备份完整性 ──
    # 这是恢复流程中**最关键的一道闸门**。
    #
    # 原实现直接把这个文件的内容写进正在使用的 medical.db。若备份本身损坏
    # （磁盘坏道、当初备份时写入中断、跨机传输损坏），写入会中途失败，
    # 而此时**生产库已被写入一半** —— 结果从「备份不可用」恶化为「生产数据也损坏」，
    # 且必须人工介入才能恢复。
    #
    # 因此：先校验，不通过就**在动生产库之前**中止。此时生产库完好无损，
    # 用户只需换一个备份文件重试即可，不产生任何次生损害。
    _ok, _detail = _verify_sqlite_integrity(backup_path)
    if not _ok:
        logger.error(
            f"备份文件完整性校验失败，已中止恢复（生产库未做任何改动）: "
            f"{filename}, 原因: {_detail}"
        )
        try:
            _notify_system_admins(
                "数据库恢复已中止",
                f"备份文件 {filename} 未通过完整性校验（{_detail}），"
                "恢复流程已在写入前中止，现有数据未受影响。请改用其他备份文件。",
                "critical",
            )
        except Exception as notify_err:
            logger.warning(f"恢复中止告警未发出: {notify_err}", exc_info=True)
        return {"success": False, "error": f"备份文件已损坏，恢复已中止: {_detail}"}

    db_path = _get_db_path()
    # [新增] 记录预恢复副本路径，供失败时自动回滚使用（原实现仅保留副本待人工处理）
    _pre_restore_path: Path | None = None
    try:
        import sqlite3

        # 先备份当前数据库（预防性）
        timestamp = _bj_fmt()
        pre_restore = BACKUP_DIR / f"prerestore_{timestamp}.db"
        _pre_restore_path = pre_restore  # [新增] 供外层失败分支自动回滚使用
        if db_path.exists():
            try:
                src_conn = sqlite3.connect(str(db_path))
                dst_conn = sqlite3.connect(str(pre_restore))
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
                logger.info(f"已创建预恢复备份: {pre_restore.name}")
            except Exception as pre_err:
                logger.warning(f"创建预恢复备份失败（非致命）: {pre_err}", exc_info=True)

        # 1. 释放现有数据库连接
        import app.database as db_module
        try:
            db_module.engine.dispose()
        except Exception:
            # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
            # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
            logger.warning(
                "旁路操作失败（已忽略，不影响主流程）", exc_info=True
            )

        # 2. [修复] 直接从备份恢复到 db_path，不再"删除旧文件 + 重命名"。
        #    Windows 下 medical.db 常被 SQLAlchemy 连接池或并发请求持续占用，
        #    unlink 会报 WinError 32（即使 engine.dispose() + 重试也无法保证释放）；
        #    改用 SQLite backup API 直接写入目标文件，由 SQLite 内部协调文件锁，
        #    跨平台可靠（backup 会自动重试等待 busy 目标释放）。
        #
        #    先执行 WAL checkpoint(TRUNCATE) 把可能残留的 WAL 合并进主文件，
        #    避免 backup 写入后新连接读到旧的 WAL 数据。
        try:
            _chk = sqlite3.connect(str(db_path), timeout=30)
            try:
                _chk.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                _chk.close()
        except Exception as chk_err:
            logger.warning(f"恢复前 WAL checkpoint 失败（非致命）: {chk_err}", exc_info=True)

        try:
            src_conn = sqlite3.connect(str(backup_path))
            try:
                # timeout=30 提供锁等待超时；backup 遇 busy 目标会自动重试等待
                dst_conn = sqlite3.connect(str(db_path), timeout=30)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
            logger.info(f"已从备份文件直接恢复数据库: {backup_path.name}")

            # ── [新增 2026-09-21 / 存储审计 D-2] 恢复后校验目标库 ──
            # 恢复前已校验源备份，此处再校验**写入结果**：SQLite backup API 在
            # 目标磁盘空间不足、文件系统异常等情况下，可能出现"调用成功但写入不完整"。
            # 此时必须立即发现并回滚，否则应用会带着一个损坏的库继续对外服务。
            _dst_ok, _dst_detail = _verify_sqlite_integrity(db_path)
            if not _dst_ok:
                raise RuntimeError(f"恢复后目标库完整性校验未通过: {_dst_detail}")
            logger.info("恢复后目标库完整性校验通过")
        except Exception as restore_err:
            # [修正 2026-09-19] ERROR → DEBUG：该异常会被向上抛出，由本函数外层
            # 统一以 ERROR + 堆栈记录（见下方 except）。此处再记 ERROR 属「重复记录
            # 同一事件」，会让一次失败产生两条告警，故降为 DEBUG 仅保留过程痕迹。
            logger.debug(f"数据库恢复写入失败，交由外层统一记录: {restore_err}")
            raise restore_err

        # 3. [修复/问题10b] 不再热替换全局 engine / SessionLocal。
        #    原实现在 dispose 后重建 engine 并重新绑定 SessionLocal，
        #    导致在途请求已 check out 的 Session 仍绑定旧引擎，
        #    其下一次 IO 会因旧引擎已被 dispose 而失败（500）。
        #    改为复用同一个 engine：dispose() 关闭池内连接后，
        #    后续新请求从该 engine 取到的即是读取恢复后数据的全新连接；
        #    已 checkout 的连接在归还时才关闭，不影响正在处理的请求。
        try:
            db_module.engine.dispose()
        except Exception as dispose_err:
            logger.warning(f"恢复后释放数据库连接失败（非致命）: {dispose_err}", exc_info=True)

        # 4. [修复/问题10a] 「恢复」审计留痕必须在恢复成功之后写入恢复后的新库。
        #    原实现先 record_audit("restore") 再覆盖 medical.db，
        #    该记录写在即将被覆盖的库里，恢复完成后即丢失，
        #    与「数据库恢复必须留痕」的初衷自相矛盾。
        try:
            from app.services.audit_service import record_audit
            sess = db_module.SessionLocal()
            try:
                record_audit(
                    sess, "restore", operator or "system",
                    detail=f"file={filename}, prerestore={pre_restore.name}",
                    target=filename, ip_address=None,
                )
                sess.commit()
            finally:
                sess.close()
        except Exception as audit_err:
            logger.warning(f"恢复审计留痕失败（非致命）: {audit_err}", exc_info=True)

        # 保留预恢复备份文件（prerestore_*.db），作为恢复失败/发现问题时的回滚点
        # [修正 2026-09-19] 原为连续两条「数据库恢复成功」（内容重叠且无信息增量），
        # 合并为一条，同时保留回滚点位置与引擎状态两个关键信息。
        logger.info(
            f"数据库恢复成功: {filename}，引擎已重新初始化，"
            f"预恢复备份保留于 {pre_restore.name}"
        )
        return {"success": True, "message": f"已从 {filename} 恢复数据"}
    except Exception as e:
        logger.error(f"数据库恢复失败: {e}", exc_info=True)

        # ── [新增 2026-09-21 / 存储审计 D-2] 失败自动回滚 ──
        # 原实现在失败时只保留一个 prerestore 副本，**等待人工介入**。
        # 但恢复失败往往发生在数据已被写入一半的状态，应用此时仍在对外服务，
        # 期间所有读写都会作用在这个不一致的库上 —— 拖得越久，损害越难收拾。
        #
        # 现改为：一旦恢复流程抛错，立即用预恢复副本把库还原到操作前的状态。
        # 回滚成功后系统即可正常使用（等于"本次恢复没发生过"），
        # 管理员可从容排查原因、换个备份重试，而不是在故障中抢时间。
        rollback_note = ""
        if _pre_restore_path is not None and _pre_restore_path.exists():
            try:
                import sqlite3 as _sqlite3

                import app.database as db_module_rb

                try:
                    db_module_rb.engine.dispose()
                except Exception:
                    logger.warning("回滚前释放数据库连接失败（继续尝试回滚）", exc_info=True)

                _src = _sqlite3.connect(str(_pre_restore_path))
                _dst = _sqlite3.connect(str(db_path), timeout=30)
                try:
                    _src.backup(_dst)
                finally:
                    _dst.close()
                    _src.close()

                try:
                    db_module_rb.engine.dispose()
                except Exception:
                    logger.warning("回滚后释放数据库连接失败", exc_info=True)

                _rb_ok, _rb_detail = _verify_sqlite_integrity(db_path)
                if _rb_ok:
                    rollback_note = f"，已自动回滚到恢复前状态（{_pre_restore_path.name}）"
                    logger.info(
                        f"恢复失败后已自动回滚到恢复前状态: {_pre_restore_path.name}"
                    )
                else:
                    rollback_note = f"，回滚后校验未通过（{_rb_detail}），需人工介入"
                    logger.error(
                        f"[CRITICAL] 自动回滚后数据库完整性校验仍未通过: {_rb_detail}，"
                        f"请立即人工介入，预恢复副本位于 {_pre_restore_path}"
                    )
            except Exception as rb_err:
                rollback_note = f"，自动回滚失败（{rb_err}），需人工介入"
                logger.error(
                    f"[CRITICAL] 恢复失败后自动回滚也失败: {rb_err}，"
                    f"请立即人工介入，预恢复副本位于 {_pre_restore_path}",
                    exc_info=True,
                )
        else:
            rollback_note = "，且无可用的预恢复副本（恢复前未成功创建），需人工介入"
            logger.error(
                "[CRITICAL] 恢复失败且没有可用的预恢复副本，无法自动回滚，请立即人工介入"
            )

        # 无论自动回滚结果如何都要通知管理员：这是一次严重的失败，必须有人知晓
        try:
            _notify_system_admins(
                "数据库恢复失败",
                f"从 {filename} 恢复失败：{e}{rollback_note}",
                "critical",
            )
        except Exception as notify_err:
            logger.warning(f"恢复失败告警未发出: {notify_err}", exc_info=True)

        return {"success": False, "error": f"{e}{rollback_note}"}


def scheduled_backup():
    """定时备份任务"""
    logger.info("开始执行定时备份任务...")
    result = create_backup()
    if result["success"]:
        logger.info(f"定时备份完成: {result['filename']}")
    else:
        # [修正 2026-09-19] ERROR → WARN：具体失败原因已在 create_backup 内记录，
        # 此处仅作调度层摘要，重复打 ERROR 会让同一次失败触发两条告警。
        logger.warning(f"定时备份失败: {result.get('error')}")


def clean_expired_packages():
    """清理过期打包文件（保留1天）"""
    try:
        from app.database import SessionLocal
        from app.models.export_package import ExportPackage

        db = SessionLocal()
        try:
            expired = db.query(ExportPackage).filter(
                ExportPackage.expires_at < utc_now().replace(tzinfo=None)
            ).all()
            # 导出目录 - 统一存放在数据根目录下的 data/exports（与 backend 完全隔离）
            exports_dir = DATA_ROOT / "exports"
            for p in expired:
                zip_path = exports_dir / p.filename
                if zip_path.exists():
                    zip_path.unlink()
                db.delete(p)
            if expired:
                db.commit()
                logger.info(f"已清理 {len(expired)} 个过期打包文件")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"清理过期打包文件失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）


def clean_expired_blacklist():
    """清理过期的 token 黑名单条目"""
    try:
        from app.database import SessionLocal
        from app.services.auth_service import cleanup_expired_blacklist

        db = SessionLocal()
        try:
            deleted = cleanup_expired_blacklist(db)
            if deleted:
                logger.info(f"已清理 {deleted} 个过期 token 黑名单条目")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"清理过期 token 黑名单失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）


# ---- [改进] 新增长期运行维护任务 ----

def checkpoint_wal():
    """定时执行 WAL checkpoint，控制 SQLite -wal 文件大小。
    
    WAL 模式下，写入操作先追加到 -wal 文件，仅在 checkpoint 时合并回主数据库。
    若不主动触发 checkpoint，-wal 文件在高写入负载下会持续增长至数百 MB 甚至 GB。
    使用 TRUNCATE 模式确保 checkpoint 后 -wal 文件被截断释放空间。
    """
    try:
        from app.database import engine
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        logger.info("WAL checkpoint 完成")
    except Exception as e:
        logger.warning(f"WAL checkpoint 失败（非致命）: {e}", exc_info=True)


# [改进/1.0.9] WAL 文件大小监控阈值（50MB），超过时强制 checkpoint 防止磁盘波动
WAL_SIZE_THRESHOLD = 50 * 1024 * 1024

# [改进/1.0.9] 数据库文件大小告警阈值（MB）
DB_SIZE_WARNING_MB = 500
DB_SIZE_CRITICAL_MB = 1000


def monitor_wal_size():
    """[改进/1.0.9] 检查 WAL 文件大小，超过阈值时强制执行 checkpoint。

    正常情况下每天 00:30 会执行 checkpoint，但在高写入量场景下 WAL 可能在此期间暴涨。
    此任务每 2 小时检查一次，作为补充保护机制。
    """
    db_path = str(settings.database_url).replace("sqlite:///", "")
    wal_path = f"{db_path}-wal"
    if not os.path.exists(wal_path):
        return
    try:
        wal_size = os.path.getsize(wal_path)
        if wal_size > WAL_SIZE_THRESHOLD:
            logger.warning(
                f"WAL 文件过大 ({wal_size / 1024 / 1024:.1f}MB > {WAL_SIZE_THRESHOLD // 1024 // 1024}MB)，"
                "立即执行 checkpoint(TRUNCATE)"
            )
            from app.database import engine
            with engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            # [修正 2026-09-19] 补上下文：与例行的 checkpoint_wal 任务区分开
            # （两处原文案完全相同，排查时无法判断是例行执行还是超阈值触发）
            logger.info("WAL 超过阈值，已执行 checkpoint(TRUNCATE)")
    except Exception as e:
        logger.warning(f"监控 WAL 大小失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时监控任务）


# [改进] 告警通知去重窗口（秒）：同一级别告警在窗口内不重复发通知，
# 避免每次定时检查都重复骚扰，仅在该级别告警状态持续/变化时通知。
ALERT_NOTIFY_DEDUP_SECONDS = 6 * 3600  # 6 小时

# [改进] 记录各告警级别最近一次发送通知的时间，用于去重。
_alert_notify_times: dict[str, float] = {}


def _notify_system_admins(title: str, content: str, level: str):
    """[改进] 将系统级告警（磁盘/数据库）写入 Notification 表通知给系统管理员。

    - 发送对象：拥有 system.config 或 system.backup 权限的活跃用户（基于权限表，
      而非角色名硬编码，与 notify_super_admins 保持一致）。
    - 去重：同级别告警在 ALERT_NOTIFY_DEDUP_SECONDS 窗口内不重复发送，
      防止每 6 小时/每日定时检查重复骚扰；但若级别升级（warning→critical）会立即发送。
    """
    import time as _time
    now = _time.time()
    last = _alert_notify_times.get(level, 0.0)
    if now - last < ALERT_NOTIFY_DEDUP_SECONDS:
        return  # 窗口内已通知，去重
    try:
        from app.database import SessionLocal
        from app.models.user import User
        from app.dependencies import has_permission, PERM_SYSTEM_CONFIG, PERM_SYSTEM_BACKUP
        # [调整 2026-09-11] 系统告警并入站内信（统一收件箱）
        from app.services import message_service

        db = SessionLocal()
        try:
            active = db.query(User).filter(User.is_active == True).all()  # noqa: E712
            targets = [
                u.employee_id
                for u in active
                if has_permission(u, PERM_SYSTEM_CONFIG) or has_permission(u, PERM_SYSTEM_BACKUP)
            ]
            if targets:
                # [调整 2026-09-15] 统一走通知中心（事件：system.alert）：
                # 管理员可在「通知设置 → 系统告警」中关闭或调整文案；正文/标题按原文插入
                from app.services import notification_center
                notification_center.emit(
                    db, "system.alert",
                    context={"级别": level.upper(), "标题": title, "内容": content},
                    recipients=targets,
                    related_type="system_alert",
                    fallback_title=f"[{level.upper()}] {title}",
                    fallback_content=content,
                )
            db.commit()
            _alert_notify_times[level] = now
            if targets:
                logger.info(f"已发送系统告警通知 {len(targets)} 条: {title}")
        finally:
            db.close()
    except Exception as e:
        # 告警通知失败不能阻断主流程，仅记录日志
        # [修正 2026-09-19] ERROR → WARN：与本文件其他「通知类失败」等级保持一致
        # （创建预恢复备份 / WAL checkpoint / 释放连接 / 审计留痕失败均为 WARN）。
        # 通知失败本身不该触发告警，否则会形成「告警发不出去→再触发告警」的递归噪音。
        logger.warning(f"发送系统告警通知失败: {e}", exc_info=True)


def check_db_size():
    """[改进/1.0.9] 检查数据库主文件大小并记录告警日志 + 通知管理员。

    SQLite 数据库只会增大不会自动缩小（除非 VACUUM），
    此函数提供主动告警能力，便于运维人员及时处理。
    [改进] 超过阈值时除写日志外，还向系统管理员写入 Notification 表告警，
    避免仅落 7 天轮转日志无人查看。
    """
    db_path = str(settings.database_url).replace("sqlite:///", "")
    try:
        size_mb = os.path.getsize(db_path) / 1024 / 1024
        if size_mb > DB_SIZE_CRITICAL_MB:
            # [修正 2026-09-19] critical → error + 显式 [CRITICAL] 标注：
            # 统一到规范约定的四个等级（DEBUG/INFO/WARN/ERROR），
            # 由文案标明严重程度，避免第五个等级绕过既有的告警规则配置。
            logger.error(
                f"[CRITICAL] 数据库文件严重过大: {size_mb:.1f}MB (>{DB_SIZE_CRITICAL_MB}MB)，"
                "建议检查数据增长原因或手动执行 VACUUM"
            )
            _notify_system_admins(
                "数据库文件严重过大",
                f"数据库文件 {size_mb:.1f}MB（> {DB_SIZE_CRITICAL_MB}MB），"
                "建议检查数据增长原因或手动执行 VACUUM",
                "critical",
            )
        elif size_mb > DB_SIZE_WARNING_MB:
            logger.warning(f"数据库文件接近上限: {size_mb:.1f}MB (>{DB_SIZE_WARNING_MB}MB)")
            _notify_system_admins(
                "数据库文件接近上限",
                f"数据库文件 {size_mb:.1f}MB（> {DB_SIZE_WARNING_MB}MB），建议近期处理",
                "warning",
            )
        else:
            logger.debug(f"数据库文件大小正常: {size_mb:.1f}MB")
    except Exception as e:
        logger.warning(f"检查数据库大小失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时巡检任务）


def check_disk_space():
    """每日检查磁盘可用空间，低于阈值则记录告警 + 通知管理员。
    
    SQLite 在磁盘满时会报 "database is locked" 错误，
    提前告警可让运维在问题发生前介入清理。
    [改进] 低于阈值时除写日志外，还向系统管理员写入 Notification 表告警，
    避免仅落 7 天轮转日志无人查看。
    """
    try:
        data_root_str = str(DATA_ROOT)
        usage = shutil.disk_usage(data_root_str)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct = usage.free / usage.total * 100
        if pct < 10:
            # [修正 2026-09-19] critical → error + [CRITICAL] 标注（同上，统一等级体系）
            logger.error(
                f"[CRITICAL] 磁盘可用空间严重不足: {free_gb:.1f}GB/{total_gb:.1f}GB ({pct:.1f}%)，"
                f"请立即清理！否则数据库将无法写入。"
            )
            _notify_system_admins(
                "磁盘空间严重不足",
                f"磁盘可用空间仅剩 {free_gb:.1f}GB/{total_gb:.1f}GB（{pct:.1f}%），"
                "请立即清理！否则数据库将无法写入",
                "critical",
            )
        elif pct < 20:
            logger.warning(
                f"磁盘可用空间偏低: {free_gb:.1f}GB/{total_gb:.1f}GB ({pct:.1f}%)，"
                f"建议近期清理。"
            )
            _notify_system_admins(
                "磁盘空间偏低",
                f"磁盘可用空间 {free_gb:.1f}GB/{total_gb:.1f}GB（{pct:.1f}%），建议近期清理",
                "warning",
            )
        else:
            logger.info(f"磁盘空间正常: {free_gb:.1f}GB/{total_gb:.1f}GB ({pct:.1f}%)")
    except Exception as e:
        logger.warning(f"磁盘空间检查失败（非致命）: {e}", exc_info=True)


def vacuum_database():
    """每月 VACUUM 回收数据库空闲空间。
    
    SQLite 的 DELETE 操作仅标记页面为空闲，不会缩减数据库文件大小。
    长期运行后数据库文件会持续膨胀，VACUUM 可将其压缩至实际数据大小。
    注意：VACUUM 需要约 2 倍数据库大小的临时磁盘空间，执行期间数据库会被锁定。
    """
    try:
        from app.database import engine
        with engine.connect() as conn:
            conn.execute(text("VACUUM"))
        logger.info("VACUUM 完成，数据库空间已回收")
    except Exception as e:
        logger.warning(f"VACUUM 失败（非致命）: {e}", exc_info=True)


def clean_old_audit_logs():
    """清理 90 天前的审计日志，防止 ModificationHistory 表无限增长。
    
    审计日志用于追溯数据变更历史，但超过 90 天的记录在实际运维中极少查阅，
    持续累积会影响查询性能并占用磁盘空间。
    """
    try:
        from app.database import SessionLocal
        from app.models.audit_log import ModificationHistory

        deadline = utc_now() - timedelta(days=90)
        db = SessionLocal()
        try:
            deleted = db.query(ModificationHistory).filter(
                ModificationHistory.modified_at < deadline
            ).delete()
            db.commit()
            if deleted:
                logger.info(f"已清理 {deleted} 条过期审计日志（90天前）")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"清理过期审计日志失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）


# [改进] 通知保留天数策略：
# - 已读通知：保留 30 天（用户已读，无再查阅价值，优先清理）
# - 未读通知：保留 90 天（用户可能尚未查看，需更长保留期，避免过早删除）
# 卡片上传/信息变更等场景每次为多个用户各插一条通知（chunk_upload.py:475-493），
# 长期累积会占库空间，需定时清理。
NOTIFICATION_READ_RETENTION_DAYS = 30
NOTIFICATION_UNREAD_RETENTION_DAYS = 90


def clean_old_notifications():
    """清理过期的系统通知，防止 notifications 表无限增长。

    通知由卡片上传、信息变更等操作为多个用户批量生成（chunk_upload.py:475-493），
    长期累积占用数据库空间并拖慢查询。清理策略（均相对创建时间 created_at）：
      - 已读通知保留 30 天
      - 未读通知保留 90 天
    未读通知保留更久，避免误删用户尚未查看的重要通知。
    """
    try:
        from app.database import SessionLocal
        # [调整 2026-09-11] 通知已并入站内信：改为清理 message_recipients 收件记录
        from app.models.message import Message, MessageRecipient

        now = utc_now()
        read_deadline = now - timedelta(days=NOTIFICATION_READ_RETENTION_DAYS)
        unread_deadline = now - timedelta(days=NOTIFICATION_UNREAD_RETENTION_DAYS)
        db = SessionLocal()
        try:
            # 先清理过期的已读收件记录（30 天）
            read_deleted = db.query(MessageRecipient).filter(
                MessageRecipient.is_read == True,  # noqa: E712
                MessageRecipient.created_at < read_deadline,
            ).delete(synchronize_session=False)
            # 再清理过期的未读收件记录（90 天）
            unread_deleted = db.query(MessageRecipient).filter(
                MessageRecipient.is_read == False,  # noqa: E712
                MessageRecipient.created_at < unread_deadline,
            ).delete(synchronize_session=False)
            # 收件记录清空后，删除已无任何收件人的孤立消息（消息主体与收件记录分离存储）
            orphan_deleted = db.query(Message).filter(
                ~Message.recipients.any()
            ).delete(synchronize_session=False)
            db.commit()
            if read_deleted or unread_deleted:
                logger.info(
                    f"已清理过期站内信: 已读 {read_deleted} 条（{NOTIFICATION_READ_RETENTION_DAYS}天前），"
                    f"未读 {unread_deleted} 条（{NOTIFICATION_UNREAD_RETENTION_DAYS}天前），"
                    f"孤立消息 {orphan_deleted} 条"
                )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"清理过期通知失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）


def clean_old_regulation_history():
    """[新增] 清理超过 3 年的制度历史版本，防止 regulation_history 表无限增长。

    每次修改制度都会生成一条历史版本记录（含版本号+完整内容快照），
    长期累积占用数据库空间。仅清理 edited_at 超过 3 年（1095 天）的记录。
    """
    try:
        from app.database import SessionLocal
        from app.models.regulation import RegulationHistory

        now = utc_now()
        deadline = now - timedelta(days=1095)
        db = SessionLocal()
        try:
            deleted = db.query(RegulationHistory).filter(
                RegulationHistory.edited_at < deadline,
            ).delete(synchronize_session=False)
            db.commit()
            if deleted:
                logger.info(f"已清理 {deleted} 条超过3年的制度历史版本（{deadline.strftime('%Y-%m-%d')} 前）")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"清理制度历史版本失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）


# [修复/问题16] 显式指定 UTC 时区。
# APScheduler 未指定 timezone 时默认使用服务器本地时区；而下面所有 cron 的
# hour/minute 均按 UTC 设计（如 hour=16 意为 UTC 16:15 = 北京时间 00:15）。
# 若服务器系统时区为 Asia/Shanghai，实际会在北京 16:15（UTC 08:15）触发，
# 与预期相差 8 小时，导致备份/清理等运维任务在错误时段执行。
# 显式固定为 UTC 后，cron 语义与注释一致，且不受部署环境系统时区影响。
scheduler = BackgroundScheduler(timezone="UTC")


def notify_resigned_accounts():
    """[新增 2026-09-11] 离职保留期提醒

    离职满 `RESIGN_RETENTION_DAYS`（默认 180 天 ≈ 6 个月）后，其档案按策略
    「仅保留统计」（不再出现在「离职人员」明细里），并通过**站内信**私信全部
    超级管理员，提醒手动删除该员工的登录账号——删除账号会级联清理人员档案，
    最终只留下统计口径与操作日志留痕。

    - 同一员工只提醒一次（写入 `staff.account_notice_at`，避免反复打扰）；
    - 系统中若无启用的超级管理员则跳过（记日志），下次运行会自动重试。
    """
    try:
        from app.database import SessionLocal
        from app.dependencies import ROLE_SUPER_ADMIN
        from app.models.staff import Staff
        from app.models.user import User
        from app.services import message_service
        from app.services.staff_service import RESIGN_RETENTION_DAYS

        db = SessionLocal()
        try:
            cutoff = utc_now() - timedelta(days=RESIGN_RETENTION_DAYS)
            candidates = (
                db.query(Staff)
                .filter(Staff.status == "resigned", Staff.account_notice_at.is_(None))
                .all()
            )
            # 历史数据兼容：resigned_at 为空时以 updated_at 近似离职时间
            targets = [
                s for s in candidates
                if (s.resigned_at or s.updated_at) and (s.resigned_at or s.updated_at) <= cutoff
            ]
            if not targets:
                return

            admins = [
                u.employee_id for u in db.query(User).filter(
                    User.role == ROLE_SUPER_ADMIN,
                    User.is_active == True,  # noqa: E712
                ).all()
            ]
            if not admins:
                logger.warning("离职档案清理提醒：系统内无启用的超级管理员，本次跳过（下次运行重试）")
                return

            shown = "、".join(f"{s.name}（{s.employee_id}）" for s in targets[:20])
            more = f" 等共 {len(targets)} 人" if len(targets) > 20 else ""
            content = (
                f"以下员工离职已满 {RESIGN_RETENTION_DAYS} 天（约 6 个月），按保留期策略"
                f"其档案已仅保留统计：{shown}{more}。<br/>"
                f"请前往「用户管理」手动删除其登录账号（删除账号会一并清理人员档案，"
                f"离职人数等统计不受影响）。"
            )
            # [调整 2026-09-15] 统一走通知中心（事件：system.resign_cleanup）
            from app.services import notification_center
            notification_center.emit(
                db, "system.resign_cleanup",
                context={
                    "保留天数": RESIGN_RETENTION_DAYS,
                    "名单": shown,
                    "更多": more,
                },
                recipients=admins,
                related_type="system_alert",
                fallback_title="离职档案清理提醒",
                fallback_content=content,
            )
            now = utc_now()
            for s in targets:
                s.account_notice_at = now
            db.commit()
            logger.info(
                "离职档案清理提醒已发送给 %d 名超级管理员，涉及 %d 名离职员工",
                len(admins), len(targets),
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"离职档案清理提醒失败（不影响其他任务）: {e}", exc_info=True)


def start_scheduler():
    """启动定时调度器
    
    所有调度任务以 UTC 时间配置（apscheduler 运行在 UTC 时区）:
    - UTC 16:15（北京时间 00:15） 数据库备份
    - UTC 19:15（北京时间 03:15） 清理孤儿图片（磁盘有、数据库无引用的照片文件）
    - UTC 1:00（北京时间 09:00） 清理残留临时导出文件（temp_exports）
    - UTC 3:00（北京时间 11:00） 清理过期打包文件
    - UTC 4:00（北京时间 12:00） 清理过期 token 黑名单
    - 每小时 清理孤儿分片目录
    - UTC 16:30（北京时间 00:30） WAL checkpoint（备份后执行）
    - UTC 0:00（北京时间 08:00） 磁盘空间检查
    - 每月 1 日 UTC 2:00（北京时间 10:00） VACUUM 回收数据库空间
    - 每月 1 日 UTC 3:30（北京时间 11:30） 清理过期审计日志
    - UTC 18:00（北京时间 02:00） 清理过期通知（已读 30 天 / 未读 90 天）
    - 每小时 清理过期的登录/刷新限流记录（限流已改为数据库存储）
    - [新增 2026-09-11] UTC 1:30（北京时间 09:30） 离职保留期提醒（满 6 个月 → 仅保留统计 + 私信超管删除账号）
    """
    if scheduler.get_jobs():
        logger.info("调度器已有作业，跳过初始化")
        return

    # UTC 16:15 = 北京时间 00:15（仅每日凌晨一次）
    scheduler.add_job(scheduled_backup, "cron", hour=16, minute=15, id="backup_daily", replace_existing=True)
    # UTC 3:00 = 北京时间 11:00 清理过期打包文件
    scheduler.add_job(clean_expired_packages, "cron", hour=3, minute=0, id="clean_packages", replace_existing=True)
    # UTC 4:00 = 北京时间 12:00 清理过期 token 黑名单
    scheduler.add_job(clean_expired_blacklist, "cron", hour=4, minute=0, id="clean_blacklist", replace_existing=True)
    # [改进] 每小时清理孤儿分片目录，释放未完成上传占用的磁盘
    scheduler.add_job(clean_orphan_chunks, "interval", hours=1, id="clean_orphan_chunks", replace_existing=True)
    # [新增 2026-09-08] 每小时清理超过 24 小时的标识附件导出压缩包（启动后立即先执行一次）
    from app.services.signage_export_service import cleanup_expired_exports
    scheduler.add_job(cleanup_expired_exports, "interval", hours=1,
                      id="clean_expired_exports", replace_existing=True,
                      next_run_time=datetime.now())
    # [改进] 每日 UTC 19:15（北京时间 03:15）清理孤儿图片（备份恢复后残留在磁盘的死文件）。
    # 频率由每周一次提高为每日一次：删除用户/备份恢复等操作产生的孤儿图片
    # 原先需等近一周才回收，现最迟 24 小时内回收，缩短磁盘残留滞留期。
    scheduler.add_job(clean_orphan_images, "cron", hour=19, minute=15, id="clean_orphan_images", replace_existing=True)

    # [改进] 新增长期运行维护任务
    # UTC 16:30 = 北京时间 00:30 WAL checkpoint（备份完成后执行）
    scheduler.add_job(checkpoint_wal, "cron", hour=16, minute=30, id="wal_checkpoint", replace_existing=True)
    # [改进/1.0.9] 每 2 小时检查一次 WAL 文件大小，防止高写入期间 WAL 暴涨
    scheduler.add_job(monitor_wal_size, 'interval', hours=2, id='monitor_wal', replace_existing=True)
    # [改进/1.0.9] 每 6 小时检查数据库文件大小并输出告警日志
    scheduler.add_job(check_db_size, 'interval', hours=6, id='check_db_size', replace_existing=True)
    # UTC 0:00 = 北京时间 08:00 磁盘空间检查
    scheduler.add_job(check_disk_space, "cron", hour=0, minute=0, id="disk_space_check", replace_existing=True)
    # [改进] UTC 1:00 = 北京时间 09:00 清理残留临时导出文件。
    # 兜底 BackgroundTasks 未执行/客户端中断导致的 temp_exports 累积（原先仅在应用启动时清理）
    # [重构 2026-09-21 / Q-2] 原为 `from app.routers.data_io import ...` ——
    # service 层反向导入 router 层，为绕开循环依赖只能写在函数体内。
    # 该逻辑已抽到同层的 services/temp_export_service.py，此处按正常方向导入。
    from app.services.temp_export_service import cleanup_stale_temp_files
    scheduler.add_job(cleanup_stale_temp_files, "cron", hour=1, minute=0, id="clean_temp_exports", replace_existing=True)
    # [改进/1.0.9] 每月 1 日执行 VACUUM 回收数据库空间
    scheduler.add_job(vacuum_database, "cron", day=1, hour=2, minute=0, id="vacuum_monthly", replace_existing=True)
    # 每月 1 日 UTC 3:30 = 北京时间 11:30 清理过期审计日志
    scheduler.add_job(clean_old_audit_logs, "cron", day=1, hour=3, minute=30, id="clean_audit_logs", replace_existing=True)
    # [改进] UTC 18:00 = 北京时间 02:00 清理过期通知（已读 30 天 / 未读 90 天），
    # 卡片上传/信息变更为多用户批量生成的通知长期累积占库空间，需定时清理
    scheduler.add_job(clean_old_notifications, "cron", hour=18, minute=0, id="clean_notifications", replace_existing=True)
    # [新增] UTC 19:30 = 北京时间 03:30 清理超过3年的制度历史版本
    scheduler.add_job(clean_old_regulation_history, "cron", hour=19, minute=30, id="clean_reg_history", replace_existing=True)
    # [新增 2026-09-11] UTC 1:30 = 北京时间 09:30 离职保留期提醒：
    # 离职满 6 个月 → 档案仅保留统计，私信超管提醒删除登录账号（上班时间提醒，便于及时处理）
    scheduler.add_job(notify_resigned_accounts, "cron", hour=1, minute=30,
                      id="notify_resigned_accounts", replace_existing=True)
    # [修复/问题14] 每小时清理过期限流记录。
    # 限流状态已由进程内存字典改为数据库表，原 prune_ip_failures 不再存在，
    # 改为调用需要数据库会话的 prune_rate_limits。
    from app.services.auth_service import prune_rate_limits

    def _prune_rate_limits_job():
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            prune_rate_limits(db)
        except Exception as e:
            logger.warning(f"清理过期限流记录失败: {e}", exc_info=True)  # [修正 2026-09-19] ERROR → WARN（定时清理，可重跑）
        finally:
            db.close()

    scheduler.add_job(_prune_rate_limits_job, "interval", hours=1,
                      id="prune_rate_limits", replace_existing=True)

    scheduler.start()

    jobs = scheduler.get_jobs()
    job_info = ", ".join([f"{j.id}→{j.next_run_time.strftime('%H:%M')}" for j in jobs])
    logger.info(f"定时调度器已启动: {job_info}")


def stop_scheduler():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
