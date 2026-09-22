# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""库结构同步：把现有数据库对齐到当前代码的模型定义。

[新增 2026-09-22] 起因是一次真实故障：

    用户恢复了一份**旧版本**的备份，那份库只有 24 张表（当前模型需要 50 张）。
    恢复流程只替换了数据文件，而建表（create_all）与自动补列**只在应用启动时执行** ——
    应用没有重启，于是登录时查询 `rate_limit_records`（登录限流表）直接抛
    `OperationalError: no such table`，被全局处理器包装成「500 服务器内部错误」。

    现象是"应用损坏、无法登录"，实际数据完好无损 —— 纯粹是**结构没对齐**。

本模块把"对齐结构"从"启动流程的一部分"变成**可随时调用的独立能力**，
让恢复备份、导入外部库等场景都能主动对齐，而不必依赖"记得重启应用"。

设计取舍：
  - **只做增量的加法**（建缺失的表、补缺失的列），绝不删表、删列、改类型 ——
    同步过程本身不能成为数据损失的原因；
  - 补列时若模型未给默认值且列不允许为空，则**跳过并告警**而不是强加一个
    可能错误的默认值（这与此前审计指出的 D-7 问题同源，此处选择保守）；
  - 任何单点失败都只记日志、不向上抛 —— 调用方（如恢复流程）不应因为
    "某张表补列失败"而回滚一次成功的恢复。
"""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _render_default(col) -> tuple[bool, str]:
    """尝试把模型列定义渲染为可用的 SQL 默认值。

    返回 (是否可安全补列, DEFAULT 子句或列类型占位)。

    只有**标量常量默认值**才认为安全；callable（如 default=utc_now）、
    server_default 之外的表达式一律拒绝 —— 因为无法在 ALTER 语句里
    表达"按函数生成"，强加一个固定值会把语义改错。
    """
    # 允许为空：补一个 NULL 即可，无风险
    if col.nullable:
        return True, "NULL"

    # 以下是 NOT NULL 列 —— 必须能给出一个有意义的默认值才敢补
    default = col.default
    if default is None:
        # NOT NULL 且模型未给默认值：补列时无法为存量行填值，ALTER 必然失败
        return False, ""

    # callable 默认值（如 default=utc_now）：无法在 ALTER 语句里表达
    # "按函数生成"，强加一个固定值会把语义改错（例如所有行都得到同一个时间戳）
    if getattr(default, "is_callable", False) or callable(getattr(default, "arg", None)):
        return False, ""

    arg = getattr(default, "arg", None)
    if arg is None:
        return False, ""

    # 标量常量：按类型渲染（注意 bool 要放在 int 之前判断，因为 bool 是 int 的子类）
    if isinstance(arg, bool):
        return True, "1" if arg else "0"
    if isinstance(arg, (int, float)):
        return True, str(arg)
    if isinstance(arg, str):
        return True, "'" + arg.replace("'", "''") + "'"
    return False, ""


def sync_schema() -> dict:
    """把数据库结构对齐到当前模型定义。返回统计信息。

    幂等：可重复调用；已存在的表与列不会被触碰。
    """
    stats = {
        "tables_before": 0,
        "tables_after": 0,
        "tables_created": [],
        "columns_added": [],
        "columns_skipped": [],
    }

    try:
        from app.database import Base, engine
        import app.models  # noqa: F401  确保所有模型都注册进 Base.metadata
    except Exception as e:
        logger.error("结构同步：加载模型失败", exc_info=True)
        stats["error"] = f"加载模型失败: {e}"
        return stats

    try:
        insp = inspect(engine)
        existing = set(insp.get_table_names())
        expected = set(Base.metadata.tables.keys())
        stats["tables_before"] = len(existing)

        missing_tables = sorted(expected - existing)

        # ── 1. 建缺失的表 ──
        # create_all 只创建不存在的表，对已有表完全跳过，因此不会影响存量数据
        if missing_tables:
            Base.metadata.create_all(bind=engine)
            stats["tables_created"] = missing_tables
            logger.warning(
                "结构同步：新建 %d 张缺失的表（原库来自较旧版本）: %s",
                len(missing_tables), missing_tables,
            )

        insp = inspect(engine)
        stats["tables_after"] = len(set(insp.get_table_names()))

        # ── 2. 补缺失的列 ──
        # 逐表比对"模型列"与"库中列"。只 ADD，不改类型、不删列。
        for tname in sorted(expected):
            try:
                db_cols = {c["name"] for c in insp.get_columns(tname)}
            except Exception:
                continue  # 表刚建出来但 inspector 缓存未更新等情况，跳过
            model_cols = Base.metadata.tables[tname].columns
            for col in model_cols:
                if col.name in db_cols:
                    continue
                # 新建的表不会有"缺列"，此处只针对**既有表**
                ok, default_sql = _render_default(col)
                if not ok:
                    stats["columns_skipped"].append(f"{tname}.{col.name}")
                    logger.warning(
                        "结构同步：跳过补列 %s.%s（模型未提供可静态表达的默认值；"
                        "该列不允许为空，强加默认值可能改变语义）—— 如有功能异常请人工处理",
                        tname, col.name,
                    )
                    continue

                try:
                    col_type = col.type.compile(dialect=engine.dialect)
                    nullable_sql = "" if col.nullable else " NOT NULL"
                    ddl = (
                        f"ALTER TABLE {tname} ADD COLUMN {col.name} "
                        f"{col_type}{nullable_sql} DEFAULT {default_sql}"
                    )
                    with engine.connect() as conn:
                        conn.execute(text(ddl))
                        conn.commit()
                    stats["columns_added"].append(f"{tname}.{col.name}")
                    logger.info("结构同步：已补列 %s.%s", tname, col.name)
                except Exception as e:
                    stats["columns_skipped"].append(f"{tname}.{col.name}")
                    logger.warning("结构同步：补列失败 %s.%s: %s", tname, col.name, e, exc_info=True)

        logger.info(
            "结构同步完成：表 %d → %d（新建 %d），补列 %d，跳过 %d",
            stats["tables_before"], stats["tables_after"],
            len(stats["tables_created"]), len(stats["columns_added"]),
            len(stats["columns_skipped"]),
        )
    except Exception as e:
        logger.error("结构同步失败（非致命，不影响调用方主流程）: %s", e, exc_info=True)
        stats["error"] = str(e)

    return stats
