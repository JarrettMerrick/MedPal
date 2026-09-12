# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
院区-楼栋-楼层-区域 数据模式定义
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


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
    floor_number: int = Field(..., description="楼层号")
    floor_name: Optional[str] = Field(None, max_length=100, description="楼层名称")
    description: Optional[str] = Field(None, description="楼层描述")
    is_active: bool = Field(True, description="是否启用")


class FloorCreate(FloorBase):
    """创建楼层"""
    building_id: int = Field(..., description="所属楼栋ID")


class FloorUpdate(BaseModel):
    """更新楼层"""
    building_id: Optional[int] = Field(None, description="所属楼栋ID")
    floor_number: Optional[int] = Field(None, description="楼层号")
    floor_name: Optional[str] = Field(None, max_length=100, description="楼层名称")
    description: Optional[str] = Field(None, description="楼层描述")
    is_active: Optional[bool] = Field(None, description="是否启用")


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
    floor_number: int = Field(..., description="楼层号")
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