# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""功能开关路由（系统设置 → 功能开关）。

- `GET /api/public/features`   免登录：读取各功能启停状态，供前端菜单/入口按开关显隐；
- `GET /api/feature-settings`  需 system.config：设置页汇总（当前开关 + 功能元信息）。

设计说明：
- 保存复用现有 `PUT /api/system-config/{key}`（同样要求 system.config），不新增写端点；
- 开关是**单位级**控制，与角色级的 feature.* 权限点互为两层，两者都通过才放行；
- 接口层的强制校验统一在 `main.py` 通过 `include_router(dependencies=...)` 挂载，
  见 `require_feature_enabled`，避免逐个接口漏挂。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PERM_SYSTEM_CONFIG, get_current_user, has_permission
from app.models.user import User
from app.services.system_config_service import FEATURE_CONFIG_KEYS, get_feature_flags

router = APIRouter(tags=["功能开关"])

# 角色级门禁：所有功能开关共用**同一个**权限点（需求：合并为一个权限，命名为「功能开关」）。
# 早前按功能拆分的 feature.messages / feature.signage / feature.regulation 已废弃，
# 由 role_initializer 的合并迁移统一折算到本权限点。
FEATURE_ACCESS_PERMISSION = "feature.access"

# 功能元信息：设置页按此顺序渲染。
# 新增一个功能开关时，只需在此登记 + 在 system_config_service 里加配置 key，
# 前端设置页会自动多出一张卡片，无需改动前端（角色级门禁仍复用上面那一个权限点）。
FEATURE_META = [
    {
        "key": "messages",
        "config_key": FEATURE_CONFIG_KEYS["messages"],
        "label": "站内信",
        "applies_to": "左侧菜单「站内信」与顶部消息铃铛",
        "description": (
            "系统通知、私发与群发的统一消息中心。关闭后：菜单与铃铛入口隐藏，"
            "相关接口返回 403。历史消息数据保留，重新开启即可继续查看。"
        ),
    },
    {
        "key": "signage",
        "config_key": FEATURE_CONFIG_KEYS["signage"],
        "label": "标识平面与标识设置",
        "applies_to": "左侧菜单「标识平面」「标识设置」两个分组",
        "description": (
            "合并控制「标识平面」（标识总览 / 标识管理 / 标识标记 / 维修记录 / 标识预警 / 标识巡检）"
            "与「标识设置」（院区管理 / 平面设置 / 标识分类 / 供应商设置）。"
            "关闭后两个分组一并隐藏，相关接口返回 403。"
        ),
    },
    {
        "key": "regulation",
        "config_key": FEATURE_CONFIG_KEYS["regulation"],
        "label": "制度牌",
        "applies_to": "左侧菜单「制度管理」（含数据管理中的制度导出/导入模板）",
        "description": (
            "制度牌（制度管理）模块：制度列表、制度详情、版本历史与类别维护。"
            "关闭后：菜单入口隐藏，制度相关接口与「数据管理」中的制度导出/导入一并返回 403。"
            "已有制度数据不会删除，重新开启即可继续使用。"
        ),
    },
]


@router.get("/api/public/features")
def get_public_features(db: Session = Depends(get_db)):
    """公开特性开关（免登录）。

    仅暴露「各功能是否启用」这几个布尔值，不含任何敏感信息；
    目的是让前端在首屏（含登录页、强制改密页）即可决定菜单与入口的显隐，
    避免出现"先渲染全部菜单、再闪一下消失"的观感问题。
    """
    return get_feature_flags(db)


@router.get("/api/feature-settings")
def get_feature_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """功能开关设置页汇总（需系统配置权限）"""
    if not has_permission(current_user, PERM_SYSTEM_CONFIG):
        raise HTTPException(status_code=403, detail="权限不足")

    flags = get_feature_flags(db)
    return {
        # 角色级门禁：所有功能开关共用的同一个权限点（供设置页提示管理员前往「角色管理」授权）
        "permission": FEATURE_ACCESS_PERMISSION,
        "features": [
            {**item, "enabled": flags.get(item["key"], True)}
            for item in FEATURE_META
        ]
    }
