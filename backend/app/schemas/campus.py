# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
院区-楼栋-楼层-区域 数据模式定义
"""

import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ==================== 楼层号规范 ====================
# [新增 2026-09-17] 楼层号由纯整数改为「字母前缀 + 数字」，支持字母编号：
#   地上 F1 / F2 / F3 …（F3 = 三层）
#   地下 B1 / B2 / B3 …（B1 = 地下一层）
# 输入兼容旧习惯写法（3 → F3、-1 → B1、f03 → F3），入库统一为规范值。
# 排序语义见 services/campus_service.floor_order_expr()（B 系列在前、越深越靠前）；
# 前端同一口径实现：frontend/src/utils/floor.ts
FLOOR_NUMBER_PATTERN = re.compile(r"^[BF][1-9]\d{0,2}$")
FLOOR_NUMBER_HINT = "楼层号格式：地上 F+层数（如 F3＝三层），地下 B+深度（如 B1＝地下一层）"


def normalize_floor_number(value) -> Optional[str]:
    """把多种输入写法规范化为标准楼层号；无法识别返回 None。

    与前端 utils/floor.ts 的 normalizeFloorNumber 保持同一口径：
    - 纯数字 / 负数：3 → F3，-1 → B1（0 不合法）
    - 带前缀且含多余前导零：F03 → F3、b1 → B1
    """
    if value is None:
        return None
    text = str(value).strip().upper().replace(" ", "")
    if not text:
        return None
    # 旧习惯：直接输入数字（3 = 三层），负数表示地下（-1 = 地下一层）
    if re.fullmatch(r"-?\d+", text):
        n = int(text)
        if n == 0 or abs(n) > 999:
            return None
        return f"{'B' if n < 0 else 'F'}{abs(n)}"
    matched = re.fullmatch(r"([BF])0*(\d+)", text)
    if matched:
        n = int(matched.group(2))
        if 1 <= n <= 999:
            return f"{matched.group(1)}{n}"
    return None


def coerce_floor_number_input(value):
    """[新增 2026-09-17] 入参类型兼容：把整数楼层号转成字符串，交给规范化函数处理。

    字段类型已由 int 改为 str，但以下来源仍可能传数字（Pydantic 的 str 类型
    会在校验阶段直接拒绝 int，导致兼容逻辑没有机会执行）：
      - 浏览器缓存的旧版前端（InputNumber 提交数字）
      - 运维/第三方脚本直接调用 API
    统一在此转换为字符串（3 → "3" → 后续规范化为 F3），避免 422。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(int(value))
    return value


# ==================== 院区 ====================

class CampusBase(BaseModel):
    """院区基础信息"""
    name: str = Field(..., max_length=100, description="院区名称")
    description: Optional[str] = Field(None, description="院区描述")
    address: Optional[str] = Field(None, max_length=200, description="院区地址")
    code: Optional[str] = Field(None, max_length=50, description="院区代号")
    is_active: bool = Field(True, description="是否启用")


class CampusCreate(CampusBase):
    """创建院区"""
    pass


class CampusUpdate(BaseModel):
    """更新院区"""
    name: Optional[str] = Field(None, max_length=100, description="院区名称")
    description: Optional[str] = Field(None, description="院区描述")
    address: Optional[str] = Field(None, max_length=200, description="院区地址")
    code: Optional[str] = Field(None, max_length=50, description="院区代号")
    is_active: Optional[bool] = Field(None, description="是否启用")


class CampusOut(CampusBase):
    """院区输出信息"""
    id: int = Field(..., description="院区ID")
    code: Optional[str] = Field(None, description="院区代号")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_by: Optional[str] = Field(None, description="更新人")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    building_count: int = Field(0, description="楼栋数量")

    class Config:
        from_attributes = True


# ==================== 楼栋 ====================

class BuildingBase(BaseModel):
    """楼栋基础信息"""
    name: str = Field(..., max_length=100, description="楼栋名称")
    building_number: str = Field(..., max_length=50, description="楼栋编号")
    description: Optional[str] = Field(None, description="楼栋描述")
    is_active: bool = Field(True, description="是否启用")


class BuildingCreate(BuildingBase):
    """创建楼栋"""
    campus_id: int = Field(..., description="所属院区ID")


class BuildingUpdate(BaseModel):
    """更新楼栋"""
    campus_id: Optional[int] = Field(None, description="所属院区ID")
    name: Optional[str] = Field(None, max_length=100, description="楼栋名称")
    building_number: Optional[str] = Field(None, max_length=50, description="楼栋编号")
    description: Optional[str] = Field(None, description="楼栋描述")
    is_active: Optional[bool] = Field(None, description="是否启用")


class BuildingOut(BuildingBase):
    """楼栋输出信息"""
    id: int = Field(..., description="楼栋ID")
    campus_id: int = Field(..., description="所属院区ID")
    campus_name: Optional[str] = Field(None, description="院区名称")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_by: Optional[str] = Field(None, description="更新人")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    floor_count: int = Field(0, description="楼层数量")

    class Config:
        from_attributes = True


# ==================== 楼层 ====================

class FloorBase(BaseModel):
    """楼层基础信息"""
    # [调整 2026-09-17] 由 int 改为 str：支持 B1（地下一层）/ F3（三层）等字母编号
    floor_number: str = Field(
        ..., max_length=20,
        description="楼层号：地上 F1/F2…（F3 = 三层）、地下 B1/B2…（B1 = 地下一层）",
    )
    floor_name: Optional[str] = Field(None, max_length=100, description="楼层名称")
    description: Optional[str] = Field(None, description="楼层描述")
    is_active: bool = Field(True, description="是否启用")

    @field_validator("floor_number", mode="before")
    @classmethod
    def _coerce_floor_number(cls, v):
        """[新增 2026-09-17] 入参兼容：数字 → 字符串（旧客户端 / 脚本调用）"""
        return coerce_floor_number_input(v)

    @field_validator("floor_number")
    @classmethod
    def _validate_floor_number(cls, v: str) -> str:
        """[新增 2026-09-17] 校验并规范化楼层号（3 → F3、-1 → B1、f03 → F3）"""
        normalized = normalize_floor_number(v)
        if not normalized:
            raise ValueError(FLOOR_NUMBER_HINT)
        return normalized


class FloorCreate(FloorBase):
    """创建楼层"""
    building_id: int = Field(..., description="所属楼栋ID")


class FloorUpdate(BaseModel):
    """更新楼层"""
    building_id: Optional[int] = Field(None, description="所属楼栋ID")
    # [调整 2026-09-17] 由 int 改为 str：支持字母编号（同 FloorBase）
    floor_number: Optional[str] = Field(
        None, max_length=20,
        description="楼层号：地上 F1/F2…（F3 = 三层）、地下 B1/B2…（B1 = 地下一层）",
    )
    floor_name: Optional[str] = Field(None, max_length=100, description="楼层名称")
    description: Optional[str] = Field(None, description="楼层描述")
    is_active: Optional[bool] = Field(None, description="是否启用")

    @field_validator("floor_number", mode="before")
    @classmethod
    def _coerce_floor_number(cls, v):
        """[新增 2026-09-17] 入参兼容：数字 → 字符串（旧客户端 / 脚本调用）"""
        return coerce_floor_number_input(v)

    @field_validator("floor_number")
    @classmethod
    def _validate_floor_number(cls, v):
        """[新增 2026-09-17] 更新时同样规范化楼层号；未传（None）表示不修改该字段"""
        if v is None:
            return v
        normalized = normalize_floor_number(v)
        if not normalized:
            raise ValueError(FLOOR_NUMBER_HINT)
        return normalized


class FloorOut(FloorBase):
    """楼层输出信息"""
    id: int = Field(..., description="楼层ID")
    building_id: int = Field(..., description="所属楼栋ID")
    building_name: Optional[str] = Field(None, description="楼栋名称")
    campus_id: Optional[int] = Field(None, description="所属院区ID")
    campus_name: Optional[str] = Field(None, description="院区名称")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_by: Optional[str] = Field(None, description="更新人")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    area_count: int = Field(0, description="区域数量")

    class Config:
        from_attributes = True


# ==================== 区域 ====================

class AreaBase(BaseModel):
    """区域基础信息"""
    name: str = Field(..., max_length=100, description="区域名称")
    area_type: str = Field("merged", description="区域类型: east/west/merged")
    description: Optional[str] = Field(None, description="区域描述")
    is_active: bool = Field(True, description="是否启用")


class AreaCreate(AreaBase):
    """创建区域"""
    floor_id: int = Field(..., description="所属楼层ID")


class AreaUpdate(BaseModel):
    """更新区域"""
    floor_id: Optional[int] = Field(None, description="所属楼层ID")
    name: Optional[str] = Field(None, max_length=100, description="区域名称")
    area_type: Optional[str] = Field(None, description="区域类型: east/west/merged")
    description: Optional[str] = Field(None, description="区域描述")
    is_active: Optional[bool] = Field(None, description="是否启用")


class AreaOut(AreaBase):
    """区域输出信息"""
    id: int = Field(..., description="区域ID")
    floor_id: int = Field(..., description="所属楼层ID")
    floor_name: Optional[str] = Field(None, description="楼层名称")
    building_id: Optional[int] = Field(None, description="所属楼栋ID")
    building_name: Optional[str] = Field(None, description="楼栋名称")
    campus_id: Optional[int] = Field(None, description="所属院区ID")
    campus_name: Optional[str] = Field(None, description="院区名称")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_by: Optional[str] = Field(None, description="更新人")
    updated_at: Optional[datetime] = Field(None, description="更新时间")

    class Config:
        from_attributes = True


# ==================== 层级结构 ====================

class CampusTreeNode(BaseModel):
    """院区树形结构节点"""
    id: int = Field(..., description="院区ID")
    name: str = Field(..., description="院区名称")
    children: List["BuildingTreeNode"] = Field(default_factory=list, description="楼栋列表")


class BuildingTreeNode(BaseModel):
    """楼栋树形结构节点"""
    id: int = Field(..., description="楼栋ID")
    name: str = Field(..., description="楼栋名称")
    building_number: str = Field(..., description="楼栋编号")
    children: List["FloorTreeNode"] = Field(default_factory=list, description="楼层列表")


class FloorTreeNode(BaseModel):
    """楼层树形结构节点"""
    id: int = Field(..., description="楼层ID")
    # [调整 2026-09-17] 与 FloorBase 保持一致，改为字母编号字符串
    floor_number: str = Field(..., description="楼层号：F1/F2…（地上）、B1/B2…（地下）")
    floor_name: Optional[str] = Field(None, description="楼层名称")
    children: List["AreaTreeNode"] = Field(default_factory=list, description="区域列表")


class AreaTreeNode(BaseModel):
    """区域树形结构节点"""
    id: int = Field(..., description="区域ID")
    name: str = Field(..., description="区域名称")
    area_type: str = Field(..., description="区域类型")


# 更新树形结构的前向引用
CampusTreeNode.model_rebuild()
BuildingTreeNode.model_rebuild()
FloorTreeNode.model_rebuild()