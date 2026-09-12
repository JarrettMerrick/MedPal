# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PermissionOut(BaseModel):
    id: int
    name: str
    display_name: str
    category: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    department_scope: str = "own"      # own / managed / all
    work_type_scope: str = "all"       # all 或 "doctor,nurse,technician,admin"
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    department_scope: Optional[str] = None
    work_type_scope: Optional[str] = None
    permission_ids: Optional[list[int]] = None


class RoleOut(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    is_system: bool
    department_scope: str = "own"
    work_type_scope: str = "all"
    permissions: list[PermissionOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RoleListResponse(BaseModel):
    total: int
    items: list[RoleOut]
    page: int
    page_size: int


class PermissionCategoryOut(BaseModel):
    category: str
    category_label: str
    permissions: list[PermissionOut]
