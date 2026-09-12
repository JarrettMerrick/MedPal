# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
串行任务队列模块

业务背景：
    备份（create_backup）和导出打包（_build_package_background）都是耗时操作，
    会长时间占用数据库连接或文件 I/O 资源。在 SQLite 单写锁模型下，同时运行多个此类
    操作可能导致其他正常读写请求排队超时。
    
    本模块提供一个全局串行锁，确保同一时间只有一个重量级后台任务在执行，
    其余任务排队等待。适用于 < 50 并发用户的中小型系统。

使用方式：
    from app.services.task_queue import run_serial
    run_serial(some_heavy_function, arg1, arg2)
"""

import logging
import threading

logger = logging.getLogger("task_queue")

# 全局串行锁 — 确保同一时间只有一个重量级操作在执行
_heavy_lock = threading.Lock()


def run_serial(task_func, *args, **kwargs):
    """在串行锁保护下执行任务，防止多个重量级操作并发。

    Args:
        task_func: 要执行的可调用对象
        *args: 传递给 task_func 的位置参数
        **kwargs: 传递给 task_func 的关键字参数

    Returns:
        task_func 的返回值
    """
    task_name = getattr(task_func, "__name__", str(task_func))
    logger.info("⏳ 排队等待串行锁: %s", task_name)
    with _heavy_lock:
        logger.info("▶ 开始执行串行任务: %s", task_name)
        try:
            return task_func(*args, **kwargs)
        except Exception:
            logger.error("✕ 串行任务失败: %s", task_name, exc_info=True)
            raise
        finally:
            logger.info("✓ 串行任务完成: %s", task_name)
