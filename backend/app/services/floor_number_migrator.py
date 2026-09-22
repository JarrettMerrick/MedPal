# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""楼层号格式迁移：把历史纯数字楼层号统一为字母编号（幂等）。

[新增 2026-09-17] 背景
    楼层号原为整数（1、2、-1，负数表示地下），新需求要求支持字母编号：
        F1 / F2 / F3 …（地上，F3 = 三层）
        B1 / B2 / B3 …（地下，B1 = 地下一层）
    `floors.floor_number` 字段类型已改为字符串。本模块负责把**存量数据**就地转换，
    并同步修正派生出去的楼层展示文本，保证新旧数据口径一致。

迁移项（全部幂等，可重复执行；仅转换明确匹配的旧格式，不误伤其它文本）：
    1) floors.floor_number：1 → F1、-1 → B1（0 或无法识别的值跳过并告警）
    2) signages.floor：旧展示文本 "3F-门诊层" → "F3-门诊层"
    3) floor_plans.floor：同上
    4) floor_plans.floor_code：旧编码 "-1" → "B1"（"F3" 这类新编码保持不变）

由 app.main 启动流程调用，单次执行只处理需要转换的行，转换完自动跳过。
"""

import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger("floor_migration")

# 旧展示文本前缀："3F"、"3F-门诊层"、"-1F"，要求其后是行尾或分隔符（避免误伤 "3F2" 这类文本）
_LEGACY_FLOOR_TEXT_RE = re.compile(r"^(-?\d+)F(?=$|[-—－_/·（(（])")
# 旧楼层编码：整个字符串就是数字（含负数），如 floor_plans.floor_code = "-1"
_LEGACY_FLOOR_CODE_RE = re.compile(r"^(-?\d+)$")
# 纯数字文本：早期版本可能直接存了楼层号数字
_PLAIN_NUMBER_RE = re.compile(r"^(-?\d+)$")


def _convert_legacy_floor_text(text: str | None) -> str | None:
    """旧展示文本 → 新格式；无需转换时返回 None。

    "3F-门诊层" → "F3-门诊层"、"3F" → "F3"、"-1F" → "B1"、"3" → "F3"
    """
    if not text:
        return None
    stripped = text.strip()
    matched = _LEGACY_FLOOR_TEXT_RE.match(stripped)
    if matched:
        n = int(matched.group(1))
        if n == 0:
            return None
        return f"{'B' if n < 0 else 'F'}{abs(n)}{stripped[matched.end():]}"
    if _PLAIN_NUMBER_RE.match(stripped):
        n = int(stripped)
        if n == 0:
            return None
        return f"{'B' if n < 0 else 'F'}{abs(n)}"
    return None


def _convert_legacy_floor_code(text: str | None) -> str | None:
    """旧楼层编码 → 新格式；无需转换时返回 None。

    "-1" → "B1"；已是 "F3"/"B1" 形态则返回 None（保持不变）。
    """
    if not text:
        return None
    matched = _LEGACY_FLOOR_CODE_RE.match(text.strip())
    if not matched:
        return None
    n = int(matched.group(1))
    if n == 0:
        return None
    return f"{'B' if n < 0 else 'F'}{abs(n)}"


def migrate_floor_number_format(db: Session) -> dict:
    """执行楼层号格式迁移（幂等）。返回各项修改计数。"""
    from app.models.campus import Floor
    from app.models.signage import Signage, FloorPlan
    from app.schemas.campus import normalize_floor_number

    stats = {
        "floors": 0,           # 楼层号：数字 → F/B 字母编号
        "signage_floor": 0,    # 标识的楼层展示文本
        "plan_floor": 0,       # 平面图的楼层展示文本
        "plan_floor_code": 0,  # 平面图的楼层编码
        "skipped_floors": 0,   # 无法识别的楼层号（保留原值，仅告警）
    }

    # 1) floors.floor_number：数字 → 字母编号
    # normalize_floor_number 对 "F3" 原样返回（不触发写入），
    # 对 "3" → "F3"、"-1" → "B1"、小写 "b1" → "B1" 均会转换。
    for floor in db.query(Floor).all():
        raw = floor.floor_number
        if raw is None:
            continue
        normalized = normalize_floor_number(str(raw))
        if not normalized:
            stats["skipped_floors"] += 1
            logger.warning("楼层号迁移跳过（无法识别）：floors.id=%s value=%r", floor.id, raw)
            continue
        if normalized != str(raw):
            floor.floor_number = normalized
            stats["floors"] += 1

    # 2) signages.floor：标识的楼层展示文本
    for signage in db.query(Signage).all():
        converted = _convert_legacy_floor_text(signage.floor)
        if converted:
            signage.floor = converted
            stats["signage_floor"] += 1

    # 3) floor_plans.floor / floor_code：平面图的楼层展示文本与编码
    for plan in db.query(FloorPlan).all():
        converted_floor = _convert_legacy_floor_text(plan.floor)
        if converted_floor:
            plan.floor = converted_floor
            stats["plan_floor"] += 1
        converted_code = _convert_legacy_floor_code(plan.floor_code)
        if converted_code:
            plan.floor_code = converted_code
            stats["plan_floor_code"] += 1

    changed = (
        stats["floors"] + stats["signage_floor"]
        + stats["plan_floor"] + stats["plan_floor_code"]
    )
    if changed:
        db.commit()
        logger.info("楼层号格式迁移完成：%s", stats)
    return stats
