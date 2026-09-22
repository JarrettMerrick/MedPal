# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""导出临时文件的管理（目录定义 + 残留清理）。

[新增 2026-09-21 / 代码质量审计 Q-2] 从 routers/data_io.py 抽出。

**为什么要抽**：本模块的内容原先定义在**路由层**（routers/data_io.py），
却被**服务层**（services/backup_service.py 的定时任务）和 main.py 的启动流程导入。
依赖方向被反转，构成隐式循环依赖 —— 为了绕开 ImportError，
backup_service.py 只能把导入写在**函数体内**（`from app.routers.data_io import ...`）。

后果不只是"不优雅"：
  1. 任何拆包/调整路由结构的重构都会让这条隐式依赖突然断裂；
  2. 函数内导入使依赖关系在模块顶部不可见，静态分析工具与 IDE 都难以发现；
  3. 路由模块的导入会连带加载 FastAPI 路由、Pydantic 模型等一堆无关内容，
     而定时任务只需要一个目录路径和清理函数。

抽出后依赖方向恢复为 router → service，backup_service.py 与 main.py 均可
在模块顶部正常导入。

本模块的职责边界：**只管"导出产物的落地目录"与"过期产物的清理"**，
不涉及任何导出内容的生成逻辑（那部分仍在 data_io.py）。
"""

import logging
import time
from pathlib import Path

from app.config import DATA_ROOT

logger = logging.getLogger(__name__)

# [改进/1.0.9] 导出临时文件专用目录，便于启动时统一清理残留
TEMP_EXPORT_DIR: Path = DATA_ROOT / "temp_exports"

# 残留判定阈值：超过该秒数未被动过的临时文件视为"上次运行遗留"。
# 取值 1 小时：远大于任何正常导出的耗时（秒级），
# 又能保证崩溃重启后一小时内即可回收磁盘。
STALE_TEMP_FILE_AGE_SECONDS = 3600


def ensure_temp_export_dir() -> None:
    """确保临时导出目录存在（幂等）。"""
    TEMP_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_stale_temp_files() -> None:
    """清理超过 1 小时的残留临时导出文件。

    [改进/1.0.9] 正常流程下 BackgroundTasks 会在响应发送后删除临时文件，
    但以下场景会导致残留：
      - 服务器崩溃/重启（BackgroundTasks 未执行）
      - 客户端提前断开连接（FileResponse 未完成传输）
      - 文件系统只读（unlink 失败）

    因此除了在响应末尾清理，还需要在**应用启动时**兜底清一次
    （由 main.py 的启动流程调用）。
    """
    ensure_temp_export_dir()
    cleaned_count = 0
    try:
        for f in TEMP_EXPORT_DIR.iterdir():
            if not f.is_file() or f.suffix not in (".xlsx", ".zip"):
                continue
            try:
                age = time.time() - f.stat().st_mtime
                if age > STALE_TEMP_FILE_AGE_SECONDS:
                    size = f.stat().st_size
                    f.unlink()
                    cleaned_count += 1
                    # 循环内逐条用 debug，汇总用 info（符合日志规范）
                    logger.debug(
                        "清理残留临时文件: %s (%s bytes, 存留 %.0f 分钟)",
                        f.name, size, age / 60,
                    )
            except OSError as e:
                logger.warning("清理残留临时文件失败 %s: %s", f.name, e, exc_info=True)
        if cleaned_count:
            logger.info("共清理 %d 个残留临时导出文件", cleaned_count)
    except Exception as e:
        logger.warning("扫描临时导出目录失败（非致命）: %s", e, exc_info=True)
