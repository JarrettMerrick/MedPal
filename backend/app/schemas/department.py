# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SpecialtyBase(BaseModel):
    name: str
    detail: Optional[str] = ""
    sort_order: int = 0


class SpecialtyCreate(SpecialtyBase):
    pass


class SpecialtyUpdate(SpecialtyBase):
    id: Optional[int] = None


class SpecialtyImageOut(BaseModel):
    id: int
    specialty_id: int
    image_url: str
    caption: Optional[str] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class SpecialtyImageUpdate(BaseModel):
    caption: Optional[str] = None


class SpecialtyOut(SpecialtyBase):
    id: int
    department_id: int
    images: list[SpecialtyImageOut] = []

    model_config = {"from_attributes": True}


# ==================== 设备相关模型 ====================

class EquipmentBase(BaseModel):
    name: str
    model: Optional[str] = ""
    function_description: Optional[str] = ""
    features: Optional[str] = ""
    sort_order: int = 0


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentUpdate(EquipmentBase):
    id: Optional[int] = None


class EquipmentImageOut(BaseModel):
    id: int
    equipment_id: int
    image_url: str
    caption: Optional[str] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class EquipmentImageUpdate(BaseModel):
    caption: Optional[str] = None


class EquipmentOut(EquipmentBase):
    id: int
    department_id: int
    images: list[EquipmentImageOut] = []

    model_config = {"from_attributes": True}


class DepartmentBase(BaseModel):
    name: str
    description: Optional[str] = ""


class DepartmentCreate(DepartmentBase):
    category: str = "临床专科"
    # [修复 2026-09-01] 新增 allowed_work_types 字段，支持混合科室配置
    allowed_work_types: Optional[str] = None
    specialties: list[SpecialtyCreate] = []
    equipments: list[EquipmentCreate] = []


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    group_photo: Optional[str] = None
    # [修复 2026-09-01] 新增 allowed_work_types 字段，支持混合科室配置
    allowed_work_types: Optional[str] = None
    specialties: Optional[list[SpecialtyUpdate]] = None
    equipments: Optional[list[EquipmentUpdate]] = None


class DepartmentOut(DepartmentBase):
    id: int
    category: str = "临床专科"
    group_photo: Optional[str] = None
    # [修复 2026-09-01] 新增 allowed_work_types 字段，支持混合科室配置
    allowed_work_types: Optional[str] = None
    specialties: list[SpecialtyOut] = []
    equipments: list[EquipmentOut] = []
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DepartmentListOut(BaseModel):
    items: list[DepartmentOut]
    total: int
